"""Predictive OOT and independent historical-response replay contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import arviz as az
import numpy as np
import pandas as pd

from .fit import _make_geo_lagged_tensor_np, _safe_fit_key
from .io import read_json, resolve_path, write_json
from .model_package import sha256_file


VALIDATION_SCHEMA_VERSION = "1.0.0"
OOT_INPUT_COVERAGE_SCHEMA_VERSION = "1.0.0"
TARGET_COLUMNS = {"turnover_per_user", "orders_per_user", "avg_basket"}
TARGET_DERIVED_COLUMNS = {
    "turnover_total",
    "orders_cnt",
    "unique_users",
    "turnover_per_user_raw",
    "orders_per_user_raw",
}


@dataclass(frozen=True)
class OOTSplit:
    train_end: str
    oot_start: str
    oot_end: str
    pre_roll_days: int = 14
    min_scored_days: int = 28
    development_seen: bool = False


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_oot_split(split: OOTSplit) -> dict[str, Any]:
    train_end = pd.Timestamp(split.train_end)
    oot_start = pd.Timestamp(split.oot_start)
    oot_end = pd.Timestamp(split.oot_end)
    if train_end >= oot_start:
        raise ValueError("OOT leakage: train_end must be strictly before oot_start")
    if oot_end < oot_start:
        raise ValueError("oot_end must be on or after oot_start")
    scored_days = int((oot_end - oot_start).days + 1)
    if split.pre_roll_days < 14:
        raise ValueError("Predictive OOT requires at least 14 pre-roll days")
    if scored_days < split.min_scored_days:
        raise ValueError(
            f"Predictive OOT requires at least {split.min_scored_days} scored days; got {scored_days}"
        )
    return {
        **asdict(split),
        "scored_days": scored_days,
        "pre_roll_start": (oot_start - pd.Timedelta(days=split.pre_roll_days)).date().isoformat(),
        "date_overlap_days": 0,
        "activation_evidence_allowed": not split.development_seen,
        "evidence_role": "shadow_development_seen" if split.development_seen else "sealed_activation_oot",
    }


def required_oot_inputs(run_dir: str | Path, fit_keys: list[str]) -> list[dict[str, str]]:
    """Derive every target, media and control input required by the frozen fits."""
    run_dir = resolve_path(run_dir)
    required: set[tuple[str, str, str]] = set()
    for fit_key in fit_keys:
        transform = _load_transform(run_dir, fit_key)
        segment, target = fit_key.split("::", 1)
        required.add(("targets", segment, target))
        for column in transform.get("spend_active") or []:
            required.add(("own_media", segment, str(column)))
        for column in transform.get("controls") or []:
            kind = "competitor_media" if str(column).startswith("compet_") else "controls"
            required.add((kind, segment, str(column)))
    return [
        {"input_kind": kind, "segment": segment, "name": name}
        for kind, segment, name in sorted(required)
    ]


def evaluate_oot_input_coverage(
    manifest: dict[str, Any],
    split: OOTSplit,
    required_inputs: list[dict[str, str]],
    *,
    panel_sha256: str | None,
    manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Fail closed when an OOT zero may actually be an incomplete source delivery."""
    split_manifest = validate_oot_split(split)
    reason_codes: list[str] = []
    if str(manifest.get("schema_version") or "") != OOT_INPUT_COVERAGE_SCHEMA_VERSION:
        reason_codes.append("UNSUPPORTED_COVERAGE_MANIFEST_SCHEMA")
    if str(manifest.get("status") or "") != "complete":
        reason_codes.append("COVERAGE_MANIFEST_STATUS_INCOMPLETE")
    if manifest.get("missing_delivery_is_zero") is not False:
        reason_codes.append("MISSING_DELIVERY_ZERO_POLICY_NOT_FAIL_CLOSED")
    if not panel_sha256 or manifest.get("panel_sha256") != panel_sha256:
        reason_codes.append("COVERAGE_PANEL_HASH_MISMATCH")
    if str(manifest.get("oot_start") or "") != split.oot_start:
        reason_codes.append("COVERAGE_OOT_START_MISMATCH")
    if str(manifest.get("oot_end") or "") != split.oot_end:
        reason_codes.append("COVERAGE_OOT_END_MISMATCH")

    coverage_rows = manifest.get("coverage_rows") or []
    if not isinstance(coverage_rows, list):
        coverage_rows = []
        reason_codes.append("INVALID_COVERAGE_ROWS")
    index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in coverage_rows:
        if not isinstance(row, dict):
            continue
        key = (
            str(row.get("input_kind") or ""),
            str(row.get("segment") or ""),
            str(row.get("name") or ""),
        )
        if all(key):
            index[key] = row

    pre_roll_start = pd.Timestamp(split_manifest["pre_roll_start"])
    oot_start = pd.Timestamp(split.oot_start)
    oot_end = pd.Timestamp(split.oot_end)
    missing_requirements: list[dict[str, str]] = []
    invalid_requirements: list[dict[str, Any]] = []
    for required in required_inputs:
        kind = str(required["input_kind"])
        segment = str(required["segment"])
        name = str(required["name"])
        row = index.get((kind, segment, name)) or index.get((kind, "__ALL__", name))
        if row is None:
            missing_requirements.append(required)
            continue
        row_reasons: list[str] = []
        if str(row.get("status") or "") != "complete":
            row_reasons.append("SOURCE_STATUS_NOT_COMPLETE")
        coverage_start = pd.to_datetime(row.get("coverage_start"), errors="coerce")
        coverage_end = pd.to_datetime(row.get("coverage_end"), errors="coerce")
        required_start = oot_start if kind == "targets" else pre_roll_start
        if pd.isna(coverage_start) or coverage_start > required_start:
            row_reasons.append("COVERAGE_START_TOO_LATE")
        if pd.isna(coverage_end) or coverage_end < oot_end:
            row_reasons.append("COVERAGE_END_TOO_EARLY")
        for field in ["missing_dates_n", "missing_rows_n"]:
            value = pd.to_numeric(row.get(field), errors="coerce")
            if pd.isna(value) or float(value) != 0.0:
                row_reasons.append(f"{field.upper()}_NONZERO_OR_MISSING")
        if not str(row.get("source_sha256") or ""):
            row_reasons.append("MISSING_SOURCE_HASH")
        if row_reasons:
            invalid_requirements.append({**required, "reason_codes": row_reasons})

    if missing_requirements:
        reason_codes.append("MISSING_REQUIRED_INPUT_COVERAGE")
    if invalid_requirements:
        reason_codes.append("INVALID_REQUIRED_INPUT_COVERAGE")
    reason_codes = list(dict.fromkeys(reason_codes))
    return {
        "schema_version": OOT_INPUT_COVERAGE_SCHEMA_VERSION,
        "status": "passed" if not reason_codes else "unavailable",
        "reason_codes": reason_codes or ["OK"],
        "manifest_status": manifest.get("status"),
        "manifest_sha256": manifest_sha256,
        "panel_sha256": panel_sha256,
        "required_inputs_n": len(required_inputs),
        "coverage_rows_n": len(coverage_rows),
        "missing_requirements": missing_requirements,
        "invalid_requirements": invalid_requirements,
        "source_blockers": list(manifest.get("blockers") or []),
    }


