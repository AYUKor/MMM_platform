"""Validators for turnover-only product semantics and map-ready data contracts."""

from __future__ import annotations

import json
import math
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable


WEB_APP_DIR = Path(__file__).resolve().parents[1]
PYMC_CODE_DIR = WEB_APP_DIR.parent / "02_Code" / "01_PyMC"
if str(PYMC_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(PYMC_CODE_DIR))

from mmm_core.serving_semantics import (  # noqa: E402
    ACTIVE_SERVING_MODELS_N,
    CHANNEL_CATALOG_VERSION,
    CHANNEL_DISPLAY_NAMES,
    RESEARCH_MODELS_N,
    SERVING_CORE_TARGET,
    SERVING_TARGET_ID,
)


SCHEMA_VERSION = "2.0.0"
JOB_RESULT_VIEW_CONTRACT = "job_result_view_v2"
VALIDATION_RESULT_CONTRACT = "validation_result_v2"
MODEL_PASSPORT_CONTRACT = "model_passport_v2"
MODEL_OVERVIEW_CONTRACT = "model_overview_v2"
GEO_CATALOG_CONTRACT = "geo_catalog_v1"
WORKSPACE_GEO_BUDGET_CONTRACT = "workspace_geo_budget_v1"
SCENARIO_MEDIA_PLAN_CONTRACT = "scenario_media_plan_v2"
SCENARIO_IDS = ("S01", "S02", "S03", "S04", "S05", "S06")
DECISION_STATUSES = {
    "recommended_reallocation",
    "keep_uploaded_plan",
    "manual_review_required",
    "no_safe_recommendation",
    "unavailable",
}
REVIEW_STATUSES = {"not_required", "manual_review_required"}
RISK_TOLERANCE_RUB = 1.0
SHARE_TOLERANCE = 1e-8

_ABSOLUTE_PATH_RE = re.compile(r"^(?:/|[A-Za-z]:[\\/]|file://)")
_TRUNCATED_LIST_RE = re.compile(r"\.\.\.\s*еще\s+\d+", re.IGNORECASE)
_FORBIDDEN_PRIMARY_KEYS = {
    "orders_per_user",
    "incremental_orders",
    "additional_orders",
    "orders_per_100k_rub",
    "avg_basket",
    "average_basket",
    "avg_basket_delta_rub",
    "avg_basket_turnover_bridge_rub",
    "turnover_bridge_from_avg_basket_rub",
}
_FORBIDDEN_KEY_TOKENS = (
    "orders_per_user",
    "incremental_orders",
    "additional_orders",
    "orders_per_100k",
    "avg_basket",
    "average_basket",
    "turnover_bridge_from_avg_basket",
)
_FORBIDDEN_TEXT = (
    "часть дополнительного оборота",
    "orders_per_user",
    "avg_basket",
    "average basket",
)
_PRESENTATION_FIELDS = {
    "display_text",
    "title",
    "name",
    "description",
    "what",
    "why",
    "recommended_action",
    "decision_scope_text",
}


class BusinessSemanticsContractError(ValueError):
    """Raised when a v2 product projection violates business semantics."""


def _schema(name: str) -> dict[str, Any]:
    path = Path(__file__).with_name(name)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BusinessSemanticsContractError(f"Schema {name} must contain an object")
    return value


def load_job_result_view_v2_schema() -> dict[str, Any]:
    return _schema("job_result_view_v2.schema.json")


def load_validation_result_v2_schema() -> dict[str, Any]:
    return _schema("validation_result_v2.schema.json")


def load_model_passport_v2_schema() -> dict[str, Any]:
    return _schema("model_passport_v2.schema.json")


def load_model_overview_v2_schema() -> dict[str, Any]:
    return _schema("model_overview_v2.schema.json")


def load_geo_catalog_v1_schema() -> dict[str, Any]:
    return _schema("geo_catalog_v1.schema.json")


def load_workspace_geo_budget_v1_schema() -> dict[str, Any]:
    return _schema("workspace_geo_budget_v1.schema.json")


def load_scenario_media_plan_v2_schema() -> dict[str, Any]:
    return _schema("scenario_media_plan_v2.schema.json")


