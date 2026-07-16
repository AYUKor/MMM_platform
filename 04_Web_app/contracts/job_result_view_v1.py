"""Validation helpers for the browser-safe calculation result projection.

The contract is a presentation boundary over an already published
``ResultOverview v1``.  It must not choose another recommendation, calculate a
reliability score or reconstruct missing model metrics.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any


CONTRACT_NAME = "job_result_view_v1"
SCHEMA_VERSION = "1.0.0"
SCENARIO_IDS = ("S01", "S02", "S03", "S04", "S05", "S06")
RECORD_ORIGINS = {"application_runtime", "sanitized_fixture"}
QUALITY_STATUSES = {"safe", "caution", "blocked", "unavailable"}
AVAILABILITY_STATUSES = {"available", "unavailable"}

_OPAQUE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*_[0-9a-f]{12,64}$")
_ABSOLUTE_PATH_RE = re.compile(r"^(?:/|[A-Za-z]:[\\/]|file://)", re.IGNORECASE)


class JobResultViewContractError(ValueError):
    """Raised when a result-view payload violates the public contract."""


def _finite(value: Any, field_name: str, *, nullable: bool = False) -> float | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JobResultViewContractError(f"{field_name} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise JobResultViewContractError(f"{field_name} must be finite")
    return parsed


def _non_negative(value: Any, field_name: str, *, nullable: bool = False) -> float | None:
    parsed = _finite(value, field_name, nullable=nullable)
    if parsed is not None and parsed < 0:
        raise JobResultViewContractError(f"{field_name} must be non-negative")
    return parsed


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise JobResultViewContractError(f"{field_name} is required")
    return value


def _opaque_id(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not _OPAQUE_ID_RE.fullmatch(value):
        raise JobResultViewContractError(f"{field_name} must be an opaque ID")


def _timestamp(value: Any, field_name: str) -> None:
    if not isinstance(value, str):
        raise JobResultViewContractError(f"{field_name} must be an ISO-8601 datetime")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise JobResultViewContractError(f"{field_name} must be an ISO-8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise JobResultViewContractError(f"{field_name} must include a timezone")


def _reject_paths(value: Any, field_name: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            _reject_paths(nested, f"{field_name}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_paths(nested, f"{field_name}[{index}]")
    elif isinstance(value, str) and _ABSOLUTE_PATH_RE.match(value):
        browser_api_path = value.startswith("/api/v1/") and (
            field_name.endswith(".download_path") or field_name.endswith(".endpoint")
        )
        if not browser_api_path:
            raise JobResultViewContractError(f"Local path is forbidden at {field_name}")


def _validate_quantile_metric(metric: Mapping[str, Any], field_name: str) -> None:
    status = metric.get("status")
    if status not in AVAILABILITY_STATUSES:
        raise JobResultViewContractError(f"Unknown {field_name}.status")
    _required_text(metric.get("display_text"), f"{field_name}.display_text")
    values = [metric.get(key) for key in ("p10", "p50", "p90")]
    if status == "unavailable":
        if any(value is not None for value in values):
            raise JobResultViewContractError(f"{field_name} unavailable metric must be null")
        return
    parsed = [_finite(value, f"{field_name}.{key}") for value, key in zip(values, ("p10", "p50", "p90"))]
    if not parsed[0] <= parsed[1] <= parsed[2]:
        raise JobResultViewContractError(f"{field_name} must satisfy p10 <= p50 <= p90")


def _validate_scenario(scenario: Mapping[str, Any], field_name: str) -> None:
    scenario_id = scenario.get("scenario_id")
    if scenario_id not in SCENARIO_IDS:
        raise JobResultViewContractError(f"Unknown {field_name}.scenario_id")
    if scenario.get("status") not in {"completed", "unavailable", "failed"}:
        raise JobResultViewContractError(f"Unknown {field_name}.status")
    if scenario.get("quality_status") not in QUALITY_STATUSES:
        raise JobResultViewContractError(f"Unknown {field_name}.quality_status")
    for key in ("requested_budget_rub", "allocated_budget_rub", "unallocated_budget_rub"):
        _non_negative((scenario.get("budget") or {}).get(key), f"{field_name}.budget.{key}")
    metrics = scenario.get("metrics")
    if not isinstance(metrics, Mapping):
        raise JobResultViewContractError(f"{field_name}.metrics must be an object")
    metric_semantics = {
        "incremental_turnover_rub": ("RUB", "primary", None),
        "incremental_orders": ("orders", "diagnostic_only", None),
        "orders_per_100k_rub": (
            "orders_per_100k_RUB",
            "diagnostic_only",
            "orders_quantile_divided_by_deterministic_budget_v1",
        ),
        "avg_basket_delta_rub": ("RUB_per_order", "unavailable", None),
        "avg_basket_turnover_bridge_rub": (
            "turnover_bridge_from_avg_basket_rub",
            "diagnostic_only",
            None,
        ),
        "roas": ("ratio", "primary", None),
    }
    for metric_id, (unit, usage, formula_version) in metric_semantics.items():
        metric = metrics.get(metric_id)
        if not isinstance(metric, Mapping):
            raise JobResultViewContractError(f"{field_name}.metrics.{metric_id} is required")
        _validate_quantile_metric(metric, f"{field_name}.metrics.{metric_id}")
        if (
            metric.get("unit") != unit
            or metric.get("usage") != usage
            or metric.get("formula_version") != formula_version
        ):
            raise JobResultViewContractError(
                f"{field_name}.metrics.{metric_id} has incompatible semantics"
            )
    if scenario.get("status") == "completed" and metrics["incremental_turnover_rub"].get("status") != "available":
        raise JobResultViewContractError(f"{field_name} completed scenario requires turnover")
    if scenario.get("status") != "completed" and any(
        metric.get("status") == "available" for metric in metrics.values()
    ):
        raise JobResultViewContractError(f"{field_name} unavailable scenario contains metrics")
    for rank_name in ("safe_rank", "raw_rank"):
        rank = scenario.get(rank_name)
        if rank is not None and (isinstance(rank, bool) or not isinstance(rank, int) or rank < 1):
            raise JobResultViewContractError(f"{field_name}.{rank_name} must be a positive integer")
    reliability = scenario.get("reliability")
    if not isinstance(reliability, Mapping) or reliability.get("score") is not None:
        raise JobResultViewContractError(f"{field_name}.reliability score must remain unavailable")


def _aggregate_total(rows: list[Mapping[str, Any]], key: str) -> float:
    return sum(float(row[key]) for row in rows)


def _validate_budget_comparison(row: Mapping[str, Any], field_name: str) -> None:
    source = _non_negative(row.get("source_budget_rub"), f"{field_name}.source_budget_rub")
    selected = _non_negative(row.get("selected_budget_rub"), f"{field_name}.selected_budget_rub")
    delta = _finite(row.get("delta_rub"), f"{field_name}.delta_rub")
    if abs((selected - source) - delta) > 0.01:
        raise JobResultViewContractError(f"{field_name}.delta_rub does not reconcile")
    delta_pct = row.get("delta_pct")
    if source == 0:
        if delta_pct is not None:
            raise JobResultViewContractError(f"{field_name}.delta_pct must be null")
    else:
        expected = delta / source * 100.0
        actual = _finite(delta_pct, f"{field_name}.delta_pct")
        if abs(actual - expected) > 1e-6:
            raise JobResultViewContractError(f"{field_name}.delta_pct does not reconcile")


def validate_job_result_view_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate and return one browser-safe result-view payload."""

    if payload.get("contract_name") != CONTRACT_NAME:
        raise JobResultViewContractError("Unknown job result-view contract")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise JobResultViewContractError("Unsupported job result-view schema version")
    if payload.get("record_origin") not in RECORD_ORIGINS:
        raise JobResultViewContractError("Unknown job result-view record_origin")
    _opaque_id(payload.get("job_id"), "job_id")
    _opaque_id(payload.get("result_id"), "result_id")
    _opaque_id(payload.get("source_overview_id"), "source_overview_id")
    _timestamp(payload.get("updated_at_utc"), "updated_at_utc")

    campaign = payload.get("campaign")
    if not isinstance(campaign, Mapping):
        raise JobResultViewContractError("campaign is required")
    _opaque_id(campaign.get("campaign_id"), "campaign.campaign_id")
    _required_text(campaign.get("campaign_name"), "campaign.campaign_name")
    _non_negative(campaign.get("total_budget_rub"), "campaign.total_budget_rub")

    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list) or [row.get("scenario_id") for row in scenarios] != list(SCENARIO_IDS):
        raise JobResultViewContractError("scenarios must be ordered S01-S06")
    for index, scenario in enumerate(scenarios):
        _validate_scenario(scenario, f"scenarios[{index}]")

    for rank_name in ("safe_rank", "raw_rank"):
        ranks = [row[rank_name] for row in scenarios if row.get(rank_name) is not None]
        if len(ranks) != len(set(ranks)):
            raise JobResultViewContractError(f"Scenario {rank_name} values must be unique")

    recommendation = payload.get("recommendation")
    if not isinstance(recommendation, Mapping):
        raise JobResultViewContractError("recommendation is required")
    recommendation_status = recommendation.get("status")
    if recommendation_status not in {"recommended", "no_safe_recommendation", "unavailable"}:
        raise JobResultViewContractError("Unknown recommendation.status")
    recommended_flags = [row["scenario_id"] for row in scenarios if row.get("is_recommended") is True]
    if recommendation_status == "recommended":
        scenario_id = recommendation.get("scenario_id")
        if scenario_id not in SCENARIO_IDS or recommended_flags != [scenario_id]:
            raise JobResultViewContractError("Recommended scenario is inconsistent")
    elif recommendation.get("scenario_id") is not None or recommended_flags:
        raise JobResultViewContractError("Unavailable recommendation must not select a scenario")

    best_safe_flags = [row["scenario_id"] for row in scenarios if row.get("is_best_safe") is True]
    best_safe = recommendation.get("best_safe") or {}
    if best_safe.get("available"):
        if best_safe.get("scenario_id") not in SCENARIO_IDS or best_safe_flags != [best_safe.get("scenario_id")]:
            raise JobResultViewContractError("Best-safe scenario is inconsistent")
    elif best_safe_flags:
        raise JobResultViewContractError("Best-safe flag requires canonical evidence")
    if (
        recommendation_status == "recommended"
        and recommendation.get("scenario_id") == "S06"
        and not best_safe.get("available")
    ):
        raise JobResultViewContractError("Recommended S06 requires canonical best-safe evidence")

    best_raw = payload.get("best_raw")
    if not isinstance(best_raw, Mapping):
        raise JobResultViewContractError("best_raw is required")
    if best_raw.get("available"):
        if best_raw.get("scenario_id") != "S06" or not isinstance(best_raw.get("metrics"), Mapping):
            raise JobResultViewContractError("Available best_raw is inconsistent")
        cells = best_raw.get("blocking_cells")
        cells_status = best_raw.get("blocking_cells_status")
        if not isinstance(cells, list) or (
            (cells_status == "available" and not cells)
            or (cells_status in {"unavailable", "not_applicable"} and cells)
        ):
            raise JobResultViewContractError("best_raw blocking cells are inconsistent")
    elif any(
        best_raw.get(key) is not None
        for key in ("scenario_id", "raw_rank", "safe_rank", "reason_not_recommended", "metrics")
    ) or best_raw.get("blocking_cells") not in ([], ()):
        raise JobResultViewContractError("Unavailable best_raw must not expose candidate data")

    overview = payload.get("overview")
    if not isinstance(overview, Mapping):
        raise JobResultViewContractError("overview is required")
    if overview.get("source_scenario_id") != "S01" or overview.get("benchmark_scenario_id") != "S05":
        raise JobResultViewContractError("Overview source and benchmark scenarios are fixed")
    selected_id = overview.get("selected_scenario_id")
    selected = next((row for row in scenarios if row["scenario_id"] == selected_id), None)
    if selected is None or selected.get("status") != "completed":
        raise JobResultViewContractError("Overview selected scenario must be available")

    source_budget = next(row for row in scenarios if row["scenario_id"] == "S01")["budget"]["allocated_budget_rub"]
    selected_budget = selected["budget"]["allocated_budget_rub"]
    for aggregate_name in ("channel_summary", "geo_summary", "geo_channel_summary"):
        rows = overview.get(aggregate_name)
        if not isinstance(rows, list) or not rows:
            raise JobResultViewContractError(f"overview.{aggregate_name} must not be empty")
        for index, row in enumerate(rows):
            _validate_budget_comparison(row, f"overview.{aggregate_name}[{index}]")
        if abs(_aggregate_total(rows, "source_budget_rub") - float(source_budget)) > 1.0:
            raise JobResultViewContractError(f"overview.{aggregate_name} source budget does not reconcile")
        if abs(_aggregate_total(rows, "selected_budget_rub") - float(selected_budget)) > 1.0:
            raise JobResultViewContractError(f"overview.{aggregate_name} selected budget does not reconcile")

    reliability = payload.get("reliability")
    if not isinstance(reliability, Mapping) or reliability.get("score") is not None:
        raise JobResultViewContractError("Reliability score must remain unavailable")
    components = reliability.get("components")
    expected_components = {
        "historical_support",
        "model_support",
        "extrapolation",
        "posterior_uncertainty",
        "business_constraints",
        "data_completeness",
    }
    if not isinstance(components, list) or {row.get("component_id") for row in components} != expected_components:
        raise JobResultViewContractError("Reliability components are incomplete")
    if any(row.get("score") is not None for row in components):
        raise JobResultViewContractError("Reliability component scores are not approved")

    report = payload.get("report")
    if not isinstance(report, Mapping) or report.get("status") not in {"ready", "failed", "unavailable"}:
        raise JobResultViewContractError("Unknown report status")
    artifact = report.get("artifact")
    if report.get("status") == "ready" and not isinstance(artifact, Mapping):
        raise JobResultViewContractError("Ready report requires an artifact")
    if report.get("status") != "ready" and (
        artifact is not None or report.get("sheets") not in ([], ())
    ):
        raise JobResultViewContractError("Unavailable or failed report must not expose artifacts or sheets")
    if isinstance(artifact, Mapping):
        expected_path = f"/api/v1/artifacts/{artifact.get('artifact_id')}/download"
        if artifact.get("download_path") != expected_path:
            raise JobResultViewContractError("Report download path is not canonical")
    working = report.get("working_media_plan") or {}
    working_artifact = working.get("artifact")
    if working.get("status") == "ready" and not isinstance(working_artifact, Mapping):
        raise JobResultViewContractError("Ready working media plan requires an artifact")
    if working.get("status") == "unavailable" and working_artifact is not None:
        raise JobResultViewContractError("Unavailable working media plan must not expose an artifact")

    warnings = payload.get("warnings")
    if not isinstance(warnings, list):
        raise JobResultViewContractError("warnings must be an array")
    warning_codes = []
    for index, warning in enumerate(warnings):
        if not isinstance(warning, Mapping):
            raise JobResultViewContractError(f"warnings[{index}] must be an object")
        warning_codes.append(_required_text(warning.get("code"), f"warnings[{index}].code"))
        if warning.get("severity") not in {"info", "caution", "manual_review", "blocking"}:
            raise JobResultViewContractError(f"Unknown warnings[{index}].severity")
        for key in ("title", "display_text", "recommended_action", "scope"):
            _required_text(warning.get(key), f"warnings[{index}].{key}")
    if len(warning_codes) != len(set(warning_codes)):
        raise JobResultViewContractError("warning codes must be unique")

    map_view = (payload.get("media_plan") or {}).get("map") or {}
    if map_view.get("status") == "unavailable" and map_view.get("geo_points") is not None:
        raise JobResultViewContractError("Unavailable map must not contain coordinates")
    _reject_paths(payload)
    return payload
