"""Browser-safe paginated calculation history contract."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


CONTRACT_NAME = "calculation_history_v1"
SCHEMA_VERSION = "1.0.0"
RECORD_ORIGINS = {"application_runtime", "synthetic_fixture"}
JOB_STATUSES = {
    "queued",
    "running",
    "cancel_requested",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
}
ACTIVE_STATUSES = {"queued", "running", "cancel_requested"}
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "timed_out"}
STATUS_FILTERS = JOB_STATUSES | {"active"}
SORT_CODES = {"created_desc", "created_asc", "completed_desc", "campaign_asc"}

_OPAQUE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*_[0-9a-f]{12,64}$")
_ABSOLUTE_PATH_RE = re.compile(r"^(?:/|[A-Za-z]:[\\/]|file://)", re.IGNORECASE)
_FORBIDDEN_PRESENTATION_TERMS = (
    "backend",
    "api",
    "worker",
    "stack trace",
    "local path",
    "model package",
    "internal registry",
)


class CalculationHistoryContractError(ValueError):
    """Raised when a calculation-history payload violates public invariants."""


def _mapping(value: Any, field_name: str, keys: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CalculationHistoryContractError(f"{field_name} must be an object")
    if set(value) != keys:
        raise CalculationHistoryContractError(f"{field_name} keys are invalid")
    return value


def _list(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise CalculationHistoryContractError(f"{field_name} must be an array")
    return value


def _text(
    value: Any,
    field_name: str,
    *,
    nullable: bool = False,
    presentation: bool = False,
) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value.strip():
        raise CalculationHistoryContractError(f"{field_name} is required")
    if presentation and any(
        term in value.casefold() for term in _FORBIDDEN_PRESENTATION_TERMS
    ):
        raise CalculationHistoryContractError(f"{field_name} contains internal terminology")
    return value


def _integer(value: Any, field_name: str, *, nullable: bool = False) -> int | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CalculationHistoryContractError(f"{field_name} must be non-negative")
    return value


def _number(value: Any, field_name: str, *, nullable: bool = False) -> float | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise CalculationHistoryContractError(f"{field_name} must be non-negative")
    return float(value)


def _timestamp(value: Any, field_name: str, *, nullable: bool = False) -> datetime | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise CalculationHistoryContractError(f"{field_name} must be an ISO-8601 datetime")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CalculationHistoryContractError(
            f"{field_name} must be an ISO-8601 datetime"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CalculationHistoryContractError(f"{field_name} must include a timezone")
    return parsed


def _iso_date(value: Any, field_name: str, *, nullable: bool = False) -> date | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise CalculationHistoryContractError(f"{field_name} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CalculationHistoryContractError(f"{field_name} must be an ISO date") from exc


def _route(value: Any, field_name: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, str) or not value.startswith("/"):
        raise CalculationHistoryContractError(f"{field_name} must be an internal route")
    parsed = urlsplit(value)
    if (
        parsed.scheme
        or parsed.netloc
        or "\\" in value
        or ".." in parsed.path.split("/")
        or parsed.path.startswith(("/Users/", "/home/", "/private/", "/tmp/", "/var/"))
    ):
        raise CalculationHistoryContractError(f"{field_name} must be an internal route")


def _reject_paths(value: Any, field_name: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            _reject_paths(nested, f"{field_name}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_paths(nested, f"{field_name}[{index}]")
    elif isinstance(value, str) and _ABSOLUTE_PATH_RE.match(value):
        if field_name.endswith("_path"):
            _route(value, field_name)
        else:
            raise CalculationHistoryContractError(f"Local path is forbidden at {field_name}")


def validate_calculation_history_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return one JSON-native calculation-history payload."""

    root = _mapping(
        payload,
        "payload",
        {
            "contract_name",
            "schema_version",
            "record_origin",
            "summary",
            "filters",
            "pagination",
            "items",
            "updated_at_utc",
        },
    )
    if root["contract_name"] != CONTRACT_NAME:
        raise CalculationHistoryContractError("Unknown calculation history contract")
    if root["schema_version"] != SCHEMA_VERSION:
        raise CalculationHistoryContractError("Unsupported calculation history version")
    if root["record_origin"] not in RECORD_ORIGINS:
        raise CalculationHistoryContractError("Unknown calculation history record origin")

    summary = _mapping(
        root["summary"],
        "summary",
        {"all", "active", "succeeded", "failed", "cancelled", "timed_out"},
    )
    for key in summary:
        _integer(summary[key], f"summary.{key}")
    if summary["all"] != sum(
        summary[key] for key in ("active", "succeeded", "failed", "cancelled", "timed_out")
    ):
        raise CalculationHistoryContractError("History summary counts are inconsistent")

    filters = _mapping(
        root["filters"],
        "filters",
        {"status", "search", "created_from", "created_to", "sort"},
    )
    status_filter = _text(filters["status"], "filters.status", nullable=True)
    if status_filter is not None and status_filter not in STATUS_FILTERS:
        raise CalculationHistoryContractError("Unknown history status filter")
    search = _text(filters["search"], "filters.search", nullable=True)
    if search is not None and len(search) > 120:
        raise CalculationHistoryContractError("History search is too long")
    created_from = _iso_date(filters["created_from"], "filters.created_from", nullable=True)
    created_to = _iso_date(filters["created_to"], "filters.created_to", nullable=True)
    if created_from is not None and created_to is not None and created_to < created_from:
        raise CalculationHistoryContractError("History date range is reversed")
    if filters["sort"] not in SORT_CODES:
        raise CalculationHistoryContractError("Unknown history sort code")

    pagination = _mapping(
        root["pagination"],
        "pagination",
        {"page", "page_size", "total_items", "total_pages"},
    )
    page = _integer(pagination["page"], "pagination.page")
    page_size = _integer(pagination["page_size"], "pagination.page_size")
    total_items = _integer(pagination["total_items"], "pagination.total_items")
    total_pages = _integer(pagination["total_pages"], "pagination.total_pages")
    if page is None or page < 1:
        raise CalculationHistoryContractError("pagination.page must be positive")
    if page_size is None or not 1 <= page_size <= 100:
        raise CalculationHistoryContractError("pagination.page_size is invalid")
    expected_pages = math.ceil(total_items / page_size) if total_items else 0
    if total_pages != expected_pages:
        raise CalculationHistoryContractError("pagination.total_pages is inconsistent")

    items = _list(root["items"], "items")
    if len(items) > page_size:
        raise CalculationHistoryContractError("History page contains too many items")
    job_ids: set[str] = set()
    for index, raw in enumerate(items):
        field_name = f"items[{index}]"
        item = _mapping(
            raw,
            field_name,
            {
                "job_id",
                "campaign_name",
                "created_at_utc",
                "completed_at_utc",
                "status",
                "status_display_text",
                "campaign_period",
                "total_budget_rub",
                "segments",
                "channels_n",
                "geographies_n",
                "result_available",
                "report_available",
                "progress_path",
                "result_path",
                "warnings_count",
            },
        )
        job_id = item["job_id"]
        if not isinstance(job_id, str) or not _OPAQUE_ID_RE.fullmatch(job_id):
            raise CalculationHistoryContractError(f"{field_name}.job_id is invalid")
        if job_id in job_ids:
            raise CalculationHistoryContractError("History job IDs must be unique")
        job_ids.add(job_id)
        _text(item["campaign_name"], f"{field_name}.campaign_name")
        created = _timestamp(item["created_at_utc"], f"{field_name}.created_at_utc")
        completed = _timestamp(
            item["completed_at_utc"],
            f"{field_name}.completed_at_utc",
            nullable=True,
        )
        status = item["status"]
        if status not in JOB_STATUSES:
            raise CalculationHistoryContractError(f"{field_name}.status is invalid")
        _text(
            item["status_display_text"],
            f"{field_name}.status_display_text",
            presentation=True,
        )
        if status in TERMINAL_STATUSES and completed is None:
            raise CalculationHistoryContractError(f"{field_name} terminal item needs completed_at")
        if status in ACTIVE_STATUSES and completed is not None:
            raise CalculationHistoryContractError(f"{field_name} active item cannot be completed")
        if completed is not None and created is not None and completed < created:
            raise CalculationHistoryContractError(f"{field_name} timestamps are reversed")
        if item["campaign_period"] is not None:
            period = _mapping(
                item["campaign_period"],
                f"{field_name}.campaign_period",
                {"start_date", "end_date"},
            )
            start = _iso_date(period["start_date"], f"{field_name}.campaign_period.start_date")
            end = _iso_date(period["end_date"], f"{field_name}.campaign_period.end_date")
            if start is not None and end is not None and end < start:
                raise CalculationHistoryContractError(f"{field_name}.campaign_period is reversed")
        _number(item["total_budget_rub"], f"{field_name}.total_budget_rub", nullable=True)
        segments = item["segments"]
        if segments is not None:
            values = _list(segments, f"{field_name}.segments")
            if len(values) != len(set(values)):
                raise CalculationHistoryContractError(f"{field_name}.segments must be unique")
            for value in values:
                _text(value, f"{field_name}.segments")
        _integer(item["channels_n"], f"{field_name}.channels_n", nullable=True)
        _integer(item["geographies_n"], f"{field_name}.geographies_n", nullable=True)
        for key in ("result_available", "report_available"):
            if not isinstance(item[key], bool):
                raise CalculationHistoryContractError(f"{field_name}.{key} must be boolean")
        if item["report_available"] and not item["result_available"]:
            raise CalculationHistoryContractError(f"{field_name} report requires a result")
        if status != "succeeded" and (item["result_available"] or item["report_available"]):
            raise CalculationHistoryContractError(f"{field_name} active/failed result flags are invalid")
        _route(item["progress_path"], f"{field_name}.progress_path")
        _route(item["result_path"], f"{field_name}.result_path", nullable=True)
        if item["result_available"] != (item["result_path"] is not None):
            raise CalculationHistoryContractError(f"{field_name}.result_path is inconsistent")
        _integer(item["warnings_count"], f"{field_name}.warnings_count", nullable=True)

    _timestamp(root["updated_at_utc"], "updated_at_utc")
    _reject_paths(root)
    return json.loads(json.dumps(root, ensure_ascii=False))


def load_calculation_history_schema() -> dict[str, Any]:
    return json.loads(
        Path(__file__).with_name("calculation_history_v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