def _load_transform(run_dir: Path, fit_key: str) -> dict[str, Any]:
    path = run_dir / f"fit_transform_{_safe_fit_key(fit_key)}.json"
    transform = read_json(path)
    if not isinstance(transform, dict):
        raise FileNotFoundError(f"Missing frozen fit transform: {path}")
    expected_hash = transform.get("transform_sha256")
    payload = dict(transform)
    payload.pop("transform_sha256", None)
    if expected_hash != _canonical_hash(payload):
        raise ValueError(f"Frozen fit transform hash mismatch: {fit_key}")
    return transform


def _posterior_samples(run_dir: Path, fit_key: str, max_draws: int, seed: int) -> dict[str, Any]:
    path = run_dir / f"posterior_{_safe_fit_key(fit_key)}.nc"
    if not path.exists():
        raise FileNotFoundError(f"Missing posterior for OOT: {path}")
    idata = az.from_netcdf(path)
    posterior = idata.posterior
    sample_index = posterior.stack(sample=("chain", "draw"))["sample"]
    n_total = int(sample_index.size)
    selected = np.sort(
        np.random.RandomState(seed).choice(n_total, size=min(max_draws, n_total), replace=False)
    )

    def stack(name: str) -> tuple[np.ndarray | None, list[str]]:
        if name not in posterior:
            return None, []
        data = posterior[name].stack(sample=("chain", "draw"))
        non_sample = [dimension for dimension in data.dims if dimension != "sample"]
        values = data.transpose(*non_sample, "sample").values[..., selected]
        return values, non_sample

    arrays = {name: stack(name) for name in ["alpha", "lam", "beta", "tau_g", "gamma", "sigma", "sigma_tier"]}
    sample_ids = [f"{int(sample_index.values[index][0])}:{int(sample_index.values[index][1])}" for index in selected]
    return {"arrays": arrays, "sample_ids": sample_ids, "posterior_sha256": sha256_file(path)}


