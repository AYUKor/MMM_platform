"""Script-facing lifecycle helpers for immutable X5 MMM model runs.

Fresh sampling is executed through the hash-bound fit contract in ``fit.py``;
saved runs can then be validated or replayed without changing their posterior.
"""

from __future__ import annotations

import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .forecast_engine import export_fit_design_metadata
from .io import project_root, read_json, resolve_path, write_json
from .model_package import (
    build_package,
    list_posteriors,
    sha256_file,
    write_package_artifacts,
)
from .model_package_reader import ModelPackage


REQUIRED_REPLAY_EVIDENCE = [
    "run_config.json",
    "diagnostics_summary.csv",
    "channel_reliability.csv",
    "adequacy.json",
    "roas_all_fits.csv",
    "target_effects_all_fits.csv",
    "prior_posterior_contraction.csv",
]


def _safe_fit_key(fit_key: str) -> str:
    return fit_key.replace("/", "_").replace("::", "__")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _cached_fit_is_valid(run_dir: Path, fit_key: str) -> bool:
    safe = _safe_fit_key(fit_key)
    posterior_path = run_dir / f"posterior_{safe}.nc"
    state_path = run_dir / f"fit_state_{safe}.json"
    if not posterior_path.exists() and not state_path.exists():
        return False
    if not posterior_path.exists() or not state_path.exists():
        raise ValueError(f"Incomplete cached fit state for {fit_key}")
    state = read_json(state_path) or {}
    if state.get("fit_key") != fit_key or state.get("status") != "complete":
        raise ValueError(f"Invalid cached fit state for {fit_key}")
    if state.get("posterior_sha256") != sha256_file(posterior_path):
        raise ValueError(f"Cached posterior hash mismatch for {fit_key}")
    return True


def _process_tree_cpu(root_pid: int) -> float:
    result = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,%cpu="],
        capture_output=True,
        text=True,
        check=True,
    )
    rows: dict[int, tuple[int, float]] = {}
    children: dict[int, list[int]] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue
        pid, ppid, cpu = int(parts[0]), int(parts[1]), float(parts[2])
        rows[pid] = (ppid, cpu)
        children.setdefault(ppid, []).append(pid)
    total = 0.0
    pending = [root_pid]
    seen: set[int] = set()
    while pending:
        pid = pending.pop()
        if pid in seen:
            continue
        seen.add(pid)
        total += rows.get(pid, (0, 0.0))[1]
        pending.extend(children.get(pid, []))
    return total


def _terminate_process_group(process: subprocess.Popen[Any], grace_seconds: int = 30) -> None:
    if process.poll() is not None:
        return
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    with suppress(subprocess.TimeoutExpired):
        process.wait(timeout=10)


