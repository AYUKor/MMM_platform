"""CLI for predictive OOT and independent historical-response replay validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mmm_core.io import project_root
from mmm_core.validation import (
    OOTSplit,
    run_historical_response_replay_validation,
    run_independent_historical_response_replay,
    run_predictive_oot,
)


def resolve(path: str | None) -> Path | None:
    if path is None:
        return None
    candidate = Path(path).expanduser()
    return candidate if candidate.is_absolute() else project_root() / candidate


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate an immutable X5 MMM run.")
    parser.add_argument("--mode", required=True, choices=["oot", "response-replay"])
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--write-verdict", action="store_true", help="Persist validation artifacts in the run folder.")
    parser.add_argument("--panel")
    parser.add_argument("--oot-start")
    parser.add_argument("--oot-end")
    parser.add_argument("--coverage-manifest")
    parser.add_argument("--pre-roll-days", type=int, default=14)
    parser.add_argument("--min-scored-days", type=int, default=28)
    parser.add_argument("--development-seen", action="store_true")
    parser.add_argument("--max-draws", type=int, default=300)
    parser.add_argument("--seed", type=int, default=10042)
    parser.add_argument("--reference", help="Optional prebuilt reference file; omit both files to generate producers.")
    parser.add_argument("--replayed", help="Optional prebuilt replay file; omit both files to generate producers.")
    parser.add_argument("--expected-fits", type=int, default=12)
    parser.add_argument("--expected-effects", type=int, default=61)
    parser.add_argument("--expected-draws", type=int, default=64)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_dir = resolve(args.run_dir)
    if run_dir is None:
        raise ValueError("--run-dir is required")
    if args.mode == "oot":
        panel_path = resolve(args.panel)
        coverage_manifest = resolve(args.coverage_manifest)
        if panel_path is None or coverage_manifest is None or not args.oot_start or not args.oot_end:
            raise ValueError(
                "OOT requires --panel, --coverage-manifest, --oot-start and --oot-end"
            )
        run_config = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
        result = run_predictive_oot(
            run_dir,
            panel_path,
            coverage_manifest,
            OOTSplit(
                train_end=str(run_config["train_end"]),
                oot_start=args.oot_start,
                oot_end=args.oot_end,
                pre_roll_days=args.pre_roll_days,
                min_scored_days=args.min_scored_days,
                development_seen=args.development_seen,
            ),
            max_draws=args.max_draws,
            seed=args.seed,
            write=args.write_verdict,
        )
    else:
        reference = resolve(args.reference)
        replayed = resolve(args.replayed)
        if (reference is None) != (replayed is None):
            raise ValueError("Provide both --reference and --replayed, or omit both to generate independent producers")
        if reference is not None and replayed is not None:
            result = run_historical_response_replay_validation(
                run_dir,
                reference,
                replayed,
                expected_fits=args.expected_fits,
                expected_effects=args.expected_effects,
                expected_draws=args.expected_draws,
                write=args.write_verdict,
            )
        else:
            result = run_independent_historical_response_replay(
                run_dir,
                resolve(args.panel),
                expected_fits=args.expected_fits,
                expected_effects=args.expected_effects,
                expected_draws=args.expected_draws,
                seed=args.seed,
                write=args.write_verdict,
            )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
