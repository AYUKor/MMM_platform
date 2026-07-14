"""Lifecycle entrypoint for immutable X5 MMM fit, validate and replay jobs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mmm_core.io import project_root
from mmm_core.model import orchestrate_guarded_fit, run_model_refresh


DEFAULT_RUN_DIR = (
    "03_Outputs/01_PyMC_outputs/04_PyMC_05072026_Q1_2026_refit/"
    "production_q1_2026_tc5_specific_indoor_separate_rf_prorata_"
    "tc5_online_basket_pooled_tc5_offline_turnover_nat_tv_tier_pool"
)
DEFAULT_FIT_CONFIG = "02_Code/01_PyMC/configs/q1_2026_panel_v3_guarded_fit.yaml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fit, validate or replay an immutable X5 MMM run.")
    parser.add_argument("--run-dir", default=None, help="Concrete PyMC run folder. Fit may read it from YAML.")
    parser.add_argument(
        "--mode",
        default="validate",
        choices=["validate", "replay", "fit"],
        help="validate = read-only; replay = rebuild metadata/package; fit = guarded fresh sampling.",
    )
    parser.add_argument(
        "--panel",
        default=None,
        help="Optional panel assertion. Replay rejects a path different from run_config.json.",
    )
    parser.add_argument("--no-write", action="store_true", help="Do not persist replay artifacts.")
    parser.add_argument("--fit-config", default=DEFAULT_FIT_CONFIG, help="Fit YAML contract used by --mode fit.")
    parser.add_argument(
        "--fit-profile",
        choices=["fast", "medium", "pilot", "production"],
        default=None,
        help="Optional fit profile override; it becomes part of the immutable run identity.",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Build all 12 deterministic fit contracts without sampling.",
    )
    parser.add_argument("--resume", action="store_true", help="Resume only hash-matching completed fit contracts.")
    parser.add_argument(
        "--only-fit",
        action="append",
        default=None,
        help="Exact fit key, for example 'ТСХ/Оффлайн::avg_basket'. Repeat for multiple fits.",
    )
    parser.add_argument(
        "--orchestrate",
        action="store_true",
        help="Run each guarded fit in an isolated subprocess with retry, heartbeat and stall protection.",
    )
    parser.add_argument("--job-max-retries", type=int, default=2)
    parser.add_argument("--job-stall-minutes", type=float, default=20.0)
    parser.add_argument("--job-timeout-hours", type=float, default=8.0)
    parser.add_argument("--job-poll-seconds", type=float, default=60.0)
    return parser.parse_args()


def resolve(path: str | None) -> Path | None:
    if path is None:
        return None
    candidate = Path(path).expanduser()
    return candidate if candidate.is_absolute() else project_root() / candidate


def main() -> None:
    args = parse_args()
    run_dir = resolve(args.run_dir or (None if args.mode == "fit" else DEFAULT_RUN_DIR))
    panel_path = resolve(args.panel)
    fit_config = resolve(args.fit_config)
    if run_dir is None and args.mode != "fit":
        raise ValueError("--run-dir is required for validate/replay")
    if args.mode == "fit" and run_dir is None:
        from mmm_core.fit import load_guarded_fit_spec

        run_dir = load_guarded_fit_spec(
            fit_config,
            panel_override=panel_path,
            mode_override=args.fit_profile,
        ).run_dir
    if args.orchestrate:
        if args.mode != "fit" or run_dir is None:
            raise ValueError("--orchestrate requires --mode fit and a guarded run directory")
        card = orchestrate_guarded_fit(
            run_dir,
            fit_config=fit_config,
            fit_profile=args.fit_profile,
            max_retries=args.job_max_retries,
            stall_minutes=args.job_stall_minutes,
            timeout_hours=args.job_timeout_hours,
            poll_seconds=args.job_poll_seconds,
        )
        print(json.dumps(card, ensure_ascii=False, indent=2))
        return
    card = run_model_refresh(
        run_dir,
        mode=args.mode,
        panel_override=panel_path,
        write=not args.no_write,
        fit_config=fit_config,
        fit_profile=args.fit_profile,
        prepare_only=args.prepare_only,
        resume=args.resume,
        only_fits=args.only_fit,
    )
    print(json.dumps(card, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
