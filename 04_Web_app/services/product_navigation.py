"""Browser projections for product navigation pages.

The service reads existing application state, published result projections,
the active Model Passport and the versioned help catalog. It does not execute
or reproduce MMM, forecast, optimizer or recommendation calculations.
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


WEB_APP_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = WEB_APP_DIR.parent
PYMC_CODE_DIR = PROJECT_ROOT / "02_Code" / "01_PyMC"
for entry in (WEB_APP_DIR, PYMC_CODE_DIR):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from contracts.calculation_history_v1 import (  # noqa: E402
    ACTIVE_STATUSES,
    CONTRACT_NAME as HISTORY_CONTRACT,
    SCHEMA_VERSION as HISTORY_SCHEMA_VERSION,
    SORT_CODES,
    STATUS_FILTERS,
    validate_calculation_history_payload,
)
from contracts.help_catalog_v1 import validate_help_catalog_payload  # noqa: E402
from contracts.model_overview_v1 import (  # noqa: E402
    CONTRACT_NAME as MODEL_CONTRACT,
    SCHEMA_VERSION as MODEL_SCHEMA_VERSION,
    validate_model_overview_payload,
)
from contracts.product_api_v1 import validate_model_passport  # noqa: E402
from contracts.workspace_home_v1 import (  # noqa: E402
    CONTRACT_NAME as HOME_CONTRACT,
    SCHEMA_VERSION as HOME_SCHEMA_VERSION,
    validate_workspace_home_payload,
)
from mmm_core.model_registry import list_registrations  # noqa: E402


ResourceReader = Callable[[str, str], Any]
ValidationReader = Callable[[str], Mapping[str, Any]]
ProgressViewBuilder = Callable[[str], Mapping[str, Any]]

JOB_STATUSES = {
    "queued",
    "running",
    "cancel_requested",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
}
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "timed_out"}
STATUS_DISPLAY = {
    "queued": "В очереди",
    "running": "Выполняется",
    "cancel_requested": "Отмена запрошена",
    "succeeded": "Расчет завершен",
    "failed": "Расчет завершился с ошибкой",
    "cancelled": "Расчет отменен",
    "timed_out": "Расчет остановлен по времени ожидания",
}
DEFAULT_HELP_CATALOG = WEB_APP_DIR / "content" / "help_catalog_v1.json"


class ProductNavigationError(ValueError):
    """Base error for Phase D product projections."""


class ProductNavigationQueryError(ProductNavigationError):
    """Raised for invalid browser query values."""


class ProductNavigationStateError(ProductNavigationError):
    """Raised when published application facts contradict each other."""


class ProductNavigationUnavailableError(ProductNavigationError):
    """Raised when a required projection source cannot be read."""


def _utc_now(now: datetime | None = None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProductNavigationStateError("A timezone-aware clock is required")
    return value.astimezone(timezone.utc)


def _timestamp(value: Any, field_name: str, *, nullable: bool = False) -> datetime | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise ProductNavigationStateError(f"{field_name} is not a timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProductNavigationStateError(f"{field_name} is not a timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProductNavigationStateError(f"{field_name} has no timezone")
    return parsed.astimezone(timezone.utc)


def _iso_date(value: Any, field_name: str) -> date:
    if not isinstance(value, str):
        raise ProductNavigationStateError(f"{field_name} is not a date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ProductNavigationStateError(f"{field_name} is not a date") from exc


def _status(job: Mapping[str, Any]) -> str:
    status = job.get("status")
    code = status.get("code") if isinstance(status, Mapping) else None
    if code not in JOB_STATUSES:
        raise ProductNavigationStateError("Calculation status is missing or unsupported")
    return str(code)


def _campaign_facts(campaigns: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not campaigns:
        return {
            "campaign_name": "Сведения о кампании недоступны",
            "campaign_period": None,
            "total_budget_rub": None,
            "segments": None,
            "channels_n": None,
            "geographies_n": None,
        }

    names = sorted(
        {
            str(campaign.get("campaign_name") or "").strip()
            for campaign in campaigns
            if str(campaign.get("campaign_name") or "").strip()
        }
    )
    campaign_name = "; ".join(names) if names else "Сведения о кампании недоступны"

    periods: list[tuple[date, date]] = []
    period_complete = True
    for index, campaign in enumerate(campaigns):
        start = campaign.get("start_date")
        end = campaign.get("end_date")
        if start is None or end is None:
            period_complete = False
            break
        periods.append(
            (
                _iso_date(start, f"campaigns[{index}].start_date"),
                _iso_date(end, f"campaigns[{index}].end_date"),
            )
        )
    campaign_period = None
    if period_complete and periods:
        start = min(value[0] for value in periods)
        end = max(value[1] for value in periods)
        if end < start:
            raise ProductNavigationStateError("Campaign period is reversed")
        campaign_period = {"start_date": start.isoformat(), "end_date": end.isoformat()}

    budgets: list[float] = []
    budget_complete = True
    for campaign in campaigns:
        value = campaign.get("uploaded_budget_rub")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            budget_complete = False
            break
        budgets.append(float(value))

    def union_values(key: str) -> list[str] | None:
        output: set[str] = set()
        for campaign in campaigns:
            raw = campaign.get(key)
            if not isinstance(raw, list):
                return None
            for value in raw:
                text = str(value).strip()
                if text:
                    output.add(text)
        return sorted(output)

    segments = union_values("segments")
    channels = union_values("channels")
    geographies = union_values("geographies")
    return {
        "campaign_name": campaign_name,
        "campaign_period": campaign_period,
        "total_budget_rub": sum(budgets) if budget_complete else None,
        "segments": segments,
        "channels_n": len(channels) if channels is not None else None,
        "geographies_n": len(geographies) if geographies is not None else None,
    }


def _optional_resource(
    resource_reader: ResourceReader,
    job_id: str,
    resource: str,
) -> Mapping[str, Any] | None:
    try:
        payload = resource_reader(job_id, resource)
    except FileNotFoundError:
        return None
    if not isinstance(payload, Mapping):
        raise ProductNavigationStateError(f"Published {resource} resource is malformed")
    return payload


def _published_facts(
    *,
    job_id: str,
    status: str,
    resource_reader: ResourceReader,
    validation_id: str | None,
    validation_reader: ValidationReader | None,
) -> dict[str, Any]:
    result = _optional_resource(resource_reader, job_id, "result")
    overview = _optional_resource(resource_reader, job_id, "overview")
    result_available = status == "succeeded" and result is not None and overview is not None
    artifacts = overview.get("artifacts") if overview is not None else None
    if artifacts is not None and not isinstance(artifacts, list):
        raise ProductNavigationStateError("Published result artifacts are malformed")
    report_available = bool(
        result_available
        and any(
            isinstance(item, Mapping) and item.get("kind") == "marketer_report_xlsx"
            for item in artifacts or []
        )
    )
    warnings_count: int | None = None
    if overview is not None:
        root_warnings = overview.get("warnings")
        campaigns = overview.get("campaigns")
        if not isinstance(root_warnings, list) or not isinstance(campaigns, list):
            raise ProductNavigationStateError("Published result warnings are malformed")
        campaign_warnings = 0
        for campaign in campaigns:
            if not isinstance(campaign, Mapping) or not isinstance(campaign.get("warnings"), list):
                raise ProductNavigationStateError("Published campaign warnings are malformed")
            campaign_warnings += len(campaign["warnings"])
        warnings_count = len(root_warnings) + campaign_warnings
    elif validation_reader is not None and validation_id:
        try:
            validation = validation_reader(validation_id)
        except FileNotFoundError:
            validation = None
        if validation is not None:
            warnings = validation.get("warnings")
            if warnings is not None and not isinstance(warnings, list):
                raise ProductNavigationStateError("Validation warnings are malformed")
            warnings_count = len(warnings or [])
    return {
        "result_available": result_available,
        "report_available": report_available,
        "result_path": f"/calculations/{job_id}/result" if result_available else None,
        "warnings_count": warnings_count,
    }


def _history_rows(
    records: Sequence[Mapping[str, Any]],
    *,
    resource_reader: ResourceReader,
    validation_reader: ValidationReader | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        job = record.get("job")
        campaigns = record.get("campaigns")
        if not isinstance(job, Mapping) or not isinstance(campaigns, list):
            raise ProductNavigationStateError("Calculation history record is malformed")
        job_id = str(job.get("job_id") or "")
        if not job_id or job_id in seen:
            raise ProductNavigationStateError("Calculation identifiers are missing or duplicated")
        seen.add(job_id)
        status = _status(job)
        created = _timestamp(job.get("created_at_utc"), "job.created_at_utc")
        completed = _timestamp(
            job.get("finished_at_utc"),
            "job.finished_at_utc",
            nullable=True,
        )
        if status in TERMINAL_STATUSES and completed is None:
            raise ProductNavigationStateError("Completed calculation has no completion time")
        if status in ACTIVE_STATUSES and completed is not None:
            raise ProductNavigationStateError("Active calculation has a completion time")
        facts = _campaign_facts(
            [campaign for campaign in campaigns if isinstance(campaign, Mapping)]
        )
        if len(facts) != 6 or any(not isinstance(campaign, Mapping) for campaign in campaigns):
            raise ProductNavigationStateError("Campaign summary is malformed")
        validation_id = job.get("validation_id")
        published = _published_facts(
            job_id=job_id,
            status=status,
            resource_reader=resource_reader,
            validation_id=str(validation_id) if validation_id else None,
            validation_reader=validation_reader,
        )
        rows.append(
            {
                "job_id": job_id,
                "campaign_name": facts["campaign_name"],
                "created_at_utc": created.isoformat() if created is not None else "",
                "completed_at_utc": completed.isoformat() if completed is not None else None,
                "status": status,
                "status_display_text": STATUS_DISPLAY[status],
                "campaign_period": facts["campaign_period"],
                "total_budget_rub": facts["total_budget_rub"],
                "segments": facts["segments"],
                "channels_n": facts["channels_n"],
                "geographies_n": facts["geographies_n"],
                **published,
                "progress_path": f"/calculations/{job_id}/progress",
            }
        )
    return rows


def _history_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = Counter(str(row["status"]) for row in rows)
    return {
        "all": len(rows),
        "active": sum(counts[status] for status in ACTIVE_STATUSES),
        "succeeded": counts["succeeded"],
        "failed": counts["failed"],
        "cancelled": counts["cancelled"],
        "timed_out": counts["timed_out"],
    }


def _sort_history(rows: Sequence[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    def created_value(row: Mapping[str, Any]) -> float:
        value = _timestamp(row["created_at_utc"], "created_at_utc")
        return value.timestamp() if value is not None else 0.0

    if sort == "created_desc":
        return sorted(rows, key=lambda row: (-created_value(row), row["job_id"]))
    if sort == "created_asc":
        return sorted(rows, key=lambda row: (created_value(row), row["job_id"]))
    if sort == "completed_desc":
        def completed_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
            completed = _timestamp(
                row["completed_at_utc"],
                "completed_at_utc",
                nullable=True,
            )
            return (
                0 if completed is not None else 1,
                -(completed.timestamp() if completed is not None else 0.0),
                -created_value(row),
                row["job_id"],
            )

        return sorted(rows, key=completed_key)
    if sort == "campaign_asc":
        return sorted(
            rows,
            key=lambda row: (
                str(row["campaign_name"]).casefold(),
                -created_value(row),
                row["job_id"],
            ),
        )
    raise ProductNavigationQueryError("Unsupported history sort")


def build_calculation_history(
    records: Sequence[Mapping[str, Any]],
    *,
    resource_reader: ResourceReader,
    validation_reader: ValidationReader | None = None,
    page: int = 1,
    page_size: int = 25,
    status: str | None = None,
    search: str | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    sort: str = "created_desc",
    now: datetime | None = None,
    record_origin: str = "application_runtime",
) -> dict[str, Any]:
    """Build one paginated history projection from persisted job state."""

    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise ProductNavigationQueryError("History page is invalid")
    if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 100:
        raise ProductNavigationQueryError("History page size is invalid")
    if status is not None and status not in STATUS_FILTERS:
        raise ProductNavigationQueryError("History status filter is invalid")
    if search is not None and (not search.strip() or len(search.strip()) > 120):
        raise ProductNavigationQueryError("History search is invalid")
    if created_from is not None and created_to is not None and created_to < created_from:
        raise ProductNavigationQueryError("History date range is reversed")
    if sort not in SORT_CODES:
        raise ProductNavigationQueryError("History sort is invalid")

    rows = _history_rows(
        records,
        resource_reader=resource_reader,
        validation_reader=validation_reader,
    )
    summary = _history_summary(rows)
    filtered = rows
    if status == "active":
        filtered = [row for row in filtered if row["status"] in ACTIVE_STATUSES]
    elif status is not None:
        filtered = [row for row in filtered if row["status"] == status]
    normalized_search = search.strip().casefold() if search is not None else None
    if normalized_search:
        filtered = [
            row
            for row in filtered
            if normalized_search
            in " ".join(
                [
                    str(row["job_id"]),
                    str(row["campaign_name"]),
                    " ".join(row["segments"] or []),
                ]
            ).casefold()
        ]
    if created_from is not None:
        filtered = [
            row
            for row in filtered
            if _timestamp(row["created_at_utc"], "created_at_utc").date() >= created_from
        ]
    if created_to is not None:
        filtered = [
            row
            for row in filtered
            if _timestamp(row["created_at_utc"], "created_at_utc").date() <= created_to
        ]
    filtered = _sort_history(filtered, sort)
    total_items = len(filtered)
    start = (page - 1) * page_size
    payload = {
        "contract_name": HISTORY_CONTRACT,
        "schema_version": HISTORY_SCHEMA_VERSION,
        "record_origin": record_origin,
        "summary": summary,
        "filters": {
            "status": status,
            "search": search.strip() if search is not None else None,
            "created_from": created_from.isoformat() if created_from is not None else None,
            "created_to": created_to.isoformat() if created_to is not None else None,
            "sort": sort,
        },
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_items": total_items,
            "total_pages": math.ceil(total_items / page_size) if total_items else 0,
        },
        "items": filtered[start : start + page_size],
        "updated_at_utc": _utc_now(now).isoformat(),
    }
    return validate_calculation_history_payload(payload)


def _model_summary(model_overview: Mapping[str, Any]) -> dict[str, Any]:
    active = model_overview.get("active_model")
    if not isinstance(active, Mapping):
        raise ProductNavigationStateError("Model overview has no active-model state")
    status = active.get("status")
    code = status.get("code") if isinstance(status, Mapping) else None
    if code == "available":
        scope = active.get("supported_scope")
        if not isinstance(scope, Mapping):
            raise ProductNavigationStateError("Available model has no supported scope")
        return {
            "status": {"code": "available", "display_text": "Модель доступна"},
            "model_id": active.get("model_id"),
            "display_name": active.get("display_name"),
            "version": active.get("version"),
            "published_at_utc": active.get("published_at_utc"),
            "training_period": active.get("training_period"),
            "supported_scope": {
                "segments": list(scope.get("segments") or []),
                "channels": list(scope.get("channels") or []),
                "targets": list(scope.get("targets") or []),
                "geographies_n": int(scope.get("geographies_n") or 0),
            },
            "description": str(active.get("description") or "Активная модель доступна для расчетов."),
            "details_path": "/model",
        }
    if code != "unavailable":
        raise ProductNavigationStateError("Model overview status is unsupported")
    return {
        "status": {"code": "unavailable", "display_text": "Сведения о модели недоступны"},
        "model_id": None,
        "display_name": None,
        "version": None,
        "published_at_utc": None,
        "training_period": None,
        "supported_scope": None,
        "description": "Сведения об активной модели временно недоступны.",
        "details_path": "/model",
    }


def build_workspace_home(
    records: Sequence[Mapping[str, Any]],
    *,
    model_overview: Mapping[str, Any],
    resource_reader: ResourceReader,
    progress_view_builder: ProgressViewBuilder,
    validation_reader: ValidationReader | None = None,
    now: datetime | None = None,
    record_origin: str = "application_runtime",
) -> dict[str, Any]:
    """Build the compact workspace snapshot used by the home page."""

    current_time = _utc_now(now)
    rows = _history_rows(
        records,
        resource_reader=resource_reader,
        validation_reader=validation_reader,
    )
    rows = _sort_history(rows, "created_desc")
    active_rows = [row for row in rows if row["status"] in ACTIVE_STATUSES]
    progress_unavailable = False
    active_calculations = []
    for row in active_rows:
        current_stage = None
        try:
            progress = progress_view_builder(str(row["job_id"]))
            stage_id = progress.get("current_stage_id")
            stages = progress.get("stages")
            if not isinstance(stages, list):
                raise ProductNavigationStateError("Progress stages are malformed")
            stage = next(
                (
                    item
                    for item in stages
                    if isinstance(item, Mapping) and item.get("stage_id") == stage_id
                ),
                None,
            )
            if stage is not None:
                current_stage = {
                    "stage_id": str(stage["stage_id"]),
                    "title": str(stage["title"]),
                    "status": str(stage["status"]),
                    "display_text": str(stage["display_text"]),
                }
        except Exception:
            progress_unavailable = True
        status = str(row["status"])
        active_calculations.append(
            {
                "job_id": row["job_id"],
                "campaign_name": row["campaign_name"],
                "status": {"code": status, "display_text": STATUS_DISPLAY[status]},
                "current_stage": current_stage,
                "created_at_utc": row["created_at_utc"],
                "progress_path": row["progress_path"],
                "can_cancel": status in {"queued", "running"},
                "display_text": STATUS_DISPLAY[status],
            }
        )

    recent_rows = [row for row in rows if row["status"] in TERMINAL_STATUSES][:5]
    recent_calculations = [
        {
            "job_id": row["job_id"],
            "campaign_name": row["campaign_name"],
            "campaign_period": row["campaign_period"],
            "total_budget_rub": row["total_budget_rub"],
            "created_at_utc": row["created_at_utc"],
            "completed_at_utc": row["completed_at_utc"],
            "status": {
                "code": row["status"],
                "display_text": row["status_display_text"],
            },
            "result_available": row["result_available"],
            "report_available": row["report_available"],
            "result_path": row["result_path"],
            "progress_path": row["progress_path"],
            "warnings_count": row["warnings_count"],
        }
        for row in recent_rows
    ]

    cutoff = current_time - timedelta(days=30)
    completed_30d = 0
    failed_30d = 0
    for row in rows:
        completed = _timestamp(
            row["completed_at_utc"],
            "completed_at_utc",
            nullable=True,
        )
        if completed is None or completed < cutoff:
            continue
        if row["status"] == "succeeded":
            completed_30d += 1
        elif row["status"] in {"failed", "timed_out"}:
            failed_30d += 1

    warnings: list[dict[str, Any]] = []
    if failed_30d:
        warnings.append(
            {
                "code": "recent_calculation_failures",
                "severity": "warning",
                "title": "Есть незавершенные расчеты",
                "display_text": "За последние 30 дней есть расчеты с ошибкой или остановкой по времени.",
                "recommended_action": "Откройте историю и проверьте статус нужной кампании.",
                "path": "/calculations",
            }
        )
    if any(row["status"] == "succeeded" and not row["report_available"] for row in recent_rows):
        warnings.append(
            {
                "code": "recent_report_unavailable",
                "severity": "info",
                "title": "Для части расчетов нет отчета",
                "display_text": "У одного или нескольких недавних результатов файл отчета недоступен.",
                "recommended_action": "Откройте результат и используйте доступные данные на странице.",
                "path": "/calculations",
            }
        )
    model_summary = _model_summary(model_overview)
    if model_summary["status"]["code"] == "unavailable":
        warnings.append(
            {
                "code": "active_model_unavailable",
                "severity": "error",
                "title": "Сведения о модели недоступны",
                "display_text": "Сейчас нельзя подтвердить параметры активной модели.",
                "recommended_action": "Повторите попытку позже перед запуском нового расчета.",
                "path": "/model",
            }
        )
    if progress_unavailable:
        warnings.append(
            {
                "code": "active_progress_partially_unavailable",
                "severity": "info",
                "title": "Этап расчета уточняется",
                "display_text": "Для одного из активных расчетов пока доступен только общий статус.",
                "recommended_action": "Откройте расчет или обновите страницу позже.",
                "path": "/calculations",
            }
        )

    payload = {
        "contract_name": HOME_CONTRACT,
        "schema_version": HOME_SCHEMA_VERSION,
        "record_origin": record_origin,
        "summary": {
            "running": sum(row["status"] in {"running", "cancel_requested"} for row in active_rows),
            "queued": sum(row["status"] == "queued" for row in active_rows),
            "completed_30d": completed_30d,
            "failed_30d": failed_30d,
        },
        "active_calculations": active_calculations,
        "recent_calculations": recent_calculations,
        "model": model_summary,
        "quick_actions": [
            {
                "action_id": "new_calculation",
                "title": "Новый расчет",
                "description": "Загрузить будущую кампанию и запустить оценку.",
                "path": "/calculations/new",
            },
            {
                "action_id": "calculation_history",
                "title": "История расчетов",
                "description": "Найти ранее запущенную кампанию и ее результат.",
                "path": "/calculations",
            },
            {
                "action_id": "model_overview",
                "title": "О модели",
                "description": "Посмотреть область применения и ограничения модели.",
                "path": "/model",
            },
            {
                "action_id": "help_catalog",
                "title": "Справка",
                "description": "Разобраться в сценариях, метриках и предупреждениях.",
                "path": "/help",
            },
        ],
        "warnings": warnings,
        "updated_at_utc": current_time.isoformat(),
    }
    return validate_workspace_home_payload(payload)


def _registry_versions(
    registry_root: Path | None,
    *,
    active_model_id: str | None,
    registry_channel: str,
) -> tuple[list[dict[str, Any]], str | None]:
    if registry_root is None or not registry_root.is_dir():
        return [], None
    try:
        registrations = list_registrations(registry_root)
        pointer_path = registry_root / "channels" / f"{registry_channel}.json"
        pointer = json.loads(pointer_path.read_text(encoding="utf-8")) if pointer_path.is_file() else None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ProductNavigationUnavailableError("Model registry cannot be read") from exc
    if pointer is not None and not isinstance(pointer, Mapping):
        raise ProductNavigationStateError("Active model pointer is malformed")
    pointer_id = str(pointer.get("package_id") or "") if pointer is not None else None
    published_at = str(pointer.get("updated_at_utc") or "") if pointer is not None else None
    if active_model_id and pointer_id and active_model_id != pointer_id:
        raise ProductNavigationStateError("Active model and registry pointer differ")
    versions: list[dict[str, Any]] = []
    for registration in registrations:
        if not isinstance(registration, Mapping):
            raise ProductNavigationStateError("Model registration is malformed")
        model_id = str(registration.get("package_id") or "")
        model_run_id = str(registration.get("model_run_id") or "")
        package_stage = str(registration.get("package_stage") or "")
        activation_status = str(registration.get("activation_status_at_registration") or "")
        if not all((model_id, model_run_id, package_stage, activation_status)):
            raise ProductNavigationStateError("Model registration is incomplete")
        versions.append(
            {
                "model_id": model_id,
                "model_run_id": model_run_id,
                "registered_at_utc": registration.get("registered_at_utc"),
                "package_stage": package_stage,
                "activation_status": activation_status,
                "status": "active" if model_id == active_model_id else "registered",
                "source": "registry_registration",
            }
        )
    versions.sort(
        key=lambda item: (
            str(item.get("registered_at_utc") or ""),
            str(item["model_id"]),
        ),
        reverse=True,
    )
    return versions, published_at or None


def _capabilities(available: bool) -> list[dict[str, Any]]:
    unavailable = "unavailable" if not available else None
    return [
        {
            "capability_id": "incremental_effect_forecast",
            "title": "Прогноз дополнительного эффекта",
            "status": unavailable or "available",
            "description": "Оценивает эффект будущей кампании относительно варианта без нее.",
        },
        {
            "capability_id": "six_scenarios",
            "title": "Сравнение S1-S6",
            "status": unavailable or "available",
            "description": "Сравнивает исходный план, контрольные распределения и адаптивный поиск.",
        },
        {
            "capability_id": "budget_allocation",
            "title": "Распределение бюджета",
            "status": unavailable or "available",
            "description": "Показывает распределение заданного бюджета по каналам и географиям.",
        },
        {
            "capability_id": "safe_recommendation",
            "title": "Рекомендация с ограничениями надежности",
            "status": unavailable or "conditional",
            "description": "Выбирает вариант распределения с учетом исторической зоны и правил использования каналов.",
        },
        {
            "capability_id": "marketer_report",
            "title": "Отчет для маркетолога",
            "status": unavailable or "available",
            "description": "Формирует Excel с кампанией, сценариями, рекомендацией и предупреждениями.",
        },
    ]


def _data_requirements() -> list[dict[str, Any]]:
    return [
        {
            "requirement_id": "file_format",
            "title": "Формат файла",
            "required": True,
            "description": "Используйте табличный файл с заголовками колонок.",
            "accepted_values": ["CSV", "XLSX"],
        },
        {
            "requirement_id": "one_campaign",
            "title": "Одна кампания",
            "required": True,
            "description": "Один запуск расчета должен содержать одну будущую кампанию.",
            "accepted_values": ["Одна кампания в одном файле"],
        },
        {
            "requirement_id": "campaign_period",
            "title": "Период",
            "required": True,
            "description": "Укажите начало и окончание либо дневную дату для каждой строки.",
            "accepted_values": ["start_date и end_date", "date"],
        },
        {
            "requirement_id": "budget",
            "title": "Бюджет",
            "required": True,
            "description": "Для каждой строки должна быть указана неотрицательная сумма в рублях.",
            "accepted_values": ["Бюджет в рублях"],
        },
        {
            "requirement_id": "allocation_dimensions",
            "title": "Структура медиаплана",
            "required": True,
            "description": "Укажите сегмент, канал и географию для каждой части бюджета.",
            "accepted_values": ["Сегмент", "Канал", "География"],
        },
        {
            "requirement_id": "target_metric",
            "title": "Целевой показатель",
            "required": True,
            "description": "Выберите показатель, который поддерживается активной моделью.",
            "accepted_values": ["Поддерживаемый целевой показатель"],
        },
    ]


def _methodology() -> list[dict[str, str]]:
    return [
        {
            "method_id": "carryover",
            "title": "Перенос эффекта во времени",
            "summary": "Часть отклика рекламы может проявляться после дня размещения и учитывается последовательно по географиям.",
        },
        {
            "method_id": "saturation",
            "title": "Насыщение",
            "summary": "Рост расходов не обязан давать пропорциональный рост эффекта; отдача может замедляться.",
        },
        {
            "method_id": "uncertainty",
            "title": "Неопределенность",
            "summary": "Результат публикуется диапазоном P10, P50 и P90, а не одной гарантированной цифрой.",
        },
        {
            "method_id": "counterfactual_forecast",
            "title": "Сравнение с вариантом без кампании",
            "summary": "Прогноз показывает дополнительный медиавклад, а не полный будущий оборот бизнеса.",
        },
        {
            "method_id": "scenario_search",
            "title": "Поиск распределения",
            "summary": "S6 перебирает варианты и оценивает финалистов тем же posterior-движком, что и прогноз.",
        },
        {
            "method_id": "reliability_guardrails",
            "title": "Ограничения надежности",
            "summary": "Историческая поддержка и правила каналов ограничивают автоматический перелив бюджета.",
        },
    ]


def build_model_overview(
    model_passport: Mapping[str, Any] | None,
    *,
    registry_root: Path | None,
    registry_channel: str,
    now: datetime | None = None,
    record_origin: str = "application_runtime",
) -> dict[str, Any]:
    """Build a browser-safe model explanation from verified model facts."""

    current_time = _utc_now(now)
    available = model_passport is not None
    active_model_id: str | None = None
    if model_passport is not None:
        validate_model_passport(model_passport)
        package = model_passport["package"]
        serving = model_passport["serving"]
        data = model_passport["data"]
        coverage = model_passport["coverage"]
        active_model_id = str(package["package_id"])
    versions, published_at = _registry_versions(
        registry_root,
        active_model_id=active_model_id,
        registry_channel=registry_channel,
    )
    if available and active_model_id not in {item["model_id"] for item in versions}:
        versions.insert(
            0,
            {
                "model_id": active_model_id,
                "model_run_id": str(package["model_run_id"]),
                "registered_at_utc": None,
                "package_stage": str(package["package_stage"]),
                "activation_status": str(package["activation_status"]),
                "status": "active",
                "source": "active_model_passport",
            },
        )
    if not available:
        versions = [{**item, "status": "registered"} for item in versions]

    if available:
        target_names = sorted(
            {
                str(item.get("target") or "")
                for item in coverage["targets"]
                if isinstance(item, Mapping) and str(item.get("target") or "")
            }
        )
        active_model = {
            "status": {"code": "available", "display_text": "Модель доступна"},
            "model_id": active_model_id,
            "display_name": str(serving["display_name"]),
            "version": str(package["model_run_id"]),
            "published_at_utc": published_at,
            "framework": "Bayesian MMM на PyMC",
            "purpose": "Прогноз дополнительного медиаэффекта и сравнение распределений заданного бюджета.",
            "training_period": dict(data["training_period"]),
            "supported_scope": {
                "segments": sorted(str(value) for value in coverage["segments"]),
                "channels": sorted(str(value) for value in coverage["channels"]),
                "targets": target_names,
                "geographies_n": int(coverage["geographies_n"]),
                "capability_cells_n": int(coverage["capability_cells_n"]),
                "allowed_use_counts": {
                    key: int(coverage["allowed_use_counts"].get(key, 0))
                    for key in ("primary", "caution", "diagnostic", "unavailable")
                },
            },
            "description": "Активная исследовательская модель проверяет кампанию в пределах поддерживаемых сегментов, каналов, географий и целевых показателей.",
        }
    else:
        active_model = {
            "status": {"code": "unavailable", "display_text": "Сведения о модели недоступны"},
            "model_id": None,
            "display_name": None,
            "version": None,
            "published_at_utc": None,
            "framework": None,
            "purpose": "Прогноз дополнительного медиаэффекта и сравнение распределений заданного бюджета.",
            "training_period": None,
            "supported_scope": None,
            "description": "Сведения об активной модели временно недоступны.",
        }

    limitations: list[dict[str, str]] = [
        {
            "code": "reliability_score_unavailable",
            "status": "unavailable",
            "title": "Нет единого балла надежности",
            "display_text": "Надежность объясняется диапазоном неопределенности, historical support и предупреждениями, а не вымышленным числом.",
            "recommended_action": "Читайте P10-P90 и предупреждения по выбранному сценарию.",
        },
        {
            "code": "daily_scenario_plans_unavailable",
            "status": "unavailable",
            "title": "Дневные планы сценариев недоступны",
            "display_text": "Отдельная дневная раскладка каждого рассчитанного сценария пока не публикуется.",
            "recommended_action": "Используйте доступное распределение по каналам и географиям.",
        },
        {
            "code": "map_unavailable",
            "status": "unavailable",
            "title": "Карта географий недоступна",
            "display_text": "Распределение доступно в таблице без картографического представления.",
            "recommended_action": "Используйте фильтр географии в медиаплане.",
        },
        {
            "code": "working_media_plan_xlsx_unavailable",
            "status": "unavailable",
            "title": "Нет отдельного рабочего медиаплана",
            "display_text": "Редактируемый Excel только с рабочей раскладкой бюджета пока не публикуется отдельно.",
            "recommended_action": "Используйте отчет для маркетолога и таблицу медиаплана на странице результата.",
        },
        {
            "code": "allocation_only",
            "status": "active",
            "title": "Рекомендация только по распределению",
            "display_text": "Система не принимает бизнес-решение о запуске или отмене кампании.",
            "recommended_action": "Сопоставьте прогноз с бизнес-целями и ограничениями кампании.",
        },
        {
            "code": "orders_diagnostic_only",
            "status": "active",
            "title": "Заказы остаются диагностикой",
            "display_text": "Количество заказов не используется как основной показатель автоматической оптимизации.",
            "recommended_action": "Основной вывод делайте по incremental turnover, ROAS и надежности.",
        },
    ]
    if available and model_passport["validation"]["sealed_oot"]["status"] != "passed":
        limitations.append(
            {
                "code": "sealed_oot_unavailable",
                "status": "active",
                "title": "Независимая проверка на новом периоде не завершена",
                "display_text": "Полный новый период данных для sealed OOT пока недоступен; расчеты остаются исследовательскими.",
                "recommended_action": "Не трактуйте текущий результат как production-гарантию качества.",
            }
        )

    payload = {
        "contract_name": MODEL_CONTRACT,
        "schema_version": MODEL_SCHEMA_VERSION,
        "record_origin": record_origin,
        "active_model": active_model,
        "capabilities": _capabilities(
            available and bool(model_passport["serving"]["calculation_allowed"])
        ),
        "data_requirements": _data_requirements(),
        "methodology": _methodology(),
        "limitations": limitations,
        "versions": versions,
        "artifacts": [],
        "updated_at_utc": current_time.isoformat(),
    }
    return validate_model_overview_payload(payload)


def load_help_catalog(path: Path | None = None) -> dict[str, Any]:
    """Read and validate the versioned structured help source."""

    source = path or DEFAULT_HELP_CATALOG
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductNavigationUnavailableError("Help catalog cannot be read") from exc
    if not isinstance(payload, Mapping):
        raise ProductNavigationStateError("Help catalog is malformed")
    try:
        return validate_help_catalog_payload(payload)
    except ValueError as exc:
        raise ProductNavigationStateError("Help catalog is inconsistent") from exc
