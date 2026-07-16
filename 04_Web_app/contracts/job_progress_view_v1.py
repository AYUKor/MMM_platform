"""Browser-safe product progress contract for one calculation job.

The contract is an additive projection over application lifecycle records. It
contains no calculation logic and deliberately omits internal worker phases,
local paths, model internals and intermediate business results.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any


CONTRACT_NAME = "job_progress_view_v1"
SCHEMA_VERSION = "1.0.0"
RECORD_ORIGINS = {"application_runtime", "synthetic_fixture"}

STAGE_CATALOG: tuple[tuple[str, int, str], ...] = (
    ("P01", 1, "Расчет ожидает запуска"),
    ("P02", 2, "Подготавливаем медиаплан"),
    ("P03", 3, "Рассчитываем исходный медиаплан"),
    ("P04", 4, "Рассчитываем контрольные сценарии"),
    ("P05", 5, "Ищем устойчивый вариант"),
    ("P06", 6, "Перебираем варианты распределения"),
    ("P07", 7, "Проверяем результаты"),
    ("P08", 8, "Формируем отчет"),
    ("P09", 9, "Расчет завершен"),
)
STAGE_IDS = tuple(item[0] for item in STAGE_CATALOG)
STAGE_STATUSES = {"pending", "active", "completed", "warning", "failed", "skipped"}
JOB_STATUS_CODES = {
    "queued",
    "running",
    "cancel_requested",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
}
SCENARIO6_STATUSES = {"pending", "running", "completed", "unavailable", "failed"}
REPORT_STATUSES = {"pending", "running", "completed", "failed", "not_required"}
ERROR_SEVERITIES = {"warning", "error"}

_OPAQUE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*_[0-9a-f]{12,64}$")
_ABSOLUTE_PATH_RE = re.compile(r"^(?:/|[A-Za-z]:[\\/]|file://)", re.IGNORECASE)


class JobProgressViewContractError(ValueError):
    """Raised when the product progress snapshot is inconsistent."""


def _json_compatible(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_compatible(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compatible(nested) for nested in value]
    return value


def _required_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise JobProgressViewContractError(f"{field_name} is required")


def _opaque_id(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not _OPAQUE_ID_RE.fullmatch(value):
        raise JobProgressViewContractError(f"{field_name} must be an opaque ID")


def _non_negative_int(value: int | None, field_name: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise JobProgressViewContractError(f"{field_name} must be a non-negative integer")


def _positive_int(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise JobProgressViewContractError(f"{field_name} must be a positive integer")


def _timestamp(
    value: str | None,
    field_name: str,
    *,
    nullable: bool = False,
) -> datetime | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise JobProgressViewContractError(f"{field_name} must be an ISO-8601 datetime")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise JobProgressViewContractError(
            f"{field_name} must be an ISO-8601 datetime"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise JobProgressViewContractError(f"{field_name} must include a timezone")
    return parsed


def _iso_date(value: str, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise JobProgressViewContractError(f"{field_name} must be an ISO date") from exc


def _reject_paths(value: Any, field_name: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            _reject_paths(nested, f"{field_name}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _reject_paths(nested, f"{field_name}[{index}]")
        return
    if isinstance(value, str) and _ABSOLUTE_PATH_RE.match(value):
        raise JobProgressViewContractError(
            f"Absolute workstation path is forbidden at {field_name}"
        )


@dataclass(frozen=True)
class ProgressStatus:
    code: str
    display_text: str

    def validate(self, field_name: str) -> None:
        if self.code not in JOB_STATUS_CODES:
            raise JobProgressViewContractError(f"Unknown {field_name}.code: {self.code}")
        _required_text(self.display_text, f"{field_name}.display_text")


@dataclass(frozen=True)
class QueueSummary:
    position: int | None
    queued_jobs_total: int | None
    display_text: str

    def validate(self, field_name: str, job_status: str) -> None:
        _non_negative_int(self.position, f"{field_name}.position")
        _non_negative_int(self.queued_jobs_total, f"{field_name}.queued_jobs_total")
        _required_text(self.display_text, f"{field_name}.display_text")
        if job_status == "queued":
            if self.position is not None and self.position < 1:
                raise JobProgressViewContractError(f"{field_name}.position is invalid")
            if self.position is not None and (
                self.queued_jobs_total is None
                or self.position > self.queued_jobs_total
            ):
                raise JobProgressViewContractError(
                    f"{field_name} queued totals are inconsistent"
                )
        elif self.position is not None:
            raise JobProgressViewContractError(
                f"{field_name}.position is only allowed for a queued job"
            )


@dataclass(frozen=True)
class CampaignProgressSummary:
    campaign_id: str
    campaign_name: str
    segment: tuple[str, ...]
    start_date: str
    end_date: str
    total_budget_rub: float
    channels_n: int
    geographies_n: int

    def validate(self, field_name: str) -> None:
        _opaque_id(self.campaign_id, f"{field_name}.campaign_id")
        _required_text(self.campaign_name, f"{field_name}.campaign_name")
        if not self.segment or len(set(self.segment)) != len(self.segment):
            raise JobProgressViewContractError(
                f"{field_name}.segment must contain unique values"
            )
        for value in self.segment:
            _required_text(value, f"{field_name}.segment")
        start = _iso_date(self.start_date, f"{field_name}.start_date")
        end = _iso_date(self.end_date, f"{field_name}.end_date")
        if end < start:
            raise JobProgressViewContractError(f"{field_name} period is reversed")
        if isinstance(self.total_budget_rub, bool) or not isinstance(
            self.total_budget_rub, (int, float)
        ) or self.total_budget_rub < 0:
            raise JobProgressViewContractError(
                f"{field_name}.total_budget_rub must be non-negative"
            )
        _positive_int(self.channels_n, f"{field_name}.channels_n")
        _positive_int(self.geographies_n, f"{field_name}.geographies_n")


@dataclass(frozen=True)
class StageProgress:
    current: int
    total: int | None
    unit: str

    def validate(self, field_name: str) -> None:
        _non_negative_int(self.current, f"{field_name}.current")
        _non_negative_int(self.total, f"{field_name}.total")
        if self.total is not None and self.current > self.total:
            raise JobProgressViewContractError(
                f"{field_name}.current must not exceed total"
            )
        _required_text(self.unit, f"{field_name}.unit")


@dataclass(frozen=True)
class ProductStage:
    stage_id: str
    order: int
    title: str
    status: str
    started_at_utc: str | None
    finished_at_utc: str | None
    display_text: str
    progress: StageProgress | None = None

    def validate(self, field_name: str) -> None:
        if self.status not in STAGE_STATUSES:
            raise JobProgressViewContractError(f"Unknown {field_name}.status: {self.status}")
        expected = next(
            (item for item in STAGE_CATALOG if item[0] == self.stage_id),
            None,
        )
        if expected is None or (self.order, self.title) != (expected[1], expected[2]):
            raise JobProgressViewContractError(f"{field_name} does not match stage catalog")
        started = _timestamp(
            self.started_at_utc,
            f"{field_name}.started_at_utc",
            nullable=True,
        )
        finished = _timestamp(
            self.finished_at_utc,
            f"{field_name}.finished_at_utc",
            nullable=True,
        )
        if finished is not None and started is None:
            raise JobProgressViewContractError(
                f"{field_name}.finished_at_utc requires started_at_utc"
            )
        if started is not None and finished is not None and finished < started:
            raise JobProgressViewContractError(f"{field_name} timestamps are reversed")
        if self.status == "pending" and (started is not None or finished is not None):
            raise JobProgressViewContractError(f"{field_name} pending stage has timestamps")
        if self.status == "active" and (started is None or finished is not None):
            raise JobProgressViewContractError(
                f"{field_name} active stage requires only started_at_utc"
            )
        if self.status in {"completed", "failed"} and (
            started is None or finished is None
        ):
            raise JobProgressViewContractError(
                f"{field_name} {self.status} stage requires both timestamps"
            )
        _required_text(self.display_text, f"{field_name}.display_text")
        if self.progress is not None:
            self.progress.validate(f"{field_name}.progress")


@dataclass(frozen=True)
class Scenario6Progress:
    status: str
    attempt_budget: int | None
    attempts_checked: int | None
    safe_candidates: int | None
    blocked_candidates: int | None
    finalists_scored: int | None
    finalists_total: int | None

    def validate(self, field_name: str) -> None:
        if self.status not in SCENARIO6_STATUSES:
            raise JobProgressViewContractError(f"Unknown {field_name}.status: {self.status}")
        for name in (
            "attempt_budget",
            "attempts_checked",
            "safe_candidates",
            "blocked_candidates",
            "finalists_scored",
            "finalists_total",
        ):
            _non_negative_int(getattr(self, name), f"{field_name}.{name}")
        if (
            self.attempts_checked is not None
            and self.attempt_budget is not None
            and self.attempts_checked > self.attempt_budget
        ):
            raise JobProgressViewContractError(
                f"{field_name}.attempts_checked must not exceed attempt_budget"
            )
        if (
            self.finalists_scored is not None
            and self.finalists_total is not None
            and self.finalists_scored > self.finalists_total
        ):
            raise JobProgressViewContractError(
                f"{field_name}.finalists_scored must not exceed finalists_total"
            )


@dataclass(frozen=True)
class ReportProgress:
    status: str
    display_text: str
    retryable: bool

    def validate(self, field_name: str) -> None:
        if self.status not in REPORT_STATUSES:
            raise JobProgressViewContractError(f"Unknown {field_name}.status: {self.status}")
        _required_text(self.display_text, f"{field_name}.display_text")
        if not isinstance(self.retryable, bool):
            raise JobProgressViewContractError(f"{field_name}.retryable must be boolean")


@dataclass(frozen=True)
class ProgressViewError:
    error_id: str
    stage_id: str
    severity: str
    blocking: bool
    retryable: bool
    display_text: str
    recommended_action: str

    def validate(self, field_name: str) -> None:
        _opaque_id(self.error_id, f"{field_name}.error_id")
        if self.stage_id not in STAGE_IDS:
            raise JobProgressViewContractError(f"Unknown {field_name}.stage_id")
        if self.severity not in ERROR_SEVERITIES:
            raise JobProgressViewContractError(f"Unknown {field_name}.severity")
        if not isinstance(self.blocking, bool) or not isinstance(self.retryable, bool):
            raise JobProgressViewContractError(
                f"{field_name}.blocking and retryable must be boolean"
            )
        _required_text(self.display_text, f"{field_name}.display_text")
        _required_text(self.recommended_action, f"{field_name}.recommended_action")


@dataclass(frozen=True)
class JobProgressViewV1:
    contract_name: str
    schema_version: str
    record_origin: str
    job_id: str
    job_status: ProgressStatus
    queue: QueueSummary
    campaign: CampaignProgressSummary
    current_stage_id: str
    stages: tuple[ProductStage, ...]
    scenario6: Scenario6Progress
    report: ReportProgress
    errors: tuple[ProgressViewError, ...]
    can_cancel: bool
    result_available: bool
    updated_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        return _json_compatible(asdict(self))

    def validate(self) -> None:
        if self.contract_name != CONTRACT_NAME or self.schema_version != SCHEMA_VERSION:
            raise JobProgressViewContractError("Unsupported job progress view contract")
        if self.record_origin not in RECORD_ORIGINS:
            raise JobProgressViewContractError("Unknown record_origin")
        _opaque_id(self.job_id, "job_id")
        self.job_status.validate("job_status")
        self.queue.validate("queue", self.job_status.code)
        self.campaign.validate("campaign")
        if self.current_stage_id not in STAGE_IDS:
            raise JobProgressViewContractError("current_stage_id is not in the stage catalog")
        if tuple(stage.stage_id for stage in self.stages) != STAGE_IDS:
            raise JobProgressViewContractError("stages must contain the fixed nine-stage catalog")
        for index, stage in enumerate(self.stages):
            stage.validate(f"stages[{index}]")
        if self.job_status.code in {"succeeded", "failed", "cancelled", "timed_out"} and any(
            stage.status == "active" for stage in self.stages
        ):
            raise JobProgressViewContractError("terminal job must not contain active stages")
        expected_can_cancel = self.job_status.code in {"queued", "running"}
        if self.can_cancel is not expected_can_cancel:
            raise JobProgressViewContractError("can_cancel is inconsistent with job status")
        if self.result_available and self.job_status.code != "succeeded":
            raise JobProgressViewContractError(
                "result_available requires succeeded job status"
            )
        if self.job_status.code == "succeeded":
            if not self.result_available:
                raise JobProgressViewContractError(
                    "succeeded job requires an available result"
                )
            if self.stages[-1].status != "completed":
                raise JobProgressViewContractError("succeeded job requires completed P09")
            if self.report.status != "completed":
                raise JobProgressViewContractError(
                    "succeeded job requires a completed report"
                )
        self.scenario6.validate("scenario6")
        self.report.validate("report")
        for index, error in enumerate(self.errors):
            error.validate(f"errors[{index}]")
        updated = _timestamp(self.updated_at_utc, "updated_at_utc")
        starts = [
            _timestamp(stage.started_at_utc, "stage.started_at_utc", nullable=True)
            for stage in self.stages
        ]
        non_null_starts = [value for value in starts if value is not None]
        if non_null_starts != sorted(non_null_starts):
            raise JobProgressViewContractError("stage starts must be chronological")
        for stage in self.stages:
            for value in (stage.started_at_utc, stage.finished_at_utc):
                parsed = _timestamp(value, "stage timestamp", nullable=True)
                if parsed is not None and updated is not None and parsed > updated:
                    raise JobProgressViewContractError(
                        "updated_at_utc must not precede stage timestamps"
                    )
        _reject_paths(self.to_dict())


def job_progress_view_from_dict(payload: Mapping[str, Any]) -> JobProgressViewV1:
    """Parse and semantically validate a wire payload."""

    data = dict(payload)
    data["job_status"] = ProgressStatus(**dict(data["job_status"]))
    data["queue"] = QueueSummary(**dict(data["queue"]))
    campaign = dict(data["campaign"])
    campaign["segment"] = tuple(campaign.get("segment") or ())
    data["campaign"] = CampaignProgressSummary(**campaign)
    stages: list[ProductStage] = []
    for raw_stage in data.get("stages") or ():
        stage = dict(raw_stage)
        if stage.get("progress") is not None:
            stage["progress"] = StageProgress(**dict(stage["progress"]))
        stages.append(ProductStage(**stage))
    data["stages"] = tuple(stages)
    data["scenario6"] = Scenario6Progress(**dict(data["scenario6"]))
    data["report"] = ReportProgress(**dict(data["report"]))
    data["errors"] = tuple(
        ProgressViewError(**dict(item)) for item in data.get("errors") or ()
    )
    record = JobProgressViewV1(**data)
    record.validate()
    return record


def validate_job_progress_view_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    return job_progress_view_from_dict(payload).to_dict()