def orchestrate_guarded_fit(
    run_dir: str | Path,
    *,
    fit_config: str | Path,
    fit_profile: str | None = None,
    max_retries: int = 2,
    stall_minutes: float = 20.0,
    timeout_hours: float = 8.0,
    poll_seconds: float = 60.0,
) -> dict[str, Any]:
    """Run each immutable fit in an isolated process with retry and stall protection."""
    run_dir = resolve_path(run_dir)
    fit_config = resolve_path(fit_config)
    identity = read_json(run_dir / "run_identity.json") or {}
    fit_keys = list(identity.get("expected_fit_keys") or [])
    if not fit_keys:
        raise ValueError(f"Guarded run has no expected_fit_keys: {run_dir}")
    if max_retries < 0 or stall_minutes <= 0 or timeout_hours <= 0 or poll_seconds <= 0:
        raise ValueError("Orchestrator retry, stall, timeout and poll settings must be positive")

    logs_dir = run_dir / "job_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    status_path = run_dir / "fit_orchestrator_status.json"
    events_path = run_dir / "fit_orchestrator_events.jsonl"
    lock_path = run_dir / ".fit_orchestrator.lock"
    lock_handle = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        lock_handle.close()
        raise RuntimeError(f"Another fit orchestrator already holds {lock_path}") from exc

    cli_path = Path(__file__).resolve().parents[1] / "02_pymc_model.py"
    started_at = datetime.now(timezone.utc).isoformat()
    status: dict[str, Any] = {
        "schema_version": "1.0.0",
        "status": "running",
        "started_at_utc": started_at,
        "updated_at_utc": started_at,
        "run_dir": str(run_dir),
        "run_identity_sha256": identity.get("run_identity_sha256"),
        "orchestrator_code_sha256": sha256_file(Path(__file__).resolve()),
        "fit_config": str(fit_config),
        "max_retries": max_retries,
        "stall_minutes": stall_minutes,
        "timeout_hours": timeout_hours,
        "poll_seconds": poll_seconds,
        "expected_fit_keys": fit_keys,
        "completed_fit_keys": [],
        "current_fit_key": None,
        "current_attempt": None,
        "current_pid": None,
        "last_cpu_percent": None,
        "last_error": None,
    }

    def persist(event: str, **extra: Any) -> None:
        now = datetime.now(timezone.utc).isoformat()
        status.update(extra)
        status["updated_at_utc"] = now
        write_json(status_path, status)
        _append_jsonl(events_path, {"at_utc": now, "event": event, **extra})

    try:
        completed = [fit_key for fit_key in fit_keys if _cached_fit_is_valid(run_dir, fit_key)]
        persist("orchestrator_started", completed_fit_keys=completed)
        for fit_index, fit_key in enumerate(fit_keys, start=1):
            if _cached_fit_is_valid(run_dir, fit_key):
                completed = [key for key in fit_keys if _cached_fit_is_valid(run_dir, key)]
                persist("fit_reused", completed_fit_keys=completed, current_fit_key=fit_key)
                continue

            fit_succeeded = False
            safe = _safe_fit_key(fit_key)
            for attempt in range(1, max_retries + 2):
                partial_path = run_dir / f".posterior_{safe}.partial.nc"
                if partial_path.exists():
                    raise RuntimeError(f"Stale partial posterior requires review: {partial_path}")
                log_path = logs_dir / f"{fit_index:02d}_{safe}_attempt_{attempt}.log"
                command = [
                    "/usr/bin/caffeinate",
                    "-dimsu",
                    sys.executable,
                    "-B",
                    str(cli_path),
                    "--mode",
                    "fit",
                    "--fit-config",
                    str(fit_config),
                    "--run-dir",
                    str(run_dir),
                    "--resume",
                    "--only-fit",
                    fit_key,
                ]
                if fit_profile:
                    command.extend(["--fit-profile", fit_profile])
                env = os.environ.copy()
                env.update(
                    {
                        "MPLCONFIGDIR": "/tmp/matplotlib",
                        "XDG_CACHE_HOME": "/tmp/codex_xdg",
                        "PYTHONPYCACHEPREFIX": "/tmp/codex_pycache",
                        "PYTHONDONTWRITEBYTECODE": "1",
                        "PYTHONUNBUFFERED": "1",
                    }
                )
                with log_path.open("a", encoding="utf-8") as log_handle:
                    process = subprocess.Popen(
                        command,
                        cwd=project_root(),
                        env=env,
                        stdin=subprocess.DEVNULL,
                        stdout=log_handle,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                        text=True,
                    )
                    attempt_started = time.monotonic()
                    last_active = attempt_started
                    persist(
                        "fit_attempt_started",
                        current_fit_key=fit_key,
                        current_attempt=attempt,
                        current_pid=process.pid,
                        current_log=str(log_path),
                        last_error=None,
                    )
                    stop_reason = None
                    while process.poll() is None:
                        now = time.monotonic()
                        cpu = _process_tree_cpu(process.pid)
                        if cpu >= 1.0:
                            last_active = now
                        persist(
                            "fit_heartbeat",
                            last_cpu_percent=round(cpu, 2),
                            attempt_elapsed_minutes=round((now - attempt_started) / 60.0, 2),
                            idle_minutes=round((now - last_active) / 60.0, 2),
                        )
                        if now - last_active >= stall_minutes * 60:
                            stop_reason = f"CPU_STALL_{stall_minutes:g}_MIN"
                            _terminate_process_group(process)
                            break
                        if now - attempt_started >= timeout_hours * 3600:
                            stop_reason = f"FIT_TIMEOUT_{timeout_hours:g}_H"
                            _terminate_process_group(process)
                            break
                        time.sleep(poll_seconds)
                    exit_code = process.poll()

                if exit_code == 0 and _cached_fit_is_valid(run_dir, fit_key):
                    fit_succeeded = True
                    completed = [key for key in fit_keys if _cached_fit_is_valid(run_dir, key)]
                    persist(
                        "fit_completed",
                        completed_fit_keys=completed,
                        current_pid=None,
                        last_error=None,
                    )
                    break
                reason = stop_reason or f"EXIT_CODE_{exit_code}"
                persist("fit_attempt_failed", current_pid=None, last_error=reason)
            if not fit_succeeded:
                raise RuntimeError(f"Fit failed after {max_retries + 1} attempts: {fit_key}")

        completed = [fit_key for fit_key in fit_keys if _cached_fit_is_valid(run_dir, fit_key)]
        if completed != fit_keys:
            raise RuntimeError(f"Orchestrator ended with incomplete fit set: {len(completed)}/{len(fit_keys)}")
        if not (run_dir / "model_fit_card.json").exists():
            raise RuntimeError("All posteriors exist but final model package card is missing")
        persist(
            "orchestrator_completed",
            status="complete",
            completed_fit_keys=completed,
            current_fit_key=None,
            current_attempt=None,
            current_pid=None,
        )
        return status
    except Exception as exc:
        persist(
            "orchestrator_failed",
            status="failed",
            current_pid=None,
            last_error=f"{type(exc).__name__}: {exc}",
        )
        raise
    finally:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        lock_handle.close()


