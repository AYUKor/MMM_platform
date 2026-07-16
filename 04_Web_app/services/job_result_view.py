"""Build browser-safe result and media-plan projections from published evidence.

The service intentionally works *after* the calculation has completed.  It
does not call MMM, forecast or optimizer code.  Numeric scenario effects and
the canonical recommendation come from ``ResultOverview v1``; allocation
ranks and plans are read from hash-checked artifacts produced by that same
run.
"""

from __future__ import annotations

import csv
import hashlib
import math
import zipfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from contracts.job_result_view_v1 import validate_job_result_view_payload
from contracts.scenario_media_plan_v1 import validate_scenario_media_plan_payload


ArtifactResolver = Callable[[str], tuple[Path, Mapping[str, Any]]]
SCENARIO_IDS = ("S01", "S02", "S03", "S04", "S05", "S06")
SCENARIO_COPY: dict[str, tuple[str, str, str]] = {
    "S01": (
        "Как загружено",
        "Бюджет, каналы и географии сохранены в исходном распределении.",
        "source",
    ),
    "S02": (
        "Ровно по связкам",
        "Бюджет поровну распределен между исходными связками география × канал.",
        "control",
    ),
    "S03": (
        "Каналы как были, географии ровно",
        "Бюджет каждого канала сохранен и поровну распределен между его географиями.",
        "control",
    ),
    "S04": (
        "Географии как были, каналы ровно",
        "Бюджет каждой географии сохранен и поровну распределен между ее каналами.",
        "control",
    ),
    "S05": (
        "Устойчивый ориентир",
        "Бюджет распределен ближе к тем уровням активности, которые модель наблюдала в истории.",
        "benchmark",
    ),
    "S06": (
        "Адаптивное распределение",
        "Система перебрала варианты и проверила их по эффекту и ограничениям качества.",
        "adaptive",
    ),
}


class ResultProjectionError(RuntimeError):
    """Base class for controlled product projection failures."""


class ResultProjectionStateError(ResultProjectionError):
    """Published result resources contradict each other or their artifacts."""


class ResultProjectionUnavailableError(ResultProjectionError):
    """The projection cannot be built although persisted evidence is coherent."""


class UnsupportedMediaPlanQuery(ValueError):
    """The requested scenario or filter is not supported by current evidence."""


def _opaque_id(prefix: str, seed: str) -> str:
    return f"{prefix}_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:20]}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _float(row: Mapping[str, Any], key: str) -> float:
    value = row.get(key)
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ResultProjectionStateError(f"Artifact field {key!r} is not numeric") from exc
    if not math.isfinite(parsed):
        raise ResultProjectionStateError(f"Artifact field {key!r} is not finite")
    return parsed


def _optional_positive_int(row: Mapping[str, Any], key: str) -> int | None:
    value = str(row.get(key) or "").strip()
    if not value:
        return None
    try:
        parsed = int(round(float(value)))
    except ValueError as exc:
        raise ResultProjectionStateError(f"Artifact field {key!r} is not an integer") from exc
    if parsed < 1:
        raise ResultProjectionStateError(f"Artifact field {key!r} must be positive")
    return parsed


def _artifact_public(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": item["artifact_id"],
        "display_name": item["display_name"],
        "media_type": item["media_type"],
        "size_bytes": int(item["size_bytes"]),
        "sha256": item["sha256"],
        "download_path": item["download_path"],
    }


class _Evidence:
    def __init__(self, overview: Mapping[str, Any], resolver: ArtifactResolver) -> None:
        self.overview = overview
        self.resolver = resolver
        self._paths: dict[str, tuple[Path, Mapping[str, Any]]] = {}
        self._csv_rows: dict[str, list[dict[str, str]]] = {}

    def artifact(self, kind: str, *, required: bool = True) -> tuple[Path, Mapping[str, Any]] | None:
        if kind in self._paths:
            return self._paths[kind]
        matches = [item for item in self.overview.get("artifacts") or [] if item.get("kind") == kind]
        if not matches:
            if required:
                raise ResultProjectionStateError(f"Required artifact {kind!r} is not published")
            return None
        if len(matches) != 1:
            raise ResultProjectionStateError(f"Artifact kind {kind!r} is duplicated")
        item = matches[0]
        expected_download = f"/api/v1/artifacts/{item.get('artifact_id')}/download"
        if item.get("download_path") != expected_download:
            raise ResultProjectionStateError(f"Artifact {kind!r} has a non-canonical download path")
        try:
            path, resolved = self.resolver(str(item["artifact_id"]))
        except (FileNotFoundError, PermissionError) as exc:
            raise ResultProjectionStateError(f"Artifact {kind!r} did not pass integrity checks") from exc
        if not path.is_file():
            raise ResultProjectionStateError(f"Artifact {kind!r} is missing")
        if path.stat().st_size != int(item["size_bytes"]) or _sha256(path) != str(item["sha256"]):
            raise ResultProjectionStateError(f"Artifact {kind!r} did not reconcile with result metadata")
        if resolved.get("sha256") not in {None, item["sha256"]}:
            raise ResultProjectionStateError(f"Artifact {kind!r} resolver metadata is inconsistent")
        self._paths[kind] = (path, item)
        return self._paths[kind]

    def csv(self, kind: str, required_columns: set[str]) -> list[dict[str, str]]:
        if kind in self._csv_rows:
            return self._csv_rows[kind]
        artifact = self.artifact(kind)
        assert artifact is not None
        path, _ = artifact
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                columns = set(reader.fieldnames or [])
                if missing := required_columns - columns:
                    raise ResultProjectionStateError(
                        f"Artifact {kind!r} lacks required columns: {sorted(missing)}"
                    )
                rows = [dict(row) for row in reader]
        except UnicodeError as exc:
            raise ResultProjectionStateError(f"Artifact {kind!r} is not valid UTF-8 CSV") from exc
        self._csv_rows[kind] = rows
        return rows


