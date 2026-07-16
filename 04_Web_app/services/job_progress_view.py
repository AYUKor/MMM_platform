"""Build a browser-safe nine-stage progress snapshot from persisted records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from contracts.application_lifecycle_v1 import (
    ApplicationErrorV1,
    DecisionJobV1,
    LifecycleContractValidationError,
    ProgressEventV1,
    ValidationResultV1,
    parse_lifecycle_contract,
)
from contracts.job_progress_view_v1 import (
    CONTRACT_NAME,
    SCHEMA_VERSION,
    CampaignProgressSummary,
    JobProgressViewV1,
    ProductStage,
    ProgressStatus,
    ProgressViewError,
    QueueSummary,
    ReportProgress,
    Scenario6Progress,
    StageProgress,
    STAGE_CATALOG,
)


INTERNAL_STAGE_TO_PRODUCT_STAGE: dict[str, str] = {
    "prepare": "P02",
    "forecast": "P03",
    "benchmarks": "P03",
    "scenario6": "P06",
    "final_scoring": "P07",
    "report": "P08",
}

_JOB_STATUS_TEXT = {
    "queued": "Расчет ожидает запуска",
    "running": "Расчет выполняется",
    "cancel_requested": "Останавливаем расчет",
    "succeeded": "Расчет завершен",
    "failed": "Расчет завершился с ошибкой",
    "cancelled": "Расчет отменен",
    "timed_out": "Расчет не завершен вовремя",
}

_STAGE_TEXT = {
    "P01": {
        "pending": "Ожидает постановки в очередь.",
        "active": "Задача ожидает запуска.",
        "completed": "Задача передана на выполнение.",
        "failed": "Задачу не удалось запустить.",
        "skipped": "Этап не выполнялся.",
    },
    "P02": {
        "pending": "Подготовка еще не началась.",
        "active": "Проверяем файлы и параметры расчета.",
        "completed": "Медиаплан подготовлен.",
        "failed": "Не удалось подготовить медиаплан.",
        "skipped": "Подготовка не выполнялась.",
    },
    "P03": {
        "pending": "Исходный медиаплан еще не рассчитан.",
        "active": "Оцениваем исходное распределение бюджета.",
        "completed": "Исходный медиаплан рассчитан.",
        "failed": "Не удалось рассчитать исходный медиаплан.",
        "skipped": "Исходный медиаплан не рассчитывался.",
    },
    "P04": {
        "pending": "Контрольные сценарии еще не рассчитаны.",
        "active": "Оцениваем три контрольных распределения.",
        "completed": "Контрольные сценарии рассчитаны.",
        "failed": "Не удалось рассчитать контрольные сценарии.",
        "skipped": "Контрольные сценарии не рассчитывались.",
    },
    "P05": {
        "pending": "Устойчивый вариант еще не рассчитан.",
        "active": "Оцениваем вариант в более привычной исторической зоне.",
        "completed": "Устойчивый вариант рассчитан.",
        "failed": "Не удалось рассчитать устойчивый вариант.",
        "skipped": "Устойчивый вариант не рассчитывался.",
    },
    "P06": {
        "pending": "Поиск вариантов еще не начался.",
        "active": "Перебираем допустимые варианты распределения.",
        "completed": "Поиск вариантов завершен.",
        "failed": "Не удалось завершить поиск вариантов.",
        "skipped": "Адаптивный поиск недоступен для этой кампании.",
    },
    "P07": {
        "pending": "Финальная проверка еще не началась.",
        "active": "Сравниваем варианты и проверяем ограничения.",
        "completed": "Проверка результатов завершена.",
        "failed": "Не удалось завершить проверку результатов.",
        "skipped": "Финальная проверка не выполнялась.",
    },
    "P08": {
        "pending": "Формирование отчета еще не началось.",
        "active": "Формируем Excel-отчет и файлы результата.",
        "completed": "Отчет и файлы результата готовы.",
        "failed": "Расчет выполнен, но отчет не сформирован.",
        "skipped": "Отчет не формировался.",
    },
    "P09": {
        "pending": "Результат еще не опубликован.",
        "active": "Публикуем проверенный результат.",
        "completed": "Результат доступен для просмотра.",
        "failed": "Результат не опубликован.",
        "skipped": "Результат недоступен.",
    },
}


class ProgressProjectionError(ValueError):
    """Raised when persisted application state cannot form a safe projection."""


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _latest_timestamp(values: Sequence[str | None]) -> str:
    present = [value for value in values if value]
    if not present:
        raise ProgressProjectionError("Progress state has no timestamp")
    return max(present, key=_parse_timestamp)


def _first_event_time(
    events: Sequence[ProgressEventV1],
    stages: set[str],
) -> str | None:
    return next(
        (event.emitted_at_utc for event in events if event.stage in stages),
        None,
    )


def _counter_value(
    events: Sequence[ProgressEventV1],
    name: str,
) -> tuple[int | None, int | None]:
    for event in reversed(events):
        for counter in event.counters:
            if counter.name != name:
                continue
            current = int(counter.current) if float(counter.current).is_integer() else None
            total = (
                int(counter.total)
                if counter.total is not None and float(counter.total).is_integer()
                else None
            )
            return current, total
    return None, None


def _parse_records(
    job_payload: Mapping[str, Any],
    validation_payload: Mapping[str, Any],
    progress_payloads: Sequence[Mapping[str, Any]],
    error_payloads: Sequence[Mapping[str, Any]],
) -> tuple[
    DecisionJobV1,
    ValidationResultV1,
    tuple[ProgressEventV1, ...],
    tuple[ApplicationErrorV1, ...],
]:
    try:
        job = parse_lifecycle_contract(job_payload)
        validation = parse_lifecycle_contract(validation_payload)
        progress = tuple(parse_lifecycle_contract(item) for item in progress_payloads)
        errors = tuple(parse_lifecycle_contract(item) for item in error_payloads)
    except (KeyError, TypeError, LifecycleContractValidationError) as exc:
        raise ProgressProjectionError("Persisted lifecycle records are invalid") from exc
    if not isinstance(job, DecisionJobV1) or not isinstance(validation, ValidationResultV1):
        raise ProgressProjectionError("Progress projection requires job and validation records")
    if any(not isinstance(item, ProgressEventV1) for item in progress):
        raise ProgressProjectionError("Progress resource contains another contract")
    if any(not isinstance(item, ApplicationErrorV1) for item in errors):
        raise ProgressProjectionError("Error resource contains another contract")
    typed_progress = tuple(item for item in progress if isinstance(item, ProgressEventV1))
    typed_errors = tuple(item for item in errors if isinstance(item, ApplicationErrorV1))
    if job.validation_id != validation.validation_id:
        raise ProgressProjectionError("Job and validation do not match")
    if len(validation.campaigns) != 1:
        raise ProgressProjectionError("Progress view requires exactly one campaign")
    if any(event.job_id != job.job_id for event in typed_progress):
        raise ProgressProjectionError("Progress event belongs to another job")
    if any(event.attempt_number > job.attempt_number for event in typed_progress):
        raise ProgressProjectionError("Progress event belongs to a future attempt")
    if job.attempt_number > 0:
        typed_progress = tuple(
            event for event in typed_progress if event.attempt_number == job.attempt_number
        )
    sequences = [event.sequence for event in typed_progress]
    if sequences != sorted(sequences) or len(sequences) != len(set(sequences)):
        raise ProgressProjectionError("Progress event sequence is not monotonic")
    event_times = [_parse_timestamp(event.emitted_at_utc) for event in typed_progress]
    if event_times != sorted(event_times):
        raise ProgressProjectionError("Progress event timestamps are not monotonic")
    if any(error.resource_id != job.job_id for error in typed_errors):
        raise ProgressProjectionError("Application error belongs to another job")
    return job, validation, typed_progress, typed_errors


def _scenario6_from_result(
    result_payload: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    if result_payload is None:
        return None
    campaign_results = result_payload.get("campaign_results")
    if not isinstance(campaign_results, list) or len(campaign_results) != 1:
        return None
    scenario6 = campaign_results[0].get("scenario6")
    return scenario6 if isinstance(scenario6, Mapping) else None


def _report_is_available(result_payload: Mapping[str, Any] | None) -> bool:
    if result_payload is None:
        return False
    artifacts = result_payload.get("artifacts")
    if not isinstance(artifacts, list):
        return False
    return any(
        isinstance(item, Mapping) and item.get("kind") == "marketer_report_xlsx"
        for item in artifacts
    )


def _scenario6_status(
    job: DecisionJobV1,
    events: Sequence[ProgressEventV1],
    errors: Sequence[ApplicationErrorV1],
    result_scenario6: Mapping[str, Any] | None,
) -> str:
    run_status = None
    if result_scenario6 is not None and isinstance(result_scenario6.get("run_status"), Mapping):
        run_status = result_scenario6["run_status"].get("code")
    if run_status in {
        "completed_best_safe",
        "completed_partial_safe",
        "completed_no_safe_candidate",
    }:
        return "completed"
    if run_status in {"gate_policy_blocked", "not_run"}:
        return "unavailable"
    if any(error.stage == "scenario6" for error in errors):
        return "failed"
    if any(event.stage in {"final_scoring", "report"} for event in events):
        return "completed"
    if any(event.stage == "scenario6" for event in events):
        return (
            "running"
            if job.status.code in {"running", "cancel_requested"}
            else "unavailable"
        )
    if job.status.code in {"succeeded", "failed", "cancelled", "timed_out"}:
        return "unavailable"
    return "pending"


def _failure_stage_id(
    errors: Sequence[ApplicationErrorV1],
    fallback: str,
) -> str:
    for error in reversed(errors):
        if error.stage in INTERNAL_STAGE_TO_PRODUCT_STAGE:
            return INTERNAL_STAGE_TO_PRODUCT_STAGE[str(error.stage)]
    return fallback


def _stage_order(stage_id: str) -> int:
    return next(order for known_id, order, _ in STAGE_CATALOG if known_id == stage_id)


def _current_order(job: DecisionJobV1, events: Sequence[ProgressEventV1]) -> int:
    if job.status.code == "queued":
        return 1
    current = 2
    scenario6_seen = False
    for event in events:
        if event.stage == "prepare" and event.state == "completed":
            current = max(current, 3)
        elif event.stage == "benchmarks":
            current = max(current, 3)
        elif event.stage == "scenario6":
            scenario6_seen = True
            current = max(current, 6)
        elif event.stage == "forecast":
            current = max(current, 6 if scenario6_seen else 3)
        elif event.stage == "final_scoring":
            current = max(current, 7)
        elif event.stage == "report":
            current = max(current, 9 if event.state == "completed" else 8)
    if job.status.code == "succeeded":
        return 9
    return current


def _stage_boundaries(
    job: DecisionJobV1,
    events: Sequence[ProgressEventV1],
    current_order: int,
    updated_at: str,
) -> dict[int, str | None]:
    prepare = _first_event_time(events, {"prepare"})
    scenario = _first_event_time(
        events,
        {"benchmarks", "forecast", "scenario6", "final_scoring", "report"},
    )
    scenario6 = _first_event_time(events, {"scenario6"})
    final_scoring = _first_event_time(events, {"final_scoring"})
    report = _first_event_time(events, {"report"})
    boundaries: dict[int, str | None] = {
        1: job.queued_at_utc,
        2: job.started_at_utc or prepare,
        3: scenario,
        4: scenario,
        5: scenario,
        6: scenario6 or final_scoring or report,
        7: final_scoring or report,
        8: report,
        9: job.finished_at_utc,
    }
    last = job.queued_at_utc
    for order in range(1, current_order + 1):
        value = boundaries[order]
        if value is None:
            value = last if order > 1 else updated_at
        if _parse_timestamp(value) < _parse_timestamp(last):
            value = last
        boundaries[order] = value
        last = value
    return boundaries


def _build_stages(
    job: DecisionJobV1,
    current_order: int,
    boundaries: Mapping[int, str | None],
    updated_at: str,
    scenario6_status: str,
    attempts_checked: int | None,
    attempt_budget: int | None,
    failure_stage_id: str | None,
) -> tuple[ProductStage, ...]:
    terminal_failure = job.status.code in {"failed", "timed_out"}
    terminal_cancel = job.status.code == "cancelled"
    failure_order = _stage_order(failure_stage_id) if failure_stage_id else None
    stages: list[ProductStage] = []
    for stage_id, order, title in STAGE_CATALOG:
        if terminal_failure and failure_order is not None:
            if order < failure_order:
                status = "completed"
            elif order == failure_order:
                status = "failed"
            else:
                status = "skipped"
        elif terminal_cancel:
            status = "completed" if order < current_order else "skipped"
        elif job.status.code == "succeeded":
            status = "completed"
        elif order < current_order:
            status = "completed"
        elif order == current_order:
            status = "active"
        else:
            status = "pending"

        if stage_id == "P06" and scenario6_status == "unavailable" and order <= current_order:
            status = "skipped"

        if status == "pending":
            started_at = None
            finished_at = None
        elif status == "active":
            started_at = boundaries.get(order) or updated_at
            finished_at = None
        elif status in {"completed", "failed"}:
            started_at = boundaries.get(order) or updated_at
            next_boundary = boundaries.get(order + 1)
            finished_at = (
                job.finished_at_utc
                if status == "failed"
                else next_boundary or job.finished_at_utc or updated_at
            )
            if _parse_timestamp(finished_at) < _parse_timestamp(started_at):
                finished_at = started_at
        else:
            started_at = None
            finished_at = None

        progress = None
        if stage_id == "P06" and attempts_checked is not None:
            progress = StageProgress(
                current=attempts_checked,
                total=attempt_budget,
                unit="вариантов",
            )

        display_text = _STAGE_TEXT[stage_id][status]
        if stage_id == "P06" and status == "active" and attempts_checked is not None:
            display_text = (
                f"Проверено {attempts_checked:,} из {attempt_budget:,} вариантов".replace(
                    ",", " "
                )
                if attempt_budget is not None
                else f"Проверено {attempts_checked:,} вариантов".replace(",", " ")
            )
        stages.append(
            ProductStage(
                stage_id=stage_id,
                order=order,
                title=title,
                status=status,
                started_at_utc=started_at,
                finished_at_utc=finished_at,
                display_text=display_text,
                progress=progress,
            )
        )
    return tuple(stages)


def _build_errors(
    job: DecisionJobV1,
    errors: Sequence[ApplicationErrorV1],
    fallback_stage_id: str,
) -> tuple[ProgressViewError, ...]:
    projected: list[ProgressViewError] = []
    for error in errors:
        stage_id = INTERNAL_STAGE_TO_PRODUCT_STAGE.get(
            str(error.stage),
            fallback_stage_id,
        )
        blocking = error.error_id == job.terminal_error_id
        if error.retryable:
            action = (
                "Обновите страницу. Если состояние не изменится, запустите расчет "
                "повторно со страницы проверенного медиаплана."
            )
        else:
            action = (
                "Обратитесь к ответственному за сервис и сообщите номер расчета."
            )
        projected.append(
            ProgressViewError(
                error_id=error.error_id,
                stage_id=stage_id,
                severity="error",
                blocking=blocking,
                retryable=error.retryable,
                display_text=error.display_text,
                recommended_action=action,
            )
        )
    return tuple(projected)


def build_job_progress_view(
    *,
    job_payload: Mapping[str, Any],
    validation_payload: Mapping[str, Any],
    progress_payloads: Sequence[Mapping[str, Any]],
    error_payloads: Sequence[Mapping[str, Any]],
    result_payload: Mapping[str, Any] | None,
    queue_position: int | None,
    queued_jobs_total: int | None,
) -> JobProgressViewV1:
    """Project persisted lifecycle resources into one deterministic snapshot."""

    job, validation, events, errors = _parse_records(
        job_payload,
        validation_payload,
        progress_payloads,
        error_payloads,
    )
    campaign = validation.campaigns[0]
    timestamp_values: list[str | None] = [
        job.created_at_utc,
        job.queued_at_utc,
        job.started_at_utc,
        job.cancel_requested_at_utc,
        job.finished_at_utc,
        *(event.emitted_at_utc for event in events),
        *(error.occurred_at_utc for error in errors),
    ]
    updated_at = _latest_timestamp(timestamp_values)
    current_order = _current_order(job, events)
    fallback_stage_id = f"P{current_order:02d}"
    failure_stage_id = (
        _failure_stage_id(errors, fallback_stage_id)
        if job.status.code in {"failed", "timed_out"}
        else None
    )
    if failure_stage_id is not None:
        current_order = _stage_order(failure_stage_id)
        fallback_stage_id = failure_stage_id

    result_scenario6 = _scenario6_from_result(result_payload)
    scenario6_status = _scenario6_status(job, events, errors, result_scenario6)
    attempt_budget = job.sampling.scenario6_attempt_budget
    attempts_checked, event_attempt_budget = _counter_value(events, "attempts")
    finalists_scored, _ = _counter_value(events, "finalists")
    finalists_total = None
    if result_scenario6 is not None:
        result_budget = result_scenario6.get("attempt_budget")
        if isinstance(result_budget, int) and not isinstance(result_budget, bool):
            if result_budget != attempt_budget:
                raise ProgressProjectionError(
                    "Scenario 6 attempt budget does not match the immutable job"
                )
        result_attempts = result_scenario6.get("attempts_evaluated")
        if isinstance(result_attempts, int) and not isinstance(result_attempts, bool):
            attempts_checked = result_attempts
        result_finalists = result_scenario6.get("finalists")
        if isinstance(result_finalists, int) and not isinstance(result_finalists, bool):
            finalists_scored = result_finalists
            finalists_total = result_finalists
    if event_attempt_budget is not None and event_attempt_budget != attempt_budget:
        raise ProgressProjectionError(
            "Scenario 6 progress budget does not match the immutable job"
        )

    report_available = _report_is_available(result_payload)
    report_events = [event for event in events if event.stage == "report"]
    report_errors = [error for error in errors if error.stage == "report"]
    if job.status.code == "succeeded" and (
        result_payload is None or not report_available
    ):
        raise ProgressProjectionError(
            "Succeeded job is missing the required result or report"
        )
    if report_errors:
        report = ReportProgress(
            status="failed",
            display_text="Отчет не сформирован.",
            retryable=any(error.retryable for error in report_errors),
        )
    elif report_available:
        report = ReportProgress(
            status="completed",
            display_text="Excel-отчет готов.",
            retryable=False,
        )
    elif report_events:
        report = ReportProgress(
            status="running",
            display_text="Формируем Excel-отчет.",
            retryable=False,
        )
    elif job.status.code in {"failed", "cancelled", "timed_out"}:
        report = ReportProgress(
            status="not_required",
            display_text="Отчет не формировался, потому что расчет не был завершен.",
            retryable=False,
        )
    else:
        report = ReportProgress(
            status="pending",
            display_text="Отчет будет сформирован после проверки результатов.",
            retryable=False,
        )

    if report_available and job.status.code != "succeeded":
        current_order = max(current_order, 9)
        fallback_stage_id = f"P{current_order:02d}"
    boundaries = _stage_boundaries(job, events, current_order, updated_at)
    stages = _build_stages(
        job,
        current_order,
        boundaries,
        updated_at,
        scenario6_status,
        attempts_checked,
        attempt_budget,
        failure_stage_id,
    )

    if job.status.code == "queued":
        queue_position_known = queue_position is not None
        queue = QueueSummary(
            position=queue_position,
            queued_jobs_total=queued_jobs_total,
            display_text=(
                f"Позиция в очереди: {queue_position} из {queued_jobs_total}"
                if queue_position_known and queued_jobs_total is not None
                else "Положение в очереди уточняется."
            ),
        )
    elif job.status.code in {"running", "cancel_requested"}:
        queue = QueueSummary(
            position=None,
            queued_jobs_total=queued_jobs_total,
            display_text="Расчет уже запущен.",
        )
    else:
        queue = QueueSummary(
            position=None,
            queued_jobs_total=queued_jobs_total,
            display_text="Расчет больше не находится в очереди.",
        )

    record = JobProgressViewV1(
        contract_name=CONTRACT_NAME,
        schema_version=SCHEMA_VERSION,
        record_origin=job.record_origin,
        job_id=job.job_id,
        job_status=ProgressStatus(
            code=job.status.code,
            display_text=_JOB_STATUS_TEXT[job.status.code],
        ),
        queue=queue,
        campaign=CampaignProgressSummary(
            campaign_id=campaign.campaign_id,
            campaign_name=campaign.campaign_name,
            segment=campaign.segments,
            start_date=campaign.start_date,
            end_date=campaign.end_date,
            total_budget_rub=campaign.uploaded_budget_rub,
            channels_n=len(campaign.channels),
            geographies_n=len(campaign.geographies),
        ),
        current_stage_id=f"P{current_order:02d}",
        stages=stages,
        scenario6=Scenario6Progress(
            status=scenario6_status,
            attempt_budget=attempt_budget,
            attempts_checked=attempts_checked,
            safe_candidates=None,
            blocked_candidates=None,
            finalists_scored=finalists_scored,
            finalists_total=finalists_total,
        ),
        report=report,
        errors=_build_errors(job, errors, fallback_stage_id),
        can_cancel=job.status.code in {"queued", "running"},
        result_available=job.status.code == "succeeded" and result_payload is not None,
        updated_at_utc=updated_at,
    )
    try:
        record.validate()
    except Exception as exc:
        if isinstance(exc, ProgressProjectionError):
            raise
        raise ProgressProjectionError("Progress snapshot is inconsistent") from exc
    return record
