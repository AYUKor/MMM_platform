"""Validation helpers for paginated scenario media-plan projections."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any


CONTRACT_NAME = "scenario_media_plan_v1"
SCHEMA_VERSION = "1.0.0"
SCENARIO_IDS = {"S01", "S02", "S03", "S04", "S05", "S06"}
_OPAQUE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*_[0-9a-f]{12,64}$")
_ABSOLUTE_PATH_RE = re.compile(r"^(?:/|[A-Za-z]:[\\/]|file://)", re.IGNORECASE)


class ScenarioMediaPlanContractError(ValueError):
    """Raised when a media-plan payload is internally inconsistent."""


def _number(value: Any, field_name: str, *, non_negative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScenarioMediaPlanContractError(f"{field_name} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed) or (non_negative and parsed < 0):
        raise ScenarioMediaPlanContractError(f"{field_name} is invalid")
    return parsed


def _opaque_id(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not _OPAQUE_ID_RE.fullmatch(value):
        raise ScenarioMediaPlanContractError(f"{field_name} must be an opaque ID")


def _reject_paths(value: Any, field_name: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            _reject_paths(nested, f"{field_name}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_paths(nested, f"{field_name}[{index}]")
    elif isinstance(value, str) and _ABSOLUTE_PATH_RE.match(value):
        raise ScenarioMediaPlanContractError(f"Local path is forbidden at {field_name}")


def _validate_budget_row(row: Mapping[str, Any], field_name: str) -> None:
    source = _number(row.get("source_budget_rub"), f"{field_name}.source_budget_rub", non_negative=True)
    selected = _number(row.get("selected_budget_rub"), f"{field_name}.selected_budget_rub", non_negative=True)
    delta = _number(row.get("delta_rub"), f"{field_name}.delta_rub")
    if abs((selected - source) - delta) > 0.01:
        raise ScenarioMediaPlanContractError(f"{field_name}.delta_rub does not reconcile")
    expected_pct = None if source == 0 else delta / source * 100.0
    actual_pct = row.get("delta_pct")
    if expected_pct is None:
        if actual_pct is not None:
            raise ScenarioMediaPlanContractError(f"{field_name}.delta_pct must be null")
    elif actual_pct is None or abs(float(actual_pct) - expected_pct) > 1e-6:
        raise ScenarioMediaPlanContractError(f"{field_name}.delta_pct does not reconcile")
    if row.get("quality_status") not in {"safe", "caution", "blocked", "unavailable"}:
        raise ScenarioMediaPlanContractError(f"Unknown {field_name}.quality_status")


def validate_scenario_media_plan_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate and return one media-plan page."""

    if payload.get("contract_name") != CONTRACT_NAME or payload.get("schema_version") != SCHEMA_VERSION:
        raise ScenarioMediaPlanContractError("Unsupported scenario media-plan contract")
    if payload.get("record_origin") not in {"application_runtime", "sanitized_fixture"}:
        raise ScenarioMediaPlanContractError("Unknown scenario media-plan record_origin")
    for field_name in ("job_id", "result_id", "campaign_id"):
        _opaque_id(payload.get(field_name), field_name)
    source_artifact = payload.get("source_artifact") or {}
    _opaque_id(source_artifact.get("artifact_id"), "source_artifact.artifact_id")
    if source_artifact.get("kind") != "recommended_allocations_csv" or not re.fullmatch(
        r"[0-9a-f]{64}", str(source_artifact.get("sha256") or "")
    ):
        raise ScenarioMediaPlanContractError("source_artifact is invalid")
    scenario = payload.get("scenario") or {}
    if scenario.get("scenario_id") not in SCENARIO_IDS or scenario.get("status") != "completed":
        raise ScenarioMediaPlanContractError("Media plan requires an available scenario")
    if payload.get("grain") != "geo_channel_total":
        raise ScenarioMediaPlanContractError("Only geo_channel_total grain is published")
    try:
        updated = datetime.fromisoformat(str(payload.get("updated_at_utc")).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ScenarioMediaPlanContractError("updated_at_utc is invalid") from exc
    if updated.tzinfo is None or updated.utcoffset() is None:
        raise ScenarioMediaPlanContractError("updated_at_utc must include timezone")

    pagination = payload.get("pagination") or {}
    for key in ("page", "page_size", "total_rows", "total_pages"):
        value = pagination.get(key)
        minimum = 1 if key in {"page", "page_size"} else 0
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ScenarioMediaPlanContractError(f"pagination.{key} is invalid")
    rows = payload.get("rows")
    if not isinstance(rows, list) or len(rows) > pagination["page_size"]:
        raise ScenarioMediaPlanContractError("rows do not match pagination")
    keys = []
    for index, row in enumerate(rows):
        if row.get("scenario_id") != scenario.get("scenario_id") or row.get("date") is not None:
            raise ScenarioMediaPlanContractError("Media-plan row has inconsistent scenario or date")
        _validate_budget_row(row, f"rows[{index}]")
        keys.append((row.get("segment"), row.get("geo"), row.get("channel")))
    if keys != sorted(keys):
        raise ScenarioMediaPlanContractError("Media-plan rows must have stable ordering")
    expected_pages = math.ceil(pagination["total_rows"] / pagination["page_size"]) if pagination["total_rows"] else 0
    if pagination["total_pages"] != expected_pages:
        raise ScenarioMediaPlanContractError("pagination.total_pages does not reconcile")
    expected_rows = min(
        pagination["page_size"],
        max(
            pagination["total_rows"]
            - (pagination["page"] - 1) * pagination["page_size"],
            0,
        ),
    )
    if len(rows) != expected_rows:
        raise ScenarioMediaPlanContractError("rows do not reconcile with the requested page")

    aggregates = payload.get("aggregates") or {}
    totals = payload.get("totals") or {}
    requested_total = _number(totals.get("requested_budget_rub"), "totals.requested_budget_rub", non_negative=True)
    source_total = _number(totals.get("source_budget_rub"), "totals.source_budget_rub", non_negative=True)
    selected_total = _number(totals.get("selected_budget_rub"), "totals.selected_budget_rub", non_negative=True)
    unallocated_total = _number(totals.get("unallocated_budget_rub"), "totals.unallocated_budget_rub", non_negative=True)
    delta_total = _number(totals.get("delta_rub"), "totals.delta_rub")
    if abs((selected_total - source_total) - delta_total) > 1.0:
        raise ScenarioMediaPlanContractError("Media-plan total delta does not reconcile")
    if abs((selected_total + unallocated_total) - requested_total) > 1.0:
        raise ScenarioMediaPlanContractError("Requested media-plan budget does not reconcile")
    filtered = payload.get("filtered_totals") or {}
    filtered_source = _number(filtered.get("source_budget_rub"), "filtered_totals.source_budget_rub", non_negative=True)
    filtered_selected = _number(filtered.get("selected_budget_rub"), "filtered_totals.selected_budget_rub", non_negative=True)
    filtered_delta = _number(filtered.get("delta_rub"), "filtered_totals.delta_rub")
    if abs((filtered_selected - filtered_source) - filtered_delta) > 1.0:
        raise ScenarioMediaPlanContractError("Filtered media-plan delta does not reconcile")
    for aggregate_name in ("by_channel", "by_geo", "by_geo_channel"):
        aggregate_rows = aggregates.get(aggregate_name)
        if not isinstance(aggregate_rows, list) or not aggregate_rows:
            raise ScenarioMediaPlanContractError(f"aggregates.{aggregate_name} must not be empty")
        for index, row in enumerate(aggregate_rows):
            _validate_budget_row(row, f"aggregates.{aggregate_name}[{index}]")
        if abs(sum(float(row["source_budget_rub"]) for row in aggregate_rows) - source_total) > 1.0:
            raise ScenarioMediaPlanContractError(f"aggregates.{aggregate_name} source total does not reconcile")
        if abs(sum(float(row["selected_budget_rub"]) for row in aggregate_rows) - selected_total) > 1.0:
            raise ScenarioMediaPlanContractError(f"aggregates.{aggregate_name} selected total does not reconcile")

    for unavailable_name in ("by_date", "channel_date_matrix"):
        block = aggregates.get(unavailable_name) or {}
        if block.get("status") != "unavailable" or block.get("rows") is not None:
            raise ScenarioMediaPlanContractError(f"aggregates.{unavailable_name} must be unavailable")
    map_view = payload.get("map") or {}
    if map_view.get("status") != "unavailable" or map_view.get("geo_points") is not None:
        raise ScenarioMediaPlanContractError("Map must remain unavailable without approved coordinates")
    working = payload.get("working_media_plan") or {}
    if working.get("status") != "unavailable" or working.get("artifact") is not None:
        raise ScenarioMediaPlanContractError(
            "Working media-plan XLSX must remain unavailable without an artifact"
        )
    _reject_paths(payload)
    return payload