def _finite(value: Any, field: str, *, nullable: bool = False) -> float | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BusinessSemanticsContractError(f"{field} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise BusinessSemanticsContractError(f"{field} must be finite")
    return parsed


def _non_negative(value: Any, field: str, *, nullable: bool = False) -> float | None:
    parsed = _finite(value, field, nullable=nullable)
    if parsed is not None and parsed < 0:
        raise BusinessSemanticsContractError(f"{field} must be non-negative")
    return parsed


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BusinessSemanticsContractError(f"{field} is required")
    return value.strip()


def _is_local_absolute_path(value: str) -> bool:
    if value.startswith("/api/"):
        return False
    return bool(_ABSOLUTE_PATH_RE.match(value))


def _reject_unsafe(value: Any, field: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized_key = str(key).lower()
            if normalized_key in _FORBIDDEN_PRIMARY_KEYS or any(
                token in normalized_key for token in _FORBIDDEN_KEY_TOKENS
            ):
                raise BusinessSemanticsContractError(
                    f"Diagnostic target field is forbidden in turnover-only contract: {field}.{key}"
                )
            if normalized_key in _PRESENTATION_FIELDS and isinstance(nested, str):
                for channel_id in ("Digital_Performance", "OOH_Total"):
                    if channel_id in nested:
                        raise BusinessSemanticsContractError(
                            f"Raw channel ID is forbidden in presentation text at {field}.{key}"
                        )
            _reject_unsafe(nested, f"{field}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_unsafe(nested, f"{field}[{index}]")
    elif isinstance(value, str):
        normalized = value.lower().replace("ё", "е")
        if _TRUNCATED_LIST_RE.search(normalized):
            raise BusinessSemanticsContractError(
                f"Presentation-truncated list is forbidden at {field}"
            )
        if _is_local_absolute_path(value):
            raise BusinessSemanticsContractError(f"Local path is forbidden at {field}")
        if any(text in normalized for text in _FORBIDDEN_TEXT):
            raise BusinessSemanticsContractError(f"Forbidden diagnostic wording at {field}")


def _channel(value: Mapping[str, Any], field: str) -> None:
    channel_id = _required_text(value.get("channel_id"), f"{field}.channel_id")
    expected = CHANNEL_DISPLAY_NAMES.get(channel_id)
    if expected is None:
        raise BusinessSemanticsContractError(
            f"{field}.channel_id is absent from {CHANNEL_CATALOG_VERSION}"
        )
    if value.get("channel_display_name") != expected:
        raise BusinessSemanticsContractError(f"{field} has an unapproved display name")


def _quantiles(metric: Mapping[str, Any], field: str, *, nullable: bool = False) -> None:
    status = metric.get("status")
    if status not in {"available", "unavailable"}:
        raise BusinessSemanticsContractError(f"{field}.status is invalid")
    values = [metric.get(key) for key in ("p10", "p50", "p90")]
    if status == "unavailable":
        if any(value is not None for value in values):
            raise BusinessSemanticsContractError(f"{field} unavailable values must be null")
        return
    parsed = [_finite(value, f"{field}.{key}") for key, value in zip(("p10", "p50", "p90"), values)]
    if not float(parsed[0]) <= float(parsed[1]) <= float(parsed[2]):
        raise BusinessSemanticsContractError(f"{field} quantiles are out of order")


def _budget(budget: Mapping[str, Any], field: str) -> tuple[float, float, float]:
    requested = float(_non_negative(budget.get("requested_budget_rub"), f"{field}.requested_budget_rub"))
    allocated = float(_non_negative(budget.get("allocated_budget_rub"), f"{field}.allocated_budget_rub"))
    unallocated = float(_non_negative(budget.get("unallocated_budget_rub"), f"{field}.unallocated_budget_rub"))
    if abs(requested - allocated - unallocated) > RISK_TOLERANCE_RUB:
        raise BusinessSemanticsContractError(f"{field} does not reconcile")
    share = _finite(budget.get("allocation_share"), f"{field}.allocation_share", nullable=True)
    expected = allocated / requested if requested > 0 else None
    if expected is None:
        if share is not None:
            raise BusinessSemanticsContractError(f"{field}.allocation_share must be null")
    elif share is None or abs(float(share) - expected) > SHARE_TOLERANCE:
        raise BusinessSemanticsContractError(f"{field}.allocation_share does not reconcile")
    return requested, allocated, unallocated


def _risk(risk: Mapping[str, Any], allocated: float, field: str) -> None:
    budgets = [
        float(_non_negative(risk.get(key), f"{field}.{key}"))
        for key in (
            "within_support_budget_rub",
            "controlled_extrapolation_budget_rub",
            "high_risk_budget_rub",
        )
    ]
    if abs(sum(budgets) - allocated) > RISK_TOLERANCE_RUB:
        raise BusinessSemanticsContractError(f"{field} budgets do not reconcile")
    shares = [
        _finite(risk.get(key), f"{field}.{key}", nullable=True)
        for key in (
            "within_support_share",
            "controlled_extrapolation_share",
            "high_risk_share",
        )
    ]
    if allocated <= 0:
        if any(value is not None for value in shares):
            raise BusinessSemanticsContractError(f"{field} shares must be null")
    else:
        if any(value is None for value in shares) or abs(sum(float(value) for value in shares) - 1.0) > SHARE_TOLERANCE:
            raise BusinessSemanticsContractError(f"{field} shares do not reconcile")


def _roas(roas: Mapping[str, Any], requested: float, allocated: float, turnover: Mapping[str, Any], field: str) -> None:
    allocated_metric = roas.get("allocated_budget")
    requested_metric = roas.get("requested_budget")
    if not isinstance(allocated_metric, Mapping) or not isinstance(requested_metric, Mapping):
        raise BusinessSemanticsContractError(f"{field} metrics are required")
    _quantiles(allocated_metric, f"{field}.allocated_budget")
    _quantiles(requested_metric, f"{field}.requested_budget")
    kind = roas.get("primary_denominator_kind")
    if kind not in {"allocated_budget", "requested_budget"}:
        raise BusinessSemanticsContractError(f"{field}.primary_denominator_kind is invalid")
    denominator = float(_non_negative(roas.get("primary_denominator_budget_rub"), f"{field}.primary_denominator_budget_rub"))
    expected_denominator = allocated if kind == "allocated_budget" else requested
    if abs(denominator - expected_denominator) > RISK_TOLERANCE_RUB:
        raise BusinessSemanticsContractError(f"{field} denominator does not reconcile")
    if turnover.get("status") != "available":
        if allocated_metric.get("status") != "unavailable" or requested_metric.get("status") != "unavailable":
            raise BusinessSemanticsContractError(f"{field} cannot be available without turnover")
        return
    turnover_values = [float(turnover[key]) for key in ("p10", "p50", "p90")]
    for metric, budget, metric_field in (
        (allocated_metric, allocated, "allocated_budget"),
        (requested_metric, requested, "requested_budget"),
    ):
        if budget <= 0:
            if metric.get("status") != "unavailable":
                raise BusinessSemanticsContractError(f"{field}.{metric_field} must be unavailable")
            continue
        expected = [value / budget for value in turnover_values]
        actual = [float(metric[key]) for key in ("p10", "p50", "p90")]
        if any(abs(left - right) > 1e-8 for left, right in zip(expected, actual)):
            raise BusinessSemanticsContractError(f"{field}.{metric_field} uses the wrong denominator")


def validate_job_result_view_v2(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    if payload.get("contract_name") != JOB_RESULT_VIEW_CONTRACT or payload.get("schema_version") != SCHEMA_VERSION:
        raise BusinessSemanticsContractError("Unsupported job_result_view_v2 contract")
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list) or [row.get("scenario_id") for row in scenarios] != list(SCENARIO_IDS):
        raise BusinessSemanticsContractError("Scenarios must be ordered S01-S06")
    s5_rows = [row for row in scenarios if row.get("scenario_id") == "S05"]
    if len(s5_rows) != 1 or s5_rows[0].get("scenario_variant") not in {"full_conservative", "safe_partial"}:
        raise BusinessSemanticsContractError("Exactly one public S5 variant is required")
    scenario_by_id: dict[str, Mapping[str, Any]] = {}
    recommended_rows: list[Mapping[str, Any]] = []
    for index, scenario in enumerate(scenarios):
        field = f"scenarios[{index}]"
        scenario_id = str(scenario.get("scenario_id") or "")
        scenario_by_id[scenario_id] = scenario
        if scenario.get("decision_status") not in DECISION_STATUSES:
            raise BusinessSemanticsContractError(f"{field}.decision_status is invalid")
        if scenario.get("review_status") not in REVIEW_STATUSES:
            raise BusinessSemanticsContractError(f"{field}.review_status is invalid")
        requested, allocated, unallocated = _budget(scenario.get("budget") or {}, f"{field}.budget")
        turnover = scenario.get("incremental_turnover") or {}
        _quantiles(turnover, f"{field}.incremental_turnover")
        _risk(scenario.get("risk_budget") or {}, allocated, f"{field}.risk_budget")
        _roas(scenario.get("roas") or {}, requested, allocated, turnover, f"{field}.roas")
        if scenario.get("scenario_id") == "S01":
            if scenario.get("decision_status") != "keep_uploaded_plan" or scenario.get("review_status") != "manual_review_required" or scenario.get("is_recommended"):
                raise BusinessSemanticsContractError("S1 must remain a manual-review reference plan")
        if scenario.get("scenario_id") == "S05":
            if scenario.get("scenario_variant") == "full_conservative":
                if unallocated > RISK_TOLERANCE_RUB:
                    raise BusinessSemanticsContractError("S5 full_conservative must allocate the full budget")
                if float((scenario.get("risk_budget") or {}).get("high_risk_budget_rub") or 0.0) > RISK_TOLERANCE_RUB:
                    raise BusinessSemanticsContractError("S5 full_conservative cannot contain high-risk budget")
            if scenario.get("scenario_variant") == "safe_partial":
                if (
                    unallocated <= RISK_TOLERANCE_RUB
                    or scenario.get("decision_status") != "no_safe_recommendation"
                    or scenario.get("review_status") != "manual_review_required"
                ):
                    raise BusinessSemanticsContractError("S5 safe_partial must expose an unrecommended remainder")
                if not scenario.get("limiting_constraints"):
                    raise BusinessSemanticsContractError("S5 safe_partial requires limiting constraints")
        if scenario.get("scenario_id") == "S06":
            if scenario.get("status") == "completed" and unallocated > RISK_TOLERANCE_RUB:
                raise BusinessSemanticsContractError("Completed S6 must allocate the full budget")
            if scenario.get("status") != "completed" and allocated > RISK_TOLERANCE_RUB:
                raise BusinessSemanticsContractError("Unavailable S6 cannot publish a partial allocation")
            if scenario.get("is_recommended") and float((scenario.get("risk_budget") or {}).get("high_risk_budget_rub") or 0.0) > RISK_TOLERANCE_RUB:
                raise BusinessSemanticsContractError("Recommended S6 cannot contain high-risk budget")
        if scenario.get("is_recommended"):
            recommended_rows.append(scenario)
    recommendation = payload.get("recommendation") or {}
    if recommendation.get("decision_status") not in DECISION_STATUSES or recommendation.get("review_status") not in REVIEW_STATUSES:
        raise BusinessSemanticsContractError("Recommendation states are invalid")
    recommendation_scenario_id = str(recommendation.get("scenario_id") or "")
    selected = scenario_by_id.get(recommendation_scenario_id)
    if selected is None:
        raise BusinessSemanticsContractError("Recommendation scenario is absent")
    if recommendation_scenario_id == "S01":
        if recommendation.get("decision_status") != "keep_uploaded_plan" or recommendation.get("review_status") != "manual_review_required":
            raise BusinessSemanticsContractError("S1 cannot be a recommended reallocation")
    if recommendation.get("decision_status") == "recommended_reallocation":
        if (
            recommendation.get("review_status") != "not_required"
            or selected.get("status") != "completed"
            or selected.get("decision_status") != "recommended_reallocation"
            or not selected.get("is_recommended")
            or float((selected.get("budget") or {}).get("unallocated_budget_rub") or 0.0) > RISK_TOLERANCE_RUB
            or float((selected.get("risk_budget") or {}).get("high_risk_budget_rub") or 0.0) > RISK_TOLERANCE_RUB
        ):
            raise BusinessSemanticsContractError("Recommended reallocation is not a complete policy-safe plan")
        if len(recommended_rows) != 1:
            raise BusinessSemanticsContractError("Exactly one scenario must carry the recommendation flag")
    elif recommended_rows:
        raise BusinessSemanticsContractError("A non-reallocation decision cannot mark a scenario recommended")
    campaign = payload.get("campaign") or {}
    channels = campaign.get("channels") or []
    for index, channel in enumerate(channels):
        _channel(channel, f"campaign.channels[{index}]")
    geographies = campaign.get("geographies") or []
    if len({row.get("geo_id") for row in geographies}) != len(geographies):
        raise BusinessSemanticsContractError("Campaign geographies are duplicated")
    if int(campaign.get("geographies_n") or -1) != len(geographies):
        raise BusinessSemanticsContractError("Campaign geography count does not reconcile")
    map_payload = payload.get("map") or {}
    map_points = map_payload.get("geo_points") or []
    map_ids: set[str] = set()
    for index, point in enumerate(map_points):
        point_id = _required_text(point.get("geo_id"), f"map.geo_points[{index}].geo_id")
        if point_id in map_ids:
            raise BusinessSemanticsContractError("Result map contains duplicate geographies")
        map_ids.add(point_id)
        _coordinates(point, f"map.geo_points[{index}]")
    campaign_ids = {str(row.get("geo_id") or "") for row in geographies}
    if map_ids != campaign_ids:
        raise BusinessSemanticsContractError("Result map geographies do not reconcile with campaign")
    located_points = sum(
        point.get("coordinates_status") == "canonical" for point in map_points
    )
    expected_map_status = (
        "available"
        if map_points and located_points == len(map_points)
        else "partial"
        if located_points
        else "unavailable"
    )
    if map_payload.get("status") != expected_map_status:
        raise BusinessSemanticsContractError("Result map availability is inconsistent")
    _reject_unsafe(payload)
    return payload


def validate_validation_result_v2(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    if payload.get("contract_name") != VALIDATION_RESULT_CONTRACT or payload.get("schema_version") != SCHEMA_VERSION:
        raise BusinessSemanticsContractError("Unsupported validation_result_v2 contract")
    file_validation = payload.get("file_validation") or {}
    if file_validation.get("status") not in {"passed", "warning", "failed", "unavailable"}:
        raise BusinessSemanticsContractError("File validation status is invalid")
    if bool(payload.get("job_creation_allowed")) and file_validation.get("status") == "failed":
        raise BusinessSemanticsContractError("Failed file validation cannot allow calculation")
    limitations = payload.get("model_limitations") or []
    seen: set[tuple[str, str, str]] = set()
    for index, limitation in enumerate(limitations):
        if limitation.get("target") != SERVING_TARGET_ID:
            raise BusinessSemanticsContractError("Only turnover limitations may be served")
        _channel(limitation, f"model_limitations[{index}]")
        geos = limitation.get("affected_geos") or []
        if int(limitation.get("affected_geos_n") or -1) != len(geos):
            raise BusinessSemanticsContractError("Model limitation geography count does not reconcile")
        key = (
            str(limitation.get("target")),
            str(limitation.get("channel_id")),
            str(limitation.get("limitation_type")),
        )
        if key in seen:
            raise BusinessSemanticsContractError("Duplicate model limitation group")
        seen.add(key)
    geo_points = payload.get("geo_points") or []
    if int(file_validation.get("geographies_n") or 0) != len(geo_points):
        raise BusinessSemanticsContractError("Validation geo count does not reconcile")
    requested = float(_non_negative(file_validation.get("requested_budget_rub"), "file_validation.requested_budget_rub"))
    geo_ids: set[str] = set()
    geo_names: set[str] = set()
    total = 0.0
    for index, row in enumerate(geo_points):
        field = f"geo_points[{index}]"
        geo_id = _required_text(row.get("geo_id"), f"{field}.geo_id")
        geo_name = _required_text(row.get("geo_display_name"), f"{field}.geo_display_name")
        if geo_id in geo_ids or geo_name in geo_names:
            raise BusinessSemanticsContractError("Validation geo points contain duplicates")
        geo_ids.add(geo_id)
        geo_names.add(geo_name)
        _coordinates(row, field)
        for channel_index, channel in enumerate(row.get("channels") or []):
            _channel(channel, f"{field}.channels[{channel_index}]")
        budget = float(_non_negative(row.get("budget_rub"), f"{field}.budget_rub"))
        share = _finite(row.get("budget_share"), f"{field}.budget_share", nullable=True)
        expected_share = budget / requested if requested > 0 else None
        if expected_share is None and share is not None:
            raise BusinessSemanticsContractError("Validation zero-total geo shares must be null")
        if expected_share is not None and (
            share is None or abs(float(share) - expected_share) > SHARE_TOLERANCE
        ):
            raise BusinessSemanticsContractError("Validation geo budget share does not reconcile")
        total += budget
    if abs(total - requested) > RISK_TOLERANCE_RUB:
        raise BusinessSemanticsContractError("Validation geo budgets do not reconcile")
    _reject_unsafe(payload)
    return payload


def _validate_serving_summary(payload: Mapping[str, Any], contract_name: str) -> None:
    if payload.get("contract_name") != contract_name or payload.get("schema_version") != SCHEMA_VERSION:
        raise BusinessSemanticsContractError(f"Unsupported {contract_name} contract")
    serving = payload.get("serving") or {}
    expected = {
        "serving_policy_version": "turnover_serving_v1",
        "target_id": SERVING_TARGET_ID,
        "core_target": SERVING_CORE_TARGET,
        "serving_targets_n": 1,
        "active_serving_models_n": ACTIVE_SERVING_MODELS_N,
        "research_models_in_package_n": RESEARCH_MODELS_N,
    }
    for key, value in expected.items():
        if serving.get(key) != value:
            raise BusinessSemanticsContractError(f"serving.{key} is inconsistent")
    for index, policy in enumerate(payload.get("channel_policies") or []):
        if policy.get("target") != SERVING_TARGET_ID:
            raise BusinessSemanticsContractError("Only turnover channel policies may be served")
        _channel(policy, f"channel_policies[{index}]")
    _reject_unsafe(payload)


def validate_model_passport_v2(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    _validate_serving_summary(payload, MODEL_PASSPORT_CONTRACT)
    return payload


def validate_model_overview_v2(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    _validate_serving_summary(payload, MODEL_OVERVIEW_CONTRACT)
    return payload


def _coordinates(row: Mapping[str, Any], field: str) -> None:
    latitude = _finite(row.get("latitude"), f"{field}.latitude", nullable=True)
    longitude = _finite(row.get("longitude"), f"{field}.longitude", nullable=True)
    status = row.get("coordinates_status")
    if (latitude is None) != (longitude is None):
        raise BusinessSemanticsContractError(f"{field} coordinate pair is incomplete")
    if latitude is None:
        if status != "unavailable":
            raise BusinessSemanticsContractError(f"{field} missing coordinates must be unavailable")
    else:
        if not -90 <= float(latitude) <= 90 or not -180 <= float(longitude) <= 180:
            raise BusinessSemanticsContractError(f"{field} coordinates are out of range")
        if status != "canonical":
            raise BusinessSemanticsContractError(f"{field} coordinates must be canonical")


def validate_geo_catalog_v1(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    if payload.get("contract_name") != GEO_CATALOG_CONTRACT or payload.get("schema_version") != "1.0.0":
        raise BusinessSemanticsContractError("Unsupported geo_catalog_v1 contract")
    entries = payload.get("entries") or []
    ids: set[str] = set()
    names: set[str] = set()
    for index, entry in enumerate(entries):
        geo_id = _required_text(entry.get("geo_id"), f"entries[{index}].geo_id")
        name = _required_text(entry.get("geo_display_name"), f"entries[{index}].geo_display_name")
        if geo_id in ids or name in names:
            raise BusinessSemanticsContractError("Geo catalog contains duplicates")
        ids.add(geo_id)
        names.add(name)
        _coordinates(entry, f"entries[{index}]")
    if int(payload.get("geographies_n") or 0) != len(entries):
        raise BusinessSemanticsContractError("Geo catalog count does not reconcile")
    _reject_unsafe(payload)
    return payload


def validate_workspace_geo_budget_v1(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    if payload.get("contract_name") != WORKSPACE_GEO_BUDGET_CONTRACT or payload.get("schema_version") != "1.0.0":
        raise BusinessSemanticsContractError("Unsupported workspace_geo_budget_v1 contract")
    rows = payload.get("rows") or []
    total = float(_non_negative(payload.get("total_budget_rub"), "total_budget_rub"))
    row_total = sum(float(_non_negative(row.get("total_budget_rub"), "rows.total_budget_rub")) for row in rows)
    if abs(total - row_total) > RISK_TOLERANCE_RUB:
        raise BusinessSemanticsContractError("Workspace geo budgets do not reconcile")
    for index, row in enumerate(rows):
        _coordinates(row, f"rows[{index}]")
        share = _finite(row.get("budget_share"), f"rows[{index}].budget_share", nullable=True)
        expected = float(row["total_budget_rub"]) / total if total > 0 else None
        if expected is None and share is not None:
            raise BusinessSemanticsContractError("Workspace zero-total shares must be null")
        if expected is not None and (share is None or abs(float(share) - expected) > SHARE_TOLERANCE):
            raise BusinessSemanticsContractError("Workspace geo share does not reconcile")
    _reject_unsafe(payload)
    return payload


def validate_scenario_media_plan_v2(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    if (
        payload.get("contract_name") != SCENARIO_MEDIA_PLAN_CONTRACT
        or payload.get("schema_version") != SCHEMA_VERSION
    ):
        raise BusinessSemanticsContractError("Unsupported scenario_media_plan_v2 contract")
    scenario = payload.get("scenario") or {}
    if scenario.get("scenario_id") not in SCENARIO_IDS:
        raise BusinessSemanticsContractError("Media-plan scenario is invalid")
    totals = payload.get("totals") or {}
    requested = float(_non_negative(totals.get("requested_budget_rub"), "totals.requested_budget_rub"))
    selected = float(_non_negative(totals.get("selected_budget_rub"), "totals.selected_budget_rub"))
    unallocated = float(_non_negative(totals.get("unallocated_budget_rub"), "totals.unallocated_budget_rub"))
    if abs(requested - selected - unallocated) > RISK_TOLERANCE_RUB:
        raise BusinessSemanticsContractError("Media-plan requested budget does not reconcile")
    rows = payload.get("rows") or []
    seen_rows: set[tuple[str, str, str]] = set()
    for index, row in enumerate(rows):
        _channel(row, f"rows[{index}]")
        geo_value = _required_text(row.get("geo_display_name"), f"rows[{index}].geo_display_name")
        geo_key = _required_text(row.get("geo_id"), f"rows[{index}].geo_id")
        key = (str(row.get("segment") or ""), geo_key, str(row.get("channel_id") or ""))
        if key in seen_rows:
            raise BusinessSemanticsContractError("Media-plan page contains duplicate rows")
        seen_rows.add(key)
        _required_text(geo_value, f"rows[{index}].geo_display_name")
    aggregates = payload.get("aggregates") or {}
    aggregate_selected = 0.0
    aggregate_source = 0.0
    for index, row in enumerate(aggregates.get("by_geo_channel") or []):
        _channel(row, f"aggregates.by_geo_channel[{index}]")
        _required_text(row.get("geo_id"), f"aggregates.by_geo_channel[{index}].geo_id")
        _required_text(
            row.get("geo_display_name"),
            f"aggregates.by_geo_channel[{index}].geo_display_name",
        )
        aggregate_source += float(
            _non_negative(
                row.get("source_budget_rub"),
                f"aggregates.by_geo_channel[{index}].source_budget_rub",
            )
        )
        aggregate_selected += float(
            _non_negative(
                row.get("selected_budget_rub"),
                f"aggregates.by_geo_channel[{index}].selected_budget_rub",
            )
        )
    if (
        abs(aggregate_source - float(totals.get("source_budget_rub") or 0.0))
        > RISK_TOLERANCE_RUB
        or abs(aggregate_selected - selected) > RISK_TOLERANCE_RUB
    ):
        raise BusinessSemanticsContractError("Media-plan aggregates do not reconcile")
    filters = payload.get("filters") or {}
    channel_filter = filters.get("channel_id")
    if channel_filter is not None and str(channel_filter) not in CHANNEL_DISPLAY_NAMES:
        raise BusinessSemanticsContractError("Media-plan channel filter is outside the catalog")
    _reject_unsafe(payload)
    return payload


SCHEMA_LOADERS: dict[str, Callable[[], dict[str, Any]]] = {
    "job-result-view-v2": load_job_result_view_v2_schema,
    "validation-result-v2": load_validation_result_v2_schema,
    "model-passport-v2": load_model_passport_v2_schema,
    "model-overview-v2": load_model_overview_v2_schema,
    "geo-catalog-v1": load_geo_catalog_v1_schema,
    "workspace-geo-budget-v1": load_workspace_geo_budget_v1_schema,
    "scenario-media-plan-v2": load_scenario_media_plan_v2_schema,
}
