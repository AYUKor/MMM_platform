"""Audit whether an MMM model package is ready for posterior forecast simulation.

This script is intentionally read-only for model artifacts. It does not run PyMC
and does not estimate campaign effects. Its job is to check whether a selected
model run folder contains enough information for the next forecast/optimizer
engine layers:

- package/capability/risk artifacts;
- posterior variables needed for response simulation;
- replay metadata needed to reproduce the exact model transforms.

The expected result for the current stage is usually:
``package_ready_for_capability_layer`` but
``missing_fit_design_metadata_for_strict_replay``.
That is useful: it prevents downstream code from falling back to ad-hoc ROAS
heuristics.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CODE_DIR = Path(__file__).resolve().parents[1]
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from mmm_core.io import resolve_path, write_json
from mmm_core.model_package_reader import ModelPackage, ModelPackageError

CORE_PACKAGE_FILES = [
    "model_manifest.json",
    "capability_matrix.csv",
    "risk_registry.csv",
    "posterior_index.json",
    "run_config.json",
]

MODEL_OUTPUT_FILES = [
    "diagnostics_summary.csv",
    "adequacy.json",
    "channel_reliability.csv",
    "target_effects_all_fits.csv",
    "roas_all_fits.csv",
    "roas_rub_all_fits.csv",
    "media_grouping_config.json",
    "spend_audit.csv",
]

# These artifacts are the next contract extension for exact historical replay
# and future posterior simulation. Some can be generated as one JSON, others as
# CSV tables; the audit accepts either common naming pattern where sensible.
STRICT_REPLAY_ARTIFACTS = {
    "fit_design_metadata": ["fit_design_metadata.json"],
    "historical_support_bounds": ["historical_support_bounds.csv", "historical_support_bounds.json"],
    "adstock_warm_start": ["adstock_warm_start.json", "adstock_warm_start.csv"],
    "target_denominator_metadata": ["target_denominator_metadata.json", "target_denominator_metadata.csv"],
}

POSTERIOR_REQUIRED_VARS = {"beta", "alpha", "lam"}
POSTERIOR_BASELINE_VARS = {"gamma", "tau_g", "sigma"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit X5 MMM package readiness for forecast engine.")
    parser.add_argument("--run-dir", required=True, help="Model run folder with model package artifacts.")
    parser.add_argument("--output", default=None, help="Optional JSON output path. Defaults to <run-dir>/forecast_engine_audit.json.")
    parser.add_argument("--sample-posteriors", type=int, default=12, help="How many posterior files to inspect with xarray.")
    return parser.parse_args()


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def read_json(path: Path) -> Any:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def file_status(run_dir: Path, names: list[str]) -> dict[str, bool]:
    return {name: (run_dir / name).exists() for name in names}


def _first_existing(run_dir: Path, candidates: list[str]) -> str | None:
    for name in candidates:
        if (run_dir / name).exists():
            return name
    return None


def inspect_posterior_files(run_dir: Path, limit: int) -> dict[str, Any]:
    posterior_files = sorted(run_dir.glob("posterior_*.nc"))
    out: dict[str, Any] = {
        "posterior_files_n": len(posterior_files),
        "inspected_files_n": 0,
        "xarray_available": None,
        "files": [],
        "all_required_response_vars_present": False,
        "all_baseline_vars_present": False,
        "missing_required_vars_by_file": {},
    }
    if not posterior_files:
        return out

    try:
        import xarray as xr  # type: ignore
        out["xarray_available"] = True
    except Exception as exc:  # pragma: no cover - environment dependent
        out["xarray_available"] = False
        out["xarray_error"] = repr(exc)
        return out

    inspected = posterior_files[: max(limit, 0)]
    required_ok = True
    baseline_ok = True
    for path in inspected:
        with xr.open_dataset(path, group="posterior") as ds:
            vars_present = set(ds.data_vars)
            coords_present = set(ds.coords)
            dims = dict(ds.sizes)
            missing_required = sorted(POSTERIOR_REQUIRED_VARS - vars_present)
            missing_baseline = sorted(POSTERIOR_BASELINE_VARS - vars_present)
            if missing_required:
                required_ok = False
                out["missing_required_vars_by_file"][path.name] = missing_required
            if missing_baseline:
                baseline_ok = False
            out["files"].append({
                "file_name": path.name,
                "dims": dims,
                "coords": sorted(coords_present),
                "vars": sorted(vars_present),
                "missing_required_response_vars": missing_required,
                "missing_baseline_vars": missing_baseline,
            })
    out["inspected_files_n"] = len(inspected)
    out["all_required_response_vars_present"] = required_ok and bool(inspected)
    out["all_baseline_vars_present"] = baseline_ok and bool(inspected)
    return out


def audit_run(run_dir: Path, sample_posteriors: int = 12) -> dict[str, Any]:
    run_dir = resolve_path(run_dir)
    audit: dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(run_dir),
        "core_package_files": file_status(run_dir, CORE_PACKAGE_FILES),
        "model_output_files": file_status(run_dir, MODEL_OUTPUT_FILES),
    }

    missing_core = [name for name, ok in audit["core_package_files"].items() if not ok]
    missing_outputs = [name for name, ok in audit["model_output_files"].items() if not ok]
    audit["missing_core_package_files"] = missing_core
    audit["missing_model_output_files"] = missing_outputs

    try:
        package = ModelPackage.from_run_dir(run_dir, require_posterior_ready=False)
        audit["package_summary"] = package.summary()
        audit["package_reader_ok"] = True
    except ModelPackageError as exc:
        audit["package_reader_ok"] = False
        audit["package_reader_error"] = str(exc)
        package = None

    capability_rows = read_csv_rows(run_dir / "capability_matrix.csv")
    risk_rows = read_csv_rows(run_dir / "risk_registry.csv")
    diagnostics_rows = read_csv_rows(run_dir / "diagnostics_summary.csv")
    target_effect_rows = read_csv_rows(run_dir / "target_effects_all_fits.csv")

    audit["row_counts"] = {
        "capability_matrix": len(capability_rows),
        "risk_registry": len(risk_rows),
        "diagnostics_summary": len(diagnostics_rows),
        "target_effects_all_fits": len(target_effect_rows),
    }
    if capability_rows:
        audit["capability_counts"] = {
            "allowed_use": dict(Counter(r.get("allowed_use", "") for r in capability_rows)),
            "optimizer_use": dict(Counter(r.get("optimizer_use", "") for r in capability_rows)),
            "forecast_use": dict(Counter(r.get("forecast_use", "") for r in capability_rows)),
            "target": dict(Counter(r.get("target", "") for r in capability_rows)),
        }

    scaling_audits = sorted(run_dir.glob("media_scaling_audit_*.csv"))
    audit["media_scaling_audit_files_n"] = len(scaling_audits)
    audit["media_scaling_audit_files_sample"] = [p.name for p in scaling_audits[:5]]

    replay_status = {}
    for key, candidates in STRICT_REPLAY_ARTIFACTS.items():
        replay_status[key] = {
            "present": _first_existing(run_dir, candidates) is not None,
            "file": _first_existing(run_dir, candidates) or "",
            "accepted_file_names": candidates,
        }
    audit["strict_replay_artifacts"] = replay_status
    audit["missing_strict_replay_artifacts"] = [k for k, v in replay_status.items() if not v["present"]]

    audit["posterior_inspection"] = inspect_posterior_files(run_dir, sample_posteriors)

    package_ready = (
        not missing_core
        and audit.get("package_reader_ok") is True
        and (audit.get("package_summary") or {}).get("package_stage") == "posterior_ready"
        and audit["posterior_inspection"].get("all_required_response_vars_present") is True
    )
    strict_replay_ready = package_ready and not audit["missing_strict_replay_artifacts"]
    if strict_replay_ready:
        readiness = "strict_replay_ready"
    elif package_ready:
        readiness = "package_ready_but_missing_strict_replay_metadata"
    else:
        readiness = "not_ready"
    audit["forecast_engine_readiness"] = readiness
    audit["recommended_next_step"] = (
        "Implement/export fit_design_metadata and historical_support_bounds before forecast math."
        if readiness == "package_ready_but_missing_strict_replay_metadata"
        else "Fix package/core artifact issues before forecast math."
        if readiness == "not_ready"
        else "Proceed to historical replay implementation."
    )
    return audit


def main() -> None:
    args = parse_args()
    run_dir = resolve_path(args.run_dir)
    output = resolve_path(args.output) if args.output else run_dir / "forecast_engine_audit.json"
    audit = audit_run(run_dir, sample_posteriors=args.sample_posteriors)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, audit)
    print(json.dumps({
        "run_dir": str(run_dir),
        "output": str(output),
        "forecast_engine_readiness": audit["forecast_engine_readiness"],
        "package_stage": (audit.get("package_summary") or {}).get("package_stage"),
        "capability_counts": audit.get("capability_counts", {}),
        "missing_strict_replay_artifacts": audit.get("missing_strict_replay_artifacts", []),
        "recommended_next_step": audit.get("recommended_next_step"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
