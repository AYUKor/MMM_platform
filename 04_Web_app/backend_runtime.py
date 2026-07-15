"""Preflight and launch the local X5 MMM backend from one versioned config."""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping


WEB_APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = WEB_APP_DIR.parent
PYMC_CODE_DIR = PROJECT_ROOT / "02_Code" / "01_PyMC"
for entry in (WEB_APP_DIR, PYMC_CODE_DIR):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from api.http_smoke import HttpSmokeApplication, HttpSmokeSettings, serve  # noqa: E402
from mmm_core.model_registry import resolve_channel  # noqa: E402
from services.product_api_service import (  # noqa: E402
    RuntimeRetentionManager,
    build_model_passport,
)


CONFIG_SCHEMA_VERSION = "1.1.0"
SUPPORTED_CONFIG_SCHEMA_VERSIONS = {"1.0.0", CONFIG_SCHEMA_VERSION}
ENV_PUBLIC_BASE_URL = "MMM_BACKEND_PUBLIC_BASE_URL"
ENV_ALLOWED_ORIGINS = "MMM_BACKEND_ALLOWED_ORIGINS"
ENV_PORT = "MMM_BACKEND_PORT"
ENV_RETENTION_DAYS = "MMM_BACKEND_RETENTION_DAYS"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Backend runtime config must be a JSON object")
    return payload


def _config_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _project_path(project_root: Path, value: Any, field_name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty path")
    candidate = Path(value).expanduser()
    return (candidate if candidate.is_absolute() else project_root / candidate).resolve()


def _positive_number(value: Any, field_name: str) -> float:
    number = float(value)
    if number <= 0:
        raise ValueError(f"{field_name} must be positive")
    return number


def apply_environment_overrides(
    config: Mapping[str, Any],
    environ: Mapping[str, str],
) -> dict[str, Any]:
    """Apply non-secret deployment overrides before hashing the effective config."""

    effective = copy.deepcopy(dict(config))
    server = effective.setdefault("server", {})
    retention = effective.setdefault("retention", {})
    if not isinstance(server, dict) or not isinstance(retention, dict):
        raise ValueError("server and retention config sections must be objects")
    if environ.get(ENV_PUBLIC_BASE_URL):
        server["public_base_url"] = environ[ENV_PUBLIC_BASE_URL].strip()
    if environ.get(ENV_ALLOWED_ORIGINS):
        origins = [
            value.strip()
            for value in environ[ENV_ALLOWED_ORIGINS].split(",")
            if value.strip()
        ]
        if not origins:
            raise ValueError(f"{ENV_ALLOWED_ORIGINS} must contain at least one origin")
        server["allowed_origins"] = origins
    if environ.get(ENV_PORT):
        server["port"] = int(environ[ENV_PORT])
    if environ.get(ENV_RETENTION_DAYS):
        retention["days"] = int(environ[ENV_RETENTION_DAYS])
    return effective


def build_settings(
    config: Mapping[str, Any],
    *,
    project_root: Path,
) -> tuple[HttpSmokeSettings, str, int]:
    schema_version = str(config.get("schema_version") or "")
    if schema_version not in SUPPORTED_CONFIG_SCHEMA_VERSIONS:
        raise ValueError(f"Unsupported backend config schema: {config.get('schema_version')!r}")
    server = dict(config.get("server") or {})
    paths = dict(config.get("paths") or {})
    model = dict(config.get("model") or {})
    worker = dict(config.get("worker") or {})
    retention = dict(config.get("retention") or {})
    host = str(server.get("host") or "127.0.0.1")
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("Local backend may bind only to localhost")
    port = int(server.get("port") or 8765)
    if not 1 <= port <= 65535:
        raise ValueError("server.port must be between 1 and 65535")
    allowed_origins = tuple(
        str(value)
        for value in server.get(
            "allowed_origins",
            [
                "http://localhost:4173",
                "http://127.0.0.1:4173",
                "http://localhost:5173",
                "http://127.0.0.1:5173",
            ],
        )
    )
    python_value = worker.get("python_executable")
    python_executable = (
        Path(sys.executable).resolve()
        if python_value in {None, ""}
        else _project_path(project_root, python_value, "worker.python_executable")
    )
    settings = HttpSmokeSettings(
        state_root=_project_path(project_root, paths.get("state_root"), "paths.state_root"),
        runtime_root=_project_path(project_root, paths.get("runtime_root"), "paths.runtime_root"),
        artifact_root=_project_path(project_root, paths.get("artifact_root"), "paths.artifact_root"),
        project_root=project_root,
        python_executable=python_executable,
        registry_root=_project_path(project_root, paths.get("registry_root"), "paths.registry_root"),
        registry_channel=str(model.get("registry_channel") or "preprod"),
        expected_package_id=str(model.get("expected_package_id") or ""),
        model_verification_mode=str(
            model.get("verification_mode") or "full_lineage"
        ),
        optimizer_policy_path=_project_path(
            project_root,
            paths.get("optimizer_policy_path"),
            "paths.optimizer_policy_path",
        ),
        business_policy_path=_project_path(
            project_root,
            paths.get("business_policy_path"),
            "paths.business_policy_path",
        ),
        timeout_seconds=_positive_number(
            worker.get("timeout_seconds", 7200),
            "worker.timeout_seconds",
        ),
        max_workers=int(worker.get("max_workers", 1)),
        max_upload_bytes=int(worker.get("max_upload_mb", 50)) * 1024 * 1024,
        config_schema_version=schema_version,
        deployment_profile=str(server.get("deployment_profile") or "local_development"),
        public_base_url=(
            str(server["public_base_url"]).rstrip("/")
            if server.get("public_base_url")
            else None
        ),
        access_control_mode=str(server.get("access_control_mode") or "local_only"),
        retention_days=int(retention.get("days", 30)),
        allowed_origins=allowed_origins,
    )
    settings.validate()
    return settings, host, port


def preflight(
    settings: HttpSmokeSettings,
    *,
    config_sha256: str,
) -> dict[str, Any]:
    required_files = (
        settings.python_executable,
        settings.optimizer_policy_path,
        settings.business_policy_path,
        settings.project_root / "02_Code" / "02_Budget_optimizer" / "budget_optimizer.py",
    )
    missing = [str(path) for path in required_files if path is None or not Path(path).is_file()]
    if missing:
        raise FileNotFoundError(f"Local backend preflight is missing required files: {missing}")
    if not settings.expected_package_id:
        raise ValueError("model.expected_package_id must pin one immutable package")
    resolved = resolve_channel(
        settings.registry_channel,
        expected_package_id=settings.expected_package_id,
        registry_root=settings.registry_root,
        verification_mode=settings.model_verification_mode,
    )
    actual_package_id = str(resolved.get("package_id") or "")
    if actual_package_id != settings.expected_package_id:
        raise ValueError(
            "Registry channel/package mismatch: "
            f"expected={settings.expected_package_id}, actual={actual_package_id}"
        )
    model_passport = build_model_passport(
        resolved,
        project_root=settings.project_root,
        deployment_profile=settings.deployment_profile,
    )
    git_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=settings.project_root,
        text=True,
    ).strip()
    return {
        "status": "ready",
        "mode": settings.deployment_profile,
        "config_schema_version": settings.config_schema_version,
        "config_sha256": config_sha256,
        "package_id": actual_package_id,
        "package_fingerprint": resolved["registration"]["package_input_fingerprint"],
        "registry_channel": settings.registry_channel,
        "model_verification_mode": settings.model_verification_mode,
        "source_panel_status": resolved["verified"].get("source_panel_status"),
        "inventory_files_n": resolved["verified"]["inventory_files_n"],
        "git_commit": git_commit,
        "python_version": sys.version.split()[0],
        "model_passport": model_passport,
    }


