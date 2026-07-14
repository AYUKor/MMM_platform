"""Budget optimization workflow for future media allocation.

Business purpose:
- start from an available budget and business constraints;
- compare candidate allocations across channels/geos;
- estimate p10/p50/p90 outcomes using the same response logic as campaign forecast;
- produce a simple Excel report: budget -> allocation -> expected result.

The first executable layer is a model-package check. It verifies what the
selected fitted model can optimize directly, what can be used with caution, and
what must stay as a side diagnostic metric.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PYMC_CODE_DIR = Path(__file__).resolve().parents[1] / "01_PyMC"
if str(PYMC_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(PYMC_CODE_DIR))

from mmm_core.campaign_plan import prepare_campaign_from_config
from mmm_core.forecast_engine import export_fit_design_metadata, run_optimizer_from_flighting
from mmm_core.io import ensure_dir, load_config, project_root, resolve_path, write_json
from mmm_core.model_package_reader import ModelPackage
from mmm_core.model_registry import resolve_model_reference
from mmm_core.model_package import sha256_file
from marketer_report import ReportPaths, build_marketer_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run X5 MMM budget optimization workflow.")
    parser.add_argument("--config", required=True, help="Path to budget optimizer YAML/JSON config.")
    parser.add_argument(
        "--check-model-package-only",
        action="store_true",
        help="Validate selected model package and write a check card without running optimization math.",
    )
    parser.add_argument(
        "--prepare-campaign-only",
        action="store_true",
        help="Parse/flight/validate the campaign file, then stop before optimization math.",
    )
    parser.add_argument(
        "--export-model-metadata-only",
        action="store_true",
        help="Export strict forecast/replay metadata from the selected model package, then stop.",
    )
    return parser.parse_args()


def _path_from_config(config: dict, config_path: Path, key: str, fallback_key: str | None = None) -> Path:
    paths = config.get("paths") or {}
    value = paths.get(key)
    if value is None and fallback_key is not None:
        value = paths.get(fallback_key)
    if value is None:
        raise ValueError(f"Config paths.{key} is required")
    return resolve_path(value, base_dir=config_path.parent)


def _campaign_input_from_config(config: dict, config_path: Path) -> tuple[Path | None, Path | None]:
    paths = config.get("paths") or {}
    input_dir_value = paths.get("campaign_input_dir")
    file_value = paths.get("campaign_file")
    input_dir = resolve_path(input_dir_value, base_dir=config_path.parent) if input_dir_value else None
    campaign_file = None
    if input_dir is not None and file_value:
        campaign_file = input_dir / str(file_value)
    return input_dir, campaign_file


def main() -> None:
    args = parse_args()
    config_path = Path(args.config).expanduser().resolve()
    config = load_config(config_path)
    output_dir = ensure_dir(_path_from_config(config, config_path, "output_dir"))
    model_run_dir, model_resolution = resolve_model_reference(config, config_path, purpose="optimizer")
    write_json(output_dir / "model_resolution_optimizer.json", model_resolution)
    objective_config = config.setdefault("objective", {})
    policy_value = objective_config.get("business_threshold_policy") or "business_threshold_policy_v1.yaml"
    policy_path = resolve_path(policy_value, base_dir=config_path.parent)
    business_policy = load_config(policy_path)
    objective_config["business_threshold_policy_snapshot"] = business_policy
    objective_config["business_threshold_policy_sha256"] = sha256_file(policy_path)
    policy_decision = business_policy.get("decision") or {}
    guardrails = objective_config.setdefault("guardrails", {})
    if guardrails.get("min_roas_p50") is None and policy_decision.get("min_roas_p50") is not None:
        guardrails["min_roas_p50"] = policy_decision["min_roas_p50"]
    guardrails["business_policy_id"] = business_policy.get("policy_id")
    guardrails["business_decision_mode"] = policy_decision.get("mode", "allocation_only")
    write_json(
        output_dir / "business_threshold_policy_snapshot.json",
        {
            "policy_path": str(policy_path),
            "policy_sha256": sha256_file(policy_path),
            "policy": business_policy,
        },
    )
    decision_policy_value = config.get("decision_policy_file") or "optimizer_decision_policy_v1.yaml"
    decision_policy_path = resolve_path(decision_policy_value, base_dir=config_path.parent)
    decision_policy = load_config(decision_policy_path)
    config["decision_policy"] = decision_policy
    config["decision_policy_sha256"] = sha256_file(decision_policy_path)
    write_json(
        output_dir / "optimizer_decision_policy_snapshot.json",
        {
            "policy_path": str(decision_policy_path),
            "policy_sha256": sha256_file(decision_policy_path),
            "policy": decision_policy,
        },
    )
    campaign_input_dir, campaign_file = _campaign_input_from_config(config, config_path)
    optimizer_policy = ((config.get("objective") or {}).get("model_risk_policy") or "balanced")

    package = ModelPackage.from_run_dir(model_run_dir, require_posterior_ready=False)
    check_card = package.check_card(purpose="optimizer", optimizer_policy=optimizer_policy)
    check_path = output_dir / "model_package_check_optimizer.json"
    write_json(check_path, check_card)

    summary = check_card["package_summary"]
    selection = check_card["selection_summary"]
    print(f"Project root: {project_root()}")
    print(f"Config: {config_path}")
    print(f"Model run: {model_run_dir}")
    print(f"Model source: {model_resolution['source']} / {model_resolution['channel']}")
    print(f"Package stage: {summary['package_stage']}")
    if campaign_input_dir is not None:
        print(f"Campaign input dir: {campaign_input_dir}")
    if campaign_file is not None:
        print(f"Campaign file: {campaign_file} (exists={campaign_file.exists()})")
    print(f"Optimizer policy: {optimizer_policy}")
    print(f"Objective rows: {selection['objective_rows_n']}")
    print(f"Side metric rows: {selection['side_metric_rows_n']}")
    print(f"Check card: {check_path}")

    if args.export_model_metadata_only:
        export_card = export_fit_design_metadata(model_run_dir)
        print(f"Fit-design metadata exported: {export_card['fit_design_metadata']}")
        print(f"Fits exported: {export_card['fits_n']}")
        return

    if args.prepare_campaign_only:
        prep = prepare_campaign_from_config(config, config_path, package, output_dir, purpose="optimizer")
        print(f"Normalized campaign: {prep.normalized_path}")
        print(f"Daily flighting: {prep.flighting_path}")
        print(f"Model validation: {prep.validation_path}")
        print(f"Prepare card: {prep.card_path}")
        return

    if args.check_model_package_only:
        return

    prep = prepare_campaign_from_config(config, config_path, package, output_dir, purpose="optimizer")
    run_id = str(config.get("run_id") or "budget_optimizer")
    opt_cfg = (config.get("optimizer") or {}).get("scenario_6") or {}
    search_requested = int(opt_cfg.get("search_candidates") or opt_cfg.get("monte_carlo_candidates") or 80)
    safety_cap = int(opt_cfg.get("runtime_safety_max_candidates") or 300)
    search_candidates = min(search_requested, safety_cap)
    search_samples = int(opt_cfg.get("search_posterior_samples") or 60)
    final_samples = int(opt_cfg.get("final_posterior_samples") or 300)
    seed = int(opt_cfg.get("random_seed") or 42)
    finalists = int(opt_cfg.get("finalists") or 5)
    optimizer_card = run_optimizer_from_flighting(
        model_run_dir,
        prep.flighting_path,
        output_dir,
        run_id,
        search_candidates=search_candidates,
        search_samples=search_samples,
        final_samples=final_samples,
        seed=seed,
        finalists=finalists,
        workflow_config=config,
    )
    marketer_report = build_marketer_report(
        ReportPaths(
            model_run_dir=model_run_dir,
            flighting_path=Path(prep.flighting_path),
            optimizer_output_dir=output_dir,
            output_xlsx=output_dir / "marketer_preprod_forecast_optimizer_report.xlsx",
            run_id=run_id,
        )
    )
    print(f"Normalized campaign: {prep.normalized_path}")
    print(f"Daily flighting: {prep.flighting_path}")
    print(f"Model validation: {prep.validation_path}")
    print(f"Optimizer outputs: {optimizer_card['outputs']}")
    print(f"Marketer report: {marketer_report['output_xlsx']}")


if __name__ == "__main__":
    main()
