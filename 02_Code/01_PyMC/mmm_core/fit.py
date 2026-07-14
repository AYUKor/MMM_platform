"""PyMC fit math extracted from the accepted Q1-2026 production notebook.

Do not edit formulas without updating deterministic parity fixtures.
"""

from __future__ import annotations

import json
import hashlib
import importlib.metadata
import logging
import os
import platform
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import arviz as az
import numpy as np
import pandas as pd
import pymc as pm
import pytensor.tensor as pt
from linearmodels.panel import PanelOLS

from .io import load_config, project_root, resolve_path, write_json
from .model_package import sha256_file

log = logging.getLogger("mmm_fit")

FIT_CONTRACT_SCHEMA_VERSION = "1.0.0"
FIT_RUNTIME_VERSION = "1.1.0"
CONTRACTION_SCHEMA_VERSION = "2.0.0"
RANDOM_SEED = 42
EXPECTED_TARGETS = ["turnover_per_user", "orders_per_user", "avg_basket"]
EXPECTED_SEGMENTS = ["ТС5/Онлайн", "ТС5/Оффлайн", "ТСХ/Онлайн", "ТСХ/Оффлайн"]
EXPECTED_FIT_KEYS = [f"{segment}::{target}" for segment in EXPECTED_SEGMENTS for target in EXPECTED_TARGETS]

MODE_PROFILES = {
    "fast": {
        "top_n_geos": 20,
        "draws": 300,
        "tune": 300,
        "chains": 2,
        "fourier_pairs": 1,
        "decay_grid_step": 0.15,
        "target_accept": 0.90,
        "use_jax": True,
        "l_max": 14,
    },
    "medium": {
        "top_n_geos": 20,
        "draws": 1000,
        "tune": 1000,
        "chains": 4,
        "fourier_pairs": 2,
        "decay_grid_step": 0.10,
        "target_accept": 0.99,
        "use_jax": True,
        "l_max": 14,
    },
    "pilot": {
        "top_n_geos": None,
        "draws": 1000,
        "tune": 1000,
        "chains": 2,
        "fourier_pairs": 2,
        "decay_grid_step": 0.10,
        "target_accept": 0.99,
        "use_jax": True,
        "l_max": 14,
    },
    "production": {
        "top_n_geos": None,
        "draws": 2000,
        "tune": 2000,
        "chains": 4,
        "fourier_pairs": 2,
        "decay_grid_step": 0.05,
        "target_accept": 0.99,
        "use_jax": True,
        "l_max": 14,
    },
}

DIGITAL_RAW_SPEND_INPUTS = [
    "spend_Programmatic",
    "spend_Paid_Search",
    "spend_Paid_Social",
    "spend_Marketplace_Ads",
    "spend_Telecom_Ads",
    "spend_App_Ads",
    "spend_Video_Ads",
    "spend_Premium_Publishers",
    "spend_Other_Digital",
]
OOH_TOTAL_INPUTS = ["spend_OOH", "spend_ООН_РТБ"]
DEFAULT_MEDIA_GROUPING_CONFIG = {
    segment: {
        "spend_Digital_Performance": DIGITAL_RAW_SPEND_INPUTS,
        "spend_OOH_Total": OOH_TOTAL_INPUTS,
    }
    for segment in EXPECTED_SEGMENTS
}
DERIVED_MEDIA_GROUP_COLS = sorted(
    {group for groups in DEFAULT_MEDIA_GROUPING_CONFIG.values() for group in groups}
)
BASE_CONTROL_COLS = [
    "compet_spend_NacTV",
    "compet_spend_RegTV",
    "compet_spend_OOH",
    "usd_rub_log_return",
    "brent_log_return",
    "ruonia_change",
    "temp_dev_from_norm_c",
    "is_heatwave_d",
    "is_coldwave_d",
    "is_heavy_rain_d",
    "is_snowy_d",
    "is_official_holiday",
    "is_pre_holiday",
    "is_salary_period",
    "sin_7",
    "cos_7",
    "sin_365",
    "cos_365",
    "anomaly_period_jul2025",
]

ALLOWED_BETA_STRUCTURES = {"pooled", "hierarchical_geo", "hierarchical_tier"}
BETA_STRUCTURE_BY_TARGET = {
    "orders_per_user": "pooled",
    "turnover_per_user": "hierarchical_tier",
    "avg_basket": "hierarchical_tier",
}
BETA_STRUCTURE_OVERRIDES_BY_FIT = {
    ("ТС5", "Онлайн", "avg_basket"): "pooled",
    ("ТС5", "Оффлайн", "avg_basket"): "hierarchical_geo",
}
BETA_TIER_POOLED_CHANNELS_BY_FIT = {
    ("ТС5", "Оффлайн", "turnover_per_user"): {"Нац_ТВ"},
}

MEDIA_SCALING_MODE = "tier_p95_shrunk"
MEDIA_GEO_SCALE_MIN_NZ = 8
MEDIA_GEO_SCALE_FULL_NZ = 30
MEDIA_GEO_SCALE_RATIO_FLOOR = 0.25
MEDIA_GEO_SCALE_RATIO_CEIL = 4.0
MEDIA_TIER_COUNT = 3
MEDIA_TIER_SCALE_MIN_NZ = 20
MEDIA_TIER_SCALE_FULL_NZ = 120
MEDIA_TIER_SCALE_RATIO_FLOOR = 0.50
MEDIA_TIER_SCALE_RATIO_CEIL = 2.0
MARKET_SIZE_TIER_COL = "market_size_tier"
MARKET_SIZE_TIER_FALLBACK = "population_k_qcut"
BASELINE_STRUCTURE = "geo"
ERROR_STRUCTURE = "global"
MEDIA_RESPONSE_MODE = "tight"
CENTER_MEDIA_RESPONSE = False
TC5_OFFLINE_SPECIFIC_POLICY_ENABLED = True
TC5_OFFLINE_POLICY_SEGMENT = ("ТС5", "Оффлайн")
TC5_OFFLINE_POLICY_TARGETS = {"turnover_per_user", "avg_basket"}
TC5_OFFLINE_EXCLUDED_MEDIA_COLS = {"spend_Digital_Performance"}
INDOOR_MEDIA_COL = "spend_Indoor"
INDOOR_REPORTING_MODE = "diagnostic_only_in_fast_until_medium_validated"
MODE = "production"

SPEND_ACTIVE_BASE: list[str] = []
MEDIA_GROUPING_CONFIG = DEFAULT_MEDIA_GROUPING_CONFIG
MEDIA_GROUPING_ENABLED = True
MEDIA_GROUP_INPUTS_BY_SEGMENT: dict[str, set[str]] = {}
panel = pd.DataFrame()


@dataclass(frozen=True)
class GuardedFitSpec:
    config_path: Path
    panel_path: Path
    run_dir: Path
    mode: str
    train_start: str
    train_end: str
    holdout_start: str
    holdout_end: str
    profile: dict[str, Any]
    require_numpyro: bool
    random_seed: int
    thin_sample_threshold: int
    vif_threshold: float
    fixed_lambda_channels_by_fit: dict[str, tuple[str, ...]] = field(default_factory=dict)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json_sha256(value: Any) -> str:
    return _sha256_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8"))


def _array_sha256(value: Any) -> str | None:
    if value is None:
        return None
    arr = np.ascontiguousarray(np.asarray(value))
    header = json.dumps({"dtype": str(arr.dtype), "shape": list(arr.shape)}, sort_keys=True).encode("utf-8")
    return _sha256_bytes(header + arr.tobytes())


def _validate_csv_roundtrip(path: Path, expected: pd.DataFrame, artifact_name: str) -> None:
    """Validate immutable CSV metadata without treating parser-level float noise as tampering."""
    existing = pd.read_csv(path, float_precision="round_trip")
    try:
        pd.testing.assert_frame_equal(
            existing,
            expected,
            check_dtype=False,
            check_exact=False,
            rtol=1e-12,
            atol=1e-12,
        )
    except AssertionError as exc:
        raise ValueError(f"{artifact_name} changed inside an immutable run") from exc


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def get_spend_cols_for_segment(
    network: str,
    channel: str,
    spend_cols: Iterable[str] | None = None,
) -> list[str]:
    """Apply the accepted segment-level grouping without double-counting inputs."""
    base_cols = list(SPEND_ACTIVE_BASE if spend_cols is None else spend_cols)
    segment = f"{network}/{channel}"
    if not MEDIA_GROUPING_ENABLED or segment not in MEDIA_GROUPING_CONFIG:
        return [column for column in base_cols if column in panel.columns and column not in DERIVED_MEDIA_GROUP_COLS]
    grouped_inputs = MEDIA_GROUP_INPUTS_BY_SEGMENT.get(segment, set())
    group_cols = [column for column in MEDIA_GROUPING_CONFIG[segment] if column in panel.columns]
    keep_raw = [
        column
        for column in base_cols
        if column not in grouped_inputs and column not in DERIVED_MEDIA_GROUP_COLS
    ]
    return list(dict.fromkeys(keep_raw + group_cols))

def get_beta_structure_for_fit(network, channel, target):
    """Resolve beta structure with fit-level overrides above target defaults."""
    beta_structure = BETA_STRUCTURE_OVERRIDES_BY_FIT.get(
        (network, channel, target),
        BETA_STRUCTURE_BY_TARGET.get(target, "hierarchical_geo"),
    )
    if beta_structure not in ALLOWED_BETA_STRUCTURES:
        raise ValueError(f"Unknown beta_structure for {network}/{channel}::{target}: {beta_structure}")
    return beta_structure

def get_beta_tier_pooled_channels_for_fit(network, channel, target):
    """Channels that should be pooled inside a hierarchical_tier beta fit."""
    return set(BETA_TIER_POOLED_CHANNELS_BY_FIT.get((network, channel, target), set()))

def compute_vif_for_cols(df, cols):
    '''Возвращает [(col, vif)] для каждой колонки в cols.'''
    from statsmodels.stats.outliers_influence import variance_inflation_factor
    sub = df[cols].dropna()
    if len(sub) < len(cols) + 10:
        return [(c, np.nan) for c in cols]
    Xc = sub.copy()
    Xc["__c__"] = 1.0
    out = []
    for i, c in enumerate(cols):
        try:
            v = float(variance_inflation_factor(Xc.values, i))
        except Exception:
            v = np.nan
        out.append((c, v))
    return out

def geometric_adstock(x, decay):
    out = np.zeros_like(x, dtype=float)
    out[0] = x[0]
    for t in range(1, len(x)):
        out[t] = x[t] + decay * out[t-1]
    return out

def adstock_panel_inplace(df_seg, spend_col, decay):
    df_seg = df_seg.sort_values(["geo_label","date"]).copy()
    df_seg[spend_col + "_ads"] = (df_seg.groupby("geo_label")[spend_col]
                                   .transform(lambda s: geometric_adstock(s.values, decay)))
    return df_seg

def grid_search_adstock_fe(panel_seg, target, spend_col, ctrl_cols, decay_grid, min_obs=200):
    best = {"ssr": np.inf, "decay": 0.3, "beta": 0.0, "se": np.nan}
    for decay in decay_grid:
        df_a = adstock_panel_inplace(panel_seg, spend_col, decay)
        x_cols = [spend_col + "_ads"] + [c for c in ctrl_cols if c in df_a.columns and df_a[c].std() > 0]
        sub = df_a[[target, "geo_label", "date"] + x_cols].dropna()
        if len(sub) < min_obs:
            continue
        sub = sub.set_index(["geo_label", "date"])
        try:
            mod = PanelOLS(sub[target], sub[x_cols], entity_effects=True).fit()
            ssr = float((mod.resids ** 2).sum())
            if ssr < best["ssr"]:
                best["ssr"] = ssr
                best["decay"] = float(decay)
                ads_col = spend_col + "_ads"
                if ads_col in mod.params.index:
                    best["beta"] = float(mod.params[ads_col])
                    best["se"]   = float(mod.std_errors[ads_col])
        except Exception:
            continue
    return best["decay"], best["beta"], best["se"]

def make_geo_lagged_tensor(X, geo_idx, l_max):
    """Build lag tensor with adstock reset at geo boundaries.

    Shape: (lag, obs, channel). Rows are sorted by geo/date, but every geo gets
    its own lag history. This prevents the last day of one region from leaking
    into the first day of the next region.
    """
    X = np.asarray(X, dtype=float)
    geo_idx = np.asarray(geo_idx)
    n_obs, n_media = X.shape
    x_lagged = np.zeros((l_max + 1, n_obs, n_media), dtype=float)
    for g in np.unique(geo_idx):
        ix = np.where(geo_idx == g)[0]
        xg = X[ix, :]
        for lag in range(l_max + 1):
            if lag == 0:
                x_lagged[lag, ix, :] = xg
            else:
                x_lagged[lag, ix[lag:], :] = xg[:-lag, :]
    return x_lagged

def _float_or_nan(value):
    """Convert optional numeric metadata to float; keep bad FE audit values as NaN."""
    try:
        if value is None:
            return np.nan
        out = float(value)
        return out if np.isfinite(out) else np.nan
    except Exception:
        return np.nan

def beta_prior_from_empirical(seg_priors, spend_col, fallback_median, fallback_scale,
                              seg_df, x_scale_m, lam_prior_mean_m, y_scale,
                              population_col="population_k", x_scaled_typical_m=None):
    """Build a beta prior from FE when it is usable; otherwise keep benchmark fallback.

    FE grid search estimates beta in raw units:
        Y_raw ~ beta_FE * adstock(spend_raw_rub) + controls + geo FE

    PyMC beta multiplies saturated, scaled per-capita spend and scaled Y:
        Y_scaled ~ beta_PyMC * tanh(lambda * adstock(spend_pc / x_scale) / 2)

    To move FE information into the PyMC scale, match both contributions at a
    typical active spend point:
        beta_PyMC = beta_FE * spend_raw_typical / (y_scale * tanh_response_typical)

    This is an order-of-magnitude prior, not a post-fit estimate. The source and
    all audit fields are saved so every channel is traceable in the reports.
    """
    rec = (seg_priors or {}).get(spend_col, {})
    fe_beta = _float_or_nan(rec.get("beta_FE"))
    fe_se = _float_or_nan(rec.get("beta_SE"))

    audit = {
        "fe_beta_raw": fe_beta,
        "fe_se_raw": fe_se,
        "fallback_median": float(fallback_median),
        "fallback_scale": float(fallback_scale),
    }

    def fallback(source):
        fallback_log_sd = np.clip(
            float(fallback_scale) / max(float(fallback_median), 1e-4),
            0.3,
            2.0,
        )
        return {
            "median": float(fallback_median),
            "scale": float(fallback_log_sd),
            "source": source,
            **audit,
            "spend_raw_typical": np.nan,
            "pop_typical": np.nan,
            "tanh_response_typ": np.nan,
            "beta_pymc_implied": np.nan,
            "beta_pymc_sd": np.nan,
            "lam_prior_used": float(lam_prior_mean_m) if np.isfinite(lam_prior_mean_m) else np.nan,
            "x_scale_typical": float(x_scale_m) if np.isfinite(x_scale_m) else np.nan,
            "spend_scaled_typical": np.nan,
        }

    fe_usable = (
        np.isfinite(fe_beta)
        and np.isfinite(fe_se)
        and fe_beta > 0
        and fe_se > 0
        and abs(fe_beta) > 2.0 * fe_se
        and fe_se / max(abs(fe_beta), 1e-12) < 1.0
    )
    if not fe_usable:
        return fallback("fallback_benchmark__fe_not_usable")

    if seg_df is None or spend_col not in seg_df.columns or population_col not in seg_df.columns:
        return fallback("fallback_benchmark__no_seg_df")

    s = seg_df[spend_col].astype(float).values
    pop = seg_df[population_col].astype(float).values
    nz = (s > 0) & (pop > 0) & np.isfinite(s) & np.isfinite(pop)
    if nz.sum() < 20:
        return fallback("fallback_benchmark__sparse_channel")

    spend_raw_typical = float(np.median(s[nz]))
    pop_typical = float(np.median(pop[nz]))
    spend_pc_typical = spend_raw_typical / max(pop_typical, 1e-3)
    if x_scaled_typical_m is None or not np.isfinite(x_scaled_typical_m) or x_scaled_typical_m <= 0:
        spend_scaled_typical = spend_pc_typical / max(float(x_scale_m), 1e-12)
    else:
        spend_scaled_typical = float(x_scaled_typical_m)
    adstock_scaled_typical = spend_scaled_typical
    tanh_response_typ = float(np.tanh(float(lam_prior_mean_m) * adstock_scaled_typical / 2.0))

    if tanh_response_typ < 1e-6 or y_scale < 1e-12:
        return fallback("fallback_benchmark__tanh_response_degenerate")

    beta_pymc = fe_beta * spend_raw_typical / (float(y_scale) * tanh_response_typ)
    if not np.isfinite(beta_pymc) or not (1e-4 <= beta_pymc <= 5.0):
        return fallback(f"fallback_benchmark__beta_pymc_out_of_range_{beta_pymc:.3g}")

    rel_err = fe_se / fe_beta
    beta_pymc_sd = beta_pymc * max(rel_err, 0.20)
    sigma_log = np.sqrt(np.log(1.0 + (beta_pymc_sd / beta_pymc) ** 2))

    return {
        "median": float(beta_pymc),
        "scale": float(np.clip(sigma_log, 0.3, 2.0)),
        "source": "empirical_fe_rescaled",
        **audit,
        "spend_raw_typical": spend_raw_typical,
        "pop_typical": pop_typical,
        "tanh_response_typ": tanh_response_typ,
        "beta_pymc_implied": float(beta_pymc),
        "beta_pymc_sd": float(beta_pymc_sd),
        "lam_prior_used": float(lam_prior_mean_m),
        "x_scale_typical": float(x_scale_m),
        "spend_scaled_typical": float(spend_scaled_typical),
    }

