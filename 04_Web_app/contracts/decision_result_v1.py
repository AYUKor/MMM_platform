"""DecisionResult v1 domain models.

The module deliberately uses only the Python standard library. It defines the
stable worker-to-API-to-frontend result boundary without introducing a new
production dependency before the repository dependency policy is approved.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import PurePosixPath
from typing import Any


CONTRACT_NAME = "decision_result_v1"
SCHEMA_VERSION = "1.0.0"
RESULT_ADAPTER_NAME = "optimizer_result_adapter"
RESULT_ADAPTER_VERSION = "1.0.2"

CALCULATION_STATUS_CODES = {"calculated", "partially_calculated", "not_calculated"}
CAMPAIGN_SCALE_STATUS_CODES = {
    "within_historical_p95",
    "between_historical_p95_p99",
    "between_historical_p99_and_robust_upper",
    "above_historical_robust_upper",
    "benchmark_unavailable",
}
CELL_SUPPORT_STATUS_CODES = {
    "within_p95",
    "between_p95_p99",
    "above_p99_within_robust_upper",
    "above_robust_upper",
    "not_evaluated",
}
OPTIMIZER_STATUS_CODES = {
    "best_safe_available",
    "partial_safe_available",
    "no_safe_candidate",
    "gate_policy_blocked",
    "not_run",
}
BUSINESS_DECISION_STATUS_CODES = {
    "allocation_only",
    "manual_review_required",
    "meets_business_hurdle",
    "below_business_hurdle",
    "not_evaluated",
}
QUALITY_STATUS_CODES = {
    "reliable",
    "elevated_uncertainty",
    "manual_review_required",
    "not_for_automatic_reallocation",
    "not_calculated",
}
RECOMMENDATION_TYPE_CODES = {
    "keep_uploaded_plan",
    "reallocate_for_reliability",
    "reallocate_for_effect",
    "partial_safe_plan",
    "manual_review",
}
PLAN_STATUS_CODES = {
    "recommended_media_plan",
    "full_plan_partial_model_coverage",
    "partial_safe_plan",
    "no_automatic_plan",
}
SCENARIO6_RUN_STATUS_CODES = {
    "completed_best_safe",
    "completed_partial_safe",
    "completed_no_safe_candidate",
    "gate_policy_blocked",
    "not_run",
}
WARNING_SEVERITIES = {"info", "caution", "manual_review", "blocking"}
RESULT_ORIGINS = {"verified_optimizer_artifacts", "sanitized_fixture"}
EXPECTED_SCENARIOS = {f"S0{index}" for index in range(1, 7)}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_OPAQUE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*_[0-9a-f]{12,64}$")
_ABSOLUTE_PATH_RE = re.compile(r"^(?:/|[A-Za-z]:[\\/]|file://)")


class ContractValidationError(ValueError):
    """Raised when a DecisionResult object violates the v1 contract."""


def _json_compatible(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_compatible(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compatible(nested) for nested in value]
    return value


def _finite(value: float | None, field_name: str) -> None:
    if value is not None and not math.isfinite(float(value)):
        raise ContractValidationError(f"{field_name} must be finite")


def _fraction(value: float | None, field_name: str) -> None:
    _finite(value, field_name)
    if value is not None and not 0.0 <= float(value) <= 1.0:
        raise ContractValidationError(f"{field_name} must be between 0 and 1")


def _non_negative(value: float | int | None, field_name: str) -> None:
    _finite(float(value) if value is not None else None, field_name)
    if value is not None and float(value) < 0:
        raise ContractValidationError(f"{field_name} must be non-negative")


def _validate_status(status: "Status", allowed: set[str], field_name: str) -> None:
    if status.code not in allowed:
        raise ContractValidationError(f"Unknown {field_name} code: {status.code}")
    if not status.display_text.strip():
        raise ContractValidationError(f"{field_name}.display_text is required")


@dataclass(frozen=True)
class Status:
    code: str
    display_text: str


@dataclass(frozen=True)
class QuantileMetric:
    unit: str
    p10: float
    p50: float
    p90: float

    def validate(self, field_name: str) -> None:
        for quantile in ("p10", "p50", "p90"):
            _finite(getattr(self, quantile), f"{field_name}.{quantile}")
        if not self.p10 <= self.p50 <= self.p90:
            raise ContractValidationError(f"{field_name} must satisfy p10 <= p50 <= p90")


@dataclass(frozen=True)
class ScenarioMetrics:
    incremental_turnover: QuantileMetric | None
    roas_p50: float | None
    incremental_orders: QuantileMetric | None = None
    avg_basket_bridge: QuantileMetric | None = None

    def validate(self, field_name: str) -> None:
        _finite(self.roas_p50, f"{field_name}.roas_p50")
        for name in ("incremental_turnover", "incremental_orders", "avg_basket_bridge"):
            metric = getattr(self, name)
            if metric is not None:
                metric.validate(f"{field_name}.{name}")


@dataclass(frozen=True)
class PairedComparison:
    delta_incremental_turnover: QuantileMetric
    probability_gt_zero: float | None
    probability_noninferior: float | None
    moved_budget_rub: float | None
    posterior_draws: int | None

    def validate(self, field_name: str) -> None:
        self.delta_incremental_turnover.validate(f"{field_name}.delta_incremental_turnover")
        _fraction(self.probability_gt_zero, f"{field_name}.probability_gt_zero")
        _fraction(self.probability_noninferior, f"{field_name}.probability_noninferior")
        _non_negative(self.moved_budget_rub, f"{field_name}.moved_budget_rub")
        _non_negative(self.posterior_draws, f"{field_name}.posterior_draws")


@dataclass(frozen=True)
class SupportSummary:
    elevated_warnings: int
    strong_warnings: int
    hard_warnings: int
    policy_violations: int

    def validate(self, field_name: str) -> None:
        for name in ("elevated_warnings", "strong_warnings", "hard_warnings", "policy_violations"):
            _non_negative(getattr(self, name), f"{field_name}.{name}")


@dataclass(frozen=True)
class QualitySummary:
    status: Status
    explanation: str
    coverage_share: float | None = None
    uncertainty_width_share: float | None = None

    def validate(self, field_name: str) -> None:
        _validate_status(self.status, QUALITY_STATUS_CODES, f"{field_name}.status")
        if not self.explanation.strip():
            raise ContractValidationError(f"{field_name}.explanation is required")
        _fraction(self.coverage_share, f"{field_name}.coverage_share")
        _non_negative(self.uncertainty_width_share, f"{field_name}.uncertainty_width_share")


@dataclass(frozen=True)
class WarningItem:
    code: str
    severity: str
    display_text: str
    scope: str
    affected_cells: tuple[str, ...] = field(default_factory=tuple)

    def validate(self, field_name: str) -> None:
        if self.severity not in WARNING_SEVERITIES:
            raise ContractValidationError(f"Unknown {field_name}.severity: {self.severity}")
        if not self.code or not self.display_text.strip() or not self.scope.strip():
            raise ContractValidationError(f"{field_name} requires code, display_text and scope")


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    name: str
    description: str
    available: bool
    requested_budget_rub: float
    allocated_budget_rub: float
    unallocated_budget_rub: float
    metrics: ScenarioMetrics
    calculation_status: Status
    cell_support_status: Status
    optimizer_status: Status
    support: SupportSummary
    quality: QualitySummary
    paired_comparison: PairedComparison | None = None

    def validate(self, field_name: str) -> None:
        if self.scenario_id not in EXPECTED_SCENARIOS:
            raise ContractValidationError(f"Unknown {field_name}.scenario_id: {self.scenario_id}")
        for name in ("requested_budget_rub", "allocated_budget_rub", "unallocated_budget_rub"):
            _non_negative(getattr(self, name), f"{field_name}.{name}")
        self.metrics.validate(f"{field_name}.metrics")
        _validate_status(self.calculation_status, CALCULATION_STATUS_CODES, f"{field_name}.calculation_status")
        _validate_status(self.cell_support_status, CELL_SUPPORT_STATUS_CODES, f"{field_name}.cell_support_status")
        _validate_status(self.optimizer_status, OPTIMIZER_STATUS_CODES, f"{field_name}.optimizer_status")
        self.support.validate(f"{field_name}.support")
        self.quality.validate(f"{field_name}.quality")
        if self.paired_comparison is not None:
            self.paired_comparison.validate(f"{field_name}.paired_comparison")
        if self.available and self.metrics.incremental_turnover is None:
            raise ContractValidationError(f"{field_name} is available but has no turnover metric")


@dataclass(frozen=True)
class Scenario6Audit:
    run_status: Status
    method: str
    attempt_budget: int
    attempts_evaluated: int
    kernel_evaluations: int
    unique_allocations: int
    candidates_generated: int
    candidates_scored: int
    candidates_rejected: int
    finalists: int
    search_posterior_draws: int
    final_posterior_draws: int
    search_converged: bool | None
    search_budget_exhausted: bool | None
    best_raw_candidate_id: str | None
    best_safe_candidate_id: str | None
    explanation: str

    def validate(self, field_name: str) -> None:
        _validate_status(self.run_status, SCENARIO6_RUN_STATUS_CODES, f"{field_name}.run_status")
        for name in (
            "attempt_budget",
            "attempts_evaluated",
            "kernel_evaluations",
            "unique_allocations",
            "candidates_generated",
            "candidates_scored",
            "candidates_rejected",
            "finalists",
            "search_posterior_draws",
            "final_posterior_draws",
        ):
            _non_negative(getattr(self, name), f"{field_name}.{name}")
        for candidate_id in (self.best_raw_candidate_id, self.best_safe_candidate_id):
            if candidate_id is not None and not _OPAQUE_ID_RE.fullmatch(candidate_id):
                raise ContractValidationError(f"{field_name} contains a non-opaque candidate ID")
        if not self.explanation.strip():
            raise ContractValidationError(f"{field_name}.explanation is required")


@dataclass(frozen=True)
class CampaignPassport:
    campaign_name: str
    source_campaign_name: str
    segments: tuple[str, ...]
    source_start_date: str
    source_end_date: str
    model_start_date: str
    model_end_date: str
    source_active_days: int
    model_active_days: int
    source_channels: tuple[str, ...]
    modeled_channels: tuple[str, ...]
    unmodeled_channels: tuple[str, ...]
    geographies: tuple[str, ...]
    creatives: tuple[str, ...]

    def validate(self, field_name: str) -> None:
        if not self.campaign_name.strip() or not self.source_campaign_name.strip():
            raise ContractValidationError(f"{field_name} requires campaign names")
        if not self.segments or not self.source_channels or not self.geographies:
            raise ContractValidationError(f"{field_name} requires segment, source channel and geography")
        try:
            source_start = date.fromisoformat(self.source_start_date)
            source_end = date.fromisoformat(self.source_end_date)
            model_start = date.fromisoformat(self.model_start_date)
            model_end = date.fromisoformat(self.model_end_date)
        except ValueError as exc:
            raise ContractValidationError(f"{field_name} contains an invalid ISO date") from exc
        if source_end < source_start or model_end < model_start:
            raise ContractValidationError(f"{field_name} date interval is reversed")
        if self.source_active_days <= 0 or self.model_active_days <= 0:
            raise ContractValidationError(f"{field_name} active-day counts must be positive")


@dataclass(frozen=True)
class BudgetReconciliation:
    uploaded_budget_rub: float
    model_input_budget_rub: float
    calculated_budget_rub: float
    unmodeled_budget_rub: float
    unallocated_budget_rub: float
    model_coverage_share: float

    def validate(self, field_name: str) -> None:
        for name in (
            "uploaded_budget_rub",
            "model_input_budget_rub",
            "calculated_budget_rub",
            "unmodeled_budget_rub",
            "unallocated_budget_rub",
        ):
            _non_negative(getattr(self, name), f"{field_name}.{name}")
        _fraction(self.model_coverage_share, f"{field_name}.model_coverage_share")
        tolerance = max(1.0, self.uploaded_budget_rub * 1e-9)
        if abs(self.uploaded_budget_rub - self.model_input_budget_rub - self.unmodeled_budget_rub) > tolerance:
            raise ContractValidationError(f"{field_name} uploaded/model-input/unmodeled budgets do not reconcile")
        if abs(self.model_input_budget_rub - self.calculated_budget_rub - self.unallocated_budget_rub) > tolerance:
            raise ContractValidationError(f"{field_name} model-input/calculated/unallocated budgets do not reconcile")


@dataclass(frozen=True)
class AllocationLine:
    segment: str
    geo: str
    channel: str
    budget_rub: float
    budget_share: float
    allocation_note: str

    def validate(self, field_name: str) -> None:
        if not self.segment.strip() or not self.geo.strip() or not self.channel.strip():
            raise ContractValidationError(f"{field_name} requires segment, geo and channel")
        _non_negative(self.budget_rub, f"{field_name}.budget_rub")
        _fraction(self.budget_share, f"{field_name}.budget_share")


@dataclass(frozen=True)
class Recommendation:
    scenario_id: str
    scenario_name: str
    candidate_id: str
    recommendation_type: Status
    reason: str
    plan_status: Status
    optimizer_available: bool
    metrics: ScenarioMetrics

    def validate(self, field_name: str) -> None:
        if self.scenario_id not in EXPECTED_SCENARIOS:
            raise ContractValidationError(f"Unknown {field_name}.scenario_id: {self.scenario_id}")
        if not _OPAQUE_ID_RE.fullmatch(self.candidate_id):
            raise ContractValidationError(f"{field_name}.candidate_id must be opaque")
        if not self.scenario_name.strip():
            raise ContractValidationError(f"{field_name}.scenario_name is required")
        _validate_status(self.recommendation_type, RECOMMENDATION_TYPE_CODES, f"{field_name}.recommendation_type")
        _validate_status(self.plan_status, PLAN_STATUS_CODES, f"{field_name}.plan_status")
        self.metrics.validate(f"{field_name}.metrics")
        if not self.reason.strip():
            raise ContractValidationError(f"{field_name}.reason is required")


@dataclass(frozen=True)
class DecisionStatuses:
    calculation_status: Status
    campaign_scale_status: Status
    cell_support_status: Status
    optimizer_status: Status
    business_decision_status: Status

    def validate(self, field_name: str) -> None:
        _validate_status(self.calculation_status, CALCULATION_STATUS_CODES, f"{field_name}.calculation_status")
        _validate_status(self.campaign_scale_status, CAMPAIGN_SCALE_STATUS_CODES, f"{field_name}.campaign_scale_status")
        _validate_status(self.cell_support_status, CELL_SUPPORT_STATUS_CODES, f"{field_name}.cell_support_status")
        _validate_status(self.optimizer_status, OPTIMIZER_STATUS_CODES, f"{field_name}.optimizer_status")
        _validate_status(
            self.business_decision_status,
            BUSINESS_DECISION_STATUS_CODES,
            f"{field_name}.business_decision_status",
        )


@dataclass(frozen=True)
class CampaignDecisionResult:
    campaign_id: str
    passport: CampaignPassport
    budget: BudgetReconciliation
    scenarios: tuple[ScenarioResult, ...]
    scenario6: Scenario6Audit
    recommendation: Recommendation
    recommended_allocation: tuple[AllocationLine, ...]
    statuses: DecisionStatuses
    quality: QualitySummary
    warnings: tuple[WarningItem, ...]

    def validate(self, field_name: str) -> None:
        if not _OPAQUE_ID_RE.fullmatch(self.campaign_id):
            raise ContractValidationError(f"{field_name}.campaign_id must be opaque")
        self.passport.validate(f"{field_name}.passport")
        self.budget.validate(f"{field_name}.budget")
        scenario_ids = {scenario.scenario_id for scenario in self.scenarios}
        if scenario_ids != EXPECTED_SCENARIOS or len(self.scenarios) != len(EXPECTED_SCENARIOS):
            raise ContractValidationError(f"{field_name}.scenarios must contain S01-S06 exactly once")
        for index, scenario in enumerate(self.scenarios):
            scenario.validate(f"{field_name}.scenarios[{index}]")
        self.scenario6.validate(f"{field_name}.scenario6")
        self.recommendation.validate(f"{field_name}.recommendation")
        for index, allocation in enumerate(self.recommended_allocation):
            allocation.validate(f"{field_name}.recommended_allocation[{index}]")
        self.statuses.validate(f"{field_name}.statuses")
        self.quality.validate(f"{field_name}.quality")
        for index, warning in enumerate(self.warnings):
            warning.validate(f"{field_name}.warnings[{index}]")


@dataclass(frozen=True)
class JobLineage:
    job_id: str
    source_run_id: str
    job_type: str
    started_at_utc: str
    finished_at_utc: str
    workflow_config_sha256: str
    input_flighting_sha256: str
    adapter_name: str
    adapter_version: str
    adapter_sha256: str

    def validate(self, field_name: str) -> None:
        if not _OPAQUE_ID_RE.fullmatch(self.job_id):
            raise ContractValidationError(f"{field_name}.job_id must be opaque")
        for name, value in {
            "source_run_id": self.source_run_id,
            "job_type": self.job_type,
            "started_at_utc": self.started_at_utc,
            "finished_at_utc": self.finished_at_utc,
            "adapter_name": self.adapter_name,
            "adapter_version": self.adapter_version,
        }.items():
            if not str(value).strip():
                raise ContractValidationError(f"{field_name}.{name} must not be empty")
        if self.job_type != "forecast_optimizer_report":
            raise ContractValidationError(f"{field_name}.job_type is unsupported")
        if self.adapter_name != RESULT_ADAPTER_NAME or self.adapter_version != RESULT_ADAPTER_VERSION:
            raise ContractValidationError(f"{field_name} has an unsupported result adapter")
        for name, value in {
            "workflow_config_sha256": self.workflow_config_sha256,
            "input_flighting_sha256": self.input_flighting_sha256,
            "adapter_sha256": self.adapter_sha256,
        }.items():
            if not _SHA256_RE.fullmatch(value):
                raise ContractValidationError(f"{field_name}.{name} is invalid")


@dataclass(frozen=True)
class ModelLineage:
    registry_channel: str
    registry_event_id: str
    package_id: str
    package_fingerprint: str
    package_manifest_sha256: str
    activation_status: str
    production_blockers: tuple[str, ...]

    def validate(self, field_name: str) -> None:
        for name, value in {
            "registry_channel": self.registry_channel,
            "registry_event_id": self.registry_event_id,
            "package_id": self.package_id,
            "activation_status": self.activation_status,
        }.items():
            if not str(value).strip():
                raise ContractValidationError(f"{field_name}.{name} must not be empty")
        for name, value in {
            "package_fingerprint": self.package_fingerprint,
            "package_manifest_sha256": self.package_manifest_sha256,
        }.items():
            if not _SHA256_RE.fullmatch(value):
                raise ContractValidationError(f"{field_name}.{name} is invalid")


@dataclass(frozen=True)
class PolicyLineage:
    optimizer_policy_id: str
    optimizer_policy_sha256: str
    business_policy_id: str
    business_policy_sha256: str
    business_decision_mode: str
    search_seed: int
    final_seed: int

    def validate(self, field_name: str) -> None:
        for name, value in {
            "optimizer_policy_id": self.optimizer_policy_id,
            "business_policy_id": self.business_policy_id,
            "business_decision_mode": self.business_decision_mode,
        }.items():
            if not str(value).strip():
                raise ContractValidationError(f"{field_name}.{name} must not be empty")
        for name, value in {
            "optimizer_policy_sha256": self.optimizer_policy_sha256,
            "business_policy_sha256": self.business_policy_sha256,
        }.items():
            if not _SHA256_RE.fullmatch(value):
                raise ContractValidationError(f"{field_name}.{name} is invalid")
        _non_negative(self.search_seed, f"{field_name}.search_seed")
        _non_negative(self.final_seed, f"{field_name}.final_seed")


@dataclass(frozen=True)
class ArtifactReference:
    artifact_id: str
    kind: str
    display_name: str
    media_type: str
    sha256: str
    size_bytes: int
    storage_key: str

    def validate(self, field_name: str) -> None:
        if not _OPAQUE_ID_RE.fullmatch(self.artifact_id):
            raise ContractValidationError(f"{field_name}.artifact_id must be opaque")
        if not _SHA256_RE.fullmatch(self.sha256):
            raise ContractValidationError(f"{field_name}.sha256 is invalid")
        _non_negative(self.size_bytes, f"{field_name}.size_bytes")
        path = PurePosixPath(self.storage_key)
        if path.is_absolute() or ".." in path.parts or not self.storage_key.strip():
            raise ContractValidationError(f"{field_name}.storage_key must be a safe relative key")


@dataclass(frozen=True)
class DecisionResultV1:
    contract_name: str
    schema_version: str
    result_id: str
    result_origin: str
    created_at_utc: str
    job: JobLineage
    model: ModelLineage
    policies: PolicyLineage
    campaign_results: tuple[CampaignDecisionResult, ...]
    artifacts: tuple[ArtifactReference, ...]
    warnings: tuple[WarningItem, ...]

    def validate(self) -> None:
        if self.contract_name != CONTRACT_NAME or self.schema_version != SCHEMA_VERSION:
            raise ContractValidationError("Unsupported DecisionResult contract version")
        if self.result_origin not in RESULT_ORIGINS:
            raise ContractValidationError(f"Unknown result_origin: {self.result_origin}")
        if not _OPAQUE_ID_RE.fullmatch(self.result_id):
            raise ContractValidationError("result_id must be opaque")
        self.job.validate("job")
        self.model.validate("model")
        self.policies.validate("policies")
        if not self.campaign_results:
            raise ContractValidationError("campaign_results must not be empty")
        campaign_ids = [campaign.campaign_id for campaign in self.campaign_results]
        if len(campaign_ids) != len(set(campaign_ids)):
            raise ContractValidationError("campaign_ids must be unique")
        for index, campaign in enumerate(self.campaign_results):
            campaign.validate(f"campaign_results[{index}]")
        artifact_ids = [artifact.artifact_id for artifact in self.artifacts]
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ContractValidationError("artifact_ids must be unique")
        for index, artifact in enumerate(self.artifacts):
            artifact.validate(f"artifacts[{index}]")
        for index, warning in enumerate(self.warnings):
            warning.validate(f"warnings[{index}]")
        self._reject_absolute_paths(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return _json_compatible(asdict(self))

    @classmethod
    def _reject_absolute_paths(cls, value: Any, field_name: str = "root") -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                cls._reject_absolute_paths(nested, f"{field_name}.{key}")
            return
        if isinstance(value, (list, tuple)):
            for index, nested in enumerate(value):
                cls._reject_absolute_paths(nested, f"{field_name}[{index}]")
            return
        if isinstance(value, str) and _ABSOLUTE_PATH_RE.match(value):
            raise ContractValidationError(f"Absolute workstation path is forbidden at {field_name}")