def _panel_path(run_dir: Path, config: dict[str, Any], panel_override: str | Path | None) -> Path:
    if panel_override is not None:
        return resolve_path(panel_override)
    raw = config.get("panel_path")
    if not raw:
        raise ValueError(f"run_config.json in {run_dir} has no panel_path")
    return resolve_path(raw)


def build_model_run_fingerprint(
    run_dir: str | Path,
    *,
    panel_override: str | Path | None = None,
) -> dict[str, Any]:
    run_dir = resolve_path(run_dir)
    config = read_json(run_dir / "run_config.json") or {}
    if not isinstance(config, dict):
        raise ValueError(f"Invalid run_config.json in {run_dir}")
    panel_path = _panel_path(run_dir, config, panel_override)
    if not panel_path.exists():
        raise FileNotFoundError(f"Model panel is missing: {panel_path}")
    missing_evidence = [name for name in REQUIRED_REPLAY_EVIDENCE if not (run_dir / name).exists()]
    posterior_index = list_posteriors(run_dir)
    return {
        "run_dir": str(run_dir),
        "run_config_sha256": sha256_file(run_dir / "run_config.json"),
        "panel_path": str(panel_path),
        "panel_sha256": sha256_file(panel_path),
        "panel_size_bytes": panel_path.stat().st_size,
        "posterior_files_n": len(posterior_index),
        "posterior_sha256": {
            fit_key: row.get("sha256") for fit_key, row in sorted(posterior_index.items())
        },
        "missing_replay_evidence": missing_evidence,
        "train_start": config.get("train_start"),
        "train_end": config.get("train_end"),
        "mode": config.get("mode"),
        "run_label": config.get("run_label"),
        "run_variant": config.get("run_variant"),
    }


def validate_existing_model_run(
    run_dir: str | Path,
    *,
    panel_override: str | Path | None = None,
) -> dict[str, Any]:
    run_dir = resolve_path(run_dir)
    package = ModelPackage.from_run_dir(run_dir, require_posterior_ready=True, validate_hash=True)
    fingerprint = build_model_run_fingerprint(run_dir, panel_override=panel_override)
    if fingerprint["missing_replay_evidence"]:
        raise ValueError(f"Missing replay evidence: {fingerprint['missing_replay_evidence']}")
    expected_fits = set((package.manifest.get("evidence_coverage") or {}).get("expected_fit_keys") or [])
    posterior_fits = set(fingerprint["posterior_sha256"])
    if not expected_fits:
        raise ValueError("Model package has no expected_fit_keys evidence contract")
    if expected_fits != posterior_fits:
        raise ValueError(
            "Posterior fit set differs from package contract: "
            f"missing={sorted(expected_fits - posterior_fits)}, extra={sorted(posterior_fits - expected_fits)}"
        )
    return {
        "status": "validated",
        "package_stage": package.package_stage,
        "activation_status": package.activation_status,
        "production_blockers": list(package.manifest.get("production_blockers") or []),
        "expected_fits_n": len(expected_fits),
        "fingerprint": fingerprint,
    }


