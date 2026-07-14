"""Content-addressed registry for immutable X5 MMM model packages."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .io import project_root, read_json, resolve_path, write_json
from .model_package import sha256_file
from .model_package_reader import ModelPackage


REGISTRY_SCHEMA_VERSION = "1.0.0"
MIN_PACKAGE_SCHEMA = (0, 3, 0)
CORE_INVENTORY_FILES = [
    "model_manifest.json",
    "run_config.json",
    "capability_matrix.csv",
    "risk_registry.csv",
    "gate_policy.json",
    "gate_results.csv",
    "posterior_index.json",
]
OPTIONAL_SERVING_FILES = [
    "fit_design_metadata.json",
    "fit_design_media_scales.csv",
    "fit_design_media_scales_exact.csv",
    "fit_design_control_scalers.csv",
    "fit_design_row_index.parquet",
    "historical_support_bounds.csv",
    "historical_campaign_support_bounds.csv",
    "source_geo_aliases.csv",
    "target_denominator_metadata.csv",
    "adstock_warm_start.csv",
    "oot_validation.json",
    "historical_replay_validation.json",
    "model_fit_card.json",
]


def default_registry_root() -> Path:
    return project_root() / "03_Outputs/01_PyMC_outputs/00_Model_registry"


def _version_tuple(value: str) -> tuple[int, int, int]:
    parts = str(value).split(".")
    try:
        numbers = tuple(int(part) for part in parts[:3])
    except ValueError as exc:
        raise ValueError(f"Invalid package schema version: {value!r}") from exc
    return (numbers + (0, 0, 0))[:3]


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _relative_or_absolute(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root().resolve()))
    except ValueError:
        return str(path.resolve())


def _resolve_recorded_path(value: str) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else project_root() / candidate


def _atomic_write_json(path: Path, payload: dict[str, Any], *, overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise FileExistsError(f"Immutable registry artifact already exists: {path}")
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    if temp.exists():
        raise FileExistsError(f"Registry temporary artifact already exists: {temp}")
    try:
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


@contextmanager
def _registry_lock(registry_root: Path) -> Iterator[None]:
    registry_root.mkdir(parents=True, exist_ok=True)
    lock_path = registry_root / "registry.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _inventory(run_dir: Path) -> dict[str, str]:
    files: list[Path] = []
    for name in CORE_INVENTORY_FILES:
        path = run_dir / name
        if not path.exists():
            raise FileNotFoundError(f"Model registration is missing required artifact: {path}")
        files.append(path)
    files.extend(path for name in OPTIONAL_SERVING_FILES if (path := run_dir / name).exists())
    files.extend(sorted(run_dir.glob("posterior_*.nc")))
    files.extend(sorted(run_dir.glob("fit_contract_*.json")))
    files.extend(sorted(run_dir.glob("fit_transform_*.json")))
    return {path.name: sha256_file(path) for path in files}


def _registration_payload(run_dir: Path, *, registered_by: str, reason: str) -> dict[str, Any]:
    package = ModelPackage.from_run_dir(run_dir, require_posterior_ready=True, validate_hash=True)
    manifest = package.manifest
    schema = str(manifest.get("package_schema_version") or "0.0.0")
    if _version_tuple(schema) < MIN_PACKAGE_SCHEMA:
        raise ValueError(f"Legacy package schema {schema} cannot be registered; minimum is 0.3.0")
    run_config = read_json(run_dir / "run_config.json", {}) or {}
    panel_raw = run_config.get("panel_path") or manifest.get("panel_path")
    if not panel_raw:
        raise ValueError("Model package has no panel path")
    panel_path = resolve_path(panel_raw)
    if not panel_path.exists():
        raise FileNotFoundError(f"Registered model panel is missing: {panel_path}")
    inventory = _inventory(run_dir)
    package_fingerprint = str(manifest.get("package_input_fingerprint") or "")
    if not package_fingerprint:
        raise ValueError("Model package has no package_input_fingerprint")
    panel_sha256 = sha256_file(panel_path)
    package_id = f"pkg_{package_fingerprint[:16]}_{panel_sha256[:16]}"
    payload = {
        "registry_schema_version": REGISTRY_SCHEMA_VERSION,
        "package_id": package_id,
        "model_run_id": manifest.get("model_run_id"),
        "run_dir": _relative_or_absolute(run_dir),
        "package_input_fingerprint": package_fingerprint,
        "package_schema_version": schema,
        "gate_policy_version": manifest.get("gate_policy_version"),
        "package_stage": manifest.get("package_stage"),
        "activation_status_at_registration": manifest.get("activation_status"),
        "production_blockers_at_registration": list(manifest.get("production_blockers") or []),
        "panel": {
            "path": _relative_or_absolute(panel_path),
            "sha256": panel_sha256,
            "size_bytes": panel_path.stat().st_size,
        },
        "inventory_sha256": inventory,
        "registered_at_utc": datetime.now(timezone.utc).isoformat(),
        "registered_by": registered_by.strip(),
        "reason": reason.strip(),
    }
    if not payload["registered_by"] or not payload["reason"]:
        raise ValueError("Registration requires non-empty registered_by and reason")
    immutable = dict(payload)
    immutable.pop("registered_at_utc")
    immutable.pop("registered_by")
    immutable.pop("reason")
    payload["registration_content_sha256"] = _canonical_hash(immutable)
    return payload


def register_model(
    run_dir: str | Path,
    *,
    registered_by: str,
    reason: str,
    registry_root: str | Path | None = None,
) -> dict[str, Any]:
    run_dir = resolve_path(run_dir)
    root = resolve_path(registry_root) if registry_root else default_registry_root()
    payload = _registration_payload(run_dir, registered_by=registered_by, reason=reason)
    path = root / "registrations" / f"{payload['package_id']}.json"
    with _registry_lock(root):
        if path.exists():
            existing = read_json(path) or {}
            if existing.get("registration_content_sha256") != payload["registration_content_sha256"]:
                raise ValueError(f"Package id collision or mutated registration: {payload['package_id']}")
            return existing
        _atomic_write_json(path, payload, overwrite=False)
    return payload


def load_registration(package_id: str, registry_root: str | Path | None = None) -> dict[str, Any]:
    root = resolve_path(registry_root) if registry_root else default_registry_root()
    path = root / "registrations" / f"{package_id}.json"
    registration = read_json(path)
    if not isinstance(registration, dict):
        raise FileNotFoundError(f"Unknown registry package: {package_id}")
    return registration


def verify_registration(package_id: str, registry_root: str | Path | None = None) -> dict[str, Any]:
    registration = load_registration(package_id, registry_root)
    run_dir = _resolve_recorded_path(registration["run_dir"])
    panel_path = _resolve_recorded_path(registration["panel"]["path"])
    if not run_dir.exists() or not panel_path.exists():
        raise FileNotFoundError("Registered run directory or panel is missing")
    current_inventory = _inventory(run_dir)
    if current_inventory != registration["inventory_sha256"]:
        expected = registration["inventory_sha256"]
        changed = sorted(
            name
            for name in set(expected) | set(current_inventory)
            if expected.get(name) != current_inventory.get(name)
        )
        raise ValueError(f"Registered package was mutated after registration: {changed}")
    panel_sha256 = sha256_file(panel_path)
    if panel_sha256 != registration["panel"]["sha256"]:
        raise ValueError("Registered panel hash mismatch")
    ModelPackage.from_run_dir(run_dir, require_posterior_ready=True, validate_hash=True)
    return {
        "status": "verified",
        "package_id": package_id,
        "run_dir": str(run_dir),
        "panel_sha256": panel_sha256,
        "inventory_files_n": len(current_inventory),
        "registration_content_sha256": registration["registration_content_sha256"],
    }


def list_registrations(registry_root: str | Path | None = None) -> list[dict[str, Any]]:
    root = resolve_path(registry_root) if registry_root else default_registry_root()
    return [read_json(path) for path in sorted((root / "registrations").glob("*.json"))]


def history(registry_root: str | Path | None = None) -> list[dict[str, Any]]:
    root = resolve_path(registry_root) if registry_root else default_registry_root()
    events = [read_json(path) for path in sorted((root / "events").glob("*.json"))]
    return sorted(events, key=lambda event: event.get("generated_at_utc", ""))


def _channel_pointer(root: Path, channel: str) -> dict[str, Any] | None:
    if channel not in {"preprod", "production"}:
        raise ValueError("Registry channel must be preprod or production")
    value = read_json(root / "channels" / f"{channel}.json")
    return value if isinstance(value, dict) else None


def _assert_expected_current(pointer: dict[str, Any] | None, expected_current: str) -> None:
    current = pointer.get("package_id") if pointer else None
    expected = None if expected_current.lower() == "none" else expected_current
    if current != expected:
        raise ValueError(f"Registry compare-and-swap failed: expected={expected!r}, current={current!r}")


def _assert_production_eligible(registration: dict[str, Any]) -> None:
    if registration.get("activation_status_at_registration") != "production_ready":
        raise ValueError("Production activation requires a production_ready package registration")
    if registration.get("production_blockers_at_registration"):
        raise ValueError("Production activation requires zero package blockers")
    run_dir = _resolve_recorded_path(registration["run_dir"])
    oot = read_json(run_dir / "oot_validation.json", {}) or {}
    replay = read_json(run_dir / "historical_replay_validation.json", {}) or {}
    if oot.get("status") != "passed" or not oot.get("activation_eligible"):
        raise ValueError("Production activation requires passed sealed OOT evidence")
    if replay.get("status") != "passed":
        raise ValueError("Production activation requires passed historical replay evidence")
    for name, evidence in [("OOT", oot), ("historical replay", replay)]:
        binding = evidence.get("binding") or {}
        if binding.get("package_input_fingerprint") != registration.get("package_input_fingerprint"):
            raise ValueError(f"{name} evidence is not bound to the registered package fingerprint")


def _event_payload(
    *,
    action: str,
    channel: str,
    package_id: str,
    previous_package_id: str | None,
    actor: str,
    reason: str,
    registration: dict[str, Any],
) -> dict[str, Any]:
    generated = datetime.now(timezone.utc).isoformat()
    base = {
        "registry_schema_version": REGISTRY_SCHEMA_VERSION,
        "action": action,
        "channel": channel,
        "package_id": package_id,
        "previous_package_id": previous_package_id,
        "actor": actor.strip(),
        "reason": reason.strip(),
        "generated_at_utc": generated,
        "registration_content_sha256": registration["registration_content_sha256"],
    }
    if not base["actor"] or not base["reason"]:
        raise ValueError("Activation event requires non-empty actor and reason")
    base["event_id"] = f"evt_{generated.replace(':', '').replace('-', '').replace('.', '')}_{_canonical_hash(base)[:12]}"
    return base


def activate_model(
    package_id: str,
    *,
    channel: str,
    expected_current: str,
    approved_by: str,
    reason: str,
    registry_root: str | Path | None = None,
) -> dict[str, Any]:
    root = resolve_path(registry_root) if registry_root else default_registry_root()
    registration = load_registration(package_id, root)
    verify_registration(package_id, root)
    if channel == "production":
        _assert_production_eligible(registration)
    elif registration.get("package_stage") != "posterior_ready":
        raise ValueError("Preprod activation requires posterior_ready package stage")
    with _registry_lock(root):
        pointer = _channel_pointer(root, channel)
        _assert_expected_current(pointer, expected_current)
        previous = pointer.get("package_id") if pointer else None
        event = _event_payload(
            action="activate",
            channel=channel,
            package_id=package_id,
            previous_package_id=previous,
            actor=approved_by,
            reason=reason,
            registration=registration,
        )
        _atomic_write_json(root / "events" / f"{event['event_id']}.json", event, overwrite=False)
        channel_payload = {
            "registry_schema_version": REGISTRY_SCHEMA_VERSION,
            "channel": channel,
            "package_id": package_id,
            "event_id": event["event_id"],
            "updated_at_utc": event["generated_at_utc"],
            "run_dir": registration["run_dir"],
            "registration_content_sha256": registration["registration_content_sha256"],
        }
        _atomic_write_json(root / "channels" / f"{channel}.json", channel_payload, overwrite=True)
    return event


def rollback_model(
    to_package_id: str,
    *,
    expected_current: str,
    approved_by: str,
    reason: str,
    registry_root: str | Path | None = None,
) -> dict[str, Any]:
    root = resolve_path(registry_root) if registry_root else default_registry_root()
    prior_production = {
        event.get("package_id")
        for event in history(root)
        if event.get("channel") == "production" and event.get("action") in {"activate", "rollback"}
    }
    if to_package_id not in prior_production:
        raise ValueError("Rollback target was never previously active in production")
    registration = load_registration(to_package_id, root)
    verify_registration(to_package_id, root)
    _assert_production_eligible(registration)
    with _registry_lock(root):
        pointer = _channel_pointer(root, "production")
        _assert_expected_current(pointer, expected_current)
        previous = pointer.get("package_id") if pointer else None
        event = _event_payload(
            action="rollback",
            channel="production",
            package_id=to_package_id,
            previous_package_id=previous,
            actor=approved_by,
            reason=reason,
            registration=registration,
        )
        _atomic_write_json(root / "events" / f"{event['event_id']}.json", event, overwrite=False)
        _atomic_write_json(
            root / "channels/production.json",
            {
                "registry_schema_version": REGISTRY_SCHEMA_VERSION,
                "channel": "production",
                "package_id": to_package_id,
                "event_id": event["event_id"],
                "updated_at_utc": event["generated_at_utc"],
                "run_dir": registration["run_dir"],
                "registration_content_sha256": registration["registration_content_sha256"],
            },
            overwrite=True,
        )
    return event


def resolve_channel(
    channel: str,
    *,
    expected_package_id: str | None = None,
    registry_root: str | Path | None = None,
) -> dict[str, Any]:
    root = resolve_path(registry_root) if registry_root else default_registry_root()
    pointer = _channel_pointer(root, channel)
    if pointer is None:
        raise FileNotFoundError(f"Registry channel is not active: {channel}")
    package_id = str(pointer["package_id"])
    if expected_package_id and package_id != expected_package_id:
        raise ValueError(
            f"Resolved package differs from expected package: expected={expected_package_id}, actual={package_id}"
        )
    verified = verify_registration(package_id, root)
    registration = load_registration(package_id, root)
    return {**pointer, "verified": verified, "registration": registration}


def resolve_model_reference(
    config: dict[str, Any],
    config_path: str | Path,
    *,
    purpose: str,
) -> tuple[Path, dict[str, Any]]:
    """Resolve one immutable model package for forecast or optimizer startup."""
    config_path = Path(config_path).expanduser().resolve()
    reference = config.get("model_ref") or {}
    source = str(reference.get("source") or "direct")
    if source == "registry":
        registry_value = reference.get("registry_root")
        registry_root = (
            resolve_path(registry_value, base_dir=config_path.parent)
            if registry_value
            else default_registry_root()
        )
        channel = str(reference.get("channel") or "production")
        resolved = resolve_channel(
            channel,
            expected_package_id=reference.get("expected_package_id"),
            registry_root=registry_root,
        )
        registration = resolved["registration"]
        run_dir = _resolve_recorded_path(registration["run_dir"])
        return run_dir, {
            "schema_version": "1.0.0",
            "purpose": purpose,
            "source": "registry",
            "channel": channel,
            "package_id": resolved["package_id"],
            "event_id": resolved["event_id"],
            "run_dir": str(run_dir),
            "package_input_fingerprint": registration["package_input_fingerprint"],
            "panel_sha256": registration["panel"]["sha256"],
            "registration_content_sha256": registration["registration_content_sha256"],
        }
    if source != "direct":
        raise ValueError(f"Unsupported model_ref.source={source!r}")
    paths = config.get("paths") or {}
    raw = paths.get("model_run_dir") or paths.get("model_artifacts_dir")
    if not raw:
        raise ValueError("Direct model_ref requires paths.model_run_dir")
    run_dir = resolve_path(raw, base_dir=config_path.parent)
    package = ModelPackage.from_run_dir(run_dir, require_posterior_ready=True, validate_hash=True)
    allow_preprod = bool(reference.get("allow_preprod_restricted", False))
    if package.activation_status != "production_ready" and not allow_preprod:
        raise ValueError(
            "Direct package is not production_ready. Use registry production channel or set "
            "model_ref.allow_preprod_restricted=true only for an explicit controlled preprod run."
        )
    return run_dir, {
        "schema_version": "1.0.0",
        "purpose": purpose,
        "source": "direct",
        "channel": "preprod_override" if package.activation_status != "production_ready" else "production_direct",
        "package_id": None,
        "event_id": None,
        "run_dir": str(run_dir),
        "package_input_fingerprint": package.manifest.get("package_input_fingerprint"),
        "panel_sha256": None,
        "activation_status": package.activation_status,
        "allow_preprod_restricted": allow_preprod,
    }
