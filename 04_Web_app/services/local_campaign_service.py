"""Local marketer upload, validation and immutable-job application service."""

from __future__ import annotations

import csv
import hashlib
import json
import mimetypes
import shutil
import subprocess
import sys
import traceback
import uuid
from collections import defaultdict
from concurrent.futures import Executor
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol


WEB_APP_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT_ROOT = WEB_APP_DIR.parent
PYMC_CODE_DIR = DEFAULT_PROJECT_ROOT / "02_Code" / "01_PyMC"
if str(WEB_APP_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_APP_DIR))
if str(PYMC_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(PYMC_CODE_DIR))

from contracts.application_lifecycle_v1 import (  # noqa: E402
    CAMPAIGN_UPLOAD_CONTRACT,
    DECISION_JOB_CONTRACT,
    SCHEMA_VERSION,
    VALIDATION_RESULT_CONTRACT,
    AffectedCell,
    ArtifactIdentity,
    CampaignPreview,
    CampaignUploadV1,
    DecisionJobV1,
    LifecycleContractValidationError,
    LifecycleStatus,
    ModelSelector,
    PolicySelection,
    ResolvedModelReference,
    SamplingProfile,
    ValidationIssue,
    ValidationResultV1,
    ValidationTotals,
    parse_lifecycle_contract,
)
from mmm_core.campaign_plan import (  # noqa: E402
    CampaignPlanError,
    normalize_campaign_rows,
    prepare_campaign_from_config,
    read_campaign_brief,
)
from mmm_core.io import load_config  # noqa: E402
from mmm_core.model_package import sha256_file  # noqa: E402
from mmm_core.model_package_reader import ModelPackage  # noqa: E402
from mmm_core.model_registry import resolve_model_reference  # noqa: E402


