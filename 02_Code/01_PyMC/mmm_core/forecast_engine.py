"""Posterior campaign forecast and lightweight optimizer for X5 MMM.

The engine is deliberately model-package driven. It does not learn a new media
model and does not multiply a static ROAS table by budget. It reuses the fitted
PyMC posterior response variables and the same MMM transforms:

raw spend -> per-capita spend -> model scaling -> geo-reset adstock -> tanh
saturation -> posterior beta -> target units.

Scope of this first production-oriented implementation:
- incremental media effect forecast, i.e. campaign scenario minus no-campaign
  counterfactual; baseline and controls cancel out by construction;
- p10/p50/p90 uncertainty from posterior draws;
- optimizer search by repeatedly scoring candidate plans with this same engine.
"""

from __future__ import annotations

import csv
import heapq
import hashlib
import json
import math
import random
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

try:  # xarray is already required by posterior NetCDF inspection.
    import xarray as xr
except Exception as exc:  # pragma: no cover - runtime dependent
    xr = None  # type: ignore
    _XARRAY_IMPORT_ERROR = exc
else:
    _XARRAY_IMPORT_ERROR = None

from .io import ensure_dir, read_json, resolve_path, write_json
from .model_package import sha256_file
from .model_package_reader import ModelPackage
from .serving_semantics import (
    SERVING_CORE_TARGET,
    SERVING_POLICY_VERSION,
    serving_model_inventory,
    validate_serving_model_inventory,
)

TARGETS = ["turnover_per_user", "orders_per_user", "avg_basket"]
DEFAULT_FORECAST_SAMPLES = 300
DEFAULT_OPTIMIZER_SEARCH_CANDIDATES = 80
DEFAULT_OPTIMIZER_FINALISTS = 5
DEFAULT_OPTIMIZER_ALLOCATION_QUANTUM_RUB = 100_000.0
SUPPORT_REL_TOL = 1e-9
SUPPORT_ABS_TOL_RUB = 0.01
BUDGET_RECONCILIATION_REL_TOL = 1e-8
BUDGET_RECONCILIATION_ABS_TOL_RUB = 1.0
ANALOG_DENOMINATOR_MAX_NEAREST_GAP_DAYS = 7

SUPPORT_LEVEL_WITHIN = "within_support"
SUPPORT_LEVEL_ELEVATED = "elevated_p95_p99"
SUPPORT_LEVEL_STRONG = "strong_p99_robust_upper"
SUPPORT_LEVEL_OUTSIDE = "outside_robust_observed_support"
SUPPORT_LEVEL_ORDER = {
    SUPPORT_LEVEL_WITHIN: 0,
    SUPPORT_LEVEL_ELEVATED: 1,
    SUPPORT_LEVEL_STRONG: 2,
    SUPPORT_LEVEL_OUTSIDE: 3,
}


@dataclass(frozen=True)
class SupportAssessment:
    """Evidence-based support status for one future geo x channel spend path."""

    level: str
    flags: tuple[str, ...]
    active_days: int
    future_daily_max_rub: float
    p95_rub: float
    p99_rub: float
    observed_max_rub: float
    robust_upper_rub: float

    @property
    def flags_text(self) -> str:
        return "|".join(self.flags) if self.flags else "OK"