def _positive_p95(values, default=1.0):
    vals = np.asarray(values, dtype=float)
    vals = vals[np.isfinite(vals) & (vals > 0)]
    if len(vals) >= 20:
        return float(np.percentile(vals, 95))
    if len(vals) > 0:
        return float(np.max(vals))
    return float(default)

def _make_market_size_tiers(geo_size_values, n_tiers=3):
    """Fallback tier assignment when panel has no stable market_size_tier."""
    values = np.asarray(geo_size_values, dtype=float)
    if np.isfinite(values).any():
        values = np.where(np.isfinite(values), values, np.nanmedian(values[np.isfinite(values)]))
    else:
        values = np.arange(len(values), dtype=float)
    n_geo = len(values)
    n_tiers = int(max(1, min(n_tiers, n_geo)))
    if n_tiers == 1:
        return np.zeros(n_geo, dtype=int), ["all"], "fallback_single_tier"
    ranks = pd.Series(values).rank(method="first")
    tier_idx = pd.qcut(ranks, q=n_tiers, labels=False, duplicates="drop").astype(int).to_numpy()
    n_actual = int(tier_idx.max()) + 1 if len(tier_idx) else 1
    default_names = ["small", "medium", "large"] if n_actual == 3 else [f"tier_{i}" for i in range(n_actual)]
    return tier_idx, default_names, globals().get("MARKET_SIZE_TIER_FALLBACK", "population_k_qcut")

def _mode_or_first(values):
    vals = pd.Series(values).dropna().astype(str)
    if vals.empty:
        return np.nan
    mode = vals.mode()
    return mode.iloc[0] if not mode.empty else vals.iloc[0]

def extract_market_size_tiers(seg, geos, geo_idx):
    """Return stable geo/obs tier ids for the current fit.

    Preferred source is panel_final.market_size_tier. Fallback uses population_k
    quantiles only for backward compatibility with old panel_final artifacts.
    """
    tier_col = globals().get("MARKET_SIZE_TIER_COL", "market_size_tier")
    preferred_order = ["small", "medium", "large"]
    if tier_col in seg.columns and seg[tier_col].notna().any():
        geo_tier = seg.groupby("geo_label")[tier_col].agg(_mode_or_first).reindex(geos)
        present = [str(x) for x in geo_tier.dropna().unique()]
        tier_names = [x for x in preferred_order if x in present]
        tier_names += sorted([x for x in present if x not in tier_names])
        if not tier_names:
            tier_names = ["all"]
        fallback_name = tier_names[0]
        geo_tier = geo_tier.fillna(fallback_name).astype(str)
        tier_map = {name: i for i, name in enumerate(tier_names)}
        geo_tier_idx = geo_tier.map(tier_map).astype(int).to_numpy()
        return geo_tier_idx, geo_tier_idx[geo_idx], tier_names, f"panel_column:{tier_col}"

    geo_size_values = (
        pd.Series(np.maximum(seg["population_k"].values.astype(float), 1e-3))
        .groupby(geo_idx).median().reindex(range(len(geos))).values
    )
    geo_tier_idx, tier_names, source = _make_market_size_tiers(
        geo_size_values,
        n_tiers=int(globals().get("MEDIA_TIER_COUNT", 3)),
    )
    return geo_tier_idx, geo_tier_idx[geo_idx], tier_names, source

def compute_media_scaling(X_spend_pc, geo_idx, clean_mask, geos, spend_active,
                          geo_size_values=None, market_tier_idx=None, tier_names=None):
    """Scale per-capita media spend for PyMC.

    `global_p95` is the previous fixed behavior: one robust p95 per channel.
    `geo_p95_shrunk` gives every geo its own channel scale.
    `tier_p95_shrunk` shares scale inside stable market-size tiers. This prevents
    Moscow-like geos from setting the scale for everyone, but avoids adding a
    separate noisy media scale to every single geo.
    """
    mode = globals().get("MEDIA_SCALING_MODE", "global_p95")
    geo_min_nz = int(globals().get("MEDIA_GEO_SCALE_MIN_NZ", 8))
    geo_full_nz = max(int(globals().get("MEDIA_GEO_SCALE_FULL_NZ", 30)), geo_min_nz)
    geo_ratio_floor = float(globals().get("MEDIA_GEO_SCALE_RATIO_FLOOR", 0.25))
    geo_ratio_ceil = float(globals().get("MEDIA_GEO_SCALE_RATIO_CEIL", 4.0))
    tier_count = int(globals().get("MEDIA_TIER_COUNT", 3))
    tier_min_nz = int(globals().get("MEDIA_TIER_SCALE_MIN_NZ", 20))
    tier_full_nz = max(int(globals().get("MEDIA_TIER_SCALE_FULL_NZ", 120)), tier_min_nz)
    tier_ratio_floor = float(globals().get("MEDIA_TIER_SCALE_RATIO_FLOOR", 0.50))
    tier_ratio_ceil = float(globals().get("MEDIA_TIER_SCALE_RATIO_CEIL", 2.0))

    X_spend_pc = np.asarray(X_spend_pc, dtype=float)
    geo_idx = np.asarray(geo_idx, dtype=int)
    clean_mask = np.asarray(clean_mask, dtype=bool)
    n_obs, n_media = X_spend_pc.shape
    n_geo = len(geos)

    if market_tier_idx is None:
        if geo_size_values is None:
            geo_size_values = np.arange(n_geo, dtype=float)
        market_tier_idx, fallback_names, _ = _make_market_size_tiers(geo_size_values, n_tiers=tier_count)
        tier_names = tier_names or fallback_names
    market_tier_idx = np.asarray(market_tier_idx, dtype=int)
    if tier_names is None:
        n_tiers_tmp = int(market_tier_idx.max()) + 1 if len(market_tier_idx) else 1
        tier_names = [f"tier_{i}" for i in range(n_tiers_tmp)]
    tier_names = list(tier_names)
    n_tiers = len(tier_names)

    x_scale_global = np.zeros(n_media, dtype=float)
    x_scale_geo = np.zeros((n_geo, n_media), dtype=float)
    x_scale_tier = np.zeros((n_tiers, n_media), dtype=float)
    geo_nz = np.zeros((n_geo, n_media), dtype=int)
    tier_nz = np.zeros((n_tiers, n_media), dtype=int)

    for m in range(n_media):
        clean_col = X_spend_pc[clean_mask, m]
        global_scale = max(_positive_p95(clean_col, default=1.0), 1e-8)
        x_scale_global[m] = global_scale

        if mode == "tier_p95_shrunk":
            for t in range(n_tiers):
                tier_geo_codes = np.where(market_tier_idx == t)[0]
                tier_mask = np.isin(geo_idx, tier_geo_codes) & clean_mask
                vals = X_spend_pc[tier_mask, m]
                nz = vals[np.isfinite(vals) & (vals > 0)]
                tier_nz[t, m] = len(nz)
                raw_tier = _positive_p95(nz, default=global_scale) if len(nz) >= tier_min_nz else global_scale
                w = min(max(len(nz), 0) / tier_full_nz, 1.0)
                tier_scale = float(np.exp((1.0 - w) * np.log(global_scale) + w * np.log(max(raw_tier, 1e-8))))
                tier_scale = float(np.clip(tier_scale, global_scale * tier_ratio_floor, global_scale * tier_ratio_ceil))
                x_scale_tier[t, m] = max(tier_scale, 1e-8)
            x_scale_geo[:, m] = x_scale_tier[market_tier_idx, m]
            continue

        for g in range(n_geo):
            mask = (geo_idx == g) & clean_mask
            vals = X_spend_pc[mask, m]
            nz = vals[np.isfinite(vals) & (vals > 0)]
            geo_nz[g, m] = len(nz)
            if mode == "global_p95":
                local_scale = global_scale
            else:
                raw_local = _positive_p95(nz, default=global_scale) if len(nz) >= geo_min_nz else global_scale
                if mode == "geo_p95_shrunk":
                    w = min(max(len(nz), 0) / geo_full_nz, 1.0)
                    local_scale = float(np.exp((1.0 - w) * np.log(global_scale) + w * np.log(max(raw_local, 1e-8))))
                elif mode == "geo_p95":
                    local_scale = raw_local
                else:
                    raise ValueError(f"Unknown MEDIA_SCALING_MODE: {mode}")
                local_scale = float(np.clip(local_scale, global_scale * geo_ratio_floor, global_scale * geo_ratio_ceil))
            x_scale_geo[g, m] = max(local_scale, 1e-8)
        x_scale_tier[:, m] = global_scale

    if mode == "global_p95":
        x_scale_obs = np.broadcast_to(x_scale_global[None, :], (n_obs, n_media)).copy()
    else:
        x_scale_obs = x_scale_geo[geo_idx, :]

    X_spend_scaled = X_spend_pc / np.maximum(x_scale_obs, 1e-8)
    x_scale_typical = np.zeros(n_media, dtype=float)
    x_scaled_typical = np.zeros(n_media, dtype=float)
    audit_rows = []
    for m, sc in enumerate(spend_active):
        active = clean_mask & np.isfinite(X_spend_pc[:, m]) & (X_spend_pc[:, m] > 0)
        if active.any():
            x_scale_typical[m] = float(np.median(x_scale_obs[active, m]))
            x_scaled_typical[m] = float(np.median(X_spend_scaled[active, m]))
        else:
            x_scale_typical[m] = float(x_scale_global[m])
            x_scaled_typical[m] = 0.0
        ratios = x_scale_geo[:, m] / max(x_scale_global[m], 1e-8)
        row = {
            "spend_col": sc,
            "channel": sc.replace("spend_", ""),
            "media_scaling_mode": mode,
            "global_p95_scale": float(x_scale_global[m]),
            "typical_scale_active_rows": float(x_scale_typical[m]),
            "typical_scaled_spend_active_rows": float(x_scaled_typical[m]),
            "geo_scale_ratio_min": float(np.min(ratios)),
            "geo_scale_ratio_p25": float(np.percentile(ratios, 25)),
            "geo_scale_ratio_median": float(np.median(ratios)),
            "geo_scale_ratio_p75": float(np.percentile(ratios, 75)),
            "geo_scale_ratio_max": float(np.max(ratios)),
            "geos_with_active_spend": int(sum(np.any((geo_idx == g) & clean_mask & np.isfinite(X_spend_pc[:, m]) & (X_spend_pc[:, m] > 0)) for g in range(n_geo))),
            "geos_using_global_or_sparse_scale": int((geo_nz[:, m] < geo_min_nz).sum()) if mode.startswith("geo_") else np.nan,
            "active_obs": int(active.sum()),
        }
        if mode == "tier_p95_shrunk":
            for t, name in enumerate(tier_names):
                row[f"tier_{name}_geo_count"] = int((market_tier_idx == t).sum())
                row[f"tier_{name}_scale_ratio"] = float(x_scale_tier[t, m] / max(x_scale_global[m], 1e-8))
                row[f"tier_{name}_active_obs"] = int(tier_nz[t, m])
        audit_rows.append(row)
    return X_spend_scaled, x_scale_typical, x_scale_global, x_scaled_typical, pd.DataFrame(audit_rows)

def _channel_family(spend_col, offline_prior_cols):
    """Coarse family used only to borrow fallback beta scale in PyMC units."""
    if spend_col in offline_prior_cols:
        return "offline"
    digital_markers = (
        "Digital", "Programmatic", "Paid_", "Marketplace", "Telecom",
        "App_", "Video", "Premium", "Other_Digital",
    )
    if any(marker in spend_col for marker in digital_markers):
        return "digital"
    return "other"

def _fallback_log_sd_from_values(values, min_log_sd=1.0, max_log_sd=2.0):
    """Wide lognormal fallback width from successful empirical priors."""
    vals = np.asarray([v for v in values if np.isfinite(v) and v > 0], dtype=float)
    if len(vals) >= 2:
        spread = float(np.std(np.log(vals)))
    else:
        spread = min_log_sd
    return float(np.clip(max(spread, min_log_sd), 0.3, max_log_sd))

def _scaled_fallback_prior(target, channel_family, candidate_infos, failure_source):
    """Fallback beta prior in the same PyMC scale as empirical FE priors.

    Priority:
      1. orders_per_user gets a weak near-zero media prior when FE is not usable;
      2. same target + same channel family successful FE-rescaled priors;
      3. same target successful FE-rescaled priors across families;
      4. global weak prior in PyMC units.

    This prevents mixing tiny FE-rescaled beta values with old benchmark beta
    constants such as 0.15-0.30 that lived in a different interpretation.
    """
    if target == "orders_per_user":
        return {
            "median": 0.01,
            "scale": 1.50,
            "source": "fallback_near_zero_orders_per_user",
            "fallback_reason": failure_source,
            "fallback_pool_n": 0,
            "fallback_pool_median": np.nan,
        }

    successes = [
        info for info in candidate_infos
        if info.get("source") == "empirical_fe_rescaled"
        and np.isfinite(info.get("median", np.nan))
        and info.get("median", 0) > 0
    ]
    same_family_vals = [
        info["median"] for info in successes
        if info.get("channel_family") == channel_family
    ]
    target_vals = [info["median"] for info in successes]

    if same_family_vals:
        vals = same_family_vals
        source = "fallback_empirical_family_scale"
    elif target_vals:
        vals = target_vals
        source = "fallback_empirical_target_scale"
    else:
        vals = []
        source = "fallback_global_weak"

    if vals:
        median = float(np.clip(np.median(vals), 1e-4, 5.0))
        log_sd = _fallback_log_sd_from_values(vals, min_log_sd=1.0, max_log_sd=2.0)
        pool_median = median
        pool_n = len(vals)
    else:
        median = 0.001
        log_sd = 1.50
        pool_median = np.nan
        pool_n = 0

    return {
        "median": median,
        "scale": log_sd,
        "source": source,
        "fallback_reason": failure_source,
        "fallback_pool_n": pool_n,
        "fallback_pool_median": pool_median,
    }