PARSER_NAME = "canonical_campaign_plan_parser"
PARSER_VERSION = "1.0.0"
VALIDATOR_NAME = "model_package_campaign_validator"
VALIDATOR_VERSION = "1.0.0"
SUPPORTED_UPLOAD_SUFFIXES = {".csv", ".tsv", ".xlsx", ".xls"}
CALCULATION_SOURCE_PATHS = (
    "02_Code/01_PyMC",
    "02_Code/02_Budget_optimizer",
    "02_Code/03_AC_forecast",
    "04_Web_app/adapters",
    "04_Web_app/api",
    "04_Web_app/contracts",
    "04_Web_app/services",
    "04_Web_app/worker",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _opaque_id(prefix: str, seed: str | None = None) -> str:
    value = hashlib.sha256((seed or uuid.uuid4().hex).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{value}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_child(root: Path, storage_key: str) -> Path:
    resolved_root = root.expanduser().resolve()
    candidate = resolved_root.joinpath(*storage_key.split("/")).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("Unsafe artifact storage key") from exc
    return candidate


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise CampaignPlanError("Campaign parser produced no rows")
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _artifact(
    root: Path,
    storage_key: str,
    *,
    kind: str,
    display_name: str | None = None,
    source: Path | None = None,
) -> ArtifactIdentity:
    destination = _safe_child(root, storage_key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source is not None:
        shutil.copy2(source, destination)
    if not destination.is_file():
        raise FileNotFoundError(destination)
    identity = ArtifactIdentity(
        artifact_id=_opaque_id("artifact", f"{storage_key}:{_sha256(destination)}"),
        kind=kind,
        display_name=display_name or destination.name,
        media_type=mimetypes.guess_type(destination.name)[0] or "application/octet-stream",
        sha256=_sha256(destination),
        size_bytes=destination.stat().st_size,
        storage_key=storage_key,
    )
    identity.validate("artifact", kind)
    return identity


class ApplicationState(Protocol):
    def create_upload(self, upload: CampaignUploadV1, idempotency_key: str, request_sha256: str) -> tuple[dict[str, Any], bool]: ...
    def write_upload(self, upload: CampaignUploadV1) -> None: ...
    def read_upload(self, upload_id: str) -> dict[str, Any]: ...
    def list_uploads(self) -> tuple[dict[str, Any], ...]: ...
    def create_validation(self, validation: ValidationResultV1, idempotency_key: str, request_sha256: str) -> tuple[dict[str, Any], bool]: ...
    def write_validation(self, validation: ValidationResultV1) -> None: ...
    def read_validation(self, validation_id: str) -> dict[str, Any]: ...
    def list_validations(self) -> tuple[dict[str, Any], ...]: ...
    def write_validation_inputs(self, validation_id: str, payload: Mapping[str, Any]) -> None: ...
    def read_validation_inputs(self, validation_id: str) -> dict[str, Any]: ...
    def find_job_by_idempotency(self, idempotency_key: str) -> dict[str, Any] | None: ...


JobSubmitter = Callable[[Mapping[str, Any]], tuple[dict[str, Any], bool]]


@dataclass(frozen=True)
class LocalCampaignServiceSettings:
    project_root: Path
    artifact_root: Path
    validation_runtime_root: Path
    registry_root: Path
    registry_channel: str
    expected_package_id: str
    optimizer_policy_path: Path
    business_policy_path: Path
    model_verification_mode: str = "full_lineage"
    max_upload_bytes: int = 50 * 1024 * 1024
    default_sampling: SamplingProfile = SamplingProfile(
        scenario6_attempt_budget=2048,
        search_posterior_draws=128,
        final_posterior_draws=600,
        search_seed=42,
        final_seed=10042,
    )

    def validate(self) -> None:
        if self.max_upload_bytes <= 0:
            raise ValueError("max_upload_bytes must be positive")
        if not self.registry_channel or not self.expected_package_id:
            raise ValueError("Pinned registry channel and package ID are required")
        if self.model_verification_mode not in {"full_lineage", "serving_bundle"}:
            raise ValueError("Unknown model verification mode")
        for path in (self.optimizer_policy_path, self.business_policy_path):
            if not path.expanduser().resolve().is_file():
                raise FileNotFoundError(path)
        self.default_sampling.validate("default_sampling")


class LocalCampaignService:
    """Create lifecycle resources without placing model calculations in HTTP requests."""

    def __init__(
        self,
        settings: LocalCampaignServiceSettings,
        state: ApplicationState,
        executor: Executor,
        job_submitter: JobSubmitter,
    ) -> None:
        settings.validate()
        self.settings = settings
        self.state = state
        self.executor = executor
        self.job_submitter = job_submitter
        self.settings.artifact_root.mkdir(parents=True, exist_ok=True)
        self.settings.validation_runtime_root.mkdir(parents=True, exist_ok=True)

    def recover_pending_resources(self) -> dict[str, int]:
        """Resubmit deterministic upload parsing and validation after restart."""

        uploads_resumed = 0
        validations_resumed = 0
        uploads: dict[str, CampaignUploadV1] = {}
        for payload in self.state.list_uploads():
            parsed = parse_lifecycle_contract(payload)
            if not isinstance(parsed, CampaignUploadV1):
                raise LifecycleContractValidationError(
                    "Upload state contains an unexpected lifecycle record"
                )
            uploads[parsed.upload_id] = parsed
            if parsed.status.code == "received":
                self.executor.submit(self._parse_upload, parsed)
                uploads_resumed += 1
        for payload in self.state.list_validations():
            validation = parse_lifecycle_contract(payload)
            if not isinstance(validation, ValidationResultV1):
                raise LifecycleContractValidationError(
                    "Validation state contains an unexpected lifecycle record"
                )
            if validation.status.code != "running":
                continue
            upload = uploads.get(validation.upload_id)
            if upload is None:
                upload_payload = self.state.read_upload(validation.upload_id)
                parsed_upload = parse_lifecycle_contract(upload_payload)
                if not isinstance(parsed_upload, CampaignUploadV1):
                    raise LifecycleContractValidationError(
                        "Validation references an invalid upload record"
                    )
                upload = parsed_upload
            if upload.status.code != "parsed":
                invalid = replace(
                    validation,
                    status=LifecycleStatus("invalid", "План нельзя отправить в расчет"),
                    finished_at_utc=_utc_now(),
                    blocking_errors=(
                        ValidationIssue(
                            code="UPLOAD_NOT_PARSED_AFTER_RESTART",
                            severity="blocking",
                            display_text=(
                                "Backend был перезапущен до завершения разбора файла. "
                                "Повторите загрузку и validation."
                            ),
                            scope="upload",
                            recoverable=True,
                        ),
                    ),
                )
                invalid.validate()
                self.state.write_validation(invalid)
                continue
            self.executor.submit(self._validate_campaign, upload, validation)
            validations_resumed += 1
        return {
            "uploads_resumed": uploads_resumed,
            "validations_resumed": validations_resumed,
        }

    def create_upload(
        self,
        *,
        filename: str,
        content: bytes,
        idempotency_key: str,
        actor_id: str,
    ) -> tuple[dict[str, Any], bool]:
        if not content or len(content) > self.settings.max_upload_bytes:
            raise ValueError("Upload is empty or exceeds the configured size limit")
        if filename in {"", ".", ".."} or Path(filename).name != filename or "/" in filename or "\\" in filename:
            raise ValueError("Upload filename must not contain a path")
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
            raise ValueError("Supported campaign files: CSV, TSV, XLSX and XLS")
        content_sha = hashlib.sha256(content).hexdigest()
        upload_id = _opaque_id("upload", f"{idempotency_key}:{filename}:{content_sha}")
        storage_key = f"uploads/{upload_id}/source/{filename}"
        source_path = _safe_child(self.settings.artifact_root, storage_key)
        source_path.parent.mkdir(parents=True, exist_ok=True)
        if not source_path.exists():
            source_path.write_bytes(content)
        if _sha256(source_path) != content_sha:
            raise ValueError("Stored upload hash does not match request body")
        original = _artifact(
            self.settings.artifact_root,
            storage_key,
            kind="campaign_upload_source",
            display_name=filename,
        )
        upload = CampaignUploadV1(
            contract_name=CAMPAIGN_UPLOAD_CONTRACT,
            schema_version=SCHEMA_VERSION,
            record_origin="application_runtime",
            upload_id=upload_id,
            actor_id=actor_id,
            status=LifecycleStatus("received", "Файл получен"),
            received_at_utc=_utc_now(),
            parsed_at_utc=None,
            rejected_at_utc=None,
            original_file=original,
            parser_name=None,
            parser_version=None,
            parsed_payload=None,
            source_rows_n=None,
            detected_campaigns_n=None,
            rejection_error_id=None,
        )
        upload.validate()
        request_sha = hashlib.sha256(f"{filename}:{content_sha}".encode()).hexdigest()
        record, created = self.state.create_upload(upload, idempotency_key, request_sha)
        if created:
            self.executor.submit(self._parse_upload, upload)
        return record, created

    def _parse_upload(self, upload: CampaignUploadV1) -> None:
        try:
            source_path = _safe_child(self.settings.artifact_root, upload.original_file.storage_key)
            raw_rows = read_campaign_brief(source_path)
            normalized_rows, issues = normalize_campaign_rows(raw_rows)
            if issues:
                raise CampaignPlanError(f"Campaign contains {len(issues)} invalid row(s)")
            campaigns = sorted({str(row["campaign_name"]) for row in normalized_rows})
            parsed_key = f"uploads/{upload.upload_id}/parsed/campaign_upload_parsed.csv"
            parsed_path = _safe_child(self.settings.artifact_root, parsed_key)
            _write_csv(parsed_path, normalized_rows)
            parsed_artifact = _artifact(
                self.settings.artifact_root,
                parsed_key,
                kind="campaign_upload_parsed",
            )
            parsed = replace(
                upload,
                status=LifecycleStatus("parsed", "Файл разобран"),
                parsed_at_utc=_utc_now(),
                parser_name=PARSER_NAME,
                parser_version=PARSER_VERSION,
                parsed_payload=parsed_artifact,
                source_rows_n=len(raw_rows),
                detected_campaigns_n=len(campaigns),
            )
            parsed.validate()
            self.state.write_upload(parsed)
        except Exception:
            log_path = self.settings.validation_runtime_root / "upload_parse_errors" / f"{upload.upload_id}.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(traceback.format_exc(), encoding="utf-8")
            error_id = _opaque_id("error", f"{upload.upload_id}:parse")
            rejected = replace(
                upload,
                status=LifecycleStatus("rejected", "Файл не удалось разобрать"),
                rejected_at_utc=_utc_now(),
                rejection_error_id=error_id,
            )
            rejected.validate()
            self.state.write_upload(rejected)

    def request_validation(
        self,
        upload_id: str,
        idempotency_key: str,
    ) -> tuple[dict[str, Any], bool]:
        parsed = parse_lifecycle_contract(self.state.read_upload(upload_id))
        if not isinstance(parsed, CampaignUploadV1) or parsed.status.code != "parsed":
            raise ValueError("Upload must be parsed before validation")
        assert parsed.parsed_payload is not None
        validation_id = _opaque_id("validation", f"{upload_id}:{idempotency_key}")
        started = ValidationResultV1(
            contract_name=VALIDATION_RESULT_CONTRACT,
            schema_version=SCHEMA_VERSION,
            record_origin="application_runtime",
            validation_id=validation_id,
            upload_id=upload_id,
            status=LifecycleStatus("running", "План проверяется"),
            validator_name=VALIDATOR_NAME,
            validator_version=VALIDATOR_VERSION,
            started_at_utc=_utc_now(),
            finished_at_utc=None,
            source_payload=parsed.parsed_payload,
            model=None,
            normalized_plan=None,
            daily_flighting=None,
            model_validation=None,
            campaigns=(),
            totals=None,
            blocking_errors=(),
            warnings=(),
            job_creation_allowed=False,
        )
        started.validate()
        request_sha = hashlib.sha256(upload_id.encode()).hexdigest()
        record, created = self.state.create_validation(
            started,
            idempotency_key,
            request_sha,
        )
        if created:
            self.executor.submit(self._validate_campaign, parsed, started)
        return record, created

    def _workflow_config(self, validation: ValidationResultV1) -> dict[str, Any]:
        source = validation.source_payload
        parsed_path = _safe_child(self.settings.artifact_root, source.storage_key)
        output_dir = self.settings.validation_runtime_root / validation.validation_id / "preparation"
        intermediate_dir = self.settings.validation_runtime_root / validation.validation_id / "campaign_intermediates"
        return {
            "run_id": f"web_validation_{validation.validation_id}",
            "layer": "budget_optimizer",
            "decision_policy_file": str(self.settings.optimizer_policy_path.resolve()),
            "model_ref": {
                "source": "registry",
                "registry_root": str(self.settings.registry_root.resolve()),
                "channel": self.settings.registry_channel,
                "expected_package_id": self.settings.expected_package_id,
                "verification_mode": self.settings.model_verification_mode,
            },
            "paths": {
                "campaign_input_dir": str(parsed_path.parent),
                "campaign_file": parsed_path.name,
                "campaign_sheet": None,
                "output_dir": str(output_dir.resolve()),
                "validated_output_dir": str((intermediate_dir / "validated").resolve()),
                "flighting_output_dir": str((intermediate_dir / "flighting").resolve()),
            },
            "validation": {"fail_on_parse_issues": True, "fail_on_unsupported": True},
            "future_controls": {
                "strategy": "historical_analog_period",
                "analog_year": 2025,
                "missing_geo_policy": "nearest_available_year_same_geo",
            },
            "objective": {
                "primary": "maximize_incremental_turnover_p50",
                "model_risk_policy": "balanced",
                "business_threshold_policy": str(self.settings.business_policy_path.resolve()),
            },
            "optimizer": {
                "targets": ["turnover_per_user", "orders_per_user", "avg_basket"],
                "scenario_6": {"enabled": True},
            },
            "report": {"intervals": ["p10", "p50", "p90"]},
        }

    def _validate_campaign(
        self,
        upload: CampaignUploadV1,
        validation: ValidationResultV1,
    ) -> None:
        try:
            config = self._workflow_config(validation)
            config_key = f"validations/{validation.validation_id}/config/source_workflow_config.json"
            config_path = _safe_child(self.settings.artifact_root, config_key)
            _write_json(config_path, config)
            workflow_artifact = _artifact(
                self.settings.artifact_root,
                config_key,
                kind="workflow_config",
            )
            run_dir, resolution = resolve_model_reference(config, config_path, purpose="optimizer")
            package = ModelPackage.from_run_dir(
                run_dir,
                require_posterior_ready=False,
                validate_hash=(
                    resolution.get("verification_mode", "full_lineage") == "full_lineage"
                ),
            )
            preparation_dir = Path(config["paths"]["output_dir"])
            prep = prepare_campaign_from_config(
                config,
                config_path,
                package,
                preparation_dir,
                purpose="optimizer",
            )
            valid = self._build_valid_validation(
                upload,
                validation,
                prep,
                resolution,
                package,
            )
            policies = self._policy_selection(package)
            self.state.write_validation_inputs(
                validation.validation_id,
                {
                    "workflow_config": asdict(workflow_artifact),
                    "policies": {
                        "optimizer_policy_id": policies.optimizer_policy_id,
                        "optimizer_policy_sha256": policies.optimizer_policy_sha256,
                        "gate_policy_version": policies.gate_policy_version,
                        "business_policy_id": policies.business_policy_id,
                        "business_policy_sha256": policies.business_policy_sha256,
                        "business_decision_mode": policies.business_decision_mode,
                    },
                },
            )
            self.state.write_validation(valid)
        except Exception:
            log_path = (
                self.settings.validation_runtime_root
                / validation.validation_id
                / "protected_validation.log"
            )
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(traceback.format_exc(), encoding="utf-8")
            issue = self._validation_failure_issue(validation.validation_id)
            invalid = replace(
                validation,
                status=LifecycleStatus("invalid", "План нельзя отправить в расчет"),
                finished_at_utc=_utc_now(),
                blocking_errors=(issue,),
            )
            invalid.validate()
            self.state.write_validation(invalid)

    def _validation_failure_issue(self, validation_id: str) -> ValidationIssue:
        preparation_dir = (
            self.settings.validation_runtime_root / validation_id / "preparation"
        )
        validation_files = sorted(preparation_dir.glob("*_campaign_model_validation.csv"))
        if len(validation_files) == 1:
            rows = _read_csv(validation_files[0])
            unsupported = [
                row
                for row in rows
                if str(row.get("supported_by_model") or "").lower() != "true"
            ]
            if unsupported:
                affected = tuple(
                    AffectedCell(
                        campaign_id=_opaque_id(
                            "campaign", str(row.get("campaign_name") or "")
                        ),
                        segment=str(row.get("segment") or ""),
                        geo=str(row.get("geo") or ""),
                        channel=str(row.get("channel") or ""),
                        target=str(row.get("target") or ""),
                    )
                    for row in unsupported
                )
                return ValidationIssue(
                    code="UNSUPPORTED_MODEL_CELLS",
                    severity="blocking",
                    display_text=(
                        f"Модель не поддерживает {len(unsupported)} связок campaign x geo x channel x target. "
                        "Исправьте медиаплан или используйте подходящий model package."
                    ),
                    scope="cell",
                    recoverable=True,
                    affected_cells=affected,
                )
        return ValidationIssue(
            code="CAMPAIGN_VALIDATION_FAILED",
            severity="blocking",
            display_text=(
                "Кампания не прошла model-aware validation. Проверьте обязательные поля, "
                "поддержку geo x channel и формат бюджета."
            ),
            scope="upload",
            recoverable=True,
        )

    def _policy_selection(self, package: ModelPackage) -> PolicySelection:
        optimizer_policy = load_config(self.settings.optimizer_policy_path)
        business_policy = load_config(self.settings.business_policy_path)
        selection = PolicySelection(
            optimizer_policy_id=str(optimizer_policy.get("policy_id") or ""),
            optimizer_policy_sha256=sha256_file(self.settings.optimizer_policy_path),
            gate_policy_version=str(package.manifest.get("gate_policy_version") or ""),
            business_policy_id=str(business_policy.get("policy_id") or ""),
            business_policy_sha256=sha256_file(self.settings.business_policy_path),
            business_decision_mode=str((business_policy.get("decision") or {}).get("mode") or ""),
        )
        selection.validate("policies")
        return selection

    def _build_valid_validation(
        self,
        upload: CampaignUploadV1,
        validation: ValidationResultV1,
        prep: Any,
        resolution: Mapping[str, Any],
        package: ModelPackage,
    ) -> ValidationResultV1:
        prefix = f"validations/{validation.validation_id}"
        normalized = _artifact(
            self.settings.artifact_root,
            f"{prefix}/prepared/campaign_plan_normalized.csv",
            kind="campaign_plan_normalized",
            source=Path(prep.normalized_path),
        )
        flighting = _artifact(
            self.settings.artifact_root,
            f"{prefix}/prepared/campaign_flighting_daily.csv",
            kind="campaign_flighting_daily",
            source=Path(prep.flighting_path),
        )
        model_validation = _artifact(
            self.settings.artifact_root,
            f"{prefix}/prepared/campaign_model_validation.csv",
            kind="campaign_model_validation",
            source=Path(prep.validation_path),
        )
        normalized_rows = _read_csv(Path(prep.normalized_path))
        daily_rows = _read_csv(Path(prep.flighting_path))
        validation_rows = _read_csv(Path(prep.validation_path))
        campaigns, totals = self._campaign_previews(normalized_rows, daily_rows)
        model_summary = package.summary()
        manifest_path = Path(resolution["run_dir"]) / "model_manifest.json"
        model = ResolvedModelReference(
            registry_channel=str(resolution.get("channel") or ""),
            registry_event_id=str(resolution.get("event_id") or ""),
            package_id=str(resolution.get("package_id") or ""),
            package_fingerprint=str(resolution.get("package_input_fingerprint") or ""),
            package_manifest_sha256=sha256_file(manifest_path),
            activation_status=str(model_summary.get("activation_status") or ""),
            production_blockers=tuple(str(value) for value in model_summary.get("production_blockers") or []),
        )
        warnings = self._validation_warnings(validation_rows, campaigns)
        valid = replace(
            validation,
            status=LifecycleStatus("valid", "План можно рассчитать"),
            finished_at_utc=_utc_now(),
            model=model,
            normalized_plan=normalized,
            daily_flighting=flighting,
            model_validation=model_validation,
            campaigns=campaigns,
            totals=totals,
            warnings=warnings,
            job_creation_allowed=True,
        )
        valid.validate()
        return valid

    @staticmethod
    def _campaign_previews(
        normalized_rows: list[dict[str, str]],
        daily_rows: list[dict[str, str]],
    ) -> tuple[tuple[CampaignPreview, ...], ValidationTotals]:
        normalized_by_campaign: dict[str, list[dict[str, str]]] = defaultdict(list)
        daily_by_campaign: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in normalized_rows:
            normalized_by_campaign[str(row["campaign_name"])].append(row)
        for row in daily_rows:
            daily_by_campaign[str(row["campaign_name"])].append(row)
        previews: list[CampaignPreview] = []
        for name in sorted(normalized_by_campaign):
            source = normalized_by_campaign[name]
            daily = daily_by_campaign[name]
            dates = sorted({str(row["date"]) for row in daily})
            source_budget = sum(float(row["budget_rub"]) for row in source)
            daily_budget = sum(float(row["budget_rub"]) for row in daily)
            creatives = sorted(
                {
                    str(row.get("creative_name") or "").strip()
                    for row in source
                    if str(row.get("creative_name") or "").strip()
                    and str(row.get("creative_name") or "").strip() != "Не указан в источнике"
                }
            )
            preview = CampaignPreview(
                campaign_id=_opaque_id("campaign", name),
                campaign_name=name,
                segments=tuple(sorted({str(row["segment"]) for row in source})),
                start_date=dates[0],
                end_date=dates[-1],
                active_days=len(dates),
                channels=tuple(sorted({str(row["channel"]) for row in source})),
                geographies=tuple(sorted({str(row["geo"]) for row in source})),
                creatives=tuple(creatives),
                source_rows_n=len(source),
                normalized_rows_n=len(source),
                daily_rows_n=len(daily),
                uploaded_budget_rub=source_budget,
                model_input_budget_rub=source_budget,
                unmodeled_budget_rub=0.0,
                daily_budget_rub=daily_budget,
            )
            preview.validate("campaign")
            previews.append(preview)
        totals = ValidationTotals(
            source_rows_n=sum(item.source_rows_n for item in previews),
            normalized_rows_n=sum(item.normalized_rows_n for item in previews),
            daily_rows_n=sum(item.daily_rows_n for item in previews),
            uploaded_budget_rub=sum(item.uploaded_budget_rub for item in previews),
            model_input_budget_rub=sum(item.model_input_budget_rub for item in previews),
            unmodeled_budget_rub=0.0,
            daily_budget_rub=sum(item.daily_budget_rub for item in previews),
            raw_to_normalized_abs_diff_rub=0.0,
            normalized_to_daily_abs_diff_rub=abs(
                sum(item.model_input_budget_rub for item in previews)
                - sum(item.daily_budget_rub for item in previews)
            ),
        )
        totals.validate("totals")
        return tuple(previews), totals

    @staticmethod
    def _validation_warnings(
        validation_rows: list[dict[str, str]],
        campaigns: tuple[CampaignPreview, ...],
    ) -> tuple[ValidationIssue, ...]:
        campaign_ids = {campaign.campaign_name: campaign.campaign_id for campaign in campaigns}
        warnings: list[ValidationIssue] = []
        for allowed_use, code, text in (
            ("caution", "MODEL_CAUTION_CELLS", "Часть связок разрешена только с повышенной осторожностью."),
            ("diagnostic", "MODEL_DIAGNOSTIC_CELLS", "Часть target-оценок доступна только как диагностика."),
        ):
            rows = [row for row in validation_rows if str(row.get("allowed_use") or "") == allowed_use]
            if not rows:
                continue
            cells = tuple(
                AffectedCell(
                    campaign_id=campaign_ids.get(str(row.get("campaign_name") or "")),
                    segment=str(row.get("segment") or ""),
                    geo=str(row.get("geo") or ""),
                    channel=str(row.get("channel") or ""),
                    target=str(row.get("target") or ""),
                )
                for row in rows
            )
            warnings.append(
                ValidationIssue(
                    code=code,
                    severity="warning",
                    display_text=f"{text} Затронуто строк проверки: {len(rows)}.",
                    scope="model",
                    recoverable=True,
                    affected_cells=cells,
                )
            )
        return tuple(warnings)

    def create_job(
        self,
        validation_id: str,
        idempotency_key: str,
        options: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        existing = self.state.find_job_by_idempotency(idempotency_key)
        if existing is not None:
            return existing, False
        validation = parse_lifecycle_contract(self.state.read_validation(validation_id))
        if not isinstance(validation, ValidationResultV1) or validation.status.code != "valid":
            raise ValueError("Only a valid validation can create a job")
        upload = parse_lifecycle_contract(self.state.read_upload(validation.upload_id))
        assert isinstance(upload, CampaignUploadV1)
        inputs = self.state.read_validation_inputs(validation_id)
        workflow = ArtifactIdentity(**inputs["workflow_config"])
        policies = PolicySelection(**inputs["policies"])
        sampling = self._sampling(options or {})
        model = validation.model
        assert model is not None and validation.normalized_plan is not None and validation.daily_flighting is not None
        now = _utc_now()
        job = DecisionJobV1(
            contract_name=DECISION_JOB_CONTRACT,
            schema_version=SCHEMA_VERSION,
            record_origin="application_runtime",
            job_id=_opaque_id("job", f"{validation_id}:{idempotency_key}"),
            idempotency_key=idempotency_key,
            job_type="forecast_optimizer_report",
            created_by_actor_id=upload.actor_id,
            upload_id=upload.upload_id,
            validation_id=validation_id,
            normalized_plan=validation.normalized_plan,
            daily_flighting=validation.daily_flighting,
            workflow_config=workflow,
            model_selector=ModelSelector(
                mode="registry_channel",
                registry_channel=model.registry_channel,
                package_id=model.package_id,
                expected_package_fingerprint=model.package_fingerprint,
            ),
            policies=policies,
            sampling=sampling,
            code_reference=self._code_reference(),
            status=LifecycleStatus("queued", "В очереди"),
            created_at_utc=now,
            queued_at_utc=now,
            started_at_utc=None,
            cancel_requested_at_utc=None,
            finished_at_utc=None,
            attempt_number=0,
            result_id=None,
            terminal_error_id=None,
        )
        job.validate()
        return self.job_submitter(job.to_dict())

    def _sampling(self, options: Mapping[str, Any]) -> SamplingProfile:
        requested = dict(options.get("sampling") or {})
        base = self.settings.default_sampling
        sampling = SamplingProfile(
            scenario6_attempt_budget=int(requested.get("scenario6_attempt_budget", base.scenario6_attempt_budget)),
            search_posterior_draws=int(requested.get("search_posterior_draws", base.search_posterior_draws)),
            final_posterior_draws=int(requested.get("final_posterior_draws", base.final_posterior_draws)),
            search_seed=int(requested.get("search_seed", base.search_seed)),
            final_seed=int(requested.get("final_seed", base.final_seed)),
        )
        sampling.validate("sampling")
        if sampling.scenario6_attempt_budget > 4096 or sampling.search_posterior_draws > 512 or sampling.final_posterior_draws > 2000:
            raise ValueError("Requested sampling profile exceeds local safety limits")
        return sampling

    def _code_reference(self) -> str:
        root = self.settings.project_root.resolve()
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        tracked_changes = subprocess.check_output(
            [
                "git",
                "status",
                "--porcelain",
                "--untracked-files=no",
                "--",
                *CALCULATION_SOURCE_PATHS,
            ],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if tracked_changes:
            raise ValueError("Tracked source changes must be committed before creating a real job")
        return f"git:{head}"
