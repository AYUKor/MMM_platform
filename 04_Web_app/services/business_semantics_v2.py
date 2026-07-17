"""Browser-safe v2 projections for turnover serving and allocation semantics.

Every builder works from already published application/model evidence.  This
module never calls forecast or optimizer mathematics and never geocodes.
"""

from __future__ import annotations

import csv
import hashlib
import math
import re
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


WEB_APP_DIR = Path(__file__).resolve().parents[1]
PYMC_CODE_DIR = WEB_APP_DIR.parent / "02_Code" / "01_PyMC"
for entry in (WEB_APP_DIR, PYMC_CODE_DIR):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from contracts.business_semantics_v2 import (  # noqa: E402
    GEO_CATALOG_CONTRACT,
    JOB_RESULT_VIEW_CONTRACT,
    MODEL_OVERVIEW_CONTRACT,
    MODEL_PASSPORT_CONTRACT,
    SCHEMA_VERSION,
    SCENARIO_MEDIA_PLAN_CONTRACT,
    VALIDATION_RESULT_CONTRACT,
    WORKSPACE_GEO_BUDGET_CONTRACT,
    validate_geo_catalog_v1,
    validate_job_result_view_v2,
    validate_model_overview_v2,
    validate_model_passport_v2,
    validate_scenario_media_plan_v2,
    validate_validation_result_v2,
    validate_workspace_geo_budget_v1,
)
from mmm_core.serving_semantics import (  # noqa: E402
    ACTIVE_SERVING_MODELS_N,
    CHANNEL_CATALOG_VERSION,
    RESEARCH_MODELS_N,
    SERVING_CORE_TARGET,
    SERVING_POLICY_VERSION,
    SERVING_TARGET_ID,
    channel_identity,
)
from services.job_result_view import (  # noqa: E402
    SCENARIO_COPY,
    _Evidence,
    _all_allocation_rows,
    _candidate_ranks,
    _scenario_candidates,
    _validate_sources,
)


GEO_CATALOG_VERSION = "geo_catalog_v1_unlocated_2026_07"


def _issue_cells(issue: Mapping[str, Any], target: str) -> list[Mapping[str, Any]]:
    return [
        cell
        for cell in issue.get("affected_cells") or []
        if str(cell.get("target") or "") == target
    ]


def _browser_issue_text(
    issue: Mapping[str, Any],
    field: str,
    *,
    channel_id: str,
    channel_display_name: str,
    fallback: str,
) -> str:
    value = str(issue.get(field) or "").strip() or fallback
    return value.replace(channel_id, channel_display_name)


def _contains_diagnostic_metric(value: Any) -> bool:
    text = str(value).casefold()
    return any(
        token in text
        for token in (
            "orders_per_user",
            "avg_basket",
            "average basket",
            "orders_diagnostic",
            "заказ",
            "средний чек",
            "среднего чека",
        )
    )


def geo_id(geo_display_name: str) -> str:
    canonical = str(geo_display_name or "").strip().upper().replace("Ё", "Е")
    if not canonical:
        raise ValueError("Geo display name is required")
    return "geo_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def build_scenario_media_plan_v2(payload_v1: Mapping[str, Any]) -> dict[str, Any]:
    """Project a validated v1 plan into browser-safe channel/geo identities."""

    def plan_row(row: Mapping[str, Any]) -> dict[str, Any]:
        channel = channel_identity(row.get("channel"))
        geo_name = str(row.get("geo") or "").strip()
        return {
            **{
                key: value
                for key, value in row.items()
                if key not in {"channel", "geo"}
            },
            "geo_id": geo_id(geo_name),
            "geo_display_name": geo_name,
            **channel,
        }

    def channel_row(row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            **{key: value for key, value in row.items() if key != "channel"},
            **channel_identity(row.get("channel")),
        }

    def geo_row(row: Mapping[str, Any]) -> dict[str, Any]:
        geo_name = str(row.get("geo") or "").strip()
        return {
            **{key: value for key, value in row.items() if key != "geo"},
            "geo_id": geo_id(geo_name),
            "geo_display_name": geo_name,
        }

    def geo_channel_row(row: Mapping[str, Any]) -> dict[str, Any]:
        return plan_row(row)

    aggregates_v1 = payload_v1.get("aggregates") or {}
    by_geo_channel = [
        geo_channel_row(row) for row in aggregates_v1.get("by_geo_channel") or []
    ]
    payload = {
        **dict(payload_v1),
        "contract_name": SCENARIO_MEDIA_PLAN_CONTRACT,
        "schema_version": SCHEMA_VERSION,
        "filters": {
            "channel_id": (payload_v1.get("filters") or {}).get("channel"),
            "geo_display_name": (payload_v1.get("filters") or {}).get("geo"),
            "date": None,
        },
        "rows": [plan_row(row) for row in payload_v1.get("rows") or []],
        "aggregates": {
            "by_channel": [
                channel_row(row) for row in aggregates_v1.get("by_channel") or []
            ],
            "by_geo": [geo_row(row) for row in aggregates_v1.get("by_geo") or []],
            "by_geo_channel": by_geo_channel,
            "by_date": dict(aggregates_v1.get("by_date") or {}),
            "channel_date_matrix": dict(
                aggregates_v1.get("channel_date_matrix") or {}
            ),
            "geo_channel_matrix": {
                **dict(aggregates_v1.get("geo_channel_matrix") or {}),
                "rows": by_geo_channel,
            },
        },
    }
    validate_scenario_media_plan_v2(payload)
    return payload


