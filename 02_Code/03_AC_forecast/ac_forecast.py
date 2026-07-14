"""Campaign forecast workflow for future media plans.

Input shape expected from business:
- campaign name and optional creative;
- channel list;
- geo list;
- start/end dates, possibly different by channel/geo;
- budget by channel x geo;
- no guaranteed daily flighting.

The first executable layer is a model-package check. It verifies that the
selected fitted model can support the requested forecast before we simulate any
campaign response.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PYMC_CODE_DIR = Path(__file__).resolve().parents[1] / "01_PyMC"
if str(PYMC_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(PYMC_CODE_DIR))

from mmm_core.campaign_plan import prepare_campaign_from_config
from mmm_core.forecast_engine import export_fit_design_metadata, run_forecast_from_flighting
from mmm_core.io import ensure_dir, load_config, project_root, resolve_path, write_json
from mmm_core.model_package_reader import ModelPackage
from mmm_core.model_registry import resolve_model_reference


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run X5 MMM campaign forecast workflow.")
    parser.add_argument("--config", required=True, help="Path to campaign forecast YAML/JSON config.")
    parser.add_argument(
        "--check-model-package-only",
        action="store_true",
        help="Validate selected model package and write a check card without running forecast math.",
    )
    parser.add_argument(
        "--prepare-campaign-only",
        action="store_true",
        help="Parse/flight/validate the campaign file, then stop before forecast math.",
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
    model_run_dir, model_resolution = resolve_model_reference(config, config_path, purpose="forecast")
    write_json(output_dir / "model_resolution_forecast.json", model_resolution)
    campaign_input_dir, campaign_file = _campaign_input_from_config(config, config_path)

    package = ModelPackage.from_run_dir(model_run_dir, require_posterior_ready=False)
    check_card = package.check_card(purpose="forecast")
    check_path = output_dir / "model_package_check_forecast.json"
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
    print(f"Forecast-supported rows: {selection['objective_rows_n']}")
    print(f"Check card: {check_path}")

    if args.export_model_metadata_only:
        export_card = export_fit_design_metadata(model_run_dir)
        print(f"Fit-design metadata exported: {export_card['fit_design_metadata']}")
        print(f"Fits exported: {export_card['fits_n']}")
        return

    if args.prepare_campaign_only:
        prep = prepare_campaign_from_config(config, config_path, package, output_dir, purpose="forecast")
        print(f"Normalized campaign: {prep.normalized_path}")
        print(f"Daily flighting: {prep.flighting_path}")
        print(f"Model validation: {prep.validation_path}")
        print(f"Prepare card: {prep.card_path}")
        return

    if args.check_model_package_only:
        return

    prep = prepare_campaign_from_config(config, config_path, package, output_dir, purpose="forecast")
    forecast_cfg = config.get("forecast") or {}
    run_id = str(config.get("run_id") or "campaign_forecast")
    n_samples = int(forecast_cfg.get("posterior_samples") or 300)
    seed = int(forecast_cfg.get("random_seed") or 42)
    forecast_card = run_forecast_from_flighting(
        model_run_dir,
        prep.flighting_path,
        output_dir,
        run_id,
        n_samples=n_samples,
        seed=seed,
        future_controls=config.get("future_controls") or {},
    )
    print(f"Normalized campaign: {prep.normalized_path}")
    print(f"Daily flighting: {prep.flighting_path}")
    print(f"Model validation: {prep.validation_path}")
    print(f"Forecast detail rows: {forecast_card['detail_rows_n']}")
    print(f"Forecast summary rows: {forecast_card['summary_rows_n']}")
    print(f"Forecast outputs: {forecast_card['outputs']}")


if __name__ == "__main__":
    main()
