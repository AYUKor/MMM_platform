"""Build a model package passport from an X5 MMM run folder.

The forecast and budget optimizer layers must not hard-code model assumptions.
They should read a model package generated from the model run itself:

- run_config.json is the configuration source of truth;
- posterior_*.nc files tell which fits are actually ready;
- diagnostics/adequacy/reliability artifacts define risk and allowed use.

This script supports both partial and completed runs. A run that only has
run_config.json can already produce a config-level passport; posterior-dependent
fields are marked as pending until the fit artifacts appear.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CODE_DIR = Path(__file__).resolve().parents[1]
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from mmm_core.io import project_root

PACKAGE_SCHEMA_VERSION = "0.4.0"
GATE_POLICY_VERSION = "1.2.0"
DEFAULT_TARGETS = ["turnover_per_user", "orders_per_user", "avg_basket"]
PENDING_ALLOWED_USE = "pending_fit"
POSTERIOR_RE = re.compile(r"^posterior_(?P<segment_token>.+)__(?P<target>[^/]+)\.nc$")
PACKAGE_EVIDENCE_FILES = [
    "run_config.json",
    "diagnostics_summary.csv",
    "channel_reliability.csv",
    "roas_all_fits.csv",
    "target_effects_all_fits.csv",
    "prior_posterior_contraction.csv",
    "adequacy.json",
    "model_gate_policy.json",
    "historical_campaign_support_bounds.csv",
    "source_geo_aliases.csv",
]
CAPABILITY_FIELDS = [
    "segment", "target", "channel", "fit_key", "configured", "posterior_status",
    "posterior_file", "diagnostics_status", "rhat_max", "ess_bulk_min", "n_divergences",
    "r2_mean", "r2_point", "coverage_90", "beta_structure", "tier_pooled_channels",
    "media_scaling_mode", "media_response_mode", "l_max", "channel_reliability_flags",
    "upstream_roas_use_case", "upstream_quality_flags", "active_days", "active_geos",
    "pct_nonzero_rows", "posterior_expanded_share", "low_contraction_share",
    "medium_contraction_share", "high_contraction_share", "unavailable_contraction_share",
    "fixed_saturation_shape", "gate_reason_codes", "risk_level",
    "allowed_use", "allowed_use_reason", "analysis_included", "forecast_use",
    "optimizer_use", "objective_role", "marketer_message",
]
RISK_FIELDS = [
    "scope", "segment", "target", "channel", "fit_key", "risk_type", "risk_level",
    "reason", "affects_forecast", "affects_optimizer",
]
GATE_FIELDS = [
    "segment", "target", "channel", "fit_key", "gate_policy_version",
    "fit_allowed_use", "upstream_roas_use_case", "upstream_quality_flags",
    "active_days", "active_geos", "pct_nonzero_rows", "contraction_rows_n",
    "posterior_expanded_share", "low_contraction_share", "medium_contraction_share",
    "high_contraction_share", "unavailable_contraction_share", "fixed_saturation_shape", "allowed_use",
    "forecast_policy", "optimizer_policy", "objective_role", "gate_reason_codes",
    "marketer_message",
]

DEFAULT_GATE_POLICY: dict[str, Any] = {
    "schema_version": GATE_POLICY_VERSION,
    "channel_evidence": {
        "diagnostic_active_days_lt": 30,
        "caution_active_days_lt": 90,
        "diagnostic_active_geos_lt": 5,
        "caution_active_geos_lt": 10,
        "diagnostic_nonzero_rows_pct_lt": 0.5,
        "caution_nonzero_rows_pct_lt": 2.0,
    },
    "fit_adequacy": {
        "diagnostic_ppc_r2_lt": 0.20,
        "caution_ppc_r2_lt": 0.30,
    },
    "contraction_evidence": {
        "low_contraction_lt": 0.20,
        "medium_contraction_lt": 0.50,
        "caution_limited_contraction_share_gte": 0.67,
    },
    "target_rules": {
        "orders_per_user": {
            "minimum_allowed_use": "diagnostic",
            "reason_code": "TARGET_POLICY_DIAGNOSTIC_ONLY",
        },
    },
    "optimizer_actions": {
        "primary": "optimize",
        "caution": "no_increase",
        "diagnostic": "fixed_at_plan",
        "unavailable": "blocked",
        PENDING_ALLOWED_USE: "blocked",
    },
    "forecast_actions": {
        "primary": "allowed",
        "caution": "allowed_with_warning",
        "diagnostic": "diagnostic_only",
        "unavailable": "blocked",
        PENDING_ALLOWED_USE: "blocked",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build X5 MMM model package passport from a run folder.")
    parser.add_argument("--run-dir", required=True, help="Path to MMM run folder with run_config.json.")
    parser.add_argument("--output-dir", default=None, help="Where to write package files. Defaults to run dir.")
    parser.add_argument("--write", action="store_true", help="Write model_manifest/capability/risk/posterior files.")
    parser.add_argument("--pretty", action="store_true", help="Print full manifest JSON to stdout.")
    return parser.parse_args()


def resolve(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate
    return project_root() / candidate


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_package_input_fingerprint(
    run_dir: Path,
    posterior_index: dict[str, dict[str, Any]],
    gate_policy: dict[str, Any],
) -> tuple[str, dict[str, str | None], dict[str, str | None]]:
    evidence_sha256 = {name: sha256_file(run_dir / name) for name in PACKAGE_EVIDENCE_FILES}
    run_config = load_json(run_dir / "run_config.json", default={}) or {}
    if run_config.get("fit_runtime_version"):
        panel_raw = run_config.get("panel_path")
        if panel_raw:
            panel_path = resolve(panel_raw)
            evidence_sha256["panel"] = sha256_file(panel_path)
            approval_path = panel_path.parent / "audits" / f"{panel_path.stem}_promotion_decision.json"
            evidence_sha256["panel_promotion_decision"] = sha256_file(approval_path)
        for name in [
            "fit_design_metadata.json",
            "fit_design_media_scales.csv",
            "fit_design_media_scales_exact.csv",
            "fit_design_control_scalers.csv",
            "fit_design_row_index.parquet",
        ]:
            evidence_sha256[name] = sha256_file(run_dir / name)
        for path in sorted(run_dir.glob("fit_contract_*.json")):
            evidence_sha256[path.name] = sha256_file(path)
        for path in sorted(run_dir.glob("fit_transform_*.json")):
            evidence_sha256[path.name] = sha256_file(path)
        evidence_sha256["fit_runtime_recorded_sha256"] = str(run_config.get("fit_code_sha256") or "")
        fit_snapshot = run_dir / "fit_runtime_snapshot.py"
        if fit_snapshot.exists():
            evidence_sha256["fit_runtime_snapshot"] = sha256_file(fit_snapshot)
        for name, path in {
            "gate_compiler_code": Path(__file__),
            "forecast_scorer_code": Path(__file__).with_name("forecast_engine.py"),
            "validation_code": Path(__file__).with_name("validation.py"),
        }.items():
            evidence_sha256[name] = sha256_file(path)
    posterior_sha256 = {
        fit_key: row.get("sha256") for fit_key, row in sorted(posterior_index.items())
    }
    fingerprint = sha256_json(
        {
            "evidence_sha256": evidence_sha256,
            "posterior_sha256": posterior_sha256,
            "gate_policy": gate_policy,
        }
    )
    return fingerprint, evidence_sha256, posterior_sha256


def fit_runtime_provenance_issues(run_dir: Path, run_config: dict[str, Any]) -> list[str]:
    """Validate recorded fit provenance without binding serving to mutable source code."""
    if not run_config.get("fit_runtime_version"):
        return []
    expected_hash = str(run_config.get("fit_code_sha256") or "")
    issues: list[str] = []
    if not expected_hash:
        issues.append("MISSING_RECORDED_FIT_CODE_HASH")
    contracts = sorted(run_dir.glob("fit_contract_*.json"))
    if not contracts:
        issues.append("MISSING_FIT_CONTRACTS")
    for path in contracts:
        contract = load_json(path, default={}) or {}
        if str(contract.get("fit_code_sha256") or "") != expected_hash:
            issues.append("FIT_CONTRACT_CODE_HASH_MISMATCH")
            break
    fit_snapshot = run_dir / "fit_runtime_snapshot.py"
    if fit_snapshot.exists() and sha256_file(fit_snapshot) != expected_hash:
        issues.append("FIT_RUNTIME_SNAPSHOT_HASH_MISMATCH")
    return sorted(set(issues))


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def spend_col_to_channel(spend_col: str) -> str:
    return spend_col.removeprefix("spend_")


def channel_to_spend_col(channel: str) -> str:
    return channel if channel.startswith("spend_") else f"spend_{channel}"


def split_segment(segment: str) -> tuple[str, str]:
    if "/" not in segment:
        return segment, ""
    network, channel = segment.split("/", 1)
    return network, channel


def make_fit_key(segment: str, target: str) -> str:
    return f"{segment}::{target}"


def parse_fit_key(fit_key: str) -> tuple[str, str]:
    if "::" not in fit_key:
        return fit_key, ""
    segment, target = fit_key.split("::", 1)
    return segment, target


def parse_posterior_file(path: Path) -> tuple[str, str] | None:
    match = POSTERIOR_RE.match(path.name)
    if not match:
        return None
    token = match.group("segment_token")
    target = match.group("target")
    if "_" in token:
        network, channel = token.split("_", 1)
        segment = f"{network}/{channel}"
    else:
        segment = token.replace("_", "/")
    return make_fit_key(segment, target), target


def sorted_unique(values: list[str]) -> list[str]:
    return sorted({v for v in values if v is not None and str(v) != ""})


def derive_segments(config: dict[str, Any], artifact_rows: dict[str, list[dict[str, str]]]) -> list[str]:
    segments: list[str] = []
    segments.extend((config.get("media_grouping_config") or {}).keys())
    for item in config.get("beta_structure_overrides_by_fit") or []:
        if item.get("fit_key"):
            segments.append(parse_fit_key(item["fit_key"])[0])
        elif item.get("network") and item.get("channel"):
            segments.append(f"{item['network']}/{item['channel']}")
    for item in config.get("beta_tier_pooled_channels_by_fit") or []:
        if item.get("fit_key"):
            segments.append(parse_fit_key(item["fit_key"])[0])
        elif item.get("network") and item.get("channel"):
            segments.append(f"{item['network']}/{item['channel']}")
    for rows in artifact_rows.values():
        for row in rows:
            if row.get("segment"):
                segments.append(row["segment"])
    return sorted_unique(segments)


def derive_targets(config: dict[str, Any], artifact_rows: dict[str, list[dict[str, str]]]) -> list[str]:
    targets: list[str] = []
    targets.extend((config.get("beta_structure_by_target") or {}).keys())
    for item in config.get("beta_structure_overrides_by_fit") or []:
        if item.get("target"):
            targets.append(item["target"])
        elif item.get("fit_key"):
            targets.append(parse_fit_key(item["fit_key"])[1])
    for item in config.get("beta_tier_pooled_channels_by_fit") or []:
        if item.get("target"):
            targets.append(item["target"])
        elif item.get("fit_key"):
            targets.append(parse_fit_key(item["fit_key"])[1])
    for rows in artifact_rows.values():
        for row in rows:
            if row.get("target"):
                targets.append(row["target"])
    return sorted_unique(targets) or DEFAULT_TARGETS


def grouping_components_for_segment(config: dict[str, Any], segment: str) -> set[str]:
    grouping = (config.get("media_grouping_config") or {}).get(segment) or {}
    components: set[str] = set()
    for component_cols in grouping.values():
        components.update(component_cols or [])
    return components


def grouped_channels_for_segment(config: dict[str, Any], segment: str) -> list[str]:
    grouping = (config.get("media_grouping_config") or {}).get(segment) or {}
    return [spend_col_to_channel(col) for col in grouping.keys()]



def artifact_channels_for_fit(artifact_rows: dict[str, list[dict[str, str]]], segment: str, target: str) -> list[str]:
    channels: list[str] = []
    for rows in artifact_rows.values():
        for row in rows:
            if row.get("segment") == segment and row.get("target") == target and row.get("channel"):
                channels.append(row["channel"])
    return sorted_unique(channels)

def configured_channels(config: dict[str, Any], segment: str, target: str) -> list[str]:
    base_cols = list(config.get("spend_active_base") or config.get("spend_active_model_universe") or [])
    grouped_component_cols = grouping_components_for_segment(config, segment)
    direct_channels = [
        spend_col_to_channel(col)
        for col in base_cols
        if col not in grouped_component_cols
        and spend_col_to_channel(col) not in grouped_channels_for_segment(config, segment)
    ]
    channels = direct_channels + grouped_channels_for_segment(config, segment)

    policy = config.get("tc5_offline_specific_policy") or {}
    if policy.get("enabled") and segment == policy.get("segment") and target in set(policy.get("targets") or []):
        excluded = {spend_col_to_channel(col) for col in policy.get("excluded_media_cols") or []}
        channels = [ch for ch in channels if ch not in excluded]
    return sorted_unique(channels)


def beta_structure_for_fit(config: dict[str, Any], segment: str, target: str) -> str:
    for item in config.get("beta_structure_overrides_by_fit") or []:
        fit_key = item.get("fit_key") or make_fit_key(f"{item.get('network')}/{item.get('channel')}", item.get("target", ""))
        if fit_key == make_fit_key(segment, target):
            return item.get("beta_structure") or ""
    return (config.get("beta_structure_by_target") or {}).get(target, "")


def tier_pooled_channels_for_fit(config: dict[str, Any], segment: str, target: str) -> list[str]:
    fit_key = make_fit_key(segment, target)
    channels: list[str] = []
    for item in config.get("beta_tier_pooled_channels_by_fit") or []:
        item_fit_key = item.get("fit_key") or make_fit_key(f"{item.get('network')}/{item.get('channel')}", item.get("target", ""))
        if item_fit_key == fit_key:
            channels.extend(item.get("pooled_channels") or [])
    return sorted_unique(channels)


def index_rows(rows: list[dict[str, str]], *keys: str) -> dict[tuple[str, ...], dict[str, str]]:
    out = {}
    for row in rows:
        key = tuple(row.get(k, "") for k in keys)
        if all(key):
            out[key] = row
    return out


def list_posteriors(run_dir: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(run_dir.glob("posterior_*.nc")):
        parsed = parse_posterior_file(path)
        if not parsed:
            continue
        fit_key, target = parsed
        out[fit_key] = {
            "fit_key": fit_key,
            "target": target,
            "path": str(path),
            "file_name": path.name,
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
            "mtime_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        }
    return out


def as_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_gate_policy(run_dir: Path) -> dict[str, Any]:
    """Load an optional run-specific gate policy over conservative defaults."""
    override = load_json(run_dir / "model_gate_policy.json", default={}) or {}
    if not isinstance(override, dict):
        raise ValueError("model_gate_policy.json must contain a JSON object")
    policy = _deep_merge(DEFAULT_GATE_POLICY, override)

    # Run-level policy may tighten defaults, but it cannot promote weaker evidence.
    channel = policy["channel_evidence"]
    default_channel = DEFAULT_GATE_POLICY["channel_evidence"]
    for key, default_value in default_channel.items():
        requested = as_float(channel.get(key))
        channel[key] = max(float(default_value), requested if requested is not None else float(default_value))

    adequacy = policy["fit_adequacy"]
    default_adequacy = DEFAULT_GATE_POLICY["fit_adequacy"]
    diagnostic_ppc = max(
        float(default_adequacy["diagnostic_ppc_r2_lt"]),
        as_float(adequacy.get("diagnostic_ppc_r2_lt"))
        if as_float(adequacy.get("diagnostic_ppc_r2_lt")) is not None
        else float(default_adequacy["diagnostic_ppc_r2_lt"]),
    )
    caution_ppc = max(
        float(default_adequacy["caution_ppc_r2_lt"]),
        as_float(adequacy.get("caution_ppc_r2_lt"))
        if as_float(adequacy.get("caution_ppc_r2_lt")) is not None
        else float(default_adequacy["caution_ppc_r2_lt"]),
        diagnostic_ppc,
    )
    adequacy["diagnostic_ppc_r2_lt"] = diagnostic_ppc
    adequacy["caution_ppc_r2_lt"] = caution_ppc

    contraction = policy["contraction_evidence"]
    default_contraction = DEFAULT_GATE_POLICY["contraction_evidence"]
    contraction["low_contraction_lt"] = float(default_contraction["low_contraction_lt"])
    contraction["medium_contraction_lt"] = float(default_contraction["medium_contraction_lt"])
    requested_share = as_float(contraction.get("caution_limited_contraction_share_gte"))
    contraction["caution_limited_contraction_share_gte"] = min(
        float(default_contraction["caution_limited_contraction_share_gte"]),
        requested_share if requested_share is not None else float(default_contraction["caution_limited_contraction_share_gte"]),
    )

    target_rules = policy.setdefault("target_rules", {})
    for target, default_rule in DEFAULT_GATE_POLICY["target_rules"].items():
        requested_rule = target_rules.get(target) if isinstance(target_rules.get(target), dict) else {}
        target_rules[target] = {
            **requested_rule,
            "minimum_allowed_use": _most_restrictive(
                str(default_rule["minimum_allowed_use"]),
                str(requested_rule.get("minimum_allowed_use") or ""),
            ),
            "reason_code": str(requested_rule.get("reason_code") or default_rule["reason_code"]),
        }

    for action_type, key in [("optimizer", "optimizer_actions"), ("forecast", "forecast_actions")]:
        for allowed_use, minimum in DEFAULT_GATE_POLICY[key].items():
            policy[key][allowed_use] = _restricted_action(
                str(policy[key].get(allowed_use) or minimum),
                minimum,
                action_type=action_type,
            )
    policy["schema_version"] = GATE_POLICY_VERSION
    return policy


def _restriction_level(value: str) -> int:
    return {
        "primary": 0,
        "caution": 1,
        "diagnostic": 2,
        PENDING_ALLOWED_USE: 3,
        "unavailable": 4,
    }.get(str(value or ""), 4)


def _most_restrictive(*values: str) -> str:
    clean = [str(value) for value in values if value]
    return max(clean, key=_restriction_level) if clean else "unavailable"


def _restricted_action(requested: str, minimum: str, *, action_type: str) -> str:
    ranks_by_type = {
        "optimizer": {"optimize": 0, "no_increase": 1, "fixed_at_plan": 2, "blocked": 3},
        "forecast": {"allowed": 0, "allowed_with_warning": 1, "diagnostic_only": 2, "blocked": 3},
    }
    ranks = ranks_by_type[action_type]
    requested_rank = ranks.get(str(requested or ""), ranks["blocked"])
    minimum_rank = ranks.get(str(minimum or ""), ranks["blocked"])
    effective_rank = max(requested_rank, minimum_rank)
    return next(action for action, rank in ranks.items() if rank == effective_rank)


def _contraction_index(
    rows: list[dict[str, str]],
    gate_policy: dict[str, Any],
) -> dict[tuple[str, str, str], dict[str, float]]:
    thresholds = gate_policy["contraction_evidence"]
    low_lt = float(thresholds["low_contraction_lt"])
    medium_lt = float(thresholds["medium_contraction_lt"])
    counts: dict[tuple[str, str, str], dict[str, int]] = {}
    for row in rows:
        key = (row.get("segment", ""), row.get("target", ""), row.get("channel", ""))
        if not all(key):
            continue
        bucket = counts.setdefault(
            key,
            {
                "total": 0,
                "posterior_expanded": 0,
                "low_contraction": 0,
                "medium_contraction": 0,
                "high_contraction": 0,
                "unavailable": 0,
            },
        )
        bucket["total"] += 1
        value = as_float(row.get("contraction"))
        if value is None or not math.isfinite(value):
            bucket["unavailable"] += 1
        elif value < 0:
            bucket["posterior_expanded"] += 1
        elif value < low_lt:
            bucket["low_contraction"] += 1
        elif value < medium_lt:
            bucket["medium_contraction"] += 1
        else:
            bucket["high_contraction"] += 1
    out: dict[tuple[str, str, str], dict[str, float]] = {}
    for key, bucket in counts.items():
        total = max(bucket["total"], 1)
        out[key] = {
            "rows_n": float(bucket["total"]),
            "posterior_expanded_share": bucket["posterior_expanded"] / total,
            "low_contraction_share": bucket["low_contraction"] / total,
            "medium_contraction_share": bucket["medium_contraction"] / total,
            "high_contraction_share": bucket["high_contraction"] / total,
            "unavailable_contraction_share": bucket["unavailable"] / total,
        }
    return out


def evaluate_channel_gate(
    *,
    target: str,
    fit_allowed: str,
    upstream_row: dict[str, str],
    reliability_flags: str,
    contraction: dict[str, float],
    gate_policy: dict[str, Any],
    fixed_response_shape: bool = False,
) -> dict[str, Any]:
    """Compile model evidence into explicit forecast and optimizer permissions."""
    thresholds = gate_policy["channel_evidence"]
    reasons: list[str] = []
    levels: list[str] = [fit_allowed]

    upstream_use = str(upstream_row.get("roas_use_case") or "").strip()
    if upstream_use == "reportable":
        levels.append("primary")
    elif upstream_use == "diagnostic_only":
        levels.append("diagnostic")
        reasons.append("UPSTREAM_DIAGNOSTIC_ONLY")
    else:
        levels.append("diagnostic")
        reasons.append("MISSING_UPSTREAM_USE_CASE")

    flags = str(reliability_flags or "").strip()
    if flags and flags != "OK":
        levels.append("diagnostic")
        reasons.extend(flag for flag in flags.split("|") if flag and flag != "OK")

    quality_flags = str(upstream_row.get("quality_flags") or "").strip()
    if quality_flags and quality_flags != "OK":
        reasons.extend(flag for flag in quality_flags.split("|") if flag and flag != "OK")

    active_days = as_float(upstream_row.get("active_days"))
    active_geos = as_float(upstream_row.get("active_geos"))
    pct_nonzero = as_float(upstream_row.get("pct_nonzero_rows"))
    contraction_rows_n = float(contraction.get("rows_n") or 0.0)
    posterior_expanded_share = float(contraction.get("posterior_expanded_share") or 0.0)
    low_contraction_share = float(contraction.get("low_contraction_share") or 0.0)
    medium_contraction_share = float(contraction.get("medium_contraction_share") or 0.0)
    high_contraction_share = float(contraction.get("high_contraction_share") or 0.0)
    unavailable_contraction_share = float(contraction.get("unavailable_contraction_share") or 0.0)

    if active_days is None:
        levels.append("diagnostic")
        reasons.append("MISSING_ACTIVE_DAYS")
    elif active_days < float(thresholds["diagnostic_active_days_lt"]):
        levels.append("diagnostic")
        reasons.append("VERY_SHORT_ACTIVE_HISTORY")
    elif active_days < float(thresholds["caution_active_days_lt"]):
        levels.append("caution")
        reasons.append("SHORT_ACTIVE_HISTORY")

    if active_geos is None:
        levels.append("diagnostic")
        reasons.append("MISSING_ACTIVE_GEOS")
    elif active_geos < float(thresholds["diagnostic_active_geos_lt"]):
        levels.append("diagnostic")
        reasons.append("VERY_LOW_GEO_COVERAGE")
    elif active_geos < float(thresholds["caution_active_geos_lt"]):
        levels.append("caution")
        reasons.append("LOW_GEO_COVERAGE")

    if pct_nonzero is None:
        levels.append("diagnostic")
        reasons.append("MISSING_NONZERO_SHARE")
    elif pct_nonzero < float(thresholds["diagnostic_nonzero_rows_pct_lt"]):
        levels.append("diagnostic")
        reasons.append("EXTREMELY_SPARSE_MEDIA")
    elif pct_nonzero < float(thresholds["caution_nonzero_rows_pct_lt"]):
        levels.append("caution")
        reasons.append("SPARSE_MEDIA")

    target_rule = (gate_policy.get("target_rules") or {}).get(target) or {}
    mandatory_target_rule = (DEFAULT_GATE_POLICY.get("target_rules") or {}).get(target) or {}
    target_minimum = _most_restrictive(
        str(mandatory_target_rule.get("minimum_allowed_use") or "primary"),
        str(target_rule.get("minimum_allowed_use") or "primary"),
    )
    if target_minimum != "primary":
        levels.append(target_minimum)
        reasons.append(
            str(
                mandatory_target_rule.get("reason_code")
                or target_rule.get("reason_code")
                or "TARGET_POLICY_RESTRICTION"
            )
        )

    if contraction_rows_n <= 0:
        levels.append("diagnostic")
        reasons.append("MISSING_CONTRACTION_EVIDENCE")
    elif unavailable_contraction_share > 0:
        levels.append("diagnostic")
        reasons.append("UNAVAILABLE_CONTRACTION_EVIDENCE")

    limited_contraction_share = posterior_expanded_share + low_contraction_share
    limited_threshold = float(
        gate_policy["contraction_evidence"]["caution_limited_contraction_share_gte"]
    )
    if limited_contraction_share >= limited_threshold:
        levels.append("caution")
        if posterior_expanded_share > 0:
            reasons.append("POSTERIOR_EXPANDED_EFFECT")
        if low_contraction_share > 0:
            reasons.append("LOW_CONTRACTION_EFFECT")

    if fixed_response_shape:
        levels.append("caution")
        reasons.append("FIXED_SATURATION_SHAPE")

    allowed_use = _most_restrictive(*levels)
    if fit_allowed == "caution":
        reasons.append("FIT_LEVEL_CAUTION")
    elif fit_allowed == "diagnostic":
        reasons.append("FIT_LEVEL_DIAGNOSTIC")
    reasons = list(dict.fromkeys(reasons))

    if "TARGET_POLICY_DIAGNOSTIC_ONLY" in reasons:
        marketer_message = "Количество заказов показывается только как диагностическая метрика и не используется для автоматического перераспределения бюджета."
    elif allowed_use == "primary":
        marketer_message = "Данных и диагностик достаточно для прогноза и перераспределения бюджета в historical support-zone."
    elif allowed_use == "caution" and fixed_response_shape:
        marketer_message = "Форма saturation-кривой зафиксирована для устойчивости оценки: прогноз допустим с оговоркой, но автоматически увеличивать бюджет в этот канал нельзя."
    elif allowed_use == "caution":
        marketer_message = "Эффект можно прогнозировать, но бюджет в этот канал нельзя автоматически увеличивать до накопления более надежных данных."
    elif allowed_use == "diagnostic":
        marketer_message = "Оценка канала недостаточно надежна для оптимизации: система сохраняет исходный бюджет и показывает эффект только как диагностический."
    else:
        marketer_message = "Эффект недоступен для автоматического прогноза и оптимизации."

    objective_role = {
        "primary": "primary_objective",
        "caution": "risk_adjusted_objective",
        "diagnostic": "side_metric_only",
    }.get(allowed_use, "forbidden")
    minimum_forecast = DEFAULT_GATE_POLICY["forecast_actions"].get(allowed_use, "blocked")
    minimum_optimizer = DEFAULT_GATE_POLICY["optimizer_actions"].get(allowed_use, "blocked")
    requested_forecast = gate_policy["forecast_actions"].get(allowed_use, "blocked")
    requested_optimizer = gate_policy["optimizer_actions"].get(allowed_use, "blocked")
    return {
        "allowed_use": allowed_use,
        "forecast_policy": _restricted_action(requested_forecast, minimum_forecast, action_type="forecast"),
        "optimizer_policy": _restricted_action(requested_optimizer, minimum_optimizer, action_type="optimizer"),
        "objective_role": objective_role,
        "gate_reason_codes": "|".join(reasons) if reasons else "OK",
        "marketer_message": marketer_message,
        "upstream_roas_use_case": upstream_use or "missing",
        "upstream_quality_flags": quality_flags or "missing",
        "active_days": active_days if active_days is not None else "",
        "active_geos": active_geos if active_geos is not None else "",
        "pct_nonzero_rows": pct_nonzero if pct_nonzero is not None else "",
        "contraction_rows_n": contraction_rows_n,
        "posterior_expanded_share": posterior_expanded_share,
        "low_contraction_share": low_contraction_share,
        "medium_contraction_share": medium_contraction_share,
        "high_contraction_share": high_contraction_share,
        "unavailable_contraction_share": unavailable_contraction_share,
        "fixed_saturation_shape": bool(fixed_response_shape),
    }


def fit_risk_from_artifacts(
    fit_key: str,
    diagnostics: dict[tuple[str], dict[str, str]],
    adequacy: dict[str, Any],
    posterior_index: dict[str, dict[str, Any]],
    gate_policy: dict[str, Any] | None = None,
) -> tuple[str, str, list[dict[str, Any]]]:
    risks: list[dict[str, Any]] = []
    posterior_present = fit_key in posterior_index
    diag = diagnostics.get((fit_key,)) or {}
    adequacy_rec = adequacy.get(fit_key) or {}

    if not posterior_present:
        risks.append({"risk_type": "PENDING_POSTERIOR", "risk_level": "pending", "reason": "posterior file is not present yet"})
        return "pending", PENDING_ALLOWED_USE, risks

    if not diag:
        risks.append(
            {
                "risk_type": "MISSING_FIT_DIAGNOSTICS",
                "risk_level": "high",
                "reason": "No diagnostics_summary row exists for this posterior fit",
            }
        )
    if not adequacy_rec:
        risks.append(
            {
                "risk_type": "MISSING_FIT_ADEQUACY",
                "risk_level": "high",
                "reason": "No adequacy record exists for this posterior fit",
            }
        )

    status = diag.get("status", "")
    rhat = as_float(diag.get("rhat_max"))
    ess = as_float(diag.get("ess_bulk_min"))
    divergences = as_float(diag.get("n_divergences"))
    missing_diag_fields = [
        name
        for name, value in {"status": status, "rhat_max": rhat, "ess_bulk_min": ess, "n_divergences": divergences}.items()
        if value is None or value == ""
    ]
    if missing_diag_fields:
        risks.append(
            {
                "risk_type": "INCOMPLETE_FIT_DIAGNOSTICS",
                "risk_level": "high",
                "reason": f"Missing diagnostic fields: {','.join(missing_diag_fields)}",
            }
        )
    if status and "OK" not in status:
        risks.append({"risk_type": "SAMPLER_WARNING", "risk_level": "medium", "reason": status})
    if rhat is not None and rhat > 1.02:
        risks.append({"risk_type": "RHAT_GT_1_02", "risk_level": "medium", "reason": f"rhat_max={rhat:.4g}"})
    if rhat is not None and rhat > 1.05:
        risks.append({"risk_type": "RHAT_GT_1_05", "risk_level": "high", "reason": f"rhat_max={rhat:.4g}"})
    if ess is not None and ess < 200:
        risks.append({"risk_type": "LOW_ESS", "risk_level": "medium", "reason": f"ess_bulk_min={ess:.4g}"})
    if divergences is not None and divergences > 0:
        risks.append({"risk_type": "DIVERGENCES", "risk_level": "medium", "reason": f"n_divergences={int(divergences)}"})

    r2_mean = as_float(adequacy_rec.get("r2_mean"))
    if adequacy_rec and r2_mean is None:
        risks.append(
            {
                "risk_type": "INCOMPLETE_FIT_ADEQUACY",
                "risk_level": "high",
                "reason": "Missing adequacy.r2_mean",
            }
        )
    adequacy_thresholds = (gate_policy or DEFAULT_GATE_POLICY)["fit_adequacy"]
    default_adequacy = DEFAULT_GATE_POLICY["fit_adequacy"]
    diagnostic_ppc_r2_lt = max(
        float(default_adequacy["diagnostic_ppc_r2_lt"]),
        float(adequacy_thresholds["diagnostic_ppc_r2_lt"]),
    )
    caution_ppc_r2_lt = max(
        float(default_adequacy["caution_ppc_r2_lt"]),
        float(adequacy_thresholds["caution_ppc_r2_lt"]),
        diagnostic_ppc_r2_lt,
    )
    if r2_mean is not None and r2_mean < 0:
        risks.append({"risk_type": "WEAK_FIT_NEGATIVE_PPC_R2", "risk_level": "high", "reason": f"r2_mean={r2_mean:.4g}"})
    elif r2_mean is not None and r2_mean < diagnostic_ppc_r2_lt:
        risks.append({"risk_type": "WEAK_FIT_LOW_PPC_R2", "risk_level": "high", "reason": f"r2_mean={r2_mean:.4g}"})
    elif r2_mean is not None and r2_mean < caution_ppc_r2_lt:
        risks.append({"risk_type": "PPC_R2_MANUAL_REVIEW_BAND", "risk_level": "medium", "reason": f"r2_mean={r2_mean:.4g}"})

    high = any(r["risk_level"] == "high" for r in risks)
    medium = any(r["risk_level"] == "medium" for r in risks)
    if high:
        return "high", "diagnostic", risks
    if medium:
        return "medium", "caution", risks
    return "low", "primary", risks


def build_package(
    run_dir: Path,
    output_dir: Path,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
    list[dict[str, Any]],
    dict[str, Any],
]:
    run_config_path = run_dir / "run_config.json"
    config = load_json(run_config_path)
    if not isinstance(config, dict):
        raise FileNotFoundError(f"run_config.json not found or invalid in {run_dir}")
    fit_provenance_issues = fit_runtime_provenance_issues(run_dir, config)

    diagnostics_rows = load_csv(run_dir / "diagnostics_summary.csv")
    reliability_rows = load_csv(run_dir / "channel_reliability.csv")
    roas_rows = load_csv(run_dir / "roas_all_fits.csv")
    target_effect_rows = load_csv(run_dir / "target_effects_all_fits.csv")
    contraction_rows = load_csv(run_dir / "prior_posterior_contraction.csv")
    adequacy = load_json(run_dir / "adequacy.json", default={}) or {}
    posterior_index = list_posteriors(run_dir)
    gate_policy = load_gate_policy(run_dir)

    package_input_fingerprint, evidence_sha256, posterior_sha256 = build_package_input_fingerprint(
        run_dir,
        posterior_index,
        gate_policy,
    )

    artifact_rows = {
        "diagnostics_summary": diagnostics_rows,
        "channel_reliability": reliability_rows,
        "roas_all_fits": roas_rows,
        "target_effects_all_fits": target_effect_rows,
    }
    segments = derive_segments(config, artifact_rows)
    targets = derive_targets(config, artifact_rows)

    diagnostics_by_fit = index_rows(diagnostics_rows, "fit_key")
    reliability_by_stc = index_rows(reliability_rows, "segment", "target", "channel")
    roas_by_stc = index_rows(roas_rows, "segment", "target", "channel")
    contraction_by_stc = _contraction_index(contraction_rows, gate_policy)
    fixed_lambda_by_fit = {
        str(fit_key): {str(channel) for channel in channels}
        for fit_key, channels in (config.get("fixed_lambda_channels_by_fit") or {}).items()
        if isinstance(channels, list)
    }

    expected_fit_keys = sorted(
        make_fit_key(segment, target)
        for segment in segments
        for target in targets
        if configured_channels(config, segment, target) or artifact_channels_for_fit(artifact_rows, segment, target)
    )
    missing_posterior_fits = sorted(set(expected_fit_keys) - set(posterior_index))
    missing_diagnostics_fits = sorted(
        fit_key for fit_key in expected_fit_keys if (fit_key,) not in diagnostics_by_fit
    )
    missing_adequacy_fits = sorted(fit_key for fit_key in expected_fit_keys if not adequacy.get(fit_key))
    package_stage = "config_only_or_partial"
    if posterior_index:
        package_stage = "posterior_partial"
    if expected_fit_keys and not missing_posterior_fits and not missing_diagnostics_fits and not missing_adequacy_fits:
        package_stage = "posterior_ready"

    capability_rows: list[dict[str, Any]] = []
    risk_rows: list[dict[str, Any]] = []
    gate_rows: list[dict[str, Any]] = []

    for segment in segments:
        for target in targets:
            fit_key = make_fit_key(segment, target)
            beta_structure = beta_structure_for_fit(config, segment, target)
            fit_risk_level, fit_allowed, fit_risks = fit_risk_from_artifacts(
                fit_key, diagnostics_by_fit, adequacy, posterior_index, gate_policy
            )
            for risk in fit_risks:
                risk_rows.append({
                    "scope": "fit",
                    "segment": segment,
                    "target": target,
                    "channel": "__all__",
                    "fit_key": fit_key,
                    "risk_type": risk["risk_type"],
                    "risk_level": risk["risk_level"],
                    "reason": risk["reason"],
                    "affects_forecast": True,
                    "affects_optimizer": True,
                })

            artifact_channels = artifact_channels_for_fit(artifact_rows, segment, target)
            channel_list = artifact_channels or configured_channels(config, segment, target)
            for channel in channel_list:
                reliability = reliability_by_stc.get((segment, target, channel)) or {}
                flags = reliability.get("reliability_flags", "")
                upstream_row = roas_by_stc.get((segment, target, channel)) or {}
                contraction = contraction_by_stc.get((segment, target, channel)) or {}
                gate = evaluate_channel_gate(
                    target=target,
                    fit_allowed=fit_allowed,
                    upstream_row=upstream_row,
                    reliability_flags=flags,
                    contraction=contraction,
                    gate_policy=gate_policy,
                    fixed_response_shape=channel in fixed_lambda_by_fit.get(fit_key, set()),
                )
                allowed_use = str(gate["allowed_use"])
                risk_level = {
                    "primary": "low",
                    "caution": "medium",
                    "diagnostic": "high",
                    PENDING_ALLOWED_USE: "pending",
                }.get(allowed_use, "unavailable")
                allowed_reason = str(gate["marketer_message"])
                if flags and flags != "OK":
                    risk_rows.append({
                        "scope": "channel",
                        "segment": segment,
                        "target": target,
                        "channel": channel,
                        "fit_key": fit_key,
                        "risk_type": "CHANNEL_RELIABILITY_FLAGS",
                        "risk_level": "medium",
                        "reason": flags,
                        "affects_forecast": True,
                        "affects_optimizer": True,
                    })

                for reason_code in str(gate["gate_reason_codes"]).split("|"):
                    if not reason_code or reason_code == "OK":
                        continue
                    risk_rows.append({
                        "scope": "channel_gate",
                        "segment": segment,
                        "target": target,
                        "channel": channel,
                        "fit_key": fit_key,
                        "risk_type": reason_code,
                        "risk_level": risk_level,
                        "reason": allowed_reason,
                        "affects_forecast": gate["forecast_policy"] != "allowed",
                        "affects_optimizer": gate["optimizer_policy"] != "optimize",
                    })

                gate_row = {
                    "segment": segment,
                    "target": target,
                    "channel": channel,
                    "fit_key": fit_key,
                    "gate_policy_version": gate_policy["schema_version"],
                    "fit_allowed_use": fit_allowed,
                    **gate,
                }
                gate_rows.append(gate_row)

                capability_rows.append({
                    "segment": segment,
                    "target": target,
                    "channel": channel,
                    "fit_key": fit_key,
                    "configured": True,
                    "posterior_status": "present" if fit_key in posterior_index else "missing",
                    "posterior_file": posterior_index.get(fit_key, {}).get("file_name", ""),
                    "diagnostics_status": (diagnostics_by_fit.get((fit_key,)) or {}).get("status", "missing"),
                    "rhat_max": (diagnostics_by_fit.get((fit_key,)) or {}).get("rhat_max", ""),
                    "ess_bulk_min": (diagnostics_by_fit.get((fit_key,)) or {}).get("ess_bulk_min", ""),
                    "n_divergences": (diagnostics_by_fit.get((fit_key,)) or {}).get("n_divergences", ""),
                    "r2_mean": (adequacy.get(fit_key) or {}).get("r2_mean", ""),
                    "r2_point": (adequacy.get(fit_key) or {}).get("r2_point", ""),
                    "coverage_90": (adequacy.get(fit_key) or {}).get("coverage_90", ""),
                    "beta_structure": beta_structure,
                    "tier_pooled_channels": ";".join(tier_pooled_channels_for_fit(config, segment, target)),
                    "media_scaling_mode": config.get("media_scaling_mode", ""),
                    "media_response_mode": config.get("media_response_mode", ""),
                    "l_max": (config.get("cfg") or {}).get("l_max", ""),
                    "channel_reliability_flags": flags or "missing",
                    "upstream_roas_use_case": gate["upstream_roas_use_case"],
                    "upstream_quality_flags": gate["upstream_quality_flags"],
                    "active_days": gate["active_days"],
                    "active_geos": gate["active_geos"],
                    "pct_nonzero_rows": gate["pct_nonzero_rows"],
                    "posterior_expanded_share": gate["posterior_expanded_share"],
                    "low_contraction_share": gate["low_contraction_share"],
                    "medium_contraction_share": gate["medium_contraction_share"],
                    "high_contraction_share": gate["high_contraction_share"],
                    "unavailable_contraction_share": gate["unavailable_contraction_share"],
                    "fixed_saturation_shape": gate["fixed_saturation_shape"],
                    "gate_reason_codes": gate["gate_reason_codes"],
                    "risk_level": risk_level,
                    "allowed_use": allowed_use,
                    "allowed_use_reason": allowed_reason,
                    "analysis_included": True,
                    "forecast_use": gate["forecast_policy"],
                    "optimizer_use": gate["optimizer_policy"],
                    "objective_role": gate["objective_role"],
                    "marketer_message": gate["marketer_message"],
                })

    production_blockers: list[str] = []
    if package_stage != "posterior_ready":
        production_blockers.append("INCOMPLETE_PER_FIT_EVIDENCE")
    if fit_provenance_issues:
        production_blockers.append("INCONSISTENT_FIT_RUNTIME_PROVENANCE")
    if config.get("fit_runtime_version"):
        panel_path = resolve(config.get("panel_path")) if config.get("panel_path") else None
        panel_approval = {}
        if panel_path is not None:
            panel_approval_path = panel_path.parent / "audits" / f"{panel_path.stem}_promotion_decision.json"
            panel_approval = load_json(panel_approval_path, default={}) or {}
            if (
                panel_approval.get("status") != "reviewed_promoted"
                or panel_approval.get("promoted_panel_sha256") != sha256_file(panel_path)
            ):
                production_blockers.append("MISSING_OR_STALE_PANEL_PROMOTION_APPROVAL")
        else:
            production_blockers.append("MISSING_OR_STALE_PANEL_PROMOTION_APPROVAL")
    oot_validation = load_json(run_dir / "oot_validation.json", default={}) or {}
    replay_validation = load_json(run_dir / "historical_replay_validation.json", default={}) or {}
    if (
        not isinstance(oot_validation, dict)
        or oot_validation.get("status") != "passed"
        or not oot_validation.get("activation_eligible")
    ):
        production_blockers.append("MISSING_OR_FAILED_OOT_VALIDATION")
    elif oot_validation.get("package_input_fingerprint") != package_input_fingerprint:
        production_blockers.append("STALE_OR_UNBOUND_OOT_VALIDATION")
    if not isinstance(replay_validation, dict) or replay_validation.get("status") != "passed":
        production_blockers.append("MISSING_OR_FAILED_HISTORICAL_REPLAY")
    elif replay_validation.get("package_input_fingerprint") != package_input_fingerprint:
        production_blockers.append("STALE_OR_UNBOUND_HISTORICAL_REPLAY")
    activation_status = "production_ready" if package_stage == "posterior_ready" and not production_blockers else "preprod_restricted"

    manifest = {
        "package_schema_version": PACKAGE_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "package_stage": package_stage,
        "activation_status": activation_status,
        "production_blockers": production_blockers,
        "gate_policy_version": gate_policy["schema_version"],
        "run_dir": str(run_dir),
        "output_dir": str(output_dir),
        "run_config_path": str(run_config_path),
        "run_config_sha256": sha256_file(run_config_path),
        "package_input_fingerprint": package_input_fingerprint,
        "evidence_sha256": evidence_sha256,
        "posterior_sha256": posterior_sha256,
        "fit_runtime_provenance": {
            "recorded_fit_code_sha256": config.get("fit_code_sha256"),
            "source_snapshot_present": (run_dir / "fit_runtime_snapshot.py").exists(),
            "issues": fit_provenance_issues,
            "status": "consistent" if not fit_provenance_issues else "invalid",
        },
        "model_run_id": f"{config.get('run_label', '')}/{config.get('mode', '')}_{config.get('run_variant', '')}".strip("/"),
        "mode": config.get("mode"),
        "run_label": config.get("run_label"),
        "run_variant": config.get("run_variant"),
        "panel_path": config.get("panel_path"),
        "train_start": config.get("train_start"),
        "train_end": config.get("train_end"),
        "holdout_start": config.get("holdout_start"),
        "holdout_end": config.get("holdout_end"),
        "segments": segments,
        "targets": targets,
        "channels_by_segment_target": {
            make_fit_key(segment, target): (
                artifact_channels_for_fit(artifact_rows, segment, target)
                or configured_channels(config, segment, target)
            )
            for segment in segments
            for target in targets
        },
        "cfg": config.get("cfg") or {},
        "model_spec": {
            "media_response_mode": config.get("media_response_mode"),
            "media_scaling_mode": config.get("media_scaling_mode"),
            "baseline_structure": config.get("baseline_structure"),
            "error_structure": config.get("error_structure"),
            "postfit_roas_response_basis": config.get("postfit_roas_response_basis"),
            "beta_structure_by_target": config.get("beta_structure_by_target"),
            "beta_structure_overrides_by_fit": config.get("beta_structure_overrides_by_fit"),
            "beta_tier_pooled_channels_by_fit": config.get("beta_tier_pooled_channels_by_fit"),
            "fixed_lambda_channels_by_fit": config.get("fixed_lambda_channels_by_fit"),
            "tc5_offline_specific_policy": config.get("tc5_offline_specific_policy"),
            "media_grouping_enabled": config.get("media_grouping_enabled"),
            "media_grouping_source": config.get("media_grouping_source"),
            "force_include_spend_cols": config.get("force_include_spend_cols"),
            "indoor_policy_mode": config.get("indoor_policy_mode"),
            "indoor_reporting_mode": config.get("indoor_reporting_mode"),
        },
        "artifact_status": {
            "posterior_files_n": len(posterior_index),
            "diagnostics_summary": (run_dir / "diagnostics_summary.csv").exists(),
            "channel_reliability": (run_dir / "channel_reliability.csv").exists(),
            "adequacy": (run_dir / "adequacy.json").exists(),
            "roas_all_fits": (run_dir / "roas_all_fits.csv").exists(),
            "target_effects_all_fits": (run_dir / "target_effects_all_fits.csv").exists(),
            "prior_posterior_contraction": (run_dir / "prior_posterior_contraction.csv").exists(),
            "oot_validation_passed": not any("OOT_VALIDATION" in code for code in production_blockers),
            "historical_replay_passed": not any("HISTORICAL_REPLAY" in code for code in production_blockers),
        },
        "evidence_coverage": {
            "expected_fit_keys": expected_fit_keys,
            "missing_posterior_fits": missing_posterior_fits,
            "missing_diagnostics_fits": missing_diagnostics_fits,
            "missing_adequacy_fits": missing_adequacy_fits,
            "fit_evidence_complete": not bool(
                missing_posterior_fits or missing_diagnostics_fits or missing_adequacy_fits
            ),
        },
        "contract": {
            "model_run_folder_is_source_of_truth": True,
            "warnings_are_not_dropped": True,
            "analysis_includes_warning_rows": True,
            "forecast_and_optimizer_must_read_manifest": True,
            "allowed_use_levels": ["primary", "caution", "diagnostic", PENDING_ALLOWED_USE, "unavailable"],
            "most_restrictive_evidence_wins": True,
            "diagnostic_effects_are_never_optimizer_objectives": True,
            "missing_gate_evidence_fails_closed": True,
            "orders_per_user_is_diagnostic_only": True,
            "negative_contraction_is_posterior_expansion": True,
            "gate_compiler_is_fingerprint_bound": True,
            "fit_runtime_uses_recorded_provenance_not_mutable_source": True,
            "fixed_saturation_shape_is_never_primary": True,
        },
    }

    posterior_json = {
        "generated_at_utc": manifest["generated_at_utc"],
        "run_dir": str(run_dir),
        "posterior_files_n": len(posterior_index),
        "posterior_by_fit": posterior_index,
        "package_input_fingerprint": package_input_fingerprint,
    }
    return manifest, capability_rows, risk_rows, posterior_json, gate_rows, gate_policy


def write_package_artifacts(
    output_dir: Path,
    built: tuple[
        dict[str, Any],
        list[dict[str, Any]],
        list[dict[str, Any]],
        dict[str, Any],
        list[dict[str, Any]],
        dict[str, Any],
    ],
) -> dict[str, str]:
    manifest, capability_rows, risk_rows, posterior_json, gate_rows, gate_policy = built
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "model_manifest.json", manifest)
    write_json(output_dir / "posterior_index.json", posterior_json)
    write_json(output_dir / "gate_policy.json", gate_policy)
    write_csv(output_dir / "capability_matrix.csv", capability_rows, CAPABILITY_FIELDS)
    write_csv(output_dir / "risk_registry.csv", risk_rows, RISK_FIELDS)
    write_csv(output_dir / "gate_results.csv", gate_rows, GATE_FIELDS)
    return {
        "model_manifest": str(output_dir / "model_manifest.json"),
        "posterior_index": str(output_dir / "posterior_index.json"),
        "gate_policy": str(output_dir / "gate_policy.json"),
        "capability_matrix": str(output_dir / "capability_matrix.csv"),
        "risk_registry": str(output_dir / "risk_registry.csv"),
        "gate_results": str(output_dir / "gate_results.csv"),
    }


def main() -> None:
    args = parse_args()
    run_dir = resolve(args.run_dir)
    output_dir = resolve(args.output_dir) if args.output_dir else run_dir
    manifest, capability_rows, risk_rows, posterior_json, gate_rows, gate_policy = build_package(run_dir, output_dir)

    summary = {
        "package_stage": manifest["package_stage"],
        "model_run_id": manifest["model_run_id"],
        "segments_n": len(manifest["segments"]),
        "targets_n": len(manifest["targets"]),
        "capability_rows_n": len(capability_rows),
        "risk_rows_n": len(risk_rows),
        "gate_rows_n": len(gate_rows),
        "posterior_files_n": manifest["artifact_status"]["posterior_files_n"],
        "activation_status": manifest["activation_status"],
        "production_blockers": manifest["production_blockers"],
        "run_config_sha256": manifest["run_config_sha256"],
    }

    if args.write:
        write_package_artifacts(
            output_dir,
            (manifest, capability_rows, risk_rows, posterior_json, gate_rows, gate_policy),
        )
        print(f"Wrote model package to {output_dir}")

    print(json.dumps(summary if not args.pretty else manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