def build_geo_catalog(
    geographies: Iterable[str],
    *,
    canonical_coordinates: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a deterministic catalog without runtime geocoding or guessed points."""

    names = sorted({str(value).strip() for value in geographies if str(value).strip()})
    coordinates = dict(canonical_coordinates or {})
    unknown = set(coordinates) - set(names)
    if unknown:
        raise ValueError(f"Coordinate catalog contains unknown geographies: {sorted(unknown)}")
    entries: list[dict[str, Any]] = []
    for name in names:
        source = coordinates.get(name) or {}
        latitude = source.get("latitude")
        longitude = source.get("longitude")
        if (latitude is None) != (longitude is None):
            raise ValueError(f"Canonical coordinate pair is incomplete for {name}")
        entries.append(
            {
                "geo_id": geo_id(name),
                "geo_display_name": name,
                "latitude": float(latitude) if latitude is not None else None,
                "longitude": float(longitude) if longitude is not None else None,
                "coordinates_status": "canonical" if latitude is not None else "unavailable",
                "region_id": source.get("region_id"),
                "region_display_name": source.get("region_display_name"),
            }
        )
    located = sum(entry["coordinates_status"] == "canonical" for entry in entries)
    status = "available" if entries and located == len(entries) else "partial" if located else "unavailable"
    payload = {
        "contract_name": GEO_CATALOG_CONTRACT,
        "schema_version": "1.0.0",
        "catalog_version": GEO_CATALOG_VERSION,
        "status": status,
        "display_text": (
            "Для всех географий доступны утвержденные координаты."
            if status == "available"
            else "Для части географий утвержденные координаты пока недоступны."
            if status == "partial"
            else "Утвержденные координаты пока недоступны; карта не строится."
        ),
        "geographies_n": len(entries),
        "entries": entries,
    }
    validate_geo_catalog_v1(payload)
    return payload


def _read_normalized_rows(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def build_validation_result_v2(
    validation: Mapping[str, Any],
    *,
    normalized_plan_path: Path | None = None,
    canonical_coordinates: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    campaigns = list(validation.get("campaigns") or [])
    totals = validation.get("totals") or {}
    preview = validation.get("preview") or {}
    job_allowed = bool(validation.get("job_creation_allowed"))
    blocking = list(validation.get("blocking_errors") or [])
    warnings = list(validation.get("warnings") or [])
    all_issues = [*blocking, *warnings]
    model_issues = [
        issue for issue in all_issues if _issue_cells(issue, SERVING_CORE_TARGET)
    ]
    file_blocking = [
        issue
        for issue in blocking
        if str(issue.get("scope") or "file") != "model"
        and not list(issue.get("affected_cells") or [])
    ]
    file_warnings = [
        issue
        for issue in warnings
        if str(issue.get("scope") or "file") != "model"
        and not list(issue.get("affected_cells") or [])
    ]
    status_code = str((validation.get("status") or {}).get("code") or "")
    if file_blocking:
        file_status = "failed"
    elif file_warnings:
        file_status = "warning"
    elif campaigns and totals:
        file_status = "passed"
    elif status_code == "invalid":
        file_status = "failed"
    else:
        file_status = "unavailable"

    geographies = sorted(
        {
            str(geo)
            for campaign in campaigns
            for geo in campaign.get("geographies") or []
        }
    )
    channels = sorted(
        {
            str(channel)
            for campaign in campaigns
            for channel in campaign.get("channels") or []
        }
    )
    normalized_rows = _read_normalized_rows(normalized_plan_path)
    channels_by_geo: dict[str, set[str]] = defaultdict(set)
    for row in normalized_rows:
        geo = str(row.get("geo") or "").strip()
        channel = str(row.get("channel") or "").strip()
        if geo and channel:
            channels_by_geo[geo].add(channel)
    if not normalized_rows:
        for geo in geographies:
            channels_by_geo[geo].update(channels)

    catalog = build_geo_catalog(
        geographies,
        canonical_coordinates=canonical_coordinates,
    )
    catalog_by_name = {entry["geo_display_name"]: entry for entry in catalog["entries"]}
    budget_by_geo = {
        str(row.get("geo") or ""): float(row.get("total_budget_rub") or 0.0)
        for row in preview.get("budget_by_geo") or []
    }
    requested_budget = float(
        totals.get("model_input_budget_rub") or sum(budget_by_geo.values())
    )

    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for issue in model_issues:
        for cell in _issue_cells(issue, SERVING_CORE_TARGET):
            channel_id = str(cell.get("channel") or "")
            identity = channel_identity(channel_id)
            severity_code = str(issue.get("severity") or "warning")
            key = (SERVING_TARGET_ID, channel_id, str(issue.get("code") or "MODEL_LIMITATION"))
            group = grouped.setdefault(
                key,
                {
                    "target": SERVING_TARGET_ID,
                    **identity,
                    "limitation_type": str(issue.get("code") or "MODEL_LIMITATION").lower(),
                    "affected_geos": set(),
                    "severity": (
                        "blocking"
                        if severity_code == "blocking"
                        else "manual_review"
                        if severity_code == "error"
                        else "warning"
                    ),
                    "allowed_use": (
                        "unsupported"
                        if "UNSUPPORTED" in str(issue.get("code") or "").upper()
                        else "diagnostic"
                        if "DIAGNOSTIC" in str(issue.get("code") or "").upper()
                        else "caution"
                    ),
                    "blocks_calculation": severity_code == "blocking",
                    "what": _browser_issue_text(
                        issue,
                        "what",
                        channel_id=channel_id,
                        channel_display_name=identity["channel_display_name"],
                        fallback=(
                            f"Для канала «{identity['channel_display_name']}» обнаружено "
                            "ограничение качества оценки оборота."
                        ),
                    ),
                    "why": _browser_issue_text(
                        issue,
                        "why",
                        channel_id=channel_id,
                        channel_display_name=identity["channel_display_name"],
                        fallback="Оценка имеет дополнительные ограничения качества.",
                    ),
                    "recommended_action": _browser_issue_text(
                        issue,
                        "recommended_action",
                        channel_id=channel_id,
                        channel_display_name=identity["channel_display_name"],
                        fallback="Проверьте отмеченные географии вручную.",
                    ),
                },
            )
            group["affected_geos"].add(str(cell.get("geo") or ""))
    model_limitations: list[dict[str, Any]] = []
    for key in sorted(grouped):
        group = grouped[key]
        affected = sorted(value for value in group.pop("affected_geos") if value)
        model_limitations.append(
            {
                **group,
                "affected_geos_n": len(affected),
                "affected_geos": affected,
            }
        )

    limitation_geos = {
        geo
        for limitation in model_limitations
        for geo in limitation["affected_geos"]
    }
    geo_points = []
    for geo in geographies:
        entry = catalog_by_name[geo]
        budget = float(budget_by_geo.get(geo, 0.0))
        geo_points.append(
            {
                "geo_id": entry["geo_id"],
                "geo_display_name": geo,
                "latitude": entry["latitude"],
                "longitude": entry["longitude"],
                "coordinates_status": entry["coordinates_status"],
                "budget_rub": budget,
                "budget_share": budget / requested_budget if requested_budget > 0 else None,
                "channels": [channel_identity(channel) for channel in sorted(channels_by_geo[geo])],
                "has_model_limitations": geo in limitation_geos,
            }
        )

    file_checks = [
        {
            "code": str(row.get("code") or ""),
            "status": str(row.get("status") or "unavailable"),
            "display_text": str(row.get("display_text") or "Проверка недоступна."),
        }
        for row in preview.get("checks") or []
        if str(row.get("code") or "")
        in {"FILE_STRUCTURE", "CAMPAIGN_COUNT", "BUDGET_RECONCILIATION", "DATES"}
    ]
    payload = {
        "contract_name": VALIDATION_RESULT_CONTRACT,
        "schema_version": SCHEMA_VERSION,
        "validation_id": str(validation.get("validation_id") or ""),
        "status": (
            "failed"
            if file_status == "failed"
            else "warning"
            if file_warnings or model_limitations
            else file_status
        ),
        "job_creation_allowed": job_allowed,
        "file_validation": {
            "status": file_status,
            "rows_n": int(totals.get("source_rows_n") or 0),
            "campaigns_n": len(campaigns),
            "geographies_n": len(geographies),
            "channels_n": len(channels),
            "requested_budget_rub": requested_budget,
            "blocking_errors_n": len(file_blocking),
            "warnings_n": len(file_warnings),
            "checks": file_checks,
        },
        "model_limitations": model_limitations,
        "geo_points": geo_points,
    }
    validate_validation_result_v2(payload)
    return payload


def build_model_passport_v2(passport_v1: Mapping[str, Any]) -> dict[str, Any]:
    coverage = passport_v1.get("coverage") or {}
    segments = [str(value) for value in coverage.get("segments") or []]
    research_targets = [
        str(row.get("target") or "")
        for row in coverage.get("targets") or []
        if str(row.get("target") or "")
    ]
    measured_research_models = len(segments) * len(set(research_targets))
    measured_serving_models = (
        len(segments) if SERVING_CORE_TARGET in research_targets else 0
    )
    if passport_v1.get("record_origin") == "verified_model_package" and (
        measured_research_models != RESEARCH_MODELS_N
        or measured_serving_models != ACTIVE_SERVING_MODELS_N
    ):
        raise ValueError(
            "Active model package does not expose the approved 12-to-4 serving inventory"
        )
    policies = []
    for row in coverage.get("channel_policies") or []:
        if str(row.get("target") or "") != SERVING_CORE_TARGET:
            continue
        policies.append(
            {
                "segment": str(row.get("segment") or ""),
                **channel_identity(row.get("channel")),
                "target": SERVING_TARGET_ID,
                "allowed_use": str(row.get("allowed_use") or "unavailable"),
                "forecast_action": str(row.get("forecast_action") or "unavailable"),
                "optimizer_action": str(row.get("optimizer_action") or "unavailable"),
                "display_text": str(row.get("display_text") or "Ограничение требует проверки."),
            }
        )
    channels = sorted({row["channel_id"] for row in policies})
    payload = {
        "contract_name": MODEL_PASSPORT_CONTRACT,
        "schema_version": SCHEMA_VERSION,
        "record_origin": passport_v1.get("record_origin", "verified_model_package"),
        "serving": {
            "serving_policy_version": SERVING_POLICY_VERSION,
            "target_id": SERVING_TARGET_ID,
            "core_target": SERVING_CORE_TARGET,
            "serving_targets_n": 1,
            "active_serving_models_n": (
                measured_serving_models
                if passport_v1.get("record_origin") == "verified_model_package"
                else ACTIVE_SERVING_MODELS_N
            ),
            "research_models_in_package_n": (
                measured_research_models
                if passport_v1.get("record_origin") == "verified_model_package"
                else RESEARCH_MODELS_N
            ),
            "calculation_allowed": bool((passport_v1.get("serving") or {}).get("calculation_allowed")),
            "production_claim_allowed": False,
        },
        "package": dict(passport_v1.get("package") or {}),
        "data": dict(passport_v1.get("data") or {}),
        "coverage": {
            "segments": segments,
            "channels": [channel_identity(channel) for channel in channels],
            "targets": [{"target_id": SERVING_TARGET_ID, "core_target": SERVING_CORE_TARGET}],
            "geographies_n": int(coverage.get("geographies_n") or 0),
            "capability_cells_n": len(policies),
        },
        "validation": dict(passport_v1.get("validation") or {}),
        "channel_policies": policies,
        "caveats": [
            dict(row)
            for row in passport_v1.get("caveats") or []
            if not _contains_diagnostic_metric(row)
        ],
    }
    validate_model_passport_v2(payload)
    return payload


def build_model_overview_v2(
    overview_v1: Mapping[str, Any],
    passport_v2: Mapping[str, Any],
) -> dict[str, Any]:
    payload = {
        "contract_name": MODEL_OVERVIEW_CONTRACT,
        "schema_version": SCHEMA_VERSION,
        "serving": dict(passport_v2["serving"]),
        "summary": {
            "training_period": dict((passport_v2.get("data") or {}).get("training_period") or {}),
            "package_status": (passport_v2.get("package") or {}).get("package_stage"),
            "activation_status": (passport_v2.get("package") or {}).get("activation_status"),
            "calculation_allowed": bool(passport_v2["serving"]["calculation_allowed"]),
            "historical_replay": dict((passport_v2.get("validation") or {}).get("historical_replay") or {}),
            "sealed_oot": dict((passport_v2.get("validation") or {}).get("sealed_oot") or {}),
        },
        "channel_policies": list(passport_v2.get("channel_policies") or []),
        "limitations": [
            dict(row)
            for row in overview_v1.get("limitations")
            or passport_v2.get("caveats")
            or []
            if not _contains_diagnostic_metric(row)
        ],
    }
    validate_model_overview_v2(payload)
    return payload


def _score_row(evidence: _Evidence, campaign_name: str, candidate_name: str) -> dict[str, str]:
    rows = evidence.csv(
        "candidate_scores_csv",
        {
            "campaign_name",
            "candidate_name",
            "requested_budget_rub",
            "allocated_budget_rub",
            "unallocated_budget_rub",
            "within_support_budget_rub",
            "within_support_share",
            "controlled_extrapolation_budget_rub",
            "controlled_extrapolation_share",
            "high_risk_budget_rub",
            "high_risk_share",
            "within_support_cells_n",
            "controlled_extrapolation_cells_n",
            "high_risk_cells_n",
            "scenario_kind",
            "scenario_variant",
            "scenario_feasibility_status",
        },
    )
    matches = [
        row
        for row in rows
        if row.get("campaign_name") == campaign_name
        and row.get("candidate_name") == candidate_name
    ]
    if len(matches) != 1:
        raise ValueError("Scenario candidate score evidence is missing or duplicated")
    return matches[0]


def _rub(value: float) -> str:
    return f"{float(value):,.0f}".replace(",", " ") + " ₽"


def _scenario6_limiting_constraints(
    evidence: _Evidence,
    campaign_name: str,
) -> list[str]:
    rows = evidence.csv(
        "candidate_scores_csv",
        {"campaign_name", "candidate_name", "precheck_status", "precheck_reason"},
    )
    scenario_rows = [
        row
        for row in rows
        if row.get("campaign_name") == campaign_name
        and "__scenario6_" in str(row.get("candidate_name") or "")
        and str(row.get("precheck_status") or "") != "scored"
    ]
    constraints: list[str] = []
    capacity_pattern = re.compile(
        r"(p95|p99|robust_upper):capacity=([0-9.]+)<requested=([0-9.]+)"
    )
    minimum_pattern = re.compile(
        r"(p95|p99|robust_upper):required_minimum=([0-9.]+)>requested=([0-9.]+)"
    )
    labels = {
        "p95": "исторически поддержанной зоне",
        "p99": "расширенной исторической зоне",
        "robust_upper": "максимальной утвержденной границе риска",
    }
    for row in scenario_rows:
        status = str(row.get("precheck_status") or "")
        reason = str(row.get("precheck_reason") or "")
        if status == "not_run_no_modifiable_cells":
            constraints.append(
                "Нет двух связок, между которыми разрешено автоматическое перераспределение."
            )
        for level, capacity, requested in capacity_pattern.findall(reason):
            constraints.append(
                f"При {labels[level]} можно распределить {_rub(float(capacity))} "
                f"из {_rub(float(requested))}."
            )
        for level, minimum, requested in minimum_pattern.findall(reason):
            constraints.append(
                f"Обязательный минимум при {labels[level]} составляет {_rub(float(minimum))}, "
                f"что выше запрошенного бюджета {_rub(float(requested))}."
            )
    return list(dict.fromkeys(constraints))


def _number(row: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    value = row.get(key)
    if value in (None, ""):
        return float(default)
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"Non-finite result field: {key}")
    return parsed


def _quantile_projection(metric: Mapping[str, Any], *, unit: str, text: str) -> dict[str, Any]:
    values = [metric.get(key) for key in ("p10", "p50", "p90")]
    if metric.get("status") == "unavailable" or any(value is None for value in values):
        return {"status": "unavailable", "unit": unit, "p10": None, "p50": None, "p90": None, "display_text": text}
    return {
        "status": "available",
        "unit": unit,
        "p10": float(metric["p10"]),
        "p50": float(metric["p50"]),
        "p90": float(metric["p90"]),
        "display_text": text,
    }


def _roas_projection(turnover: Mapping[str, Any], requested: float, allocated: float, primary_kind: str) -> dict[str, Any]:
    def metric(denominator: float, text: str) -> dict[str, Any]:
        if turnover.get("status") != "available" or denominator <= 0:
            return {"status": "unavailable", "unit": "ratio", "p10": None, "p50": None, "p90": None, "display_text": text}
        return {
            "status": "available",
            "unit": "ratio",
            "p10": float(turnover["p10"]) / denominator,
            "p50": float(turnover["p50"]) / denominator,
            "p90": float(turnover["p90"]) / denominator,
            "display_text": text,
        }
    return {
        "allocated_budget": metric(allocated, "Дополнительный оборот относительно распределенной части бюджета."),
        "requested_budget": metric(requested, "Дополнительный оборот относительно всего запрошенного бюджета."),
        "primary_denominator_kind": primary_kind,
        "primary_denominator_budget_rub": allocated if primary_kind == "allocated_budget" else requested,
    }


def _risk_projection(score: Mapping[str, Any] | None) -> dict[str, Any]:
    if score is None:
        return {
            "within_support_budget_rub": 0.0,
            "within_support_share": None,
            "controlled_extrapolation_budget_rub": 0.0,
            "controlled_extrapolation_share": None,
            "high_risk_budget_rub": 0.0,
            "high_risk_share": None,
            "within_support_cells_n": 0,
            "controlled_extrapolation_cells_n": 0,
            "high_risk_cells_n": 0,
        }
    return {
        "within_support_budget_rub": _number(score, "within_support_budget_rub"),
        "within_support_share": _number(score, "within_support_share") if score.get("within_support_share") not in (None, "") else None,
        "controlled_extrapolation_budget_rub": _number(score, "controlled_extrapolation_budget_rub"),
        "controlled_extrapolation_share": _number(score, "controlled_extrapolation_share") if score.get("controlled_extrapolation_share") not in (None, "") else None,
        "high_risk_budget_rub": _number(score, "high_risk_budget_rub"),
        "high_risk_share": _number(score, "high_risk_share") if score.get("high_risk_share") not in (None, "") else None,
        "within_support_cells_n": int(round(_number(score, "within_support_cells_n"))),
        "controlled_extrapolation_cells_n": int(round(_number(score, "controlled_extrapolation_cells_n"))),
        "high_risk_cells_n": int(round(_number(score, "high_risk_cells_n"))),
    }


def _recommendable_score(
    score: Mapping[str, Any] | None,
    *,
    scenario_id: str,
    available: bool,
) -> bool:
    """Fail closed unless one published candidate is a complete policy-safe plan."""

    if score is None or not available:
        return False
    requested = _number(score, "requested_budget_rub")
    allocated = _number(score, "allocated_budget_rub")
    unallocated = _number(score, "unallocated_budget_rub")
    if requested <= 0 or abs(requested - allocated) > 1.0 or unallocated > 1.0:
        return False
    if _number(score, "high_risk_budget_rub") > 1.0:
        return False
    for field in (
        "hard_support_warnings_n",
        "policy_violations_n",
        "risk_policy_violations_n",
    ):
        if _number(score, field) > 0:
            return False
    if scenario_id == "S05" and str(score.get("scenario_variant") or "") != "full_conservative":
        return False
    if scenario_id == "S06" and str(score.get("scenario_variant") or "") != "full_effect_maximizing":
        return False
    return True


def build_job_result_view_v2(
    *,
    job_id: str,
    job: Mapping[str, Any],
    result: Mapping[str, Any],
    overview: Mapping[str, Any],
    artifact_resolver: Any,
    canonical_coordinates: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    campaign_source = _validate_sources(job_id, job, result, overview)
    campaign_name = str(campaign_source["passport"]["campaign_name"])
    evidence = _Evidence(overview, artifact_resolver)
    candidates = _scenario_candidates(evidence, campaign_source)
    allocation_rows = _all_allocation_rows(evidence, campaign_source)
    scenario_by_id = {
        str(row["scenario_id"]): row for row in campaign_source["scenarios"]
    }
    source_candidate = candidates.get("S01")
    if not source_candidate:
        raise ValueError("Uploaded-plan allocation evidence is missing")
    passport_geographies = list(campaign_source["passport"]["geographies"])
    allocation_geographies = sorted(
        {
            str(row.get("geo") or "")
            for row in allocation_rows
            if row.get("candidate_name") == source_candidate
            and str(row.get("geo") or "")
        }
    )
    if (
        len(passport_geographies) != len(set(passport_geographies))
        or set(passport_geographies) != set(allocation_geographies)
    ):
        raise ValueError(
            "Campaign geographies do not reconcile with source allocation evidence"
        )
    catalog = build_geo_catalog(
        passport_geographies,
        canonical_coordinates=canonical_coordinates,
    )
    s6_infeasible_constraints = _scenario6_limiting_constraints(
        evidence, campaign_name
    )

    scenarios: list[dict[str, Any]] = []
    source_selected_id = str(
        (campaign_source.get("recommendation") or {}).get("scenario_id") or "S01"
    )
    if source_selected_id not in scenario_by_id:
        raise ValueError("Recommended scenario is absent from result evidence")
    selected_source_id = source_selected_id
    selected_candidate = candidates.get(selected_source_id)
    selected_score = (
        _score_row(evidence, campaign_name, selected_candidate)
        if selected_candidate
        else None
    )
    selected_variant = str(selected_score.get("scenario_variant") or "") if selected_score else ""
    if selected_source_id == "S01":
        recommendation_decision = "keep_uploaded_plan"
        recommendation_review = "manual_review_required"
    elif selected_source_id == "S05" and selected_variant == "safe_partial":
        recommendation_decision = "no_safe_recommendation"
        recommendation_review = "manual_review_required"
    elif _recommendable_score(
        selected_score,
        scenario_id=selected_source_id,
        available=bool(scenario_by_id[selected_source_id].get("available")),
    ):
        recommendation_decision = "recommended_reallocation"
        recommendation_review = "not_required"
    else:
        selected_source_id = "S01"
        selected_candidate = candidates.get(selected_source_id)
        selected_score = (
            _score_row(evidence, campaign_name, selected_candidate)
            if selected_candidate
            else None
        )
        selected_variant = str(selected_score.get("scenario_variant") or "") if selected_score else ""
        recommendation_decision = "keep_uploaded_plan"
        recommendation_review = "manual_review_required"
    for scenario_id in ("S01", "S02", "S03", "S04", "S05", "S06"):
        legacy_scenario = scenario_by_id[scenario_id]
        available = bool(legacy_scenario.get("available"))
        candidate_name = candidates.get(scenario_id)
        score = _score_row(evidence, campaign_name, candidate_name) if available and candidate_name else None
        requested_budget = (
            _number(score, "requested_budget_rub")
            if score is not None
            else float(legacy_scenario["budget"]["requested_budget_rub"])
        )
        allocated_budget = (
            _number(score, "allocated_budget_rub") if score is not None else 0.0
        )
        unallocated_budget = (
            _number(score, "unallocated_budget_rub")
            if score is not None
            else requested_budget
        )
        budget = {
            "requested_budget_rub": requested_budget,
            "allocated_budget_rub": allocated_budget,
            "unallocated_budget_rub": unallocated_budget,
            "allocation_share": (
                allocated_budget / requested_budget if requested_budget > 0 else None
            ),
        }
        turnover = _quantile_projection(
            legacy_scenario["metrics"]["incremental_turnover"] if available else {},
            unit="RUB",
            text="Дополнительный оборот относительно варианта без кампании.",
        )
        variant = str(score.get("scenario_variant") or "") if score else None
        kind = {
            "S01": "uploaded_plan",
            "S02": "benchmark_plan",
            "S03": "benchmark_plan",
            "S04": "benchmark_plan",
            "S05": "conservative_plan",
            "S06": "optimized_plan",
        }[scenario_id]
        if scenario_id == "S05" and variant not in {"full_conservative", "safe_partial"}:
            raise ValueError("Scenario 5 variant is absent from optimizer evidence")
        if scenario_id == "S06" and not available:
            status = "infeasible"
            variant = "infeasible"
        else:
            status = "completed" if available else "unavailable"
        if scenario_id == "S01":
            decision_status = "keep_uploaded_plan"
            review_status = "manual_review_required"
        elif scenario_id == "S05" and variant == "safe_partial":
            decision_status = "no_safe_recommendation"
            review_status = "manual_review_required"
        elif available and scenario_id == selected_source_id and recommendation_decision == "recommended_reallocation":
            decision_status = "recommended_reallocation"
            review_status = "not_required"
        else:
            decision_status = "manual_review_required" if available else "unavailable"
            review_status = "manual_review_required"
        risk = _risk_projection(score)
        reliability_codes = []
        if risk["high_risk_budget_rub"] > 1.0:
            reliability_status = "high_risk"
            reliability_codes.append("HIGH_RISK_BUDGET_PRESENT")
        elif risk["controlled_extrapolation_budget_rub"] > 1.0:
            reliability_status = "controlled_extrapolation"
            reliability_codes.append("CONTROLLED_EXTRAPOLATION_PRESENT")
        elif available:
            reliability_status = "within_support"
            reliability_codes.append("WITHIN_SUPPORT")
        else:
            reliability_status = "unavailable"
            reliability_codes.append("SCENARIO_INFEASIBLE")
        ranks = _candidate_ranks(allocation_rows, candidate_name) if candidate_name else (None, None)
        limiting = []
        if scenario_id == "S05" and variant == "safe_partial":
            limiting.append(
                "В пределах максимальной утвержденной границы риска можно распределить "
                f"{_rub(allocated_budget)} из {_rub(requested_budget)}."
            )
        elif score and str(score.get("limiting_constraints") or "").strip():
            limiting.append(str(score["limiting_constraints"]).strip())
        if scenario_id == "S06" and not available:
            limiting.extend(s6_infeasible_constraints)
            if not limiting:
                limiting.append(
                    "Полный план не найден в пределах утвержденных ограничений."
                )
        name, description, _ = SCENARIO_COPY[scenario_id]
        if scenario_id == "S05":
            name = "Осторожный полный план" if variant == "full_conservative" else "Безопасно распределяемая часть"
        elif scenario_id == "S06":
            name = "План максимального эффекта"
        scenarios.append(
            {
                "scenario_id": scenario_id,
                "name": name,
                "description": description,
                "scenario_kind": kind,
                "scenario_variant": variant,
                "status": status,
                "is_recommended": bool(decision_status == "recommended_reallocation" and scenario_id == selected_source_id),
                "decision_status": decision_status,
                "review_status": review_status,
                "budget": budget,
                "incremental_turnover": turnover,
                "roas": _roas_projection(
                    turnover,
                    budget["requested_budget_rub"],
                    budget["allocated_budget_rub"],
                    "allocated_budget" if variant == "safe_partial" else "requested_budget",
                ),
                "risk_budget": risk,
                "reliability": {
                    "status": reliability_status,
                    "display_text": {
                        "within_support": "Распределенный бюджет находится в исторически поддержанной зоне.",
                        "controlled_extrapolation": "Часть бюджета использует контролируемое расширение исторического диапазона.",
                        "high_risk": "Часть бюджета находится выше утвержденной границы риска.",
                        "unavailable": "Надежность недоступна, потому что полный план не сформирован.",
                    }[reliability_status],
                    "evidence_codes": reliability_codes,
                    "safe_rank": ranks[0],
                    "raw_rank": ranks[1],
                },
                "limiting_constraints": list(dict.fromkeys(limiting)),
            }
        )

    selected_scenario = next(row for row in scenarios if row["scenario_id"] == selected_source_id)
    if recommendation_decision == "keep_uploaded_plan":
        recommendation_text = (
            "Автоматическое перераспределение не подтвердило надежного улучшения. "
            "Исходный план сохранен как точка отсчета и требует ручной проверки."
        )
        recommendation_title = "Исходный план сохранен для проверки"
    elif recommendation_decision == "no_safe_recommendation":
        recommendation_text = (
            "Весь бюджет нельзя распределить с приемлемой надежностью. "
            "Опубликована только безопасно распределяемая часть и явный остаток."
        )
        recommendation_title = "Автоматическая рекомендация недоступна"
    else:
        recommendation_text = str((campaign_source.get("recommendation") or {}).get("reason") or "Выбран полный план, прошедший ограничения расчета.")
        recommendation_title = "Рекомендуемое перераспределение бюджета"
    geographies = [
        {"geo_id": entry["geo_id"], "geo_display_name": entry["geo_display_name"]}
        for entry in catalog["entries"]
    ]
    payload = {
        "contract_name": JOB_RESULT_VIEW_CONTRACT,
        "schema_version": SCHEMA_VERSION,
        "record_origin": (
            "sanitized_fixture"
            if overview.get("result_origin") == "sanitized_fixture"
            else "application_runtime"
        ),
        "job_id": job_id,
        "result_id": result["result_id"],
        "source_overview_id": overview["overview_id"],
        "updated_at_utc": job.get("finished_at_utc") or overview["created_at_utc"],
        "campaign": {
            "campaign_id": campaign_source["campaign_id"],
            "campaign_name": campaign_name,
            "segments": list(campaign_source["passport"]["segments"]),
            "start_date": campaign_source["passport"]["source_start_date"],
            "end_date": campaign_source["passport"]["source_end_date"],
            "requested_budget_rub": float(campaign_source["budget"]["uploaded_budget_rub"]),
            "channels": [channel_identity(channel) for channel in campaign_source["passport"]["source_channels"]],
            "geographies_n": len(geographies),
            "geographies": geographies,
        },
        "recommendation": {
            "decision_status": recommendation_decision,
            "review_status": recommendation_review,
            "scenario_id": selected_source_id,
            "title": recommendation_title,
            "display_text": recommendation_text,
            "decision_scope_text": "Рекомендация относится к распределению бюджета, а не к решению о запуске кампании.",
        },
        "scenarios": scenarios,
        "media_plan": {
            "endpoint": f"/api/v1/jobs/{job_id}/media-plan-v2",
            "selected_scenario_id": selected_scenario["scenario_id"],
        },
        "map": {
            "status": catalog["status"],
            "display_text": catalog["display_text"],
            "coordinate_catalog_version": catalog["catalog_version"],
            "geo_points": catalog["entries"],
        },
        "limitations": [
            {"code": "incremental_effect_only", "display_text": "Результат показывает дополнительный оборот относительно варианта без кампании, а не полный прогноз оборота."},
            {"code": "turnover_roas_not_profit", "display_text": "ROAS рассчитан по дополнительному обороту и не является оценкой прибыли."},
            {"code": "research_model", "display_text": "Расчет предназначен для исследовательского планирования и требует бизнес-проверки."},
        ],
    }
    validate_job_result_view_v2(payload)
    return payload


def build_workspace_geo_budget_v1(
    validations: Iterable[Mapping[str, Any]],
    *,
    canonical_coordinates: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    budgets: dict[str, float] = defaultdict(float)
    campaigns_by_geo: dict[str, set[str]] = defaultdict(set)
    for validation in validations:
        if not validation.get("job_creation_allowed"):
            continue
        preview = validation.get("preview") or {}
        campaign_ids = [str(row.get("campaign_id") or "") for row in validation.get("campaigns") or []]
        for row in preview.get("budget_by_geo") or []:
            geo = str(row.get("geo") or "").strip()
            if not geo:
                continue
            budgets[geo] += float(row.get("total_budget_rub") or 0.0)
            campaigns_by_geo[geo].update(campaign_ids)
    catalog = build_geo_catalog(budgets, canonical_coordinates=canonical_coordinates)
    by_name = {entry["geo_display_name"]: entry for entry in catalog["entries"]}
    total = sum(budgets.values())
    rows = [
        {
            "geo_id": by_name[geo]["geo_id"],
            "geo_display_name": geo,
            "latitude": by_name[geo]["latitude"],
            "longitude": by_name[geo]["longitude"],
            "coordinates_status": by_name[geo]["coordinates_status"],
            "total_budget_rub": budget,
            "campaigns_n": len(campaigns_by_geo[geo]),
            "budget_share": budget / total if total > 0 else None,
        }
        for geo, budget in sorted(budgets.items())
    ]
    payload = {
        "contract_name": WORKSPACE_GEO_BUDGET_CONTRACT,
        "schema_version": "1.0.0",
        "catalog_version": catalog["catalog_version"],
        "status": catalog["status"],
        "display_text": catalog["display_text"],
        "total_budget_rub": total,
        "campaigns_n": len({value for values in campaigns_by_geo.values() for value in values}),
        "geographies_n": len(rows),
        "rows": rows,
    }
    validate_workspace_geo_budget_v1(payload)
    return payload