@contextmanager
def _single_instance_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(
                "Another local backend already owns this state directory"
            ) from exc
        handle.seek(0)
        handle.truncate()
        handle.write(f"pid={os.getpid()}\n")
        handle.flush()
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write_runtime_card(
    settings: HttpSmokeSettings,
    preflight_result: Mapping[str, Any],
    *,
    host: str,
    port: int,
) -> None:
    settings.runtime_root.mkdir(parents=True, exist_ok=True)
    card = {
        **dict(preflight_result),
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
        "url": f"http://{host}:{port}",
        "paths": {
            key: str(value)
            for key, value in asdict(settings).items()
            if key in {"state_root", "runtime_root", "artifact_root", "registry_root"}
        },
    }
    target = settings.runtime_root / "backend_runtime_card.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)


def _console_preflight(preflight_result: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        key: value
        for key, value in preflight_result.items()
        if key != "model_passport"
    }
    passport = dict(preflight_result.get("model_passport") or {})
    coverage = dict(passport.get("coverage") or {})
    validation = dict(passport.get("validation") or {})
    payload["model_passport_summary"] = {
        "contract_name": passport.get("contract_name"),
        "capability_cells_n": coverage.get("capability_cells_n"),
        "historical_replay": dict(validation.get("historical_replay") or {}).get("status"),
        "sealed_oot": dict(validation.get("sealed_oot") or {}).get("status"),
    }
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check-only", action="store_true")
    action.add_argument("--retention-report", action="store_true")
    action.add_argument("--apply-retention", action="store_true")
    args = parser.parse_args(argv)
    project_root = args.project_root.expanduser().resolve()
    config = apply_environment_overrides(
        _read_json(args.config.expanduser().resolve()),
        os.environ,
    )
    config_sha = _config_sha256(config)
    settings, host, port = build_settings(config, project_root=project_root)
    if args.retention_report or args.apply_retention:
        manager = RuntimeRetentionManager(
            settings.state_root,
            settings.runtime_root,
            settings.artifact_root,
        )
        plan = manager.plan(settings.retention_days)
        if args.retention_report:
            print(json.dumps({"status": "dry_run", **plan.to_dict()}, ensure_ascii=False, indent=2))
            return 0
        lock_path = settings.state_root.parent / "backend.lock"
        with _single_instance_lock(lock_path):
            result = manager.apply(plan)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    preflight_result = preflight(settings, config_sha256=config_sha)
    if args.check_only:
        print(json.dumps(preflight_result, ensure_ascii=False, indent=2), flush=True)
        return 0
    lock_path = settings.state_root.parent / "backend.lock"
    with _single_instance_lock(lock_path):
        application = HttpSmokeApplication(
            settings,
            model_passport=preflight_result["model_passport"],
        )
        _write_runtime_card(
            settings,
            {**preflight_result, "recovery": application.recovery_summary},
            host=host,
            port=port,
        )
        print(
            json.dumps(
                {
                    **_console_preflight(preflight_result),
                    "status": "starting",
                    "url": f"http://{host}:{port}",
                    "pid": os.getpid(),
                    "recovery": application.recovery_summary,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        try:
            serve(application, host, port)
        except KeyboardInterrupt:
            print(json.dumps({"status": "stopped", "reason": "keyboard_interrupt"}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
