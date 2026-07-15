"""Build DecisionResult v1 from completed optimizer and marketer artifacts.

The adapter reads values only from completed, hash-checked artifacts. It does
not call forecast/optimizer code and does not recalculate MMM values.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


WEB_APP_DIR = Path(__file__).resolve().parents[1]
if str(WEB_APP_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_APP_DIR))

from contracts.decision_result_v1 import (  # noqa: E402
    CONTRACT_NAME,
    RESULT_ADAPTER_NAME,
    RESULT_ADAPTER_VERSION,
    SCHEMA_VERSION,
    AllocationLine,
    ArtifactReference,
    BudgetReconciliation,
    CampaignDecisionResult,
    CampaignPassport,
    DecisionResultV1,
    DecisionStatuses,
    JobLineage,
    ModelLineage,
    PairedComparison,
    PolicyLineage,
    QualitySummary,
    QuantileMetric,
    Recommendation,
    Scenario6Audit,
    ScenarioMetrics,
    ScenarioResult,
    Status,
    SupportSummary,
    WarningItem,
)


class OptimizerResultAdapterError(RuntimeError):
    """Raised when source artifacts cannot produce a trustworthy contract."""


STATUS_DISPLAY_TO_CODE: dict[str, dict[str, str]] = {
    "calculation_status": {
        "Рассчитано": "calculated",
        "Рассчитано частично": "partially_calculated",
        "Расчет не выполнен": "not_calculated",
        "Расчёт не выполнен": "not_calculated",
    },
    "campaign_scale_status": {
        "Сопоставимо с историческими кампаниями": "within_historical_p95",
        "Крупная, но похожие кампании встречались": "between_historical_p95_p99",
        "Очень крупная, нужна повышенная осторожность": "between_historical_p99_and_robust_upper",
        "Выше надежной наблюдаемой зоны": "above_historical_robust_upper",
        "Исторический benchmark недоступен": "benchmark_unavailable",
    },
    "cell_support_status": {
        "Внутри p95 support-zone": "within_p95",
        "Между p95 и p99": "between_p95_p99",
        "Выше p99, требуется ручная проверка": "above_p99_within_robust_upper",
        "Вне надежной наблюдаемой зоны": "above_robust_upper",
        "Не оценено": "not_evaluated",
    },
    "optimizer_status": {
        "Автоматический план доступен": "best_safe_available",
        "Лучший безопасный S6 рассчитан": "best_safe_available",
        "Частичный безопасный план": "partial_safe_available",
        "Безопасный автоматический план не найден": "no_safe_candidate",
        "Только ручное распределение": "no_safe_candidate",
        "Перераспределение недоступно по gate policy": "gate_policy_blocked",
        "Оптимизация не запускалась": "not_run",
    },
    "business_decision_status": {
        "Не настроено: нужен бизнес-порог": "allocation_only",
        "Бизнес-порог не настроен": "allocation_only",
        "Требуется ручное бизнес-решение": "manual_review_required",
        "Выше бизнес-порога": "meets_business_hurdle",
        "Ниже бизнес-порога": "below_business_hurdle",
        "Бизнес-решение не оценено": "not_evaluated",
    },
    "quality_status": {
        "Надежный расчет": "reliable",
        "Надёжный расчёт": "reliable",
        "Повышенная неопределенность": "elevated_uncertainty",
        "Требуется ручная проверка": "manual_review_required",
        "Не использовать для автоматического перераспределения": "not_for_automatic_reallocation",
        "Расчет не выполнен": "not_calculated",
    },
    "recommendation_type": {
        "Оставить исходный план": "keep_uploaded_plan",
        "Перераспределить ради надежности": "reallocate_for_reliability",
        "Перераспределить ради эффекта": "reallocate_for_effect",
        "Частичный безопасный план": "partial_safe_plan",
        "Требуется ручное решение": "manual_review",
    },
    "plan_status": {
        "Рекомендованный медиаплан": "recommended_media_plan",
        "Полный медиаплан; частичное покрытие модели": "full_plan_partial_model_coverage",
        "Частичный безопасный план": "partial_safe_plan",
        "Автоматический медиаплан недоступен": "no_automatic_plan",
    },
}


ARTIFACT_DISPLAY_NAMES = {
    "marketer_report_xlsx": "Отчет для маркетолога",
    "technical_optimizer_xlsx": "Технический отчет optimizer",
    "scenario_results_csv": "Результаты сценариев",
    "recommendations_csv": "Рекомендации",
    "best_plan_csv": "Рекомендованный медиаплан",
    "decision_pool_csv": "Пул сценариев для решения",
    "candidate_scores_csv": "Оценки кандидатов optimizer",
    "finalist_summary_csv": "Результаты финалистов",
    "recommended_allocations_csv": "Техническое распределение бюджета",
    "paired_comparisons_csv": "Парные posterior-сравнения",
    "search_trace_csv": "Трассировка Scenario 6",
    "optimizer_run_card": "Run card optimizer",
    "marketer_report_card": "Run card marketer report",
    "campaign_prepare_card": "Run card подготовки кампании",
    "model_resolution": "Разрешение model package",
    "optimizer_policy_snapshot": "Снимок optimizer policy",
    "business_policy_snapshot": "Снимок business policy",
}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OptimizerResultAdapterError(f"Cannot read JSON artifact {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise OptimizerResultAdapterError(f"JSON artifact must contain an object: {path.name}")
    return value


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except OSError as exc:
        raise OptimizerResultAdapterError(f"Cannot read CSV artifact {path.name}: {exc}") from exc


def _find_one(output_dir: Path, pattern: str) -> Path:
    matches = sorted(output_dir.glob(pattern))
    if len(matches) != 1:
        raise OptimizerResultAdapterError(
            f"Expected one artifact matching {pattern!r}, found {len(matches)} in {output_dir}"
        )
    return matches[0]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _opaque_id(prefix: str, source: str) -> str:
    return f"{prefix}_{hashlib.sha256(source.encode('utf-8')).hexdigest()[:20]}"


def _status(domain: str, display_text: str) -> Status:
    normalized = str(display_text or "").strip()
    try:
        code = STATUS_DISPLAY_TO_CODE[domain][normalized]
    except KeyError as exc:
        raise OptimizerResultAdapterError(
            f"Unmapped {domain} display value {normalized!r}; update the versioned adapter mapping"
        ) from exc
    return Status(code=code, display_text=normalized)


def _float(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = row.get(key)
    if value is None or str(value).strip() == "":
        return float(default)
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise OptimizerResultAdapterError(f"Field {key} must be numeric, got {value!r}") from exc
    if not math.isfinite(result):
        raise OptimizerResultAdapterError(f"Field {key} must be finite")
    return result


def _optional_float(row: dict[str, Any], key: str) -> float | None:
    value = row.get(key)
    if value is None or str(value).strip() == "":
        return None
    return _float(row, key)


def _fraction_value(row: dict[str, Any], key: str) -> float | None:
    value = _optional_float(row, key)
    if value is None:
        return None
    tolerance = 1e-9
    if abs(value) <= tolerance:
        return 0.0
    if abs(value - 1.0) <= tolerance:
        return 1.0
    if not 0.0 <= value <= 1.0:
        raise OptimizerResultAdapterError(f"Field {key} must be between 0 and 1, got {value}")
    return value


def _budget_rub(value: float) -> float:
    return 0.0 if abs(value) < 0.01 else value


def _int(row: dict[str, Any], key: str, default: int = 0) -> int:
    return int(round(_float(row, key, float(default))))


def _bool(row: dict[str, Any], key: str, default: bool = False) -> bool:
    value = row.get(key)
    if value is None or str(value).strip() == "":
        return default
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise OptimizerResultAdapterError(f"Field {key} must be boolean, got {value!r}")


def _split_list(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    items = [item.strip() for item in str(value).split(",")]
    return tuple(item for item in items if item and item.lower() != "nan")


def _active_days(row: dict[str, Any], count_key: str, start_value: str, end_value: str) -> int:
    count = _int(row, count_key) if row.get(count_key) not in (None, "") else 0
    if count > 0:
        return count
    try:
        return (date.fromisoformat(end_value) - date.fromisoformat(start_value)).days + 1
    except ValueError as exc:
        raise OptimizerResultAdapterError(
            f"Cannot derive active days from {start_value!r} to {end_value!r}"
        ) from exc


def _metric_from_mln(row: dict[str, Any], prefix: str, unit: str) -> QuantileMetric | None:
    values = [_optional_float(row, f"{prefix}_{quantile}_mln") for quantile in ("p10", "p50", "p90")]
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise OptimizerResultAdapterError(f"Incomplete quantiles for {prefix}")
    return QuantileMetric(
        unit=unit,
        p10=float(values[0]) * 1_000_000.0,
        p50=float(values[1]) * 1_000_000.0,
        p90=float(values[2]) * 1_000_000.0,
    )


def _metric_from_raw(row: dict[str, Any], prefix: str, unit: str) -> QuantileMetric | None:
    """Read quantiles whose legacy column suffix does not match their stored unit."""

    values = [_optional_float(row, f"{prefix}_{quantile}_mln") for quantile in ("p10", "p50", "p90")]
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise OptimizerResultAdapterError(f"Incomplete quantiles for {prefix}")
    return QuantileMetric(
        unit=unit,
        p10=float(values[0]),
        p50=float(values[1]),
        p90=float(values[2]),
    )


def _scenario_metrics(row: dict[str, Any]) -> ScenarioMetrics:
    return ScenarioMetrics(
        incremental_turnover=_metric_from_mln(row, "rto", "RUB"),
        roas_p50=_optional_float(row, "rto_roas_p50")
        if row.get("rto_roas_p50") not in (None, "")
        else _optional_float(row, "roas_p50"),
        # The marketer CSV keeps raw order counts in legacy *_mln columns.
        incremental_orders=_metric_from_raw(row, "orders", "orders"),
        avg_basket_bridge=_metric_from_mln(
            row, "basket", "turnover_bridge_from_avg_basket_rub"
        ),
    )


def _finalist_total_metric(
    finalist_rows: list[dict[str, Any]],
    candidate_name: str,
    target: str,
    unit: str,
) -> QuantileMetric | None:
    matches = [
        row
        for row in finalist_rows
        if str(row.get("candidate_name") or "") == candidate_name
        and str(row.get("segment") or "") == "__ALL__"
        and str(row.get("channel") or "") == "__TOTAL__"
        and str(row.get("target") or "") == target
    ]
    if not matches:
        return None
    if len(matches) != 1:
        raise OptimizerResultAdapterError(
            f"Expected one total finalist row for {candidate_name!r}/{target}, found {len(matches)}"
        )
    row = matches[0]
    return QuantileMetric(
        unit=unit,
        p10=_float(row, "total_effect_p10"),
        p50=_float(row, "total_effect_p50"),
        p90=_float(row, "total_effect_p90"),
    )


def _scenario_metrics_with_finalists(
    row: dict[str, Any], finalist_rows: list[dict[str, Any]]
) -> ScenarioMetrics:
    base = _scenario_metrics(row)
    candidate_name = str(row.get("candidate_name") or "")
    if not candidate_name or not finalist_rows:
        return base
    return ScenarioMetrics(
        incremental_turnover=base.incremental_turnover,
        roas_p50=base.roas_p50,
        incremental_orders=_finalist_total_metric(
            finalist_rows, candidate_name, "orders_per_user", "orders"
        ),
        avg_basket_bridge=_finalist_total_metric(
            finalist_rows,
            candidate_name,
            "avg_basket",
            "turnover_bridge_from_avg_basket_rub",
        ),
    )


def _recommendation_metrics(row: dict[str, Any]) -> ScenarioMetrics:
    turnover = QuantileMetric(
        unit="RUB",
        p10=_float(row, "rto_p10_mln") * 1_000_000.0,
        p50=_float(row, "rto_p50_mln") * 1_000_000.0,
        p90=_float(row, "rto_p90_mln") * 1_000_000.0,
    )
    return ScenarioMetrics(
        incremental_turnover=turnover,
        roas_p50=_optional_float(row, "roas_p50"),
        incremental_orders=None,
        avg_basket_bridge=None,
    )


def _paired_comparison(row: dict[str, Any]) -> PairedComparison | None:
    deltas = [_optional_float(row, f"paired_delta_{quantile}") for quantile in ("p10", "p50", "p90")]
    if all(value is None for value in deltas):
        return None
    if any(value is None for value in deltas):
        raise OptimizerResultAdapterError("Paired comparison contains incomplete delta quantiles")
    return PairedComparison(
        delta_incremental_turnover=QuantileMetric(
            unit="RUB",
            p10=float(deltas[0]) * 1_000_000.0,
            p50=float(deltas[1]) * 1_000_000.0,
            p90=float(deltas[2]) * 1_000_000.0,
        ),
        probability_gt_zero=_fraction_value(row, "paired_probability_gt_zero"),
        probability_noninferior=_fraction_value(row, "paired_probability_noninferior"),
        moved_budget_rub=(
            _optional_float(row, "moved_budget_mln_rub") * 1_000_000.0
            if _optional_float(row, "moved_budget_mln_rub") is not None
            else None
        ),
        posterior_draws=_int(row, "paired_draws_n") if row.get("paired_draws_n") not in (None, "") else None,
    )


def _quality(row: dict[str, Any], coverage_key: str) -> QualitySummary:
    coverage = _fraction_value(row, coverage_key)
    width = _optional_float(row, "uncertainty_width_share")
    if width is None:
        p10 = _optional_float(row, "rto_p10_mln")
        p50 = _optional_float(row, "rto_p50_mln")
        p90 = _optional_float(row, "rto_p90_mln")
        if p10 is not None and p50 not in (None, 0.0) and p90 is not None:
            width = (p90 - p10) / abs(float(p50))
    return QualitySummary(
        status=_status("quality_status", str(row.get("quality_status", ""))),
        explanation=str(row.get("quality_explanation") or "").strip(),
        coverage_share=coverage,
        uncertainty_width_share=width,
    )


def _scenario_from_row(
    row: dict[str, Any], finalist_rows: list[dict[str, Any]] | None = None
) -> ScenarioResult:
    scenario_id = str(row.get("scenario_no") or "").strip()
    return ScenarioResult(
        scenario_id=scenario_id,
        name=str(row.get("scenario_name") or "").strip(),
        description=str(row.get("scenario_description") or "").strip(),
        available=True,
        requested_budget_rub=_budget_rub(
            _float(row, "requested_budget_mln_rub", _float(row, "budget_mln_rub")) * 1_000_000.0
        ),
        allocated_budget_rub=_budget_rub(
            _float(row, "allocated_budget_mln_rub", _float(row, "budget_mln_rub")) * 1_000_000.0
        ),
        unallocated_budget_rub=_budget_rub(_float(row, "unallocated_budget_mln_rub") * 1_000_000.0),
        metrics=_scenario_metrics_with_finalists(row, finalist_rows or []),
        calculation_status=_status("calculation_status", str(row.get("calculation_status", ""))),
        cell_support_status=_status("cell_support_status", str(row.get("cell_support_status", ""))),
        optimizer_status=_status("optimizer_status", str(row.get("optimizer_status", ""))),
        support=SupportSummary(
            elevated_warnings=_int(row, "elevated_support_warnings_n"),
            strong_warnings=_int(row, "strong_support_warnings_n"),
            hard_warnings=_int(row, "hard_support_warnings_n"),
            policy_violations=_int(row, "policy_violations_n"),
        ),
        quality=_quality(row, "allocated_budget_share"),
        paired_comparison=_paired_comparison(row),
    )


def _scenario6_from_recommendation(row: dict[str, Any]) -> ScenarioResult:
    return ScenarioResult(
        scenario_id="S06",
        name=str(row.get("scenario_name") or "Сценарий 6. Адаптивный поиск").strip(),
        description=str(row.get("scenario_description") or "Support-aware adaptive optimizer search.").strip(),
        available=True,
        requested_budget_rub=_budget_rub(_float(row, "requested_budget_mln_rub") * 1_000_000.0),
        allocated_budget_rub=_budget_rub(_float(row, "allocated_budget_mln_rub") * 1_000_000.0),
        unallocated_budget_rub=_budget_rub(_float(row, "unallocated_budget_mln_rub") * 1_000_000.0),
        metrics=_recommendation_metrics(row),
        calculation_status=_status("calculation_status", str(row.get("calculation_status", ""))),
        cell_support_status=_status("cell_support_status", str(row.get("cell_support_status", ""))),
        optimizer_status=_status("optimizer_status", str(row.get("optimizer_status", ""))),
        support=SupportSummary(
            elevated_warnings=_int(row, "elevated_support_warnings_n"),
            strong_warnings=_int(row, "strong_support_warnings_n"),
            hard_warnings=_int(row, "hard_support_warnings_n"),
            policy_violations=_int(row, "policy_violations_n"),
        ),
        quality=_quality(row, "effective_coverage_share"),
        paired_comparison=_paired_comparison(row),
    )


def _unavailable_scenario6(row: dict[str, Any], optimizer_status: Status) -> ScenarioResult:
    explanation = str(row.get("allocation_decision") or "Scenario 6 не сформировал автоматический план.").strip()
    return ScenarioResult(
        scenario_id="S06",
        name="Сценарий 6. Адаптивный поиск",
        description=explanation,
        available=False,
        requested_budget_rub=_float(row, "model_input_budget_rub")
        or _float(row, "requested_budget_mln_rub") * 1_000_000.0,
        allocated_budget_rub=0.0,
        unallocated_budget_rub=_float(row, "model_input_budget_rub")
        or _float(row, "requested_budget_mln_rub") * 1_000_000.0,
        metrics=ScenarioMetrics(
            incremental_turnover=None,
            roas_p50=None,
            incremental_orders=None,
            avg_basket_bridge=None,
        ),
        calculation_status=Status(code="not_calculated", display_text="Сценарий 6 не рассчитан"),
        cell_support_status=Status(code="not_evaluated", display_text="Не оценено"),
        optimizer_status=optimizer_status,
        support=SupportSummary(0, 0, 0, 0),
        quality=QualitySummary(
            status=Status(code="not_calculated", display_text="Сценарий недоступен"),
            explanation=explanation,
            coverage_share=None,
            uncertainty_width_share=None,
        ),
        paired_comparison=None,
    )


def _scenario6_audit(
    recommendation: dict[str, Any],
    candidates: list[dict[str, Any]],
    run_card: dict[str, Any],
    optimizer_status: Status,
) -> Scenario6Audit:
    scenario6_rows = [row for row in candidates if "__scenario6_" in str(row.get("candidate_name", ""))]
    actual_rows = [
        row for row in scenario6_rows if not str(row.get("precheck_status", "")).startswith("not_run")
    ]
    scored_rows = [row for row in actual_rows if str(row.get("precheck_status", "")) == "scored"]
    rejected_rows = [row for row in actual_rows if str(row.get("precheck_status", "")) != "scored"]
    diagnostic_row = next(
        (
            row
            for row in actual_rows
            if _optional_float(row, "search_attempts_evaluated_n") is not None
        ),
        None,
    )

    def diagnostic_int(key: str) -> int:
        return _int(diagnostic_row, key) if diagnostic_row is not None else 0

    def diagnostic_bool(key: str) -> bool | None:
        if diagnostic_row is None or str(diagnostic_row.get(key) or "").strip() == "":
            return None
        return _bool(diagnostic_row, key)

    best_raw = next((row for row in actual_rows if _bool(row, "is_best_raw_search")), None)
    if best_raw is None:
        ranked_raw = [row for row in actual_rows if _optional_float(row, "search_rank_raw") is not None]
        best_raw = min(ranked_raw, key=lambda row: _float(row, "search_rank_raw"), default=None)
    best_safe = next((row for row in actual_rows if _bool(row, "is_best_reliable_search")), None)
    if recommendation.get("scenario_no") == "S06" and optimizer_status.code in {
        "best_safe_available",
        "partial_safe_available",
    }:
        best_safe_candidate_id = _opaque_id("candidate", str(recommendation.get("candidate_name") or ""))
    elif best_safe is not None and optimizer_status.code in {"best_safe_available", "partial_safe_available"}:
        best_safe_candidate_id = _opaque_id("candidate", str(best_safe.get("candidate_name") or ""))
    else:
        best_safe_candidate_id = None

    run_status_code = {
        "best_safe_available": "completed_best_safe",
        "partial_safe_available": "completed_partial_safe",
        "no_safe_candidate": "completed_no_safe_candidate",
        "gate_policy_blocked": "gate_policy_blocked",
        "not_run": "not_run",
    }[optimizer_status.code]
    run_status_display = {
        "completed_best_safe": "Лучший безопасный вариант найден",
        "completed_partial_safe": "Найден частичный безопасный вариант",
        "completed_no_safe_candidate": "Безопасный вариант не найден",
        "gate_policy_blocked": "Поиск заблокирован gate policy",
        "not_run": "Поиск не запускался",
    }[run_status_code]
    explanation = str(recommendation.get("allocation_decision") or "").strip()
    if not explanation and scenario6_rows:
        explanation = str(scenario6_rows[0].get("precheck_reason") or "").strip()
    if not explanation:
        explanation = run_status_display

    return Scenario6Audit(
        run_status=Status(code=run_status_code, display_text=run_status_display),
        method=str(run_card.get("scenario6_method") or "not_run"),
        attempt_budget=int(run_card.get("search_candidates_per_campaign") or 0),
        attempts_evaluated=diagnostic_int("search_attempts_evaluated_n"),
        kernel_evaluations=diagnostic_int("search_kernel_evaluations_n"),
        unique_allocations=diagnostic_int("search_unique_allocations_n"),
        candidates_generated=len(actual_rows),
        candidates_scored=len(scored_rows),
        candidates_rejected=len(rejected_rows),
        finalists=len(scored_rows),
        search_posterior_draws=int(run_card.get("search_samples") or 0),
        final_posterior_draws=int(run_card.get("final_samples") or 0),
        search_converged=diagnostic_bool("search_converged"),
        search_budget_exhausted=diagnostic_bool("search_budget_exhausted"),
        best_raw_candidate_id=(
            _opaque_id("candidate", str(best_raw.get("candidate_name") or "")) if best_raw is not None else None
        ),
        best_safe_candidate_id=best_safe_candidate_id,
        explanation=explanation,
    )


def _campaign_warnings(
    row: dict[str, Any], statuses: DecisionStatuses, quality: QualitySummary
) -> tuple[WarningItem, ...]:
    warnings: list[WarningItem] = []
    unmodeled_budget = _float(row, "unmodeled_budget_rub")
    if unmodeled_budget > 0:
        channels = str(row.get("unmodeled_channels") or "неподдерживаемые каналы").strip()
        warnings.append(
            WarningItem(
                code="unmodeled_budget_present",
                severity="manual_review",
                display_text=(
                    f"Часть бюджета ({unmodeled_budget:,.0f} RUB) не рассчитана моделью: {channels}."
                ),
                scope="campaign",
            )
        )
    elevated = _int(row, "elevated_support_warnings_n")
    strong = _int(row, "strong_support_warnings_n")
    hard = _int(row, "hard_support_warnings_n")
    if elevated or strong or hard:
        severity = "manual_review" if strong or hard else "caution"
        warnings.append(
            WarningItem(
                code="cell_support_risk",
                severity=severity,
                display_text=(
                    f"Support warnings: elevated={elevated}, strong={strong}, hard={hard}. "
                    "Проверьте отмеченные geo x channel перед изменением медиаплана."
                ),
                scope="recommended_scenario",
            )
        )
    if statuses.optimizer_status.code in {"gate_policy_blocked", "no_safe_candidate", "not_run"}:
        warnings.append(
            WarningItem(
                code=statuses.optimizer_status.code,
                severity="manual_review",
                display_text=str(row.get("allocation_decision") or statuses.optimizer_status.display_text).strip(),
                scope="scenario6",
            )
        )
    if quality.status.code != "reliable":
        warnings.append(
            WarningItem(
                code=f"quality_{quality.status.code}",
                severity="caution" if quality.status.code == "elevated_uncertainty" else "manual_review",
                display_text=quality.explanation,
                scope="campaign",
            )
        )
    if statuses.business_decision_status.code == "allocation_only":
        warnings.append(
            WarningItem(
                code="business_hurdle_not_approved",
                severity="info",
                display_text=(
                    "Результат помогает распределить бюджет, но не принимает решение о запуске кампании: "
                    "ROAS/contribution-margin threshold не утвержден."
                ),
                scope="campaign",
            )
        )
    return tuple(warnings)


def _campaign_calculation_status(row: dict[str, Any]) -> Status:
    source_status = _status("calculation_status", str(row.get("calculation_status", "")))
    if source_status.code == "not_calculated":
        return source_status
    uncovered_budget = _float(row, "unmodeled_budget_rub")
    unallocated_budget = _float(row, "unallocated_budget_mln_rub") * 1_000_000.0
    coverage = _fraction_value(row, "effective_coverage_share")
    if uncovered_budget > 1.0 or unallocated_budget > 1.0 or (coverage is not None and coverage < 1.0 - 1e-9):
        return Status(code="partially_calculated", display_text="Рассчитано частично")
    return source_status


def _build_campaign(
    recommendation_row: dict[str, Any],
    scenario_rows: list[dict[str, Any]],
    decision_pool_rows: list[dict[str, Any]],
    allocation_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    finalist_rows: list[dict[str, Any]],
    run_card: dict[str, Any],
) -> CampaignDecisionResult:
    campaign_name = str(recommendation_row.get("campaign_name") or "").strip()
    if not campaign_name:
        raise OptimizerResultAdapterError("Recommendation row has no campaign_name")

    statuses = DecisionStatuses(
        calculation_status=_campaign_calculation_status(recommendation_row),
        campaign_scale_status=_status(
            "campaign_scale_status", str(recommendation_row.get("campaign_scale_status", ""))
        ),
        cell_support_status=_status(
            "cell_support_status", str(recommendation_row.get("cell_support_status", ""))
        ),
        optimizer_status=_status("optimizer_status", str(recommendation_row.get("optimizer_status", ""))),
        business_decision_status=_status(
            "business_decision_status", str(recommendation_row.get("business_decision_status", ""))
        ),
    )
    quality = _quality(recommendation_row, "effective_coverage_share")

    scenario_items = [_scenario_from_row(row) for row in scenario_rows]
    if len({scenario.scenario_id for scenario in scenario_items}) != len(scenario_items):
        raise OptimizerResultAdapterError(f"Campaign {campaign_name!r} contains duplicate scenario rows")
    scenarios_by_id = {scenario.scenario_id: scenario for scenario in scenario_items}

    pool_scenario6_rows = [row for row in decision_pool_rows if str(row.get("scenario_no") or "") == "S06"]
    if len(pool_scenario6_rows) > 1:
        raise OptimizerResultAdapterError(f"Campaign {campaign_name!r} contains duplicate S06 pool rows")
    if pool_scenario6_rows:
        scenarios_by_id["S06"] = _scenario_from_row(pool_scenario6_rows[0], finalist_rows)
    elif recommendation_row.get("scenario_no") == "S06":
        scenarios_by_id["S06"] = _scenario6_from_recommendation(recommendation_row)
    elif statuses.optimizer_status.code in {"best_safe_available", "partial_safe_available"}:
        raise OptimizerResultAdapterError(
            f"Campaign {campaign_name!r} reports a safe S6 but decision_pool has no S06 row"
        )
    if "S06" not in scenarios_by_id:
        scenarios_by_id["S06"] = _unavailable_scenario6(recommendation_row, statuses.optimizer_status)
    required_benchmarks = {f"S0{index}" for index in range(1, 6)}
    missing_benchmarks = sorted(required_benchmarks - set(scenarios_by_id))
    if missing_benchmarks:
        raise OptimizerResultAdapterError(
            f"Campaign {campaign_name!r} is missing benchmark scenarios: {missing_benchmarks}"
        )
    scenarios = tuple(scenarios_by_id[scenario_id] for scenario_id in sorted(scenarios_by_id))

    selected_scenario = scenarios_by_id.get(str(recommendation_row.get("scenario_no") or ""))
    recommendation_metrics = (
        selected_scenario.metrics if selected_scenario is not None else _recommendation_metrics(recommendation_row)
    )
    recommendation = Recommendation(
        scenario_id=str(recommendation_row.get("scenario_no") or "").strip(),
        scenario_name=str(recommendation_row.get("scenario_name") or "").strip(),
        candidate_id=_opaque_id("candidate", str(recommendation_row.get("candidate_name") or "")),
        recommendation_type=_status(
            "recommendation_type", str(recommendation_row.get("recommendation_type", ""))
        ),
        reason=str(recommendation_row.get("allocation_decision") or "").strip(),
        plan_status=_status("plan_status", str(recommendation_row.get("plan_status", ""))),
        optimizer_available=_bool(recommendation_row, "optimizer_available"),
        metrics=recommendation_metrics,
    )

    allocations = tuple(
        AllocationLine(
            segment=str(row.get("direction") or "").strip(),
            geo=str(row.get("geo") or "").strip(),
            channel=str(row.get("channel") or "").strip(),
            budget_rub=_budget_rub(_float(row, "recommended_budget_mln_rub") * 1_000_000.0),
            budget_share=float(_fraction_value(row, "budget_share") or 0.0),
            allocation_note=str(row.get("channel_policy") or "").strip(),
        )
        for row in allocation_rows
    )

    uploaded_budget = _budget_rub(_float(recommendation_row, "uploaded_budget_rub"))
    model_input_budget = _budget_rub(_float(recommendation_row, "model_input_budget_rub"))
    unmodeled_budget = _budget_rub(_float(recommendation_row, "unmodeled_budget_rub"))
    calculated_budget = _budget_rub(
        _float(recommendation_row, "allocated_budget_mln_rub") * 1_000_000.0
    )
    budget = BudgetReconciliation(
        uploaded_budget_rub=uploaded_budget,
        model_input_budget_rub=model_input_budget,
        calculated_budget_rub=calculated_budget,
        unmodeled_budget_rub=unmodeled_budget,
        unallocated_budget_rub=_budget_rub(
            _float(recommendation_row, "unallocated_budget_mln_rub") * 1_000_000.0
        ),
        model_coverage_share=min(1.0, max(0.0, model_input_budget / uploaded_budget if uploaded_budget else 0.0)),
    )
    creatives = _split_list(recommendation_row.get("creatives"))
    if creatives == ("Не указан в источнике",):
        creatives = ()
    source_start_date = str(
        recommendation_row.get("source_campaign_start") or recommendation_row.get("campaign_start") or ""
    ).strip()
    source_end_date = str(
        recommendation_row.get("source_campaign_end") or recommendation_row.get("campaign_end") or ""
    ).strip()
    model_start_date = str(
        recommendation_row.get("model_input_start") or recommendation_row.get("model_flighting_start") or ""
    ).strip()
    model_end_date = str(
        recommendation_row.get("model_input_end") or recommendation_row.get("model_flighting_end") or ""
    ).strip()
    passport = CampaignPassport(
        campaign_name=campaign_name,
        source_campaign_name=str(recommendation_row.get("source_campaign_name") or campaign_name).strip(),
        segments=_split_list(recommendation_row.get("directions")),
        source_start_date=source_start_date,
        source_end_date=source_end_date,
        model_start_date=model_start_date,
        model_end_date=model_end_date,
        source_active_days=_active_days(
            recommendation_row, "source_active_dates", source_start_date, source_end_date
        ),
        model_active_days=_active_days(
            recommendation_row, "model_input_active_dates", model_start_date, model_end_date
        ),
        source_channels=_split_list(
            recommendation_row.get("source_channels") or recommendation_row.get("channels")
        ),
        modeled_channels=_split_list(
            recommendation_row.get("modeled_channels") or recommendation_row.get("channels")
        ),
        unmodeled_channels=_split_list(recommendation_row.get("unmodeled_channels")),
        geographies=_split_list(recommendation_row.get("geos")),
        creatives=creatives,
    )

    return CampaignDecisionResult(
        campaign_id=_opaque_id("campaign", campaign_name),
        passport=passport,
        budget=budget,
        scenarios=scenarios,
        scenario6=_scenario6_audit(recommendation_row, candidate_rows, run_card, statuses.optimizer_status),
        recommendation=recommendation,
        recommended_allocation=allocations,
        statuses=statuses,
        quality=quality,
        warnings=_campaign_warnings(recommendation_row, statuses, quality),
    )


def _media_type(path: Path) -> str:
    return {
        ".csv": "text/csv",
        ".json": "application/json",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }.get(path.suffix.lower(), "application/octet-stream")


def _artifact_path(output_dir: Path, raw_path: Any) -> Path:
    name = Path(str(raw_path or "")).name
    if not name:
        raise OptimizerResultAdapterError("Artifact declaration has an empty path")
    path = output_dir / name
    if not path.is_file():
        raise OptimizerResultAdapterError(f"Declared artifact is missing: {name}")
    return path


def _build_artifacts(
    output_dir: Path,
    run_id: str,
    run_card_path: Path,
    report_card_path: Path,
    run_card: dict[str, Any],
    report_card: dict[str, Any],
    storage_prefix: str,
) -> tuple[ArtifactReference, ...]:
    prefix = str(PurePosixPath(storage_prefix.strip("/")))
    declarations: list[tuple[str, Path, str | None]] = []

    report_fields = {
        "output_xlsx": ("marketer_report_xlsx", "xlsx"),
        "scenario_results_csv": ("scenario_results_csv", "scenario_results_csv"),
        "recommendations_csv": ("recommendations_csv", "recommendations_csv"),
        "best_plan_csv": ("best_plan_csv", "best_plan_csv"),
        "decision_pool_csv": ("decision_pool_csv", "decision_pool_csv"),
    }
    report_hashes = report_card.get("output_sha256") or {}
    for field_name, (kind, hash_key) in report_fields.items():
        if report_card.get(field_name):
            declarations.append(
                (kind, _artifact_path(output_dir, report_card[field_name]), report_hashes.get(hash_key))
            )

    run_kind = {
        "candidate_scores_csv": "candidate_scores_csv",
        "finalist_summary_csv": "finalist_summary_csv",
        "recommended_allocations_csv": "recommended_allocations_csv",
        "paired_comparisons_csv": "paired_comparisons_csv",
        "search_trace_csv": "search_trace_csv",
        "xlsx": "technical_optimizer_xlsx",
    }
    run_hashes = run_card.get("output_sha256") or {}
    for key, raw_path in (run_card.get("outputs") or {}).items():
        kind = run_kind.get(key)
        if kind:
            declarations.append((kind, _artifact_path(output_dir, raw_path), run_hashes.get(key)))

    known_artifacts = {
        "optimizer_run_card": run_card_path,
        "marketer_report_card": report_card_path,
        "campaign_prepare_card": _find_one(output_dir, "*_campaign_prepare_card.json"),
        "model_resolution": output_dir / "model_resolution_optimizer.json",
        "optimizer_policy_snapshot": output_dir / "optimizer_decision_policy_snapshot.json",
        "business_policy_snapshot": output_dir / "business_threshold_policy_snapshot.json",
    }
    declarations.extend(
        (kind, path, None) for kind, path in known_artifacts.items() if path.is_file()
    )

    artifacts: list[ArtifactReference] = []
    seen_paths: set[Path] = set()
    for kind, path, expected_hash in declarations:
        resolved = path.resolve()
        if resolved in seen_paths:
            continue
        seen_paths.add(resolved)
        actual_hash = _sha256(path)
        if expected_hash and actual_hash != expected_hash:
            raise OptimizerResultAdapterError(
                f"Hash mismatch for {path.name}: expected {expected_hash}, got {actual_hash}"
            )
        artifact_id = _opaque_id("artifact", f"{run_id}:{kind}:{actual_hash}")
        artifacts.append(
            ArtifactReference(
                artifact_id=artifact_id,
                kind=kind,
                display_name=ARTIFACT_DISPLAY_NAMES[kind],
                media_type=_media_type(path),
                sha256=actual_hash,
                size_bytes=path.stat().st_size,
                storage_key=str(PurePosixPath(prefix) / run_id / path.name),
            )
        )
    return tuple(artifacts)


def build_decision_result(
    optimizer_output_dir: Path | str,
    *,
    storage_prefix: str = "optimizer-runs",
    job_id: str | None = None,
    workflow_config_sha256: str | None = None,
) -> DecisionResultV1:
    output_dir = Path(optimizer_output_dir).expanduser().resolve()
    if not output_dir.is_dir():
        raise OptimizerResultAdapterError(f"Optimizer output directory does not exist: {output_dir}")

    run_card_path = _find_one(output_dir, "*_optimizer_run_card.json")
    report_card_path = output_dir / "marketer_report_card.json"
    model_resolution_path = output_dir / "model_resolution_optimizer.json"
    run_card = _read_json(run_card_path)
    report_card = _read_json(report_card_path)
    model_resolution = _read_json(model_resolution_path)

    run_id = str(run_card.get("run_id") or "").strip()
    if not run_id:
        raise OptimizerResultAdapterError("Optimizer run card has no run_id")
    if model_resolution.get("package_id") is None or model_resolution.get("package_input_fingerprint") is None:
        raise OptimizerResultAdapterError("Model resolution lacks package identity")
    if report_card.get("forecast_recomputed_during_report") is not False:
        raise OptimizerResultAdapterError("Marketer report must be assembled from cached optimizer artifacts")

    scenario_path = _artifact_path(output_dir, report_card.get("scenario_results_csv"))
    decision_pool_path = _artifact_path(output_dir, report_card.get("decision_pool_csv"))
    recommendation_path = _artifact_path(output_dir, report_card.get("recommendations_csv"))
    best_plan_path = _artifact_path(output_dir, report_card.get("best_plan_csv"))
    candidate_path = _artifact_path(output_dir, (run_card.get("outputs") or {}).get("candidate_scores_csv"))
    finalist_path = _artifact_path(output_dir, (run_card.get("outputs") or {}).get("finalist_summary_csv"))

    scenario_rows = _read_csv(scenario_path)
    decision_pool_rows = _read_csv(decision_pool_path)
    recommendation_rows = _read_csv(recommendation_path)
    allocation_rows = _read_csv(best_plan_path)
    candidate_rows = _read_csv(candidate_path)
    finalist_rows = _read_csv(finalist_path)
    if not recommendation_rows:
        raise OptimizerResultAdapterError("No campaign recommendations found")

    scenarios_by_campaign: dict[str, list[dict[str, Any]]] = defaultdict(list)
    decision_pool_by_campaign: dict[str, list[dict[str, Any]]] = defaultdict(list)
    allocations_by_campaign: dict[str, list[dict[str, Any]]] = defaultdict(list)
    candidates_by_campaign: dict[str, list[dict[str, Any]]] = defaultdict(list)
    finalists_by_campaign: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in scenario_rows:
        scenarios_by_campaign[str(row.get("campaign_name") or "")].append(row)
    for row in decision_pool_rows:
        decision_pool_by_campaign[str(row.get("campaign_name") or "")].append(row)
    for row in allocation_rows:
        allocations_by_campaign[str(row.get("campaign_name") or "")].append(row)
    for row in candidate_rows:
        candidates_by_campaign[str(row.get("campaign_name") or "")].append(row)
    for row in finalist_rows:
        finalists_by_campaign[str(row.get("source_campaign_name") or "")].append(row)

    campaigns = tuple(
        _build_campaign(
            recommendation,
            scenarios_by_campaign[str(recommendation.get("campaign_name") or "")],
            decision_pool_by_campaign[str(recommendation.get("campaign_name") or "")],
            allocations_by_campaign[str(recommendation.get("campaign_name") or "")],
            candidates_by_campaign[str(recommendation.get("campaign_name") or "")],
            finalists_by_campaign[str(recommendation.get("campaign_name") or "")],
            run_card,
        )
        for recommendation in recommendation_rows
    )

    artifacts = _build_artifacts(
        output_dir,
        run_id,
        run_card_path,
        report_card_path,
        run_card,
        report_card,
        storage_prefix,
    )
    business_snapshot = (run_card.get("objective") or {}).get("business_threshold_policy_snapshot") or {}
    root_warnings = [
        WarningItem(
            code="model_preprod_restricted",
            severity="caution",
            display_text=(
                "Расчет выполнен preprod-моделью. Production activation ожидает обязательную OOT-валидацию."
            ),
            scope="model",
        )
    ]
    for blocker in run_card.get("model_production_blockers") or []:
        root_warnings.append(
            WarningItem(
                code=str(blocker).lower(),
                severity="caution",
                display_text=f"Production blocker модели: {blocker}.",
                scope="model",
            )
        )

    adapter_sha256 = _sha256(Path(__file__).resolve())
    resolved_job_id = job_id or _opaque_id("job", run_id)
    resolved_workflow_config_sha256 = (
        workflow_config_sha256 or str(run_card.get("workflow_config_sha256") or "")
    )
    if job_id is None and workflow_config_sha256 is None:
        result_seed = (
            f"{CONTRACT_NAME}:{SCHEMA_VERSION}:{RESULT_ADAPTER_VERSION}:{adapter_sha256}:"
            f"{run_id}:{model_resolution['package_id']}:"
            f"{report_card.get('output_sha256', {}).get('xlsx', '')}"
        )
    else:
        result_seed = (
            f"{CONTRACT_NAME}:{SCHEMA_VERSION}:{RESULT_ADAPTER_VERSION}:{adapter_sha256}:"
            f"{resolved_job_id}:{resolved_workflow_config_sha256}:{run_id}:"
            f"{model_resolution['package_id']}:"
            f"{report_card.get('output_sha256', {}).get('xlsx', '')}"
        )
    result = DecisionResultV1(
        contract_name=CONTRACT_NAME,
        schema_version=SCHEMA_VERSION,
        result_id=_opaque_id("result", result_seed),
        result_origin="verified_optimizer_artifacts",
        created_at_utc=str(run_card.get("finished_at_utc") or ""),
        job=JobLineage(
            job_id=resolved_job_id,
            source_run_id=run_id,
            job_type="forecast_optimizer_report",
            started_at_utc=str(run_card.get("started_at_utc") or ""),
            finished_at_utc=str(run_card.get("finished_at_utc") or ""),
            workflow_config_sha256=resolved_workflow_config_sha256,
            input_flighting_sha256=str(run_card.get("flighting_sha256") or ""),
            adapter_name=RESULT_ADAPTER_NAME,
            adapter_version=RESULT_ADAPTER_VERSION,
            adapter_sha256=adapter_sha256,
        ),
        model=ModelLineage(
            registry_channel=str(model_resolution.get("channel") or ""),
            registry_event_id=str(model_resolution.get("event_id") or ""),
            package_id=str(model_resolution.get("package_id") or ""),
            package_fingerprint=str(model_resolution.get("package_input_fingerprint") or ""),
            package_manifest_sha256=str(run_card.get("model_manifest_sha256") or ""),
            activation_status=str(run_card.get("model_activation_status") or ""),
            production_blockers=tuple(str(value) for value in run_card.get("model_production_blockers") or []),
        ),
        policies=PolicyLineage(
            optimizer_policy_id=str((run_card.get("decision_policy") or {}).get("policy_id") or ""),
            optimizer_policy_sha256=str(run_card.get("decision_policy_sha256") or ""),
            business_policy_id=str(business_snapshot.get("policy_id") or ""),
            business_policy_sha256=str(
                (run_card.get("objective") or {}).get("business_threshold_policy_sha256") or ""
            ),
            business_decision_mode=str((run_card.get("business_guardrails") or {}).get("business_decision_mode") or ""),
            search_seed=int(run_card.get("search_seed") or run_card.get("seed") or 0),
            final_seed=int(run_card.get("final_seed") or 0),
        ),
        campaign_results=campaigns,
        artifacts=artifacts,
        warnings=tuple(root_warnings),
    )
    result.validate()
    return result


def _replace_sha_values(value: Any, field_name: str = "root") -> Any:
    if isinstance(value, dict):
        replaced: dict[str, Any] = {}
        for key, nested in value.items():
            if key.endswith("sha256") and isinstance(nested, str):
                replaced[key] = hashlib.sha256(f"sanitized:{field_name}.{key}".encode("utf-8")).hexdigest()
            else:
                replaced[key] = _replace_sha_values(nested, f"{field_name}.{key}")
        return replaced
    if isinstance(value, list):
        return [_replace_sha_values(item, f"{field_name}[]") for item in value]
    if isinstance(value, tuple):
        return [_replace_sha_values(item, f"{field_name}[]") for item in value]
    return value


def sanitized_fixture_payload(result: DecisionResultV1) -> dict[str, Any]:
    """Return a labeled, deterministic and non-production fixture payload."""

    payload = _replace_sha_values(copy.deepcopy(result.to_dict()))
    payload["result_origin"] = "sanitized_fixture"
    payload["result_id"] = _opaque_id("result", "sanitized-decision-result-v1")
    payload["created_at_utc"] = "2026-01-01T00:00:00+00:00"
    payload["job"]["job_id"] = _opaque_id("job", "sanitized-decision-job-v1")
    payload["job"]["source_run_id"] = "sanitized_optimizer_run"
    payload["job"]["started_at_utc"] = "2026-01-01T00:00:00+00:00"
    payload["job"]["finished_at_utc"] = "2026-01-01T00:01:00+00:00"
    payload["model"]["registry_event_id"] = "sanitized_registry_event"
    payload["model"]["package_id"] = "pkg_sanitized_fixture"
    payload["model"]["package_fingerprint"] = hashlib.sha256(
        b"sanitized-decision-result-v1-package"
    ).hexdigest()

    label_maps: dict[str, dict[str, str]] = {"segment": {}, "geo": {}, "channel": {}}

    def label(kind: str, source: str) -> str:
        mapping = label_maps[kind]
        if source not in mapping:
            mapping[source] = f"{kind.upper()}_{len(mapping) + 1:02d}"
        return mapping[source]

    budget_scale = 0.137
    effect_scale = 0.083
    orders_scale = 0.419
    roas_scale = effect_scale / budget_scale

    def scale_fixture_values(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("unit") in {"RUB", "turnover_bridge_from_avg_basket_rub"}:
                for quantile in ("p10", "p50", "p90"):
                    if isinstance(node.get(quantile), (int, float)):
                        node[quantile] = round(float(node[quantile]) * effect_scale, 2)
            elif node.get("unit") == "orders":
                for quantile in ("p10", "p50", "p90"):
                    if isinstance(node.get(quantile), (int, float)):
                        node[quantile] = round(float(node[quantile]) * orders_scale, 4)
            for key, nested in node.items():
                if key.endswith("_rub") and isinstance(nested, (int, float)):
                    node[key] = round(float(nested) * budget_scale, 2)
                elif key == "roas_p50" and isinstance(nested, (int, float)):
                    node[key] = round(float(nested) * roas_scale, 6)
                else:
                    scale_fixture_values(nested)
        elif isinstance(node, list):
            for item in node:
                scale_fixture_values(item)

    scale_fixture_values(payload)
    for index, campaign in enumerate(payload["campaign_results"], start=1):
        passport = campaign["passport"]
        source_start = date(2026, 1, 1) + timedelta(days=(index - 1) * 60)
        model_start = source_start
        passport["source_start_date"] = source_start.isoformat()
        passport["source_end_date"] = (
            source_start + timedelta(days=max(int(passport["source_active_days"]) - 1, 0))
        ).isoformat()
        passport["model_start_date"] = model_start.isoformat()
        passport["model_end_date"] = (
            model_start + timedelta(days=max(int(passport["model_active_days"]) - 1, 0))
        ).isoformat()
        passport["campaign_name"] = f"Demo campaign {index}"
        passport["source_campaign_name"] = f"Demo source campaign {index}"
        passport["segments"] = [label("segment", value) for value in passport["segments"]]
        passport["source_channels"] = [label("channel", value) for value in passport["source_channels"]]
        passport["modeled_channels"] = [label("channel", value) for value in passport["modeled_channels"]]
        passport["unmodeled_channels"] = [label("channel", value) for value in passport["unmodeled_channels"]]
        passport["geographies"] = [label("geo", value) for value in passport["geographies"]]
        passport["creatives"] = [f"CREATIVE_{position:02d}" for position, _ in enumerate(passport["creatives"], 1)]
        campaign["campaign_id"] = _opaque_id("campaign", f"sanitized-campaign-{index}")
        campaign["recommendation"]["candidate_id"] = _opaque_id("candidate", f"sanitized-selected-{index}")
        for candidate_key in ("best_raw_candidate_id", "best_safe_candidate_id"):
            if campaign["scenario6"].get(candidate_key):
                campaign["scenario6"][candidate_key] = _opaque_id(
                    "candidate", f"sanitized-{candidate_key}-{index}"
                )
        for allocation in campaign["recommended_allocation"]:
            allocation["segment"] = label("segment", allocation["segment"])
            allocation["geo"] = label("geo", allocation["geo"])
            allocation["channel"] = label("channel", allocation["channel"])
        for scenario in campaign["scenarios"]:
            support = scenario["support"]
            support["elevated_warnings"] = min(int(support["elevated_warnings"]), 3)
            support["strong_warnings"] = min(int(support["strong_warnings"]), 1)
            support["hard_warnings"] = min(int(support["hard_warnings"]), 1)
            support["policy_violations"] = min(int(support["policy_violations"]), 1)
        for warning in campaign["warnings"]:
            warning["affected_cells"] = []
            warning["display_text"] = {
                "unmodeled_budget_present": (
                    "Часть демонстрационного бюджета находится вне покрытия модели."
                ),
                "cell_support_risk": (
                    "В демонстрационном плане есть geo x channel ячейки с повышенным support risk."
                ),
                "gate_policy_blocked": (
                    "Scenario 6 недоступен в этом демонстрационном состоянии из-за gate policy."
                ),
                "no_safe_candidate": (
                    "В демонстрационном состоянии безопасный автоматический вариант не найден."
                ),
                "business_hurdle_not_approved": (
                    "Fixture показывает allocation-only режим без утвержденного business hurdle."
                ),
            }.get(warning["code"], f"Демонстрационное предупреждение: {warning['code']}.")

    for index, artifact in enumerate(payload["artifacts"], start=1):
        artifact["artifact_id"] = _opaque_id("artifact", f"sanitized-artifact-{index}")
        artifact["display_name"] = f"Demo artifact {index}: {artifact['kind']}"
        artifact["size_bytes"] = 0
        suffix = {
            "text/csv": ".csv",
            "application/json": ".json",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        }.get(artifact["media_type"], ".bin")
        artifact["storage_key"] = f"fixtures/decision-result-v1/artifact-{index:02d}{suffix}"

    payload["warnings"].insert(
        0,
        {
            "code": "sanitized_fixture_not_production_evidence",
            "severity": "info",
            "display_text": "Sanitized fixture for contract and UI tests; not production evidence.",
            "scope": "result",
            "affected_cells": [],
        },
    )
    return payload


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--optimizer-output-dir", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--storage-prefix", default="optimizer-runs")
    parser.add_argument("--job-id")
    parser.add_argument("--workflow-config-sha256")
    parser.add_argument("--sanitized-fixture-output", type=Path)
    args = parser.parse_args(list(argv) if argv is not None else None)

    result = build_decision_result(
        args.optimizer_output_dir,
        storage_prefix=args.storage_prefix,
        job_id=args.job_id,
        workflow_config_sha256=args.workflow_config_sha256,
    )
    output_path = args.output or Path(args.optimizer_output_dir) / "decision_result_manifest_v1.json"
    write_json_atomic(output_path, result.to_dict())
    if args.sanitized_fixture_output is not None:
        write_json_atomic(args.sanitized_fixture_output, sanitized_fixture_payload(result))
    print(
        json.dumps(
            {
                "status": "ok",
                "result_id": result.result_id,
                "campaigns_n": len(result.campaign_results),
                "artifacts_n": len(result.artifacts),
                "output": str(output_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