def replay_existing_model_run(
    run_dir: str | Path,
    *,
    panel_override: str | Path | None = None,
    write: bool = True,
) -> dict[str, Any]:
    """Rebuild strict replay metadata and package artifacts from saved posteriors."""
    run_dir = resolve_path(run_dir)
    before = validate_existing_model_run(run_dir, panel_override=panel_override)
    configured_panel = Path(before["fingerprint"]["panel_path"])
    run_config = read_json(run_dir / "run_config.json") or {}
    original_panel = resolve_path(run_config["panel_path"])
    if configured_panel.resolve() != original_panel.resolve():
        raise ValueError(
            "Replay with a different panel is forbidden. Create a new run/refit instead of attaching old posteriors "
            "to a new dataset."
        )

    metadata_card = export_fit_design_metadata(run_dir)
    built = build_package(run_dir, run_dir)
    manifest = built[0]
    if manifest.get("package_stage") != "posterior_ready":
        raise ValueError(
            f"Replay rebuilt an incomplete package: stage={manifest.get('package_stage')}, "
            f"coverage={manifest.get('evidence_coverage')}"
        )
    outputs = write_package_artifacts(run_dir, built) if write else {}
    after = validate_existing_model_run(run_dir, panel_override=panel_override) if write else before
    code_files = {
        "model.py": Path(__file__).resolve(),
        "forecast_engine.py": Path(__file__).with_name("forecast_engine.py").resolve(),
        "model_package.py": Path(__file__).with_name("model_package.py").resolve(),
        "02_pymc_model.py": Path(__file__).resolve().parents[1] / "02_pymc_model.py",
    }
    card = {
        "status": "replayed_from_saved_posteriors",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "sampling_performed": False,
        "run_dir": str(run_dir),
        "before": before,
        "after": after,
        "fit_design_metadata": metadata_card,
        "package_outputs": outputs,
        "code_sha256": {name: sha256_file(path) for name, path in code_files.items()},
        "contract": {
            "saved_posteriors_are_immutable_inputs": True,
            "different_panel_requires_new_refit": True,
            "production_activation_requires_oot_and_historical_replay": True,
        },
    }
    if write:
        write_json(run_dir / "model_replay_card.json", card)
    return card


def run_model_refresh(
    run_dir: str | Path,
    *,
    mode: str,
    panel_override: str | Path | None = None,
    write: bool = True,
    fit_config: str | Path | None = None,
    fit_profile: str | None = None,
    prepare_only: bool = False,
    resume: bool = False,
    only_fits: list[str] | None = None,
) -> dict[str, Any]:
    if mode == "validate":
        return validate_existing_model_run(run_dir, panel_override=panel_override)
    if mode == "replay":
        return replay_existing_model_run(run_dir, panel_override=panel_override, write=write)
    if mode == "fit":
        if not write:
            raise ValueError("--no-write is incompatible with guarded fit; use --prepare-only for no sampling")
        if fit_config is None:
            raise ValueError("Guarded fit requires --fit-config")
        from .fit import run_guarded_fit

        fit_card = run_guarded_fit(
            fit_config,
            run_dir=run_dir,
            panel_override=panel_override,
            mode_override=fit_profile,
            prepare_only=prepare_only,
            resume=resume,
            only_fits=only_fits,
        )
        if fit_card.get("status") != "fit_complete":
            return fit_card

        run_dir = resolve_path(run_dir)
        package_outputs = write_package_artifacts(run_dir, build_package(run_dir, run_dir))
        metadata_card = export_fit_design_metadata(run_dir)
        package_outputs = write_package_artifacts(run_dir, build_package(run_dir, run_dir))
        validated = validate_existing_model_run(run_dir, panel_override=panel_override)
        card = {
            **fit_card,
            "package_outputs": package_outputs,
            "fit_design_metadata": metadata_card,
            "validated_package": validated,
        }
        write_json(run_dir / "model_fit_card.json", card)
        return card
    raise ValueError(f"Unsupported model refresh mode: {mode}")