def _validate_sources(
    job_id: str,
    job: Mapping[str, Any],
    result: Mapping[str, Any],
    overview: Mapping[str, Any],
) -> Mapping[str, Any]:
    if job.get("job_id") != job_id:
        raise ResultProjectionStateError("Requested job does not match persisted job")
    if ((job.get("status") or {}).get("code")) != "succeeded":
        raise ResultProjectionUnavailableError("Result is not published for a non-succeeded job")
    result_id = result.get("result_id")
    if not isinstance(result_id, str) or job.get("result_id") != result_id:
        raise ResultProjectionStateError("Job and result identifiers do not reconcile")
    if overview.get("source_result_id") != result_id:
        raise ResultProjectionStateError("Result overview points to another result")
    if overview.get("result_origin") not in {
        "verified_optimizer_artifacts",
        "sanitized_fixture",
    }:
        raise ResultProjectionStateError("Result overview has an unsupported origin")
    result_artifacts = result.get("artifacts")
    overview_artifacts = overview.get("artifacts")
    if (
        not isinstance(result_artifacts, list)
        or not isinstance(overview_artifacts, list)
        or any(not isinstance(item, Mapping) for item in result_artifacts)
        or any(not isinstance(item, Mapping) for item in overview_artifacts)
    ):
        raise ResultProjectionStateError("Published artifact metadata has an invalid shape")
    result_by_id = {item.get("artifact_id"): item for item in result_artifacts}
    if len(result_by_id) != len(result_artifacts):
        raise ResultProjectionStateError("Result artifact identifiers are duplicated")
    for item in overview_artifacts:
        source = result_by_id.get(item.get("artifact_id"))
        if not isinstance(source, Mapping) or any(
            source.get(key) != item.get(key)
            for key in ("kind", "media_type", "sha256", "size_bytes")
        ):
            raise ResultProjectionStateError("Result and overview artifact metadata do not reconcile")
    campaigns = overview.get("campaigns")
    if not isinstance(campaigns, list) or len(campaigns) != 1:
        raise ResultProjectionStateError("Product result view requires exactly one campaign")
    scenario_ids = [row.get("scenario_id") for row in campaigns[0].get("scenarios") or []]
    if scenario_ids != list(SCENARIO_IDS):
        raise ResultProjectionStateError("Result overview must contain ordered S01-S06")
    return campaigns[0]


def _campaign_name(campaign: Mapping[str, Any]) -> str:
    name = str((campaign.get("passport") or {}).get("campaign_name") or "").strip()
    if not name:
        raise ResultProjectionStateError("Campaign name is missing")
    return name


def _scenario_candidates(
    evidence: _Evidence,
    campaign: Mapping[str, Any],
) -> dict[str, str]:
    campaign_name = _campaign_name(campaign)
    scenario_rows = evidence.csv(
        "scenario_results_csv", {"campaign_name", "scenario_no", "candidate_name"}
    )
    candidates: dict[str, str] = {}
    for row in scenario_rows:
        if row.get("campaign_name") != campaign_name:
            continue
        scenario_id = str(row.get("scenario_no") or "")
        if scenario_id not in SCENARIO_IDS[:5]:
            continue
        if scenario_id in candidates:
            raise ResultProjectionStateError(f"Scenario {scenario_id} candidate is duplicated")
        candidates[scenario_id] = str(row.get("candidate_name") or "")

    decision_rows = evidence.csv(
        "decision_pool_csv", {"campaign_name", "scenario_no", "candidate_name"}
    )
    s6_rows = [
        row
        for row in decision_rows
        if row.get("campaign_name") == campaign_name and row.get("scenario_no") == "S06"
    ]
    if len(s6_rows) > 1:
        raise ResultProjectionStateError("Scenario S06 candidate is duplicated")
    if s6_rows:
        candidates["S06"] = str(s6_rows[0].get("candidate_name") or "")

    missing = [scenario_id for scenario_id in SCENARIO_IDS[:5] if not candidates.get(scenario_id)]
    if missing:
        raise ResultProjectionStateError(f"Allocation evidence is missing scenarios: {missing}")
    s6_available = bool(next(row for row in campaign["scenarios"] if row["scenario_id"] == "S06")["available"])
    if s6_available and not candidates.get("S06"):
        recommendation_rows = evidence.csv(
            "recommendations_csv", {"campaign_name", "scenario_no", "candidate_name"}
        )
        matches = [
            row
            for row in recommendation_rows
            if row.get("campaign_name") == campaign_name and row.get("scenario_no") == "S06"
        ]
        if len(matches) > 1:
            raise ResultProjectionStateError("Scenario S06 recommendation is duplicated")
        if matches:
            candidates["S06"] = str(matches[0].get("candidate_name") or "")
    if s6_available and not candidates.get("S06"):
        raise ResultProjectionStateError("Available Scenario S06 has no allocation evidence")
    return candidates


def _all_allocation_rows(evidence: _Evidence, campaign: Mapping[str, Any]) -> list[dict[str, str]]:
    campaign_name = _campaign_name(campaign)
    rows = evidence.csv(
        "recommended_allocations_csv",
        {
            "source_campaign_name",
            "candidate_name",
            "optimizer_raw_rank",
            "optimizer_reliable_rank",
            "segment",
            "geo",
            "channel",
            "budget_rub",
            "allowed_use",
            "optimizer_policy",
            "gate_reason_codes",
        },
    )
    selected = [row for row in rows if row.get("source_campaign_name") == campaign_name]
    if not selected:
        raise ResultProjectionStateError("Campaign allocation evidence is missing")
    return selected


def _candidate_rows(rows: list[dict[str, str]], candidate_name: str) -> list[dict[str, str]]:
    selected = [row for row in rows if row.get("candidate_name") == candidate_name]
    if not selected:
        raise ResultProjectionStateError("Scenario allocation candidate is missing")
    return selected


def _candidate_name_by_id(rows: list[dict[str, str]], candidate_id: str | None) -> str | None:
    if candidate_id is None:
        return None
    names = {
        str(row.get("candidate_name") or "")
        for row in rows
        if _opaque_id("candidate", str(row.get("candidate_name") or "")) == candidate_id
    }
    if len(names) != 1:
        return None
    return next(iter(names))


def _candidate_ranks(rows: list[dict[str, str]], candidate_name: str | None) -> tuple[int | None, int | None]:
    if candidate_name is None:
        return None, None
    selected = _candidate_rows(rows, candidate_name)
    raw = {_optional_positive_int(row, "optimizer_raw_rank") for row in selected}
    safe = {_optional_positive_int(row, "optimizer_reliable_rank") for row in selected}
    if len(raw) != 1 or len(safe) != 1:
        raise ResultProjectionStateError("Candidate ranks are inconsistent across allocation rows")
    return next(iter(safe)), next(iter(raw))