def _finite_nonnegative(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(number, 0.0) if np.isfinite(number) else 0.0


def _robust_support_upper(p95: float, p99: float, observed_max: float, active_days: int) -> float:
    """Limit outlier influence while retaining genuinely observed upper support."""
    p95 = _finite_nonnegative(p95)
    p99 = max(_finite_nonnegative(p99), p95)
    observed_max = max(_finite_nonnegative(observed_max), p99)
    if p99 <= 0:
        return 0.0
    if active_days < 10:
        return p95
    if active_days < 30:
        return p99
    return max(p99, min(observed_max, 1.5 * p99))

SUPPORTED_OPTIMIZER_OBJECTIVES: dict[str, dict[str, str]] = {
    "maximize_incremental_turnover_p50": {
        "target": "turnover_per_user",
        "metric": "total_effect_p50",
        "downside_metric": "total_effect_p10",
        "direction": "maximize",
    },
    "maximize_incremental_turnover_p10": {
        "target": "turnover_per_user",
        "metric": "total_effect_p10",
        "downside_metric": "total_effect_p50",
        "direction": "maximize",
    },
    "maximize_roas_p50": {
        "target": "turnover_per_user",
        "metric": "roas_p50",
        "downside_metric": "roas_p10",
        "direction": "maximize",
    },
}
SUPPORTED_MODEL_RISK_POLICIES = {"balanced", "strict"}

DEFAULT_DECISION_POLICY: dict[str, Any] = {
    "reliability": {
        "full_coverage_min": 0.99,
        "usable_partial_coverage_min": 0.95,
    },
    "materiality": {
        "min_incremental_rto_gain_rub": 1_000_000.0,
        "min_incremental_rto_gain_share": 0.01,
        "min_positive_delta_probability": 0.80,
        "min_moved_budget_rub": 500_000.0,
        "min_moved_budget_share": 0.005,
        "line_item_rounding_rub": 100_000.0,
        "max_p10_degradation_share": 0.01,
        "noninferiority_probability": 0.80,
    },
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    ensure_dir(path.parent)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _safe_id(value: str) -> str:
    out = str(value or "").strip().replace("/", "_").replace("::", "__").replace(" ", "_")
    return out or "run"


def _json_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _compile_optimizer_objective(objective_config: dict[str, Any] | None) -> dict[str, Any]:
    """Turn user-facing objective config into one fail-closed scoring contract."""
    config = objective_config or {}
    primary = str(config.get("primary") or "maximize_incremental_turnover_p50")
    if primary not in SUPPORTED_OPTIMIZER_OBJECTIVES:
        raise ValueError(
            f"Unsupported objective.primary={primary!r}. "
            f"Supported values: {sorted(SUPPORTED_OPTIMIZER_OBJECTIVES)}"
        )
    risk_policy = str(config.get("model_risk_policy") or "balanced")
    if risk_policy not in SUPPORTED_MODEL_RISK_POLICIES:
        raise ValueError(
            f"Unsupported objective.model_risk_policy={risk_policy!r}. "
            f"Supported values: {sorted(SUPPORTED_MODEL_RISK_POLICIES)}"
        )
    return {
        "primary": primary,
        "model_risk_policy": risk_policy,
        **SUPPORTED_OPTIMIZER_OBJECTIVES[primary],
    }


def _compile_decision_policy(policy_config: dict[str, Any] | None) -> dict[str, Any]:
    """Validate recommendation/materiality settings used after MMM scoring."""
    source = policy_config or {}
    reliability = {
        **DEFAULT_DECISION_POLICY["reliability"],
        **(source.get("reliability") or {}),
    }
    materiality = {
        **DEFAULT_DECISION_POLICY["materiality"],
        **(source.get("materiality") or {}),
    }
    for key in ["full_coverage_min", "usable_partial_coverage_min"]:
        reliability[key] = float(reliability[key])
        if not 0.0 <= reliability[key] <= 1.0:
            raise ValueError(f"decision_policy.reliability.{key} must be between 0 and 1")
    if reliability["usable_partial_coverage_min"] > reliability["full_coverage_min"]:
        raise ValueError("usable_partial_coverage_min cannot exceed full_coverage_min")
    for key in [
        "min_incremental_rto_gain_share",
        "min_positive_delta_probability",
        "min_moved_budget_share",
        "max_p10_degradation_share",
        "noninferiority_probability",
    ]:
        materiality[key] = float(materiality[key])
        if not 0.0 <= materiality[key] <= 1.0:
            raise ValueError(f"decision_policy.materiality.{key} must be between 0 and 1")
    for key in [
        "min_incremental_rto_gain_rub",
        "min_moved_budget_rub",
        "line_item_rounding_rub",
    ]:
        materiality[key] = float(materiality[key])
        if materiality[key] < 0.0:
            raise ValueError(f"decision_policy.materiality.{key} cannot be negative")
    return {
        "schema_version": str(source.get("schema_version") or "1.0.0"),
        "policy_id": str(source.get("policy_id") or "optimizer_recommendation_materiality_default"),
        "reliability": reliability,
        "materiality": materiality,
        "recommendation": source.get("recommendation") or {},
        "scenario_5": source.get("scenario_5") or {},
        "scenario_6": source.get("scenario_6") or {},
    }


def _analog_date(dt: date, analog_year: int) -> date:
    try:
        return dt.replace(year=int(analog_year))
    except ValueError:
        if dt.month == 2 and dt.day == 29:
            return date(int(analog_year), 2, 28)
        raise


def _future_controls_analog_year(future_controls: dict[str, Any] | None) -> int | None:
    config = future_controls or {}
    if not config:
        return None
    strategy = str(config.get("strategy") or "historical_analog_period")
    if strategy != "historical_analog_period":
        raise ValueError(f"Unsupported future_controls.strategy={strategy!r}")
    value = config.get("analog_year")
    if value is None:
        raise ValueError("future_controls.analog_year is required for historical_analog_period")
    year = int(value)
    if year < 1900 or year > 2200:
        raise ValueError(f"future_controls.analog_year is outside supported range: {year}")
    return year


def _future_controls_missing_geo_policy(future_controls: dict[str, Any] | None) -> str:
    config = future_controls or {}
    policy = str(config.get("missing_geo_policy") or "fail")
    supported = {"fail", "nearest_available_year_same_geo"}
    if policy not in supported:
        raise ValueError(f"Unsupported future_controls.missing_geo_policy={policy!r}; supported={sorted(supported)}")
    return policy


def _assert_no_cross_campaign_overlap(plan: pd.DataFrame) -> None:
    """Reject nonlinear portfolio overlap until attribution is explicitly modeled."""
    if plan["campaign_name"].nunique() <= 1:
        return
    keys = ["segment", "geo", "channel", "date"]
    funded = plan[pd.to_numeric(plan["budget_rub"], errors="coerce").fillna(0.0).gt(0)].copy()
    overlap = (
        funded.groupby(keys, dropna=False)["campaign_name"]
        .nunique()
        .reset_index(name="campaigns_n")
    )
    overlap = overlap[overlap["campaigns_n"].gt(1)]
    if overlap.empty:
        return
    examples = overlap.head(10).to_dict("records")
    raise ValueError(
        "Independent campaigns overlap in the same segment x geo x channel x date. "
        "Nonlinear saturation must be evaluated as a portfolio; independent campaign sums are unsafe. "
        f"Merge the overlapping rows into one portfolio brief or separate the dates. Examples: {examples}"
    )


def _runtime_lineage(model_run_dir: str | Path, *, purpose: str) -> dict[str, Any]:
    run_dir = resolve_path(model_run_dir)
    code_files = [
        Path(__file__).resolve(),
        Path(__file__).with_name("campaign_plan.py").resolve(),
        Path(__file__).with_name("model_package_reader.py").resolve(),
    ]
    if purpose == "forecast":
        code_files.append(Path(__file__).resolve().parents[2] / "03_AC_forecast" / "ac_forecast.py")
    elif purpose == "optimizer":
        code_files.extend(
            [
                Path(__file__).resolve().parents[2] / "02_Budget_optimizer" / "budget_optimizer.py",
                Path(__file__).resolve().parents[2] / "02_Budget_optimizer" / "marketer_report.py",
            ]
        )
    else:
        raise ValueError(f"Unsupported lineage purpose: {purpose}")
    package_files = [
        "model_manifest.json",
        "capability_matrix.csv",
        "gate_results.csv",
        "posterior_index.json",
        "fit_design_metadata.json",
        "fit_design_media_scales.csv",
        "target_denominator_metadata.csv",
        "historical_support_bounds.csv",
        "adstock_warm_start.csv",
    ]
    return {
        "code_sha256": {path.name: sha256_file(path) for path in code_files},
        "model_artifact_sha256": {name: sha256_file(run_dir / name) for name in package_files},
    }


def _parse_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.to_datetime(value).date()


def _date_iso(value: Any) -> str:
    return _parse_date(value).isoformat()


def _split_segment(segment: str) -> tuple[str, str]:
    if "/" not in segment:
        return segment, ""
    return tuple(segment.split("/", 1))  # type: ignore[return-value]


def _make_fit_key(segment: str, target: str) -> str:
    return f"{segment}::{target}"


def _channel_to_spend_col(channel: str) -> str:
    return channel if channel.startswith("spend_") else f"spend_{channel}"


def _spend_col_to_channel(spend_col: str) -> str:
    return spend_col.removeprefix("spend_")


def _positive_p95(values: Iterable[float], default: float = 1.0) -> float:
    vals = np.asarray(list(values), dtype=float)
    vals = vals[np.isfinite(vals) & (vals > 0)]
    if len(vals) >= 20:
        return float(np.percentile(vals, 95))
    if len(vals) > 0:
        return float(np.max(vals))
    return float(default)


def _mode_or_first(values: Iterable[Any]) -> Any:
    vals = pd.Series(list(values)).dropna().astype(str)
    if vals.empty:
        return np.nan
    mode = vals.mode()
    return mode.iloc[0] if not mode.empty else vals.iloc[0]


def _load_run_config(run_dir: Path) -> dict[str, Any]:
    cfg = read_json(run_dir / "run_config.json")
    if not isinstance(cfg, dict):
        raise FileNotFoundError(f"run_config.json missing or invalid in {run_dir}")
    return cfg


def load_model_panel(run_dir: Path) -> pd.DataFrame:
    """Load panel and apply the same high-level filters as the Q1 notebook."""
    config = _load_run_config(run_dir)
    panel_path = resolve_path(config["panel_path"])
    panel = pd.read_parquet(panel_path).copy()
    panel["date"] = pd.to_datetime(panel["date"])

    train_start = pd.to_datetime(config.get("train_start") or panel["date"].min())
    train_end = pd.to_datetime(config.get("train_end") or panel["date"].max())
    panel = panel[(panel["date"] >= train_start) & (panel["date"] <= train_end)].copy()

    # Rebuild segment-level grouped media exactly from run_config.
    grouping = config.get("media_grouping_config") or {}
    if grouping:
        group_cols = sorted({g for groups in grouping.values() for g in groups.keys()})
        for col in group_cols:
            panel[col] = 0.0
        for seg_key, groups in grouping.items():
            network, channel = _split_segment(seg_key)
            mask = (panel["network"] == network) & (panel["channel"] == channel)
            for group_col, input_cols in groups.items():
                available = [c for c in input_cols if c in panel.columns]
                if available:
                    panel.loc[mask, group_col] = panel.loc[mask, available].sum(axis=1)

    flag_cols = [c for c in panel.columns if c.endswith("_anomaly_flag")]
    if flag_cols:
        panel = panel[~panel[flag_cols].any(axis=1)].copy()

    thin_threshold = 50
    if "unique_users" in panel.columns:
        thin_keys = panel.groupby(["geo_label", "network", "channel"])["unique_users"].median() < thin_threshold
        thin_index = thin_keys[thin_keys].index
        if len(thin_index):
            idx = panel.set_index(["geo_label", "network", "channel"]).index
            panel = panel[~idx.isin(thin_index)].copy()
    return panel.reset_index(drop=True)


def _fit_beta_structure(config: dict[str, Any], segment: str, target: str) -> str:
    for item in config.get("beta_structure_overrides_by_fit") or []:
        if item.get("fit_key") == _make_fit_key(segment, target):
            return item.get("beta_structure") or ""
    return (config.get("beta_structure_by_target") or {}).get(target, "")


def _tier_pooled_channels(config: dict[str, Any], segment: str, target: str) -> list[str]:
    out: list[str] = []
    for item in config.get("beta_tier_pooled_channels_by_fit") or []:
        if item.get("fit_key") == _make_fit_key(segment, target):
            out.extend(item.get("pooled_channels") or [])
    return sorted(set(out))


def _extract_geo_tiers(seg: pd.DataFrame, geos: list[str], geo_idx: np.ndarray, config: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, list[str], str]:
    tier_col = str(config.get("market_size_tier_col") or "market_size_tier")
    preferred = ["small", "medium", "large"]
    if tier_col in seg.columns and seg[tier_col].notna().any():
        geo_tier = seg.groupby("geo_label")[tier_col].agg(_mode_or_first).reindex(geos)
        present = [str(x) for x in geo_tier.dropna().unique()]
        names = [x for x in preferred if x in present] + sorted([x for x in present if x not in preferred])
        if not names:
            names = ["all"]
        geo_tier = geo_tier.fillna(names[0]).astype(str)
        tier_map = {name: i for i, name in enumerate(names)}
        geo_tier_idx = geo_tier.map(tier_map).astype(int).to_numpy()
        return geo_tier_idx, geo_tier_idx[geo_idx], names, f"panel_column:{tier_col}"

    pop = pd.Series(np.maximum(seg["population_k"].values.astype(float), 1e-3)).groupby(geo_idx).median().reindex(range(len(geos))).values
    ranks = pd.Series(pop).rank(method="first")
    tier_count = int(config.get("media_tier_count") or 3)
    tier_idx = pd.qcut(ranks, q=min(tier_count, len(ranks)), labels=False, duplicates="drop").astype(int).to_numpy()
    n_actual = int(tier_idx.max()) + 1 if len(tier_idx) else 1
    names = ["small", "medium", "large"] if n_actual == 3 else [f"tier_{i}" for i in range(n_actual)]
    return tier_idx, tier_idx[geo_idx], names, str(config.get("market_size_tier_fallback") or "population_k_qcut")


def _compute_media_scaling(
    X_spend_pc: np.ndarray,
    geo_idx: np.ndarray,
    clean_mask: np.ndarray,
    geos: list[str],
    channels: list[str],
    geo_tier_idx: np.ndarray,
    tier_names: list[str],
    config: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[dict[str, Any]]]:
    mode = str(config.get("media_scaling_mode") or "global_p95")
    n_obs, n_media = X_spend_pc.shape
    n_geo = len(geos)
    n_tiers = len(tier_names)
    tier_min_nz = int(config.get("media_tier_scale_min_nz") or 20)
    tier_full_nz = max(int(config.get("media_tier_scale_full_nz") or 120), tier_min_nz)
    tier_floor = float(config.get("media_tier_scale_ratio_floor") or 0.5)
    tier_ceil = float(config.get("media_tier_scale_ratio_ceil") or 2.0)
    geo_min_nz = int(config.get("media_geo_scale_min_nz") or 8)
    geo_full_nz = max(int(config.get("media_geo_scale_full_nz") or 30), geo_min_nz)
    geo_floor = float(config.get("media_geo_scale_ratio_floor") or 0.25)
    geo_ceil = float(config.get("media_geo_scale_ratio_ceil") or 4.0)

    x_scale_global = np.zeros(n_media)
    x_scale_geo = np.zeros((n_geo, n_media))
    x_scale_tier = np.zeros((n_tiers, n_media))
    geo_nz = np.zeros((n_geo, n_media), dtype=int)
    tier_nz = np.zeros((n_tiers, n_media), dtype=int)

    for m in range(n_media):
        global_scale = max(_positive_p95(X_spend_pc[clean_mask, m], default=1.0), 1e-8)
        x_scale_global[m] = global_scale
        if mode == "tier_p95_shrunk":
            for t in range(n_tiers):
                tier_geo_codes = np.where(geo_tier_idx == t)[0]
                tier_mask = np.isin(geo_idx, tier_geo_codes) & clean_mask
                vals = X_spend_pc[tier_mask, m]
                nz = vals[np.isfinite(vals) & (vals > 0)]
                tier_nz[t, m] = len(nz)
                raw = _positive_p95(nz, default=global_scale) if len(nz) >= tier_min_nz else global_scale
                w = min(max(len(nz), 0) / tier_full_nz, 1.0)
                tier_scale = float(np.exp((1.0 - w) * np.log(global_scale) + w * np.log(max(raw, 1e-8))))
                tier_scale = float(np.clip(tier_scale, global_scale * tier_floor, global_scale * tier_ceil))
                x_scale_tier[t, m] = max(tier_scale, 1e-8)
            x_scale_geo[:, m] = x_scale_tier[geo_tier_idx, m]
        else:
            for g in range(n_geo):
                mask = (geo_idx == g) & clean_mask
                vals = X_spend_pc[mask, m]
                nz = vals[np.isfinite(vals) & (vals > 0)]
                geo_nz[g, m] = len(nz)
                if mode == "global_p95":
                    local = global_scale
                else:
                    raw = _positive_p95(nz, default=global_scale) if len(nz) >= geo_min_nz else global_scale
                    if mode == "geo_p95_shrunk":
                        w = min(max(len(nz), 0) / geo_full_nz, 1.0)
                        local = float(np.exp((1.0 - w) * np.log(global_scale) + w * np.log(max(raw, 1e-8))))
                    elif mode == "geo_p95":
                        local = raw
                    else:
                        local = global_scale
                    local = float(np.clip(local, global_scale * geo_floor, global_scale * geo_ceil))
                x_scale_geo[g, m] = max(local, 1e-8)
            x_scale_tier[:, m] = global_scale
    x_scale_obs = x_scale_geo[geo_idx, :] if mode != "global_p95" else np.broadcast_to(x_scale_global[None, :], (n_obs, n_media)).copy()
    rows: list[dict[str, Any]] = []
    for m, channel in enumerate(channels):
        for g, geo in enumerate(geos):
            tier_name = tier_names[int(geo_tier_idx[g])] if len(tier_names) else ""
            rows.append({
                "channel": channel,
                "geo_label": geo,
                "market_size_tier": tier_name,
                "x_scale": float(x_scale_geo[g, m]),
                "x_scale_global": float(x_scale_global[m]),
                "x_scale_ratio_to_global": float(x_scale_geo[g, m] / max(x_scale_global[m], 1e-8)),
            })
    return x_scale_obs, x_scale_geo, x_scale_tier, x_scale_global, rows


def _normalized_adstock(x: np.ndarray, alpha: float, l_max: int, warm_start: np.ndarray | None = None) -> np.ndarray:
    weights = alpha ** np.arange(l_max + 1, dtype=float)
    weights = weights / max(weights.sum(), 1e-12)
    x = np.asarray(x, dtype=float)
    out = np.zeros_like(x)
    if warm_start is None:
        history = np.zeros(l_max, dtype=float)
    else:
        history = np.asarray(warm_start, dtype=float)[-l_max:]
        if len(history) < l_max:
            history = np.pad(history, (l_max - len(history), 0))
    extended = np.concatenate([history, x])
    offset = len(history)
    for i in range(len(x)):
        window = extended[offset + i - np.arange(l_max + 1)]
        out[i] = float(np.sum(weights * window))
    return out


def _incremental_saturated_response(
    x: np.ndarray,
    *,
    alpha: float,
    lam: float,
    l_max: int,
    warm_start: np.ndarray | None,
) -> np.ndarray:
    """Campaign response minus a counterfactual with the same historical carryover."""
    plan_adstock = _normalized_adstock(x, alpha, l_max, warm_start=warm_start)
    counterfactual_adstock = _normalized_adstock(
        np.zeros_like(np.asarray(x, dtype=float)),
        alpha,
        l_max,
        warm_start=warm_start,
    )
    return np.tanh(lam * plan_adstock / 2.0) - np.tanh(lam * counterfactual_adstock / 2.0)


def _build_lag_tail(X_scaled: np.ndarray, geo_idx: np.ndarray, geos: list[str], channels: list[str], l_max: int, train_end: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for g, geo in enumerate(geos):
        ix = np.where(geo_idx == g)[0]
        if len(ix) == 0:
            continue
        Xg = X_scaled[ix, :]
        tail = Xg[-l_max:, :]
        pad = np.zeros((max(l_max - len(tail), 0), Xg.shape[1]))
        tail = np.vstack([pad, tail]) if len(pad) else tail
        for m, channel in enumerate(channels):
            for lag in range(1, l_max + 1):
                rows.append({
                    "geo_label": geo,
                    "channel": channel,
                    "lag": lag,
                    "scaled_spend": float(tail[-lag, m]),
                    "as_of_date": train_end,
                    "source": "training_tail",
                })
    return rows


def export_fit_design_metadata(run_dir: str | Path, *, force: bool = True) -> dict[str, Any]:
    """Rebuild and persist the transform metadata needed by forecast/optimizer."""
    run_dir = resolve_path(run_dir)
    package = ModelPackage.from_run_dir(run_dir, require_posterior_ready=True)
    config = _load_run_config(run_dir)
    panel = load_model_panel(run_dir)
    train_end = str(config.get("train_end") or "")
    l_max = int((config.get("cfg") or {}).get("l_max") or 14)

    fit_meta: dict[str, Any] = {}
    media_scale_rows: list[dict[str, Any]] = []
    support_rows: list[dict[str, Any]] = []
    denominator_rows: list[dict[str, Any]] = []
    warm_rows: list[dict[str, Any]] = []

    denominator_base = panel[[
        "date", "geo_label", "network", "channel", "population_k", "market_size_tier",
        "unique_users", "orders_cnt", "turnover_total", "avg_basket",
    ]].copy()
    denominator_base["segment"] = denominator_base["network"].astype(str) + "/" + denominator_base["channel"].astype(str)
    denominator_base["date"] = pd.to_datetime(denominator_base["date"]).dt.date.astype(str)
    denominator_rows = denominator_base[[
        "segment", "geo_label", "date", "population_k", "market_size_tier",
        "unique_users", "orders_cnt", "turnover_total", "avg_basket",
    ]].to_dict("records")

    for fit_key, channels in (package.manifest.get("channels_by_segment_target") or {}).items():
        if "::" not in fit_key:
            continue
        segment, target = fit_key.split("::", 1)
        posterior_file = None
        for row in package.capability_rows:
            if row.get("fit_key") == fit_key and row.get("posterior_file"):
                posterior_file = row.get("posterior_file")
                break
        if not posterior_file:
            continue
        post_path = run_dir / posterior_file
        if xr is None:
            raise RuntimeError(f"xarray is required to inspect posterior files: {_XARRAY_IMPORT_ERROR!r}")
        with xr.open_dataset(post_path, group="posterior") as ds:
            posterior_channels = [str(v) for v in ds.coords["channel"].values] if "channel" in ds.coords else list(channels)
            posterior_geos = [str(v) for v in ds.coords["geo_label"].values] if "geo_label" in ds.coords else []
            posterior_tiers = [str(v) for v in ds.coords["market_size_tier"].values] if "market_size_tier" in ds.coords else []
            posterior_ctrl = [str(v) for v in ds.coords["ctrl"].values] if "ctrl" in ds.coords else []
        channels = posterior_channels
        spend_active = [_channel_to_spend_col(ch) for ch in channels]
        network, ch_type = _split_segment(segment)
        seg = panel[(panel["network"] == network) & (panel["channel"] == ch_type)].copy()
        seg = seg.sort_values(["geo_label", "date"]).reset_index(drop=True)
        if posterior_geos:
            seg = seg[seg["geo_label"].isin(posterior_geos)].copy()
            geos = posterior_geos
        else:
            geos = sorted(seg["geo_label"].dropna().astype(str).unique())
        if target not in seg.columns or seg.empty:
            continue
        geo_idx = pd.Categorical(seg["geo_label"], categories=geos).codes.astype(int)
        if (geo_idx < 0).any():
            seg = seg[geo_idx >= 0].copy()
            geo_idx = pd.Categorical(seg["geo_label"], categories=geos).codes.astype(int)
        geo_tier_idx, obs_tier_idx, tier_names, tier_source = _extract_geo_tiers(seg, geos, geo_idx, config)
        if posterior_tiers:
            tier_names = posterior_tiers
        Y_raw = seg[target].astype(float).values
        clean_mask = ~seg["anomaly_period_jul2025"].astype(bool).values if "anomaly_period_jul2025" in seg.columns else np.ones(len(seg), dtype=bool)
        if clean_mask.sum() < 0.5 * len(seg):
            clean_mask = np.ones(len(seg), dtype=bool)
        if target == "orders_per_user":
            y_offset = float(np.mean(Y_raw))
            y_scale = float(max(np.std(Y_raw), 1e-8))
            y_scaling = "zscore"
        else:
            y_offset = 0.0
            y_scale = float(max(np.percentile(np.abs(Y_raw[clean_mask]), 95), 1e-8))
            y_scaling = "p95abs"
        pop = np.maximum(seg["population_k"].astype(float).values, 1e-3)
        X_raw = seg[spend_active].astype(float).values
        X_pc = X_raw / pop[:, None]
        x_scale_obs, x_scale_geo, x_scale_tier, x_scale_global, scale_rows = _compute_media_scaling(
            X_pc, geo_idx, clean_mask, geos, channels, geo_tier_idx, tier_names, config
        )
        X_scaled = X_pc / np.maximum(x_scale_obs, 1e-8)

        for row in scale_rows:
            row.update({"fit_key": fit_key, "segment": segment, "target": target})
            media_scale_rows.append(row)

        for m, channel_name in enumerate(channels):
            spend_col = spend_active[m]
            for scope, groups in [("geo", [(geo, np.where(geo_idx == g)[0]) for g, geo in enumerate(geos)])]:
                for geo, ix in groups:
                    vals = X_raw[ix, m]
                    nz = vals[np.isfinite(vals) & (vals > 0)]
                    support_rows.append({
                        "fit_key": fit_key,
                        "segment": segment,
                        "target": target,
                        "channel": channel_name,
                        "scope": scope,
                        "geo_label": geo,
                        "market_size_tier": tier_names[int(geo_tier_idx[geos.index(geo)])] if geo in geos and len(tier_names) else "",
                        "obs_n": int(len(vals)),
                        "active_days": int((vals > 0).sum()),
                        "spend_total_rub": float(np.nansum(vals)),
                        "daily_spend_p50_rub": float(np.percentile(nz, 50)) if len(nz) else 0.0,
                        "daily_spend_p95_rub": float(np.percentile(nz, 95)) if len(nz) else 0.0,
                        "daily_spend_p99_rub": float(np.percentile(nz, 99)) if len(nz) else 0.0,
                        "daily_spend_max_rub": float(np.max(nz)) if len(nz) else 0.0,
                        "pct_nonzero_rows": float((vals > 0).mean() * 100) if len(vals) else 0.0,
                    })
        warm = _build_lag_tail(X_scaled, geo_idx, geos, channels, l_max, train_end)
        for row in warm:
            row.update({"fit_key": fit_key, "segment": segment, "target": target})
            warm_rows.append(row)

        geo_to_tier = {geo: tier_names[int(geo_tier_idx[i])] if len(tier_names) else "" for i, geo in enumerate(geos)}
        fit_meta[fit_key] = {
            "segment": segment,
            "target": target,
            "posterior_file": posterior_file,
            "channels": channels,
            "spend_active": spend_active,
            "geos": geos,
            "market_size_tiers": tier_names,
            "geo_to_tier": geo_to_tier,
            "market_size_tier_source": tier_source,
            "ctrl_active": posterior_ctrl,
            "y_scale": y_scale,
            "y_offset": y_offset,
            "y_scaling": y_scaling,
            "l_max": l_max,
            "media_scaling_mode": config.get("media_scaling_mode"),
            "beta_structure": _fit_beta_structure(config, segment, target),
            "beta_tier_pooled_channels": _tier_pooled_channels(config, segment, target),
            "train_rows_n": int(len(seg)),
            "train_start": str(config.get("train_start")),
            "train_end": str(config.get("train_end")),
            "target_unit": {
                "turnover_per_user": "rub_per_user",
                "orders_per_user": "orders_per_user",
                "avg_basket": "rub_per_order",
            }.get(target, "target_unit"),
        }

    metadata = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(run_dir),
        "package_stage": package.package_stage,
        "panel_path": config.get("panel_path"),
        "train_start": config.get("train_start"),
        "train_end": config.get("train_end"),
        "l_max": l_max,
        "forecast_semantics": "incremental_media_effect_vs_no_campaign_counterfactual",
        "warm_start_policy": {
            "default_future_policy": "zero_if_forecast_starts_after_train_end_plus_l_max",
            "training_tail_available": True,
            "training_tail_file": "adstock_warm_start.csv",
        },
        "fits": fit_meta,
        "artifact_files": {
            "media_scale_metadata": "fit_design_media_scales.csv",
            "historical_support_bounds": "historical_support_bounds.csv",
            "target_denominator_metadata": "target_denominator_metadata.csv",
            "adstock_warm_start": "adstock_warm_start.csv",
        },
    }
    write_json(run_dir / "fit_design_metadata.json", metadata)
    _write_csv(run_dir / "fit_design_media_scales.csv", media_scale_rows)
    _write_csv(run_dir / "historical_support_bounds.csv", support_rows)
    _write_csv(run_dir / "target_denominator_metadata.csv", denominator_rows)
    _write_csv(run_dir / "adstock_warm_start.csv", warm_rows)
    return {
        "run_dir": str(run_dir),
        "fit_design_metadata": str(run_dir / "fit_design_metadata.json"),
        "fits_n": len(fit_meta),
        "media_scale_rows_n": len(media_scale_rows),
        "historical_support_rows_n": len(support_rows),
        "denominator_rows_n": len(denominator_rows),
        "adstock_warm_rows_n": len(warm_rows),
    }


@dataclass
class ForecastEngine:
    run_dir: Path
    package: ModelPackage
    metadata: dict[str, Any]
    media_scales: pd.DataFrame
    denominators: pd.DataFrame
    support_bounds: pd.DataFrame
    warm_start: pd.DataFrame
    capability: pd.DataFrame
    _denominator_cache: dict[tuple[str, str, str, str, str], dict[str, Any]] = field(default_factory=dict, init=False, repr=False)
    _denominator_exact: dict[tuple[str, str, str], dict[str, float]] = field(default_factory=dict, init=False, repr=False)
    _denominator_geo: dict[tuple[str, str], dict[str, float]] = field(default_factory=dict, init=False, repr=False)
    _denominator_segment: dict[str, dict[str, float]] = field(default_factory=dict, init=False, repr=False)
    _denominator_geo_year: dict[tuple[str, str, int], list[tuple[date, dict[str, float]]]] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _posterior_cache: dict[tuple[str, int, int], dict[str, Any]] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        df = self.denominators.copy()
        df["segment"] = df["segment"].astype(str)
        df["geo_label"] = df["geo_label"].astype(str)
        df["date"] = df["date"].astype(str)
        for col in ["population_k", "unique_users", "orders_cnt"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        if "market_size_tier" not in df.columns:
            df["market_size_tier"] = ""

        def _records_to_denominator_map(grouped: pd.DataFrame, key_cols: list[str]) -> dict[Any, dict[str, float]]:
            out: dict[Any, dict[str, float]] = {}
            for _, row in grouped.iterrows():
                key_values = tuple(str(row[col]) for col in key_cols)
                key: Any = key_values[0] if len(key_values) == 1 else key_values
                out[key] = {
                    "population_k": float(row["population_k"]) if pd.notna(row["population_k"]) else 1.0,
                    "unique_users": float(max(row["unique_users"], 1.0)) if pd.notna(row["unique_users"]) else 1.0,
                    "orders_cnt": float(max(row["orders_cnt"], 1.0)) if pd.notna(row["orders_cnt"]) else 1.0,
                    "market_size_tier": str(row["market_size_tier"] or ""),
                }
            return out

        agg = {
            "population_k": ("population_k", "median"),
            "unique_users": ("unique_users", "median"),
            "orders_cnt": ("orders_cnt", "median"),
            "market_size_tier": ("market_size_tier", _mode_or_first),
        }
        exact = df.groupby(["segment", "geo_label", "date"], dropna=False).agg(**agg).reset_index()
        by_geo = df.groupby(["segment", "geo_label"], dropna=False).agg(**agg).reset_index()
        by_segment = df.groupby(["segment"], dropna=False).agg(**agg).reset_index()
        self._denominator_exact = _records_to_denominator_map(exact, ["segment", "geo_label", "date"])
        self._denominator_geo = _records_to_denominator_map(by_geo, ["segment", "geo_label"])
        self._denominator_segment = _records_to_denominator_map(by_segment, ["segment"])
        for key, value in self._denominator_exact.items():
            segment, geo, date_text = key
            parsed_date = date.fromisoformat(date_text)
            self._denominator_geo_year.setdefault((segment, geo, parsed_date.year), []).append(
                (parsed_date, value)
            )
        for values in self._denominator_geo_year.values():
            values.sort(key=lambda item: item[0])

    @classmethod
    def from_run_dir(
        cls,
        run_dir: str | Path,
        *,
        auto_export: bool = True,
        validate_package_lineage: bool = True,
    ) -> "ForecastEngine":
        run_dir = resolve_path(run_dir)
        if auto_export and not (run_dir / "fit_design_metadata.json").exists():
            export_fit_design_metadata(run_dir)
        package = ModelPackage.from_run_dir(
            run_dir,
            require_posterior_ready=True,
            validate_hash=validate_package_lineage,
        )
        metadata = read_json(run_dir / "fit_design_metadata.json") or {}
        media_scales = pd.read_csv(run_dir / "fit_design_media_scales.csv")
        denominators = pd.read_csv(run_dir / "target_denominator_metadata.csv")
        support = pd.read_csv(run_dir / "historical_support_bounds.csv")
        warm = pd.read_csv(run_dir / "adstock_warm_start.csv")
        capability = pd.DataFrame(package.capability_rows)
        return cls(run_dir, package, metadata, media_scales, denominators, support, warm, capability)

    def _capability_row(self, segment: str, target: str, channel: str) -> dict[str, Any]:
        rows = self.capability[
            (self.capability["segment"] == segment)
            & (self.capability["target"] == target)
            & (self.capability["channel"] == channel)
        ]
        return rows.iloc[0].to_dict() if not rows.empty else {}

    def _denominator_for(
        self,
        segment: str,
        geo: str,
        dt: date,
        *,
        analog_year: int | None = None,
        missing_geo_policy: str = "fail",
    ) -> dict[str, Any]:
        cache_key = (
            str(segment),
            str(geo),
            dt.isoformat(),
            str(analog_year or "previous_year"),
            missing_geo_policy,
        )
        if cache_key in self._denominator_cache:
            return self._denominator_cache[cache_key]
        analog = _analog_date(dt, analog_year) if analog_year is not None else _analog_date(dt, dt.year - 1)
        exact = self._denominator_exact.get((str(segment), str(geo), analog.isoformat()))
        analog_year_used = analog.year
        if analog_year is not None and exact is None:
            available_years = sorted(
                year
                for seg, geo_label, year in self._denominator_geo_year
                if seg == str(segment) and geo_label == str(geo)
            )
            candidate_years = [int(analog_year)]
            if missing_geo_policy == "nearest_available_year_same_geo":
                candidate_years.extend(year for year in available_years if year != int(analog_year))
            viable: list[tuple[int, int, int, date, dict[str, float]]] = []
            for candidate_year in candidate_years:
                target_date = _analog_date(dt, candidate_year)
                candidates = self._denominator_geo_year.get(
                    (str(segment), str(geo), candidate_year)
                ) or []
                if not candidates:
                    continue
                nearest_date, nearest_value = min(
                    candidates,
                    key=lambda item: abs((item[0] - target_date).days),
                )
                gap_days = abs((nearest_date - target_date).days)
                if gap_days <= ANALOG_DENOMINATOR_MAX_NEAREST_GAP_DAYS:
                    viable.append(
                        (
                            abs(candidate_year - int(analog_year)),
                            gap_days,
                            candidate_year,
                            nearest_date,
                            nearest_value,
                        )
                    )
            if viable:
                _, gap_days, analog_year_used, nearest_date, nearest_value = min(
                    viable,
                    key=lambda item: (item[0], item[1], item[2]),
                )
                analog = _analog_date(dt, analog_year_used)
                exact = dict(nearest_value)
                exact["denominator_analog_date_used"] = nearest_date.isoformat()
                exact["denominator_fallback_gap_days"] = gap_days
            if exact is None:
                raise ValueError(
                    "Configured historical analog denominator is missing; fallback would change forecast semantics. "
                    f"segment={segment!r}, geo={geo!r}, future_date={dt.isoformat()}, "
                    f"analog_date={analog.isoformat()}, max_nearest_gap_days={ANALOG_DENOMINATOR_MAX_NEAREST_GAP_DAYS}"
                )
        value = exact or self._denominator_geo.get((str(segment), str(geo))) or self._denominator_segment.get(str(segment))
        if value is None:
            raise ValueError(
                f"No denominator metadata for segment={segment!r}, geo={geo!r}, date={dt.isoformat()}"
            )
        value = dict(value)
        value.setdefault("denominator_analog_date_used", analog.isoformat())
        value.setdefault("denominator_fallback_gap_days", 0)
        value["denominator_analog_year_used"] = analog_year_used
        value["denominator_fallback_years"] = abs(analog_year_used - int(analog_year or analog_year_used))
        self._denominator_cache[cache_key] = value
        return value

    def _x_scale(self, fit_key: str, geo: str, channel: str, fallback_tier: str = "") -> float:
        df = self.media_scales
        rows = df[(df["fit_key"] == fit_key) & (df["geo_label"] == geo) & (df["channel"] == channel)]
        if rows.empty and fallback_tier:
            rows = df[(df["fit_key"] == fit_key) & (df["market_size_tier"] == fallback_tier) & (df["channel"] == channel)]
        if rows.empty:
            rows = df[(df["fit_key"] == fit_key) & (df["channel"] == channel)]
        if rows.empty:
            return 1.0
        return float(np.nanmedian(rows["x_scale"].astype(float)))

    def _support_assessment(
        self,
        fit_key: str,
        geo: str,
        channel: str,
        daily_spend_values: np.ndarray,
    ) -> SupportAssessment:
        rows = self.support_bounds[
            (self.support_bounds["fit_key"] == fit_key)
            & (self.support_bounds["geo_label"] == geo)
            & (self.support_bounds["channel"] == channel)
        ]
        flags: list[str] = []
        max_future = float(np.nanmax(daily_spend_values)) if len(daily_spend_values) else 0.0
        if rows.empty:
            flags.append("NO_HISTORICAL_SUPPORT_ROW")
            return SupportAssessment(
                level=SUPPORT_LEVEL_OUTSIDE if max_future > 0 else SUPPORT_LEVEL_WITHIN,
                flags=tuple(flags),
                active_days=0,
                future_daily_max_rub=max_future,
                p95_rub=0.0,
                p99_rub=0.0,
                observed_max_rub=0.0,
                robust_upper_rub=0.0,
            )

        row = rows.iloc[0]
        p95 = _finite_nonnegative(row.get("daily_spend_p95_rub"))
        p99 = max(_finite_nonnegative(row.get("daily_spend_p99_rub")), p95)
        observed_max = max(_finite_nonnegative(row.get("daily_spend_max_rub")), p99)
        active_days = int(_finite_nonnegative(row.get("active_days")))
        robust_upper = _robust_support_upper(p95, p99, observed_max, active_days)
        if active_days < 10:
            flags.append("SPARSE_HISTORICAL_ACTIVE_DAYS_LT_10")
        if p95 <= 0 and max_future > 0:
            flags.append("NO_POSITIVE_HISTORICAL_SPEND_FOR_CELL")
            level = SUPPORT_LEVEL_OUTSIDE
        else:
            p95_tol = max(SUPPORT_ABS_TOL_RUB, abs(p95) * SUPPORT_REL_TOL)
            p99_tol = max(SUPPORT_ABS_TOL_RUB, abs(p99) * SUPPORT_REL_TOL)
            robust_tol = max(SUPPORT_ABS_TOL_RUB, abs(robust_upper) * SUPPORT_REL_TOL)
            if max_future <= p95 + p95_tol:
                level = SUPPORT_LEVEL_WITHIN
            elif max_future <= p99 + p99_tol:
                level = SUPPORT_LEVEL_ELEVATED
                flags.append("FUTURE_DAILY_SPEND_P95_TO_P99")
            elif max_future <= robust_upper + robust_tol:
                level = SUPPORT_LEVEL_STRONG
                flags.append("FUTURE_DAILY_SPEND_P99_TO_ROBUST_UPPER")
            else:
                level = SUPPORT_LEVEL_OUTSIDE
                flags.append("FUTURE_DAILY_SPEND_GT_ROBUST_HIST_UPPER")
        return SupportAssessment(
            level=level,
            flags=tuple(flags),
            active_days=active_days,
            future_daily_max_rub=max_future,
            p95_rub=p95,
            p99_rub=p99,
            observed_max_rub=observed_max,
            robust_upper_rub=robust_upper,
        )

    def _support_flags(self, fit_key: str, geo: str, channel: str, daily_spend_values: np.ndarray) -> str:
        """Backward-compatible text view of the structured support assessment."""
        return self._support_assessment(fit_key, geo, channel, daily_spend_values).flags_text

    def _warm_start_for(self, fit_key: str, geo: str, channel: str, start: date, l_max: int) -> np.ndarray | None:
        rows = self.warm_start[
            (self.warm_start["fit_key"] == fit_key)
            & (self.warm_start["geo_label"] == geo)
            & (self.warm_start["channel"] == channel)
        ].copy()
        if rows.empty:
            return None
        as_of = pd.to_datetime(rows["as_of_date"], errors="coerce").dt.date.max()
        if as_of is None or pd.isna(as_of):
            return None
        gap_days = (start - as_of).days
        if gap_days <= 0 or gap_days > l_max:
            return None
        rows["lag"] = pd.to_numeric(rows["lag"], errors="coerce")
        rows["scaled_spend"] = pd.to_numeric(rows["scaled_spend"], errors="coerce")
        rows = rows.dropna(subset=["lag", "scaled_spend"]).sort_values("lag", ascending=False)
        history = rows["scaled_spend"].to_numpy(dtype=float)
        if gap_days > 1:
            history = np.concatenate([history, np.zeros(gap_days - 1, dtype=float)])
        return history[-l_max:]

    def _posterior_samples(self, fit_meta: dict[str, Any], n_samples: int, seed: int) -> dict[str, Any]:
        if xr is None:
            raise RuntimeError(f"xarray is required for posterior simulation: {_XARRAY_IMPORT_ERROR!r}")
        path = self.run_dir / fit_meta["posterior_file"]
        cache_key = (str(path), int(n_samples), int(seed))
        cached = self._posterior_cache.get(cache_key)
        if cached is not None:
            return cached
        with xr.open_dataset(path, group="posterior") as ds:
            stacked: dict[str, Any] = {}
            n_total = int(ds.sizes.get("chain", 1) * ds.sizes.get("draw", 1))
            rng = np.random.default_rng(seed)
            idx = rng.choice(n_total, size=min(n_samples, n_total), replace=False)
            stacked["sample_idx"] = idx
            stacked["n_total"] = n_total
            for var in ["alpha", "lam", "beta"]:
                da = ds[var].stack(sample=("chain", "draw")).transpose(..., "sample")
                stacked[var] = np.asarray(da.isel(sample=idx).values)
                stacked[f"{var}_dims"] = da.dims
        self._posterior_cache[cache_key] = stacked
        return stacked

    def _beta_value(self, beta_arr: np.ndarray, beta_dims: tuple[str, ...], sample_pos: int, channel_idx: int, geo_idx: int, tier_idx: int) -> float:
        dims = list(beta_dims)
        if dims == ["channel", "sample"]:
            return float(beta_arr[channel_idx, sample_pos])
        if dims == ["channel", "market_size_tier", "sample"]:
            return float(beta_arr[channel_idx, tier_idx, sample_pos])
        if dims == ["channel", "geo_label", "sample"]:
            return float(beta_arr[channel_idx, geo_idx, sample_pos])
        # xarray can sometimes preserve alternative order; handle by name.
        index = []
        for d in dims:
            if d == "channel":
                index.append(channel_idx)
            elif d == "market_size_tier":
                index.append(tier_idx)
            elif d == "geo_label":
                index.append(geo_idx)
            elif d == "sample":
                index.append(sample_pos)
        return float(beta_arr[tuple(index)])

    def forecast_daily_rows(
        self,
        daily_rows: list[dict[str, Any]],
        *,
        n_samples: int = DEFAULT_FORECAST_SAMPLES,
        seed: int = 42,
        include_carryover_days: bool = True,
        progress_context: str | None = None,
        analog_year: int | None = None,
        analog_missing_geo_policy: str = "fail",
        independent_scenarios: bool = False,
        return_campaign_draws: bool = False,
        targets: Iterable[str] | None = None,
    ) -> tuple[pd.DataFrame, pd.DataFrame] | tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        plan = pd.DataFrame(daily_rows).copy()
        if plan.empty:
            raise ValueError("No daily rows to forecast")
        required_columns = {"campaign_name", "segment", "geo", "channel", "date", "budget_rub"}
        missing_columns = sorted(required_columns.difference(plan.columns))
        if missing_columns:
            raise ValueError(f"Daily flighting is missing required columns: {missing_columns}")
        plan["date"] = pd.to_datetime(plan["date"]).dt.date
        plan["budget_rub"] = pd.to_numeric(plan["budget_rub"], errors="coerce")
        if plan["budget_rub"].isna().any() or (~np.isfinite(plan["budget_rub"])).any():
            raise ValueError("Daily flighting contains non-numeric or non-finite budget values")
        if (plan["budget_rub"] < 0).any():
            raise ValueError("Daily flighting contains negative budget values")
        if not independent_scenarios:
            _assert_no_cross_campaign_overlap(plan)
        result_rows: list[dict[str, Any]] = []

        target_filter = {str(value) for value in targets} if targets is not None else None
        fit_items = [
            (fit_key, fit_meta)
            for fit_key, fit_meta in (self.metadata.get("fits") or {}).items()
            if target_filter is None or str(fit_meta.get("target")) in target_filter
        ]
        for fit_pos, (fit_key, fit_meta) in enumerate(fit_items, start=1):
            segment = fit_meta["segment"]
            target = fit_meta["target"]
            seg_plan = plan[plan["segment"] == segment].copy()
            if seg_plan.empty:
                continue
            if progress_context:
                print(
                    json.dumps(
                        {
                            "event": "forecast_progress",
                            "context": progress_context,
                            "phase": "fit_scoring",
                            "fit_key": fit_key,
                            "fit_index": fit_pos,
                            "fits_total": len(fit_items),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            channels = list(fit_meta["channels"])
            geos = list(fit_meta["geos"])
            tiers = list(fit_meta.get("market_size_tiers") or [])
            geo_to_tier = fit_meta.get("geo_to_tier") or {}
            l_max = int(fit_meta.get("l_max") or 14)
            y_scale = float(fit_meta["y_scale"])
            y_scaling = fit_meta.get("y_scaling")
            y_offset = float(fit_meta.get("y_offset") or 0.0)

            samples = self._posterior_samples(fit_meta, n_samples, seed)
            alpha = samples["alpha"]  # channel x sample
            lam = samples["lam"]
            beta = samples["beta"]
            beta_dims = tuple(samples["beta_dims"])
            sampled_n = alpha.shape[-1]

            for campaign_name, camp in seg_plan.groupby("campaign_name"):
                start = min(camp["date"])
                end = max(camp["date"])
                horizon_end = end + timedelta(days=l_max if include_carryover_days else 0)
                horizon = [start + timedelta(days=i) for i in range((horizon_end - start).days + 1)]
                for geo, geo_plan in camp.groupby("geo"):
                    if geo not in geos:
                        continue
                    geo_pos = geos.index(geo)
                    tier_name = str(
                        geo_to_tier.get(geo)
                        or self._denominator_for(
                            segment,
                            geo,
                            start,
                            analog_year=analog_year,
                            missing_geo_policy=analog_missing_geo_policy,
                        ).get("market_size_tier")
                        or ""
                    )
                    tier_pos = tiers.index(tier_name) if tier_name in tiers else 0
                    denom_by_date = {
                        dt: self._denominator_for(
                            segment,
                            geo,
                            dt,
                            analog_year=analog_year,
                            missing_geo_policy=analog_missing_geo_policy,
                        )
                        for dt in horizon
                    }
                    for channel in sorted(set(geo_plan["channel"]).intersection(channels)):
                        ch_pos = channels.index(channel)
                        spend_by_date = defaultdict(float)
                        for _, row in geo_plan[geo_plan["channel"] == channel].iterrows():
                            spend_by_date[row["date"]] += float(row["budget_rub"])
                        spend_raw = np.array([spend_by_date[dt] for dt in horizon], dtype=float)
                        if spend_raw.sum() <= 0:
                            continue
                        pop = np.array([max(float(denom_by_date[dt]["population_k"]), 1e-3) for dt in horizon])
                        x_scale = self._x_scale(fit_key, geo, channel, tier_name)
                        x_scaled = (spend_raw / pop) / max(x_scale, 1e-8)
                        warm_start = self._warm_start_for(fit_key, geo, channel, start, l_max)
                        unit_weight_total = 1.0
                        x_sat = _incremental_saturated_response_draw_matrix(
                            x_scaled,
                            alpha_values=np.asarray(alpha[ch_pos, :], dtype=float),
                            lam_values=np.asarray(lam[ch_pos, :], dtype=float),
                            l_max=l_max,
                            warm_start=warm_start,
                        )
                        beta_values = np.asarray(
                            [
                                self._beta_value(beta, beta_dims, s, ch_pos, geo_pos, tier_pos)
                                for s in range(sampled_n)
                            ],
                            dtype=float,
                        )
                        contrib_unit = beta_values[:, None] * x_sat * y_scale
                        if target in {"turnover_per_user", "orders_per_user"}:
                            weights = np.array(
                                [float(denom_by_date[dt]["unique_users"]) for dt in horizon],
                                dtype=float,
                            )
                        elif target == "avg_basket":
                            weights = np.array(
                                [float(denom_by_date[dt]["orders_cnt"]) for dt in horizon],
                                dtype=float,
                            )
                        else:
                            weights = np.ones(len(horizon), dtype=float)
                        safe_weights = np.maximum(weights, 1e-8)
                        unit_weight_total = float(safe_weights.sum())
                        units = (contrib_unit * safe_weights[None, :]).sum(axis=1) / unit_weight_total
                        totals = (contrib_unit * weights[None, :]).sum(axis=1)
                        cap = self._capability_row(segment, target, channel)
                        support = self._support_assessment(fit_key, geo, channel, spend_raw)
                        spend_total = float(spend_raw.sum())
                        row_out = {
                            "campaign_name": campaign_name,
                            "segment": segment,
                            "target": target,
                            "channel": channel,
                            "geo": geo,
                            "market_size_tier": tier_name,
                            "start_date": start.isoformat(),
                            "end_date": end.isoformat(),
                            "horizon_end_date": horizon_end.isoformat(),
                            "spend_rub": spend_total,
                            "active_days": int((spend_raw > 0).sum()),
                            "effect_unit": {
                                "turnover_per_user": "rub_per_user",
                                "orders_per_user": "orders_per_user",
                                "avg_basket": "rub_per_order",
                            }.get(target, "target_unit"),
                            "effect_p10": float(np.percentile(units, 10)),
                            "effect_p50": float(np.percentile(units, 50)),
                            "effect_p90": float(np.percentile(units, 90)),
                            "total_effect_unit": {
                                "turnover_per_user": "incremental_turnover_rub",
                                "orders_per_user": "incremental_orders",
                                "avg_basket": "turnover_bridge_from_avg_basket_rub",
                            }.get(target, "target_total"),
                            "total_effect_p10": float(np.percentile(totals, 10)),
                            "total_effect_p50": float(np.percentile(totals, 50)),
                            "total_effect_p90": float(np.percentile(totals, 90)),
                            "roas_p10": float(np.percentile(totals, 10) / spend_total) if target == "turnover_per_user" and spend_total > 0 else "",
                            "roas_p50": float(np.percentile(totals, 50) / spend_total) if target == "turnover_per_user" and spend_total > 0 else "",
                            "roas_p90": float(np.percentile(totals, 90) / spend_total) if target == "turnover_per_user" and spend_total > 0 else "",
                            "allowed_use": cap.get("allowed_use", "unsupported"),
                            "optimizer_use": cap.get("optimizer_use", "not_ready"),
                            "risk_level": cap.get("risk_level", "unavailable"),
                            "model_flags": cap.get("channel_reliability_flags", ""),
                            "support_level": support.level,
                            "support_flags": support.flags_text,
                            "future_daily_spend_max_rub": support.future_daily_max_rub,
                            "historical_daily_spend_p95_rub": support.p95_rub,
                            "historical_daily_spend_p99_rub": support.p99_rub,
                            "historical_daily_spend_observed_max_rub": support.observed_max_rub,
                            "historical_daily_spend_robust_upper_rub": support.robust_upper_rub,
                            "forecast_semantics": "incremental_media_effect_vs_no_campaign_counterfactual",
                            "y_scaling": y_scaling,
                            "y_offset": y_offset,
                            "posterior_samples": sampled_n,
                            "warm_start_used": warm_start is not None,
                            "warm_start_matched_in_counterfactual": True,
                            "denominator_analog_year": analog_year if analog_year is not None else "previous_year",
                            "denominator_fallback_gap_days_max": max(
                                int(denom_by_date[dt].get("denominator_fallback_gap_days") or 0)
                                for dt in horizon
                            ),
                            "denominator_fallback_years_max": max(
                                int(denom_by_date[dt].get("denominator_fallback_years") or 0)
                                for dt in horizon
                            ),
                            "_total_effect_draws": totals,
                            "_effect_unit_draws": units,
                            "_effect_unit_weight": unit_weight_total,
                        }
                        result_rows.append(row_out)
        detail_internal = pd.DataFrame(result_rows)
        summary = summarize_forecast_detail(detail_internal)
        detail = detail_internal.drop(
            columns=["_total_effect_draws", "_effect_unit_draws", "_effect_unit_weight"],
            errors="ignore",
        )
        _assert_modeled_spend_reconciles(plan, detail)
        if return_campaign_draws:
            return detail, summary, _campaign_total_draw_rows(detail_internal)
        return detail, summary


def build_historical_forecast_replay_rows(
    engine: ForecastEngine,
    panel: pd.DataFrame,
    row_index: pd.DataFrame,
    draw_pairs: list[tuple[int, int]],
) -> pd.DataFrame:
    """Replay training-period channel effects through the serving-side geo loop."""
    if xr is None:
        raise RuntimeError(f"xarray is required for historical response replay: {_XARRAY_IMPORT_ERROR!r}")
    panel_frame = panel.copy()
    panel_frame["date"] = pd.to_datetime(panel_frame["date"])
    index_frame = row_index.copy()
    index_frame["date"] = pd.to_datetime(index_frame["date"])
    keys = ["date", "geo_label", "network", "channel"]
    rows: list[dict[str, Any]] = []

    for fit_key, fit_meta in (engine.metadata.get("fits") or {}).items():
        transform_path = engine.run_dir / f"fit_transform_{_safe_id(fit_key)}.json"
        transform = read_json(transform_path) or {}
        if not transform:
            raise FileNotFoundError(f"Missing frozen transform for serving replay: {transform_path}")
        fit_index = index_frame[index_frame["fit_key"].eq(fit_key)].copy()
        if fit_index.empty:
            raise ValueError(f"Historical serving replay has no row index for {fit_key}")
        frame = fit_index.merge(panel_frame, on=keys, how="left", validate="one_to_one")
        frame = frame.sort_values("row_position").reset_index(drop=True)
        channels = list(transform["channels"])
        spend_columns = list(transform["spend_active"])
        required = {"population_k", "unique_users", "orders_cnt", *spend_columns}
        missing = sorted(required - set(frame.columns))
        if missing or frame[list(required)].isna().any().any():
            raise ValueError(f"Historical serving replay lost frozen fit values for {fit_key}: {missing}")
        target = fit_key.split("::", 1)[1]
        l_max = int(transform["l_max"])
        y_scale = float(transform["y_scale"])
        effect_unit = {
            "turnover_per_user": "incremental_turnover_rub",
            "orders_per_user": "incremental_orders",
            "avg_basket": "turnover_bridge_from_avg_basket_rub",
        }[target]
        posterior_path = engine.run_dir / str(fit_meta["posterior_file"])
        with xr.open_dataset(posterior_path, group="posterior") as posterior:
            posterior_draws = [
                (
                    posterior["alpha"].sel(chain=chain, draw=draw),
                    posterior["lam"].sel(chain=chain, draw=draw),
                    posterior["beta"].sel(chain=chain, draw=draw),
                )
                for chain, draw in draw_pairs
            ]
            for channel_name, spend_column in zip(channels, spend_columns):
                alpha_values = np.asarray(
                    [float(alpha.sel(channel=channel_name).values) for alpha, _, _ in posterior_draws]
                )
                lam_values = np.asarray(
                    [float(lam.sel(channel=channel_name).values) for _, lam, _ in posterior_draws]
                )
                effect_values = np.zeros(len(draw_pairs), dtype=float)
                for geo, geo_rows in frame.groupby("geo_label", sort=False):
                    population = np.maximum(geo_rows["population_k"].to_numpy(float), 1e-3)
                    tier = str(_mode_or_first(geo_rows["market_size_tier"]))
                    x_scale = engine._x_scale(fit_key, str(geo), channel_name, tier)
                    x_scaled = (geo_rows[spend_column].to_numpy(float) / population) / max(x_scale, 1e-8)
                    adstock = _normalized_adstock_draw_matrix(x_scaled, alpha_values, l_max)
                    saturation = np.tanh(lam_values[:, None] * adstock / 2.0)
                    beta_values: list[float] = []
                    for _, _, beta_draw in posterior_draws:
                        beta_index = {"channel": channel_name}
                        if "geo_label" in beta_draw.dims:
                            beta_index["geo_label"] = str(geo)
                        elif "market_size_tier" in beta_draw.dims:
                            beta_index["market_size_tier"] = tier
                        beta_values.append(float(beta_draw.sel(**beta_index).values))
                    if target in {"turnover_per_user", "orders_per_user"}:
                        denominator = geo_rows["unique_users"].to_numpy(float)
                    else:
                        denominator = geo_rows["orders_cnt"].to_numpy(float)
                    beta_array = np.asarray(beta_values, dtype=float)
                    contribution = beta_array[:, None] * saturation * y_scale
                    effect_values += np.sum(contribution * denominator[None, :], axis=1)
                spend_rub = float(frame[spend_column].sum())
                for (chain, draw), effect_value in zip(draw_pairs, effect_values):
                    rows.append(
                        {
                            "fit_key": fit_key,
                            "channel": channel_name,
                            "chain": int(chain),
                            "draw": int(draw),
                            "row_id": "full_frozen_training_window",
                            "effect_value": float(effect_value),
                            "effect_unit": effect_unit,
                            "spend_rub": spend_rub,
                            "producer": "forecast_geo_loop_v1",
                        }
                    )
    return pd.DataFrame(rows)


def _normalized_adstock_draw_matrix(
    x: np.ndarray,
    alpha_values: np.ndarray,
    l_max: int,
    warm_start: np.ndarray | None = None,
) -> np.ndarray:
    """Vectorized equivalent of ``_normalized_adstock`` for many posterior draws."""
    x = np.asarray(x, dtype=float)
    alpha_values = np.asarray(alpha_values, dtype=float)
    lag_matrix = np.zeros((l_max + 1, len(x)), dtype=float)
    if warm_start is None:
        history = np.zeros(l_max, dtype=float)
    else:
        history = np.asarray(warm_start, dtype=float)[-l_max:]
        if len(history) < l_max:
            history = np.pad(history, (l_max - len(history), 0))
    extended = np.concatenate([history, x])
    offset = len(history)
    for lag in range(l_max + 1):
        lag_matrix[lag] = extended[offset - lag : offset - lag + len(x)]
    draw_weights = alpha_values[:, None] ** np.arange(l_max + 1, dtype=float)[None, :]
    draw_weights = draw_weights / np.maximum(draw_weights.sum(axis=1, keepdims=True), 1e-12)
    return draw_weights @ lag_matrix


def _incremental_saturated_response_draw_matrix(
    x: np.ndarray,
    *,
    alpha_values: np.ndarray,
    lam_values: np.ndarray,
    l_max: int,
    warm_start: np.ndarray | None,
) -> np.ndarray:
    """Vectorized campaign-minus-counterfactual response for aligned posterior draws."""
    plan_adstock = _normalized_adstock_draw_matrix(
        x,
        alpha_values,
        l_max,
        warm_start=warm_start,
    )
    counterfactual_adstock = _normalized_adstock_draw_matrix(
        np.zeros_like(np.asarray(x, dtype=float)),
        alpha_values,
        l_max,
        warm_start=warm_start,
    )
    lam = np.asarray(lam_values, dtype=float)[:, None]
    return np.tanh(lam * plan_adstock / 2.0) - np.tanh(
        lam * counterfactual_adstock / 2.0
    )


def _campaign_total_draw_rows(detail: pd.DataFrame) -> pd.DataFrame:
    """Return private campaign-total draws for paired scenario comparisons."""
    if detail.empty:
        return pd.DataFrame(
            columns=["campaign_name", "target", "draw_index", "total_effect"]
        )
    if "_total_effect_draws" not in detail:
        raise ValueError("Campaign draw export requires _total_effect_draws")
    rows: list[dict[str, Any]] = []
    for (campaign_name, target), sub in detail.groupby(
        ["campaign_name", "target"], dropna=False
    ):
        arrays = [np.asarray(value, dtype=float) for value in sub["_total_effect_draws"]]
        lengths = {len(value) for value in arrays}
        if len(lengths) != 1:
            raise ValueError(
                f"Posterior draw lengths differ for {campaign_name}/{target}: {sorted(lengths)}"
            )
        totals = np.vstack(arrays).sum(axis=0)
        rows.extend(
            {
                "campaign_name": str(campaign_name),
                "target": str(target),
                "draw_index": int(draw_index),
                "total_effect": float(value),
            }
            for draw_index, value in enumerate(totals)
        )
    return pd.DataFrame(rows)


def summarize_forecast_detail(detail: pd.DataFrame) -> pd.DataFrame:
    """Aggregate posterior draws first, then calculate campaign quantiles.

    Summing cell-level p10/p50/p90 is statistically invalid because all cells
    share posterior draws and can be dependent. The private draw columns exist
    only inside ``forecast_daily_rows`` and are dropped before public outputs.
    """
    if detail.empty:
        return pd.DataFrame()
    private_columns = {"_total_effect_draws", "_effect_unit_draws", "_effect_unit_weight"}
    missing = private_columns.difference(detail.columns)
    if missing:
        raise ValueError(
            "Correct forecast aggregation requires draw-level values. "
            f"Missing internal columns: {sorted(missing)}"
        )

    def _draw_matrix(sub: pd.DataFrame, column: str) -> np.ndarray:
        arrays = [np.asarray(value, dtype=float) for value in sub[column]]
        lengths = {len(value) for value in arrays}
        if len(lengths) != 1:
            raise ValueError(f"Posterior draw lengths differ inside forecast group: {sorted(lengths)}")
        return np.vstack(arrays)

    def _count_string(sub: pd.DataFrame, column: str) -> str:
        return ";".join(f"{key}:{value}" for key, value in Counter(sub[column]).items())

    def _support_counts(sub: pd.DataFrame) -> dict[str, int]:
        flags = sub["support_flags"].fillna("OK").astype(str)
        any_warnings = int(flags.ne("OK").sum())
        if "support_level" in sub.columns:
            levels = sub["support_level"].fillna(SUPPORT_LEVEL_OUTSIDE).astype(str)
        else:
            levels = flags.map(
                lambda value: SUPPORT_LEVEL_WITHIN
                if value == "OK"
                else SUPPORT_LEVEL_OUTSIDE
            )
        return {
            "support_warnings_n": any_warnings,
            "spend_support_warnings_n": int(levels.ne(SUPPORT_LEVEL_WITHIN).sum()),
            "support_within_n": int(levels.eq(SUPPORT_LEVEL_WITHIN).sum()),
            "support_elevated_n": int(levels.eq(SUPPORT_LEVEL_ELEVATED).sum()),
            "support_strong_n": int(levels.eq(SUPPORT_LEVEL_STRONG).sum()),
            "support_outside_n": int(levels.eq(SUPPORT_LEVEL_OUTSIDE).sum()),
        }

    def _aggregate(sub: pd.DataFrame, *, channel: str, segment: str | None = None) -> dict[str, Any]:
        total_draws = _draw_matrix(sub, "_total_effect_draws").sum(axis=0)
        spend = float(sub["spend_rub"].sum())
        target = str(sub["target"].iloc[0])
        support_counts = _support_counts(sub)
        row = {
            "campaign_name": sub["campaign_name"].iloc[0],
            "segment": segment if segment is not None else sub["segment"].iloc[0],
            "target": target,
            "channel": channel,
            "spend_rub": spend,
            "geos_n": int(sub["geo"].nunique()),
            "effect_unit": sub["effect_unit"].iloc[0],
            "total_effect_unit": sub["total_effect_unit"].iloc[0],
            "total_effect_p10": float(np.percentile(total_draws, 10)),
            "total_effect_p50": float(np.percentile(total_draws, 50)),
            "total_effect_p90": float(np.percentile(total_draws, 90)),
            "roas_p10": float(np.percentile(total_draws, 10) / spend) if target == "turnover_per_user" and spend > 0 else "",
            "roas_p50": float(np.percentile(total_draws, 50) / spend) if target == "turnover_per_user" and spend > 0 else "",
            "roas_p90": float(np.percentile(total_draws, 90) / spend) if target == "turnover_per_user" and spend > 0 else "",
            "allowed_use_counts": _count_string(sub, "allowed_use"),
            "optimizer_use_counts": _count_string(sub, "optimizer_use"),
            "risk_level_counts": _count_string(sub, "risk_level"),
            **support_counts,
            "posterior_samples": int(len(total_draws)),
            "quantile_aggregation": "sum_draws_then_quantile",
        }
        if channel == "__TOTAL__":
            row.update({"effect_p10": "", "effect_p50": "", "effect_p90": ""})
        else:
            unit_matrix = _draw_matrix(sub, "_effect_unit_draws")
            weights = pd.to_numeric(sub["_effect_unit_weight"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
            weight_total = float(weights.sum())
            if weight_total > 0:
                unit_draws = (unit_matrix * weights[:, None]).sum(axis=0) / weight_total
                row.update({
                    "effect_p10": float(np.percentile(unit_draws, 10)),
                    "effect_p50": float(np.percentile(unit_draws, 50)),
                    "effect_p90": float(np.percentile(unit_draws, 90)),
                })
            else:
                row.update({"effect_p10": "", "effect_p50": "", "effect_p90": ""})
        return row

    group_cols = ["campaign_name", "segment", "target", "channel"]
    rows: list[dict[str, Any]] = []
    for keys, sub in detail.groupby(group_cols, dropna=False):
        rows.append(_aggregate(sub, channel=str(keys[3])))
    total_rows: list[dict[str, Any]] = []
    for _, sub in detail.groupby(["campaign_name", "segment", "target"], dropna=False):
        total_rows.append(_aggregate(sub, channel="__TOTAL__"))
    campaign_total_rows: list[dict[str, Any]] = []
    for _, sub in detail.groupby(["campaign_name", "target"], dropna=False):
        campaign_total_rows.append(_aggregate(sub, channel="__TOTAL__", segment="__ALL__"))
    return pd.DataFrame(rows + total_rows + campaign_total_rows)


def _assert_modeled_spend_reconciles(plan: pd.DataFrame, detail: pd.DataFrame) -> None:
    """Fail if any campaign cell was silently omitted by model metadata."""
    keys = ["campaign_name", "segment", "geo", "channel"]
    expected = plan.groupby(keys, dropna=False, as_index=False)["budget_rub"].sum().rename(
        columns={"budget_rub": "expected_budget_rub"}
    )
    if detail.empty:
        raise ValueError("Forecast produced no modeled rows for a non-empty campaign plan")
    target_priority = [target for target in TARGETS if target in set(detail["target"].astype(str))]
    if not target_priority:
        raise ValueError("Forecast output has no supported target rows for spend reconciliation")
    modeled_parts: list[pd.DataFrame] = []
    for segment, sub in expected.groupby("segment", dropna=False):
        available = detail[detail["segment"].eq(segment)]
        if available.empty:
            modeled_parts.append(pd.DataFrame(columns=keys + ["modeled_budget_rub"]))
            continue
        target = next((value for value in target_priority if value in set(available["target"])), None)
        selected = available[available["target"].eq(target)] if target is not None else available.iloc[0:0]
        modeled_parts.append(
            selected.groupby(keys, dropna=False, as_index=False)["spend_rub"].sum().rename(
                columns={"spend_rub": "modeled_budget_rub"}
            )
        )
    modeled = pd.concat(modeled_parts, ignore_index=True) if modeled_parts else pd.DataFrame(columns=keys + ["modeled_budget_rub"])
    check = expected.merge(modeled, on=keys, how="outer")
    check[["expected_budget_rub", "modeled_budget_rub"]] = check[
        ["expected_budget_rub", "modeled_budget_rub"]
    ].fillna(0.0)
    check["abs_diff_rub"] = (check["expected_budget_rub"] - check["modeled_budget_rub"]).abs()
    tolerance = np.maximum(
        BUDGET_RECONCILIATION_ABS_TOL_RUB,
        check["expected_budget_rub"].abs() * BUDGET_RECONCILIATION_REL_TOL,
    )
    failed = check[check["abs_diff_rub"] > tolerance]
    if not failed.empty:
        examples = failed[keys + ["expected_budget_rub", "modeled_budget_rub", "abs_diff_rub"]].head(10)
        raise ValueError(
            "Forecast did not model every uploaded campaign cell; no silent row loss is allowed. "
            f"Examples: {examples.to_dict('records')}"
        )


def write_forecast_outputs(detail: pd.DataFrame, summary: pd.DataFrame, output_dir: str | Path, run_id: str) -> dict[str, str]:
    output_dir = ensure_dir(output_dir)
    detail_path = output_dir / f"{_safe_id(run_id)}_forecast_detail_geo_channel.csv"
    summary_path = output_dir / f"{_safe_id(run_id)}_forecast_summary.csv"
    xlsx_path = output_dir / f"{_safe_id(run_id)}_campaign_forecast_report.xlsx"
    detail.to_csv(detail_path, index=False)
    summary.to_csv(summary_path, index=False)
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        readme = pd.DataFrame([
            {"sheet": "01_Summary", "description": "Campaign x segment x target x channel totals with p10/p50/p90."},
            {"sheet": "02_Geo_Channel", "description": "Detailed geo x channel forecast; all effects are incremental vs no-campaign counterfactual."},
            {"sheet": "03_Warnings", "description": "Model and historical-support warnings kept visible."},
        ])
        readme.to_excel(writer, sheet_name="00_ReadMe", index=False)
        summary.to_excel(writer, sheet_name="01_Summary", index=False)
        detail.to_excel(writer, sheet_name="02_Geo_Channel", index=False)
        warnings_df = detail[(detail["allowed_use"] != "primary") | (detail["support_flags"] != "OK")].copy() if not detail.empty else pd.DataFrame()
        warnings_df.to_excel(writer, sheet_name="03_Warnings", index=False)
    return {"detail_csv": str(detail_path), "summary_csv": str(summary_path), "xlsx": str(xlsx_path)}


def read_daily_flighting(path: str | Path) -> list[dict[str, Any]]:
    rows = _read_csv(Path(path))
    out = []
    for r in rows:
        out.append({
            "campaign_name": r.get("campaign_name") or "unknown_campaign",
            "creative_name": r.get("creative_name") or "",
            "segment": r.get("segment") or "",
            "geo": r.get("geo") or "",
            "channel": r.get("channel") or "",
            "date": r.get("date") or "",
            "budget_rub": float(r.get("budget_rub") or 0.0),
        })
    return out


def run_forecast_from_flighting(
    model_run_dir: str | Path,
    flighting_path: str | Path,
    output_dir: str | Path,
    run_id: str,
    *,
    n_samples: int = DEFAULT_FORECAST_SAMPLES,
    seed: int = 42,
    future_controls: dict[str, Any] | None = None,
    validate_package_lineage: bool = True,
) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    started_perf = time.monotonic()
    engine = ForecastEngine.from_run_dir(
        model_run_dir,
        auto_export=validate_package_lineage,
        validate_package_lineage=validate_package_lineage,
    )
    daily_rows = read_daily_flighting(flighting_path)
    analog_year = _future_controls_analog_year(future_controls)
    analog_missing_geo_policy = _future_controls_missing_geo_policy(future_controls)
    detail, summary = engine.forecast_daily_rows(
        daily_rows,
        n_samples=n_samples,
        seed=seed,
        progress_context=run_id,
        analog_year=analog_year,
        analog_missing_geo_policy=analog_missing_geo_policy,
        independent_scenarios=False,
    )
    paths = write_forecast_outputs(detail, summary, output_dir, run_id)
    card = {
        "run_id": run_id,
        "model_run_dir": str(resolve_path(model_run_dir)),
        "flighting_path": str(resolve_path(flighting_path)),
        "flighting_sha256": sha256_file(resolve_path(flighting_path)),
        "model_manifest_sha256": sha256_file(resolve_path(model_run_dir) / "model_manifest.json"),
        "n_samples": n_samples,
        "seed": seed,
        "future_controls": future_controls or {},
        "denominator_analog_year": analog_year if analog_year is not None else "previous_year",
        "denominator_missing_geo_policy": analog_missing_geo_policy,
        "started_at_utc": started_at.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(time.monotonic() - started_perf, 3),
        "detail_rows_n": int(len(detail)),
        "summary_rows_n": int(len(summary)),
        "runtime_lineage": _runtime_lineage(model_run_dir, purpose="forecast"),
        "output_sha256": {name: sha256_file(Path(path)) for name, path in paths.items()},
        "outputs": paths,
    }
    write_json(Path(output_dir) / f"{_safe_id(run_id)}_forecast_run_card.json", card)
    return card


def _campaign_cell_rows(plan: pd.DataFrame, campaign_name: str) -> pd.DataFrame:
    sub = plan[plan["campaign_name"] == campaign_name].copy()
    return sub.groupby(["campaign_name", "segment", "geo", "channel"], as_index=False)["budget_rub"].sum()


def _annotate_candidate_budget(
    cells: pd.DataFrame,
    requested_budget_rub: float,
    *,
    support_limit_policy: str = "unconstrained_benchmark",
) -> pd.DataFrame:
    out = cells.copy()
    allocated = float(pd.to_numeric(out["budget_rub"], errors="coerce").fillna(0.0).sum())
    out["requested_budget_rub"] = float(requested_budget_rub)
    out["allocated_budget_rub"] = allocated
    out["unallocated_budget_rub"] = max(float(requested_budget_rub) - allocated, 0.0)
    out["support_limit_policy"] = support_limit_policy
    return out


def _candidate_budget_summary(candidate: pd.DataFrame, requested_budget_rub: float) -> dict[str, Any]:
    allocated = float(pd.to_numeric(candidate["budget_rub"], errors="coerce").fillna(0.0).sum())
    requested = float(requested_budget_rub)
    if "requested_budget_rub" in candidate and not candidate.empty:
        requested = float(candidate["requested_budget_rub"].iloc[0])
    unallocated = max(requested - allocated, 0.0)
    support_policy = (
        str(candidate["support_limit_policy"].iloc[0])
        if "support_limit_policy" in candidate and not candidate.empty
        else "unconstrained_benchmark"
    )
    summary: dict[str, Any] = {
        "requested_budget_rub": requested,
        "allocated_budget_rub": allocated,
        "unallocated_budget_rub": unallocated,
        "allocated_budget_share": allocated / requested if requested > 0 else 0.0,
        "allocation_share": allocated / requested if requested > 0 else None,
        "support_limit_policy": support_policy,
    }
    for column in [
        "allocation_projection_mode",
        "operational_rounding_step_rub",
        "operational_rounding_applied",
        "operational_rounding_status",
        "search_attempts_evaluated_n",
        "search_kernel_evaluations_n",
        "search_unique_allocations_n",
        "search_effective_dimension_n",
        "search_converged",
        "search_posterior_samples",
        "search_objective",
        "search_support_limit",
        "search_kernel_score_p10",
        "search_kernel_score_p50",
        "search_kernel_score_p90",
        "search_candidate_pool_n",
        "search_max_evaluations_n",
        "search_allocation_quantum_rub",
        "search_smallest_transfer_rub",
        "search_budget_exhausted",
        "scenario_kind",
        "scenario_variant",
        "scenario_feasibility_status",
        "full_allocation_impossible_reason",
        "limiting_constraints",
    ]:
        if column in candidate and not candidate.empty:
            summary[column] = candidate[column].iloc[0]
    return summary


def _candidate_risk_budget_summary(
    candidate: pd.DataFrame,
    source_plan: pd.DataFrame,
    engine: ForecastEngine,
) -> dict[str, Any]:
    """Decompose allocated money into support-backed risk tranches.

    The p95 tranche is `within support`; spend between p95 and the robust
    observed upper boundary is controlled extrapolation; spend above that
    boundary is high risk.  A cell can therefore contribute to more than one
    monetary tranche without its full budget being mislabeled.
    """

    within = 0.0
    controlled = 0.0
    high = 0.0
    within_cells = 0
    controlled_cells = 0
    high_cells = 0
    for _, cell in candidate.iterrows():
        budget = max(float(cell.get("budget_rub") or 0.0), 0.0)
        p95_cap = max(
            _support_cap_rub_for_cell(cell, source_plan, engine, limit="p95"),
            0.0,
        )
        robust_cap = max(
            _support_cap_rub_for_cell(cell, source_plan, engine, limit="robust_upper"),
            p95_cap,
        )
        cell_within = min(budget, p95_cap)
        cell_controlled = min(max(budget - p95_cap, 0.0), robust_cap - p95_cap)
        cell_high = max(budget - robust_cap, 0.0)
        within += cell_within
        controlled += cell_controlled
        high += cell_high
        within_cells += int(cell_within > SUPPORT_ABS_TOL_RUB)
        controlled_cells += int(cell_controlled > SUPPORT_ABS_TOL_RUB)
        high_cells += int(cell_high > SUPPORT_ABS_TOL_RUB)

    allocated = float(
        pd.to_numeric(candidate.get("budget_rub"), errors="coerce").fillna(0.0).sum()
    )
    tolerance = max(
        BUDGET_RECONCILIATION_ABS_TOL_RUB,
        abs(allocated) * BUDGET_RECONCILIATION_REL_TOL,
    )
    if abs((within + controlled + high) - allocated) > tolerance:
        raise CandidateFeasibilityError("Risk-budget tranches do not reconcile to allocated budget")

    def share(value: float) -> float | None:
        return value / allocated if allocated > 0 else None

    return {
        "within_support_budget_rub": within,
        "within_support_share": share(within),
        "controlled_extrapolation_budget_rub": controlled,
        "controlled_extrapolation_share": share(controlled),
        "high_risk_budget_rub": high,
        "high_risk_share": share(high),
        "within_support_cells_n": within_cells,
        "controlled_extrapolation_cells_n": controlled_cells,
        "high_risk_cells_n": high_cells,
    }


def _candidate_concentration(candidate: pd.DataFrame) -> float:
    budget = pd.to_numeric(candidate.get("budget_rub"), errors="coerce").fillna(0.0)
    total = float(budget.sum())
    if total <= 0:
        return 1.0
    shares = budget.to_numpy(dtype=float) / total
    return float(np.square(shares).sum())


def _candidate_source_deviation(
    candidate: pd.DataFrame,
    source_cells: pd.DataFrame,
    requested_budget_rub: float,
) -> float:
    keys = ["segment", "geo", "channel"]
    candidate_budget = {
        tuple(str(row[key]) for key in keys): float(row["budget_rub"])
        for _, row in candidate.iterrows()
    }
    source_budget = {
        tuple(str(row[key]) for key in keys): float(row["budget_rub"])
        for _, row in source_cells.iterrows()
    }
    moved_twice = sum(
        abs(candidate_budget.get(key, 0.0) - source_budget.get(key, 0.0))
        for key in set(candidate_budget) | set(source_budget)
    )
    denominator = max(float(requested_budget_rub) * 2.0, 1.0)
    return float(moved_twice / denominator)


def _annotate_scenario_semantics(
    candidate: pd.DataFrame,
    *,
    scenario_kind: str,
    scenario_variant: str,
    feasibility_status: str,
    full_allocation_impossible_reason: str = "",
    limiting_constraints: str = "",
) -> pd.DataFrame:
    out = candidate.copy()
    out["scenario_kind"] = scenario_kind
    out["scenario_variant"] = scenario_variant
    out["scenario_feasibility_status"] = feasibility_status
    out["full_allocation_impossible_reason"] = full_allocation_impossible_reason
    out["limiting_constraints"] = limiting_constraints
    return out


def _make_candidate_daily(cell_budget: pd.DataFrame, source_plan: pd.DataFrame, candidate_name: str) -> list[dict[str, Any]]:
    """Scale each source cell's observed daily profile to its candidate total."""
    rows: list[dict[str, Any]] = []
    for _, cell in cell_budget.iterrows():
        base = source_plan[
            (source_plan["campaign_name"] == cell["campaign_name"])
            & (source_plan["segment"] == cell["segment"])
            & (source_plan["geo"] == cell["geo"])
            & (source_plan["channel"] == cell["channel"])
        ]
        if base.empty:
            continue
        by_date = (
            base.assign(date=pd.to_datetime(base["date"]).dt.date)
            .groupby("date", as_index=False, dropna=False)["budget_rub"]
            .sum()
            .sort_values("date")
        )
        if by_date.empty:
            continue
        source_total = float(pd.to_numeric(by_date["budget_rub"], errors="coerce").fillna(0.0).sum())
        candidate_total = float(cell["budget_rub"])
        if source_total > 0:
            by_date["candidate_budget_rub"] = by_date["budget_rub"].astype(float) * candidate_total / source_total
        else:
            by_date["candidate_budget_rub"] = candidate_total / len(by_date)
        for _, day in by_date.iterrows():
            rows.append({
                "campaign_name": candidate_name,
                "creative_name": "optimizer_candidate",
                "segment": cell["segment"],
                "geo": cell["geo"],
                "channel": cell["channel"],
                "date": day["date"].isoformat(),
                "budget_rub": float(day["candidate_budget_rub"]),
            })
    return rows


def _channel_balanced_candidate(cells: pd.DataFrame, total_budget: float) -> pd.DataFrame:
    """Keep each channel total and split it equally across that channel's geos."""
    out = cells.copy()
    for channel, sub in out.groupby("channel", dropna=False):
        mask = out["channel"].eq(channel)
        out.loc[mask, "budget_rub"] = float(sub["budget_rub"].sum()) / max(len(sub), 1)
    return out


def _geo_balanced_candidate(cells: pd.DataFrame, total_budget: float) -> pd.DataFrame:
    """Keep each geo total and split it equally across that geo's channels."""
    out = cells.copy()
    for geo, sub in out.groupby("geo", dropna=False):
        mask = out["geo"].eq(geo)
        out.loc[mask, "budget_rub"] = float(sub["budget_rub"].sum()) / max(len(sub), 1)
    return out


class CandidateFeasibilityError(ValueError):
    """Raised when campaign budget cannot satisfy support and model-policy bounds."""


def _support_cap_rub_for_cell(
    cell: pd.Series,
    source_plan: pd.DataFrame,
    engine: ForecastEngine,
    *,
    limit: str = "p95",
) -> float:
    """Return a total-budget cap consistent with the cell's daily profile."""
    rows = engine.support_bounds[
        (engine.support_bounds["segment"] == cell["segment"])
        & (engine.support_bounds["channel"] == cell["channel"])
        & (engine.support_bounds["geo_label"] == cell["geo"])
        & (engine.support_bounds["target"] == "turnover_per_user")
    ]
    if rows.empty:
        return 0.0
    row = rows.iloc[0]
    p95 = _finite_nonnegative(row.get("daily_spend_p95_rub"))
    p99 = max(_finite_nonnegative(row.get("daily_spend_p99_rub")), p95)
    observed_max = max(_finite_nonnegative(row.get("daily_spend_max_rub")), p99)
    active_days = int(_finite_nonnegative(row.get("active_days")))
    limits = {
        "p95": p95,
        "p99": p99,
        "robust_upper": _robust_support_upper(p95, p99, observed_max, active_days),
    }
    if limit not in limits:
        raise ValueError(f"Unknown support limit: {limit}")
    daily_limit = limits[limit]
    if daily_limit <= 0:
        return 0.0

    base = source_plan[
        (source_plan["campaign_name"] == cell["campaign_name"])
        & (source_plan["segment"] == cell["segment"])
        & (source_plan["geo"] == cell["geo"])
        & (source_plan["channel"] == cell["channel"])
    ].copy()
    if base.empty:
        return daily_limit
    by_date = base.groupby("date", dropna=False)["budget_rub"].sum().astype(float)
    source_total = float(by_date.sum())
    if source_total <= 0:
        return daily_limit * max(len(by_date), 1)
    peak_share = float(by_date.max() / source_total)
    return daily_limit / max(peak_share, 1e-12)


def _project_box_simplex(
    preferred: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    total_budget: float,
) -> np.ndarray:
    """Project a preferred allocation onto box bounds while preserving budget."""
    preferred = np.asarray(preferred, dtype=float)
    lower = np.asarray(lower, dtype=float)
    upper = np.asarray(upper, dtype=float)
    if not (len(preferred) == len(lower) == len(upper)):
        raise CandidateFeasibilityError("Allocation vectors have inconsistent lengths")
    if np.any(lower < -SUPPORT_ABS_TOL_RUB) or np.any(upper + SUPPORT_ABS_TOL_RUB < lower):
        raise CandidateFeasibilityError("Candidate lower bounds exceed upper bounds")
    tolerance = max(BUDGET_RECONCILIATION_ABS_TOL_RUB, abs(total_budget) * BUDGET_RECONCILIATION_REL_TOL)
    if lower.sum() > total_budget + tolerance:
        raise CandidateFeasibilityError("Required/fixed budgets exceed campaign total")
    if upper.sum() < total_budget - tolerance:
        raise CandidateFeasibilityError("Campaign budget exceeds aggregate model/support capacity")

    low = float(np.min(preferred - upper) - abs(total_budget) - 1.0)
    high = float(np.max(preferred - lower) + abs(total_budget) + 1.0)
    for _ in range(200):
        midpoint = (low + high) / 2.0
        projected = np.clip(preferred - midpoint, lower, upper)
        if projected.sum() > total_budget:
            low = midpoint
        else:
            high = midpoint
    projected = np.clip(preferred - high, lower, upper)
    remainder = total_budget - float(projected.sum())
    if abs(remainder) > tolerance:
        capacity = upper - projected if remainder > 0 else projected - lower
        available = np.where(capacity > SUPPORT_ABS_TOL_RUB)[0]
        if len(available) == 0:
            raise CandidateFeasibilityError("Unable to reconcile projected campaign budget")
        idx = int(available[np.argmax(capacity[available])])
        projected[idx] += remainder
    return projected


def _project_proportional_box_simplex(
    preferred: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    total_budget: float,
) -> np.ndarray:
    """Preserve source geo x channel proportions while respecting cell caps."""
    preferred = np.asarray(preferred, dtype=float)
    lower = np.asarray(lower, dtype=float)
    upper = np.asarray(upper, dtype=float)
    if not (len(preferred) == len(lower) == len(upper)):
        raise CandidateFeasibilityError("Allocation vectors have inconsistent lengths")
    tolerance = max(
        BUDGET_RECONCILIATION_ABS_TOL_RUB,
        abs(total_budget) * BUDGET_RECONCILIATION_REL_TOL,
    )
    capacity = np.maximum(upper - lower, 0.0)
    remaining = float(total_budget - lower.sum())
    if remaining < -tolerance or remaining > float(capacity.sum()) + tolerance:
        raise CandidateFeasibilityError("Campaign budget is infeasible under proportional support bounds")
    if remaining <= tolerance:
        return lower.copy()

    weights = np.maximum(preferred - lower, 0.0)
    positive_capacity = capacity > SUPPORT_ABS_TOL_RUB
    if not np.any(weights[positive_capacity] > 0):
        weights = capacity.copy()
    else:
        small_weight = max(float(weights[positive_capacity].mean()) * 1e-9, 1e-9)
        weights = np.where(positive_capacity & (weights <= 0), small_weight, weights)

    low, high = 0.0, 1.0
    while float(np.minimum(high * weights, capacity).sum()) < remaining - tolerance:
        high *= 2.0
        if high > 1e18:
            raise CandidateFeasibilityError("Unable to scale proportional allocation into support capacity")
    for _ in range(200):
        midpoint = (low + high) / 2.0
        used = float(np.minimum(midpoint * weights, capacity).sum())
        if used < remaining:
            low = midpoint
        else:
            high = midpoint
    projected = lower + np.minimum(high * weights, capacity)
    difference = total_budget - float(projected.sum())
    if abs(difference) > tolerance:
        room = upper - projected if difference > 0 else projected - lower
        available = np.where(room > SUPPORT_ABS_TOL_RUB)[0]
        if len(available) == 0:
            raise CandidateFeasibilityError("Unable to reconcile proportional campaign budget")
        projected[int(available[np.argmax(room[available])])] += difference
    return projected


def _candidate_policy_bounds(
    cells: pd.DataFrame,
    source_plan: pd.DataFrame,
    engine: ForecastEngine,
    *,
    support_limit: str,
    allow_fixed_contraction: bool = False,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    lower: list[float] = []
    upper: list[float] = []
    policies: list[str] = []
    for _, cell in cells.iterrows():
        source = source_plan[
            (source_plan["campaign_name"] == cell["campaign_name"])
            & (source_plan["segment"] == cell["segment"])
            & (source_plan["geo"] == cell["geo"])
            & (source_plan["channel"] == cell["channel"])
        ]
        current = float(pd.to_numeric(source["budget_rub"], errors="coerce").fillna(0.0).sum())
        capability = engine._capability_row(str(cell["segment"]), "turnover_per_user", str(cell["channel"]))
        policy = str(capability.get("optimizer_use") or "blocked")
        support_cap = _support_cap_rub_for_cell(
            cell,
            source_plan,
            engine,
            limit=support_limit,
        )
        if policy == "optimize":
            lo, hi = 0.0, support_cap
        elif policy == "no_increase":
            lo, hi = 0.0, min(current, support_cap)
        elif policy == "fixed_at_plan":
            # Gate policy has precedence: diagnostic effects may be shown, but
            # the optimizer must not manufacture a change in their budget.
            if current <= support_cap + SUPPORT_ABS_TOL_RUB:
                lo, hi = current, current
            elif allow_fixed_contraction:
                # S5 safe_partial may retain only the support-backed part and
                # expose the remainder.  It still cannot score that diagnostic
                # cell as a source of incremental budget.
                lo, hi = support_cap, support_cap
            else:
                raise CandidateFeasibilityError(
                    "A fixed-at-plan cell exceeds the selected support boundary"
                )
        else:
            lo, hi = 0.0, 0.0
        lower.append(lo)
        upper.append(hi)
        policies.append(policy)
    return np.asarray(lower, dtype=float), np.asarray(upper, dtype=float), policies


def _apply_business_share_constraints(
    allocation: np.ndarray,
    cells: pd.DataFrame,
    lower: np.ndarray,
    upper: np.ndarray,
    total_budget: float,
    constraints: dict[str, Any],
) -> np.ndarray:
    """Enforce configured aggregate channel and geo share constraints."""
    out = np.asarray(allocation, dtype=float).copy()
    dimensions = [
        ("channel", constraints.get("channel_min_share") or {}, constraints.get("channel_max_share") or {}),
        ("geo", constraints.get("geo_min_share") or {}, constraints.get("geo_max_share") or {}),
    ]

    def _transfer(amount: float, donor_mask: np.ndarray, receiver_mask: np.ndarray) -> None:
        nonlocal out
        donor_capacity = np.where(donor_mask, np.maximum(out - lower, 0.0), 0.0)
        receiver_capacity = np.where(receiver_mask, np.maximum(upper - out, 0.0), 0.0)
        transferable = min(amount, float(donor_capacity.sum()), float(receiver_capacity.sum()))
        if transferable <= SUPPORT_ABS_TOL_RUB:
            raise CandidateFeasibilityError("Configured share constraints are infeasible with model/support bounds")
        out -= transferable * donor_capacity / max(float(donor_capacity.sum()), 1e-12)
        out += transferable * receiver_capacity / max(float(receiver_capacity.sum()), 1e-12)

    for _ in range(100):
        changed = False
        for column, min_map, max_map in dimensions:
            values = cells[column].astype(str).to_numpy()
            for label, raw_share in min_map.items():
                share = float(raw_share)
                if not 0.0 <= share <= 1.0:
                    raise CandidateFeasibilityError(f"{column}_min_share for {label} must be between 0 and 1")
                mask = values == str(label)
                if not mask.any():
                    raise CandidateFeasibilityError(f"Required {column} {label} is absent from uploaded campaign cells")
                deficit = total_budget * share - float(out[mask].sum())
                if deficit > SUPPORT_ABS_TOL_RUB:
                    _transfer(deficit, ~mask, mask)
                    changed = True
            for label, raw_share in max_map.items():
                share = float(raw_share)
                if not 0.0 <= share <= 1.0:
                    raise CandidateFeasibilityError(f"{column}_max_share for {label} must be between 0 and 1")
                mask = values == str(label)
                excess = float(out[mask].sum()) - total_budget * share
                if excess > SUPPORT_ABS_TOL_RUB:
                    _transfer(excess, mask, ~mask)
                    changed = True
        if not changed:
            break

    tolerance = max(BUDGET_RECONCILIATION_ABS_TOL_RUB, abs(total_budget) * BUDGET_RECONCILIATION_REL_TOL)
    if abs(float(out.sum()) - total_budget) > tolerance or np.any(out < lower - tolerance) or np.any(out > upper + tolerance):
        raise CandidateFeasibilityError("Business-constraint projection failed budget or cell bounds")
    return out


def _enforce_candidate_constraints(
    cells: pd.DataFrame,
    source_plan: pd.DataFrame,
    engine: ForecastEngine,
    total_budget: float,
    *,
    prefer_safe_support: bool = True,
    support_limit: str | None = None,
    allow_partial: bool = False,
    business_constraints: dict[str, Any] | None = None,
    projection_mode: str = "additive",
) -> pd.DataFrame:
    """Apply model-use policy and support bounds, optionally retaining a remainder."""
    out = cells.copy()
    preferred = out["budget_rub"].to_numpy(dtype=float)
    selected_limit = support_limit or ("p95" if prefer_safe_support else "robust_upper")
    lower, upper, _ = _candidate_policy_bounds(
        out,
        source_plan,
        engine,
        support_limit=selected_limit,
        allow_fixed_contraction=allow_partial,
    )
    constraints = business_constraints or {}
    allowed_channels = {str(value) for value in constraints.get("channels_allowed") or []}
    allowed_geos = {str(value) for value in constraints.get("geos_allowed") or []}
    if allowed_channels or allowed_geos:
        restricted_upper = upper.copy()
        if allowed_channels:
            restricted_upper[~out["channel"].astype(str).isin(allowed_channels).to_numpy()] = 0.0
        if allowed_geos:
            restricted_upper[~out["geo"].astype(str).isin(allowed_geos).to_numpy()] = 0.0
        upper = restricted_upper

    tolerance = max(BUDGET_RECONCILIATION_ABS_TOL_RUB, abs(total_budget) * BUDGET_RECONCILIATION_REL_TOL)
    if lower.sum() > total_budget + tolerance:
        raise CandidateFeasibilityError("Required/fixed budgets exceed uploaded campaign total")
    allocatable_budget = min(float(total_budget), float(upper.sum())) if allow_partial else float(total_budget)
    if allocatable_budget < float(lower.sum()) - tolerance:
        raise CandidateFeasibilityError("Model-policy fixed budgets exceed support-aware capacity")
    if projection_mode == "proportional":
        projected = _project_proportional_box_simplex(
            preferred,
            lower,
            upper,
            allocatable_budget,
        )
    elif projection_mode == "additive":
        projected = _project_box_simplex(preferred, lower, upper, allocatable_budget)
    else:
        raise ValueError(f"Unknown candidate projection_mode={projection_mode!r}")

    for dimension, mandatory_key, min_key in [
        ("channel", "mandatory_channels", "channel_min_share"),
        ("geo", "mandatory_geos", "geo_min_share"),
    ]:
        minimums = constraints.get(min_key) or {}
        for label in constraints.get(mandatory_key) or []:
            if str(label) not in {str(key) for key in minimums}:
                raise CandidateFeasibilityError(
                    f"{mandatory_key} requires an explicit positive {min_key} entry for {label}"
                )
            if float(minimums[str(label)]) <= 0:
                raise CandidateFeasibilityError(f"Mandatory {dimension} {label} must have a positive minimum share")

    if constraints:
        projected = _apply_business_share_constraints(
            projected,
            out,
            lower,
            upper,
            allocatable_budget,
            constraints,
        )
    out["budget_rub"] = projected
    allocated_budget = float(projected.sum())
    out["requested_budget_rub"] = float(total_budget)
    out["allocated_budget_rub"] = allocated_budget
    out["unallocated_budget_rub"] = max(float(total_budget) - allocated_budget, 0.0)
    out["support_limit_policy"] = selected_limit
    out["allocation_projection_mode"] = projection_mode
    return out


def _round_candidate_operationally(
    candidate: pd.DataFrame,
    source_plan: pd.DataFrame,
    engine: ForecastEngine,
    *,
    rounding_step_rub: float,
    business_constraints: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Round modifiable cells to operational units and preserve exact total budget."""
    step = float(rounding_step_rub)
    out = candidate.copy()
    out["operational_rounding_step_rub"] = step
    out["operational_rounding_applied"] = False
    if step <= 0 or out.empty:
        return out
    constraints = business_constraints or {}
    if any(
        constraints.get(key)
        for key in [
            "channel_min_share",
            "channel_max_share",
            "geo_min_share",
            "geo_max_share",
            "mandatory_channels",
            "mandatory_geos",
        ]
    ):
        out["operational_rounding_status"] = "skipped_aggregate_business_constraints"
        return out

    support_limit = str(out.get("support_limit_policy", pd.Series(["p99"])).iloc[0] or "p99")
    if support_limit not in {"p95", "p99", "robust_upper"}:
        support_limit = "p99"
    lower, upper, policies = _candidate_policy_bounds(
        out,
        source_plan,
        engine,
        support_limit=support_limit,
    )
    preferred = out["budget_rub"].to_numpy(dtype=float)
    target_total = float(preferred.sum())
    tolerance = max(
        BUDGET_RECONCILIATION_ABS_TOL_RUB,
        abs(target_total) * BUDGET_RECONCILIATION_REL_TOL,
    )
    fixed = np.array(
        [policy == "fixed_at_plan" for policy in policies],
        dtype=bool,
    ) | np.isclose(lower, upper, atol=tolerance, rtol=0.0)
    adjustable = ~fixed
    if not adjustable.any():
        out["operational_rounding_status"] = "not_needed_no_modifiable_cells"
        return out

    rounded = preferred.copy()
    modifiable_total = target_total - float(rounded[fixed].sum())
    mod_lower = lower[adjustable]
    mod_upper = upper[adjustable]
    raw_units = preferred[adjustable] / step
    lower_units = np.ceil(np.maximum(mod_lower, 0.0) / step - 1e-12).astype(int)
    upper_units = np.floor(np.maximum(mod_upper, 0.0) / step + 1e-12).astype(int)
    target_units = int(math.floor(max(modifiable_total, 0.0) / step + 1e-12))
    if target_units < int(lower_units.sum()) or target_units > int(upper_units.sum()):
        out["operational_rounding_status"] = "skipped_cell_caps_smaller_than_rounding_unit"
        return out

    units = np.clip(np.floor(raw_units).astype(int), lower_units, upper_units)
    while int(units.sum()) < target_units:
        available = np.where(units < upper_units)[0]
        if len(available) == 0:
            out["operational_rounding_status"] = "skipped_rounding_reconciliation_failed"
            return out
        priority = raw_units[available] - units[available]
        units[int(available[np.argmax(priority)])] += 1
    while int(units.sum()) > target_units:
        available = np.where(units > lower_units)[0]
        if len(available) == 0:
            out["operational_rounding_status"] = "skipped_rounding_reconciliation_failed"
            return out
        priority = units[available] - raw_units[available]
        units[int(available[np.argmax(priority)])] -= 1

    mod_values = units.astype(float) * step
    residual = modifiable_total - float(mod_values.sum())
    if residual > tolerance:
        room = mod_upper - mod_values
        available = np.where(room >= residual - tolerance)[0]
        if len(available) == 0:
            out["operational_rounding_status"] = "skipped_rounding_residual_infeasible"
            return out
        preferred_gap = np.abs((mod_values[available] + residual) - preferred[adjustable][available])
        mod_values[int(available[np.argmin(preferred_gap)])] += residual
    rounded[adjustable] = mod_values
    if (
        abs(float(rounded.sum()) - target_total) > tolerance
        or np.any(rounded < lower - tolerance)
        or np.any(rounded > upper + tolerance)
    ):
        out["operational_rounding_status"] = "skipped_post_rounding_bounds_failed"
        return out
    out["budget_rub"] = rounded
    out["allocated_budget_rub"] = float(rounded.sum())
    out["unallocated_budget_rub"] = np.maximum(
        pd.to_numeric(out["requested_budget_rub"], errors="coerce").fillna(target_total)
        - float(rounded.sum()),
        0.0,
    )
    out["operational_rounding_applied"] = True
    out["operational_rounding_status"] = "applied"
    return out


def _support_weighted_candidate(
    cells: pd.DataFrame,
    source_plan: pd.DataFrame,
    engine: ForecastEngine,
    total_budget: float,
) -> pd.DataFrame:
    """Return the largest p95-safe partial allocation closest to the source plan."""
    return _enforce_candidate_constraints(
        cells.copy(),
        source_plan,
        engine,
        total_budget,
        prefer_safe_support=True,
        support_limit="p95",
        allow_partial=True,
        projection_mode="proportional",
    )


def _generate_scenario5_candidates(
    cells: pd.DataFrame,
    source_plan: pd.DataFrame,
    engine: ForecastEngine,
    total_budget: float,
    scenario_policy: dict[str, Any] | None,
    business_constraints: dict[str, Any] | None,
) -> list[tuple[str, pd.DataFrame]]:
    """Build the internal S5 pool and expose partial only after full infeasibility."""

    policy = scenario_policy or {}
    support_levels = [
        str(value)
        for value in policy.get("support_expansion_levels")
        or ["p95", "p99", "robust_upper"]
    ]
    if not support_levels or any(
        value not in {"p95", "p99", "robust_upper"} for value in support_levels
    ):
        raise ValueError("Scenario 5 support expansion levels are invalid")
    approved_max = str(
        policy.get("approved_maximum_risk_boundary") or support_levels[-1]
    )
    if approved_max not in support_levels:
        raise ValueError("Scenario 5 approved maximum must be one configured expansion level")
    support_levels = support_levels[: support_levels.index(approved_max) + 1]
    projection_modes = [
        str(value)
        for value in policy.get("projection_modes") or ["proportional", "additive"]
    ]
    if any(value not in {"proportional", "additive"} for value in projection_modes):
        raise ValueError("Scenario 5 projection mode is invalid")

    candidates: list[tuple[str, pd.DataFrame]] = []
    for support_limit in support_levels:
        level_candidates: list[tuple[str, pd.DataFrame]] = []
        for projection_mode in projection_modes:
            try:
                candidate = _enforce_candidate_constraints(
                    cells.copy(),
                    source_plan,
                    engine,
                    total_budget,
                    support_limit=support_limit,
                    allow_partial=False,
                    business_constraints=business_constraints,
                    projection_mode=projection_mode,
                )
            except CandidateFeasibilityError:
                continue
            candidate = _annotate_scenario_semantics(
                candidate,
                scenario_kind="conservative_plan",
                scenario_variant="full_conservative",
                feasibility_status="feasible_full",
            )
            level_candidates.append(
                (
                    f"scenario5_full_conservative_{support_limit}_{projection_mode}",
                    candidate,
                )
            )
        if level_candidates:
            return level_candidates

    limiting_constraints = (
        "model_policy_and_support_capacity_at_" + approved_max
    )
    reason = (
        "Весь бюджет превышает доступную емкость ячеек в пределах утвержденной "
        "границы риска. Остаток не включен в расчет эффекта."
    )
    for projection_mode in projection_modes:
        try:
            candidate = _enforce_candidate_constraints(
                cells.copy(),
                source_plan,
                engine,
                total_budget,
                support_limit=approved_max,
                allow_partial=True,
                business_constraints=business_constraints,
                projection_mode=projection_mode,
            )
        except CandidateFeasibilityError:
            continue
        candidate = _annotate_scenario_semantics(
            candidate,
            scenario_kind="conservative_plan",
            scenario_variant="safe_partial",
            feasibility_status="feasible_partial",
            full_allocation_impossible_reason=reason,
            limiting_constraints=limiting_constraints,
        )
        candidates.append(
            (
                f"scenario5_safe_partial_{approved_max}_{projection_mode}",
                candidate,
            )
        )
    if not candidates:
        raise CandidateFeasibilityError(
            "Scenario 5 cannot allocate even a partial budget within model-policy bounds"
        )
    return candidates


def _enforce_support_caps(cells: pd.DataFrame, source_plan: pd.DataFrame, engine: ForecastEngine, total_budget: float) -> pd.DataFrame:
    """Backward-compatible wrapper for policy and support projection."""
    return _enforce_candidate_constraints(
        cells,
        source_plan,
        engine,
        total_budget,
        prefer_safe_support=True,
        support_limit="p95",
        allow_partial=False,
    )


@dataclass
class _CellResponseKernel:
    """Exact turnover response for one geo x channel as total budget changes."""

    cell_pos: int
    segment: str
    geo: str
    channel: str
    base_argument: np.ndarray
    unit_argument_per_rub: np.ndarray
    counterfactual_tanh: np.ndarray
    effect_multiplier: np.ndarray
    _draw_cache: dict[float, np.ndarray] = field(default_factory=dict, repr=False)

    def response_draws(self, budget_rub: float) -> np.ndarray:
        budget = max(float(budget_rub), 0.0)
        cache_key = round(budget, 6)
        cached = self._draw_cache.get(cache_key)
        if cached is not None:
            return cached
        response = (
            self.effect_multiplier
            * (
                np.tanh(self.base_argument + budget * self.unit_argument_per_rub)
                - self.counterfactual_tanh
            )
        ).sum(axis=1)
        self._draw_cache[cache_key] = response
        return response


def _posterior_draw_stat(draws: np.ndarray, statistic: str) -> float:
    values = np.asarray(draws, dtype=float)
    if statistic == "mean":
        return float(np.mean(values))
    if statistic == "p10":
        return float(np.percentile(values, 10))
    if statistic == "p90":
        return float(np.percentile(values, 90))
    if statistic == "risk_adjusted":
        return float(np.percentile(values, 50) - 0.25 * (np.percentile(values, 90) - np.percentile(values, 10)))
    return float(np.percentile(values, 50))


def _build_turnover_response_kernels(
    engine: ForecastEngine,
    plan: pd.DataFrame,
    cells: pd.DataFrame,
    campaign_name: str,
    *,
    n_samples: int,
    seed: int,
    analog_year: int | None,
    analog_missing_geo_policy: str,
) -> list[_CellResponseKernel]:
    """Compile the exact serving equation into reusable cell-level response kernels."""
    cells = cells.reset_index(drop=True)
    fit_lookup = {
        (str(meta.get("segment")), str(meta.get("target"))): (fit_key, meta)
        for fit_key, meta in (engine.metadata.get("fits") or {}).items()
    }
    kernels: list[_CellResponseKernel | None] = [None] * len(cells)
    sampled_lengths: set[int] = set()
    for segment, segment_cells in cells.groupby("segment", sort=False):
        fit = fit_lookup.get((str(segment), "turnover_per_user"))
        if fit is None:
            raise CandidateFeasibilityError(
                f"No turnover response fit for adaptive optimizer segment={segment!r}"
            )
        fit_key, fit_meta = fit
        segment_plan = plan[
            plan["campaign_name"].eq(campaign_name) & plan["segment"].eq(segment)
        ].copy()
        if segment_plan.empty:
            raise CandidateFeasibilityError(f"No source flighting rows for {campaign_name}/{segment}")
        start = min(segment_plan["date"])
        end = max(segment_plan["date"])
        l_max = int(fit_meta.get("l_max") or 14)
        horizon_end = end + timedelta(days=l_max)
        horizon = [start + timedelta(days=i) for i in range((horizon_end - start).days + 1)]
        channels = list(fit_meta["channels"])
        geos = list(fit_meta["geos"])
        tiers = list(fit_meta.get("market_size_tiers") or [])
        geo_to_tier = fit_meta.get("geo_to_tier") or {}
        y_scale = float(fit_meta["y_scale"])
        samples = engine._posterior_samples(fit_meta, n_samples, seed)
        alpha = np.asarray(samples["alpha"], dtype=float)
        lam = np.asarray(samples["lam"], dtype=float)
        beta = np.asarray(samples["beta"], dtype=float)
        beta_dims = tuple(samples["beta_dims"])
        sampled_n = int(alpha.shape[-1])
        sampled_lengths.add(sampled_n)
        denominator_cache: dict[str, dict[date, dict[str, Any]]] = {}

        for cell_pos, cell in segment_cells.iterrows():
            geo = str(cell["geo"])
            channel = str(cell["channel"])
            if geo not in geos or channel not in channels:
                raise CandidateFeasibilityError(
                    f"Adaptive optimizer cell is absent from turnover fit: {segment}/{geo}/{channel}"
                )
            geo_pos = geos.index(geo)
            ch_pos = channels.index(channel)
            denom_by_date = denominator_cache.get(geo)
            if denom_by_date is None:
                denom_by_date = {
                    dt: engine._denominator_for(
                        str(segment),
                        geo,
                        dt,
                        analog_year=analog_year,
                        missing_geo_policy=analog_missing_geo_policy,
                    )
                    for dt in horizon
                }
                denominator_cache[geo] = denom_by_date
            tier_name = str(
                geo_to_tier.get(geo)
                or denom_by_date[start].get("market_size_tier")
                or ""
            )
            tier_pos = tiers.index(tier_name) if tier_name in tiers else 0
            source = segment_plan[
                segment_plan["geo"].eq(geo) & segment_plan["channel"].eq(channel)
            ]
            by_date = source.groupby("date", dropna=False)["budget_rub"].sum().astype(float)
            source_total = float(by_date.sum())
            if source_total <= 0:
                raise CandidateFeasibilityError(
                    f"Adaptive optimizer requires a positive source profile for {segment}/{geo}/{channel}"
                )
            spend_share = np.array(
                [float(by_date.get(dt, 0.0)) / source_total for dt in horizon],
                dtype=float,
            )
            population = np.array(
                [max(float(denom_by_date[dt]["population_k"]), 1e-3) for dt in horizon],
                dtype=float,
            )
            x_scale = engine._x_scale(fit_key, geo, channel, tier_name)
            x_per_rub = (spend_share / population) / max(x_scale, 1e-8)
            warm_start = engine._warm_start_for(fit_key, geo, channel, start, l_max)
            alpha_values = alpha[ch_pos, :]
            lam_values = lam[ch_pos, :]
            warm_adstock = _normalized_adstock_draw_matrix(
                np.zeros_like(x_per_rub),
                alpha_values,
                l_max,
                warm_start=warm_start,
            )
            unit_adstock = _normalized_adstock_draw_matrix(
                x_per_rub,
                alpha_values,
                l_max,
            )
            beta_values = np.asarray(
                [
                    engine._beta_value(beta, beta_dims, s, ch_pos, geo_pos, tier_pos)
                    for s in range(sampled_n)
                ],
                dtype=float,
            )
            denominator = np.array(
                [float(denom_by_date[dt]["unique_users"]) for dt in horizon],
                dtype=float,
            )
            base_argument = lam_values[:, None] * warm_adstock / 2.0
            kernels[int(cell_pos)] = _CellResponseKernel(
                cell_pos=int(cell_pos),
                segment=str(segment),
                geo=geo,
                channel=channel,
                base_argument=base_argument,
                unit_argument_per_rub=lam_values[:, None] * unit_adstock / 2.0,
                counterfactual_tanh=np.tanh(base_argument),
                effect_multiplier=beta_values[:, None] * y_scale * denominator[None, :],
            )
    if len(sampled_lengths) != 1:
        raise CandidateFeasibilityError(
            f"Adaptive optimizer posterior sample lengths differ across campaign fits: {sorted(sampled_lengths)}"
        )
    if any(kernel is None for kernel in kernels):
        raise CandidateFeasibilityError("Adaptive optimizer failed to compile every campaign cell")
    return [kernel for kernel in kernels if kernel is not None]


def _allocation_response_draws(
    kernels: list[_CellResponseKernel],
    allocation: np.ndarray,
) -> tuple[np.ndarray, list[np.ndarray]]:
    cell_draws = [
        kernel.response_draws(float(allocation[kernel.cell_pos]))
        for kernel in kernels
    ]
    return np.vstack(cell_draws).sum(axis=0), cell_draws


def _greedy_marginal_allocation(
    kernels: list[_CellResponseKernel],
    lower: np.ndarray,
    upper: np.ndarray,
    total_budget: float,
    *,
    quantum_rub: float,
    statistic: str,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Solve the separable bounded response problem by diminishing marginal gains."""
    allocation = np.asarray(lower, dtype=float).copy()
    upper = np.asarray(upper, dtype=float)
    target_budget = min(float(total_budget), float(upper.sum()))
    tolerance = max(BUDGET_RECONCILIATION_ABS_TOL_RUB, abs(total_budget) * BUDGET_RECONCILIATION_REL_TOL)
    remaining = target_budget - float(allocation.sum())
    if remaining < -tolerance:
        raise CandidateFeasibilityError("Adaptive lower bounds exceed allocatable campaign budget")
    quantum = max(float(quantum_rub), SUPPORT_ABS_TOL_RUB)
    current_draws = [kernel.response_draws(float(allocation[kernel.cell_pos])) for kernel in kernels]
    heap: list[tuple[float, int, int, float, float, np.ndarray]] = []
    counter = 0
    kernel_evaluations = len(kernels)

    def push_next(cell_pos: int) -> None:
        nonlocal counter, kernel_evaluations
        room = float(upper[cell_pos] - allocation[cell_pos])
        if room <= tolerance:
            return
        delta = min(quantum, room)
        next_budget = float(allocation[cell_pos] + delta)
        next_draws = kernels[cell_pos].response_draws(next_budget)
        kernel_evaluations += 1
        gain = _posterior_draw_stat(next_draws, statistic) - _posterior_draw_stat(
            current_draws[cell_pos], statistic
        )
        heapq.heappush(
            heap,
            (-gain / max(delta, 1e-12), counter, cell_pos, float(allocation[cell_pos]), delta, next_draws),
        )
        counter += 1

    for cell_pos in range(len(kernels)):
        push_next(cell_pos)
    while remaining > tolerance and heap:
        if remaining < quantum - tolerance:
            best: tuple[float, int, float, np.ndarray] | None = None
            for cell_pos, kernel in enumerate(kernels):
                room = float(upper[cell_pos] - allocation[cell_pos])
                if room <= tolerance:
                    continue
                delta = min(remaining, room)
                next_draws = kernel.response_draws(float(allocation[cell_pos] + delta))
                kernel_evaluations += 1
                gain_per_rub = (
                    _posterior_draw_stat(next_draws, statistic)
                    - _posterior_draw_stat(current_draws[cell_pos], statistic)
                ) / max(delta, 1e-12)
                if best is None or gain_per_rub > best[0]:
                    best = (gain_per_rub, cell_pos, delta, next_draws)
            if best is None:
                break
            _, cell_pos, delta, next_draws = best
        else:
            _, _, cell_pos, expected_budget, delta, next_draws = heapq.heappop(heap)
            if abs(float(allocation[cell_pos]) - expected_budget) > tolerance:
                continue
            delta = min(delta, remaining)
            if delta < quantum - tolerance:
                next_draws = kernels[cell_pos].response_draws(float(allocation[cell_pos] + delta))
                kernel_evaluations += 1
        allocation[cell_pos] += delta
        remaining -= delta
        current_draws[cell_pos] = next_draws
        push_next(cell_pos)
    if remaining > tolerance:
        raise CandidateFeasibilityError(
            f"Adaptive marginal allocation left {remaining:.2f} RUB despite declared support capacity"
        )
    return allocation, {
        "kernel_evaluations_n": int(kernel_evaluations),
        "allocated_budget_rub": float(allocation.sum()),
        "unallocated_budget_rub": max(float(total_budget) - float(allocation.sum()), 0.0),
        "statistic": statistic,
    }


def _adaptive_coordinate_refine(
    kernels: list[_CellResponseKernel],
    initial_allocation: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    *,
    transfer_steps_rub: list[float],
    beam_width: int,
    max_evaluations: int,
    statistic: str,
) -> tuple[np.ndarray, list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Refine one feasible plan with exact paired donor/receiver posterior scoring."""
    allocation = np.asarray(initial_allocation, dtype=float).copy()
    total_draws, cell_draws = _allocation_response_draws(kernels, allocation)
    current_score = _posterior_draw_stat(total_draws, statistic)
    attempts = 0
    kernel_evaluations = len(kernels)
    trace: list[dict[str, Any]] = []
    top_proposals: list[dict[str, Any]] = []
    exhausted = False
    smallest_step_checked = False
    tolerance = max(BUDGET_RECONCILIATION_ABS_TOL_RUB, abs(float(allocation.sum())) * BUDGET_RECONCILIATION_REL_TOL)
    score_tolerance = max(abs(current_score) * 1e-10, 1.0)

    steps = sorted({float(value) for value in transfer_steps_rub if float(value) > 0}, reverse=True)
    if not steps:
        raise ValueError("transfer_steps_rub must contain at least one positive value")
    smallest_step = steps[-1]
    for step in steps:
        while attempts < max_evaluations:
            donor_rank: list[tuple[float, int, float, np.ndarray]] = []
            receiver_rank: list[tuple[float, int, float, np.ndarray]] = []
            for cell_pos, kernel in enumerate(kernels):
                donor_room = float(allocation[cell_pos] - lower[cell_pos])
                if donor_room > tolerance:
                    amount = min(step, donor_room)
                    changed = kernel.response_draws(float(allocation[cell_pos] - amount))
                    kernel_evaluations += 1
                    score = _posterior_draw_stat(total_draws - cell_draws[cell_pos] + changed, statistic)
                    donor_rank.append((score, cell_pos, amount, changed))
                receiver_room = float(upper[cell_pos] - allocation[cell_pos])
                if receiver_room > tolerance:
                    amount = min(step, receiver_room)
                    changed = kernel.response_draws(float(allocation[cell_pos] + amount))
                    kernel_evaluations += 1
                    score = _posterior_draw_stat(total_draws - cell_draws[cell_pos] + changed, statistic)
                    receiver_rank.append((score, cell_pos, amount, changed))
            donors = sorted(donor_rank, reverse=True)[: max(int(beam_width), 1)]
            receivers = sorted(receiver_rank, reverse=True)[: max(int(beam_width), 1)]
            pair_proposals: list[dict[str, Any]] = []
            for _, donor_pos, donor_amount, donor_changed in donors:
                for _, receiver_pos, receiver_amount, receiver_changed in receivers:
                    if attempts >= max_evaluations:
                        exhausted = True
                        break
                    if donor_pos == receiver_pos:
                        continue
                    amount = min(step, donor_amount, receiver_amount)
                    if amount <= tolerance:
                        continue
                    donor_response = donor_changed
                    receiver_response = receiver_changed
                    if abs(amount - donor_amount) > tolerance:
                        donor_response = kernels[donor_pos].response_draws(float(allocation[donor_pos] - amount))
                        kernel_evaluations += 1
                    if abs(amount - receiver_amount) > tolerance:
                        receiver_response = kernels[receiver_pos].response_draws(float(allocation[receiver_pos] + amount))
                        kernel_evaluations += 1
                    proposal_draws = (
                        total_draws
                        - cell_draws[donor_pos]
                        - cell_draws[receiver_pos]
                        + donor_response
                        + receiver_response
                    )
                    score = _posterior_draw_stat(proposal_draws, statistic)
                    proposal_allocation = allocation.copy()
                    proposal_allocation[donor_pos] -= amount
                    proposal_allocation[receiver_pos] += amount
                    proposal = {
                        "score": score,
                        "allocation": proposal_allocation,
                        "donor_pos": donor_pos,
                        "receiver_pos": receiver_pos,
                        "amount_rub": amount,
                        "step_rub": step,
                        "draws": proposal_draws,
                        "donor_draws": donor_response,
                        "receiver_draws": receiver_response,
                    }
                    pair_proposals.append(proposal)
                    attempts += 1
                if exhausted:
                    break
            if not pair_proposals:
                if step == smallest_step:
                    smallest_step_checked = True
                break
            pair_proposals.sort(key=lambda row: float(row["score"]), reverse=True)
            for proposal in pair_proposals[:3]:
                top_proposals.append(
                    {
                        "allocation": proposal["allocation"].copy(),
                        "score": float(proposal["score"]),
                        "step_rub": float(step),
                        "statistic": statistic,
                    }
                )
            best = pair_proposals[0]
            accepted = float(best["score"]) > current_score + score_tolerance
            trace.append(
                {
                    "attempts_cumulative_n": attempts,
                    "step_rub": float(step),
                    "donor_pos": int(best["donor_pos"]),
                    "receiver_pos": int(best["receiver_pos"]),
                    "transfer_rub": float(best["amount_rub"]),
                    "score_before": float(current_score),
                    "score_after": float(best["score"]),
                    "accepted": bool(accepted),
                    "statistic": statistic,
                }
            )
            if not accepted:
                if step == smallest_step:
                    smallest_step_checked = True
                break
            allocation = best["allocation"]
            total_draws = best["draws"]
            cell_draws[int(best["donor_pos"])] = best["donor_draws"]
            cell_draws[int(best["receiver_pos"])] = best["receiver_draws"]
            current_score = float(best["score"])
        if attempts >= max_evaluations:
            exhausted = True
            break
    return allocation, top_proposals, trace, {
        "attempts_evaluated_n": int(attempts),
        "kernel_evaluations_n": int(kernel_evaluations),
        "converged": bool(smallest_step_checked and not exhausted),
        "budget_exhausted": bool(exhausted),
        "final_score": float(current_score),
    }


def _allocation_hash(allocation: np.ndarray) -> str:
    normalized = np.round(np.asarray(allocation, dtype=float), 6)
    return hashlib.sha256(normalized.tobytes()).hexdigest()


def _candidate_from_allocation(
    cells: pd.DataFrame,
    allocation: np.ndarray,
    total_budget: float,
    *,
    support_limit: str,
    diagnostics: dict[str, Any],
) -> pd.DataFrame:
    out = cells.copy().reset_index(drop=True)
    out["budget_rub"] = np.asarray(allocation, dtype=float)
    allocated = float(out["budget_rub"].sum())
    tolerance = max(
        BUDGET_RECONCILIATION_ABS_TOL_RUB,
        abs(float(total_budget)) * BUDGET_RECONCILIATION_REL_TOL,
    )
    if abs(allocated - float(total_budget)) > tolerance:
        raise CandidateFeasibilityError(
            "Scenario 6 candidate does not allocate the full requested budget"
        )
    out["requested_budget_rub"] = float(total_budget)
    out["allocated_budget_rub"] = allocated
    out["unallocated_budget_rub"] = 0.0
    out["support_limit_policy"] = support_limit
    out["allocation_projection_mode"] = "adaptive_marginal_posterior"
    out["operational_rounding_step_rub"] = 0.0
    out["operational_rounding_applied"] = False
    out["operational_rounding_status"] = "disabled_pre_score"
    for key, value in diagnostics.items():
        out[key] = value
    return _annotate_scenario_semantics(
        out,
        scenario_kind="optimized_plan",
        scenario_variant="full_effect_maximizing",
        feasibility_status="feasible_full",
    )


def _generate_adaptive_scenario6_candidates(
    cells: pd.DataFrame,
    source_plan: pd.DataFrame,
    engine: ForecastEngine,
    campaign_name: str,
    total_budget: float,
    *,
    search_samples: int,
    seed: int,
    max_evaluations: int,
    finalists: int,
    scenario_config: dict[str, Any],
    business_constraints: dict[str, Any],
    analog_year: int | None,
    analog_missing_geo_policy: str,
) -> tuple[list[tuple[str, pd.DataFrame]], list[dict[str, Any]], dict[str, Any]]:
    """Generate a compact finalist pool after a high-resolution posterior marginal search."""
    if scenario_config.get("require_full_budget") is False:
        raise ValueError("Scenario 6 policy must require the full requested budget")
    if scenario_config.get("infeasible_when_full_budget_cannot_be_allocated") is False:
        raise ValueError("Scenario 6 policy must expose full-budget infeasibility")
    aggregate_constraint_keys = {
        "channels_allowed",
        "geos_allowed",
        "channel_min_share",
        "channel_max_share",
        "geo_min_share",
        "geo_max_share",
        "mandatory_channels",
        "mandatory_geos",
    }
    if any(business_constraints.get(key) for key in aggregate_constraint_keys):
        raise CandidateFeasibilityError(
            "Adaptive marginal search requires aggregate business constraints to be compiled into cell bounds"
        )
    cells = cells.reset_index(drop=True)
    quantum = float(
        scenario_config.get("allocation_quantum_rub")
        or DEFAULT_OPTIMIZER_ALLOCATION_QUANTUM_RUB
    )
    transfer_steps = [
        float(value)
        for value in scenario_config.get("transfer_steps_rub")
        or [5_000_000.0, 1_000_000.0, 250_000.0, 50_000.0]
    ]
    beam_width = int(scenario_config.get("beam_width") or 8)
    max_pool = int(scenario_config.get("max_candidate_pool") or max(finalists * 2, 8))
    base_records: list[dict[str, Any]] = []
    trace_rows: list[dict[str, Any]] = []
    kernel_evaluations = 0
    attempts = 0
    convergence_flags: list[bool] = []
    exhaustion_flags: list[bool] = []
    ordered_support_limits = ["p95", "p99", "robust_upper"]
    approved_max = str(
        scenario_config.get("approved_maximum_risk_boundary") or "robust_upper"
    )
    if approved_max not in ordered_support_limits:
        raise ValueError("Scenario 6 approved maximum risk boundary is invalid")
    approved_index = ordered_support_limits.index(approved_max)
    default_support_limits = [
        value
        for value in ("p99", approved_max)
        if ordered_support_limits.index(value) <= approved_index
    ] or [approved_max]
    support_limits = [
        str(value)
        for value in scenario_config.get("support_limits")
        or default_support_limits
    ]
    if not support_limits or any(value not in ordered_support_limits for value in support_limits):
        raise ValueError("Scenario 6 support limits are invalid")
    if any(ordered_support_limits.index(value) > approved_index for value in support_limits):
        raise ValueError("Scenario 6 support limit exceeds the approved risk boundary")
    support_limits = list(dict.fromkeys(support_limits))

    infeasible_capacities: list[str] = []
    tolerance = max(
        BUDGET_RECONCILIATION_ABS_TOL_RUB,
        abs(float(total_budget)) * BUDGET_RECONCILIATION_REL_TOL,
    )
    feasible_bounds: list[tuple[str, np.ndarray, np.ndarray, np.ndarray]] = []
    for support_limit in support_limits:
        try:
            lower, upper, _ = _candidate_policy_bounds(
                cells,
                source_plan,
                engine,
                support_limit=support_limit,
            )
        except CandidateFeasibilityError as exc:
            infeasible_capacities.append(f"{support_limit}:{exc}")
            continue
        lower_total = float(lower.sum())
        upper_total = float(upper.sum())
        if lower_total > float(total_budget) + tolerance:
            infeasible_capacities.append(
                f"{support_limit}:required_minimum={lower_total:.6f}>requested={total_budget:.6f}"
            )
            continue
        if upper_total < float(total_budget) - tolerance:
            infeasible_capacities.append(
                f"{support_limit}:capacity={upper_total:.6f}<requested={total_budget:.6f}"
            )
            continue
        projected_source = _enforce_candidate_constraints(
            cells.copy(),
            source_plan,
            engine,
            total_budget,
            support_limit=support_limit,
            allow_partial=False,
            business_constraints=business_constraints,
        )["budget_rub"].to_numpy(dtype=float)
        feasible_bounds.append((support_limit, lower, upper, projected_source))

    if not feasible_bounds:
        detail = "; ".join(infeasible_capacities) or "no feasible full-budget allocation"
        raise CandidateFeasibilityError(
            "Scenario 6 full-budget allocation is infeasible within approved risk limits: "
            + detail
        )

    # Posterior kernels are expensive to compile.  A campaign that cannot place
    # its full budget under any approved support limit must fail before this
    # point, without opening posterior fits or spending candidate attempts.
    kernels = _build_turnover_response_kernels(
        engine,
        source_plan,
        cells,
        campaign_name,
        n_samples=search_samples,
        seed=seed,
        analog_year=analog_year,
        analog_missing_geo_policy=analog_missing_geo_policy,
    )

    for support_limit, lower, upper, projected_source in feasible_bounds:
        base_specs: list[tuple[str, str, np.ndarray]] = [
            ("source_projected", "p50", projected_source)
        ]
        for statistic in ["p50", "mean", "p10", "risk_adjusted"]:
            allocation, greedy_diag = _greedy_marginal_allocation(
                kernels,
                lower,
                upper,
                total_budget,
                quantum_rub=quantum,
                statistic=statistic,
            )
            kernel_evaluations += int(greedy_diag["kernel_evaluations_n"])
            base_specs.append((f"greedy_{statistic}", statistic, allocation))

        refine_origins = {"source_projected", "greedy_p50", "greedy_risk_adjusted"}
        refine_jobs = max(len(support_limits) * len(refine_origins), 1)
        per_job_budget = max(int(max_evaluations) // refine_jobs, beam_width * beam_width)
        for origin, statistic, allocation in base_specs:
            total_draws, _ = _allocation_response_draws(kernels, allocation)
            base_records.append(
                {
                    "allocation": allocation.copy(),
                    "support_limit": support_limit,
                    "origin": origin,
                    "statistic": statistic,
                    "p10": float(np.percentile(total_draws, 10)),
                    "p50": float(np.percentile(total_draws, 50)),
                    "p90": float(np.percentile(total_draws, 90)),
                }
            )
            if origin not in refine_origins or attempts >= max_evaluations:
                continue
            remaining_budget = min(per_job_budget, max_evaluations - attempts)
            refined, proposals, refine_trace, refine_diag = _adaptive_coordinate_refine(
                kernels,
                allocation,
                lower,
                upper,
                transfer_steps_rub=transfer_steps,
                beam_width=beam_width,
                max_evaluations=remaining_budget,
                statistic="p50" if statistic != "p10" else "p10",
            )
            attempts += int(refine_diag["attempts_evaluated_n"])
            kernel_evaluations += int(refine_diag["kernel_evaluations_n"])
            convergence_flags.append(bool(refine_diag["converged"]))
            exhaustion_flags.append(bool(refine_diag["budget_exhausted"]))
            for trace in refine_trace:
                donor = cells.iloc[int(trace["donor_pos"])]
                receiver = cells.iloc[int(trace["receiver_pos"])]
                trace_rows.append(
                    {
                        "campaign_name": campaign_name,
                        "support_limit": support_limit,
                        "origin": origin,
                        **trace,
                        "donor_geo": donor["geo"],
                        "donor_channel": donor["channel"],
                        "receiver_geo": receiver["geo"],
                        "receiver_channel": receiver["channel"],
                    }
                )
            for proposal in proposals:
                proposal_draws, _ = _allocation_response_draws(kernels, proposal["allocation"])
                base_records.append(
                    {
                        "allocation": proposal["allocation"].copy(),
                        "support_limit": support_limit,
                        "origin": f"{origin}_proposal",
                        "statistic": statistic,
                        "p10": float(np.percentile(proposal_draws, 10)),
                        "p50": float(np.percentile(proposal_draws, 50)),
                        "p90": float(np.percentile(proposal_draws, 90)),
                    }
                )
            refined_draws, _ = _allocation_response_draws(kernels, refined)
            base_records.append(
                {
                    "allocation": refined.copy(),
                    "support_limit": support_limit,
                    "origin": f"{origin}_refined",
                    "statistic": statistic,
                    "p10": float(np.percentile(refined_draws, 10)),
                    "p50": float(np.percentile(refined_draws, 50)),
                    "p90": float(np.percentile(refined_draws, 90)),
                }
            )

    unique: dict[str, dict[str, Any]] = {}
    for record in base_records:
        digest = _allocation_hash(record["allocation"])
        incumbent = unique.get(digest)
        if incumbent is None or float(record["p50"]) > float(incumbent["p50"]):
            unique[digest] = record
    unique_records = list(unique.values())
    if not unique_records:
        raise CandidateFeasibilityError(
            "Scenario 6 search produced no full-budget candidate inside approved risk limits"
        )
    selected: list[dict[str, Any]] = []
    per_limit = max(max_pool // max(len(support_limits), 1), 2)
    for support_limit in support_limits:
        rows = [row for row in unique_records if row["support_limit"] == support_limit]
        if not rows:
            continue
        chosen: dict[str, dict[str, Any]] = {}
        for row in sorted(rows, key=lambda value: float(value["p50"]), reverse=True)[: max(per_limit - 1, 1)]:
            chosen[_allocation_hash(row["allocation"])] = row
        best_downside = max(rows, key=lambda value: float(value["p10"]))
        chosen[_allocation_hash(best_downside["allocation"])] = best_downside
        selected.extend(chosen.values())
    selected = sorted(selected, key=lambda value: float(value["p50"]), reverse=True)[:max_pool]
    diagnostics = {
        "search_attempts_evaluated_n": int(attempts),
        "search_kernel_evaluations_n": int(kernel_evaluations),
        "search_unique_allocations_n": int(len(unique_records)),
        "search_candidate_pool_n": int(len(selected)),
        "search_max_evaluations_n": int(max_evaluations),
        "search_allocation_quantum_rub": float(quantum),
        "search_smallest_transfer_rub": float(min(transfer_steps)),
        "search_effective_dimension_n": int(
            sum(policy in {"optimize", "no_increase"} for policy in _candidate_policy_bounds(
                cells,
                source_plan,
                engine,
                support_limit="robust_upper",
            )[2])
        ),
        "search_converged": bool(convergence_flags and all(convergence_flags)),
        "search_budget_exhausted": bool(any(exhaustion_flags)),
        "search_posterior_samples": int(search_samples),
    }
    candidates: list[tuple[str, pd.DataFrame]] = []
    for index, record in enumerate(selected, start=1):
        candidate_name = (
            f"{campaign_name}__scenario6_adaptive_marginal_{record['support_limit']}_{index:03d}"
        )
        candidate_diagnostics = {
            **diagnostics,
            "search_objective": str(record["statistic"]),
            "search_support_limit": str(record["support_limit"]),
            "search_kernel_score_p10": float(record["p10"]),
            "search_kernel_score_p50": float(record["p50"]),
            "search_kernel_score_p90": float(record["p90"]),
        }
        candidates.append(
            (
                candidate_name,
                _candidate_from_allocation(
                    cells,
                    record["allocation"],
                    total_budget,
                    support_limit=str(record["support_limit"]),
                    diagnostics=candidate_diagnostics,
                ),
            )
        )
    return candidates, trace_rows, diagnostics


def _candidate_policy_violations(
    candidate: pd.DataFrame,
    current_cells: pd.DataFrame,
    source_plan: pd.DataFrame,
    engine: ForecastEngine,
    business_constraints: dict[str, Any] | None = None,
) -> tuple[int, str]:
    keys = ["segment", "geo", "channel"]
    current_by_key = {
        tuple(str(row[key]) for key in keys): float(row["budget_rub"])
        for _, row in current_cells.iterrows()
    }
    violations: list[str] = []
    for _, cell in candidate.iterrows():
        key = tuple(str(cell[name]) for name in keys)
        current = current_by_key.get(key, 0.0)
        value = float(cell["budget_rub"])
        capability = engine._capability_row(str(cell["segment"]), "turnover_per_user", str(cell["channel"]))
        policy = str(capability.get("optimizer_use") or "blocked")
        tolerance = max(BUDGET_RECONCILIATION_ABS_TOL_RUB, abs(current) * BUDGET_RECONCILIATION_REL_TOL)
        if policy == "fixed_at_plan" and abs(value - current) > tolerance:
            violations.append(f"FIXED_AT_PLAN_CHANGED:{cell['channel']}:{cell['geo']}")
        elif policy == "no_increase" and value > current + tolerance:
            violations.append(f"NO_INCREASE_EXCEEDED:{cell['channel']}:{cell['geo']}")
        elif policy not in {"optimize", "no_increase", "fixed_at_plan"} and value > tolerance:
            violations.append(f"BLOCKED_CELL_FUNDED:{cell['channel']}:{cell['geo']}")
        hard_cap = _support_cap_rub_for_cell(cell, source_plan, engine, limit="robust_upper")
        if value > hard_cap + max(SUPPORT_ABS_TOL_RUB, abs(hard_cap) * SUPPORT_REL_TOL):
            violations.append(f"ROBUST_SUPPORT_UPPER_EXCEEDED:{cell['channel']}:{cell['geo']}")
    constraints = business_constraints or {}
    for column, allowed_key, min_key, max_key in [
        ("channel", "channels_allowed", "channel_min_share", "channel_max_share"),
        ("geo", "geos_allowed", "geo_min_share", "geo_max_share"),
    ]:
        allowed = {str(value) for value in constraints.get(allowed_key) or []}
        if allowed:
            funded_disallowed = candidate[
                ~candidate[column].astype(str).isin(allowed)
                & candidate["budget_rub"].astype(float).gt(SUPPORT_ABS_TOL_RUB)
            ]
            if not funded_disallowed.empty:
                violations.append(f"{allowed_key.upper()}_VIOLATED")
        grouped = candidate.groupby(column, dropna=False)["budget_rub"].sum()
        total = max(float(candidate["budget_rub"].sum()), 1e-12)
        for label, share in (constraints.get(min_key) or {}).items():
            if float(grouped.get(label, 0.0)) / total + SUPPORT_REL_TOL < float(share):
                violations.append(f"{min_key.upper()}:{label}")
        for label, share in (constraints.get(max_key) or {}).items():
            if float(grouped.get(label, 0.0)) / total > float(share) + SUPPORT_REL_TOL:
                violations.append(f"{max_key.upper()}:{label}")
    return len(violations), "|".join(violations) if violations else "OK"


def _candidate_method(candidate_name: str) -> str:
    if "__scenario1_current_plan" in candidate_name:
        return "scenario1_current_plan"
    if "__scenario2_equal_cell_split" in candidate_name:
        return "scenario2_equal_cell_split"
    if "__scenario3_channel_balanced" in candidate_name:
        return "scenario3_channel_balanced"
    if "__scenario4_geo_balanced" in candidate_name:
        return "scenario4_geo_balanced"
    if "__scenario5_full_conservative" in candidate_name:
        return "scenario5_full_conservative"
    if "__scenario5_safe_partial" in candidate_name:
        return "scenario5_safe_partial"
    if "__scenario5_support_weighted" in candidate_name:
        return "scenario5_support_weighted_legacy"
    if "__scenario6_" in candidate_name:
        return "scenario6_search"
    return "other"


def _objective_allowed_counts(value: Any) -> int:
    text = str(value or "")
    total = 0
    for token in text.split(";"):
        if not token or ":" not in token:
            continue
        key, raw = token.split(":", 1)
        if key.strip() in {
            "optimize",
            "no_increase",
            "objective_allowed",
            "objective_allowed_with_penalty",
        }:
            try:
                total += int(float(raw))
            except ValueError:
                pass
    return total


def _summary_token_count(value: Any, tokens: set[str]) -> int:
    text = str(value or "")
    total = 0
    for token in text.split(";"):
        if not token or ":" not in token:
            continue
        key, raw = token.split(":", 1)
        if key.strip() in tokens:
            try:
                total += int(float(raw))
            except ValueError:
                pass
    return total


def _candidate_total_rows(summary: pd.DataFrame, target: str) -> pd.DataFrame:
    if summary.empty:
        return pd.DataFrame()
    sub = summary[(summary["target"] == target) & (summary["channel"] == "__TOTAL__")].copy()
    campaign_totals = sub[sub["segment"].eq("__ALL__")]
    return campaign_totals if not campaign_totals.empty else sub


def _candidate_score(summary: pd.DataFrame, objective_contract: dict[str, Any] | None = None) -> float:
    if summary.empty:
        return -np.inf
    contract = objective_contract or _compile_optimizer_objective(None)
    sub = _candidate_total_rows(summary, str(contract["target"]))
    if sub.empty:
        return -np.inf
    if "optimizer_use_counts" in sub.columns:
        sub = sub[sub["optimizer_use_counts"].map(_objective_allowed_counts) > 0]
    if sub.empty:
        return -np.inf
    metric = str(contract["metric"])
    values = pd.to_numeric(sub[metric], errors="coerce")
    if values.isna().any():
        return -np.inf
    return float(values.sum())


def _candidate_downside_score(summary: pd.DataFrame, objective_contract: dict[str, Any] | None = None) -> float:
    if summary.empty:
        return -np.inf
    contract = objective_contract or _compile_optimizer_objective(None)
    sub = _candidate_total_rows(summary, str(contract["target"]))
    if sub.empty:
        return -np.inf
    if "optimizer_use_counts" in sub.columns:
        sub = sub[sub["optimizer_use_counts"].map(_objective_allowed_counts) > 0]
    metric = str(contract["downside_metric"])
    values = pd.to_numeric(sub[metric], errors="coerce")
    return float(values.sum()) if not sub.empty and not values.isna().any() else -np.inf


def _candidate_p10_score(summary: pd.DataFrame) -> float:
    """Backward-compatible turnover p10 helper for technical outputs/tests."""
    contract = _compile_optimizer_objective({"primary": "maximize_incremental_turnover_p50"})
    return _candidate_downside_score(summary, contract)


def _candidate_support_warnings(summary: pd.DataFrame) -> int:
    if summary.empty:
        return 999_999
    sub = _candidate_total_rows(summary, "turnover_per_user")
    if sub.empty:
        sub = summary[summary["target"] == "turnover_per_user"].copy()
    warning_column = "spend_support_warnings_n" if "spend_support_warnings_n" in sub.columns else "support_warnings_n"
    if sub.empty or warning_column not in sub:
        return 999_999
    return int(pd.to_numeric(sub[warning_column], errors="coerce").fillna(0).max())


def _candidate_hard_support_warnings(detail: pd.DataFrame, candidate_name: str) -> int:
    if detail.empty:
        return 0
    return _candidate_support_level_warnings(detail, candidate_name, {SUPPORT_LEVEL_OUTSIDE})


def _candidate_support_level_warnings(
    detail: pd.DataFrame,
    candidate_name: str,
    levels: set[str],
) -> int:
    if detail.empty:
        return 0
    sub = detail[
        (detail["campaign_name"] == candidate_name)
        & (detail["target"] == "turnover_per_user")
    ].copy()
    if "support_level" in sub.columns:
        return int(sub["support_level"].astype(str).isin(levels).sum())
    if SUPPORT_LEVEL_OUTSIDE in levels and "support_flags" in sub.columns:
        return int(
            sub["support_flags"]
            .astype(str)
            .str.contains("FUTURE_DAILY_SPEND_GT_ROBUST_HIST_UPPER", na=False)
            .sum()
        )
    return 0


def _candidate_quality_counts(summary: pd.DataFrame) -> tuple[int, int]:
    sub = _candidate_total_rows(summary, "turnover_per_user")
    if sub.empty:
        sub = summary[summary["target"] == "turnover_per_user"].copy()
    if sub.empty:
        return 999_999, 999_999
    row = sub.iloc[0]
    diagnostic = _summary_token_count(row.get("allowed_use_counts"), {"diagnostic"}) + _summary_token_count(
        row.get("risk_level_counts"), {"high"}
    )
    caution = _summary_token_count(row.get("allowed_use_counts"), {"caution"}) + _summary_token_count(
        row.get("risk_level_counts"), {"medium"}
    )
    return diagnostic, caution


def _risk_policy_violation_count(
    diagnostic_rows: int,
    caution_rows: int,
    objective_contract: dict[str, Any],
) -> int:
    if objective_contract["model_risk_policy"] == "strict" and (diagnostic_rows > 0 or caution_rows > 0):
        return 1
    return 0


def _reliable_candidate_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    score = float(item.get("score") if np.isfinite(item.get("score", -np.inf)) else -np.inf)
    downside_score = float(
        item.get("downside_score")
        if np.isfinite(item.get("downside_score", -np.inf))
        else -np.inf
    )
    unallocated = item.get("unallocated_budget_rub")
    if unallocated is None and isinstance(item.get("cells"), pd.DataFrame):
        cells = item["cells"]
        if not cells.empty and "unallocated_budget_rub" in cells:
            unallocated = cells["unallocated_budget_rub"].iloc[0]
    return (
        int(item.get("hard_support_warnings_n") or 0),
        int(item.get("policy_violations_n") or 0),
        int(item.get("risk_policy_violations_n") or 0),
        int(item.get("strong_support_warnings_n") or 0),
        int(item.get("support_warnings_n") or 0),
        int(item.get("diagnostic_target_rows") or 0),
        int(item.get("caution_target_rows") or 0),
        float(unallocated or 0.0),
        -score,
        -downside_score,
        str(item.get("candidate_name") or ""),
    )


def _paired_candidate_comparisons(
    draw_totals: pd.DataFrame,
    *,
    source_campaign_name: str,
    reference_candidate_name: str,
    decision_policy: dict[str, Any],
) -> pd.DataFrame:
    """Compare candidate and source-plan effects on identical posterior draws."""
    if draw_totals.empty:
        return pd.DataFrame()
    materiality = decision_policy["materiality"]
    rows: list[dict[str, Any]] = []
    for target, target_draws in draw_totals.groupby("target", dropna=False):
        reference = target_draws[
            target_draws["campaign_name"].eq(reference_candidate_name)
        ][["draw_index", "total_effect"]].rename(columns={"total_effect": "reference_effect"})
        if reference.empty:
            continue
        reference_p50 = float(np.percentile(reference["reference_effect"].to_numpy(dtype=float), 50))
        gain_threshold = max(
            float(materiality["min_incremental_rto_gain_rub"]),
            abs(reference_p50) * float(materiality["min_incremental_rto_gain_share"]),
        ) if str(target) == "turnover_per_user" else 0.0
        noninferiority_floor = -abs(reference_p50) * float(
            materiality["max_p10_degradation_share"]
        )
        for candidate_name, candidate in target_draws.groupby("campaign_name", dropna=False):
            merged = candidate[["draw_index", "total_effect"]].merge(
                reference,
                on="draw_index",
                how="inner",
                validate="one_to_one",
            )
            if merged.empty:
                continue
            delta = (
                merged["total_effect"].to_numpy(dtype=float)
                - merged["reference_effect"].to_numpy(dtype=float)
            )
            rows.append(
                {
                    "source_campaign_name": source_campaign_name,
                    "candidate_name": str(candidate_name),
                    "reference_candidate_name": reference_candidate_name,
                    "target": str(target),
                    "paired_delta_p10": float(np.percentile(delta, 10)),
                    "paired_delta_p50": float(np.percentile(delta, 50)),
                    "paired_delta_p90": float(np.percentile(delta, 90)),
                    "paired_probability_gt_zero": float(np.mean(delta > 0.0)),
                    "paired_probability_gt_materiality": float(np.mean(delta >= gain_threshold)),
                    "paired_probability_noninferior": float(np.mean(delta >= noninferiority_floor)),
                    "paired_materiality_threshold": float(gain_threshold),
                    "paired_noninferiority_floor": float(noninferiority_floor),
                    "paired_draws_n": int(len(delta)),
                }
            )
    return pd.DataFrame(rows)


def run_optimizer_from_flighting(
    model_run_dir: str | Path,
    flighting_path: str | Path,
    output_dir: str | Path,
    run_id: str,
    *,
    search_candidates: int = DEFAULT_OPTIMIZER_SEARCH_CANDIDATES,
    search_samples: int = 60,
    final_samples: int = DEFAULT_FORECAST_SAMPLES,
    seed: int = 42,
    finalists: int = DEFAULT_OPTIMIZER_FINALISTS,
    workflow_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    started_perf = time.monotonic()
    workflow_config = workflow_config or {}
    scenario_cfg = ((workflow_config.get("optimizer") or {}).get("scenario_6") or {})
    objective_cfg = workflow_config.get("objective") or {}
    objective_contract = _compile_optimizer_objective(objective_cfg)
    decision_policy = _compile_decision_policy(workflow_config.get("decision_policy") or {})
    scenario6_execution_policy = {
        **(decision_policy.get("scenario_6") or {}),
        **scenario_cfg,
    }
    guardrail_cfg = objective_cfg.get("guardrails") or {}
    budget_cfg = workflow_config.get("budget") or {}
    constraints_cfg = workflow_config.get("constraints") or {}
    scenario6_enabled = bool(scenario_cfg.get("enabled", True))
    requested_method = str(scenario_cfg.get("default_method") or "adaptive_marginal_posterior")
    final_seed = int(scenario_cfg.get("final_random_seed") or (seed + 10_000))
    analog_year = _future_controls_analog_year(workflow_config.get("future_controls") or {})
    analog_missing_geo_policy = _future_controls_missing_geo_policy(
        workflow_config.get("future_controls") or {}
    )
    verification_mode = str(
        ((workflow_config.get("model_ref") or {}).get("verification_mode"))
        or "full_lineage"
    )
    engine = ForecastEngine.from_run_dir(
        model_run_dir,
        auto_export=verification_mode == "full_lineage",
        validate_package_lineage=verification_mode == "full_lineage",
    )
    model_inventory = serving_model_inventory(engine.metadata)
    if str(decision_policy.get("schema_version") or "").startswith("3."):
        model_inventory = validate_serving_model_inventory(engine.metadata)
    plan = pd.DataFrame(read_daily_flighting(flighting_path))
    plan["date"] = pd.to_datetime(plan["date"]).dt.date
    output_dir = ensure_dir(output_dir)
    candidate_summaries: list[dict[str, Any]] = []
    finalist_rows: list[dict[str, Any]] = []
    allocation_rows: list[dict[str, Any]] = []
    paired_comparison_rows: list[dict[str, Any]] = []
    search_trace_rows: list[dict[str, Any]] = []
    scenario_evaluations_n = 0
    posterior_fit_loads_before_turnover_only_n = 0
    posterior_fit_loads_after_turnover_only_n = 0

    campaign_names = sorted(plan["campaign_name"].unique())
    for campaign_pos, campaign_name in enumerate(campaign_names, start=1):
        print(
            json.dumps(
                {
                    "event": "optimizer_progress",
                    "phase": "candidate_generation",
                    "campaign": campaign_name,
                    "campaign_index": campaign_pos,
                    "campaigns_total": len(campaign_names),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        cells = _campaign_cell_rows(plan, campaign_name)
        total_budget = float(cells["budget_rub"].sum())
        if total_budget <= 0 or cells.empty:
            continue
        campaign_segments_n = int(cells["segment"].astype(str).nunique())
        configured_total = budget_cfg.get("total_budget_rub")
        if configured_total is not None:
            configured_total = float(configured_total)
            tolerance = max(BUDGET_RECONCILIATION_ABS_TOL_RUB, abs(total_budget) * BUDGET_RECONCILIATION_REL_TOL)
            if len(plan["campaign_name"].unique()) != 1:
                raise ValueError("budget.total_budget_rub is ambiguous for a multi-campaign input; use campaign-level budgets")
            if abs(configured_total - total_budget) > tolerance:
                raise ValueError(
                    f"Configured optimizer budget {configured_total:.2f} does not match uploaded campaign budget {total_budget:.2f}"
                )
        candidates: list[tuple[str, pd.DataFrame]] = []
        candidates.append(
            (
                f"{campaign_name}__scenario1_current_plan",
                _annotate_scenario_semantics(
                    _annotate_candidate_budget(cells, total_budget),
                    scenario_kind="uploaded_plan",
                    scenario_variant="uploaded_plan",
                    feasibility_status="feasible_full",
                ),
            )
        )
        equal = cells.copy()
        equal["budget_rub"] = total_budget / len(equal)
        candidates.append(
            (
                f"{campaign_name}__scenario2_equal_cell_split",
                _annotate_scenario_semantics(
                    _annotate_candidate_budget(equal, total_budget),
                    scenario_kind="benchmark_plan",
                    scenario_variant="equal_geo_channel_cells",
                    feasibility_status="feasible_full",
                ),
            )
        )
        candidates.append(
            (
                f"{campaign_name}__scenario3_channel_balanced",
                _annotate_scenario_semantics(
                    _annotate_candidate_budget(
                        _channel_balanced_candidate(cells, total_budget), total_budget
                    ),
                    scenario_kind="benchmark_plan",
                    scenario_variant="channel_totals_geo_equal",
                    feasibility_status="feasible_full",
                ),
            )
        )
        candidates.append(
            (
                f"{campaign_name}__scenario4_geo_balanced",
                _annotate_scenario_semantics(
                    _annotate_candidate_budget(
                        _geo_balanced_candidate(cells, total_budget), total_budget
                    ),
                    scenario_kind="benchmark_plan",
                    scenario_variant="geo_totals_channel_equal",
                    feasibility_status="feasible_full",
                ),
            )
        )
        scenario5_candidates = _generate_scenario5_candidates(
            cells,
            plan,
            engine,
            total_budget,
            decision_policy.get("scenario_5") or {},
            constraints_cfg,
        )
        candidates.extend(
            (f"{campaign_name}__{suffix}", candidate)
            for suffix, candidate in scenario5_candidates
        )

        n_cells = len(cells)
        precheck_rejections: list[dict[str, Any]] = []
        _, _, campaign_policies = _candidate_policy_bounds(
            cells,
            plan,
            engine,
            support_limit="robust_upper",
        )
        modifiable_cells_n = sum(policy in {"optimize", "no_increase"} for policy in campaign_policies)
        scenario6_has_degrees_of_freedom = "optimize" in campaign_policies and modifiable_cells_n >= 2
        if scenario6_enabled and not scenario6_has_degrees_of_freedom:
            precheck_rejections.append(
                {
                    "campaign_name": campaign_name,
                    "candidate_name": f"{campaign_name}__scenario6_not_run_no_modifiable_cells",
                    "method": requested_method,
                    "precheck_status": "not_run_no_modifiable_cells",
                    "precheck_reason": "All turnover cells are fixed by gate policy or there is no feasible receiver/donor pair",
                    "total_budget_rub": total_budget,
                    "cells_n": n_cells,
                    "modifiable_cells_n": modifiable_cells_n,
                    "search_samples": search_samples,
                }
            )
        elif scenario6_enabled:
            # The pre-E.1A adaptive path compiled one turnover kernel per
            # campaign segment before discovering aggregate infeasibility.
            adaptive_constraint_keys = {
                "channels_allowed",
                "geos_allowed",
                "channel_min_share",
                "channel_max_share",
                "geo_min_share",
                "geo_max_share",
                "mandatory_channels",
                "mandatory_geos",
            }
            if not any(
                constraints_cfg.get(key) for key in adaptive_constraint_keys
            ):
                posterior_fit_loads_before_turnover_only_n += campaign_segments_n
            try:
                adaptive_candidates, adaptive_trace, adaptive_diagnostics = (
                    _generate_adaptive_scenario6_candidates(
                        cells,
                        plan,
                        engine,
                        campaign_name,
                        total_budget,
                        search_samples=search_samples,
                        seed=seed,
                        max_evaluations=search_candidates,
                        finalists=finalists,
                        scenario_config=scenario6_execution_policy,
                        business_constraints=constraints_cfg,
                        analog_year=analog_year,
                        analog_missing_geo_policy=analog_missing_geo_policy,
                    )
                )
                posterior_fit_loads_after_turnover_only_n += campaign_segments_n
                candidates.extend(adaptive_candidates)
                search_trace_rows.extend(adaptive_trace)
                print(
                    json.dumps(
                        {
                            "event": "optimizer_progress",
                            "phase": "adaptive_search_complete",
                            "campaign": campaign_name,
                            **adaptive_diagnostics,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            except CandidateFeasibilityError as exc:
                precheck_rejections.append(
                    {
                        "campaign_name": campaign_name,
                        "candidate_name": f"{campaign_name}__scenario6_adaptive_infeasible",
                        "method": requested_method,
                        "precheck_status": "rejected_infeasible",
                        "precheck_reason": str(exc),
                        "total_budget_rub": total_budget,
                        "cells_n": n_cells,
                        "modifiable_cells_n": modifiable_cells_n,
                        "search_samples": search_samples,
                    }
                )

        # Score all candidates for this source campaign in one posterior pass.
        # This preserves the MMM math and avoids repeatedly reopening posterior NetCDF files.
        all_search_daily: list[dict[str, Any]] = []
        cand_by_name: dict[str, pd.DataFrame] = {}
        for cand_name, cand_cells in candidates:
            cand_by_name[cand_name] = cand_cells
            all_search_daily.extend(_make_candidate_daily(cand_cells, plan, cand_name))
        print(
            json.dumps(
                {
                    "event": "optimizer_progress",
                    "phase": "search_scoring",
                    "campaign": campaign_name,
                    "candidates_to_score": len(candidates),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        search_detail, search_summary = engine.forecast_daily_rows(
            all_search_daily,
            n_samples=search_samples,
            seed=seed,
            include_carryover_days=True,
            analog_year=analog_year,
            analog_missing_geo_policy=analog_missing_geo_policy,
            independent_scenarios=True,
            targets=[str(objective_contract["target"])],
        )
        scenario_evaluations_n += len(candidates)
        posterior_fit_loads_before_turnover_only_n += campaign_segments_n
        posterior_fit_loads_after_turnover_only_n += campaign_segments_n
        scored: list[dict[str, Any]] = []
        for cand_name, cand_cells in cand_by_name.items():
            cand_summary = search_summary[search_summary["campaign_name"] == cand_name]
            score = _candidate_score(cand_summary, objective_contract)
            downside_score = _candidate_downside_score(cand_summary, objective_contract)
            support_warnings = _candidate_support_warnings(cand_summary)
            hard_support_warnings = _candidate_hard_support_warnings(search_detail, cand_name)
            elevated_support_warnings = _candidate_support_level_warnings(
                search_detail,
                cand_name,
                {SUPPORT_LEVEL_ELEVATED},
            )
            strong_support_warnings = _candidate_support_level_warnings(
                search_detail,
                cand_name,
                {SUPPORT_LEVEL_STRONG},
            )
            diagnostic_rows, caution_rows = _candidate_quality_counts(cand_summary)
            policy_violations, policy_violation_codes = _candidate_policy_violations(
                cand_cells,
                cells,
                plan,
                engine,
                constraints_cfg,
            )
            risk_policy_violations = _risk_policy_violation_count(
                diagnostic_rows,
                caution_rows,
                objective_contract,
            )
            risk_budget = _candidate_risk_budget_summary(cand_cells, plan, engine)
            concentration = _candidate_concentration(cand_cells)
            source_deviation = _candidate_source_deviation(
                cand_cells,
                cells,
                total_budget,
            )
            scored.append(
                {
                    "score": score,
                    "downside_score": downside_score,
                    "candidate_name": cand_name,
                    "cells": cand_cells,
                    "support_warnings_n": support_warnings,
                    "elevated_support_warnings_n": elevated_support_warnings,
                    "strong_support_warnings_n": strong_support_warnings,
                    "hard_support_warnings_n": hard_support_warnings,
                    "policy_violations_n": policy_violations,
                    "policy_violation_codes": policy_violation_codes,
                    "risk_policy_violations_n": risk_policy_violations,
                    "diagnostic_target_rows": diagnostic_rows,
                    "caution_target_rows": caution_rows,
                    **risk_budget,
                    "allocation_concentration_hhi": concentration,
                    "source_budget_deviation_share": source_deviation,
                }
            )

        raw_sorted = sorted(scored, key=lambda item: float(item["score"]), reverse=True)
        reliable_sorted = sorted(scored, key=_reliable_candidate_sort_key)
        raw_rank = {str(item["candidate_name"]): rank for rank, item in enumerate(raw_sorted, start=1)}
        reliable_rank = {str(item["candidate_name"]): rank for rank, item in enumerate(reliable_sorted, start=1)}

        candidate_summaries.extend(precheck_rejections)
        for item in scored:
            cand_name = str(item["candidate_name"])
            hard_safe = int(item["hard_support_warnings_n"]) == 0
            policy_safe = int(item["policy_violations_n"]) == 0
            support_safe = int(item["strong_support_warnings_n"]) == 0 and hard_safe
            budget_summary = _candidate_budget_summary(item["cells"], total_budget)
            candidate_summaries.append({
                "campaign_name": campaign_name,
                "candidate_name": cand_name,
                "method": _candidate_method(cand_name),
                "precheck_status": "scored",
                "precheck_reason": "OK",
                "search_score_turnover_p50": item["score"],
                "search_score_turnover_p10": item["downside_score"],
                "objective_primary": objective_contract["primary"],
                "objective_metric": objective_contract["metric"],
                "objective_score": item["score"],
                "objective_downside_metric": objective_contract["downside_metric"],
                "objective_downside_score": item["downside_score"],
                "model_risk_policy": objective_contract["model_risk_policy"],
                "risk_policy_violations_n": int(item["risk_policy_violations_n"]),
                "guarded_search_score_turnover_p50": item["score"] if policy_safe and support_safe and int(item["risk_policy_violations_n"]) == 0 else -np.inf,
                "support_warnings_n": int(item["support_warnings_n"]),
                "elevated_support_warnings_n": int(item["elevated_support_warnings_n"]),
                "strong_support_warnings_n": int(item["strong_support_warnings_n"]),
                "hard_support_warnings_n": int(item["hard_support_warnings_n"]),
                "policy_violations_n": int(item["policy_violations_n"]),
                "policy_violation_codes": item["policy_violation_codes"],
                "support_safe": support_safe,
                "hard_support_safe": hard_safe,
                "policy_safe": policy_safe,
                "diagnostic_target_rows": int(item["diagnostic_target_rows"]),
                "caution_target_rows": int(item["caution_target_rows"]),
                "search_rank_raw": raw_rank.get(cand_name),
                "search_rank_reliable": reliable_rank.get(cand_name),
                "is_best_raw_search": raw_rank.get(cand_name) == 1,
                "is_best_reliable_search": reliable_rank.get(cand_name) == 1,
                "total_budget_rub": total_budget,
                **budget_summary,
                "within_support_budget_rub": item["within_support_budget_rub"],
                "within_support_share": item["within_support_share"],
                "controlled_extrapolation_budget_rub": item["controlled_extrapolation_budget_rub"],
                "controlled_extrapolation_share": item["controlled_extrapolation_share"],
                "high_risk_budget_rub": item["high_risk_budget_rub"],
                "high_risk_share": item["high_risk_share"],
                "within_support_cells_n": item["within_support_cells_n"],
                "controlled_extrapolation_cells_n": item["controlled_extrapolation_cells_n"],
                "high_risk_cells_n": item["high_risk_cells_n"],
                "allocation_concentration_hhi": item["allocation_concentration_hhi"],
                "source_budget_deviation_share": item["source_budget_deviation_share"],
                "cells_n": n_cells,
                "modifiable_cells_n": modifiable_cells_n,
                "search_samples": search_samples,
            })

        deterministic = [
            item
            for item in scored
            if "__scenario5_" not in str(item["candidate_name"])
            and "__scenario6_" not in str(item["candidate_name"])
        ]
        scenario5_scored = [
            item for item in scored if "__scenario5_" in str(item["candidate_name"])
        ]
        if scenario5_scored:
            selected_scenario5 = min(
                scenario5_scored,
                key=lambda item: (
                    float(item["high_risk_budget_rub"]),
                    float(item["controlled_extrapolation_budget_rub"]),
                    float(item["allocation_concentration_hhi"]),
                    float(item["source_budget_deviation_share"]),
                    -float(item["score"]),
                    str(item["candidate_name"]),
                ),
            )
            deterministic.append(selected_scenario5)
        scenario6_raw = [item for item in raw_sorted if str(item["candidate_name"]).split("__", 1)[1].startswith("scenario6_")]
        scenario6_reliable = [item for item in reliable_sorted if str(item["candidate_name"]).split("__", 1)[1].startswith("scenario6_")]
        selected_by_name: dict[str, dict[str, Any]] = {str(item["candidate_name"]): item for item in deterministic}
        for item in scenario6_raw[: max(finalists, 1)]:
            selected_by_name[str(item["candidate_name"])] = item
        for item in scenario6_reliable[: max(finalists, 1)]:
            selected_by_name[str(item["candidate_name"])] = item
        selected = sorted(selected_by_name.values(), key=_reliable_candidate_sort_key)
        all_finalist_daily: list[dict[str, Any]] = []
        for item in selected:
            cand_name = str(item["candidate_name"])
            all_finalist_daily.extend(_make_candidate_daily(item["cells"], plan, cand_name))
        finalist_detail, finalist_summary, finalist_draws = engine.forecast_daily_rows(
            all_finalist_daily,
            n_samples=final_samples,
            seed=final_seed,
            include_carryover_days=True,
            analog_year=analog_year,
            analog_missing_geo_policy=analog_missing_geo_policy,
            independent_scenarios=True,
            return_campaign_draws=True,
            targets=[SERVING_CORE_TARGET],
        )
        scenario_evaluations_n += len(selected)
        posterior_fit_loads_before_turnover_only_n += campaign_segments_n * len(TARGETS)
        posterior_fit_loads_after_turnover_only_n += campaign_segments_n
        campaign_comparisons = _paired_candidate_comparisons(
            finalist_draws,
            source_campaign_name=campaign_name,
            reference_candidate_name=f"{campaign_name}__scenario1_current_plan",
            decision_policy=decision_policy,
        )
        if not campaign_comparisons.empty:
            paired_comparison_rows.extend(campaign_comparisons.to_dict("records"))
        print(
            json.dumps(
                {
                    "event": "optimizer_progress",
                    "phase": "finalist_scoring_complete",
                    "campaign": campaign_name,
                    "finalists_scored": len(selected),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        final_items: list[dict[str, Any]] = []
        for selected_item in selected:
            cand_name = str(selected_item["candidate_name"])
            cand_summary = finalist_summary[finalist_summary["campaign_name"] == cand_name].copy()
            cand_summary["candidate_name"] = cand_name
            if not campaign_comparisons.empty:
                cand_summary = cand_summary.merge(
                    campaign_comparisons.drop(columns=["source_campaign_name"]),
                    on=["candidate_name", "target"],
                    how="left",
                    validate="many_to_one",
                )
            diagnostic_rows, caution_rows = _candidate_quality_counts(cand_summary)
            risk_policy_violations = _risk_policy_violation_count(
                diagnostic_rows,
                caution_rows,
                objective_contract,
            )
            final_items.append(
                {
                    **selected_item,
                    "score": _candidate_score(cand_summary, objective_contract),
                    "downside_score": _candidate_downside_score(cand_summary, objective_contract),
                    "support_warnings_n": _candidate_support_warnings(cand_summary),
                    "elevated_support_warnings_n": _candidate_support_level_warnings(
                        finalist_detail,
                        cand_name,
                        {SUPPORT_LEVEL_ELEVATED},
                    ),
                    "strong_support_warnings_n": _candidate_support_level_warnings(
                        finalist_detail,
                        cand_name,
                        {SUPPORT_LEVEL_STRONG},
                    ),
                    "hard_support_warnings_n": _candidate_hard_support_warnings(finalist_detail, cand_name),
                    "diagnostic_target_rows": diagnostic_rows,
                    "caution_target_rows": caution_rows,
                    "risk_policy_violations_n": risk_policy_violations,
                }
            )
        final_raw_sorted = sorted(final_items, key=lambda item: float(item["score"]), reverse=True)
        final_reliable_sorted = sorted(final_items, key=_reliable_candidate_sort_key)
        final_raw_rank = {
            str(item["candidate_name"]): rank for rank, item in enumerate(final_raw_sorted, start=1)
        }
        final_reliable_rank = {
            str(item["candidate_name"]): rank for rank, item in enumerate(final_reliable_sorted, start=1)
        }
        final_by_name = {str(item["candidate_name"]): item for item in final_items}

        for cand_name, rank in final_reliable_rank.items():
            cand_summary = finalist_summary[finalist_summary["campaign_name"] == cand_name].copy()
            cand_summary["optimizer_rank"] = rank
            cand_summary["optimizer_raw_rank"] = final_raw_rank.get(cand_name)
            cand_summary["optimizer_reliable_rank"] = final_reliable_rank.get(cand_name)
            cand_summary["optimizer_search_raw_rank"] = raw_rank.get(cand_name)
            cand_summary["optimizer_search_reliable_rank"] = reliable_rank.get(cand_name)
            cand_summary["objective_primary"] = objective_contract["primary"]
            cand_summary["objective_metric"] = objective_contract["metric"]
            cand_summary["objective_score"] = final_by_name[cand_name]["score"]
            cand_summary["objective_downside_metric"] = objective_contract["downside_metric"]
            cand_summary["objective_downside_score"] = final_by_name[cand_name]["downside_score"]
            cand_summary["model_risk_policy"] = objective_contract["model_risk_policy"]
            cand_summary["risk_policy_violations_n"] = final_by_name[cand_name]["risk_policy_violations_n"]
            cand_summary["elevated_support_warnings_n"] = final_by_name[cand_name]["elevated_support_warnings_n"]
            cand_summary["strong_support_warnings_n"] = final_by_name[cand_name]["strong_support_warnings_n"]
            cand_summary["hard_support_warnings_n"] = final_by_name[cand_name]["hard_support_warnings_n"]
            candidate_budget = _candidate_budget_summary(cand_by_name[cand_name], total_budget)
            candidate_risk = _candidate_risk_budget_summary(
                cand_by_name[cand_name], plan, engine
            )
            for key, value in candidate_budget.items():
                cand_summary[key] = value
            for key, value in candidate_risk.items():
                cand_summary[key] = value
            cand_summary["allocation_concentration_hhi"] = _candidate_concentration(
                cand_by_name[cand_name]
            )
            cand_summary["source_budget_deviation_share"] = _candidate_source_deviation(
                cand_by_name[cand_name], cells, total_budget
            )
            cand_summary["candidate_name"] = cand_name
            cand_summary["source_campaign_name"] = campaign_name
            finalist_rows.extend(cand_summary.to_dict("records"))
            cand_cells = cand_by_name[cand_name]
            allocated_budget = float(candidate_budget["allocated_budget_rub"])
            for _, cell in cand_cells.iterrows():
                capability = engine._capability_row(str(cell["segment"]), "turnover_per_user", str(cell["channel"]))
                safe_cap = _support_cap_rub_for_cell(
                    cell,
                    plan,
                    engine,
                    limit="p95",
                )
                automatic_cap = _support_cap_rub_for_cell(
                    cell,
                    plan,
                    engine,
                    limit="p99",
                )
                robust_cap = _support_cap_rub_for_cell(
                    cell,
                    plan,
                    engine,
                    limit="robust_upper",
                )
                cell_budget = float(cell["budget_rub"])
                cell_within = min(cell_budget, safe_cap)
                cell_controlled = min(
                    max(cell_budget - safe_cap, 0.0),
                    max(robust_cap - safe_cap, 0.0),
                )
                cell_high = max(cell_budget - robust_cap, 0.0)
                allocation_rows.append({
                    "source_campaign_name": campaign_name,
                    "candidate_name": cand_name,
                    "optimizer_rank": rank,
                    "optimizer_raw_rank": final_raw_rank.get(cand_name),
                    "optimizer_reliable_rank": final_reliable_rank.get(cand_name),
                    "segment": cell["segment"],
                    "geo": cell["geo"],
                    "channel": cell["channel"],
                    "budget_rub": float(cell["budget_rub"]),
                    "budget_share": float(cell["budget_rub"] / allocated_budget) if allocated_budget > 0 else 0.0,
                    "share_of_uploaded_budget": float(cell["budget_rub"] / total_budget) if total_budget > 0 else 0.0,
                    **candidate_budget,
                    **candidate_risk,
                    "cell_within_support_budget_rub": cell_within,
                    "cell_controlled_extrapolation_budget_rub": cell_controlled,
                    "cell_high_risk_budget_rub": cell_high,
                    "optimizer_policy": capability.get("optimizer_use", "blocked"),
                    "allowed_use": capability.get("allowed_use", "unavailable"),
                    "gate_reason_codes": capability.get("gate_reason_codes", "MISSING_GATE_POLICY"),
                    "safe_support_cap_rub": safe_cap,
                    "automatic_support_cap_rub": automatic_cap,
                    "robust_support_cap_rub": robust_cap,
                })

    candidate_df = pd.DataFrame(candidate_summaries)
    finalist_df = pd.DataFrame(finalist_rows)
    allocation_df = pd.DataFrame(allocation_rows)
    paired_comparison_df = pd.DataFrame(paired_comparison_rows)
    search_trace_df = pd.DataFrame(
        search_trace_rows,
        columns=[
            "campaign_name",
            "support_limit",
            "origin",
            "attempts_cumulative_n",
            "step_rub",
            "donor_pos",
            "receiver_pos",
            "transfer_rub",
            "score_before",
            "score_after",
            "accepted",
            "statistic",
            "donor_geo",
            "donor_channel",
            "receiver_geo",
            "receiver_channel",
        ],
    )
    candidate_path = output_dir / f"{_safe_id(run_id)}_optimizer_candidate_scores.csv"
    finalist_path = output_dir / f"{_safe_id(run_id)}_optimizer_finalist_summary.csv"
    alloc_path = output_dir / f"{_safe_id(run_id)}_optimizer_recommended_allocations.csv"
    paired_path = output_dir / f"{_safe_id(run_id)}_optimizer_paired_comparisons.csv"
    trace_path = output_dir / f"{_safe_id(run_id)}_optimizer_search_trace.csv"
    xlsx_path = output_dir / f"{_safe_id(run_id)}_budget_optimization_report.xlsx"
    candidate_df.to_csv(candidate_path, index=False)
    finalist_df.to_csv(finalist_path, index=False)
    allocation_df.to_csv(alloc_path, index=False)
    paired_comparison_df.to_csv(paired_path, index=False)
    search_trace_df.to_csv(trace_path, index=False)
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        pd.DataFrame([
            {"sheet": "01_Finalists", "description": "Top candidate allocations rescored with posterior forecast engine."},
            {"sheet": "02_Allocations", "description": "Budget by geo x channel for top candidates."},
            {"sheet": "03_Search", "description": "All searched candidates and search-time score."},
        ]).to_excel(writer, sheet_name="00_ReadMe", index=False)
        finalist_df.to_excel(writer, sheet_name="01_Finalists", index=False)
        allocation_df.to_excel(writer, sheet_name="02_Allocations", index=False)
        candidate_df.to_excel(writer, sheet_name="03_Search", index=False)
        paired_comparison_df.to_excel(writer, sheet_name="04_Paired_Comparisons", index=False)
    finished_at = datetime.now(timezone.utc)
    card = {
        "run_id": run_id,
        "model_run_dir": str(resolve_path(model_run_dir)),
        "flighting_path": str(resolve_path(flighting_path)),
        "flighting_sha256": sha256_file(resolve_path(flighting_path)),
        "model_manifest_sha256": sha256_file(resolve_path(model_run_dir) / "model_manifest.json"),
        "workflow_config_sha256": _json_sha256(workflow_config),
        "search_candidates_per_campaign": search_candidates,
        "search_samples": search_samples,
        "final_samples": final_samples,
        "finalists": finalists,
        "seed": seed,
        "search_seed": seed,
        "final_seed": final_seed,
        "started_at_utc": started_at.isoformat(),
        "finished_at_utc": finished_at.isoformat(),
        "duration_seconds": round(time.monotonic() - started_perf, 3),
        "scenario6_enabled": scenario6_enabled,
        "scenario6_method": requested_method,
        "scenario6_config": scenario6_execution_policy,
        "scenario6_search_trace_rows_n": int(len(search_trace_df)),
        "serving_policy_version": SERVING_POLICY_VERSION,
        "research_models_in_package_n": int(
            model_inventory["research_models_in_package_n"]
        ),
        "active_serving_models_n": int(model_inventory["active_serving_models_n"]),
        "serving_targets": [SERVING_CORE_TARGET],
        "scenario_evaluations_n": int(scenario_evaluations_n),
        "posterior_fit_loads_before_turnover_only_n": int(
            posterior_fit_loads_before_turnover_only_n
        ),
        "posterior_fit_loads_after_turnover_only_n": int(
            posterior_fit_loads_after_turnover_only_n
        ),
        "objective": objective_cfg,
        "compiled_objective": objective_contract,
        "decision_policy": decision_policy,
        "decision_policy_sha256": workflow_config.get("decision_policy_sha256"),
        "business_guardrails": guardrail_cfg,
        "future_controls": workflow_config.get("future_controls") or {},
        "denominator_analog_year": analog_year if analog_year is not None else "previous_year",
        "denominator_missing_geo_policy": analog_missing_geo_policy,
        "model_activation_status": engine.package.activation_status,
        "model_production_blockers": list(engine.package.manifest.get("production_blockers") or []),
        "runtime_lineage": _runtime_lineage(model_run_dir, purpose="optimizer"),
        "outputs": {
            "candidate_scores_csv": str(candidate_path),
            "finalist_summary_csv": str(finalist_path),
            "recommended_allocations_csv": str(alloc_path),
            "paired_comparisons_csv": str(paired_path),
            "search_trace_csv": str(trace_path),
            "xlsx": str(xlsx_path),
        },
        "output_sha256": {
            "candidate_scores_csv": sha256_file(candidate_path),
            "finalist_summary_csv": sha256_file(finalist_path),
            "recommended_allocations_csv": sha256_file(alloc_path),
            "paired_comparisons_csv": sha256_file(paired_path),
            "search_trace_csv": sha256_file(trace_path),
            "xlsx": sha256_file(xlsx_path),
        },
    }
    write_json(output_dir / f"{_safe_id(run_id)}_optimizer_run_card.json", card)
    return card