def build_single_target_data(panel_df, network, channel, target, spend_cols, ctrl_cols,
                             priors_dict, l_max):
    """Prepare scaled arrays for one (segment × target) PyMC fit.

    Main modeling choices:
       - spend is modeled per-capita and robust p95-scaled;
       - target uses z-score for orders_per_user and p95abs for revenue/basket;
       - media adstock is reset inside every geo_label;
       - alpha/lambda can be sampled, tight, or fixed through MEDIA_RESPONSE_MODE;
       - media response is not centered in the fixed specification.
    """
    seg = panel_df[(panel_df["network"] == network) & (panel_df["channel"] == channel)].copy()
    seg = seg.sort_values(["geo_label", "date"]).reset_index(drop=True)

    if "get_spend_cols_for_segment" in globals():
        spend_cols = get_spend_cols_for_segment(network, channel, spend_cols)

    tc5_policy_applied = False
    tc5_policy_excluded_media_cols = []
    if (
        globals().get("TC5_OFFLINE_SPECIFIC_POLICY_ENABLED", False)
        and (network, channel) == globals().get("TC5_OFFLINE_POLICY_SEGMENT", ("ТС5", "Оффлайн"))
        and target in globals().get("TC5_OFFLINE_POLICY_TARGETS", set())
    ):
        excluded_cols = set(globals().get("TC5_OFFLINE_EXCLUDED_MEDIA_COLS", set()))
        before_cols = list(spend_cols)
        spend_cols = [c for c in spend_cols if c not in excluded_cols]
        tc5_policy_excluded_media_cols = [c for c in before_cols if c in excluded_cols]
        tc5_policy_applied = bool(tc5_policy_excluded_media_cols)
        if tc5_policy_applied:
            log.info(
                "TC5 Offline specific policy: excluded %s for %s/%s::%s",
                [c.replace("spend_", "") for c in tc5_policy_excluded_media_cols],
                network, channel, target,
            )

    spend_active = [c for c in spend_cols if c in seg.columns and seg[c].std() > 0]
    ctrl_active = [c for c in ctrl_cols if c in seg.columns and seg[c].std() > 0]
    for c in ctrl_active:
        if seg[c].dtype == bool:
            seg[c] = seg[c].astype(float)

    if target not in seg.columns or seg[target].std() == 0 or not spend_active:
        return None, None, None

    n_before = len(seg)
    seg = seg[seg[target].notna()].copy()
    if len(seg) < n_before:
        print(f"  Dropped {n_before - len(seg)} NaN rows in {target}")
    if len(seg) == 0:
        return None, None, None

    geos = sorted(seg["geo_label"].unique())
    M, G, K = len(spend_active), len(geos), len(ctrl_active)
    geo_idx = pd.Categorical(seg["geo_label"], categories=geos).codes.astype(int)
    market_tier_idx_by_geo, obs_tier_idx, market_tier_names, market_tier_source = extract_market_size_tiers(seg, geos, geo_idx)
    T = len(market_tier_names)
    n_obs = len(seg)

    # ── PER-CAPITA spend + robust p95 scaling ──
    Y_raw = seg[target].values.astype(float)
    pop_per_row = np.maximum(seg["population_k"].values.astype(float), 1e-3)
    X_spend_raw = seg[spend_active].values.astype(float)
    X_spend_pc = X_spend_raw / pop_per_row[:, None]

    if "anomaly_period_jul2025" in seg.columns:
        clean_mask = ~seg["anomaly_period_jul2025"].astype(bool).values
    else:
        clean_mask = np.ones(len(seg), dtype=bool)
    if clean_mask.sum() < 0.5 * len(seg):
        clean_mask = np.ones(len(seg), dtype=bool)

    geo_size_values = pd.Series(pop_per_row).groupby(geo_idx).median().reindex(range(G)).values
    X_spend_scaled, x_scale, x_scale_global, x_scaled_typical, media_scaling_audit = compute_media_scaling(
        X_spend_pc=X_spend_pc,
        geo_idx=geo_idx,
        clean_mask=clean_mask,
        geos=geos,
        spend_active=spend_active,
        geo_size_values=geo_size_values,
        market_tier_idx=market_tier_idx_by_geo,
        tier_names=market_tier_names,
    )
    x_scale_geo = np.full((G, M), np.nan, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        recovered_scale = X_spend_pc / X_spend_scaled
    for g in range(G):
        for m in range(M):
            local = recovered_scale[(geo_idx == g) & np.isfinite(recovered_scale[:, m]), m]
            if len(local):
                x_scale_geo[g, m] = float(np.median(local))
                continue
            same_tier = recovered_scale[
                np.isin(geo_idx, np.where(market_tier_idx_by_geo == market_tier_idx_by_geo[g])[0])
                & np.isfinite(recovered_scale[:, m]),
                m,
            ]
            x_scale_geo[g, m] = float(np.median(same_tier)) if len(same_tier) else float(x_scale_global[m])
    X_lagged = make_geo_lagged_tensor(X_spend_scaled, geo_idx, l_max)

    if target == "orders_per_user":
        y_offset = float(Y_raw.mean())
        y_scale = float(max(Y_raw.std(), 1e-8))
        Y_scaled = (Y_raw - y_offset) / y_scale
        y_scaling = "zscore"
    else:
        y_offset = 0.0
        y_clean = np.abs(Y_raw[clean_mask])
        y_scale = float(max(np.percentile(y_clean, 95), 1e-8))
        Y_scaled = Y_raw / y_scale
        y_scaling = "p95abs"

    if ctrl_active:
        X_ctrl_raw = seg[ctrl_active].values.astype(float)
        ctrl_mean = X_ctrl_raw.mean(axis=0)
        ctrl_std = np.maximum(X_ctrl_raw.std(axis=0), 1e-8)
        X_ctrl_scaled = (X_ctrl_raw - ctrl_mean) / ctrl_std
    else:
        ctrl_mean = np.array([])
        ctrl_std = np.array([])
        X_ctrl_scaled = None

    HALFNORMAL_MEDIAN_FACTOR = 0.67448975
    OFFLINE_PRIORS = {
        "spend_Нац_ТВ":    {"decay": 0.70, "beta_median": 0.30},
        "spend_Рег_ТВ":    {"decay": 0.65, "beta_median": 0.25},
        "spend_Радио":     {"decay": 0.50, "beta_median": 0.18},
        "spend_OOH":       {"decay": 0.55, "beta_median": 0.15},
        "spend_ООН_РТБ":   {"decay": 0.30, "beta_median": 0.10},
        "spend_OOH_Total": {"decay": 0.50, "beta_median": 0.15},
        "spend_Indoor":    {"decay": 0.45, "beta_median": 0.12},
    }
    DIGITAL_DECAY_PRIORS = {
        "spend_Paid_Search": 0.15,
        "spend_Paid_Social": 0.25,
        "spend_Programmatic": 0.25,
        "spend_Marketplace_Ads": 0.25,
        "spend_Digital_Performance": 0.25,
    }
    DIGITAL_BETA_SCALE = {"orders_per_user": 0.03, "default": 0.08}
    OFFLINE_ALPHA_CAP = 0.95
    OFFLINE_LAM_CAP = 10.0
    OFFLINE_LAM_PRIOR_MEAN = 2.0
    DIGITAL_ALPHA_CAP = {
        "spend_Paid_Search": 0.35,
        "spend_Paid_Social": 0.50,
        "spend_Programmatic": 0.50,
        "spend_Marketplace_Ads": 0.50,
        "spend_Digital_Performance": 0.50,
    }
    DIGITAL_LAM_CAP = {
        "spend_Paid_Search": 4.0,
        "spend_Paid_Social": 5.0,
        "spend_Programmatic": 5.0,
        "spend_Marketplace_Ads": 6.0,
        "spend_Digital_Performance": 6.0,
    }
    DIGITAL_LAM_PRIOR_MEAN = {
        "spend_Paid_Search": 1.0,
        "spend_Paid_Social": 1.2,
        "spend_Programmatic": 1.2,
        "spend_Marketplace_Ads": 1.5,
        "spend_Digital_Performance": 1.5,
    }
    if MEDIA_RESPONSE_MODE == "tight":
        PRIOR_CONCENTRATION = 60.0
        LAM_PRIOR_CONCENTRATION = 40.0
    else:
        PRIOR_CONCENTRATION = 12.0
        LAM_PRIOR_CONCENTRATION = 8.0

    seg_priors = priors_dict.get(f"{network}/{channel}", {}).get(target, {})
    a_pars = np.zeros(M)
    b_pars = np.zeros(M)
    alpha_caps = np.zeros(M)
    lam_a_pars = np.zeros(M)
    lam_b_pars = np.zeros(M)
    lam_caps = np.zeros(M)
    beta_scales = np.zeros(M)
    beta_prior_medians = np.zeros(M)
    beta_prior_type = []
    beta_prior_source = []
    beta_prior_fallback_reason = []
    beta_fe_raw = np.full(M, np.nan)
    beta_fe_se_raw = np.full(M, np.nan)
    beta_prior_fallback_median = np.full(M, np.nan)
    beta_prior_fallback_scale = np.full(M, np.nan)
    beta_prior_fallback_pool_n = np.full(M, np.nan)
    beta_prior_fallback_pool_median = np.full(M, np.nan)
    beta_prior_legacy_benchmark_median = np.full(M, np.nan)
    beta_prior_legacy_benchmark_scale = np.full(M, np.nan)
    beta_spend_raw_typical = np.full(M, np.nan)
    beta_pop_typical = np.full(M, np.nan)
    beta_tanh_response_typ = np.full(M, np.nan)
    beta_pymc_implied = np.full(M, np.nan)
    beta_pymc_sd = np.full(M, np.nan)
    beta_lam_prior_used = np.full(M, np.nan)
    beta_x_scale_typical = np.full(M, np.nan)
    beta_spend_scaled_typical = np.full(M, np.nan)
    alpha_prior_mean = np.zeros(M)
    lam_prior_mean_arr = np.zeros(M)
    channel_prior_setups = []
    beta_candidate_infos = []

    for m_idx, sc in enumerate(spend_active):
        is_offline_prior = sc in OFFLINE_PRIORS
        channel_family = _channel_family(sc, set(OFFLINE_PRIORS.keys()))
        if is_offline_prior:
            op = OFFLINE_PRIORS[sc]
            decay = op["decay"]
            legacy_median = op["beta_median"]
            legacy_scale = legacy_median / HALFNORMAL_MEDIAN_FACTOR
            alpha_cap = OFFLINE_ALPHA_CAP
            lam_cap = OFFLINE_LAM_CAP
            lam_mean = OFFLINE_LAM_PRIOR_MEAN
        else:
            p = seg_priors.get(sc)
            empirical_decay = p["decay"] if p else 0.30
            decay = min(empirical_decay, DIGITAL_DECAY_PRIORS.get(sc, 0.35))
            legacy_scale = DIGITAL_BETA_SCALE["orders_per_user" if target == "orders_per_user" else "default"]
            legacy_median = legacy_scale * HALFNORMAL_MEDIAN_FACTOR
            alpha_cap = DIGITAL_ALPHA_CAP.get(sc, 0.50)
            lam_cap = DIGITAL_LAM_CAP.get(sc, 6.0)
            lam_mean = DIGITAL_LAM_PRIOR_MEAN.get(sc, 1.2)

        # beta rescaling needs the same lambda center and scaling that PyMC will use.
        alpha_caps[m_idx] = alpha_cap
        lam_caps[m_idx] = lam_cap
        lam_prior_mean_arr[m_idx] = min(max(lam_mean, 1e-4), lam_cap - 1e-4)
        channel_prior_setups.append({
            "spend_col": sc,
            "is_offline_prior": is_offline_prior,
            "channel_family": channel_family,
            "decay": decay,
            "alpha_cap": alpha_cap,
            "lam_cap": lam_cap,
            "legacy_median": legacy_median,
            "legacy_scale": legacy_scale,
        })

        beta_info = beta_prior_from_empirical(
            seg_priors, sc,
            legacy_median, legacy_scale,
            seg_df=seg,
            x_scale_m=x_scale[m_idx],
            lam_prior_mean_m=lam_prior_mean_arr[m_idx],
            y_scale=y_scale,
            x_scaled_typical_m=x_scaled_typical[m_idx],
        )
        beta_info["channel_family"] = channel_family
        beta_info["legacy_benchmark_median"] = float(legacy_median)
        beta_info["legacy_benchmark_scale"] = float(legacy_scale)
        beta_candidate_infos.append(beta_info)

    for m_idx, sc in enumerate(spend_active):
        setup = channel_prior_setups[m_idx]
        beta_info = dict(beta_candidate_infos[m_idx])
        if beta_info["source"] != "empirical_fe_rescaled":
            scaled_fallback = _scaled_fallback_prior(
                target=target,
                channel_family=setup["channel_family"],
                candidate_infos=beta_candidate_infos,
                failure_source=beta_info["source"],
            )
            beta_info.update(scaled_fallback)

        beta_prior_medians[m_idx] = beta_info["median"]
        beta_scales[m_idx] = beta_info["scale"]
        beta_prior_source.append(beta_info["source"])
        beta_prior_fallback_reason.append(beta_info.get("fallback_reason", ""))
        beta_prior_type.append(
            "lognormal_empirical_fe_rescaled"
            if beta_info["source"] == "empirical_fe_rescaled"
            else (
                "lognormal_near_zero_orders_per_user"
                if beta_info["source"] == "fallback_near_zero_orders_per_user"
                else "lognormal_empirical_scale_fallback"
            )
        )
        beta_fe_raw[m_idx] = _float_or_nan(beta_info.get("fe_beta_raw"))
        beta_fe_se_raw[m_idx] = _float_or_nan(beta_info.get("fe_se_raw"))
        beta_prior_fallback_median[m_idx] = _float_or_nan(beta_info.get("median"))
        beta_prior_fallback_scale[m_idx] = _float_or_nan(beta_info.get("scale"))
        beta_prior_fallback_pool_n[m_idx] = _float_or_nan(beta_info.get("fallback_pool_n"))
        beta_prior_fallback_pool_median[m_idx] = _float_or_nan(beta_info.get("fallback_pool_median"))
        beta_prior_legacy_benchmark_median[m_idx] = _float_or_nan(beta_info.get("legacy_benchmark_median"))
        beta_prior_legacy_benchmark_scale[m_idx] = _float_or_nan(beta_info.get("legacy_benchmark_scale"))
        beta_spend_raw_typical[m_idx] = _float_or_nan(beta_info.get("spend_raw_typical"))
        beta_pop_typical[m_idx] = _float_or_nan(beta_info.get("pop_typical"))
        beta_tanh_response_typ[m_idx] = _float_or_nan(beta_info.get("tanh_response_typ"))
        beta_pymc_implied[m_idx] = _float_or_nan(beta_info.get("beta_pymc_implied"))
        beta_pymc_sd[m_idx] = _float_or_nan(beta_info.get("beta_pymc_sd"))
        beta_lam_prior_used[m_idx] = _float_or_nan(beta_info.get("lam_prior_used"))
        beta_x_scale_typical[m_idx] = _float_or_nan(beta_info.get("x_scale_typical"))
        beta_spend_scaled_typical[m_idx] = _float_or_nan(beta_info.get("spend_scaled_typical"))

        decay = setup["decay"]
        alpha_cap = setup["alpha_cap"]
        lam_cap = setup["lam_cap"]
        alpha_prior_mean[m_idx] = min(max(decay, 1e-4), alpha_cap - 1e-4)
        alpha_raw_mean = min(max(alpha_prior_mean[m_idx] / alpha_cap, 0.05), 0.95)
        a_pars[m_idx] = max(alpha_raw_mean * PRIOR_CONCENTRATION, 0.5)
        b_pars[m_idx] = max((1 - alpha_raw_mean) * PRIOR_CONCENTRATION, 0.5)

        lam_unit_mean = min(max(lam_prior_mean_arr[m_idx] / lam_cap, 0.05), 0.95)
        lam_a_pars[m_idx] = max(lam_unit_mean * LAM_PRIOR_CONCENTRATION, 0.5)
        lam_b_pars[m_idx] = max((1 - lam_unit_mean) * LAM_PRIOR_CONCENTRATION, 0.5)

    if "get_beta_structure_for_fit" in globals():
        beta_structure = get_beta_structure_for_fit(network, channel, target)
    else:
        beta_structure = globals().get("BETA_STRUCTURE_BY_TARGET", {}).get(target, "hierarchical_geo")
        allowed_beta_structures = globals().get("ALLOWED_BETA_STRUCTURES", {"pooled", "hierarchical_geo", "hierarchical_tier"})
        if beta_structure not in allowed_beta_structures:
            raise ValueError(f"Unknown beta_structure for {network}/{channel}::{target}: {beta_structure}")

    beta_tier_pooled_channels = set()
    if beta_structure == "hierarchical_tier" and "get_beta_tier_pooled_channels_for_fit" in globals():
        beta_tier_pooled_channels = get_beta_tier_pooled_channels_for_fit(network, channel, target)

    channel_names = [c.replace("spend_", "") for c in spend_active]
    unknown_beta_tier_pooled_channels = sorted(beta_tier_pooled_channels - set(channel_names))
    if unknown_beta_tier_pooled_channels:
        raise ValueError(
            f"Unknown beta_tier pooled channels for {network}/{channel}::{target}: "
            f"{unknown_beta_tier_pooled_channels}. Available channels: {channel_names}"
        )
    beta_tier_pool_channel_mask = np.array(
        [ch_name in beta_tier_pooled_channels for ch_name in channel_names],
        dtype=bool,
    )
    beta_tier_pool_channel_idx = np.flatnonzero(beta_tier_pool_channel_mask).astype(int)
    beta_tier_hier_channel_idx = np.flatnonzero(~beta_tier_pool_channel_mask).astype(int)

    prior_tier_rows = []
    for m_idx, sc in enumerate(spend_active):
        for t_idx, tier_name in enumerate(market_tier_names):
            active_tier = (
                (obs_tier_idx == t_idx)
                & clean_mask
                & np.isfinite(X_spend_raw[:, m_idx])
                & (X_spend_raw[:, m_idx] > 0)
            )
            if active_tier.any():
                spend_raw_typ = float(np.median(X_spend_raw[active_tier, m_idx]))
                spend_pc_typ = float(np.median(X_spend_pc[active_tier, m_idx]))
                spend_scaled_typ = float(np.median(X_spend_scaled[active_tier, m_idx]))
                x_scale_typ = spend_pc_typ / max(spend_scaled_typ, 1e-12) if spend_scaled_typ > 0 else np.nan
                tanh_typ = float(np.tanh(lam_prior_mean_arr[m_idx] * spend_scaled_typ / 2.0))
            else:
                spend_raw_typ = spend_pc_typ = spend_scaled_typ = x_scale_typ = tanh_typ = np.nan
            implied_scaled = beta_prior_medians[m_idx] * tanh_typ if np.isfinite(tanh_typ) else np.nan
            prior_tier_rows.append({
                "spend_col": sc,
                "channel": sc.replace("spend_", ""),
                "market_size_tier": tier_name,
                "tier_active_obs": int(active_tier.sum()),
                "spend_raw_typical_tier": spend_raw_typ,
                "spend_pc_typical_tier": spend_pc_typ,
                "x_scale_typical_tier": x_scale_typ,
                "spend_scaled_typical_tier": spend_scaled_typ,
                "lam_prior_mean": float(lam_prior_mean_arr[m_idx]),
                "tanh_response_typical_tier": tanh_typ,
                "beta_prior_median": float(beta_prior_medians[m_idx]),
                "beta_prior_log_sd": float(np.clip(beta_scales[m_idx], 0.3, 2.0)),
                "prior_implied_effect_scaled": implied_scaled,
                "prior_implied_effect_target_unit": implied_scaled * y_scale if np.isfinite(implied_scaled) else np.nan,
                "beta_prior_source": beta_prior_source[m_idx],
            })
    prior_tier_audit = pd.DataFrame(prior_tier_rows)

    y_level_prior_mu = float(np.mean(Y_scaled))
    y_level_prior_sd = float(max(np.std(Y_scaled), 0.1))
    y_tier_means = pd.Series(Y_scaled).groupby(obs_tier_idx).mean().reindex(range(T))
    y_tier_sd_prior = float(max(np.nanstd(y_tier_means.values), 0.05))
    y_geo_means = pd.Series(Y_scaled).groupby(geo_idx).mean().reindex(range(G))
    geo_tier_mean = y_tier_means.reindex(market_tier_idx_by_geo).to_numpy()
    y_geo_resid = y_geo_means.to_numpy() - geo_tier_mean
    y_geo_sd_prior = float(max(np.nanstd(y_geo_resid), 0.05))
    beta_geo_sd_prior = np.full(M, 0.5)
    beta_tier_sd_prior = np.full(M, 0.35)
    sigma_prior = float(max(np.std(Y_scaled), 0.1))
    sigma_tier_prior = np.array([
        float(max(np.std(Y_scaled[obs_tier_idx == t]), 0.05)) if np.any(obs_tier_idx == t) else sigma_prior
        for t in range(T)
    ])
    # `beta_scales` is legacy-named; in this fixed spec it stores lognormal sigma_log.
    beta_prior_log_sd = np.clip(beta_scales, 0.3, 2.0)

    coords = {
        "channel": channel_names,
        "geo_label": geos,
        "market_size_tier": market_tier_names,
        "tier_pool_channel": [channel_names[i] for i in beta_tier_pool_channel_idx],
        "tier_hier_channel": [channel_names[i] for i in beta_tier_hier_channel_idx],
        "ctrl": ctrl_active,
        "obs": np.arange(n_obs),
    }

    return seg, coords, {
        "X_spend": X_spend_scaled,
        "X_lagged": X_lagged,
        "X_ctrl": X_ctrl_scaled,
        "Y": Y_scaled,
        "y_scale": y_scale, "y_offset": y_offset, "y_scaling": y_scaling,
        "x_scale": x_scale,
        "x_scale_global": x_scale_global,
        "x_scale_geo": x_scale_geo,
        "x_scaled_typical": x_scaled_typical,
        "media_scaling_mode": MEDIA_SCALING_MODE,
        "media_scaling_audit": media_scaling_audit,
        "prior_tier_audit": prior_tier_audit,
        "ctrl_mean": ctrl_mean, "ctrl_std": ctrl_std,
        "geo_idx": geo_idx,
        "obs_tier_idx": obs_tier_idx.astype(int),
        "geo_tier_idx": market_tier_idx_by_geo.astype(int),
        "market_size_tiers": market_tier_names,
        "market_size_tier_source": market_tier_source,
        "n_obs": n_obs,
        "spend_active": spend_active, "ctrl_active": ctrl_active, "target": target,
        "geos": geos,
        "a_pars": a_pars, "b_pars": b_pars,
        "alpha_caps": alpha_caps,
        "alpha_prior_mean": alpha_prior_mean,
        "lam_a_pars": lam_a_pars, "lam_b_pars": lam_b_pars,
        "lam_caps": lam_caps,
        "lam_prior_mean": lam_prior_mean_arr,
        "beta_scales": beta_scales,
        "beta_prior_medians": beta_prior_medians,
        "beta_prior_type": beta_prior_type,
        "beta_prior_source": beta_prior_source,
        "beta_prior_fallback_reason": beta_prior_fallback_reason,
        "beta_fe_raw": beta_fe_raw,
        "beta_fe_se_raw": beta_fe_se_raw,
        "beta_prior_fallback_median": beta_prior_fallback_median,
        "beta_prior_fallback_scale": beta_prior_fallback_scale,
        "beta_prior_fallback_pool_n": beta_prior_fallback_pool_n,
        "beta_prior_fallback_pool_median": beta_prior_fallback_pool_median,
        "beta_prior_legacy_benchmark_median": beta_prior_legacy_benchmark_median,
        "beta_prior_legacy_benchmark_scale": beta_prior_legacy_benchmark_scale,
        "beta_spend_raw_typical": beta_spend_raw_typical,
        "beta_pop_typical": beta_pop_typical,
        "beta_tanh_response_typ": beta_tanh_response_typ,
        "beta_pymc_implied": beta_pymc_implied,
        "beta_pymc_sd": beta_pymc_sd,
        "beta_lam_prior_used": beta_lam_prior_used,
        "beta_x_scale_typical": beta_x_scale_typical,
        "beta_spend_scaled_typical": beta_spend_scaled_typical,
        "beta_prior_log_sd": beta_prior_log_sd,
        "beta_geo_sd_prior": beta_geo_sd_prior,
        "beta_tier_sd_prior": beta_tier_sd_prior,
        "beta_structure": beta_structure,
        "beta_tier_pooled_channels": sorted(beta_tier_pooled_channels),
        "beta_tier_pool_channel_mask": beta_tier_pool_channel_mask,
        "beta_tier_pool_channel_idx": beta_tier_pool_channel_idx,
        "beta_tier_hier_channel_idx": beta_tier_hier_channel_idx,
        "baseline_structure": globals().get("BASELINE_STRUCTURE", "tier_geo"),
        "error_structure": globals().get("ERROR_STRUCTURE", "tier"),
        "y_level_prior_mu": y_level_prior_mu,
        "y_level_prior_sd": y_level_prior_sd,
        "y_tier_sd_prior": y_tier_sd_prior,
        "y_geo_sd_prior": y_geo_sd_prior,
        "sigma_prior": sigma_prior,
        "sigma_tier_prior": sigma_tier_prior,
        "media_response_mode": MEDIA_RESPONSE_MODE,
        "center_media_response": CENTER_MEDIA_RESPONSE,
        "postfit_roas_response_basis": "raw_saturation",
        "tc5_offline_specific_policy_applied": tc5_policy_applied,
        "tc5_offline_excluded_media_cols": tc5_policy_excluded_media_cols,
        "M": M, "G": G, "T": T, "K_ctrl": K, "l_max": l_max,
    }

def build_pymc_model(coords, data):
    """Single-target Bayesian MMM, fixed specification.

    Changes versus previous specific_TC5_offline:
      - no centered media response in likelihood;
      - tau_g is non-centered around a global intercept mu_tau;
      - beta is target-specific: pooled for orders, hierarchical channel x geo for revenue/basket;
      - alpha/lambda are sampled in tight/pilot/production modes.
    """
    M, K = data["M"], data["K_ctrl"]
    l_max = data["l_max"]

    with pm.Model(coords=coords) as model:
        response_mode = data.get("media_response_mode", "tight")
        beta_structure = data.get("beta_structure", "hierarchical_geo")

        if response_mode == "fixed":
            alpha = pm.Deterministic("alpha", pt.as_tensor_variable(data["alpha_prior_mean"]), dims="channel")
            lam = pm.Deterministic("lam", pt.as_tensor_variable(data["lam_prior_mean"]), dims="channel")
        else:
            alpha_raw = pm.Beta("alpha_raw", alpha=data["a_pars"], beta=data["b_pars"], dims="channel")
            alpha = pm.Deterministic("alpha", alpha_raw * data["alpha_caps"], dims="channel")
            fixed_lambda_idx = np.asarray(data.get("fixed_lambda_channel_idx", []), dtype=int)
            free_lambda_idx = np.asarray(data.get("free_lambda_channel_idx", np.arange(M)), dtype=int)
            if fixed_lambda_idx.size:
                lam_values = pt.as_tensor_variable(data["lam_prior_mean"])
                if free_lambda_idx.size:
                    lam_unit_free = pm.Beta(
                        "lam_unit_free",
                        alpha=data["lam_a_pars"][free_lambda_idx],
                        beta=data["lam_b_pars"][free_lambda_idx],
                        dims="lambda_free_channel",
                    )
                    lam_free = lam_unit_free * data["lam_caps"][free_lambda_idx]
                    lam_values = pt.set_subtensor(lam_values[free_lambda_idx], lam_free)
                lam = pm.Deterministic("lam", lam_values, dims="channel")
            else:
                lam_unit = pm.Beta("lam_unit", alpha=data["lam_a_pars"], beta=data["lam_b_pars"], dims="channel")
                lam = pm.Deterministic("lam", lam_unit * data["lam_caps"], dims="channel")

        if beta_structure == "pooled":
            beta = pm.LogNormal(
                "beta",
                mu=np.log(np.maximum(data["beta_prior_medians"], 1e-4)),
                sigma=data["beta_prior_log_sd"],
                dims="channel",
            )
        elif beta_structure in {"hierarchical_geo", "hierarchical_tier"}:
            if beta_structure == "hierarchical_geo":
                mu_log_beta = pm.Normal(
                    "mu_log_beta",
                    mu=np.log(np.maximum(data["beta_prior_medians"], 1e-4)),
                    sigma=data["beta_prior_log_sd"],
                    dims="channel",
                )
                sigma_log_beta = pm.HalfNormal("sigma_log_beta", sigma=data["beta_geo_sd_prior"], dims="channel")
                beta_raw = pm.Normal("beta_raw", mu=0, sigma=1.0, dims=("channel", "geo_label"))
                beta = pm.Deterministic(
                    "beta",
                    pt.exp(mu_log_beta[:, None] + sigma_log_beta[:, None] * beta_raw),
                    dims=("channel", "geo_label"),
                )
            else:
                tier_pool_idx = np.asarray(data.get("beta_tier_pool_channel_idx", []), dtype=int)
                tier_hier_idx = np.asarray(data.get("beta_tier_hier_channel_idx", np.arange(M)), dtype=int)
                beta_tier_full = pt.zeros((M, data["T"]))

                if tier_hier_idx.size:
                    mu_log_beta = pm.Normal(
                        "mu_log_beta",
                        mu=np.log(np.maximum(data["beta_prior_medians"][tier_hier_idx], 1e-4)),
                        sigma=data["beta_prior_log_sd"][tier_hier_idx],
                        dims="tier_hier_channel",
                    )
                    sigma_log_beta = pm.HalfNormal(
                        "sigma_log_beta",
                        sigma=data["beta_tier_sd_prior"][tier_hier_idx],
                        dims="tier_hier_channel",
                    )
                    beta_raw = pm.Normal(
                        "beta_raw",
                        mu=0,
                        sigma=1.0,
                        dims=("tier_hier_channel", "market_size_tier"),
                    )
                    beta_hier = pt.exp(mu_log_beta[:, None] + sigma_log_beta[:, None] * beta_raw)
                    beta_tier_full = pt.set_subtensor(beta_tier_full[tier_hier_idx, :], beta_hier)

                if tier_pool_idx.size:
                    beta_tier_pooled = pm.LogNormal(
                        "beta_tier_pooled",
                        mu=np.log(np.maximum(data["beta_prior_medians"][tier_pool_idx], 1e-4)),
                        sigma=data["beta_prior_log_sd"][tier_pool_idx],
                        dims="tier_pool_channel",
                    )
                    beta_tier_full = pt.set_subtensor(beta_tier_full[tier_pool_idx, :], beta_tier_pooled[:, None])

                beta = pm.Deterministic("beta", beta_tier_full, dims=("channel", "market_size_tier"))
        else:
            raise ValueError(f"Unknown beta_structure: {beta_structure}")

        if K > 0:
            gamma = pm.Normal("gamma", mu=0, sigma=1.0, dims="ctrl")

        x_lagged = pm.Data("x_lagged", data["X_lagged"])
        geo_idx_data = pm.Data("geo_idx", data["geo_idx"])
        tier_idx_data = pm.Data("market_tier_idx", data["obs_tier_idx"])

        mu_tau = pm.Normal("mu_tau", mu=data["y_level_prior_mu"], sigma=data["y_level_prior_sd"])
        baseline_structure = data.get("baseline_structure", "tier_geo")
        if baseline_structure == "tier_geo":
            sigma_tau_tier = pm.HalfNormal("sigma_tau_tier", sigma=data["y_tier_sd_prior"])
            tau_tier_raw = pm.Normal("tau_tier_raw", mu=0, sigma=1.0, dims="market_size_tier")
            tau_tier = pm.Deterministic("tau_tier", mu_tau + sigma_tau_tier * tau_tier_raw, dims="market_size_tier")
            sigma_tau_geo = pm.HalfNormal("sigma_tau_geo", sigma=data["y_geo_sd_prior"])
            tau_raw = pm.Normal("tau_raw", mu=0, sigma=1.0, dims="geo_label")
            geo_tier_idx_const = pt.as_tensor_variable(data["geo_tier_idx"])
            tau_g = pm.Deterministic(
                "tau_g",
                tau_tier[geo_tier_idx_const] + sigma_tau_geo * tau_raw,
                dims="geo_label",
            )
        else:
            # Centered geo baseline is empirically more stable for all-geo fits.
            # Non-centered tau_raw mixed poorly when geo effects are strongly identified.
            sigma_tau = pm.HalfNormal("sigma_tau", sigma=data["y_geo_sd_prior"])
            tau_g = pm.Normal("tau_g", mu=mu_tau, sigma=sigma_tau, dims="geo_label")

        weights = alpha[None, :] ** pt.arange(l_max + 1)[:, None]
        weights = weights / weights.sum(axis=0, keepdims=True)
        x_ads = (weights[:, None, :] * x_lagged).sum(axis=0)
        x_sat = pt.tanh(lam[None, :] * x_ads / 2.0)

        if beta_structure == "pooled":
            spend_contrib = (beta[None, :] * x_sat).sum(axis=1)
        elif beta_structure == "hierarchical_tier":
            beta_obs = beta[:, tier_idx_data].T
            spend_contrib = (beta_obs * x_sat).sum(axis=1)
        else:
            beta_obs = beta[:, geo_idx_data].T
            spend_contrib = (beta_obs * x_sat).sum(axis=1)
        mu = tau_g[geo_idx_data] + spend_contrib
        if K > 0:
            x_ctrl = pm.Data("x_ctrl", data["X_ctrl"])
            mu = mu + pt.dot(x_ctrl, gamma)

        if data.get("error_structure", "tier") == "tier":
            sigma_tier = pm.HalfNormal("sigma_tier", sigma=data["sigma_tier_prior"], dims="market_size_tier")
            sigma_obs = sigma_tier[tier_idx_data]
        else:
            sigma = pm.HalfNormal("sigma", sigma=data["sigma_prior"])
            sigma_obs = sigma
        pm.Normal("y_obs", mu=mu, sigma=sigma_obs, observed=data["Y"], dims="obs")

    return model

def fit_with_diagnostics(
    model,
    draws,
    tune,
    chains,
    target_accept,
    use_jax=True,
    *,
    require_numpyro=True,
    random_seed=RANDOM_SEED,
    progressbar=True,
):
    log.info(f"  Sampling: chains={chains}, draws={draws}, tune={tune}")
    t0 = time.time()
    kwargs = dict(
        draws=draws,
        tune=tune,
        chains=chains,
        target_accept=target_accept,
        random_seed=random_seed,
        progressbar=progressbar,
    )
    with model:
        if use_jax:
            try:
                import numpyro  # noqa
                idata = pm.sample(nuts_sampler="numpyro", **kwargs)
                sampler_name = "numpyro (JAX)"
            except ImportError as exc:
                if require_numpyro:
                    raise RuntimeError(
                        "NumPyro is required for notebook/script sampler parity. "
                        "Set require_numpyro=false only for an explicit non-parity diagnostic run."
                    ) from exc
                idata = pm.sample(**kwargs)
                sampler_name = "pymc default"
        else:
            idata = pm.sample(**kwargs)
            sampler_name = "pymc default"
    dt = time.time() - t0
    summary = az.summary(idata, round_to=4)
    diag = {
        "fit_time_min": round(dt/60, 2),
        "sampler": sampler_name,
        "rhat_max": float(summary["r_hat"].max()),
        "rhat_mean": float(summary["r_hat"].mean()),
        "ess_bulk_min": float(summary["ess_bulk"].min()),
        "ess_per_draw": float(summary["ess_bulk"].min()) / (draws * chains),
        "n_params": len(summary),
    }
    if hasattr(idata, "sample_stats") and "diverging" in idata.sample_stats:
        diag["n_divergences"] = int(idata.sample_stats["diverging"].sum())
    issues = []
    if diag["rhat_max"] > 1.05: issues.append(f"R̂={diag['rhat_max']:.3f}")
    if diag["ess_per_draw"] < 0.1: issues.append(f"ESS/draw={diag['ess_per_draw']:.3f}")
    if diag.get("n_divergences", 0) > 5: issues.append(f"div={diag['n_divergences']}")
    diag["status"] = "OK ✓" if not issues else "⚠ " + "; ".join(issues)
    log.info(f"  Time={dt/60:.1f}min | R̂={diag['rhat_max']:.4f} | ESS_min={diag['ess_bulk_min']:.0f} | {diag['status']}")
    return idata, diag

def _normalize_only_fits(only_fits):
    if only_fits is None:
        return None
    normalized = set()
    for item in only_fits:
        if isinstance(item, str):
            normalized.add(item)
        else:
            network, channel, target = item
            normalized.add(f"{network}/{channel}::{target}")
    return normalized

def _make_geo_lagged_tensor_np(X, geo_idx, l_max):
    """Numpy version of geo-reset lag tensor for post-fit calculations."""
    X = np.asarray(X, dtype=float)
    geo_idx = np.asarray(geo_idx)
    n_obs, n_media = X.shape
    x_lagged = np.zeros((l_max + 1, n_obs, n_media), dtype=float)
    for g in np.unique(geo_idx):
        ix = np.where(geo_idx == g)[0]
        xg = X[ix, :]
        for lag in range(l_max + 1):
            if lag == 0:
                x_lagged[lag, ix, :] = xg
            else:
                x_lagged[lag, ix[lag:], :] = xg[:-lag, :]
    return x_lagged

def _x_ads_sat_np(data, alpha, lam, X=None):
    """Compute adstock + saturation with the same geo-reset logic as the model.

    Post-fit decomposition intentionally uses raw saturation, even when the
    likelihood used centered response. Centering is a sampler/baseline trick;
    ROAS needs a non-zero raw response basis.
    """
    l_max = data["l_max"]
    if X is None:
        x_lagged = data.get("X_lagged")
        if x_lagged is None:
            x_lagged = _make_geo_lagged_tensor_np(data["X_spend"], data["geo_idx"], l_max)
    else:
        x_lagged = _make_geo_lagged_tensor_np(X, data["geo_idx"], l_max)
    weights = alpha[None, :] ** np.arange(l_max + 1)[:, None]
    weights = weights / weights.sum(axis=0, keepdims=True)
    x_ads = (weights[:, None, :] * x_lagged).sum(axis=0)
    x_sat = np.tanh(lam[None, :] * x_ads / 2.0)
    return x_ads, x_sat

def _stack_channel_samples(da):
    stacked = da.stack(sample=("chain", "draw"))
    if "geo_label" in stacked.dims:
        return stacked.transpose("channel", "geo_label", "sample").values, "geo"
    if "market_size_tier" in stacked.dims:
        return stacked.transpose("channel", "market_size_tier", "sample").values, "tier"
    return stacked.transpose("channel", "sample").values, "pooled"

def _beta_kind_from_da(da):
    if "geo_label" in da.dims:
        return "geo"
    if "market_size_tier" in da.dims:
        return "tier"
    return "pooled"

def _beta_sample(beta_s, beta_kind, sample_idx):
    return beta_s[:, sample_idx] if beta_kind == "pooled" else beta_s[:, :, sample_idx]

def _beta_obs_for_channel(beta_values, beta_kind, data, channel_idx):
    if beta_kind == "pooled":
        return beta_values[channel_idx]
    if beta_kind == "tier":
        return beta_values[channel_idx, data["obs_tier_idx"]]
    return beta_values[channel_idx, data["geo_idx"]]

def compute_channel_contributions(idata, data):
    """Raw-response contribution[n, m] = beta * S(adstock(x)). Single-target."""
    posterior = idata.posterior
    M = data["M"]
    geo_idx = data["geo_idx"]
    alpha_m = posterior["alpha"].mean(dim=("chain","draw")).values
    lam_m = posterior["lam"].mean(dim=("chain","draw")).values
    beta_m = posterior["beta"].mean(dim=("chain","draw")).values
    beta_kind = _beta_kind_from_da(posterior["beta"])

    x_ads, x_sat = _x_ads_sat_np(data, alpha_m, lam_m)
    contribs = np.zeros_like(x_sat)
    for m in range(M):
        contribs[:, m] = _beta_obs_for_channel(beta_m, beta_kind, data, m) * x_sat[:, m]
    return contribs, x_sat, x_ads

def compute_roas_distribution(idata, data, n_samples=200):
    """Distributional ROAS per channel in scaled units, using raw saturation basis."""
    posterior = idata.posterior
    M = data["M"]
    geo_idx = data["geo_idx"]
    spend_total = data["X_spend"].sum(axis=0)

    alpha_s, _ = _stack_channel_samples(posterior["alpha"])
    lam_s, _ = _stack_channel_samples(posterior["lam"])
    beta_s, beta_kind = _stack_channel_samples(posterior["beta"])
    n_total = alpha_s.shape[-1]
    idx_subset = np.random.RandomState(42).choice(n_total, size=min(n_samples, n_total), replace=False)

    roas_samples = np.zeros((M, len(idx_subset)))
    for i, s_idx in enumerate(idx_subset):
        alpha_i = alpha_s[:, s_idx]
        lam_i = lam_s[:, s_idx]
        beta_i = _beta_sample(beta_s, beta_kind, s_idx)
        _, x_sat_i = _x_ads_sat_np(data, alpha_i, lam_i)
        for m in range(M):
            beta_obs_m = _beta_obs_for_channel(beta_i, beta_kind, data, m)
            contrib_total = (beta_obs_m * x_sat_i[:, m]).sum()
            roas_samples[m, i] = contrib_total / spend_total[m] if spend_total[m] > 1e-10 else 0
    return roas_samples

def compute_mroas(idata, data, perturbation=0.01):
    """mROAS through +1% numerical perturbation on raw saturation basis."""
    posterior = idata.posterior
    M = data["M"]
    geo_idx = data["geo_idx"]
    alpha_m = posterior["alpha"].mean(dim=("chain","draw")).values
    lam_m = posterior["lam"].mean(dim=("chain","draw")).values
    beta_m = posterior["beta"].mean(dim=("chain","draw")).values
    beta_kind = _beta_kind_from_da(posterior["beta"])

    def _predict(X):
        _, x_sat = _x_ads_sat_np(data, alpha_m, lam_m, X=X)
        contrib = np.zeros_like(x_sat)
        for m in range(M):
            contrib[:, m] = _beta_obs_for_channel(beta_m, beta_kind, data, m) * x_sat[:, m]
        return contrib

    base_total = _predict(data["X_spend"]).sum(axis=0)
    mroas = np.zeros(M)
    for m in range(M):
        X_p = data["X_spend"].copy()
        X_p[:, m] *= (1 + perturbation)
        pert_total = _predict(X_p).sum(axis=0)
        dy = pert_total[m] - base_total[m]
        dx = data["X_spend"][:, m].sum() * perturbation
        if dx > 1e-10:
            mroas[m] = dy / dx
    return mroas

def compute_channel_reliability(seg_df, spend_col):
    """Возвращает spend/coverage flags для интерпретации ROAS."""
    if seg_df is None or spend_col not in seg_df.columns:
        return {
            "active_geos": np.nan, "active_days": np.nan, "pct_nonzero_rows": np.nan,
            "top3_geo_share": np.nan, "top5_date_share": np.nan,
            "reliability_flags": "NO_SEG_DF",
        }
    x = seg_df[spend_col].astype(float)
    total = float(x.sum())
    nz = x > 0
    by_geo = seg_df.groupby("geo_label")[spend_col].sum().sort_values(ascending=False)
    by_date = seg_df.groupby("date")[spend_col].sum().sort_values(ascending=False)
    top3_geo_share = float(by_geo.head(3).sum() / total) if total > 0 else 0.0
    top5_date_share = float(by_date.head(5).sum() / total) if total > 0 else 0.0
    flags = []
    if total < 10_000_000:
        flags.append("LOW_SPEND_LT_10M")
    if (
        spend_col == globals().get("INDOOR_MEDIA_COL", "spend_Indoor")
        and globals().get("MODE") == "fast"
        and globals().get("INDOOR_REPORTING_MODE") == "diagnostic_only_in_fast_until_medium_validated"
    ):
        flags.append("INDOOR_FAST_SMOKE_DIAGNOSTIC_ONLY")
    if seg_df.loc[nz, "geo_label"].nunique() < 5:
        flags.append("LOW_ACTIVE_GEOS_LT_5")
    if nz.mean() < 0.02:
        flags.append("SPARSE_ROWS_LT_2PCT")
    if top3_geo_share > 0.80:
        flags.append("GEO_CONCENTRATION_TOP3_GT_80PCT")
    if top5_date_share > 0.40:
        flags.append("TIME_CONCENTRATION_TOP5D_GT_40PCT")
    return {
        "active_geos": int(seg_df.loc[nz, "geo_label"].nunique()),
        "active_days": int(seg_df.loc[nz, "date"].nunique()),
        "pct_nonzero_rows": float(nz.mean() * 100),
        "top3_geo_share": top3_geo_share,
        "top5_date_share": top5_date_share,
        "reliability_flags": "|".join(flags) if flags else "OK",
    }

def build_roas_quality_flags(diag, adequacy, reliability_flags, target):
    """Machine-readable ROAS interpretation flags for reports."""
    flags = []
    diag = diag or {}
    adequacy = adequacy or {}
    rhat = diag.get("rhat_max")
    ess_per_draw = diag.get("ess_per_draw")
    n_div = diag.get("n_divergences", 0)
    if rhat is not None and rhat > 1.05:
        flags.append("FIT_NOT_CONVERGED")
    elif rhat is not None and rhat > 1.03:
        flags.append("FIT_BORDERLINE_RHAT_GT_1_03")
    if ess_per_draw is not None and ess_per_draw < 0.10:
        flags.append("FIT_LOW_ESS")
    if n_div and n_div > 0:
        flags.append("FIT_DIVERGENCES")
    if reliability_flags and reliability_flags != "OK":
        flags.append("SPEND_RELIABILITY_FLAG")
    if target == "orders_per_user":
        if adequacy.get("r2_mean", 0.0) < 0:
            flags.append("NEGATIVE_PPC_R2")
        if adequacy.get("r2_point", 1.0) < 0.30:
            flags.append("WEAK_ORDERS_FIT")
    return "|".join(flags) if flags else "OK"

def compute_revenue_roas(idata, data, seg_df, n_samples=200):
    """Convert scaled turnover_per_user ROAS to rubles.

    In this fixed specification the likelihood uses raw saturated media response.
    Monetary ROAS is computed as posterior counterfactual effect vs no channel,
    then divided by raw spend in RUB.
    """
    posterior = idata.posterior
    M = data["M"]
    geo_idx = data["geo_idx"]
    if seg_df is None or "unique_users" not in seg_df.columns:
        return None
    uu = seg_df["unique_users"].values.astype(float)
    spend_total_rub = seg_df[data["spend_active"]].sum(axis=0).values.astype(float)

    alpha_s, _ = _stack_channel_samples(posterior["alpha"])
    lam_s, _ = _stack_channel_samples(posterior["lam"])
    beta_s, beta_kind = _stack_channel_samples(posterior["beta"])
    n_total = alpha_s.shape[-1]
    idx_subset = np.random.RandomState(42).choice(n_total, size=min(n_samples, n_total), replace=False)

    roas_rub_samples = np.zeros((M, len(idx_subset)))
    for i, s in enumerate(idx_subset):
        alpha_i = alpha_s[:, s]
        lam_i = lam_s[:, s]
        beta_i = _beta_sample(beta_s, beta_kind, s)
        _, x_sat_i = _x_ads_sat_np(data, alpha_i, lam_i)

        for m in range(M):
            beta_obs_m = _beta_obs_for_channel(beta_i, beta_kind, data, m)
            contrib_scaled = beta_obs_m * x_sat_i[:, m]
            contrib_rub = (contrib_scaled * data["y_scale"] * uu).sum()
            roas_rub_samples[m, i] = contrib_rub / spend_total_rub[m] if spend_total_rub[m] > 1e-10 else 0
    return roas_rub_samples

def compute_target_effect_distribution(idata, data, seg_df, n_samples=200):
    """Counterfactual channel effects in original target units for all targets."""
    posterior = idata.posterior
    M = data["M"]
    geo_idx = data["geo_idx"]
    alpha_s, _ = _stack_channel_samples(posterior["alpha"])
    lam_s, _ = _stack_channel_samples(posterior["lam"])
    beta_s, beta_kind = _stack_channel_samples(posterior["beta"])
    n_total = alpha_s.shape[-1]
    idx_subset = np.random.RandomState(42).choice(n_total, size=min(n_samples, n_total), replace=False)

    uu = seg_df["unique_users"].values.astype(float) if seg_df is not None and "unique_users" in seg_df.columns else np.ones(data["n_obs"])
    orders = seg_df["orders_cnt"].values.astype(float) if seg_df is not None and "orders_cnt" in seg_df.columns else np.ones(data["n_obs"])
    spend_total = seg_df[data["spend_active"]].sum(axis=0).values.astype(float) if seg_df is not None else np.full(M, np.nan)
    target = data["target"]

    effect_samples = np.zeros((M, len(idx_subset)))
    total_samples = np.zeros((M, len(idx_subset)))
    for i_s, s_idx in enumerate(idx_subset):
        alpha_i = alpha_s[:, s_idx]
        lam_i = lam_s[:, s_idx]
        beta_i = _beta_sample(beta_s, beta_kind, s_idx)
        _, x_sat_i = _x_ads_sat_np(data, alpha_i, lam_i)
        for m in range(M):
            beta_obs_m = _beta_obs_for_channel(beta_i, beta_kind, data, m)
            contrib_unit = beta_obs_m * x_sat_i[:, m] * data["y_scale"]
            if target in {"turnover_per_user", "orders_per_user"}:
                weight = np.maximum(uu, 1e-8)
                effect_samples[m, i_s] = np.average(contrib_unit, weights=weight)
                total_samples[m, i_s] = np.sum(contrib_unit * uu)
            elif target == "avg_basket":
                weight = np.maximum(orders, 1e-8)
                effect_samples[m, i_s] = np.average(contrib_unit, weights=weight)
                total_samples[m, i_s] = np.sum(contrib_unit * orders)
            else:
                effect_samples[m, i_s] = np.mean(contrib_unit)
                total_samples[m, i_s] = np.sum(contrib_unit)

    return effect_samples, total_samples, spend_total

def classify_prior_posterior_contraction(
    prior_variance: float,
    posterior_variance: float,
) -> tuple[float | None, str]:
    """Classify variance contraction without conflating expansion with prior dominance."""
    prior_value = float(prior_variance)
    posterior_value = float(posterior_variance)
    if (
        not np.isfinite(prior_value)
        or not np.isfinite(posterior_value)
        or prior_value <= 1e-15
        or posterior_value < 0
    ):
        return None, "unavailable"
    contraction = 1.0 - posterior_value / prior_value
    if not np.isfinite(contraction):
        return None, "unavailable"
    if contraction < 0:
        return contraction, "posterior_expanded"
    if contraction < 0.2:
        return contraction, "low_contraction"
    if contraction < 0.5:
        return contraction, "medium_contraction"
    return contraction, "high_contraction"


def prior_posterior_contraction(idata, model, var_names=("beta",), samples=500):
    """Measure prior-to-posterior variance contraction with explicit expansion semantics."""
    with model:
        prior = pm.sample_prior_predictive(samples=samples, random_seed=42, var_names=list(var_names))
    rows = []
    for v in var_names:
        if v not in idata.posterior or v not in prior.prior:
            continue
        post = idata.posterior[v]
        pri = prior.prior[v]
        dims = [d for d in post.dims if d not in ("chain", "draw")]
        post_var = post.var(dim=("chain", "draw"))
        pri_var = pri.var(dim=("chain", "draw"))
        for idx in np.ndindex(*[post.sizes[d] for d in dims]):
            label = {d: post[d].values[idx[k]] for k, d in enumerate(dims)}
            posterior_variance = float(post_var.values[idx])
            prior_variance = float(pri_var.values[idx])
            contraction, verdict = classify_prior_posterior_contraction(
                prior_variance,
                posterior_variance,
            )
            rows.append({
                **label,
                "param": v,
                "contraction_schema_version": CONTRACTION_SCHEMA_VERSION,
                "prior_variance": prior_variance,
                "posterior_variance": posterior_variance,
                "contraction": contraction,
                "verdict": verdict,
            })
    return pd.DataFrame(rows)


def load_guarded_fit_spec(
    config_path: str | Path,
    *,
    run_dir: str | Path | None = None,
    panel_override: str | Path | None = None,
    mode_override: str | None = None,
) -> GuardedFitSpec:
    """Load the immutable script-backed fit contract."""
    config_path = resolve_path(config_path)
    config = load_config(config_path)
    mode = str(mode_override or config.get("mode") or "production")
    if mode not in MODE_PROFILES:
        raise ValueError(f"Unsupported fit mode={mode!r}; expected one of {sorted(MODE_PROFILES)}")
    configured_profile = ((config.get("profiles") or {}).get(mode) or {})
    profile = {**MODE_PROFILES[mode], **configured_profile}
    panel_raw = panel_override or config.get("panel_path")
    if not panel_raw:
        raise ValueError("Fit config requires panel_path or an explicit panel override")
    run_raw = run_dir or config.get("run_dir")
    if not run_raw:
        raise ValueError("Guarded fit requires an explicit immutable run_dir")
    train_start = str(config.get("train_start") or "2025-01-01")
    train_end = str(config.get("train_end") or "2026-03-20")
    holdout_start = str(config.get("holdout_start") or "2026-03-21")
    holdout_end = str(config.get("holdout_end") or "2026-05-31")
    if pd.Timestamp(train_end) >= pd.Timestamp(holdout_start):
        raise ValueError("train_end must be strictly before holdout_start")
    fixed_lambda_raw = config.get("fixed_lambda_channels_by_fit") or {}
    if not isinstance(fixed_lambda_raw, dict):
        raise ValueError("fixed_lambda_channels_by_fit must be a mapping of fit_key to channel names")
    fixed_lambda_channels_by_fit: dict[str, tuple[str, ...]] = {}
    fit_key_lookup = {
        token: fit_key
        for fit_key in EXPECTED_FIT_KEYS
        for token in (fit_key, _safe_fit_key(fit_key))
    }
    for fit_key_token, channels in fixed_lambda_raw.items():
        fit_key = fit_key_lookup.get(str(fit_key_token))
        if fit_key is None:
            raise ValueError(f"Unknown fixed-lambda fit_key: {fit_key_token}")
        if not isinstance(channels, list) or not channels or not all(
            isinstance(channel, str) and channel.strip() for channel in channels
        ):
            raise ValueError(f"Fixed-lambda channels must be a non-empty string list: {fit_key}")
        fixed_lambda_channels_by_fit[fit_key] = tuple(dict.fromkeys(channel.strip() for channel in channels))
    return GuardedFitSpec(
        config_path=config_path,
        panel_path=resolve_path(panel_raw),
        run_dir=resolve_path(run_raw),
        mode=mode,
        train_start=train_start,
        train_end=train_end,
        holdout_start=holdout_start,
        holdout_end=holdout_end,
        profile=profile,
        require_numpyro=bool(config.get("require_numpyro", True)),
        random_seed=int(config.get("random_seed", RANDOM_SEED)),
        thin_sample_threshold=int(config.get("thin_sample_threshold", 50)),
        vif_threshold=float(config.get("vif_threshold", 7.0)),
        fixed_lambda_channels_by_fit=fixed_lambda_channels_by_fit,
    )


def normalize_only_fits(only_fits: Iterable[str] | None) -> set[str] | None:
    normalized = _normalize_only_fits(only_fits)
    if normalized is None:
        return None
    unknown = sorted(normalized - set(EXPECTED_FIT_KEYS))
    if unknown:
        raise ValueError(f"Unknown --only-fit values: {unknown}")
    return normalized


def _configure_runtime_globals(spec: GuardedFitSpec) -> None:
    global MODE, MEDIA_RESPONSE_MODE
    MODE = spec.mode
    MEDIA_RESPONSE_MODE = "fixed" if spec.mode == "fast" else "tight"


def _validate_panel_frame(frame: pd.DataFrame, spec: GuardedFitSpec) -> dict[str, Any]:
    required = {
        "date",
        "geo_label",
        "network",
        "channel",
        "population_k",
        "unique_users",
        "orders_cnt",
        "turnover_total",
        *EXPECTED_TARGETS,
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Panel is missing fit-required columns: {missing}")
    frame["date"] = pd.to_datetime(frame["date"])
    duplicate_rows = int(frame.duplicated(["date", "geo_label", "network", "channel"]).sum())
    if duplicate_rows:
        raise ValueError(f"Panel contains {duplicate_rows} duplicate model-grain rows")
    rf_rows = int(frame["geo_label"].astype(str).str.upper().isin({"РФ", "РОССИЯ", "RUSSIA"}).sum())
    if rf_rows:
        raise ValueError("RF-like geos must be distributed upstream before fitting")
    train = frame[frame["date"].between(spec.train_start, spec.train_end, inclusive="both")]
    if train.empty:
        raise ValueError("Training cut is empty")
    target_na = int(train[EXPECTED_TARGETS].isna().sum().sum())
    target_nonpositive = int((train[EXPECTED_TARGETS] <= 0).sum().sum())
    if target_na or target_nonpositive:
        raise ValueError(
            f"Training targets fail DQ: missing_cells={target_na}, nonpositive_cells={target_nonpositive}"
        )
    control_variation: dict[str, dict[str, dict[str, float | int]]] = {}
    for control in ["usd_rub_close", "brent_usd_close", "ruonia_rate"]:
        if control not in train.columns:
            raise ValueError(f"Missing required temporal control: {control}")
    daily = train[["date", "usd_rub_close", "brent_usd_close", "ruonia_rate"]].drop_duplicates("date")
    for year, group in daily.groupby(daily["date"].dt.year):
        year_stats = {}
        for control in ["usd_rub_close", "brent_usd_close", "ruonia_rate"]:
            values = pd.to_numeric(group[control], errors="coerce")
            stats = {
                "days": int(len(values)),
                "missing_days": int(values.isna().sum()),
                "unique_values": int(values.nunique(dropna=True)),
                "std": float(values.std()),
            }
            if stats["missing_days"]:
                raise ValueError(f"Temporal control has missing dates: {year}/{control}")
            if stats["days"] >= 30 and (stats["unique_values"] < 2 or stats["std"] <= 1e-12):
                raise ValueError(f"Temporal control is constant in modeled year: {year}/{control}")
            year_stats[control] = stats
        control_variation[str(int(year))] = year_stats
    return {
        "rows": int(len(frame)),
        "train_rows": int(len(train)),
        "date_min": frame["date"].min().date().isoformat(),
        "date_max": frame["date"].max().date().isoformat(),
        "geos": int(frame["geo_label"].nunique()),
        "duplicate_grain_rows": duplicate_rows,
        "target_na_cells_train": target_na,
        "target_nonpositive_cells_train": target_nonpositive,
        "control_variation_by_year": control_variation,
    }


def _rebuild_media_groups(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, set[str]]]:
    out = frame.copy()
    grouped_inputs_by_segment: dict[str, set[str]] = {}
    for group_column in DERIVED_MEDIA_GROUP_COLS:
        out[group_column] = 0.0
    for segment, groups in MEDIA_GROUPING_CONFIG.items():
        network, channel = segment.split("/", 1)
        segment_mask = out["network"].eq(network) & out["channel"].eq(channel)
        grouped_inputs: set[str] = set()
        for group_column, input_columns in groups.items():
            available = [column for column in input_columns if column in out.columns]
            if available:
                out.loc[segment_mask, group_column] = out.loc[segment_mask, available].sum(axis=1)
            grouped_inputs.update(available)
        grouped_inputs_by_segment[segment] = grouped_inputs
    return out, grouped_inputs_by_segment


def _prepare_training_panel(
    spec: GuardedFitSpec,
) -> tuple[pd.DataFrame, list[str], list[str], dict[str, Any]]:
    global panel, SPEND_ACTIVE_BASE, MEDIA_GROUP_INPUTS_BY_SEGMENT
    if not spec.panel_path.exists():
        raise FileNotFoundError(f"Fit panel does not exist: {spec.panel_path}")
    full = pd.read_parquet(spec.panel_path)
    full["date"] = pd.to_datetime(full["date"])
    preflight = _validate_panel_frame(full, spec)
    train = full[full["date"].between(spec.train_start, spec.train_end, inclusive="both")].copy()

    anomaly_columns = [column for column in train.columns if column.endswith("_anomaly_flag")]
    anomaly_mask = train[anomaly_columns].any(axis=1) if anomaly_columns else pd.Series(False, index=train.index)
    rows_before_anomaly = len(train)
    train = train.loc[~anomaly_mask].copy()
    thin = (
        train.groupby(["geo_label", "network", "channel"])["unique_users"].median()
        < spec.thin_sample_threshold
    )
    thin_keys = thin[thin].index
    thin_mask = train.set_index(["geo_label", "network", "channel"]).index.isin(thin_keys)
    rows_before_thin = len(train)
    train = train.loc[~thin_mask].copy()

    raw_spend = sorted(
        column
        for column in train.columns
        if column.startswith("spend_")
        and not column.endswith("_pc")
        and column not in DERIVED_MEDIA_GROUP_COLS
    )
    force_include = [INDOOR_MEDIA_COL] if INDOOR_MEDIA_COL in raw_spend else []
    SPEND_ACTIVE_BASE = list(
        dict.fromkeys([column for column in raw_spend if train[column].gt(0).mean() > 0.02] + force_include)
    )
    train, MEDIA_GROUP_INPUTS_BY_SEGMENT = _rebuild_media_groups(train)
    panel = train

    control_columns = [column for column in BASE_CONTROL_COLS if column in train.columns]
    dropped_vif: list[dict[str, Any]] = []
    iteration = 0
    while True:
        iteration += 1
        candidates = [
            column
            for column in control_columns
            if column not in {"population_k", "n_stores"} and train[column].std() > 0
        ]
        values = compute_vif_for_cols(train, candidates)
        valid = [(column, value) for column, value in values if value is not None and np.isfinite(value)]
        if not valid:
            break
        worst_column, worst_vif = max(valid, key=lambda item: item[1])
        if worst_vif <= spec.vif_threshold:
            break
        dropped_vif.append({"feature": worst_column, "vif": float(worst_vif), "iteration": iteration})
        control_columns.remove(worst_column)
        if iteration > 50:
            raise RuntimeError("VIF auto-drop exceeded 50 iterations")

    top_n_geos = spec.profile.get("top_n_geos")
    if top_n_geos is not None:
        geo_spend = train.groupby("geo_label")[SPEND_ACTIVE_BASE].sum().sum(axis=1).sort_values(ascending=False)
        top_geos = geo_spend.head(int(top_n_geos)).index
        model_panel = train[train["geo_label"].isin(top_geos)].copy()
    else:
        model_panel = train.copy()
    spend_active = list(dict.fromkeys(SPEND_ACTIVE_BASE + DERIVED_MEDIA_GROUP_COLS))
    audit = {
        "preflight": preflight,
        "rows_removed_anomaly": int(rows_before_anomaly - rows_before_thin),
        "rows_removed_thin": int(rows_before_thin - len(train)),
        "thin_geo_segment_keys": int(len(thin_keys)),
        "raw_spend_columns": raw_spend,
        "spend_active_base": SPEND_ACTIVE_BASE,
        "spend_active_model_universe": spend_active,
        "controls_final": control_columns,
        "dropped_vif": dropped_vif,
        "model_rows": int(len(model_panel)),
        "model_geos": int(model_panel["geo_label"].nunique()),
    }
    return model_panel, spend_active, control_columns, audit


def _build_empirical_priors(
    model_panel: pd.DataFrame,
    controls: list[str],
    spec: GuardedFitSpec,
) -> dict[str, Any]:
    priors: dict[str, Any] = {}
    decay_grid = np.arange(0.05, 0.96, float(spec.profile["decay_grid_step"]))
    concentration = 12.0
    for segment in EXPECTED_SEGMENTS:
        network, channel = segment.split("/", 1)
        segment_frame = model_panel[
            model_panel["network"].eq(network) & model_panel["channel"].eq(channel)
        ].copy()
        if len(segment_frame) < 200:
            raise ValueError(f"Segment has fewer than 200 training rows: {segment}")
        priors[segment] = {}
        spend_columns = get_spend_cols_for_segment(network, channel)
        spend_columns = [
            column
            for column in spend_columns
            if column in segment_frame and segment_frame[column].gt(0).mean() > 0.02
        ]
        for target in EXPECTED_TARGETS:
            priors[segment][target] = {}
            for spend_column in spend_columns:
                if segment_frame[spend_column].std() == 0:
                    continue
                decay, beta_fe, se_fe = grid_search_adstock_fe(
                    segment_frame,
                    target,
                    spend_column,
                    controls,
                    decay_grid,
                )
                priors[segment][target][spend_column] = {
                    "decay": round(float(decay), 3),
                    "alpha_a": round(max(decay * concentration, 0.5), 2),
                    "alpha_b": round(max((1 - decay) * concentration, 0.5), 2),
                    "beta_FE": round(float(beta_fe), 6),
                    "beta_SE": round(float(se_fe), 6) if se_fe is not None and np.isfinite(se_fe) else None,
                    "beta_sigma": round(max(abs(beta_fe) * 3 if np.isfinite(beta_fe) else 0, 0.5), 4),
                }
    return priors


def _safe_fit_key(fit_key: str) -> str:
    return fit_key.replace("/", "_").replace("::", "__")


def _fit_tuple(fit_key: str) -> tuple[str, str, str]:
    segment, target = fit_key.split("::", 1)
    network, channel = segment.split("/", 1)
    return network, channel, target


def _fit_contract_payload(
    spec: GuardedFitSpec,
    fit_key: str,
    segment_frame: pd.DataFrame,
    coords: dict[str, Any],
    data: dict[str, Any],
    model: pm.Model,
    *,
    empirical_priors_sha256: str,
) -> dict[str, Any]:
    row_keys = segment_frame[["date", "geo_label", "network", "channel"]].copy()
    row_keys["date"] = pd.to_datetime(row_keys["date"]).dt.date.astype(str)
    initial_point = model.initial_point()
    initial_hashes = {name: _array_sha256(value) for name, value in sorted(initial_point.items())}
    try:
        initial_logp = float(model.compile_logp()(initial_point))
    except Exception as exc:
        raise RuntimeError(f"Could not compile deterministic initial logp for {fit_key}") from exc
    prior_array_names = [
        "a_pars",
        "b_pars",
        "alpha_caps",
        "alpha_prior_mean",
        "lam_a_pars",
        "lam_b_pars",
        "lam_caps",
        "lam_prior_mean",
        "beta_prior_medians",
        "beta_prior_log_sd",
        "beta_geo_sd_prior",
        "beta_tier_sd_prior",
        "sigma_tier_prior",
    ]
    payload = {
        "schema_version": FIT_CONTRACT_SCHEMA_VERSION,
        "fit_runtime_version": FIT_RUNTIME_VERSION,
        "fit_key": fit_key,
        "panel_path": str(spec.panel_path),
        "panel_sha256": sha256_file(spec.panel_path),
        "config_path": str(spec.config_path),
        "config_sha256": sha256_file(spec.config_path),
        "fit_code_sha256": sha256_file(Path(__file__).resolve()),
        "empirical_priors_sha256": empirical_priors_sha256,
        "train_start": spec.train_start,
        "train_end": spec.train_end,
        "mode": spec.mode,
        "sampler": {
            "engine": "numpyro" if spec.profile.get("use_jax") else "pymc",
            "require_numpyro": spec.require_numpyro,
            "random_seed": spec.random_seed,
            "draws": int(spec.profile["draws"]),
            "tune": int(spec.profile["tune"]),
            "chains": int(spec.profile["chains"]),
            "target_accept": float(spec.profile["target_accept"]),
        },
        "row_order_sha256": _sha256_bytes(row_keys.to_csv(index=False).encode("utf-8")),
        "n_obs": int(data["n_obs"]),
        "coords": {name: [str(value) for value in values] for name, values in coords.items()},
        "arrays_sha256": {
            "Y": _array_sha256(data["Y"]),
            "X_spend": _array_sha256(data["X_spend"]),
            "X_lagged": _array_sha256(data["X_lagged"]),
            "X_ctrl": _array_sha256(data["X_ctrl"]),
            "geo_idx": _array_sha256(data["geo_idx"]),
            "obs_tier_idx": _array_sha256(data["obs_tier_idx"]),
            "geo_tier_idx": _array_sha256(data["geo_tier_idx"]),
            "ctrl_mean": _array_sha256(data["ctrl_mean"]),
            "ctrl_std": _array_sha256(data["ctrl_std"]),
            "x_scale": _array_sha256(data["x_scale"]),
            "x_scale_global": _array_sha256(data["x_scale_global"]),
            "x_scale_geo": _array_sha256(data["x_scale_geo"]),
            "fixed_lambda_channel_idx": _array_sha256(data["fixed_lambda_channel_idx"]),
            "free_lambda_channel_idx": _array_sha256(data["free_lambda_channel_idx"]),
        },
        "prior_arrays_sha256": {name: _array_sha256(data.get(name)) for name in prior_array_names},
        "model": {
            "free_rvs": [variable.name for variable in model.free_RVs],
            "observed_rvs": [variable.name for variable in model.observed_RVs],
            "deterministics": [variable.name for variable in model.deterministics],
            "initial_point_sha256": initial_hashes,
            "initial_logp": initial_logp,
            "beta_structure": data["beta_structure"],
            "baseline_structure": data["baseline_structure"],
            "error_structure": data["error_structure"],
            "media_response_mode": data["media_response_mode"],
            "media_scaling_mode": data["media_scaling_mode"],
            "fixed_lambda_channels": data["fixed_lambda_channels"],
            "l_max": int(data["l_max"]),
        },
    }
    payload["fit_contract_sha256"] = _canonical_json_sha256(payload)
    return payload


def _write_or_validate_contract(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != payload:
            raise ValueError(f"Existing fit contract differs from current deterministic design: {path}")
        return
    write_json(path, payload)


def _run_identity(spec: GuardedFitSpec) -> dict[str, Any]:
    identity = {
        "schema_version": "1.0.0",
        "fit_runtime_version": FIT_RUNTIME_VERSION,
        "panel_path": str(spec.panel_path),
        "panel_sha256": sha256_file(spec.panel_path),
        "config_path": str(spec.config_path),
        "config_sha256": sha256_file(spec.config_path),
        "fit_code_sha256": sha256_file(Path(__file__).resolve()),
        "mode": spec.mode,
        "train_start": spec.train_start,
        "train_end": spec.train_end,
        "profile": spec.profile,
        "random_seed": spec.random_seed,
        "fixed_lambda_channels_by_fit": {
            fit_key: list(channels)
            for fit_key, channels in sorted(spec.fixed_lambda_channels_by_fit.items())
        },
        "expected_fit_keys": EXPECTED_FIT_KEYS,
    }
    identity["run_identity_sha256"] = _canonical_json_sha256(identity)
    return identity


def _ensure_run_identity(spec: GuardedFitSpec, *, resume: bool, prepare_only: bool) -> dict[str, Any]:
    identity_path = spec.run_dir / "run_identity.json"
    identity = _run_identity(spec)
    if spec.run_dir.exists() and any(spec.run_dir.iterdir()):
        if not identity_path.exists():
            raise FileExistsError(f"Non-empty run folder has no guarded identity: {spec.run_dir}")
        existing = json.loads(identity_path.read_text(encoding="utf-8"))
        if existing != identity:
            raise ValueError("Immutable run identity differs; create a new run directory")
        if not (resume or prepare_only):
            raise FileExistsError("Run directory already exists; use --resume only with the same immutable identity")
    else:
        spec.run_dir.mkdir(parents=True, exist_ok=True)
        write_json(identity_path, identity)
    return identity


def _run_config_payload(
    spec: GuardedFitSpec,
    audit: dict[str, Any],
    controls: list[str],
    spend_active: list[str],
) -> dict[str, Any]:
    return {
        "mode": spec.mode,
        "run_label": spec.run_dir.parent.name,
        "run_variant": spec.run_dir.name.removeprefix(f"{spec.mode}_"),
        "panel_path": str(spec.panel_path),
        "panel_sha256": sha256_file(spec.panel_path),
        "train_start": spec.train_start,
        "train_end": spec.train_end,
        "holdout_start": spec.holdout_start,
        "holdout_end": spec.holdout_end,
        "cfg": spec.profile,
        "random_seed": spec.random_seed,
        "require_numpyro": spec.require_numpyro,
        "fixed_lambda_channels_by_fit": {
            fit_key: list(channels)
            for fit_key, channels in sorted(spec.fixed_lambda_channels_by_fit.items())
        },
        "fit_runtime_version": FIT_RUNTIME_VERSION,
        "fit_code_sha256": sha256_file(Path(__file__).resolve()),
        "config_path": str(spec.config_path),
        "config_sha256": sha256_file(spec.config_path),
        "center_media_response": CENTER_MEDIA_RESPONSE,
        "media_response_mode": MEDIA_RESPONSE_MODE,
        "media_scaling_mode": MEDIA_SCALING_MODE,
        "media_geo_scale_min_nz": MEDIA_GEO_SCALE_MIN_NZ,
        "media_geo_scale_full_nz": MEDIA_GEO_SCALE_FULL_NZ,
        "media_geo_scale_ratio_floor": MEDIA_GEO_SCALE_RATIO_FLOOR,
        "media_geo_scale_ratio_ceil": MEDIA_GEO_SCALE_RATIO_CEIL,
        "media_tier_count": MEDIA_TIER_COUNT,
        "media_tier_scale_min_nz": MEDIA_TIER_SCALE_MIN_NZ,
        "media_tier_scale_full_nz": MEDIA_TIER_SCALE_FULL_NZ,
        "media_tier_scale_ratio_floor": MEDIA_TIER_SCALE_RATIO_FLOOR,
        "media_tier_scale_ratio_ceil": MEDIA_TIER_SCALE_RATIO_CEIL,
        "market_size_tier_col": MARKET_SIZE_TIER_COL,
        "market_size_tier_fallback": MARKET_SIZE_TIER_FALLBACK,
        "baseline_structure": BASELINE_STRUCTURE,
        "error_structure": ERROR_STRUCTURE,
        "beta_structure_by_target": BETA_STRUCTURE_BY_TARGET,
        "beta_structure_overrides_by_fit": [
            {
                "network": network,
                "channel": channel,
                "target": target,
                "fit_key": f"{network}/{channel}::{target}",
                "beta_structure": structure,
            }
            for (network, channel, target), structure in BETA_STRUCTURE_OVERRIDES_BY_FIT.items()
        ],
        "beta_tier_pooled_channels_by_fit": [
            {
                "network": network,
                "channel": channel,
                "target": target,
                "fit_key": f"{network}/{channel}::{target}",
                "pooled_channels": sorted(channels),
            }
            for (network, channel, target), channels in BETA_TIER_POOLED_CHANNELS_BY_FIT.items()
        ],
        "postfit_roas_response_basis": "raw_saturation",
        "media_grouping_enabled": True,
        "media_grouping_source": "digital_and_ooh_total_policy_2026_05_16",
        "media_grouping_config": MEDIA_GROUPING_CONFIG,
        "force_include_spend_cols": [INDOOR_MEDIA_COL],
        "spend_active_base": SPEND_ACTIVE_BASE,
        "spend_active_model_universe": spend_active,
        "ctrl_cols": controls,
        "expected_fit_keys": EXPECTED_FIT_KEYS,
        "training_audit": audit,
        "tc5_offline_specific_policy": {
            "enabled": TC5_OFFLINE_SPECIFIC_POLICY_ENABLED,
            "segment": "/".join(TC5_OFFLINE_POLICY_SEGMENT),
            "targets": sorted(TC5_OFFLINE_POLICY_TARGETS),
            "excluded_media_cols": sorted(TC5_OFFLINE_EXCLUDED_MEDIA_COLS),
            "tv_grouping_enabled": False,
        },
    }


def _prepare_one_fit(
    spec: GuardedFitSpec,
    model_panel: pd.DataFrame,
    spend_active: list[str],
    controls: list[str],
    priors: dict[str, Any],
    fit_key: str,
    empirical_priors_sha256: str,
) -> dict[str, Any]:
    network, channel, target = _fit_tuple(fit_key)
    segment_frame, coords, data = build_single_target_data(
        model_panel,
        network,
        channel,
        target,
        spend_active,
        controls,
        priors,
        l_max=int(spec.profile["l_max"]),
    )
    if data is None:
        raise ValueError(f"Fit design is unavailable or degenerate: {fit_key}")
    channel_names = [column.removeprefix("spend_") for column in data["spend_active"]]
    fixed_lambda_channels = list(spec.fixed_lambda_channels_by_fit.get(fit_key, ()))
    unknown_fixed_channels = sorted(set(fixed_lambda_channels) - set(channel_names))
    if unknown_fixed_channels:
        raise ValueError(f"Fixed-lambda channels are absent from {fit_key}: {unknown_fixed_channels}")
    fixed_lambda_idx = np.asarray(
        [index for index, name in enumerate(channel_names) if name in fixed_lambda_channels],
        dtype=int,
    )
    free_lambda_idx = np.asarray(
        [index for index, name in enumerate(channel_names) if name not in fixed_lambda_channels],
        dtype=int,
    )
    data["fixed_lambda_channels"] = fixed_lambda_channels
    data["fixed_lambda_channel_idx"] = fixed_lambda_idx
    data["free_lambda_channel_idx"] = free_lambda_idx
    if fixed_lambda_channels:
        coords["lambda_free_channel"] = [channel_names[index] for index in free_lambda_idx]
    model = build_pymc_model(coords, data)
    contract = _fit_contract_payload(
        spec,
        fit_key,
        segment_frame,
        coords,
        data,
        model,
        empirical_priors_sha256=empirical_priors_sha256,
    )
    safe = _safe_fit_key(fit_key)
    _write_or_validate_contract(spec.run_dir / f"fit_contract_{safe}.json", contract)
    transform = {
        "schema_version": "1.0.0",
        "fit_key": fit_key,
        "fit_contract_sha256": contract["fit_contract_sha256"],
        "channels": [column.removeprefix("spend_") for column in data["spend_active"]],
        "spend_active": data["spend_active"],
        "controls": data["ctrl_active"],
        "geos": data["geos"],
        "market_size_tiers": data["market_size_tiers"],
        "geo_tier_idx": np.asarray(data["geo_tier_idx"], dtype=int).tolist(),
        "ctrl_mean": np.asarray(data["ctrl_mean"], dtype=float).tolist(),
        "ctrl_std": np.asarray(data["ctrl_std"], dtype=float).tolist(),
        "x_scale_geo": np.asarray(data["x_scale_geo"], dtype=float).tolist(),
        "x_scale_global": np.asarray(data["x_scale_global"], dtype=float).tolist(),
        "y_scale": float(data["y_scale"]),
        "y_offset": float(data["y_offset"]),
        "y_scaling": data["y_scaling"],
        "l_max": int(data["l_max"]),
        "beta_structure": data["beta_structure"],
        "baseline_structure": data["baseline_structure"],
        "error_structure": data["error_structure"],
        "media_response_mode": data["media_response_mode"],
        "media_scaling_mode": data["media_scaling_mode"],
        "fixed_lambda_channels": fixed_lambda_channels,
    }
    transform["transform_sha256"] = _canonical_json_sha256(transform)
    transform_path = spec.run_dir / f"fit_transform_{safe}.json"
    if transform_path.exists():
        if json.loads(transform_path.read_text(encoding="utf-8")) != transform:
            raise ValueError(f"Existing fit transform differs from immutable design: {fit_key}")
    else:
        write_json(transform_path, transform)
    data["media_scaling_audit"].to_csv(
        spec.run_dir / f"media_scaling_audit_{safe}.csv",
        index=False,
    )
    if data.get("prior_tier_audit") is not None:
        data["prior_tier_audit"].to_csv(spec.run_dir / f"prior_tier_audit_{safe}.csv", index=False)
    return {
        "fit_key": fit_key,
        "safe": safe,
        "segment_frame": segment_frame,
        "coords": coords,
        "data": data,
        "model": model,
        "contract": contract,
    }


def _cached_posterior(
    spec: GuardedFitSpec,
    prepared: dict[str, Any],
) -> tuple[Any, dict[str, Any]] | None:
    safe = prepared["safe"]
    posterior_path = spec.run_dir / f"posterior_{safe}.nc"
    state_path = spec.run_dir / f"fit_state_{safe}.json"
    if not posterior_path.exists() and not state_path.exists():
        return None
    if not posterior_path.exists() or not state_path.exists():
        raise ValueError(f"Incomplete cached fit state for {prepared['fit_key']}")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("fit_contract_sha256") != prepared["contract"]["fit_contract_sha256"]:
        raise ValueError(f"Cached posterior contract mismatch for {prepared['fit_key']}")
    if state.get("posterior_sha256") != sha256_file(posterior_path):
        raise ValueError(f"Cached posterior hash mismatch for {prepared['fit_key']}")
    diagnostics_path = spec.run_dir / f"diagnostics_{safe}.json"
    diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8")) if diagnostics_path.exists() else {}
    return az.from_netcdf(posterior_path), diagnostics


def _sample_fit_atomic(
    spec: GuardedFitSpec,
    prepared: dict[str, Any],
) -> tuple[Any, dict[str, Any]]:
    safe = prepared["safe"]
    final_path = spec.run_dir / f"posterior_{safe}.nc"
    partial_path = spec.run_dir / f".posterior_{safe}.partial.nc"
    if final_path.exists():
        raise FileExistsError(f"Refusing to overwrite posterior: {final_path}")
    if partial_path.exists():
        raise FileExistsError(f"Stale partial posterior requires manual review: {partial_path}")
    idata, diagnostics = fit_with_diagnostics(
        prepared["model"],
        int(spec.profile["draws"]),
        int(spec.profile["tune"]),
        int(spec.profile["chains"]),
        float(spec.profile["target_accept"]),
        use_jax=bool(spec.profile.get("use_jax", True)),
        require_numpyro=spec.require_numpyro,
        random_seed=spec.random_seed,
    )
    try:
        az.to_netcdf(idata, partial_path)
        os.replace(partial_path, final_path)
    finally:
        partial_path.unlink(missing_ok=True)
    diagnostics_path = spec.run_dir / f"diagnostics_{safe}.json"
    write_json(diagnostics_path, diagnostics)
    state = {
        "schema_version": "1.0.0",
        "status": "complete",
        "fit_key": prepared["fit_key"],
        "fit_contract_sha256": prepared["contract"]["fit_contract_sha256"],
        "posterior_file": final_path.name,
        "posterior_sha256": sha256_file(final_path),
        "diagnostics_file": diagnostics_path.name,
        "diagnostics_sha256": sha256_file(diagnostics_path),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_json(spec.run_dir / f"fit_state_{safe}.json", state)
    return idata, diagnostics


def _adequacy_metrics(idata: Any, model: pm.Model, data: dict[str, Any], fit_key: str) -> dict[str, Any]:
    with model:
        ppc = pm.sample_posterior_predictive(
            idata,
            random_seed=RANDOM_SEED,
            progressbar=False,
            return_inferencedata=True,
        )
    if "y_obs" not in ppc.posterior_predictive:
        raise ValueError(f"Posterior predictive has no y_obs for {fit_key}")
    observed = np.asarray(data["Y"], dtype=float)
    predicted = ppc.posterior_predictive["y_obs"].stack(sample=("chain", "draw"))
    obs_dims = [dimension for dimension in predicted.dims if dimension != "sample"]
    if len(obs_dims) != 1:
        raise ValueError(f"Unexpected posterior predictive dimensions for {fit_key}: {predicted.dims}")
    samples = predicted.transpose(obs_dims[0], "sample").values
    if samples.shape[0] != observed.shape[0]:
        raise ValueError(f"Posterior predictive row mismatch for {fit_key}")
    residuals = observed[:, None] - samples
    tss = np.sum((observed - observed.mean()) ** 2)
    r2_draws = 1.0 - np.sum(residuals**2, axis=0) / (tss + 1e-10)
    mean_prediction = samples.mean(axis=1)
    r2_point = 1.0 - np.sum((observed - mean_prediction) ** 2) / (tss + 1e-10)
    low = np.percentile(samples, 5, axis=1)
    high = np.percentile(samples, 95, axis=1)
    return {
        "target": data["target"],
        "r2_mean": float(r2_draws.mean()),
        "r2_p5": float(np.percentile(r2_draws, 5)),
        "r2_p95": float(np.percentile(r2_draws, 95)),
        "r2_point": float(r2_point),
        "r2_method": "posterior_predictive_sse_by_draw",
        "coverage_90": float(((observed >= low) & (observed <= high)).mean()),
    }


def _prior_provenance_rows(fit_key: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    segment, target = fit_key.split("::", 1)
    rows: list[dict[str, Any]] = []
    for index, spend_column in enumerate(data["spend_active"]):
        rows.append(
            {
                "fit_key": fit_key,
                "segment": segment,
                "target": target,
                "channel": spend_column.removeprefix("spend_"),
                "spend_col": spend_column,
                "beta_structure": data["beta_structure"],
                "baseline_structure": data["baseline_structure"],
                "error_structure": data["error_structure"],
                "market_size_tier_source": data["market_size_tier_source"],
                "market_size_tiers": "|".join(data["market_size_tiers"]),
                "media_scaling_mode": data["media_scaling_mode"],
                "x_scale_global": float(data["x_scale_global"][index]),
                "x_scale_typical": float(data["x_scale"][index]),
                "x_scaled_typical": float(data["x_scaled_typical"][index]),
                "beta_prior_type": data["beta_prior_type"][index],
                "beta_prior_source": data["beta_prior_source"][index],
                "beta_prior_fallback_reason": data["beta_prior_fallback_reason"][index],
                "beta_prior_median": float(data["beta_prior_medians"][index]),
                "beta_prior_log_sd": float(data["beta_prior_log_sd"][index]),
                "fe_beta_raw": float(data["beta_fe_raw"][index])
                if np.isfinite(data["beta_fe_raw"][index])
                else np.nan,
                "fe_se_raw": float(data["beta_fe_se_raw"][index])
                if np.isfinite(data["beta_fe_se_raw"][index])
                else np.nan,
                "alpha_prior_mean": float(data["alpha_prior_mean"][index]),
                "lam_prior_mean": float(data["lam_prior_mean"][index]),
                "y_scale": float(data["y_scale"]),
                "y_scaling": data["y_scaling"],
            }
        )
    return rows


def _write_postfit_artifacts(
    spec: GuardedFitSpec,
    model_panel: pd.DataFrame,
    spend_active: list[str],
    controls: list[str],
    priors: dict[str, Any],
    empirical_priors_sha256: str,
) -> dict[str, Any]:
    adequacy: dict[str, Any] = {}
    diagnostics_rows: list[dict[str, Any]] = []
    roas_rows: list[dict[str, Any]] = []
    roas_rub_rows: list[dict[str, Any]] = []
    reliability_rows: list[dict[str, Any]] = []
    target_effect_rows: list[dict[str, Any]] = []
    prior_provenance_rows: list[dict[str, Any]] = []
    contraction_rows: list[dict[str, Any]] = []

    for fit_key in EXPECTED_FIT_KEYS:
        prepared = _prepare_one_fit(
            spec,
            model_panel,
            spend_active,
            controls,
            priors,
            fit_key,
            empirical_priors_sha256,
        )
        cached = _cached_posterior(spec, prepared)
        if cached is None:
            raise ValueError(f"Cannot build complete post-fit artifacts; posterior is missing: {fit_key}")
        idata, diagnostics = cached
        data = prepared["data"]
        segment_frame = prepared["segment_frame"]
        model = prepared["model"]
        segment, target = fit_key.split("::", 1)
        diagnostics_rows.append({"fit_key": fit_key, "segment": segment, "target": target, **diagnostics})
        fit_adequacy = _adequacy_metrics(idata, model, data, fit_key)
        adequacy[fit_key] = fit_adequacy

        scaled_roas = compute_roas_distribution(idata, data, n_samples=200)
        marginal_roas = compute_mroas(idata, data)
        rub_roas = compute_revenue_roas(idata, data, segment_frame, n_samples=200) if target == "turnover_per_user" else None
        effects, totals, raw_spend = compute_target_effect_distribution(
            idata,
            data,
            segment_frame,
            n_samples=200,
        )
        for index, spend_column in enumerate(data["spend_active"]):
            channel = spend_column.removeprefix("spend_")
            reliability = compute_channel_reliability(segment_frame, spend_column)
            quality_flags = build_roas_quality_flags(
                diagnostics,
                fit_adequacy,
                reliability["reliability_flags"],
                target,
            )
            common = {
                "segment": segment,
                "target": target,
                "channel": channel,
                "fit_status": diagnostics.get("status"),
                "fit_rhat_max": diagnostics.get("rhat_max"),
                "fit_ess_bulk_min": diagnostics.get("ess_bulk_min"),
                "fit_ess_per_draw": diagnostics.get("ess_per_draw"),
                "r2_ppc_mean": fit_adequacy.get("r2_mean"),
                "r2_point": fit_adequacy.get("r2_point"),
                **reliability,
                "quality_flags": quality_flags,
            }
            roas_rows.append(
                {
                    **common,
                    "roas_p5_scaled": float(np.percentile(scaled_roas[index], 5)),
                    "roas_median_scaled": float(np.percentile(scaled_roas[index], 50)),
                    "roas_p95_scaled": float(np.percentile(scaled_roas[index], 95)),
                    "mroas_scaled": float(marginal_roas[index]),
                    "spend_total_raw_M": float(segment_frame[spend_column].sum() / 1e6),
                    "roas_use_case": "reportable" if quality_flags == "OK" else "diagnostic_only",
                }
            )
            reliability_rows.append(
                {
                    "segment": segment,
                    "target": target,
                    "channel": channel,
                    "spend_total_raw_M": float(segment_frame[spend_column].sum() / 1e6),
                    **reliability,
                }
            )
            if rub_roas is not None:
                roas_rub_rows.append(
                    {
                        **common,
                        "roas_rub_p5": float(np.percentile(rub_roas[index], 5)),
                        "roas_rub_median": float(np.percentile(rub_roas[index], 50)),
                        "roas_rub_p95": float(np.percentile(rub_roas[index], 95)),
                        "spend_total_M": float(segment_frame[spend_column].sum() / 1e6),
                        "postfit_roas_response_basis": "raw_saturation",
                        "roas_use_case": "reportable" if quality_flags == "OK" else "diagnostic_only",
                    }
                )
            if target == "turnover_per_user":
                effect_unit, total_unit = "rub_per_user", "incremental_turnover_rub"
            elif target == "orders_per_user":
                effect_unit, total_unit = "orders_per_user", "incremental_orders"
            else:
                effect_unit, total_unit = "rub_per_order", "turnover_bridge_from_avg_basket_rub"
            target_effect_rows.append(
                {
                    **common,
                    "effect_unit": effect_unit,
                    "effect_p5": float(np.percentile(effects[index], 5)),
                    "effect_median": float(np.percentile(effects[index], 50)),
                    "effect_p95": float(np.percentile(effects[index], 95)),
                    "total_effect_unit": total_unit,
                    "total_effect_p5": float(np.percentile(totals[index], 5)),
                    "total_effect_median": float(np.percentile(totals[index], 50)),
                    "total_effect_p95": float(np.percentile(totals[index], 95)),
                    "spend_total_M": float(raw_spend[index] / 1e6),
                    "use_case": "reportable" if quality_flags == "OK" else "diagnostic_only",
                }
            )
        prior_provenance_rows.extend(_prior_provenance_rows(fit_key, data))
        contraction = prior_posterior_contraction(
            idata,
            model,
            var_names=("beta",),
            samples=500 if spec.mode in {"pilot", "production"} else 100,
        )
        if not contraction.empty:
            contraction.insert(0, "fit_key", fit_key)
            contraction.insert(1, "segment", segment)
            contraction.insert(2, "target", target)
            if "channel" not in contraction.columns:
                raise ValueError(f"Prior contraction output has no channel dimension for {fit_key}")
            contraction_rows.extend(contraction.to_dict("records"))

    pd.DataFrame(diagnostics_rows).sort_values(["segment", "target"]).to_csv(
        spec.run_dir / "diagnostics_summary.csv",
        index=False,
    )
    write_json(spec.run_dir / "adequacy.json", adequacy)
    pd.DataFrame(roas_rows).to_csv(spec.run_dir / "roas_all_fits.csv", index=False)
    pd.DataFrame(roas_rub_rows).to_csv(spec.run_dir / "roas_rub_all_fits.csv", index=False)
    pd.DataFrame(reliability_rows).to_csv(spec.run_dir / "channel_reliability.csv", index=False)
    pd.DataFrame(target_effect_rows).to_csv(spec.run_dir / "target_effects_all_fits.csv", index=False)
    pd.DataFrame(prior_provenance_rows).to_csv(spec.run_dir / "prior_provenance_all_fits.csv", index=False)
    pd.DataFrame(contraction_rows).to_csv(spec.run_dir / "prior_posterior_contraction.csv", index=False)
    return {
        "fits": len(EXPECTED_FIT_KEYS),
        "diagnostics_rows": len(diagnostics_rows),
        "roas_rows": len(roas_rows),
        "roas_rub_rows": len(roas_rub_rows),
        "reliability_rows": len(reliability_rows),
        "target_effect_rows": len(target_effect_rows),
        "contraction_rows": len(contraction_rows),
    }


def run_guarded_fit(
    config_path: str | Path,
    *,
    run_dir: str | Path | None = None,
    panel_override: str | Path | None = None,
    mode_override: str | None = None,
    prepare_only: bool = False,
    resume: bool = False,
    only_fits: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Prepare or sample an immutable 12-fit MMM run with hash-bound resume."""
    started = time.time()
    spec = load_guarded_fit_spec(
        config_path,
        run_dir=run_dir,
        panel_override=panel_override,
        mode_override=mode_override,
    )
    _configure_runtime_globals(spec)
    identity = _ensure_run_identity(spec, resume=resume, prepare_only=prepare_only)
    selected = normalize_only_fits(only_fits)
    model_panel, spend_active, controls, training_audit = _prepare_training_panel(spec)
    priors = _build_empirical_priors(model_panel, controls, spec)
    priors_path = spec.run_dir / "empirical_priors.json"
    priors_payload = json.dumps(priors, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if priors_path.exists() and priors_path.read_text(encoding="utf-8") != priors_payload:
        raise ValueError("Empirical priors changed inside an immutable run")
    if not priors_path.exists():
        priors_path.write_text(priors_payload, encoding="utf-8")
    empirical_priors_sha256 = sha256_file(priors_path)
    write_json(spec.run_dir / "media_grouping_config.json", MEDIA_GROUPING_CONFIG)
    pd.DataFrame(
        [
            {
                "channel": column.removeprefix("spend_"),
                "pct_nonzero": float(model_panel[column].gt(0).mean() * 100),
                "total_M": float(model_panel[column].sum() / 1e6),
                "active_geos": int(model_panel.loc[model_panel[column].gt(0), "geo_label"].nunique()),
            }
            for column in SPEND_ACTIVE_BASE
        ]
    ).to_csv(spec.run_dir / "spend_audit.csv", index=False)
    run_config = _run_config_payload(spec, training_audit, controls, spend_active)
    run_config_path = spec.run_dir / "run_config.json"
    if run_config_path.exists() and json.loads(run_config_path.read_text(encoding="utf-8")) != run_config:
        raise ValueError("run_config.json changed inside an immutable run")
    write_json(run_config_path, run_config)

    prepared_contracts: dict[str, str] = {}
    sampled_fits: list[str] = []
    reused_fits: list[str] = []
    row_index_frames: list[pd.DataFrame] = []
    control_scaler_rows: list[dict[str, Any]] = []
    exact_media_scale_rows: list[dict[str, Any]] = []
    for fit_key in EXPECTED_FIT_KEYS:
        prepared = _prepare_one_fit(
            spec,
            model_panel,
            spend_active,
            controls,
            priors,
            fit_key,
            empirical_priors_sha256,
        )
        prepared_contracts[fit_key] = prepared["contract"]["fit_contract_sha256"]
        row_index = prepared["segment_frame"][["date", "geo_label", "network", "channel"]].copy()
        row_index.insert(0, "fit_key", fit_key)
        row_index.insert(1, "row_position", np.arange(len(row_index), dtype=int))
        row_index_frames.append(row_index)
        for index, control in enumerate(prepared["data"]["ctrl_active"]):
            control_scaler_rows.append(
                {
                    "fit_key": fit_key,
                    "control": control,
                    "mean": float(prepared["data"]["ctrl_mean"][index]),
                    "std": float(prepared["data"]["ctrl_std"][index]),
                    "fit_contract_sha256": prepared["contract"]["fit_contract_sha256"],
                }
            )
        for geo_index, geo in enumerate(prepared["data"]["geos"]):
            tier_index = int(prepared["data"]["geo_tier_idx"][geo_index])
            tier = prepared["data"]["market_size_tiers"][tier_index]
            for channel_index, spend_column in enumerate(prepared["data"]["spend_active"]):
                exact_media_scale_rows.append(
                    {
                        "fit_key": fit_key,
                        "geo_label": geo,
                        "market_size_tier": tier,
                        "channel": spend_column.removeprefix("spend_"),
                        "spend_col": spend_column,
                        "x_scale": float(prepared["data"]["x_scale_geo"][geo_index, channel_index]),
                        "fit_contract_sha256": prepared["contract"]["fit_contract_sha256"],
                    }
                )
        if prepare_only:
            continue
        requested = selected is None or fit_key in selected
        cached = _cached_posterior(spec, prepared)
        if cached is not None:
            if not resume:
                raise FileExistsError(f"Posterior already exists; rerun requires --resume: {fit_key}")
            reused_fits.append(fit_key)
            continue
        if not requested:
            continue
        _sample_fit_atomic(spec, prepared)
        sampled_fits.append(fit_key)

    row_index_output = pd.concat(row_index_frames, ignore_index=True)
    row_index_path = spec.run_dir / "fit_design_row_index.parquet"
    if row_index_path.exists():
        existing_row_index = pd.read_parquet(row_index_path)
        if not existing_row_index.equals(row_index_output):
            raise ValueError("fit_design_row_index changed inside an immutable run")
    else:
        row_index_output.to_parquet(row_index_path, index=False, compression="snappy")
    control_scalers = pd.DataFrame(control_scaler_rows).sort_values(["fit_key", "control"]).reset_index(drop=True)
    control_scalers_path = spec.run_dir / "fit_design_control_scalers.csv"
    if control_scalers_path.exists():
        _validate_csv_roundtrip(control_scalers_path, control_scalers, "fit_design_control_scalers")
    else:
        control_scalers.to_csv(control_scalers_path, index=False)
    exact_media_scales = pd.DataFrame(exact_media_scale_rows).sort_values(
        ["fit_key", "geo_label", "channel"]
    ).reset_index(drop=True)
    exact_media_scales_path = spec.run_dir / "fit_design_media_scales_exact.csv"
    if exact_media_scales_path.exists():
        _validate_csv_roundtrip(exact_media_scales_path, exact_media_scales, "fit_design_media_scales_exact")
    else:
        exact_media_scales.to_csv(exact_media_scales_path, index=False)

    posterior_files = sorted(spec.run_dir.glob("posterior_*.nc"))
    complete = len(posterior_files) == len(EXPECTED_FIT_KEYS)
    postfit = None
    if not prepare_only and complete:
        postfit = _write_postfit_artifacts(
            spec,
            model_panel,
            spend_active,
            controls,
            priors,
            empirical_priors_sha256,
        )
    status = "prepared" if prepare_only else "fit_complete" if complete else "fit_partial"
    execution_card = {
        "schema_version": "1.0.0",
        "status": status,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "sampling_performed": bool(sampled_fits),
        "run_dir": str(spec.run_dir),
        "run_identity_sha256": identity["run_identity_sha256"],
        "panel_sha256": sha256_file(spec.panel_path),
        "config_sha256": sha256_file(spec.config_path),
        "fit_code_sha256": sha256_file(Path(__file__).resolve()),
        "mode": spec.mode,
        "selected_fit_keys": sorted(selected) if selected is not None else EXPECTED_FIT_KEYS,
        "prepared_fit_contracts": prepared_contracts,
        "sampled_fit_keys": sampled_fits,
        "reused_fit_keys": reused_fits,
        "posterior_files_n": len(posterior_files),
        "expected_posterior_files_n": len(EXPECTED_FIT_KEYS),
        "postfit": postfit,
        "duration_seconds": round(time.time() - started, 3),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "pymc": _package_version("pymc"),
            "numpyro": _package_version("numpyro"),
            "arviz": _package_version("arviz"),
            "pytensor": _package_version("pytensor"),
        },
    }
    write_json(spec.run_dir / "fit_execution_card.json", execution_card)
    return execution_card