def _row_quality(row: Mapping[str, Any]) -> tuple[str, str]:
    gate_codes = [
        code
        for code in str(row.get("gate_reason_codes") or "").split("|")
        if code and code != "OK"
    ]
    allowed_use = str(row.get("allowed_use") or "").lower()
    policy = str(row.get("optimizer_policy") or "").lower()
    if allowed_use in {"unsupported", "unavailable"} or policy in {"blocked", "exclude"}:
        return "blocked", "Связка требует ручной проверки и не должна автоматически получать дополнительный бюджет."
    if allowed_use in {"caution", "diagnostic"} or policy in {
        "caution",
        "no_increase",
        "fixed_at_plan",
        "fixed",
    }:
        return "caution", "Связка допустима только с дополнительной осторожностью."
    if allowed_use == "primary" and policy in {"optimize", "allowed", ""}:
        if gate_codes:
            return "caution", "Связка разрешена, но содержит дополнительное предупреждение качества."
        return "safe", "Связка разрешена для автоматического распределения бюджета."
    if gate_codes:
        return "blocked", "Связка требует ручной проверки и не должна автоматически получать дополнительный бюджет."
    return "unavailable", "Для связки нет однозначной пользовательской оценки качества."


def _worst_quality(statuses: list[str]) -> str:
    order = {"safe": 0, "caution": 1, "unavailable": 2, "blocked": 3}
    return max(statuses, key=lambda value: order[value]) if statuses else "unavailable"


def _quality_text(status: str) -> str:
    return {
        "safe": "Ограничения для автоматического распределения соблюдены.",
        "caution": "Есть ограничения, которые требуют осторожной интерпретации.",
        "blocked": "Есть ограничения, исключающие автоматическое увеличение бюджета.",
        "unavailable": "Однозначная оценка качества недоступна.",
    }[status]


def _delta_pct(source: float, delta: float) -> float | None:
    return None if source == 0 else delta / source * 100.0


def _budget_line(
    source: float,
    selected: float,
    quality_status: str,
    **dimensions: str,
) -> dict[str, Any]:
    delta = selected - source
    if abs(delta) < 0.005:
        delta = 0.0
    return {
        **dimensions,
        "source_budget_rub": source,
        "selected_budget_rub": selected,
        "delta_rub": delta,
        "delta_pct": _delta_pct(source, delta),
        "quality_status": quality_status,
        "quality_display_text": _quality_text(quality_status),
    }