def build_oot_feature_snapshot(
    panel: pd.DataFrame,
    transform: dict[str, Any],
    split: OOTSplit,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    segment, target = transform["fit_key"].split("::", 1)
    network, channel = segment.split("/", 1)
    frame = panel.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    pre_roll_start = pd.Timestamp(split.oot_start) - pd.Timedelta(days=split.pre_roll_days)
    end = pd.Timestamp(split.oot_end)
    segment_rows = frame[
        frame["network"].eq(network)
        & frame["channel"].eq(channel)
        & frame["date"].between(pre_roll_start, end, inclusive="both")
    ].copy()
    if segment_rows.empty:
        raise ValueError(f"No OOT rows for {transform['fit_key']}")
    frozen_geos = set(transform["geos"])
    unknown_mask = ~segment_rows["geo_label"].astype(str).isin(frozen_geos)
    unknown_geos = sorted(segment_rows.loc[unknown_mask, "geo_label"].astype(str).unique())
    if unknown_geos:
        if not split.development_seen:
            raise ValueError(f"OOT contains unknown geos for frozen fit {transform['fit_key']}: {unknown_geos}")
        segment_rows = segment_rows.loc[~unknown_mask].copy()
    scored_rows_all = int(
        frame[
            frame["network"].eq(network)
            & frame["channel"].eq(channel)
            & frame["date"].between(split.oot_start, split.oot_end, inclusive="both")
        ].shape[0]
    )
    scored_rows_known = int(
        segment_rows["date"].between(split.oot_start, split.oot_end, inclusive="both").sum()
    )
    if scored_rows_known == 0:
        raise ValueError(f"No frozen-geo OOT rows for {transform['fit_key']}")
    required_features = [
        "date",
        "geo_label",
        "network",
        "channel",
        "population_k",
        "market_size_tier",
        *transform["spend_active"],
        *transform["controls"],
    ]
    missing = sorted(set(required_features) - set(segment_rows.columns))
    if missing:
        raise ValueError(f"OOT feature snapshot is missing frozen columns: {missing}")
    snapshot = segment_rows[required_features].copy()
    forbidden = (TARGET_COLUMNS | TARGET_DERIVED_COLUMNS) & set(snapshot.columns)
    if forbidden:
        raise ValueError(f"Target leakage in OOT feature snapshot: {sorted(forbidden)}")
    snapshot = snapshot.sort_values(["geo_label", "date"]).reset_index(drop=True)
    snapshot.attrs["geo_coverage"] = {
        "unknown_geos_excluded_n": len(unknown_geos),
        "unknown_geos_excluded": unknown_geos,
        "scored_rows_all": scored_rows_all,
        "scored_rows_known": scored_rows_known,
        "known_geo_row_coverage": scored_rows_known / max(scored_rows_all, 1),
        "development_only_filter_applied": bool(unknown_geos),
    }
    outcomes = segment_rows[["date", "geo_label", target]].copy()
    outcomes = outcomes[outcomes["date"].between(split.oot_start, split.oot_end, inclusive="both")]
    outcomes = outcomes.sort_values(["geo_label", "date"]).reset_index(drop=True)
    if len(outcomes) != int(snapshot["date"].between(split.oot_start, split.oot_end, inclusive="both").sum()):
        raise ValueError("Silent OOT row loss between frozen feature snapshot and outcomes")
    return snapshot, outcomes


def _score_fit_snapshot(
    snapshot: pd.DataFrame,
    transform: dict[str, Any],
    posterior: dict[str, Any],
    split: OOTSplit,
    *,
    seed: int,
) -> tuple[pd.DataFrame, np.ndarray]:
    geos = list(transform["geos"])
    channels = list(transform["spend_active"])
    controls = list(transform["controls"])
    geo_map = {geo: index for index, geo in enumerate(geos)}
    frame = snapshot.sort_values(["geo_label", "date"]).reset_index(drop=True).copy()
    geo_idx = frame["geo_label"].map(geo_map)
    if geo_idx.isna().any():
        raise ValueError("Unknown geo reached frozen OOT scorer")
    geo_idx_values = geo_idx.astype(int).to_numpy()
    population = np.maximum(pd.to_numeric(frame["population_k"], errors="raise").to_numpy(float), 1e-3)
    spend_raw = frame[channels].to_numpy(float)
    spend_pc = spend_raw / population[:, None]
    x_scale_geo = np.asarray(transform["x_scale_geo"], dtype=float)
    x_scaled = spend_pc / np.maximum(x_scale_geo[geo_idx_values], 1e-8)
    x_lagged = _make_geo_lagged_tensor_np(x_scaled, geo_idx_values, int(transform["l_max"]))
    if controls:
        control_raw = frame[controls].to_numpy(float)
        control_scaled = (
            control_raw - np.asarray(transform["ctrl_mean"], dtype=float)
        ) / np.maximum(np.asarray(transform["ctrl_std"], dtype=float), 1e-8)
    else:
        control_scaled = np.zeros((len(frame), 0), dtype=float)
    scored_mask = frame["date"].between(split.oot_start, split.oot_end, inclusive="both").to_numpy()
    tier_by_geo = np.asarray(transform["geo_tier_idx"], dtype=int)
    obs_tier = tier_by_geo[geo_idx_values]

    arrays = posterior["arrays"]
    alpha, _ = arrays["alpha"]
    lam, _ = arrays["lam"]
    beta, beta_dims = arrays["beta"]
    tau_g, _ = arrays["tau_g"]
    gamma, _ = arrays["gamma"]
    sigma, _ = arrays["sigma"]
    sigma_tier, _ = arrays["sigma_tier"]
    if alpha is None or lam is None or beta is None or tau_g is None:
        raise ValueError(f"Posterior lacks full-target OOT variables for {transform['fit_key']}")
    draws_n = alpha.shape[-1]
    predictions = np.zeros((int(scored_mask.sum()), draws_n), dtype=float)
    rng = np.random.RandomState(seed)
    for draw in range(draws_n):
        weights = alpha[:, draw][None, :] ** np.arange(int(transform["l_max"]) + 1)[:, None]
        weights = weights / weights.sum(axis=0, keepdims=True)
        x_adstock = (weights[:, None, :] * x_lagged).sum(axis=0)
        x_sat = np.tanh(lam[:, draw][None, :] * x_adstock / 2.0)
        if "geo_label" in beta_dims:
            beta_obs = beta[:, geo_idx_values, draw].T
        elif "market_size_tier" in beta_dims:
            beta_obs = beta[:, obs_tier, draw].T
        else:
            beta_obs = np.broadcast_to(beta[:, draw][None, :], x_sat.shape)
        mu = tau_g[geo_idx_values, draw] + np.sum(beta_obs * x_sat, axis=1)
        if gamma is not None and control_scaled.shape[1]:
            mu = mu + control_scaled @ gamma[:, draw]
        if sigma_tier is not None:
            sigma_obs = sigma_tier[obs_tier, draw]
        elif sigma is not None:
            sigma_obs = np.broadcast_to(float(np.asarray(sigma[..., draw]).reshape(-1)[0]), len(mu))
        else:
            raise ValueError(f"Posterior lacks sigma for {transform['fit_key']}")
        y_scaled = rng.normal(mu, sigma_obs)
        if transform["y_scaling"] == "zscore":
            y = y_scaled * float(transform["y_scale"]) + float(transform["y_offset"])
        else:
            y = y_scaled * float(transform["y_scale"])
        predictions[:, draw] = y[scored_mask]
    keys = frame.loc[scored_mask, ["date", "geo_label", "market_size_tier"]].reset_index(drop=True)
    result = keys.copy()
    result["fit_key"] = transform["fit_key"]
    result["p05"] = np.percentile(predictions, 5, axis=1)
    result["p10"] = np.percentile(predictions, 10, axis=1)
    result["p50"] = np.percentile(predictions, 50, axis=1)
    result["p90"] = np.percentile(predictions, 90, axis=1)
    result["p95"] = np.percentile(predictions, 95, axis=1)
    result["mean"] = predictions.mean(axis=1)
    return result, predictions


def _empirical_crps(samples: np.ndarray, actual: np.ndarray) -> np.ndarray:
    first = np.mean(np.abs(samples - actual[:, None]), axis=1)
    ordered = np.sort(samples, axis=1)
    n = ordered.shape[1]
    coefficients = 2 * np.arange(1, n + 1) - n - 1
    pairwise_half = np.sum(ordered * coefficients[None, :], axis=1) / (n * n)
    return first - pairwise_half


def evaluate_predictive_oot(
    predictions: pd.DataFrame,
    draw_matrix: np.ndarray,
    outcomes: pd.DataFrame,
    training_outcomes: pd.DataFrame,
    *,
    target: str,
) -> dict[str, float | int | str]:
    merged = predictions.merge(outcomes, on=["date", "geo_label"], how="left", validate="one_to_one")
    if merged[target].isna().any() or len(merged) != len(predictions):
        raise ValueError("OOT outcome join lost or duplicated rows")
    actual = merged[target].to_numpy(float)
    point = merged["mean"].to_numpy(float)
    train = training_outcomes.sort_values(["geo_label", "date"]).copy()
    naive_scale = train.groupby("geo_label")[target].diff().abs().dropna().mean()
    if not np.isfinite(naive_scale) or naive_scale <= 0:
        raise ValueError("Cannot calculate MASE from training outcomes")
    last_train = train.groupby("geo_label")[target].last()
    naive = merged["geo_label"].map(last_train)
    if naive.isna().any():
        raise ValueError("OOT geo has no frozen naive training baseline")
    crps = _empirical_crps(draw_matrix, actual)
    naive_mae = float(np.mean(np.abs(actual - naive.to_numpy(float))))
    return {
        "rows": int(len(merged)),
        "target": target,
        "mae": float(np.mean(np.abs(actual - point))),
        "mase": float(np.mean(np.abs(actual - point)) / naive_scale),
        "crps": float(np.mean(crps)),
        "crps_skill_vs_last_value": float(1.0 - np.mean(crps) / max(naive_mae, 1e-12)),
        "normalized_abs_bias": float(abs(np.mean(point - actual)) / max(np.mean(np.abs(actual)), 1e-12)),
        "coverage_90": float(((actual >= merged["p05"]) & (actual <= merged["p95"])).mean()),
    }


def classify_oot_metrics(metrics: dict[str, Any]) -> str:
    primary = (
        float(metrics["mase"]) <= 1.00
        and float(metrics["crps_skill_vs_last_value"]) >= 0.0
        and float(metrics["normalized_abs_bias"]) <= 0.10
        and 0.80 <= float(metrics["coverage_90"]) <= 0.98
    )
    if primary:
        return "primary"
    caution = (
        float(metrics["mase"]) <= 1.10
        and float(metrics["crps_skill_vs_last_value"]) >= -0.05
        and float(metrics["normalized_abs_bias"]) <= 0.15
        and 0.75 <= float(metrics["coverage_90"]) <= 0.99
    )
    return "caution" if caution else "diagnostic"


def build_validation_binding(run_dir: str | Path, extra_files: Iterable[str | Path]) -> dict[str, Any]:
    run_dir = resolve_path(run_dir)
    manifest = read_json(run_dir / "model_manifest.json", {}) or {}
    run_config = read_json(run_dir / "run_config.json", {}) or {}
    panel_path = resolve_path(run_config.get("panel_path")) if run_config.get("panel_path") else None
    files = [resolve_path(path) for path in extra_files]
    binding = {
        "run_dir": str(run_dir),
        "package_input_fingerprint": manifest.get("package_input_fingerprint"),
        "model_manifest_sha256": sha256_file(run_dir / "model_manifest.json")
        if (run_dir / "model_manifest.json").exists()
        else None,
        "run_config_sha256": sha256_file(run_dir / "run_config.json"),
        "panel_sha256": sha256_file(panel_path) if panel_path and panel_path.exists() else None,
        "fit_code_sha256": run_config.get("fit_code_sha256"),
        "files_sha256": {str(path): sha256_file(path) for path in files},
    }
    binding["binding_sha256"] = _canonical_hash(binding)
    return binding


def run_predictive_oot(
    run_dir: str | Path,
    panel_path: str | Path,
    coverage_manifest_path: str | Path,
    split: OOTSplit,
    *,
    max_draws: int = 300,
    seed: int = 10042,
    write: bool = False,
) -> dict[str, Any]:
    run_dir = resolve_path(run_dir)
    panel_path = resolve_path(panel_path)
    coverage_manifest_path = resolve_path(coverage_manifest_path)
    split_manifest = validate_oot_split(split)
    config = read_json(run_dir / "run_config.json", {}) or {}
    fit_keys = list(config.get("expected_fit_keys") or [])
    if len(fit_keys) != 12:
        raise ValueError(f"Predictive OOT requires exactly 12 fit contracts; got {len(fit_keys)}")
    output_dir = run_dir / "validation" / "oot"
    coverage_manifest = read_json(coverage_manifest_path, {}) or {}
    coverage = evaluate_oot_input_coverage(
        coverage_manifest,
        split,
        required_oot_inputs(run_dir, fit_keys),
        panel_sha256=sha256_file(panel_path),
        manifest_sha256=sha256_file(coverage_manifest_path),
    )
    if coverage["status"] != "passed":
        verdict = {
            "schema_version": VALIDATION_SCHEMA_VERSION,
            "status": "unavailable_input_coverage",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "activation_eligible": False,
            "split": split_manifest,
            "coverage": coverage,
            "fits_n": 0,
            "turnover_required_pass": False,
            "quality_counts": {},
            "metrics": [],
        }
        if write:
            output_dir.mkdir(parents=True, exist_ok=True)
            binding = build_validation_binding(run_dir, [coverage_manifest_path])
            verdict["binding"] = binding
            verdict["package_input_fingerprint"] = binding.get("package_input_fingerprint")
            write_json(run_dir / "oot_validation.json", verdict)
        return verdict

    panel = pd.read_parquet(panel_path)
    panel["date"] = pd.to_datetime(panel["date"])
    metric_rows: list[dict[str, Any]] = []
    prediction_frames: list[pd.DataFrame] = []
    feature_frames: list[pd.DataFrame] = []
    prediction_hashes: dict[str, str] = {}
    for fit_index, fit_key in enumerate(fit_keys):
        transform = _load_transform(run_dir, fit_key)
        snapshot, outcomes = build_oot_feature_snapshot(panel, transform, split)
        posterior = _posterior_samples(run_dir, fit_key, max_draws, seed + fit_index)
        predictions, draws = _score_fit_snapshot(
            snapshot,
            transform,
            posterior,
            split,
            seed=seed + 1000 + fit_index,
        )
        prediction_hashes[fit_key] = _canonical_hash(predictions.to_dict("records"))
        target = fit_key.split("::", 1)[1]
        segment = fit_key.split("::", 1)[0]
        network, channel = segment.split("/", 1)
        training_outcomes = panel[
            panel["network"].eq(network)
            & panel["channel"].eq(channel)
            & panel["date"].between(config["train_start"], config["train_end"], inclusive="both")
        ][["date", "geo_label", target]]
        metrics = evaluate_predictive_oot(
            predictions,
            draws,
            outcomes,
            training_outcomes,
            target=target,
        )
        verdict = classify_oot_metrics(metrics)
        geo_coverage = snapshot.attrs.get("geo_coverage") or {}
        metric_rows.append(
            {
                "fit_key": fit_key,
                "segment": segment,
                **metrics,
                "quality_status": verdict,
                "unknown_geos_excluded_n": int(geo_coverage.get("unknown_geos_excluded_n", 0)),
                "known_geo_row_coverage": float(geo_coverage.get("known_geo_row_coverage", 1.0)),
            }
        )
        prediction_frames.append(predictions)
        feature_copy = snapshot.copy()
        feature_copy.insert(0, "fit_key", fit_key)
        feature_frames.append(feature_copy)
    metrics_frame = pd.DataFrame(metric_rows)
    turnover = metrics_frame[metrics_frame["target"].eq("turnover_per_user")]
    turnover_required_pass = len(turnover) == 4 and turnover["quality_status"].isin(["primary", "caution"]).all()
    activation_eligible = bool(split_manifest["activation_evidence_allowed"] and turnover_required_pass)
    status = (
        "passed"
        if activation_eligible
        else "shadow_passed_not_activation_evidence"
        if split.development_seen and turnover_required_pass
        else "failed"
    )
    predictions_all = pd.concat(prediction_frames, ignore_index=True)
    features_all = pd.concat(feature_frames, ignore_index=True)
    verdict = {
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "status": status,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "activation_eligible": activation_eligible,
        "split": split_manifest,
        "fits_n": int(len(metrics_frame)),
        "turnover_required_pass": bool(turnover_required_pass),
        "quality_counts": metrics_frame["quality_status"].value_counts().to_dict(),
        "geo_coverage": {
            row["fit_key"]: {
                "unknown_geos_excluded_n": row["unknown_geos_excluded_n"],
                "known_geo_row_coverage": row["known_geo_row_coverage"],
            }
            for row in metric_rows
        },
        "prediction_hash_before_outcome_join": prediction_hashes,
        "metrics": metric_rows,
        "coverage": coverage,
    }
    if write:
        output_dir.mkdir(parents=True, exist_ok=True)
        write_json(output_dir / "split_manifest.json", split_manifest)
        features_all.to_parquet(output_dir / "feature_snapshot_without_targets.parquet", index=False)
        predictions_all.to_parquet(output_dir / "predictions_before_outcome_join.parquet", index=False)
        metrics_frame.to_csv(output_dir / "metrics.csv", index=False)
        binding = build_validation_binding(
            run_dir,
            [
                output_dir / "split_manifest.json",
                output_dir / "feature_snapshot_without_targets.parquet",
                output_dir / "predictions_before_outcome_join.parquet",
                output_dir / "metrics.csv",
                coverage_manifest_path,
            ],
        )
        verdict["binding"] = binding
        verdict["package_input_fingerprint"] = binding.get("package_input_fingerprint")
        write_json(run_dir / "oot_validation.json", verdict)
    return verdict


def _effect_tolerance(unit: str) -> float:
    if unit in {"incremental_turnover_rub", "turnover_bridge_from_avg_basket_rub"}:
        return 1.0
    if unit == "incremental_orders":
        return 1e-4
    return 1e-8


def select_historical_replay_draw_pairs(
    run_dir: str | Path,
    fit_keys: list[str],
    *,
    expected_draws: int = 64,
    seed: int = 10042,
) -> list[tuple[int, int]]:
    """Freeze one deterministic chain/draw subset shared by both replay producers."""
    if not fit_keys:
        raise ValueError("Historical replay requires at least one fit key")
    run_dir = resolve_path(run_dir)
    first_path = run_dir / f"posterior_{_safe_fit_key(fit_keys[0])}.nc"
    idata = az.from_netcdf(first_path)
    try:
        chain_values = [int(value) for value in idata.posterior.coords["chain"].values]
        draw_values = [int(value) for value in idata.posterior.coords["draw"].values]
    finally:
        if hasattr(idata, "close"):
            idata.close()
    available = [(chain, draw) for chain in chain_values for draw in draw_values]
    if len(available) < expected_draws:
        raise ValueError(
            f"Historical replay requires {expected_draws} posterior draws; only {len(available)} are available"
        )
    positions = np.sort(
        np.random.RandomState(seed).choice(len(available), size=expected_draws, replace=False)
    )
    pairs = [available[int(position)] for position in positions]
    for fit_key in fit_keys[1:]:
        idata = az.from_netcdf(run_dir / f"posterior_{_safe_fit_key(fit_key)}.nc")
        try:
            available_for_fit = {
                (int(chain), int(draw))
                for chain in idata.posterior.coords["chain"].values
                for draw in idata.posterior.coords["draw"].values
            }
        finally:
            if hasattr(idata, "close"):
                idata.close()
        missing = sorted(set(pairs) - available_for_fit)
        if missing:
            raise ValueError(f"Historical replay draw contract is unavailable for {fit_key}: {missing}")
    return pairs


def build_model_side_historical_replay_rows(
    run_dir: str | Path,
    panel: pd.DataFrame,
    row_index: pd.DataFrame,
    fit_keys: list[str],
    draw_pairs: list[tuple[int, int]],
) -> pd.DataFrame:
    """Reference producer using the fit-side lag tensor and exact frozen transforms."""
    run_dir = resolve_path(run_dir)
    panel_frame = panel.copy()
    panel_frame["date"] = pd.to_datetime(panel_frame["date"])
    index_frame = row_index.copy()
    index_frame["date"] = pd.to_datetime(index_frame["date"])
    keys = ["date", "geo_label", "network", "channel"]
    rows: list[dict[str, Any]] = []

    for fit_key in fit_keys:
        transform = _load_transform(run_dir, fit_key)
        fit_index = index_frame[index_frame["fit_key"].eq(fit_key)].copy()
        if fit_index.empty:
            raise ValueError(f"Model-side historical replay has no row index for {fit_key}")
        frame = fit_index.merge(panel_frame, on=keys, how="left", validate="one_to_one")
        frame = frame.sort_values("row_position").reset_index(drop=True)
        channels = list(transform["channels"])
        spend_columns = list(transform["spend_active"])
        required = {"population_k", "unique_users", "orders_cnt", *spend_columns}
        missing = sorted(required - set(frame.columns))
        if missing or frame[list(required)].isna().any().any():
            raise ValueError(f"Model-side historical replay lost frozen fit values for {fit_key}: {missing}")
        geos = list(transform["geos"])
        geo_map = {geo: index for index, geo in enumerate(geos)}
        geo_idx = frame["geo_label"].map(geo_map)
        if geo_idx.isna().any():
            raise ValueError(f"Model-side historical replay reached unknown geo for {fit_key}")
        geo_idx_values = geo_idx.to_numpy(dtype=int)
        population = np.maximum(frame["population_k"].to_numpy(float), 1e-3)
        spend_raw = frame[spend_columns].to_numpy(float)
        x_scale_geo = np.asarray(transform["x_scale_geo"], dtype=float)
        x_scaled = (spend_raw / population[:, None]) / np.maximum(x_scale_geo[geo_idx_values], 1e-8)
        x_lagged = _make_geo_lagged_tensor_np(x_scaled, geo_idx_values, int(transform["l_max"]))
        tier_by_geo = np.asarray(transform["geo_tier_idx"], dtype=int)
        obs_tier = tier_by_geo[geo_idx_values]
        target = fit_key.split("::", 1)[1]
        denominator = (
            frame["unique_users"].to_numpy(float)
            if target in {"turnover_per_user", "orders_per_user"}
            else frame["orders_cnt"].to_numpy(float)
        )
        effect_unit = {
            "turnover_per_user": "incremental_turnover_rub",
            "orders_per_user": "incremental_orders",
            "avg_basket": "turnover_bridge_from_avg_basket_rub",
        }[target]
        idata = az.from_netcdf(run_dir / f"posterior_{_safe_fit_key(fit_key)}.nc")
        try:
            posterior = idata.posterior
            for chain, draw in draw_pairs:
                alpha = posterior["alpha"].sel(chain=chain, draw=draw, channel=channels).values
                lam = posterior["lam"].sel(chain=chain, draw=draw, channel=channels).values
                beta_draw = posterior["beta"].sel(chain=chain, draw=draw, channel=channels)
                weights = alpha[None, :] ** np.arange(int(transform["l_max"]) + 1)[:, None]
                weights = weights / weights.sum(axis=0, keepdims=True)
                adstock = (weights[:, None, :] * x_lagged).sum(axis=0)
                saturation = np.tanh(lam[None, :] * adstock / 2.0)
                if "geo_label" in beta_draw.dims:
                    beta_matrix = beta_draw.sel(geo_label=geos).values
                    beta_obs = beta_matrix[:, geo_idx_values].T
                elif "market_size_tier" in beta_draw.dims:
                    tiers = list(transform["market_size_tiers"])
                    beta_matrix = beta_draw.sel(market_size_tier=tiers).values
                    beta_obs = beta_matrix[:, obs_tier].T
                else:
                    beta_obs = np.broadcast_to(beta_draw.values[None, :], saturation.shape)
                contribution = beta_obs * saturation * float(transform["y_scale"])
                for channel_index, (channel_name, spend_column) in enumerate(zip(channels, spend_columns)):
                    rows.append(
                        {
                            "fit_key": fit_key,
                            "channel": channel_name,
                            "chain": int(chain),
                            "draw": int(draw),
                            "row_id": "full_frozen_training_window",
                            "effect_value": float(np.sum(contribution[:, channel_index] * denominator)),
                            "effect_unit": effect_unit,
                            "spend_rub": float(frame[spend_column].sum()),
                            "producer": "fit_tensor_reference_v1",
                        }
                    )
        finally:
            if hasattr(idata, "close"):
                idata.close()
    return pd.DataFrame(rows)


def evaluate_historical_response_replay(
    reference: pd.DataFrame,
    replayed: pd.DataFrame,
    *,
    expected_fits: int = 12,
    expected_effects: int = 61,
    expected_draws: int = 64,
) -> dict[str, Any]:
    required = {
        "fit_key",
        "channel",
        "chain",
        "draw",
        "row_id",
        "effect_value",
        "effect_unit",
        "spend_rub",
        "producer",
    }
    for name, frame in [("reference", reference), ("replayed", replayed)]:
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ValueError(f"Historical replay {name} is missing columns: {missing}")
    reference_producers = set(reference["producer"].astype(str))
    replay_producers = set(replayed["producer"].astype(str))
    if reference_producers & replay_producers:
        raise ValueError("Historical replay is not independent: producer identities overlap")
    keys = ["fit_key", "channel", "chain", "draw", "row_id", "effect_unit"]
    if reference.duplicated(keys).any() or replayed.duplicated(keys).any():
        raise ValueError("Historical replay contains duplicate comparison keys")
    ref_keys = set(map(tuple, reference[keys].astype(str).to_numpy()))
    replay_keys = set(map(tuple, replayed[keys].astype(str).to_numpy()))
    if ref_keys != replay_keys:
        raise ValueError(
            f"Historical replay key mismatch: missing={len(ref_keys - replay_keys)}, extra={len(replay_keys - ref_keys)}"
        )
    merged = reference.merge(replayed, on=keys, suffixes=("_reference", "_replayed"), validate="one_to_one")
    fits_n = int(merged["fit_key"].nunique())
    effects_n = int(merged[["fit_key", "channel"]].drop_duplicates().shape[0])
    draws_n = int(merged[["chain", "draw"]].drop_duplicates().shape[0])
    if fits_n != expected_fits or effects_n != expected_effects or draws_n != expected_draws:
        raise ValueError(
            "Historical replay coverage mismatch: "
            f"fits={fits_n}/{expected_fits}, effects={effects_n}/{expected_effects}, draws={draws_n}/{expected_draws}"
        )
    spend_delta = np.abs(merged["spend_rub_reference"] - merged["spend_rub_replayed"])
    effect_delta = np.abs(merged["effect_value_reference"] - merged["effect_value_replayed"])
    tolerances = merged["effect_unit"].map(_effect_tolerance).to_numpy(float)
    effect_ok = np.isclose(
        merged["effect_value_reference"],
        merged["effect_value_replayed"],
        rtol=1e-8,
        atol=tolerances,
    )
    spend_ok = spend_delta <= 1e-6
    status = "passed" if bool(effect_ok.all() and spend_ok.all()) else "failed"
    return {
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "status": status,
        "fits_n": fits_n,
        "effects_n": effects_n,
        "draws_n": draws_n,
        "rows_n": int(len(merged)),
        "max_effect_abs_diff": float(effect_delta.max()) if len(effect_delta) else 0.0,
        "max_spend_abs_diff": float(spend_delta.max()) if len(spend_delta) else 0.0,
        "effect_mismatch_rows": int((~effect_ok).sum()),
        "spend_mismatch_rows": int((~spend_ok).sum()),
        "reference_producers": sorted(reference_producers),
        "replay_producers": sorted(replay_producers),
    }


def run_independent_historical_response_replay(
    run_dir: str | Path,
    panel_path: str | Path | None = None,
    *,
    expected_fits: int = 12,
    expected_effects: int = 61,
    expected_draws: int = 64,
    seed: int = 10042,
    write: bool = False,
) -> dict[str, Any]:
    """Generate and compare two independent historical channel-response producers."""
    run_dir = resolve_path(run_dir)
    config = read_json(run_dir / "run_config.json", {}) or {}
    fit_keys = list(config.get("expected_fit_keys") or [])
    if len(fit_keys) != expected_fits:
        raise ValueError(f"Historical replay requires {expected_fits} fit keys; got {len(fit_keys)}")
    panel_path = resolve_path(panel_path or config.get("panel_path"))
    if not panel_path.exists():
        raise FileNotFoundError(f"Historical replay panel is missing: {panel_path}")
    row_index_path = run_dir / "fit_design_row_index.parquet"
    if not row_index_path.exists():
        raise FileNotFoundError(f"Historical replay row index is missing: {row_index_path}")
    panel = pd.read_parquet(panel_path)
    row_index = pd.read_parquet(row_index_path)
    draw_pairs = select_historical_replay_draw_pairs(
        run_dir,
        fit_keys,
        expected_draws=expected_draws,
        seed=seed,
    )
    reference = build_model_side_historical_replay_rows(
        run_dir,
        panel,
        row_index,
        fit_keys,
        draw_pairs,
    )
    from .forecast_engine import ForecastEngine, build_historical_forecast_replay_rows

    engine = ForecastEngine.from_run_dir(run_dir, auto_export=False)
    replayed = build_historical_forecast_replay_rows(engine, panel, row_index, draw_pairs)
    verdict = evaluate_historical_response_replay(
        reference,
        replayed,
        expected_fits=expected_fits,
        expected_effects=expected_effects,
        expected_draws=expected_draws,
    )
    verdict.update(
        {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "panel_path": str(panel_path),
            "panel_sha256": sha256_file(panel_path),
            "row_index_sha256": sha256_file(row_index_path),
            "draw_selection": {
                "seed": seed,
                "pairs": [{"chain": chain, "draw": draw} for chain, draw in draw_pairs],
            },
            "producer_contract": {
                "reference": "fit-side lag tensor with exact frozen x_scale_geo",
                "replayed": "forecast serving geo loop with packaged media-scale lookup",
                "shared_inputs_only": ["posterior draws", "frozen row index", "panel", "draw selection"],
            },
        }
    )
    output_dir = run_dir / "validation" / "historical_replay"
    reference_path = output_dir / "reference_fit_tensor.parquet"
    replayed_path = output_dir / "replayed_forecast_geo_loop.parquet"
    if write:
        output_dir.mkdir(parents=True, exist_ok=True)
        reference.to_parquet(reference_path, index=False)
        replayed.to_parquet(replayed_path, index=False)
        verdict["binding"] = build_validation_binding(run_dir, [reference_path, replayed_path])
        verdict["package_input_fingerprint"] = verdict["binding"].get("package_input_fingerprint")
        write_json(output_dir / "metrics.json", verdict)
        write_json(run_dir / "historical_replay_validation.json", verdict)
    return verdict


def run_historical_response_replay_validation(
    run_dir: str | Path,
    reference_path: str | Path,
    replayed_path: str | Path,
    *,
    expected_fits: int = 12,
    expected_effects: int = 61,
    expected_draws: int = 64,
    write: bool = False,
) -> dict[str, Any]:
    run_dir = resolve_path(run_dir)
    reference_path = resolve_path(reference_path)
    replayed_path = resolve_path(replayed_path)
    reference = pd.read_parquet(reference_path) if reference_path.suffix == ".parquet" else pd.read_csv(reference_path)
    replayed = pd.read_parquet(replayed_path) if replayed_path.suffix == ".parquet" else pd.read_csv(replayed_path)
    verdict = evaluate_historical_response_replay(
        reference,
        replayed,
        expected_fits=expected_fits,
        expected_effects=expected_effects,
        expected_draws=expected_draws,
    )
    verdict["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    verdict["binding"] = build_validation_binding(run_dir, [reference_path, replayed_path])
    verdict["package_input_fingerprint"] = verdict["binding"].get("package_input_fingerprint")
    if write:
        output_dir = run_dir / "validation" / "historical_replay"
        output_dir.mkdir(parents=True, exist_ok=True)
        write_json(output_dir / "metrics.json", verdict)
        write_json(run_dir / "historical_replay_validation.json", verdict)
    return verdict
