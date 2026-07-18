"""Semantic validation for the browser historical-model geo-budget contract."""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping


CONTRACT_NAME = "historical_model_geo_budget_v1"
SCHEMA_VERSION = "1.0.0"
TITLE = "Исторический рекламный бюджет в данных модели"
_ABSOLUTE_PATH_RE = re.compile(r"^(?:/|[A-Za-z]:[\\/]|file://)")


class HistoricalModelGeoBudgetContractError(ValueError):
    """Raised when an endpoint payload violates historical-budget semantics."""


def load_historical_model_geo_budget_v1_schema() -> dict[str, Any]:
    path = Path(__file__).with_name("historical_model_geo_budget_v1.schema.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise HistoricalModelGeoBudgetContractError("Contract schema must be an object")
    return payload


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HistoricalModelGeoBudgetContractError(f"{field} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise HistoricalModelGeoBudgetContractError(f"{field} must be finite")
    return parsed


def _finite(value: Any, field: str) -> float:
    parsed = _number(value, field)
    if parsed < 0:
        raise HistoricalModelGeoBudgetContractError(f"{field} must be non-negative")
    return parsed


def _non_negative_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HistoricalModelGeoBudgetContractError(
            f"{field} must be a non-negative integer"
        )
    return value


def _reject_unsafe(value: Any, field: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).casefold()
            if normalized in {"campaigns_n", "campaign_count", "campaign_id"}:
                raise HistoricalModelGeoBudgetContractError(
                    f"Campaign-count semantics are forbidden at {field}.{key}"
                )
            _reject_unsafe(nested, f"{field}.{key}")
        return
    if isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_unsafe(nested, f"{field}[{index}]")
        return
    if isinstance(value, str) and _ABSOLUTE_PATH_RE.match(value):
        raise HistoricalModelGeoBudgetContractError(
            f"Local or absolute path is forbidden at {field}"
        )


def _parse_date(value: Any, field: str) -> date:
    if not isinstance(value, str):
        raise HistoricalModelGeoBudgetContractError(f"{field} must be a date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HistoricalModelGeoBudgetContractError(f"{field} is invalid") from exc


def validate_historical_model_geo_budget_v1(
    payload: Mapping[str, Any],
) -> Mapping[str, Any]:
    if payload.get("contract_name") != CONTRACT_NAME or payload.get(
        "schema_version"
    ) != SCHEMA_VERSION:
        raise HistoricalModelGeoBudgetContractError("Historical geo-budget contract mismatch")
    if payload.get("title") != TITLE:
        raise HistoricalModelGeoBudgetContractError("Historical geo-budget title is invalid")
    origin = payload.get("record_origin")
    status = payload.get("status")
    if origin not in {
        "verified_model_package_artifact",
        "model_package_artifact_unavailable",
    }:
        raise HistoricalModelGeoBudgetContractError("record_origin is invalid")
    if status not in {"available", "partial", "unavailable"}:
        raise HistoricalModelGeoBudgetContractError("status is invalid")
    rows = payload.get("rows")
    limitations = payload.get("limitations")
    coverage = payload.get("coverage")
    if not isinstance(rows, list) or not isinstance(limitations, list):
        raise HistoricalModelGeoBudgetContractError("rows and limitations must be arrays")
    if not isinstance(coverage, Mapping):
        raise HistoricalModelGeoBudgetContractError("coverage must be an object")
    if coverage.get("status") != status:
        raise HistoricalModelGeoBudgetContractError("Coverage and payload statuses differ")

    if origin == "model_package_artifact_unavailable":
        if status != "unavailable" or rows or payload.get("geographies_n") != 0:
            raise HistoricalModelGeoBudgetContractError(
                "Missing package artifact must be an empty unavailable payload"
            )
        for field in (
            "artifact_id",
            "artifact_version",
            "period_start",
            "period_end",
            "spend_columns_version",
            "total_budget_rub",
            "updated_at_utc",
        ):
            if payload.get(field) is not None:
                raise HistoricalModelGeoBudgetContractError(
                    f"Unavailable payload field must be null: {field}"
                )
        if (
            coverage.get("located_geographies_n") != 0
            or coverage.get("unlocated_geographies_n") != 0
            or coverage.get("unlocated_geographies") != []
            or coverage.get("located_budget_rub") != 0.0
            or coverage.get("unlocated_budget_rub") != 0.0
            or coverage.get("unlocated_budget_share") is not None
        ):
            raise HistoricalModelGeoBudgetContractError(
                "Unavailable coverage must not contain fabricated data"
            )
        _reject_unsafe(payload)
        return payload

    period_start = _parse_date(payload.get("period_start"), "period_start")
    period_end = _parse_date(payload.get("period_end"), "period_end")
    if period_start > period_end:
        raise HistoricalModelGeoBudgetContractError("Historical period is reversed")
    updated = payload.get("updated_at_utc")
    try:
        parsed_updated = datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
    except ValueError as exc:
        raise HistoricalModelGeoBudgetContractError("updated_at_utc is invalid") from exc
    if parsed_updated.tzinfo is None:
        raise HistoricalModelGeoBudgetContractError("updated_at_utc must include timezone")
    total_budget = _finite(payload.get("total_budget_rub"), "total_budget_rub")
    geographies_n = _non_negative_integer(payload.get("geographies_n"), "geographies_n")
    if not rows or geographies_n != len(rows):
        raise HistoricalModelGeoBudgetContractError("Geography row count does not reconcile")

    seen_ids: set[str] = set()
    row_budget = 0.0
    row_share = 0.0
    located_budget = 0.0
    unlocated_budget = 0.0
    unlocated_identities: list[tuple[str, str]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise HistoricalModelGeoBudgetContractError(f"rows[{index}] must be an object")
        geo_id = str(row.get("geo_id") or "")
        geo_name = str(row.get("geo_display_name") or "").strip()
        if not geo_id or not geo_name or geo_id in seen_ids:
            raise HistoricalModelGeoBudgetContractError("Geography identities are invalid")
        seen_ids.add(geo_id)
        budget = _finite(
            row.get("historical_total_budget_rub"),
            f"rows[{index}].historical_total_budget_rub",
        )
        share = _finite(row.get("budget_share"), f"rows[{index}].budget_share")
        if share > 1:
            raise HistoricalModelGeoBudgetContractError("Budget share exceeds one")
        active_days = _non_negative_integer(
            row.get("active_days_n"), f"rows[{index}].active_days_n"
        )
        active_rows = _non_negative_integer(
            row.get("active_rows_n"), f"rows[{index}].active_rows_n"
        )
        if active_days > active_rows:
            raise HistoricalModelGeoBudgetContractError(
                "Active days cannot exceed active source rows"
            )
        coordinates_status = row.get("coordinates_status")
        if coordinates_status == "canonical":
            latitude = _number(row.get("latitude"), f"rows[{index}].latitude")
            longitude = _number(row.get("longitude"), f"rows[{index}].longitude")
            if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                raise HistoricalModelGeoBudgetContractError(
                    "Canonical coordinates are outside their domain"
                )
            located_budget += budget
        elif coordinates_status == "unavailable":
            if row.get("latitude") is not None or row.get("longitude") is not None:
                raise HistoricalModelGeoBudgetContractError(
                    "Unavailable coordinates must be null"
                )
            unlocated_budget += budget
            unlocated_identities.append((geo_id, geo_name))
        else:
            raise HistoricalModelGeoBudgetContractError("coordinates_status is invalid")
        row_budget += budget
        row_share += share

    tolerance = max(0.01, total_budget * 1e-12)
    if abs(row_budget - total_budget) > tolerance:
        raise HistoricalModelGeoBudgetContractError("Historical budget does not reconcile")
    expected_share = 1.0 if total_budget > 0 else 0.0
    if abs(row_share - expected_share) > 1e-8:
        raise HistoricalModelGeoBudgetContractError("Historical budget shares do not reconcile")
    located_n = geographies_n - len(unlocated_identities)
    expected_status = (
        "available"
        if located_n == geographies_n
        else "partial"
        if located_n > 0
        else "unavailable"
    )
    if status != expected_status:
        raise HistoricalModelGeoBudgetContractError("Coverage status is inconsistent")
    if coverage.get("located_geographies_n") != located_n or coverage.get(
        "unlocated_geographies_n"
    ) != len(unlocated_identities):
        raise HistoricalModelGeoBudgetContractError("Coverage geography counts do not reconcile")
    published_unlocated = sorted(
        (
            str(row.get("geo_id") or ""),
            str(row.get("geo_display_name") or ""),
        )
        for row in coverage.get("unlocated_geographies") or []
        if isinstance(row, Mapping)
    )
    if published_unlocated != sorted(unlocated_identities):
        raise HistoricalModelGeoBudgetContractError("Unlocated geography evidence differs")
    if abs(_finite(coverage.get("located_budget_rub"), "located_budget_rub") - located_budget) > tolerance:
        raise HistoricalModelGeoBudgetContractError("Located budget does not reconcile")
    if abs(_finite(coverage.get("unlocated_budget_rub"), "unlocated_budget_rub") - unlocated_budget) > tolerance:
        raise HistoricalModelGeoBudgetContractError("Unlocated budget does not reconcile")
    expected_unlocated_share = unlocated_budget / total_budget if total_budget > 0 else None
    if expected_unlocated_share is None:
        if coverage.get("unlocated_budget_share") is not None:
            raise HistoricalModelGeoBudgetContractError("Zero-budget share must be null")
    elif abs(
        _finite(coverage.get("unlocated_budget_share"), "unlocated_budget_share")
        - expected_unlocated_share
    ) > 1e-8:
        raise HistoricalModelGeoBudgetContractError("Unlocated budget share differs")
    limitation_codes = [
        str(row.get("code") or "") for row in limitations if isinstance(row, Mapping)
    ]
    if len(limitation_codes) != len(limitations) or len(set(limitation_codes)) != len(
        limitation_codes
    ):
        raise HistoricalModelGeoBudgetContractError("Limitations must have unique codes")
    _reject_unsafe(payload)
    return payload


__all__ = [
    "CONTRACT_NAME",
    "SCHEMA_VERSION",
    "TITLE",
    "HistoricalModelGeoBudgetContractError",
    "load_historical_model_geo_budget_v1_schema",
    "validate_historical_model_geo_budget_v1",
]
