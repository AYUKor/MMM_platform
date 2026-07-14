"""Versioned application lifecycle contracts for the MMM web application.

These contracts describe uploads, validation, immutable calculation jobs,
lifecycle transitions, progress events, and safe application errors. They do
not execute campaign preparation, forecast, optimization, or report code.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import PurePosixPath
from typing import Any


SCHEMA_VERSION = "1.0.0"
RECORD_ORIGINS = {"application_runtime", "synthetic_fixture"}

CAMPAIGN_UPLOAD_CONTRACT = "campaign_upload_v1"
VALIDATION_RESULT_CONTRACT = "validation_result_v1"
DECISION_JOB_CONTRACT = "decision_job_v1"
JOB_EVENT_CONTRACT = "job_event_v1"
PROGRESS_EVENT_CONTRACT = "progress_event_v1"
APPLICATION_ERROR_CONTRACT = "application_error_v1"

UPLOAD_STATUS_CODES = {"received", "parsed", "rejected"}
VALIDATION_STATUS_CODES = {"running", "valid", "invalid"}
JOB_STATUS_CODES = {
    "queued",
    "running",
    "cancel_requested",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
}
PROGRESS_STAGES = {
    "prepare",
    "forecast",
    "benchmarks",
    "scenario6",
    "final_scoring",
    "report",
}
PROGRESS_STATES = {"started", "running", "completed"}
ACTOR_TYPES = {"system", "user", "worker", "admin"}
VALIDATION_SEVERITIES = {"blocking", "warning"}
VALIDATION_SCOPES = {"upload", "row", "campaign", "cell", "model"}
ERROR_RESOURCE_TYPES = {"upload", "validation", "job"}
ERROR_COMPONENTS = {
    "upload",
    "validation",
    "worker",
    "forecast",
    "optimizer",
    "report",
    "result_adapter",
    "storage",
    "api",
}
ERROR_CATEGORIES = {
    "input_validation",
    "model_policy",
    "calculation",
    "artifact_integrity",
    "infrastructure",
    "timeout",
    "cancellation",
    "internal",
}
ERROR_SEVERITIES = {"error", "fatal"}

_OPAQUE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*_[0-9a-f]{12,64}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{1,127}$")
_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")
_ABSOLUTE_PATH_RE = re.compile(r"^(?:/|[A-Za-z]:[\\/]|file://)", re.IGNORECASE)


class LifecycleContractValidationError(ValueError):
    """Raised when an application lifecycle record violates the v1 contract."""


class _ContractMixin:
    def to_dict(self) -> dict[str, Any]:
        return _json_compatible(asdict(self))

    def _validate_header(self, expected_contract: str) -> None:
        contract_name = str(getattr(self, "contract_name", ""))
        schema_version = str(getattr(self, "schema_version", ""))
        record_origin = str(getattr(self, "record_origin", ""))
        if contract_name != expected_contract or schema_version != SCHEMA_VERSION:
            raise LifecycleContractValidationError(
                f"Unsupported {expected_contract} contract version"
            )
        if record_origin not in RECORD_ORIGINS:
            raise LifecycleContractValidationError(
                f"Unknown record_origin: {record_origin}"
            )

    def _reject_paths(self) -> None:
        _reject_absolute_paths(self.to_dict())


def _json_compatible(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_compatible(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compatible(nested) for nested in value]
    return value


def _required_text(value: str, field_name: str) -> None:
    if not str(value).strip():
        raise LifecycleContractValidationError(f"{field_name} is required")


def _opaque_id(value: str | None, field_name: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if value is None or not _OPAQUE_ID_RE.fullmatch(value):
        raise LifecycleContractValidationError(f"{field_name} must be an opaque ID")


def _sha256(value: str, field_name: str) -> None:
    if not _SHA256_RE.fullmatch(value):
        raise LifecycleContractValidationError(f"{field_name} must be a SHA-256")


def _code(value: str | None, field_name: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if value is None or not _CODE_RE.fullmatch(value):
        raise LifecycleContractValidationError(f"{field_name} must be a stable code")


def _finite(value: float | int | None, field_name: str) -> None:
    if value is not None and not math.isfinite(float(value)):
        raise LifecycleContractValidationError(f"{field_name} must be finite")


def _non_negative(value: float | int | None, field_name: str) -> None:
    _finite(value, field_name)
    if value is not None and float(value) < 0:
        raise LifecycleContractValidationError(f"{field_name} must be non-negative")


def _positive_int(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise LifecycleContractValidationError(f"{field_name} must be a positive integer")


def _non_negative_int(value: int | None, field_name: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LifecycleContractValidationError(
            f"{field_name} must be a non-negative integer"
        )


def _boolean(value: bool, field_name: str) -> None:
    if not isinstance(value, bool):
        raise LifecycleContractValidationError(f"{field_name} must be a boolean")


def _fraction(value: float | None, field_name: str) -> None:
    _finite(value, field_name)
    if value is not None and not 0.0 <= float(value) <= 1.0:
        raise LifecycleContractValidationError(f"{field_name} must be between 0 and 1")


def _percentage(value: float | None, field_name: str) -> None:
    _finite(value, field_name)
    if value is not None and not 0.0 <= float(value) <= 100.0:
        raise LifecycleContractValidationError(
            f"{field_name} must be between 0 and 100"
        )


def _timestamp(value: str | None, field_name: str, *, nullable: bool = False) -> datetime | None:
    if value is None and nullable:
        return None
    if value is None:
        raise LifecycleContractValidationError(f"{field_name} is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LifecycleContractValidationError(
            f"{field_name} must be an ISO-8601 datetime"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LifecycleContractValidationError(f"{field_name} must include a timezone")
    return parsed


def _date(value: str, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise LifecycleContractValidationError(
            f"{field_name} must be an ISO-8601 date"
        ) from exc


def _reject_absolute_paths(value: Any, field_name: str = "root") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            _reject_absolute_paths(nested, f"{field_name}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _reject_absolute_paths(nested, f"{field_name}[{index}]")
        return
    if isinstance(value, str) and _ABSOLUTE_PATH_RE.match(value):
        raise LifecycleContractValidationError(
            f"Absolute workstation path is forbidden at {field_name}"
        )


def _unique(values: tuple[Any, ...], field_name: str) -> None:
    if len(values) != len(set(values)):
        raise LifecycleContractValidationError(f"{field_name} must be unique")


@dataclass(frozen=True)
class LifecycleStatus:
    code: str
    display_text: str

    def validate(self, allowed: set[str], field_name: str) -> None:
        if self.code not in allowed:
            raise LifecycleContractValidationError(
                f"Unknown {field_name}.code: {self.code}"
            )
        _required_text(self.display_text, f"{field_name}.display_text")


@dataclass(frozen=True)
class ArtifactIdentity:
    artifact_id: str
    kind: str
    display_name: str
    media_type: str
    sha256: str
    size_bytes: int
    storage_key: str

    def validate(self, field_name: str, expected_kind: str | None = None) -> None:
        _opaque_id(self.artifact_id, f"{field_name}.artifact_id")
        _code(self.kind, f"{field_name}.kind")
        if expected_kind is not None and self.kind != expected_kind:
            raise LifecycleContractValidationError(
                f"{field_name}.kind must be {expected_kind}"
            )
        _required_text(self.display_name, f"{field_name}.display_name")
        if (
            self.display_name in {".", ".."}
            or "/" in self.display_name
            or "\\" in self.display_name
        ):
            raise LifecycleContractValidationError(
                f"{field_name}.display_name must be a filename without a path"
            )
        _required_text(self.media_type, f"{field_name}.media_type")
        _sha256(self.sha256, f"{field_name}.sha256")
        _non_negative_int(self.size_bytes, f"{field_name}.size_bytes")
        path = PurePosixPath(self.storage_key)
        raw_parts = self.storage_key.split("/")
        if (
            path.is_absolute()
            or any(part in {".", ".."} for part in raw_parts)
            or "\\" in self.storage_key
            or "://" in self.storage_key
            or not self.storage_key.strip()
        ):
            raise LifecycleContractValidationError(
                f"{field_name}.storage_key must be a safe relative key"
            )


@dataclass(frozen=True)
class AffectedCell:
    campaign_id: str | None
    segment: str
    geo: str
    channel: str
    target: str

    def validate(self, field_name: str) -> None:
        _opaque_id(self.campaign_id, f"{field_name}.campaign_id", nullable=True)
        for name in ("segment", "geo", "channel", "target"):
            _required_text(getattr(self, name), f"{field_name}.{name}")


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: str
    display_text: str
    scope: str
    recoverable: bool
    source_row_ids: tuple[int, ...] = field(default_factory=tuple)
    affected_cells: tuple[AffectedCell, ...] = field(default_factory=tuple)

    def validate(self, field_name: str) -> None:
        _code(self.code, f"{field_name}.code")
        if self.severity not in VALIDATION_SEVERITIES:
            raise LifecycleContractValidationError(
                f"Unknown {field_name}.severity: {self.severity}"
            )
        if self.scope not in VALIDATION_SCOPES:
            raise LifecycleContractValidationError(
                f"Unknown {field_name}.scope: {self.scope}"
            )
        _required_text(self.display_text, f"{field_name}.display_text")
        _boolean(self.recoverable, f"{field_name}.recoverable")
        for row_id in self.source_row_ids:
            _positive_int(row_id, f"{field_name}.source_row_ids")
        _unique(self.source_row_ids, f"{field_name}.source_row_ids")
        if self.scope == "row" and not self.source_row_ids:
            raise LifecycleContractValidationError(
                f"{field_name}.source_row_ids are required for row scope"
            )
        for index, cell in enumerate(self.affected_cells):
            cell.validate(f"{field_name}.affected_cells[{index}]")


@dataclass(frozen=True)
class CampaignPreview:
    campaign_id: str
    campaign_name: str
    segments: tuple[str, ...]
    start_date: str
    end_date: str
    active_days: int
    channels: tuple[str, ...]
    geographies: tuple[str, ...]
    creatives: tuple[str, ...]
    source_rows_n: int
    normalized_rows_n: int
    daily_rows_n: int
    uploaded_budget_rub: float
    model_input_budget_rub: float
    unmodeled_budget_rub: float
    daily_budget_rub: float

    def validate(self, field_name: str) -> None:
        _opaque_id(self.campaign_id, f"{field_name}.campaign_id")
        _required_text(self.campaign_name, f"{field_name}.campaign_name")
        if not self.segments or not self.channels or not self.geographies:
            raise LifecycleContractValidationError(
                f"{field_name} requires segments, channels and geographies"
            )
        for name in ("segments", "channels", "geographies", "creatives"):
            values = getattr(self, name)
            _unique(values, f"{field_name}.{name}")
            for value in values:
                _required_text(value, f"{field_name}.{name}")
        start = _date(self.start_date, f"{field_name}.start_date")
        end = _date(self.end_date, f"{field_name}.end_date")
        if end < start:
            raise LifecycleContractValidationError(
                f"{field_name}.end_date must not precede start_date"
            )
        _positive_int(self.active_days, f"{field_name}.active_days")
        for name in ("source_rows_n", "normalized_rows_n", "daily_rows_n"):
            _non_negative_int(getattr(self, name), f"{field_name}.{name}")
        for name in (
            "uploaded_budget_rub",
            "model_input_budget_rub",
            "unmodeled_budget_rub",
            "daily_budget_rub",
        ):
            _non_negative(getattr(self, name), f"{field_name}.{name}")
        tolerance = max(1.0, abs(self.uploaded_budget_rub) * 1e-8)
        if abs(
            self.uploaded_budget_rub
            - self.model_input_budget_rub
            - self.unmodeled_budget_rub
        ) > tolerance:
            raise LifecycleContractValidationError(
                f"{field_name} uploaded budget does not reconcile"
            )
        if abs(self.model_input_budget_rub - self.daily_budget_rub) > tolerance:
            raise LifecycleContractValidationError(
                f"{field_name} daily budget does not reconcile"
            )


@dataclass(frozen=True)
class ValidationTotals:
    source_rows_n: int
    normalized_rows_n: int
    daily_rows_n: int
    uploaded_budget_rub: float
    model_input_budget_rub: float
    unmodeled_budget_rub: float
    daily_budget_rub: float
    raw_to_normalized_abs_diff_rub: float
    normalized_to_daily_abs_diff_rub: float

    def validate(self, field_name: str) -> None:
        for name in ("source_rows_n", "normalized_rows_n", "daily_rows_n"):
            _non_negative_int(getattr(self, name), f"{field_name}.{name}")
        for name in (
            "uploaded_budget_rub",
            "model_input_budget_rub",
            "unmodeled_budget_rub",
            "daily_budget_rub",
            "raw_to_normalized_abs_diff_rub",
            "normalized_to_daily_abs_diff_rub",
        ):
            _non_negative(getattr(self, name), f"{field_name}.{name}")
        tolerance = max(1.0, abs(self.uploaded_budget_rub) * 1e-8)
        expected_raw_diff = abs(
            self.uploaded_budget_rub
            - self.model_input_budget_rub
            - self.unmodeled_budget_rub
        )
        expected_daily_diff = abs(
            self.model_input_budget_rub - self.daily_budget_rub
        )
        if abs(self.raw_to_normalized_abs_diff_rub - expected_raw_diff) > tolerance:
            raise LifecycleContractValidationError(
                f"{field_name}.raw_to_normalized_abs_diff_rub is inconsistent"
            )
        if abs(self.normalized_to_daily_abs_diff_rub - expected_daily_diff) > tolerance:
            raise LifecycleContractValidationError(
                f"{field_name}.normalized_to_daily_abs_diff_rub is inconsistent"
            )


@dataclass(frozen=True)
class ResolvedModelReference:
    registry_channel: str
    registry_event_id: str
    package_id: str
    package_fingerprint: str
    package_manifest_sha256: str
    activation_status: str
    production_blockers: tuple[str, ...] = field(default_factory=tuple)

    def validate(self, field_name: str) -> None:
        for name in (
            "registry_channel",
            "registry_event_id",
            "package_id",
            "activation_status",
        ):
            _required_text(getattr(self, name), f"{field_name}.{name}")
        _sha256(self.package_fingerprint, f"{field_name}.package_fingerprint")
        _sha256(
            self.package_manifest_sha256,
            f"{field_name}.package_manifest_sha256",
        )
        _unique(self.production_blockers, f"{field_name}.production_blockers")
        for blocker in self.production_blockers:
            _code(blocker, f"{field_name}.production_blockers")


@dataclass(frozen=True)
class ModelSelector:
    mode: str
    registry_channel: str | None
    package_id: str | None
    expected_package_fingerprint: str | None

    def validate(self, field_name: str) -> None:
        if self.mode == "registry_channel":
            _required_text(self.registry_channel or "", f"{field_name}.registry_channel")
            _required_text(self.package_id or "", f"{field_name}.package_id")
            if self.expected_package_fingerprint is None:
                raise LifecycleContractValidationError(
                    f"{field_name}.expected_package_fingerprint is required"
                )
            _sha256(
                self.expected_package_fingerprint,
                f"{field_name}.expected_package_fingerprint",
            )
            return
        if self.mode == "explicit_package":
            if self.registry_channel is not None:
                raise LifecycleContractValidationError(
                    f"{field_name} explicit-package mode must not set registry_channel"
                )
            _required_text(self.package_id or "", f"{field_name}.package_id")
            if self.expected_package_fingerprint is None:
                raise LifecycleContractValidationError(
                    f"{field_name}.expected_package_fingerprint is required"
                )
            _sha256(
                self.expected_package_fingerprint,
                f"{field_name}.expected_package_fingerprint",
            )
            return
        raise LifecycleContractValidationError(f"Unknown {field_name}.mode: {self.mode}")


@dataclass(frozen=True)
class PolicySelection:
    optimizer_policy_id: str
    optimizer_policy_sha256: str
    gate_policy_version: str
    business_policy_id: str
    business_policy_sha256: str
    business_decision_mode: str

    def validate(self, field_name: str) -> None:
        for name in (
            "optimizer_policy_id",
            "gate_policy_version",
            "business_policy_id",
            "business_decision_mode",
        ):
            _required_text(getattr(self, name), f"{field_name}.{name}")
        _sha256(
            self.optimizer_policy_sha256,
            f"{field_name}.optimizer_policy_sha256",
        )
        _sha256(
            self.business_policy_sha256,
            f"{field_name}.business_policy_sha256",
        )


@dataclass(frozen=True)
class SamplingProfile:
    scenario6_attempt_budget: int
    search_posterior_draws: int
    final_posterior_draws: int
    search_seed: int
    final_seed: int

    def validate(self, field_name: str) -> None:
        for name in (
            "scenario6_attempt_budget",
            "search_posterior_draws",
            "final_posterior_draws",
        ):
            _positive_int(getattr(self, name), f"{field_name}.{name}")
        _non_negative_int(self.search_seed, f"{field_name}.search_seed")
        _non_negative_int(self.final_seed, f"{field_name}.final_seed")


@dataclass(frozen=True)
class ProgressCounter:
    name: str
    current: float
    total: float | None
    unit: str

    def validate(self, field_name: str) -> None:
        _code(self.name, f"{field_name}.name")
        _non_negative(self.current, f"{field_name}.current")
        _non_negative(self.total, f"{field_name}.total")
        if self.total is not None and self.current > self.total:
            raise LifecycleContractValidationError(
                f"{field_name}.current must not exceed total"
            )
        _required_text(self.unit, f"{field_name}.unit")


@dataclass(frozen=True)
class CampaignUploadV1(_ContractMixin):
    contract_name: str
    schema_version: str
    record_origin: str
    upload_id: str
    actor_id: str
    status: LifecycleStatus
    received_at_utc: str
    parsed_at_utc: str | None
    rejected_at_utc: str | None
    original_file: ArtifactIdentity
    parser_name: str | None
    parser_version: str | None
    parsed_payload: ArtifactIdentity | None
    source_rows_n: int | None
    detected_campaigns_n: int | None
    rejection_error_id: str | None

    def validate(self) -> None:
        self._validate_header(CAMPAIGN_UPLOAD_CONTRACT)
        _opaque_id(self.upload_id, "upload_id")
        _opaque_id(self.actor_id, "actor_id")
        self.status.validate(UPLOAD_STATUS_CODES, "status")
        received = _timestamp(self.received_at_utc, "received_at_utc")
        parsed = _timestamp(self.parsed_at_utc, "parsed_at_utc", nullable=True)
        rejected = _timestamp(self.rejected_at_utc, "rejected_at_utc", nullable=True)
        self.original_file.validate("original_file", "campaign_upload_source")
        if (self.parser_name is None) != (self.parser_version is None):
            raise LifecycleContractValidationError(
                "parser_name and parser_version must be set together"
            )
        _non_negative_int(self.source_rows_n, "source_rows_n")
        _non_negative_int(self.detected_campaigns_n, "detected_campaigns_n")
        _opaque_id(
            self.rejection_error_id,
            "rejection_error_id",
            nullable=True,
        )
        if self.status.code == "received":
            if any(
                value is not None
                for value in (
                    self.parsed_at_utc,
                    self.rejected_at_utc,
                    self.parser_name,
                    self.parser_version,
                    self.parsed_payload,
                    self.source_rows_n,
                    self.detected_campaigns_n,
                    self.rejection_error_id,
                )
            ):
                raise LifecycleContractValidationError(
                    "received upload must not contain parse or rejection outcome"
                )
        elif self.status.code == "parsed":
            if parsed is None or self.parsed_payload is None:
                raise LifecycleContractValidationError(
                    "parsed upload requires parsed_at_utc and parsed_payload"
                )
            _required_text(self.parser_name or "", "parser_name")
            _required_text(self.parser_version or "", "parser_version")
            self.parsed_payload.validate(
                "parsed_payload",
                "campaign_upload_parsed",
            )
            if self.source_rows_n is None or self.detected_campaigns_n is None:
                raise LifecycleContractValidationError(
                    "parsed upload requires source and campaign counts"
                )
            if rejected is not None or self.rejection_error_id is not None:
                raise LifecycleContractValidationError(
                    "parsed upload must not contain a rejection outcome"
                )
        else:
            if rejected is None or self.rejection_error_id is None:
                raise LifecycleContractValidationError(
                    "rejected upload requires rejected_at_utc and rejection_error_id"
                )
            if parsed is not None or self.parsed_payload is not None:
                raise LifecycleContractValidationError(
                    "rejected upload must not contain a parsed outcome"
                )
        for timestamp_name, timestamp_value in (
            ("parsed_at_utc", parsed),
            ("rejected_at_utc", rejected),
        ):
            if timestamp_value is not None and timestamp_value < received:
                raise LifecycleContractValidationError(
                    f"{timestamp_name} must not precede received_at_utc"
                )
        self._reject_paths()


@dataclass(frozen=True)
class ValidationResultV1(_ContractMixin):
    contract_name: str
    schema_version: str
    record_origin: str
    validation_id: str
    upload_id: str
    status: LifecycleStatus
    validator_name: str
    validator_version: str
    started_at_utc: str
    finished_at_utc: str | None
    source_payload: ArtifactIdentity
    model: ResolvedModelReference | None
    normalized_plan: ArtifactIdentity | None
    daily_flighting: ArtifactIdentity | None
    model_validation: ArtifactIdentity | None
    campaigns: tuple[CampaignPreview, ...]
    totals: ValidationTotals | None
    blocking_errors: tuple[ValidationIssue, ...]
    warnings: tuple[ValidationIssue, ...]
    job_creation_allowed: bool

    def validate(self) -> None:
        self._validate_header(VALIDATION_RESULT_CONTRACT)
        _opaque_id(self.validation_id, "validation_id")
        _opaque_id(self.upload_id, "upload_id")
        self.status.validate(VALIDATION_STATUS_CODES, "status")
        _boolean(self.job_creation_allowed, "job_creation_allowed")
        _required_text(self.validator_name, "validator_name")
        _required_text(self.validator_version, "validator_version")
        started = _timestamp(self.started_at_utc, "started_at_utc")
        finished = _timestamp(self.finished_at_utc, "finished_at_utc", nullable=True)
        if finished is not None and finished < started:
            raise LifecycleContractValidationError(
                "finished_at_utc must not precede started_at_utc"
            )
        self.source_payload.validate(
            "source_payload",
            "campaign_upload_parsed",
        )
        if self.model is not None:
            self.model.validate("model")
        artifact_expectations = (
            ("normalized_plan", self.normalized_plan, "campaign_plan_normalized"),
            ("daily_flighting", self.daily_flighting, "campaign_flighting_daily"),
            ("model_validation", self.model_validation, "campaign_model_validation"),
        )
        for name, artifact, kind in artifact_expectations:
            if artifact is not None:
                artifact.validate(name, kind)
        campaign_ids = tuple(campaign.campaign_id for campaign in self.campaigns)
        _unique(campaign_ids, "campaigns.campaign_id")
        for index, campaign in enumerate(self.campaigns):
            campaign.validate(f"campaigns[{index}]")
        if self.totals is not None:
            self.totals.validate("totals")
            if self.campaigns:
                for name in ("source_rows_n", "normalized_rows_n", "daily_rows_n"):
                    campaign_total = sum(getattr(item, name) for item in self.campaigns)
                    if getattr(self.totals, name) != campaign_total:
                        raise LifecycleContractValidationError(
                            f"totals.{name} does not match campaigns"
                        )
                for name in (
                    "uploaded_budget_rub",
                    "model_input_budget_rub",
                    "unmodeled_budget_rub",
                    "daily_budget_rub",
                ):
                    campaign_total = sum(getattr(item, name) for item in self.campaigns)
                    reported_total = getattr(self.totals, name)
                    tolerance = max(1.0, abs(reported_total) * 1e-8)
                    if abs(reported_total - campaign_total) > tolerance:
                        raise LifecycleContractValidationError(
                            f"totals.{name} does not match campaigns"
                        )
        for index, issue in enumerate(self.blocking_errors):
            issue.validate(f"blocking_errors[{index}]")
            if issue.severity != "blocking":
                raise LifecycleContractValidationError(
                    "blocking_errors must contain only blocking issues"
                )
        for index, issue in enumerate(self.warnings):
            issue.validate(f"warnings[{index}]")
            if issue.severity != "warning":
                raise LifecycleContractValidationError(
                    "warnings must contain only warning issues"
                )
        if self.status.code == "running":
            if finished is not None or self.job_creation_allowed:
                raise LifecycleContractValidationError(
                    "running validation cannot be finished or allow job creation"
                )
        elif self.status.code == "valid":
            required = (
                finished,
                self.model,
                self.normalized_plan,
                self.daily_flighting,
                self.model_validation,
                self.totals,
            )
            if any(value is None for value in required) or not self.campaigns:
                raise LifecycleContractValidationError(
                    "valid validation requires completed artifacts, model, totals and campaigns"
                )
            if self.blocking_errors or not self.job_creation_allowed:
                raise LifecycleContractValidationError(
                    "valid validation must have no blockers and allow job creation"
                )
        else:
            if finished is None or not self.blocking_errors:
                raise LifecycleContractValidationError(
                    "invalid validation requires finished_at_utc and blocking errors"
                )
            if self.job_creation_allowed:
                raise LifecycleContractValidationError(
                    "invalid validation cannot allow job creation"
                )
        self._reject_paths()


@dataclass(frozen=True)
class DecisionJobV1(_ContractMixin):
    contract_name: str
    schema_version: str
    record_origin: str
    job_id: str
    idempotency_key: str
    job_type: str
    created_by_actor_id: str
    upload_id: str
    validation_id: str
    normalized_plan: ArtifactIdentity
    daily_flighting: ArtifactIdentity
    workflow_config: ArtifactIdentity
    model_selector: ModelSelector
    policies: PolicySelection
    sampling: SamplingProfile
    code_reference: str
    status: LifecycleStatus
    created_at_utc: str
    queued_at_utc: str
    started_at_utc: str | None
    cancel_requested_at_utc: str | None
    finished_at_utc: str | None
    attempt_number: int
    result_id: str | None
    terminal_error_id: str | None

    def validate(self) -> None:
        self._validate_header(DECISION_JOB_CONTRACT)
        for name in ("job_id", "created_by_actor_id", "upload_id", "validation_id"):
            _opaque_id(getattr(self, name), name)
        if not _IDEMPOTENCY_KEY_RE.fullmatch(self.idempotency_key):
            raise LifecycleContractValidationError("idempotency_key has an invalid format")
        if self.job_type != "forecast_optimizer_report":
            raise LifecycleContractValidationError("Unsupported job_type")
        self.normalized_plan.validate(
            "normalized_plan",
            "campaign_plan_normalized",
        )
        self.daily_flighting.validate(
            "daily_flighting",
            "campaign_flighting_daily",
        )
        self.workflow_config.validate("workflow_config", "workflow_config")
        self.model_selector.validate("model_selector")
        self.policies.validate("policies")
        self.sampling.validate("sampling")
        _required_text(self.code_reference, "code_reference")
        self.status.validate(JOB_STATUS_CODES, "status")
        created = _timestamp(self.created_at_utc, "created_at_utc")
        queued = _timestamp(self.queued_at_utc, "queued_at_utc")
        started = _timestamp(self.started_at_utc, "started_at_utc", nullable=True)
        cancel_requested = _timestamp(
            self.cancel_requested_at_utc,
            "cancel_requested_at_utc",
            nullable=True,
        )
        finished = _timestamp(self.finished_at_utc, "finished_at_utc", nullable=True)
        if queued < created:
            raise LifecycleContractValidationError(
                "queued_at_utc must not precede created_at_utc"
            )
        timeline = [
            ("started_at_utc", started, queued),
            ("cancel_requested_at_utc", cancel_requested, started),
            ("finished_at_utc", finished, started),
        ]
        for name, value, lower_bound in timeline:
            if value is not None and lower_bound is not None and value < lower_bound:
                raise LifecycleContractValidationError(
                    f"{name} is out of chronological order"
                )
        if (
            finished is not None
            and cancel_requested is not None
            and finished < cancel_requested
        ):
            raise LifecycleContractValidationError(
                "finished_at_utc must not precede cancel_requested_at_utc"
            )
        _non_negative_int(self.attempt_number, "attempt_number")
        _opaque_id(self.result_id, "result_id", nullable=True)
        _opaque_id(self.terminal_error_id, "terminal_error_id", nullable=True)
        status = self.status.code
        if status == "queued":
            if self.attempt_number != 0 or any(
                value is not None
                for value in (
                    started,
                    cancel_requested,
                    finished,
                    self.result_id,
                    self.terminal_error_id,
                )
            ):
                raise LifecycleContractValidationError(
                    "queued job must not contain execution outcome"
                )
        elif status == "running":
            if started is None or self.attempt_number < 1:
                raise LifecycleContractValidationError(
                    "running job requires a started execution attempt"
                )
            if any(
                value is not None
                for value in (
                    cancel_requested,
                    finished,
                    self.result_id,
                    self.terminal_error_id,
                )
            ):
                raise LifecycleContractValidationError(
                    "running job must not contain a terminal outcome"
                )
        elif status == "cancel_requested":
            if started is None or cancel_requested is None or self.attempt_number < 1:
                raise LifecycleContractValidationError(
                    "cancel_requested job requires started and cancellation timestamps"
                )
            if (
                finished is not None
                or self.result_id is not None
                or self.terminal_error_id is not None
            ):
                raise LifecycleContractValidationError(
                    "cancel_requested is not a terminal outcome"
                )
        elif status == "succeeded":
            if (
                started is None
                or finished is None
                or self.result_id is None
                or self.attempt_number < 1
            ):
                raise LifecycleContractValidationError(
                    "succeeded job requires attempt, timestamps and result_id"
                )
            if self.terminal_error_id is not None:
                raise LifecycleContractValidationError(
                    "succeeded job must not contain terminal_error_id"
                )
        elif status in {"failed", "timed_out"}:
            if (
                started is None
                or finished is None
                or self.terminal_error_id is None
                or self.attempt_number < 1
            ):
                raise LifecycleContractValidationError(
                    f"{status} job requires attempt, timestamps and terminal_error_id"
                )
            if self.result_id is not None:
                raise LifecycleContractValidationError(
                    f"{status} job must not contain result_id"
                )
        else:
            if (
                started is None
                or cancel_requested is None
                or finished is None
                or self.attempt_number < 1
            ):
                raise LifecycleContractValidationError(
                    "cancelled job requires started, cancellation and finished timestamps"
                )
            if self.result_id is not None or self.terminal_error_id is not None:
                raise LifecycleContractValidationError(
                    "cancelled job must not contain result_id or terminal_error_id"
                )
        self._reject_paths()


@dataclass(frozen=True)
class JobEventV1(_ContractMixin):
    contract_name: str
    schema_version: str
    record_origin: str
    event_id: str
    job_id: str
    sequence: int
    attempt_number: int
    emitted_at_utc: str
    actor_type: str
    actor_id: str | None
    from_status_code: str | None
    to_status: LifecycleStatus
    reason_code: str | None
    display_text: str

    def validate(self) -> None:
        self._validate_header(JOB_EVENT_CONTRACT)
        _opaque_id(self.event_id, "event_id")
        _opaque_id(self.job_id, "job_id")
        _positive_int(self.sequence, "sequence")
        _non_negative_int(self.attempt_number, "attempt_number")
        _timestamp(self.emitted_at_utc, "emitted_at_utc")
        if self.actor_type not in ACTOR_TYPES:
            raise LifecycleContractValidationError(
                f"Unknown actor_type: {self.actor_type}"
            )
        _opaque_id(self.actor_id, "actor_id", nullable=True)
        if self.actor_type in {"user", "admin"} and self.actor_id is None:
            raise LifecycleContractValidationError(
                f"actor_id is required for actor_type={self.actor_type}"
            )
        if self.from_status_code is not None and self.from_status_code not in JOB_STATUS_CODES:
            raise LifecycleContractValidationError(
                f"Unknown from_status_code: {self.from_status_code}"
            )
        self.to_status.validate(JOB_STATUS_CODES, "to_status")
        transitions = {
            (None, "queued"),
            ("queued", "running"),
            ("running", "cancel_requested"),
            ("running", "succeeded"),
            ("running", "failed"),
            ("running", "timed_out"),
            ("cancel_requested", "cancelled"),
            ("cancel_requested", "succeeded"),
            ("cancel_requested", "failed"),
            ("cancel_requested", "timed_out"),
        }
        transition = (self.from_status_code, self.to_status.code)
        if transition not in transitions:
            raise LifecycleContractValidationError(
                f"Unsupported job transition: {transition[0]} -> {transition[1]}"
            )
        _code(self.reason_code, "reason_code", nullable=True)
        if self.to_status.code in {
            "cancel_requested",
            "cancelled",
            "failed",
            "timed_out",
        } and self.reason_code is None:
            raise LifecycleContractValidationError(
                f"reason_code is required for transition to {self.to_status.code}"
            )
        if self.to_status.code == "queued" and self.attempt_number != 0:
            raise LifecycleContractValidationError(
                "queued event must use attempt_number=0"
            )
        if self.to_status.code != "queued" and self.attempt_number < 1:
            raise LifecycleContractValidationError(
                "execution transition requires attempt_number >= 1"
            )
        _required_text(self.display_text, "display_text")
        self._reject_paths()


@dataclass(frozen=True)
class ProgressEventV1(_ContractMixin):
    contract_name: str
    schema_version: str
    record_origin: str
    progress_event_id: str
    job_id: str
    sequence: int
    attempt_number: int
    emitted_at_utc: str
    stage: str
    phase: str
    state: str
    display_text: str
    campaign_id: str | None
    percent_complete: float | None
    counters: tuple[ProgressCounter, ...] = field(default_factory=tuple)

    def validate(self) -> None:
        self._validate_header(PROGRESS_EVENT_CONTRACT)
        _opaque_id(self.progress_event_id, "progress_event_id")
        _opaque_id(self.job_id, "job_id")
        _positive_int(self.sequence, "sequence")
        _positive_int(self.attempt_number, "attempt_number")
        _timestamp(self.emitted_at_utc, "emitted_at_utc")
        if self.stage not in PROGRESS_STAGES:
            raise LifecycleContractValidationError(f"Unknown progress stage: {self.stage}")
        _code(self.phase, "phase")
        if self.state not in PROGRESS_STATES:
            raise LifecycleContractValidationError(f"Unknown progress state: {self.state}")
        _required_text(self.display_text, "display_text")
        _opaque_id(self.campaign_id, "campaign_id", nullable=True)
        _percentage(self.percent_complete, "percent_complete")
        counter_names = tuple(counter.name for counter in self.counters)
        _unique(counter_names, "counters.name")
        for index, counter in enumerate(self.counters):
            counter.validate(f"counters[{index}]")
        self._reject_paths()


@dataclass(frozen=True)
class ApplicationErrorV1(_ContractMixin):
    contract_name: str
    schema_version: str
    record_origin: str
    error_id: str
    resource_type: str
    resource_id: str
    occurred_at_utc: str
    component: str
    stage: str | None
    code: str
    category: str
    severity: str
    retryable: bool
    display_text: str
    support_reference: str | None
    source_row_ids: tuple[int, ...] = field(default_factory=tuple)
    affected_cells: tuple[AffectedCell, ...] = field(default_factory=tuple)

    def validate(self) -> None:
        self._validate_header(APPLICATION_ERROR_CONTRACT)
        _opaque_id(self.error_id, "error_id")
        if self.resource_type not in ERROR_RESOURCE_TYPES:
            raise LifecycleContractValidationError(
                f"Unknown resource_type: {self.resource_type}"
            )
        _opaque_id(self.resource_id, "resource_id")
        _timestamp(self.occurred_at_utc, "occurred_at_utc")
        if self.component not in ERROR_COMPONENTS:
            raise LifecycleContractValidationError(f"Unknown component: {self.component}")
        if self.stage is not None and self.stage not in PROGRESS_STAGES | {
            "upload",
            "validation",
        }:
            raise LifecycleContractValidationError(f"Unknown error stage: {self.stage}")
        _code(self.code, "code")
        if self.category not in ERROR_CATEGORIES:
            raise LifecycleContractValidationError(f"Unknown category: {self.category}")
        if self.severity not in ERROR_SEVERITIES:
            raise LifecycleContractValidationError(f"Unknown severity: {self.severity}")
        _boolean(self.retryable, "retryable")
        _required_text(self.display_text, "display_text")
        if self.support_reference is not None:
            _required_text(self.support_reference, "support_reference")
        for row_id in self.source_row_ids:
            _positive_int(row_id, "source_row_ids")
        _unique(self.source_row_ids, "source_row_ids")
        for index, cell in enumerate(self.affected_cells):
            cell.validate(f"affected_cells[{index}]")
        self._reject_paths()


LifecycleContract = (
    CampaignUploadV1
    | ValidationResultV1
    | DecisionJobV1
    | JobEventV1
    | ProgressEventV1
    | ApplicationErrorV1
)


def validate_lifecycle_contract(record: LifecycleContract) -> dict[str, Any]:
    """Validate one lifecycle record and return its JSON-native representation."""

    record.validate()
    return record.to_dict()


def _status_from_dict(payload: Mapping[str, Any]) -> LifecycleStatus:
    return LifecycleStatus(**dict(payload))


def _artifact_from_dict(payload: Mapping[str, Any]) -> ArtifactIdentity:
    return ArtifactIdentity(**dict(payload))


def _affected_cell_from_dict(payload: Mapping[str, Any]) -> AffectedCell:
    return AffectedCell(**dict(payload))


def _validation_issue_from_dict(payload: Mapping[str, Any]) -> ValidationIssue:
    data = dict(payload)
    data["source_row_ids"] = tuple(data.get("source_row_ids", ()))
    data["affected_cells"] = tuple(
        _affected_cell_from_dict(item) for item in data.get("affected_cells", ())
    )
    return ValidationIssue(**data)


def _campaign_preview_from_dict(payload: Mapping[str, Any]) -> CampaignPreview:
    data = dict(payload)
    for name in ("segments", "channels", "geographies", "creatives"):
        data[name] = tuple(data.get(name, ()))
    return CampaignPreview(**data)


def _validation_result_from_dict(payload: Mapping[str, Any]) -> ValidationResultV1:
    data = dict(payload)
    data["status"] = _status_from_dict(data["status"])
    data["source_payload"] = _artifact_from_dict(data["source_payload"])
    if data.get("model") is not None:
        model_data = dict(data["model"])
        model_data["production_blockers"] = tuple(
            model_data.get("production_blockers", ())
        )
        data["model"] = ResolvedModelReference(**model_data)
    else:
        data["model"] = None
    for name in ("normalized_plan", "daily_flighting", "model_validation"):
        data[name] = (
            _artifact_from_dict(data[name]) if data.get(name) is not None else None
        )
    data["campaigns"] = tuple(
        _campaign_preview_from_dict(item) for item in data.get("campaigns", ())
    )
    data["totals"] = (
        ValidationTotals(**dict(data["totals"]))
        if data.get("totals") is not None
        else None
    )
    for name in ("blocking_errors", "warnings"):
        data[name] = tuple(
            _validation_issue_from_dict(item) for item in data.get(name, ())
        )
    return ValidationResultV1(**data)


def _upload_from_dict(payload: Mapping[str, Any]) -> CampaignUploadV1:
    data = dict(payload)
    data["status"] = _status_from_dict(data["status"])
    data["original_file"] = _artifact_from_dict(data["original_file"])
    data["parsed_payload"] = (
        _artifact_from_dict(data["parsed_payload"])
        if data.get("parsed_payload") is not None
        else None
    )
    return CampaignUploadV1(**data)


def _job_from_dict(payload: Mapping[str, Any]) -> DecisionJobV1:
    data = dict(payload)
    for name in ("normalized_plan", "daily_flighting", "workflow_config"):
        data[name] = _artifact_from_dict(data[name])
    data["model_selector"] = ModelSelector(**dict(data["model_selector"]))
    data["policies"] = PolicySelection(**dict(data["policies"]))
    data["sampling"] = SamplingProfile(**dict(data["sampling"]))
    data["status"] = _status_from_dict(data["status"])
    return DecisionJobV1(**data)


def _job_event_from_dict(payload: Mapping[str, Any]) -> JobEventV1:
    data = dict(payload)
    data["to_status"] = _status_from_dict(data["to_status"])
    return JobEventV1(**data)


def _progress_event_from_dict(payload: Mapping[str, Any]) -> ProgressEventV1:
    data = dict(payload)
    data["counters"] = tuple(
        ProgressCounter(**dict(item)) for item in data.get("counters", ())
    )
    return ProgressEventV1(**data)


def _application_error_from_dict(payload: Mapping[str, Any]) -> ApplicationErrorV1:
    data = dict(payload)
    data["source_row_ids"] = tuple(data.get("source_row_ids", ()))
    data["affected_cells"] = tuple(
        _affected_cell_from_dict(item) for item in data.get("affected_cells", ())
    )
    return ApplicationErrorV1(**data)


_LIFECYCLE_BUILDERS = {
    CAMPAIGN_UPLOAD_CONTRACT: _upload_from_dict,
    VALIDATION_RESULT_CONTRACT: _validation_result_from_dict,
    DECISION_JOB_CONTRACT: _job_from_dict,
    JOB_EVENT_CONTRACT: _job_event_from_dict,
    PROGRESS_EVENT_CONTRACT: _progress_event_from_dict,
    APPLICATION_ERROR_CONTRACT: _application_error_from_dict,
}


def parse_lifecycle_contract(payload: Mapping[str, Any]) -> LifecycleContract:
    """Parse and semantically validate one JSON-native lifecycle record."""

    if not isinstance(payload, Mapping):
        raise LifecycleContractValidationError(
            "Lifecycle payload must be a JSON object"
        )
    contract_name = payload.get("contract_name")
    if not isinstance(contract_name, str):
        raise LifecycleContractValidationError(
            "Lifecycle contract_name must be a string"
        )
    builder = _LIFECYCLE_BUILDERS.get(contract_name)
    if builder is None:
        raise LifecycleContractValidationError(
            f"Unknown lifecycle contract_name: {contract_name}"
        )
    try:
        record = builder(payload)
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, LifecycleContractValidationError):
            raise
        raise LifecycleContractValidationError(
            f"Malformed {contract_name} payload: {exc}"
        ) from exc
    record.validate()
    return record


def validate_lifecycle_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one JSON-native lifecycle record and return normalized JSON data."""

    return parse_lifecycle_contract(payload).to_dict()
