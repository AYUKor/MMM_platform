"""Panel, priors, and panel-regression entrypoint for X5 MMM.

This file is the stable place for model-side data preparation:
- read a model-ready panel from 00_Data;
- validate the daily x geo x segment grain;
- prepare empirical-prior / panel-regression artifacts for the PyMC model.

The accepted production logic still lives in the production notebooks. Move code
here incrementally when the notebook-to-pipeline refactor starts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from mmm_core.io import project_root


DEFAULT_PANEL = "00_Data/02_2025_2026Q1_second_pass/panel_final_v2.parquet"
DEFAULT_OUTPUT_DIR = "03_Outputs/01_PyMC_outputs/04_PyMC_05072026_Q1_2026_refit/00_panel_priors"
DEFAULT_TRAIN_START = "2025-01-01"
DEFAULT_TRAIN_END = "2026-03-20"
GRAIN_COLS = ["date", "geo_label", "network", "channel"]
TARGET_COLS = ["turnover_per_user", "orders_per_user", "avg_basket"]
CONTROL_VARIATION_COLS = ["usd_rub_close", "brent_usd_close", "ruonia_rate"]
RF_GEO_LABELS = {"РФ", "РОССИЯ", "RUSSIA"}


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare MMM panel priors and panel-regression artifacts.")
    parser.add_argument("--panel", default=DEFAULT_PANEL, help="Project-relative or absolute panel parquet path.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Project-relative or absolute output directory.")
    parser.add_argument("--train-start", default=DEFAULT_TRAIN_START, help="Inclusive train start date.")
    parser.add_argument("--train-end", default=DEFAULT_TRAIN_END, help="Inclusive train end date.")
    parser.add_argument("--write-summary", action="store_true", help="Write a lightweight panel summary JSON.")
    return parser.parse_args()


def resolve(path: str) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate
    return project_root() / candidate


def summarize_panel(panel: pd.DataFrame, train_start: str, train_end: str) -> dict:
    missing = sorted(set(GRAIN_COLS) - set(panel.columns))
    if missing:
        raise ValueError(f"Panel is missing grain columns: {missing}")
    panel = panel.copy()
    panel["date"] = pd.to_datetime(panel["date"])
    rf_geos = sorted(set(panel["geo_label"].astype(str).str.upper()) & RF_GEO_LABELS)
    if rf_geos:
        raise ValueError(f"RF-like geo rows must be distributed upstream before modeling: {rf_geos}")
    train = panel[
        (panel["date"] >= pd.Timestamp(train_start))
        & (panel["date"] <= pd.Timestamp(train_end))
    ].copy()
    spend_cols = [c for c in train.columns if c.startswith("spend_") and not c.endswith("_pc")]
    indoor = train["spend_Indoor"] if "spend_Indoor" in train.columns else pd.Series(dtype=float)
    duplicate_grain_rows = int(panel.duplicated(GRAIN_COLS).sum())
    control_columns_missing = sorted(set(CONTROL_VARIATION_COLS) - set(train.columns))
    control_variation_by_year: dict[str, dict[str, dict[str, float | int]]] = {}
    if not control_columns_missing:
        daily_controls = train[["date", *CONTROL_VARIATION_COLS]].drop_duplicates("date")
        for year, group in daily_controls.groupby(daily_controls["date"].dt.year):
            control_variation_by_year[str(int(year))] = {
                column: {
                    "days": int(len(group)),
                    "missing_days": int(pd.to_numeric(group[column], errors="coerce").isna().sum()),
                    "unique_values": int(pd.to_numeric(group[column], errors="coerce").nunique(dropna=True)),
                    "std": float(pd.to_numeric(group[column], errors="coerce").std()),
                }
                for column in CONTROL_VARIATION_COLS
            }
    return {
        "full": {
            "rows": int(len(panel)),
            "columns": int(panel.shape[1]),
            "date_min": panel["date"].min().date().isoformat(),
            "date_max": panel["date"].max().date().isoformat(),
            "geo_n": int(panel["geo_label"].nunique()),
        },
        "train": {
            "train_start": train_start,
            "train_end": train_end,
            "rows": int(len(train)),
            "date_min": train["date"].min().date().isoformat(),
            "date_max": train["date"].max().date().isoformat(),
            "geo_n": int(train["geo_label"].nunique()),
            "segments": sorted((train["network"] + "/" + train["channel"]).dropna().unique().tolist()),
        },
        "dq": {
            "duplicate_grain_rows": duplicate_grain_rows,
            "target_na_cells_train": int(train[[c for c in TARGET_COLS if c in train.columns]].isna().sum().sum()),
            "target_nonpositive_cells_train": int((train[[c for c in TARGET_COLS if c in train.columns]] <= 0).sum().sum()),
            "rf_like_geo_rows": int(panel["geo_label"].astype(str).str.upper().isin(RF_GEO_LABELS).sum()),
            "control_columns_missing": control_columns_missing,
            "control_variation_by_year": control_variation_by_year,
        },
        "media": {
            "spend_cols": spend_cols,
            "indoor_total_rub_train": float(indoor.sum()) if len(indoor) else 0.0,
            "indoor_nonzero_rows_train": int(indoor.gt(0).sum()) if len(indoor) else 0,
        },
        "model_side_policy": {
            "rf_media_policy": "РФ/ДРУГИЕ РЕГИОНЫ is distributed upstream in 00_Data/data_pipeline.py.",
            "geo_scope_policy": "All train-cut model geos keep geo-specific baselines.",
            "indoor_policy": "spend_Indoor is a separate forced channel in the Q1-2026 PyMC notebook.",
        },
    }


def build_media_train_cut_audit(panel: pd.DataFrame, train_start: str, train_end: str) -> pd.DataFrame:
    frame = panel.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    train = frame[
        frame["date"].between(pd.Timestamp(train_start), pd.Timestamp(train_end), inclusive="both")
    ].copy()
    train["segment"] = train["network"].astype(str) + "/" + train["channel"].astype(str)
    spend_cols = [column for column in train.columns if column.startswith("spend_") and not column.endswith("_pc")]
    rows = []
    for segment, sub in train.groupby("segment", dropna=False):
        for spend_col in spend_cols:
            values = pd.to_numeric(sub[spend_col], errors="coerce").fillna(0.0)
            if float(values.sum()) <= 0:
                continue
            active = values.gt(0)
            rows.append(
                {
                    "segment": segment,
                    "channel": spend_col.removeprefix("spend_"),
                    "spend_total_rub": float(values.sum()),
                    "active_rows": int(active.sum()),
                    "active_days": int(sub.loc[active, "date"].nunique()),
                    "active_geos": int(sub.loc[active, "geo_label"].nunique()),
                    "pct_nonzero_rows": float(active.mean() * 100.0),
                    "train_start": train_start,
                    "train_end": train_end,
                }
            )
    return pd.DataFrame(rows).sort_values(["segment", "spend_total_rub"], ascending=[True, False])


def assert_panel_preflight(summary: dict) -> None:
    failures = []
    if int(summary["train"]["rows"]) == 0:
        failures.append("EMPTY_TRAIN_CUT")
    if int(summary["dq"]["duplicate_grain_rows"]) > 0:
        failures.append("DUPLICATE_MODEL_GRAIN")
    if int(summary["dq"]["target_na_cells_train"]) > 0:
        failures.append("MISSING_TARGETS_IN_TRAIN_CUT")
    if int(summary["dq"]["target_nonpositive_cells_train"]) > 0:
        failures.append("NONPOSITIVE_TARGETS_IN_TRAIN_CUT")
    if int(summary["dq"]["rf_like_geo_rows"]) > 0:
        failures.append("UNDISTRIBUTED_RF_GEO")
    if summary["dq"].get("control_columns_missing"):
        failures.append("MISSING_REQUIRED_TEMPORAL_CONTROLS")
    for year, controls in summary["dq"].get("control_variation_by_year", {}).items():
        for column, stats in controls.items():
            if int(stats["missing_days"]) > 0:
                failures.append(f"MISSING_CONTROL_VALUES:{year}:{column}")
            if int(stats["days"]) >= 30 and (
                int(stats["unique_values"]) < 2 or float(stats["std"]) <= 1e-12
            ):
                failures.append(f"CONSTANT_TEMPORAL_CONTROL:{year}:{column}")
    if failures:
        raise ValueError(f"Panel preflight failed closed: {failures}")


def main() -> None:
    args = parse_args()
    panel_path = resolve(args.panel)
    output_dir = resolve(args.output_dir)
    panel = pd.read_parquet(panel_path)
    summary = summarize_panel(panel, args.train_start, args.train_end)
    media_audit = build_media_train_cut_audit(panel, args.train_start, args.train_end)
    summary["panel_path"] = str(panel_path)
    summary["panel_sha256"] = _sha256_path(panel_path)
    summary["output_dir"] = str(output_dir)
    assert_panel_preflight(summary)
    summary["preflight_status"] = "passed"

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.write_summary:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "panel_priors_input_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        media_audit.to_csv(output_dir / "media_train_cut_audit.csv", index=False)


if __name__ == "__main__":
    main()