def _aggregate_rows(rows: list[dict[str, Any]], dimensions: tuple[str, ...]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in rows:
        key = tuple(str(row[name]) for name in dimensions)
        item = grouped.setdefault(
            key,
            {"source": 0.0, "selected": 0.0, "quality": []},
        )
        item["source"] += float(row["source_budget_rub"])
        item["selected"] += float(row["selected_budget_rub"])
        item["quality"].append(str(row["quality_status"]))
    result = []
    for key in sorted(grouped):
        item = grouped[key]
        result.append(
            _budget_line(
                item["source"],
                item["selected"],
                _worst_quality(item["quality"]),
                **dict(zip(dimensions, key)),
            )
        )
    return result


def _scenario_record(campaign: Mapping[str, Any], scenario_id: str) -> Mapping[str, Any]:
    return next(row for row in campaign["scenarios"] if row["scenario_id"] == scenario_id)


def _build_plan_evidence(
    campaign: Mapping[str, Any],
    candidates: Mapping[str, str],
    allocation_rows: list[dict[str, str]],
    scenario_id: str,
) -> dict[str, Any]:
    scenario = _scenario_record(campaign, scenario_id)
    if not scenario.get("available"):
        raise UnsupportedMediaPlanQuery(f"Сценарий {scenario_id} недоступен для этой кампании.")
    candidate_name = candidates.get(scenario_id)
    if not candidate_name:
        raise ResultProjectionStateError(f"Scenario {scenario_id} has no candidate allocation")
    source_name = candidates["S01"]
    source_rows = _candidate_rows(allocation_rows, source_name)
    selected_rows = _candidate_rows(allocation_rows, candidate_name)

    def keyed(rows: list[dict[str, str]]) -> dict[tuple[str, str, str], dict[str, str]]:
        result: dict[tuple[str, str, str], dict[str, str]] = {}
        for row in rows:
            key = (str(row.get("segment") or ""), str(row.get("geo") or ""), str(row.get("channel") or ""))
            if not all(key) or key in result:
                raise ResultProjectionStateError("Allocation cells are empty or duplicated")
            result[key] = row
        return result

    source = keyed(source_rows)
    selected = keyed(selected_rows)
    if set(selected) != set(source):
        raise ResultProjectionStateError("Selected plan changes the approved source cell set")
    source_total = sum(_float(row, "budget_rub") for row in source.values())
    selected_total = sum(_float(row, "budget_rub") for row in selected.values())
    expected_source = float(_scenario_record(campaign, "S01")["budget"]["allocated_budget_rub"])
    expected_selected = float(scenario["budget"]["allocated_budget_rub"])
    if abs(source_total - expected_source) > 1.0 or abs(selected_total - expected_selected) > 1.0:
        raise ResultProjectionStateError("Scenario allocation budget does not reconcile with overview")

    rows: list[dict[str, Any]] = []
    for segment, geo, channel in sorted(source):
        source_budget = _float(source[(segment, geo, channel)], "budget_rub")
        selected_row = selected[(segment, geo, channel)]
        selected_budget = _float(selected_row, "budget_rub")
        quality_status, quality_text = _row_quality(selected_row)
        line = _budget_line(
            source_budget,
            selected_budget,
            quality_status,
            segment=segment,
            geo=geo,
            channel=channel,
        )
        line.update(
            {
                "scenario_id": scenario_id,
                "campaign_id": campaign["campaign_id"],
                "date": None,
                "source_budget_share": source_budget / source_total if source_total > 0 else 0.0,
                "selected_budget_share": selected_budget / selected_total if selected_total > 0 else 0.0,
                "quality_display_text": quality_text,
            }
        )
        rows.append(line)

    safe_rank, raw_rank = _candidate_ranks(allocation_rows, candidate_name)
    return {
        "candidate_name": candidate_name,
        "candidate_id": _opaque_id("candidate", candidate_name),
        "safe_rank": safe_rank,
        "raw_rank": raw_rank,
        "rows": rows,
        "source_total": source_total,
        "selected_total": selected_total,
        "by_channel": _aggregate_rows(rows, ("channel",)),
        "by_geo": _aggregate_rows(rows, ("geo",)),
        "by_geo_channel": _aggregate_rows(rows, ("geo", "channel")),
    }


def _metric(
    source: Mapping[str, Any] | None,
    *,
    unit: str,
    usage: str,
    available_text: str,
    unavailable_text: str,
    divisor: float | None = None,
    formula_version: str | None = None,
) -> dict[str, Any]:
    if source is None or (divisor is not None and divisor <= 0):
        return {
            "status": "unavailable",
            "unit": unit,
            "p10": None,
            "p50": None,
            "p90": None,
            "usage": usage,
            "display_text": unavailable_text,
            "formula_version": formula_version,
        }
    denominator = divisor or 1.0
    values = [float(source[key]) / denominator for key in ("p10", "p50", "p90")]
    if not values[0] <= values[1] <= values[2]:
        raise ResultProjectionStateError("Published metric quantiles are out of order")
    return {
        "status": "available",
        "unit": unit,
        "p10": values[0],
        "p50": values[1],
        "p90": values[2],
        "usage": usage,
        "display_text": available_text,
        "formula_version": formula_version,
    }


def _scenario_metrics(scenario: Mapping[str, Any]) -> dict[str, Any]:
    metrics = scenario.get("metrics") or {}
    budget = float((scenario.get("budget") or {}).get("allocated_budget_rub") or 0.0)
    orders = metrics.get("incremental_orders")
    return {
        "incremental_turnover_rub": _metric(
            metrics.get("incremental_turnover"),
            unit="RUB",
            usage="primary",
            available_text="Дополнительный оборот относительно варианта без кампании.",
            unavailable_text="Дополнительный оборот не рассчитан.",
        ),
        "incremental_orders": _metric(
            orders,
            unit="orders",
            usage="diagnostic_only",
            available_text="Диагностическая оценка дополнительных заказов.",
            unavailable_text="Оценка дополнительных заказов недоступна.",
        ),
        "orders_per_100k_rub": _metric(
            orders,
            unit="orders_per_100k_RUB",
            usage="diagnostic_only",
            available_text="Диагностическая оценка заказов на 100 000 рублей бюджета.",
            unavailable_text="Показатель нельзя рассчитать без заказов и положительного бюджета.",
            divisor=budget / 100_000.0 if budget > 0 else 0.0,
            formula_version="orders_quantile_divided_by_deterministic_budget_v1",
        ),
        "avg_basket_delta_rub": _metric(
            None,
            unit="RUB_per_order",
            usage="unavailable",
            available_text="",
            unavailable_text="Изменение среднего чека не выделено в текущем результате.",
        ),
        "avg_basket_turnover_bridge_rub": _metric(
            metrics.get("avg_basket_turnover_bridge"),
            unit="turnover_bridge_from_avg_basket_rub",
            usage="diagnostic_only",
            available_text="Часть дополнительного оборота, связанная с механизмом среднего чека.",
            unavailable_text="Оборотный вклад механизма среднего чека недоступен.",
        ),
        "roas": _metric(
            metrics.get("turnover_roas"),
            unit="ratio",
            usage="primary",
            available_text="Отношение дополнительного оборота к бюджету кампании.",
            unavailable_text="ROAS недоступен.",
        ),
    }


def _scenario_quality(scenario: Mapping[str, Any]) -> tuple[str, str]:
    if not scenario.get("available"):
        return "unavailable", "Сценарий не рассчитан."
    support = scenario.get("support") or {}
    quality_code = ((scenario.get("quality") or {}).get("status") or {}).get("code")
    cell_code = (scenario.get("cell_support_status") or {}).get("code")
    if cell_code == "above_robust_upper" or any(
        int(support.get(key) or 0) > 0 for key in ("hard_warnings", "policy_violations")
    ):
        return "blocked", "Есть жесткие ограничения для автоматического перераспределения."
    if (
        cell_code == "above_p99_within_robust_upper"
        or quality_code in {"manual_review_required", "not_for_automatic_reallocation"}
        or int(support.get("strong_warnings") or 0) > 0
    ):
        return "blocked", "Сценарий требует ручной проверки и не подходит для автоматического перераспределения."
    if quality_code == "reliable" and int(support.get("elevated_warnings") or 0) == 0:
        return "safe", "Сценарий находится в наиболее устойчивой из доступных зон расчета."
    if quality_code in {"reliable", "elevated_uncertainty"}:
        return "caution", "Сценарий рассчитан, но содержит повышенную неопределенность или ограничения поддержки."
    return "unavailable", "Однозначная оценка качества сценария недоступна."


def _component(
    component_id: str,
    title: str,
    status: str,
    display_text: str,
    observed_value: float | str | None = None,
) -> dict[str, Any]:
    return {
        "component_id": component_id,
        "title": title,
        "status": status,
        "score": None,
        "observed_value": observed_value,
        "display_text": display_text,
    }


def _reliability(campaign: Mapping[str, Any], scenario: Mapping[str, Any]) -> dict[str, Any]:
    support = scenario.get("support") or {}
    cell_code = ((scenario.get("cell_support_status") or {}).get("code"))
    quality_code = (((scenario.get("quality") or {}).get("status") or {}).get("code"))
    coverage = (campaign.get("budget") or {}).get("model_coverage_share")
    uncertainty = (scenario.get("quality") or {}).get("uncertainty_width_share")
    business_code = (((campaign.get("statuses") or {}).get("business_decision_status") or {}).get("code"))

    if not scenario.get("available") or cell_code == "not_evaluated":
        historical = ("unavailable", "Похожесть на исторические бюджеты не оценена.")
    elif cell_code in {"above_robust_upper", "above_p99_within_robust_upper"} or int(
        support.get("hard_warnings") or 0
    ) or int(support.get("strong_warnings") or 0):
        historical = ("poor", "Есть заметный выход за устойчивую историческую область.")
    elif int(support.get("elevated_warnings") or 0) or cell_code in {
        "between_p95_p99",
        "above_p99_within_robust_upper",
    }:
        historical = ("caution", "Часть бюджета находится у границы исторического опыта.")
    else:
        historical = ("good", "Бюджет находится внутри устойчивой исторической области.")

    model_status = {
        "reliable": ("good", "Модельный статус сценария не содержит специальных ограничений."),
        "elevated_uncertainty": ("caution", "Модель отмечает повышенную неопределенность."),
        "manual_review_required": ("poor", "Перед использованием нужна ручная проверка."),
        "not_for_automatic_reallocation": ("poor", "Автоматическое перераспределение для сценария недоступно."),
        "not_calculated": ("unavailable", "Сценарий не рассчитан."),
    }.get(quality_code, ("unavailable", "Модельный статус недоступен."))

    if not scenario.get("available"):
        extrapolation = ("unavailable", "Выход за наблюдаемую область не оценен.")
    elif cell_code in {"above_robust_upper", "above_p99_within_robust_upper"} or int(
        support.get("hard_warnings") or 0
    ) or int(support.get("strong_warnings") or 0):
        extrapolation = ("poor", "Обнаружен сильный выход за наблюдаемую область.")
    elif int(support.get("elevated_warnings") or 0):
        extrapolation = ("caution", "Есть умеренный выход к границе наблюдаемой области.")
    else:
        extrapolation = ("good", "Признаки выхода за наблюдаемую область не обнаружены.")

    if coverage is None:
        completeness = ("unavailable", "Доля рассчитанного бюджета недоступна.")
    elif float(coverage) >= 1.0 - 1e-9:
        completeness = ("good", "Рассчитан весь доступный модели бюджет.")
    elif float(coverage) > 0:
        completeness = ("caution", "Рассчитана только часть бюджета кампании.")
    else:
        completeness = ("poor", "Доступная модели часть бюджета не рассчитана.")

    business = {
        "meets_business_hurdle": ("good", "Утвержденный бизнес-порог выполнен."),
        "below_business_hurdle": ("poor", "Утвержденный бизнес-порог не выполнен."),
        "manual_review_required": ("caution", "Бизнес-ограничения требуют ручной проверки."),
        "allocation_only": ("unavailable", "Бизнес-порог запуска кампании пока не утвержден."),
        "not_evaluated": ("unavailable", "Бизнес-ограничения не оценены."),
    }.get(business_code, ("unavailable", "Бизнес-ограничения не оценены."))

    components = [
        _component("historical_support", "Похожесть на исторические данные", *historical),
        _component("model_support", "Поддержка со стороны модели", *model_status),
        _component("extrapolation", "Выход за наблюдаемую область", *extrapolation),
        _component(
            "posterior_uncertainty",
            "Неопределенность оценки",
            "unavailable",
            "Порог перевода ширины интервала в балл надежности не утвержден.",
            float(uncertainty) if uncertainty is not None else None,
        ),
        _component("business_constraints", "Бизнес-ограничения", *business),
        _component(
            "data_completeness",
            "Полнота рассчитанного бюджета",
            *completeness,
            float(coverage) if coverage is not None else None,
        ),
    ]
    return {
        "score": None,
        "status": "unavailable",
        "display_text": "Единая оценка надежности по шкале 1–10 пока не утверждена.",
        "components": components,
    }


def _report(evidence: _Evidence) -> dict[str, Any]:
    artifact = evidence.artifact("marketer_report_xlsx")
    working = evidence.artifact("working_media_plan_xlsx", required=False)
    working_payload = {
        "status": "unavailable",
        "display_text": "Отдельный рабочий медиаплан в формате XLSX пока не формируется.",
        "artifact": None,
    }
    if working is not None:
        working_payload = {
            "status": "ready",
            "display_text": "Рабочий медиаплан готов.",
            "artifact": _artifact_public(working[1]),
        }
    assert artifact is not None
    path, item = artifact
    try:
        with zipfile.ZipFile(path) as workbook:
            workbook_info = workbook.getinfo("xl/workbook.xml")
            if workbook_info.file_size > 2 * 1024 * 1024:
                raise ResultProjectionStateError(
                    "Published marketer report workbook metadata is unexpectedly large"
                )
            root = ElementTree.fromstring(workbook.read(workbook_info))
    except (KeyError, OSError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise ResultProjectionStateError("Published marketer report is not a readable XLSX") from exc
    namespace = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    sheet_names = [str(node.attrib.get("name") or "").strip() for node in root.findall("main:sheets/main:sheet", namespace)]
    if not sheet_names or any(not name for name in sheet_names):
        raise ResultProjectionStateError("Published marketer report has no readable sheets")
    return {
        "status": "ready",
        "display_text": "Excel-отчет готов.",
        "generated_at_utc": None,
        "artifact": _artifact_public(item),
        "sheets": [
            {"sheet_name": name, "title": name, "description": None}
            for name in sheet_names
        ],
        "working_media_plan": working_payload,
    }


def _recommendation_status(campaign: Mapping[str, Any]) -> str:
    optimizer_code = (((campaign.get("statuses") or {}).get("optimizer_status") or {}).get("code"))
    calculation_code = (((campaign.get("statuses") or {}).get("calculation_status") or {}).get("code"))
    if calculation_code == "not_calculated":
        return "unavailable"
    if optimizer_code in {"no_safe_candidate", "gate_policy_blocked", "not_run"}:
        return "no_safe_recommendation"
    return "recommended"


def _recommendation_text(campaign: Mapping[str, Any], status: str) -> str:
    if status == "no_safe_recommendation":
        return "Автоматическое перераспределение не предложено. Исходный план остается точкой отсчета для ручного решения."
    if status == "unavailable":
        return "Рекомендация недоступна, потому что расчет не завершен."
    code = ((campaign.get("recommendation") or {}).get("recommendation_type") or {}).get("code")
    return {
        "keep_uploaded_plan": "Сохранить загруженное распределение бюджета.",
        "reallocate_for_reliability": "Использовать распределение с меньшим риском выхода за наблюдаемую область.",
        "reallocate_for_effect": "Использовать распределение с подтвержденным содержательным улучшением.",
        "partial_safe_plan": "Использовать рассчитанную часть плана, а остаток проверить вручную.",
        "manual_review": "Перед изменением распределения провести ручную проверку.",
    }.get(str(code), "Использовать сценарий, выбранный утвержденными правилами расчета.")


def _product_warnings(
    campaign: Mapping[str, Any],
    selected_scenario: Mapping[str, Any],
    recommendation_status: str,
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    coverage = float((campaign.get("budget") or {}).get("model_coverage_share") or 0.0)
    if coverage < 1.0 - 1e-9:
        warnings.append(
            {
                "code": "partial_model_coverage",
                "severity": "manual_review",
                "title": "Рассчитана только часть бюджета",
                "display_text": f"Модель покрывает {coverage:.1%} загруженного бюджета. Непокрытая часть не считается нулевым эффектом.",
                "recommended_action": "Отдельно проверьте каналы и бюджет, которые не вошли в расчет.",
                "scope": "campaign",
            }
        )

    support = _scenario_record(campaign, str(selected_scenario["scenario_id"]))["support"]
    elevated = int(support.get("elevated_warnings") or 0)
    strong = int(support.get("strong_warnings") or 0)
    hard = int(support.get("hard_warnings") or 0)
    policy = int(support.get("policy_violations") or 0)
    if elevated or strong or hard or policy:
        severity = "blocking" if hard or policy else ("manual_review" if strong else "caution")
        warnings.append(
            {
                "code": "selected_scenario_support_risk",
                "severity": severity,
                "title": "Есть ограничения исторической поддержки",
                "display_text": (
                    "В выбранном для показа сценарии отмечены ограничения: "
                    f"умеренные — {elevated}, сильные — {strong}, блокирующие — {hard}, "
                    f"ограничения автоматического распределения — {policy}."
                ),
                "recommended_action": "Проверьте отмеченные связки перед изменением медиаплана.",
                "scope": "selected_scenario",
            }
        )

    if recommendation_status == "no_safe_recommendation":
        warnings.append(
            {
                "code": "automatic_reallocation_unavailable",
                "severity": "manual_review",
                "title": "Автоматическое перераспределение не предложено",
                "display_text": "Расчет не подтвердил вариант, который можно автоматически рекомендовать для перераспределения бюджета.",
                "recommended_action": "Используйте исходный план как точку отсчета и принимайте изменение вручную.",
                "scope": "recommendation",
            }
        )

    business_code = (((campaign.get("statuses") or {}).get("business_decision_status") or {}).get("code"))
    if business_code in {"allocation_only", "not_evaluated"}:
        warnings.append(
            {
                "code": "campaign_launch_threshold_unavailable",
                "severity": "info",
                "title": "Решение о запуске остается за бизнесом",
                "display_text": "Утвержденный порог для решения о запуске или отмене кампании не настроен.",
                "recommended_action": "Используйте результат только для сравнения и распределения бюджета.",
                "scope": "campaign",
            }
        )

    audit = (campaign.get("scenario6") or {}).get("audit") or {}
    if audit.get("search_converged") is False or audit.get("search_budget_exhausted") is True:
        warnings.append(
            {
                "code": "scenario6_search_limit_reached",
                "severity": "info",
                "title": "Перебор вариантов завершен по заданному лимиту",
                "display_text": "Найденный вариант является лучшим среди проверенных, но не доказанно лучшим из всех возможных.",
                "recommended_action": "Сравнивайте его с исходным и устойчивым сценариями, а не воспринимайте как единственно возможный план.",
                "scope": "scenario6",
            }
        )
    return warnings


def _headline(metric_id: str, title: str, metric: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "metric_id": metric_id,
        "title": title,
        "status": metric["status"],
        "unit": metric["unit"],
        "p10": metric["p10"],
        "p50": metric["p50"],
        "p90": metric["p90"],
        "value": None,
        "display_text": metric["display_text"],
    }


def _scalar_headline(
    metric_id: str,
    title: str,
    unit: str,
    value: float | int | None,
    display_text: str,
) -> dict[str, Any]:
    return {
        "metric_id": metric_id,
        "title": title,
        "status": "available" if value is not None else "unavailable",
        "unit": unit,
        "p10": None,
        "p50": None,
        "p90": None,
        "value": value,
        "display_text": display_text,
    }


def _best_raw_block(
    campaign: Mapping[str, Any],
    recommendation_candidate_id: str | None,
    allocation_rows: list[dict[str, str]],
) -> dict[str, Any]:
    raw = (campaign.get("scenario6") or {}).get("best_raw")
    if not isinstance(raw, Mapping) or raw.get("candidate_id") == recommendation_candidate_id:
        return {
            "available": False,
            "scenario_id": None,
            "raw_rank": None,
            "safe_rank": None,
            "reason_not_recommended": None,
            "metrics": None,
            "blocking_cells_status": "not_applicable",
            "blocking_cells": [],
        }
    candidate_name = _candidate_name_by_id(allocation_rows, str(raw.get("candidate_id")))
    safe_rank, raw_rank = _candidate_ranks(allocation_rows, candidate_name) if candidate_name else (None, None)
    blocking_cells = []
    if candidate_name:
        for row in _candidate_rows(allocation_rows, candidate_name):
            codes = [code for code in str(row.get("gate_reason_codes") or "").split("|") if code and code != "OK"]
            if codes:
                blocking_cells.append(
                    {
                        "segment": str(row.get("segment") or ""),
                        "geo": str(row.get("geo") or ""),
                        "channel": str(row.get("channel") or ""),
                        "reason": "Связка не прошла проверку для автоматического увеличения бюджета.",
                    }
                )
    metrics = {
        "incremental_turnover_rub": _metric(
            raw.get("incremental_turnover"),
            unit="RUB",
            usage="audit_only",
            available_text="Ожидаемый дополнительный оборот сырого лидера поиска.",
            unavailable_text="Финальная оценка оборота сырого лидера недоступна.",
        ),
        "roas": _metric(
            raw.get("turnover_roas"),
            unit="ratio",
            usage="audit_only",
            available_text="ROAS сырого лидера поиска.",
            unavailable_text="ROAS сырого лидера недоступен.",
        ),
    }
    eligible = bool(raw.get("eligible_for_automatic_recommendation"))
    reason = (
        "Вариант прошел ограничения, но правила выбора рекомендации не подтвердили содержательное преимущество над выбранным планом."
        if eligible
        else "Вариант показан для сравнения, но не прошел все проверки для автоматической рекомендации."
    )
    return {
        "available": True,
        "scenario_id": "S06",
        "raw_rank": raw_rank,
        "safe_rank": safe_rank,
        "reason_not_recommended": reason,
        "metrics": metrics,
        "blocking_cells_status": "available" if blocking_cells else "unavailable",
        "blocking_cells": blocking_cells,
    }


def build_job_result_view(
    *,
    job_id: str,
    job: Mapping[str, Any],
    result: Mapping[str, Any],
    overview: Mapping[str, Any],
    artifact_resolver: ArtifactResolver,
) -> dict[str, Any]:
    """Build the four-tab result projection for one completed campaign."""

    campaign = _validate_sources(job_id, job, result, overview)
    evidence = _Evidence(overview, artifact_resolver)
    candidates = _scenario_candidates(evidence, campaign)
    allocation_rows = _all_allocation_rows(evidence, campaign)
    recommendation_status = _recommendation_status(campaign)
    canonical_scenario_id = str((campaign.get("recommendation") or {}).get("scenario_id") or "")
    selected_scenario_id = canonical_scenario_id if recommendation_status == "recommended" else "S01"
    selected_plan = _build_plan_evidence(
        campaign, candidates, allocation_rows, selected_scenario_id
    )

    best_safe_id = (((campaign.get("scenario6") or {}).get("best_safe") or {}).get("candidate_id"))
    best_raw_id = (((campaign.get("scenario6") or {}).get("best_raw") or {}).get("candidate_id"))
    if recommendation_status in {"no_safe_recommendation", "unavailable"} and best_safe_id is not None:
        raise ResultProjectionStateError(
            "No-safe recommendation state cannot publish a best-safe candidate"
        )
    scenario_views = []
    for scenario_id in SCENARIO_IDS:
        scenario = _scenario_record(campaign, scenario_id)
        title, description, role = SCENARIO_COPY[scenario_id]
        candidate_name = candidates.get(scenario_id)
        candidate_id = _opaque_id("candidate", candidate_name) if candidate_name else None
        safe_rank, raw_rank = _candidate_ranks(allocation_rows, candidate_name) if candidate_name else (None, None)
        quality_status, quality_text = _scenario_quality(scenario)
        scenario_views.append(
            {
                "scenario_id": scenario_id,
                "title": title,
                "description": description,
                "role": role,
                "status": "completed" if scenario.get("available") else "unavailable",
                "is_recommended": recommendation_status == "recommended" and scenario_id == canonical_scenario_id,
                "is_best_safe": candidate_id is not None and candidate_id == best_safe_id,
                "is_best_raw": candidate_id is not None and candidate_id == best_raw_id,
                "safe_rank": safe_rank,
                "raw_rank": raw_rank,
                "quality_status": quality_status,
                "quality_display_text": quality_text,
                "budget": dict(scenario["budget"]),
                "metrics": _scenario_metrics(scenario),
                "reliability": _reliability(campaign, scenario),
            }
        )

    recommended_candidate = candidates.get(canonical_scenario_id) if recommendation_status == "recommended" else None
    recommendation_safe_rank, recommendation_raw_rank = _candidate_ranks(
        allocation_rows, recommended_candidate
    ) if recommended_candidate else (None, None)
    best_safe_name = _candidate_name_by_id(allocation_rows, best_safe_id)
    best_safe_rank, best_safe_raw_rank = _candidate_ranks(
        allocation_rows, best_safe_name
    ) if best_safe_name else (None, None)
    selected_scenario = next(row for row in scenario_views if row["scenario_id"] == selected_scenario_id)
    selected_metrics = selected_scenario["metrics"]
    report = _report(evidence)
    map_view = {
        "status": "unavailable",
        "display_text": "Данные для карты пока недоступны.",
        "geo_points": None,
        "coordinate_catalog_version": None,
    }

    payload = {
        "contract_name": "job_result_view_v1",
        "schema_version": "1.0.0",
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
            "campaign_id": campaign["campaign_id"],
            "campaign_name": campaign["passport"]["campaign_name"],
            "segments": list(campaign["passport"]["segments"]),
            "start_date": campaign["passport"]["source_start_date"],
            "end_date": campaign["passport"]["source_end_date"],
            "total_budget_rub": float(campaign["budget"]["uploaded_budget_rub"]),
            "channels_n": len(campaign["passport"]["source_channels"]),
            "geographies_n": len(campaign["passport"]["geographies"]),
            "model_coverage_share": float(campaign["budget"]["model_coverage_share"]),
        },
        "recommendation": {
            "status": recommendation_status,
            "scenario_id": canonical_scenario_id if recommendation_status == "recommended" else None,
            "title": {
                "recommended": "Рекомендуемое распределение бюджета",
                "no_safe_recommendation": "Автоматическая рекомендация недоступна",
                "unavailable": "Рекомендация недоступна",
            }[recommendation_status],
            "display_text": _recommendation_text(campaign, recommendation_status),
            "decision_scope_text": "Рекомендация относится к распределению бюджета, а не к решению о запуске кампании.",
            "safe_rank": recommendation_safe_rank,
            "raw_rank": recommendation_raw_rank,
            "best_safe": {
                "available": best_safe_name is not None,
                "scenario_id": "S06" if best_safe_name is not None else None,
                "safe_rank": best_safe_rank,
                "raw_rank": best_safe_raw_rank,
                "display_text": (
                    "Лучший вариант, прошедший проверки для автоматического перераспределения."
                    if best_safe_name is not None
                    else "Отдельный лучший безопасный вариант не опубликован."
                ),
            },
        },
        "overview": {
            "selected_scenario_id": selected_scenario_id,
            "source_scenario_id": "S01",
            "benchmark_scenario_id": "S05",
            "headline_metrics": [
                _headline("incremental_turnover_rub", "Дополнительный оборот", selected_metrics["incremental_turnover_rub"]),
                _headline("incremental_orders", "Дополнительные заказы", selected_metrics["incremental_orders"]),
                _headline("orders_per_100k_rub", "Заказы на 100 000 рублей", selected_metrics["orders_per_100k_rub"]),
                _headline("avg_basket_delta_rub", "Изменение среднего чека", selected_metrics["avg_basket_delta_rub"]),
                _scalar_headline(
                    "total_budget_rub",
                    "Бюджет сценария",
                    "RUB",
                    float(selected_scenario["budget"]["allocated_budget_rub"]),
                    "Бюджет, распределенный в выбранном для показа сценарии.",
                ),
                _scalar_headline(
                    "reliability_score",
                    "Оценка надежности",
                    "score_1_10",
                    None,
                    "Единая шкала надежности пока не утверждена.",
                ),
                _scalar_headline(
                    "safe_rank",
                    "Место среди проверенных вариантов",
                    "rank",
                    selected_scenario["safe_rank"],
                    "Порядок среди всех проверенных распределений с учетом ограничений; это не оценка качества по шкале 1–10.",
                ),
            ],
            "scenario_range": {
                "metric_id": "incremental_turnover_rub",
                "unit": "RUB",
                "rows": [
                    {
                        "scenario_id": row["scenario_id"],
                        "p10": row["metrics"]["incremental_turnover_rub"]["p10"],
                        "p50": row["metrics"]["incremental_turnover_rub"]["p50"],
                        "p90": row["metrics"]["incremental_turnover_rub"]["p90"],
                        "quality_status": row["quality_status"],
                    }
                    for row in scenario_views
                    if row["metrics"]["incremental_turnover_rub"]["status"] == "available"
                ],
            },
            "channel_summary": selected_plan["by_channel"],
            "geo_summary": selected_plan["by_geo"],
            "geo_channel_summary": selected_plan["by_geo_channel"],
        },
        "scenarios": scenario_views,
        "reliability": selected_scenario["reliability"],
        "warnings": _product_warnings(
            campaign,
            selected_scenario,
            recommendation_status,
        ),
        "best_raw": _best_raw_block(
            campaign,
            _opaque_id("candidate", recommended_candidate) if recommended_candidate else None,
            allocation_rows,
        ),
        "media_plan": {
            "endpoint": f"/api/v1/jobs/{job_id}/media-plan",
            "selected_scenario_id": selected_scenario_id,
            "grain": "geo_channel_total",
            "scenario_options": [
                {
                    "scenario_id": row["scenario_id"],
                    "title": row["title"],
                    "status": row["status"],
                }
                for row in scenario_views
            ],
            "daily_plan": {
                "status": "unavailable",
                "display_text": "Дневная разбивка сценариев не публикуется текущими результатами.",
            },
            "map": map_view,
            "working_media_plan": report["working_media_plan"],
        },
        "report": report,
        "limitations": [
            {
                "code": "incremental_effect_only",
                "display_text": "Результат показывает дополнительный эффект кампании относительно варианта без кампании, а не полный прогноз оборота.",
            },
            {
                "code": "turnover_roas_not_profit",
                "display_text": "ROAS рассчитан по дополнительному обороту и не является оценкой прибыли или contribution margin.",
            },
            {
                "code": "orders_diagnostic_only",
                "display_text": "Заказы и заказы на 100 000 рублей используются только как диагностические показатели.",
            },
            {
                "code": "avg_basket_delta_unavailable",
                "display_text": "Изменение среднего чека в рублях на заказ не выделено в текущем результате.",
            },
            {
                "code": "reliability_score_unapproved",
                "display_text": "Числовая шкала надежности 1–10 пока не утверждена.",
            },
            {
                "code": "daily_plan_unavailable",
                "display_text": "Медиаплан доступен на уровне география × канал без дневной разбивки.",
            },
            {
                "code": "map_unavailable",
                "display_text": "Карта недоступна без утвержденного справочника координат.",
            },
        ],
    }
    validate_job_result_view_payload(payload)
    return payload


def build_scenario_media_plan(
    *,
    job_id: str,
    job: Mapping[str, Any],
    result: Mapping[str, Any],
    overview: Mapping[str, Any],
    artifact_resolver: ArtifactResolver,
    scenario_id: str,
    page: int = 1,
    page_size: int = 100,
    channel: str | None = None,
    geo: str | None = None,
    date: str | None = None,
) -> dict[str, Any]:
    """Build one stable, paginated geo-by-channel media-plan page."""

    if scenario_id not in SCENARIO_IDS:
        raise UnsupportedMediaPlanQuery("Поддерживаются только сценарии S01–S06.")
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise UnsupportedMediaPlanQuery("page должен быть положительным целым числом.")
    if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 500:
        raise UnsupportedMediaPlanQuery("page_size должен быть от 1 до 500.")
    if date is not None:
        raise UnsupportedMediaPlanQuery("Фильтр по дате недоступен: текущий план не содержит дневной разбивки.")

    campaign = _validate_sources(job_id, job, result, overview)
    evidence = _Evidence(overview, artifact_resolver)
    candidates = _scenario_candidates(evidence, campaign)
    allocation_rows = _all_allocation_rows(evidence, campaign)
    plan = _build_plan_evidence(campaign, candidates, allocation_rows, scenario_id)
    allocation_artifact = evidence.artifact("recommended_allocations_csv")
    assert allocation_artifact is not None
    allocation_item = allocation_artifact[1]
    scenario = _scenario_record(campaign, scenario_id)
    rows = [
        row
        for row in plan["rows"]
        if (channel is None or row["channel"] == channel)
        and (geo is None or row["geo"] == geo)
    ]
    total_rows = len(rows)
    total_pages = math.ceil(total_rows / page_size) if total_rows else 0
    start = (page - 1) * page_size
    page_rows = rows[start : start + page_size]
    filtered_source = sum(float(row["source_budget_rub"]) for row in rows)
    filtered_selected = sum(float(row["selected_budget_rub"]) for row in rows)
    quality_status, quality_text = _scenario_quality(scenario)
    payload = {
        "contract_name": "scenario_media_plan_v1",
        "schema_version": "1.0.0",
        "record_origin": (
            "sanitized_fixture"
            if overview.get("result_origin") == "sanitized_fixture"
            else "application_runtime"
        ),
        "job_id": job_id,
        "result_id": result["result_id"],
        "campaign_id": campaign["campaign_id"],
        "scenario": {
            "scenario_id": scenario_id,
            "title": SCENARIO_COPY[scenario_id][0],
            "status": "completed",
            "is_selected": scenario_id == (campaign.get("recommendation") or {}).get("scenario_id"),
            "safe_rank": plan["safe_rank"],
            "raw_rank": plan["raw_rank"],
            "quality_status": quality_status,
            "quality_display_text": quality_text,
        },
        "source_artifact": {
            "artifact_id": allocation_item["artifact_id"],
            "kind": "recommended_allocations_csv",
            "sha256": allocation_item["sha256"],
        },
        "grain": "geo_channel_total",
        "filters": {"channel": channel, "geo": geo, "date": None},
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_rows": total_rows,
            "total_pages": total_pages,
        },
        "totals": {
            "requested_budget_rub": float(scenario["budget"]["requested_budget_rub"]),
            "source_budget_rub": plan["source_total"],
            "selected_budget_rub": plan["selected_total"],
            "unallocated_budget_rub": float(scenario["budget"]["unallocated_budget_rub"]),
            "delta_rub": plan["selected_total"] - plan["source_total"],
            "reconciliation_status": "reconciled",
        },
        "filtered_totals": {
            "source_budget_rub": filtered_source,
            "selected_budget_rub": filtered_selected,
            "delta_rub": filtered_selected - filtered_source,
        },
        "rows": page_rows,
        "aggregates": {
            "by_channel": plan["by_channel"],
            "by_geo": plan["by_geo"],
            "by_geo_channel": plan["by_geo_channel"],
            "by_date": {
                "status": "unavailable",
                "display_text": "Дневная разбивка не опубликована.",
                "rows": None,
            },
            "channel_date_matrix": {
                "status": "unavailable",
                "display_text": "Матрица канал × дата недоступна без дневной разбивки.",
                "rows": None,
            },
            "geo_channel_matrix": {
                "status": "ready",
                "display_text": "Матрица география × канал готова.",
                "rows": plan["by_geo_channel"],
            },
        },
        "map": {
            "status": "unavailable",
            "display_text": "Данные для карты пока недоступны.",
            "geo_points": None,
            "coordinate_catalog_version": None,
        },
        "working_media_plan": {
            "status": "unavailable",
            "display_text": "Отдельный рабочий медиаплан в формате XLSX пока не формируется.",
            "artifact": None,
        },
        "limitations": [
            {
                "code": "geo_channel_total_grain_only",
                "display_text": "Строки отражают итоговый бюджет по связке география × канал за весь период кампании.",
            },
            {
                "code": "daily_plan_unavailable",
                "display_text": "Дневная разбивка и календарь пока недоступны.",
            },
        ],
        "updated_at_utc": job.get("finished_at_utc") or overview["created_at_utc"],
    }
    validate_scenario_media_plan_payload(payload)
    return payload
