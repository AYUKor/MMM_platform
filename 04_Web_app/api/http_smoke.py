"""Dependency-light local HTTP boundary for DecisionJob execution.

This module is a development smoke server, not a production deployment. It
keeps long MMM calculations outside request threads and exposes only versioned
lifecycle/result contracts plus hash-checked artifact downloads.
"""

from __future__ import annotations

import argparse
import email.policy
import hashlib
import json
import mimetypes
import os
import re
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from email.parser import BytesParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import parse_qs, urlsplit


WEB_APP_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT_ROOT = WEB_APP_DIR.parent
if str(WEB_APP_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_APP_DIR))

from adapters.result_overview_adapter import build_result_overview  # noqa: E402
from contracts.application_lifecycle_v1 import (  # noqa: E402
    APPLICATION_ERROR_CONTRACT,
    JOB_EVENT_CONTRACT,
    SCHEMA_VERSION,
    ApplicationErrorV1,
    CampaignUploadV1,
    DecisionJobV1,
    JobEventV1,
    LifecycleStatus,
    LifecycleContractValidationError,
    ValidationResultV1,
    parse_lifecycle_contract,
)
from contracts.product_api_v1 import (  # noqa: E402
    HTTP_ERROR_CATALOG,
    build_calculation_profile_payload,
    build_error_catalog_payload,
    load_openapi_document,
    validate_model_passport,
)
from contracts.mmm_fact_catalog_v1 import build_mmm_fact_catalog  # noqa: E402
from worker.execution_worker import (  # noqa: E402
    ExecutionOutcome,
    ExecutionWorker,
    ExecutionWorkerSettings,
    LocalArtifactStore,
    LocalWorkerJournal,
)
from services.local_campaign_service import (  # noqa: E402
    LocalCampaignService,
    LocalCampaignServiceSettings,
)
from services.campaign_template import (  # noqa: E402
    TEMPLATE_FILENAME,
    build_campaign_plan_template,
)
from services.product_api_service import paginate_jobs  # noqa: E402
from services.job_progress_view import (  # noqa: E402
    ProgressProjectionError,
    build_job_progress_view,
)
from services.job_result_view import (  # noqa: E402
    MEDIA_PLAN_CHANNEL_ERROR_TEXT,
    MEDIA_PLAN_DATE_ERROR_TEXT,
    MEDIA_PLAN_DUPLICATE_QUERY_ERROR_TEXT,
    MEDIA_PLAN_GEO_ERROR_TEXT,
    MEDIA_PLAN_PAGINATION_ERROR_TEXT,
    MEDIA_PLAN_SCENARIO_ERROR_TEXT,
    MEDIA_PLAN_UNKNOWN_QUERY_ERROR_TEXT,
    ResultProjectionStateError,
    ResultProjectionUnavailableError,
    SCENARIO_IDS,
    UnsupportedMediaPlanQuery,
    build_job_result_view,
    build_scenario_media_plan,
)


API_VERSION = "v1"
SERVER_VERSION = "0.4.0"
MAX_JSON_BYTES = 2 * 1024 * 1024
_JOB_PATH_RE = re.compile(
    r"^/api/v1/jobs/(?P<job_id>[a-z][a-z0-9_]*_[0-9a-f]{12,64})(?:/(?P<resource>progress|progress-view|errors|result|overview|result-view|media-plan|cancel))?$"
)
_ARTIFACT_PATH_RE = re.compile(
    r"^/api/v1/artifacts/(?P<artifact_id>[a-z][a-z0-9_]*_[0-9a-f]{12,64})/download$"
)
_UPLOAD_PATH_RE = re.compile(
    r"^/api/v1/uploads/(?P<upload_id>upload_[0-9a-f]{12,64})(?:/(?P<resource>validations))?$"
)
_VALIDATION_PATH_RE = re.compile(
    r"^/api/v1/validations/(?P<validation_id>validation_[0-9a-f]{12,64})(?:/(?P<resource>jobs))?$"
)
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")
_SCHEMA_PATH_RE = re.compile(
    r"^/api/v1/contracts/(?P<contract_name>[a-z0-9][a-z0-9-]{0,63})\.json$"
)
_CONTRACT_SCHEMA_FILES = {
    "application-lifecycle-v1": WEB_APP_DIR / "contracts" / "application_lifecycle_v1.schema.json",
    "decision-result-v1": WEB_APP_DIR / "contracts" / "decision_result_v1.schema.json",
    "result-overview-v1": WEB_APP_DIR / "contracts" / "result_overview_v1.schema.json",
    "product-api-v1": WEB_APP_DIR / "contracts" / "product_api_v1.schema.json",
    "job-progress-view-v1": WEB_APP_DIR / "contracts" / "job_progress_view_v1.schema.json",
    "job-result-view-v1": WEB_APP_DIR / "contracts" / "job_result_view_v1.schema.json",
    "scenario-media-plan-v1": WEB_APP_DIR / "contracts" / "scenario_media_plan_v1.schema.json",
    "mmm-fact-catalog-v1": WEB_APP_DIR / "contracts" / "mmm_fact_catalog_v1.schema.json",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _opaque_id(prefix: str, seed: str) -> str:
    return f"{prefix}_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:20]}"


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_child(root: Path, *parts: str) -> Path:
    resolved_root = root.expanduser().resolve()
    candidate = resolved_root.joinpath(*parts).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("Unsafe local API path") from exc
    return candidate


class JobRunner(Protocol):
    def run(self, job: DecisionJobV1) -> ExecutionOutcome: ...


WorkerFactory = Callable[[DecisionJobV1, Callable[[], bool]], JobRunner]
OverviewBuilder = Callable[[Path, str, str, str], Mapping[str, Any]]


@dataclass(frozen=True)
class HttpSmokeSettings:
    state_root: Path
    runtime_root: Path
    artifact_root: Path
    project_root: Path = DEFAULT_PROJECT_ROOT
    python_executable: Path = Path(sys.executable)
    registry_root: Path | None = None
    registry_channel: str = "preprod"
    expected_package_id: str | None = None
    model_verification_mode: str = "full_lineage"
    optimizer_policy_path: Path | None = None
    business_policy_path: Path | None = None
    timeout_seconds: float = 7200.0
    max_workers: int = 1
    max_upload_bytes: int = 50 * 1024 * 1024
    config_schema_version: str = "1.1.0"
    deployment_profile: str = "local_development"
    public_base_url: str | None = None
    access_control_mode: str = "local_only"
    retention_days: int = 30
    calculation_profile_label: str = "Стандартный расчет"
    allowed_origins: tuple[str, ...] = (
        "http://localhost:4173",
        "http://127.0.0.1:4173",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )

    def validate(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not self.calculation_profile_label.strip():
            raise ValueError("calculation_profile_label is required")
        if self.max_workers <= 0:
            raise ValueError("max_workers must be positive")
        if self.max_upload_bytes <= 0:
            raise ValueError("max_upload_bytes must be positive")
        if self.retention_days <= 0:
            raise ValueError("retention_days must be positive")
        if self.model_verification_mode not in {"full_lineage", "serving_bundle"}:
            raise ValueError("Unknown model_verification_mode")
        if self.deployment_profile not in {"local_development", "research_pilot"}:
            raise ValueError("Unknown deployment_profile")
        if not self.allowed_origins:
            raise ValueError("At least one explicit CORS origin is required")
        for origin in self.allowed_origins:
            parsed = urlsplit(origin)
            is_local = parsed.scheme == "http" and parsed.hostname in {
                "localhost",
                "127.0.0.1",
            }
            is_https = parsed.scheme == "https" and bool(parsed.hostname)
            if (
                "*" in origin
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("CORS origins must not contain paths, query strings or fragments")
            if self.deployment_profile == "local_development" and not is_local:
                raise ValueError("Local development accepts localhost CORS origins only")
            if self.deployment_profile == "research_pilot" and not (is_local or is_https):
                raise ValueError("Research pilot accepts only HTTPS or localhost CORS origins")
        if self.deployment_profile == "local_development":
            if self.access_control_mode != "local_only":
                raise ValueError("Local development requires access_control_mode=local_only")
            if self.public_base_url is not None:
                parsed_public = urlsplit(self.public_base_url)
                if parsed_public.hostname not in {"localhost", "127.0.0.1"}:
                    raise ValueError("Local public_base_url must remain on localhost")
        else:
            if self.access_control_mode not in {
                "reverse_proxy_basic_auth",
                "reverse_proxy_token",
            }:
                raise ValueError("Research pilot requires reverse-proxy access control")
            if not self.public_base_url:
                raise ValueError("Research pilot requires public_base_url")
            parsed_public = urlsplit(self.public_base_url)
            if (
                parsed_public.scheme != "https"
                or not parsed_public.hostname
                or parsed_public.username is not None
                or parsed_public.password is not None
                or parsed_public.path not in {"", "/"}
                or parsed_public.query
                or parsed_public.fragment
            ):
                raise ValueError("Research pilot public_base_url must be one HTTPS origin")
            public_origin = f"{parsed_public.scheme}://{parsed_public.netloc}"
            if public_origin not in self.allowed_origins:
                raise ValueError("Research public_base_url must be present in allowed_origins")


class LocalApiState:
    """Atomic file-backed development state for API resources and indices."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _job_dir(self, job_id: str) -> Path:
        return _safe_child(self.root, "jobs", job_id)

    def _upload_dir(self, upload_id: str) -> Path:
        return _safe_child(self.root, "uploads", upload_id)

    def _validation_dir(self, validation_id: str) -> Path:
        return _safe_child(self.root, "validations", validation_id)

    def _create_indexed_record(
        self,
        *,
        index_name: str,
        idempotency_key: str,
        request_sha256: str,
        resource_id: str,
        record_path: Path,
        payload: Mapping[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        index_path = _safe_child(self.root, index_name)
        index = _read_json(index_path) if index_path.is_file() else {}
        existing = index.get(idempotency_key)
        if existing is not None:
            if existing["request_sha256"] != request_sha256:
                raise FileExistsError("Idempotency key already belongs to a different request")
            existing_path = _safe_child(self.root, *str(existing["record_path"]).split("/"))
            return _read_json(existing_path), False
        if record_path.exists():
            raise FileExistsError(f"Resource ID already exists: {resource_id}")
        _write_json_atomic(record_path, dict(payload))
        index[idempotency_key] = {
            "resource_id": resource_id,
            "request_sha256": request_sha256,
            "record_path": str(record_path.relative_to(self.root)),
        }
        _write_json_atomic(index_path, index)
        return dict(payload), True

    def create_upload(
        self,
        upload: CampaignUploadV1,
        idempotency_key: str,
        request_sha256: str,
    ) -> tuple[dict[str, Any], bool]:
        with self._lock:
            return self._create_indexed_record(
                index_name="upload_idempotency.json",
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
                resource_id=upload.upload_id,
                record_path=self._upload_dir(upload.upload_id) / "upload.json",
                payload=upload.to_dict(),
            )

    def write_upload(self, upload: CampaignUploadV1) -> None:
        with self._lock:
            _write_json_atomic(self._upload_dir(upload.upload_id) / "upload.json", upload.to_dict())

    def read_upload(self, upload_id: str) -> dict[str, Any]:
        path = self._upload_dir(upload_id) / "upload.json"
        if not path.is_file():
            raise FileNotFoundError(upload_id)
        return _read_json(path)

    def list_uploads(self) -> tuple[dict[str, Any], ...]:
        root = _safe_child(self.root, "uploads")
        if not root.is_dir():
            return ()
        return tuple(_read_json(path) for path in sorted(root.glob("*/upload.json")))

    def create_validation(
        self,
        validation: ValidationResultV1,
        idempotency_key: str,
        request_sha256: str,
    ) -> tuple[dict[str, Any], bool]:
        with self._lock:
            return self._create_indexed_record(
                index_name="validation_idempotency.json",
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
                resource_id=validation.validation_id,
                record_path=self._validation_dir(validation.validation_id) / "validation.json",
                payload=validation.to_dict(),
            )

    def write_validation(self, validation: ValidationResultV1) -> None:
        with self._lock:
            _write_json_atomic(
                self._validation_dir(validation.validation_id) / "validation.json",
                validation.to_dict(),
            )

    def read_validation(self, validation_id: str) -> dict[str, Any]:
        path = self._validation_dir(validation_id) / "validation.json"
        if not path.is_file():
            raise FileNotFoundError(validation_id)
        return _read_json(path)

    def list_validations(self) -> tuple[dict[str, Any], ...]:
        root = _safe_child(self.root, "validations")
        if not root.is_dir():
            return ()
        return tuple(
            _read_json(path) for path in sorted(root.glob("*/validation.json"))
        )

    def write_validation_inputs(self, validation_id: str, payload: Mapping[str, Any]) -> None:
        with self._lock:
            _write_json_atomic(
                self._validation_dir(validation_id) / "job_inputs.json",
                dict(payload),
            )

    def read_validation_inputs(self, validation_id: str) -> dict[str, Any]:
        path = self._validation_dir(validation_id) / "job_inputs.json"
        if not path.is_file():
            raise FileNotFoundError(f"{validation_id}/job_inputs")
        return _read_json(path)

    def find_job_by_idempotency(self, idempotency_key: str) -> dict[str, Any] | None:
        with self._lock:
            index_path = _safe_child(self.root, "idempotency.json")
            index = _read_json(index_path) if index_path.is_file() else {}
            existing = index.get(idempotency_key)
            return self.read_job(str(existing["job_id"])) if existing else None

    def create_job(self, job: DecisionJobV1, request_sha256: str) -> tuple[dict[str, Any], bool]:
        with self._lock:
            index_path = _safe_child(self.root, "idempotency.json")
            index = _read_json(index_path) if index_path.is_file() else {}
            existing = index.get(job.idempotency_key)
            if existing is not None:
                if existing["request_sha256"] != request_sha256:
                    raise FileExistsError("Idempotency key already belongs to a different request")
                return self.read_job(str(existing["job_id"])), False
            job_dir = self._job_dir(job.job_id)
            if job_dir.exists():
                raise FileExistsError("Job ID already exists")
            job_dir.mkdir(parents=True, exist_ok=False)
            _write_json_atomic(job_dir / "job.json", job.to_dict())
            _write_json_atomic(job_dir / "request.json", job.to_dict())
            index[job.idempotency_key] = {
                "job_id": job.job_id,
                "request_sha256": request_sha256,
            }
            _write_json_atomic(index_path, index)
            return job.to_dict(), True

    def write_outcome(
        self,
        outcome: ExecutionOutcome,
        *,
        overview: Mapping[str, Any] | None = None,
    ) -> None:
        with self._lock:
            job_dir = self._job_dir(outcome.final_job.job_id)
            _write_json_atomic(
                job_dir / "job_events.json",
                [event.to_dict() for event in outcome.job_events],
            )
            _write_json_atomic(
                job_dir / "progress.json",
                [event.to_dict() for event in outcome.progress_events],
            )
            _write_json_atomic(
                job_dir / "errors.json",
                [error.to_dict() for error in outcome.errors],
            )
            if outcome.decision_result is not None:
                payload = outcome.decision_result.to_dict()
                _write_json_atomic(job_dir / "result.json", payload)
                self._write_artifact_index(outcome, payload)
            if overview is not None:
                _write_json_atomic(job_dir / "overview.json", dict(overview))
            # Terminal state is the publication barrier: once the browser sees
            # succeeded, all completed-result resources already exist.
            _write_json_atomic(job_dir / "job.json", outcome.final_job.to_dict())

    def write_job(self, job: DecisionJobV1) -> None:
        with self._lock:
            _write_json_atomic(self._job_dir(job.job_id) / "job.json", job.to_dict())

    def append_resource(self, job_id: str, resource: str, payload: Mapping[str, Any]) -> None:
        filename = {
            "job_events": "job_events.json",
            "progress": "progress.json",
            "errors": "errors.json",
        }[resource]
        with self._lock:
            path = self._job_dir(job_id) / filename
            records = _read_json(path) if path.is_file() else []
            records.append(dict(payload))
            _write_json_atomic(path, records)

    def write_result(self, job_id: str, payload: Mapping[str, Any]) -> None:
        with self._lock:
            _write_json_atomic(self._job_dir(job_id) / "result.json", dict(payload))

    def write_overview(self, job_id: str, payload: Mapping[str, Any]) -> None:
        with self._lock:
            _write_json_atomic(self._job_dir(job_id) / "overview.json", dict(payload))

    def write_internal_error(self, job_id: str) -> None:
        with self._lock:
            path = self._job_dir(job_id) / "api_internal_error.json"
            _write_json_atomic(
                path,
                {
                    "code": "HTTP_SMOKE_BACKGROUND_FAILURE",
                    "display_text": "Не удалось завершить фоновую обработку.",
                },
            )

    def _write_artifact_index(self, outcome: ExecutionOutcome, result: Mapping[str, Any]) -> None:
        output_dir = outcome.attempt_root / "optimizer_output"
        entries: dict[str, Any] = {}
        for artifact in result.get("artifacts") or []:
            filename = Path(str(artifact["storage_key"])).name
            path = output_dir / filename
            if not path.is_file():
                continue
            entries[str(artifact["artifact_id"])] = {
                "relative_path": str(path.resolve().relative_to(outcome.attempt_root.parent.parent.resolve())),
                "sha256": str(artifact["sha256"]),
                "size_bytes": int(artifact["size_bytes"]),
                "media_type": str(artifact["media_type"]),
                "display_name": str(artifact["display_name"]),
            }
        _write_json_atomic(self._job_dir(outcome.final_job.job_id) / "artifacts.json", entries)

    def read_job(self, job_id: str) -> dict[str, Any]:
        path = self._job_dir(job_id) / "job.json"
        if not path.is_file():
            raise FileNotFoundError(job_id)
        return _read_json(path)

    def queue_snapshot(self, job_id: str) -> tuple[int | None, int]:
        """Return a one-based position among queued jobs without mutating state."""

        jobs_root = _safe_child(self.root, "jobs")
        if not jobs_root.is_dir():
            return None, 0
        with self._lock:
            queued = []
            for path in jobs_root.glob("*/job.json"):
                payload = _read_json(path)
                if ((payload.get("status") or {}).get("code")) == "queued":
                    queued.append(payload)
            queued.sort(
                key=lambda payload: (
                    str(payload.get("queued_at_utc") or ""),
                    str(payload.get("job_id") or ""),
                )
            )
            for index, payload in enumerate(queued, start=1):
                if payload.get("job_id") == job_id:
                    return index, len(queued)
            return None, len(queued)

    def list_jobs(self) -> list[dict[str, Any]]:
        jobs_root = _safe_child(self.root, "jobs")
        if not jobs_root.is_dir():
            return []
        records: list[dict[str, Any]] = []
        for path in jobs_root.glob("*/job.json"):
            if not path.is_file():
                continue
            job = _read_json(path)
            try:
                validation = self.read_validation(str(job["validation_id"]))
            except FileNotFoundError:
                validation = {}
            records.append(
                {
                    "job": job,
                    "campaigns": list(validation.get("campaigns") or []),
                }
            )
        return sorted(
            records,
            key=lambda record: str(record["job"].get("created_at_utc") or ""),
            reverse=True,
        )

    def recover_jobs_after_restart(
        self,
    ) -> tuple[tuple[DecisionJobV1, ...], tuple[str, ...]]:
        """Resume queued jobs and fail interrupted attempts with an auditable error."""

        queued: list[DecisionJobV1] = []
        interrupted: list[str] = []
        jobs_root = _safe_child(self.root, "jobs")
        if not jobs_root.is_dir():
            return (), ()
        with self._lock:
            for path in sorted(jobs_root.glob("*/job.json")):
                parsed = parse_lifecycle_contract(_read_json(path))
                if not isinstance(parsed, DecisionJobV1):
                    raise LifecycleContractValidationError(
                        f"Unexpected lifecycle record in job state: {path.name}"
                    )
                if parsed.status.code == "queued":
                    queued.append(parsed)
                    continue
                if parsed.status.code not in {"running", "cancel_requested"}:
                    continue
                self._fail_active_job_locked(
                    parsed,
                    code="LOCAL_BACKEND_RESTARTED",
                    component="worker",
                    category="infrastructure",
                    retryable=True,
                    display_text=(
                        "Сервис был перезапущен во время расчета. Запустите расчет "
                        "повторно со страницы проверенного плана."
                    ),
                    actor_type="system",
                    terminal_display_text="Расчет прерван перезапуском",
                )
                interrupted.append(parsed.job_id)
        return tuple(queued), tuple(interrupted)

    def fail_background_job(
        self,
        job_id: str,
        *,
        code: str,
        display_text: str,
    ) -> bool:
        """Make an unexpected API/background failure visible and terminal."""

        with self._lock:
            parsed = parse_lifecycle_contract(self.read_job(job_id))
            if not isinstance(parsed, DecisionJobV1):
                raise LifecycleContractValidationError("Job state is not decision_job_v1")
            if parsed.status.code in {"succeeded", "failed", "cancelled", "timed_out"}:
                return False
            self._fail_active_job_locked(
                parsed,
                code=code,
                component="api",
                category="internal",
                retryable=True,
                display_text=display_text,
                actor_type="system",
                terminal_display_text="Техническая ошибка сервиса",
            )
            return True

    def _fail_active_job_locked(
        self,
        job: DecisionJobV1,
        *,
        code: str,
        component: str,
        category: str,
        retryable: bool,
        display_text: str,
        actor_type: str,
        terminal_display_text: str,
    ) -> DecisionJobV1:
        job_dir = self._job_dir(job.job_id)
        event_path = job_dir / "job_events.json"
        events = _read_json(event_path) if event_path.is_file() else []
        sequence = max(
            (int(item.get("sequence") or 0) for item in events),
            default=0,
        ) + 1
        now = _utc_now()
        current = job
        if current.status.code == "queued":
            current = replace(
                current,
                status=LifecycleStatus("running", "Выполняется"),
                started_at_utc=now,
                attempt_number=1,
            )
            current.validate()
            started_event = JobEventV1(
                contract_name=JOB_EVENT_CONTRACT,
                schema_version=SCHEMA_VERSION,
                record_origin="application_runtime",
                event_id=_opaque_id("event", f"{job.job_id}:{code}:running:{now}"),
                job_id=job.job_id,
                sequence=sequence,
                attempt_number=current.attempt_number,
                emitted_at_utc=now,
                actor_type=actor_type,
                actor_id=None,
                from_status_code="queued",
                to_status=LifecycleStatus("running", "Выполняется"),
                reason_code=None,
                display_text="Задача передана на выполнение.",
            )
            started_event.validate()
            events.append(started_event.to_dict())
            sequence += 1
        error = ApplicationErrorV1(
            contract_name=APPLICATION_ERROR_CONTRACT,
            schema_version=SCHEMA_VERSION,
            record_origin="application_runtime",
            error_id=_opaque_id("error", f"{job.job_id}:{code}:{now}"),
            resource_type="job",
            resource_id=job.job_id,
            occurred_at_utc=now,
            component=component,
            stage=None,
            code=code,
            category=category,
            severity="error",
            retryable=retryable,
            display_text=display_text,
            support_reference=None,
        )
        error.validate()
        failed_event = JobEventV1(
            contract_name=JOB_EVENT_CONTRACT,
            schema_version=SCHEMA_VERSION,
            record_origin="application_runtime",
            event_id=_opaque_id("event", f"{job.job_id}:{code}:failed:{now}"),
            job_id=job.job_id,
            sequence=sequence,
            attempt_number=current.attempt_number,
            emitted_at_utc=now,
            actor_type=actor_type,
            actor_id=None,
            from_status_code=current.status.code,
            to_status=LifecycleStatus("failed", "Ошибка"),
            reason_code=code,
            display_text=display_text,
        )
        failed_event.validate()
        final_job = replace(
            current,
            status=LifecycleStatus("failed", terminal_display_text),
            finished_at_utc=now,
            terminal_error_id=error.error_id,
        )
        final_job.validate()
        errors_path = job_dir / "errors.json"
        errors = _read_json(errors_path) if errors_path.is_file() else []
        errors.append(error.to_dict())
        events.append(failed_event.to_dict())
        _write_json_atomic(errors_path, errors)
        _write_json_atomic(event_path, events)
        _write_json_atomic(job_dir / "job.json", final_job.to_dict())
        return final_job

    def read_resource(self, job_id: str, resource: str) -> Any:
        filename = {
            "progress": "progress.json",
            "errors": "errors.json",
            "result": "result.json",
            "overview": "overview.json",
        }[resource]
        path = self._job_dir(job_id) / filename
        if not path.is_file():
            raise FileNotFoundError(f"{job_id}/{resource}")
        return _read_json(path)

    def resolve_artifact(self, artifact_id: str, runtime_root: Path) -> tuple[Path, dict[str, Any]]:
        jobs_root = _safe_child(self.root, "jobs")
        for index_path in jobs_root.glob("*/artifacts.json") if jobs_root.is_dir() else ():
            index = _read_json(index_path)
            if artifact_id not in index:
                continue
            metadata = dict(index[artifact_id])
            path = _safe_child(runtime_root, *str(metadata["relative_path"]).split("/"))
            if (
                not path.is_file()
                or path.stat().st_size != int(metadata["size_bytes"])
                or _sha256(path) != str(metadata["sha256"])
            ):
                raise PermissionError("Artifact integrity check failed")
            return path, metadata
        raise FileNotFoundError(artifact_id)


class HttpSmokeApplication:
    """Thread-safe application service behind the local HTTP handler."""

    def __init__(
        self,
        settings: HttpSmokeSettings,
        *,
        worker_factory: WorkerFactory | None = None,
        overview_builder: OverviewBuilder | None = None,
        model_passport: Mapping[str, Any] | None = None,
    ) -> None:
        settings.validate()
        self.settings = settings
        settings.runtime_root.expanduser().resolve().mkdir(parents=True, exist_ok=True)
        settings.artifact_root.expanduser().resolve().mkdir(parents=True, exist_ok=True)
        self.state = LocalApiState(settings.state_root)
        self.model_passport = dict(model_passport) if model_passport is not None else None
        if self.model_passport is not None:
            validate_model_passport(self.model_passport)
        self._cancel_events: dict[str, threading.Event] = {}
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(
            max_workers=settings.max_workers,
            thread_name_prefix="mmm-worker",
        )
        self._worker_factory = worker_factory or self._default_worker_factory
        self._overview_builder = overview_builder or self._default_overview_builder
        self.campaign_service: LocalCampaignService | None = None
        if settings.expected_package_id:
            project_root = settings.project_root.expanduser().resolve()
            self.campaign_service = LocalCampaignService(
                LocalCampaignServiceSettings(
                    project_root=project_root,
                    artifact_root=settings.artifact_root.expanduser().resolve(),
                    validation_runtime_root=(settings.runtime_root / "validations").expanduser().resolve(),
                    registry_root=(
                        settings.registry_root
                        or project_root / "03_Outputs" / "01_PyMC_outputs" / "00_Model_registry"
                    ).expanduser().resolve(),
                    registry_channel=settings.registry_channel,
                    expected_package_id=settings.expected_package_id,
                    model_verification_mode=settings.model_verification_mode,
                    optimizer_policy_path=(
                        settings.optimizer_policy_path
                        or project_root / "02_Code" / "02_Budget_optimizer" / "optimizer_decision_policy_v2.yaml"
                    ).expanduser().resolve(),
                    business_policy_path=(
                        settings.business_policy_path
                        or project_root / "02_Code" / "02_Budget_optimizer" / "business_threshold_policy_v1.yaml"
                    ).expanduser().resolve(),
                    max_upload_bytes=settings.max_upload_bytes,
                ),
                self.state,
                self._executor,
                self.submit_job,
            )
        queued_jobs, interrupted_jobs = self.state.recover_jobs_after_restart()
        resource_recovery = (
            self.campaign_service.recover_pending_resources()
            if self.campaign_service is not None
            else {"uploads_resumed": 0, "validations_resumed": 0}
        )
        self.recovery_summary = {
            **resource_recovery,
            "queued_jobs_resumed": len(queued_jobs),
            "interrupted_jobs_failed": len(interrupted_jobs),
        }
        for job in queued_jobs:
            self._dispatch_job(job)

    def readiness(self) -> tuple[bool, dict[str, Any]]:
        """Return dependency readiness without exposing local filesystem paths."""

        checks = {
            "state_store": self.state.root.is_dir(),
            "runtime_store": self.settings.runtime_root.expanduser().resolve().is_dir(),
            "artifact_store": self.settings.artifact_root.expanduser().resolve().is_dir(),
            "campaign_service": self.campaign_service is not None,
            "model_passport": self.model_passport is not None,
        }
        ready = all(checks.values())
        package_id = None
        if self.model_passport is not None:
            package_id = str((self.model_passport.get("package") or {}).get("package_id") or "")
        payload = {
            "status": "ready" if ready else "not_ready",
            "service": "x5-mmm-product-api",
            "version": SERVER_VERSION,
            "deployment_profile": self.settings.deployment_profile,
            "checks": checks,
            "active_package_id": package_id or None,
        }
        return ready, payload

    def close(self) -> None:
        with self._lock:
            for event in self._cancel_events.values():
                event.set()
        self._executor.shutdown(wait=True, cancel_futures=False)

    def submit_job(self, payload: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        parsed = parse_lifecycle_contract(payload)
        if not isinstance(parsed, DecisionJobV1):
            raise LifecycleContractValidationError("POST /jobs requires decision_job_v1")
        if parsed.status.code != "queued":
            raise LifecycleContractValidationError("POST /jobs accepts only queued jobs")
        self._verify_job_validation(parsed)
        record, created = self.state.create_job(parsed, _json_sha256(payload))
        if created:
            self._dispatch_job(parsed)
        return record, created

    def _verify_job_validation(self, job: DecisionJobV1) -> None:
        """Prevent the technical job endpoint from bypassing campaign validation."""

        try:
            payload = self.state.read_validation(job.validation_id)
        except FileNotFoundError as exc:
            raise LifecycleContractValidationError(
                "Job references a validation that does not exist"
            ) from exc
        validation = parse_lifecycle_contract(payload)
        if (
            not isinstance(validation, ValidationResultV1)
            or validation.status.code != "valid"
            or not validation.job_creation_allowed
            or len(validation.campaigns) != 1
        ):
            raise LifecycleContractValidationError(
                "Job requires a valid one-campaign validation"
            )
        if validation.upload_id != job.upload_id:
            raise LifecycleContractValidationError(
                "Job upload_id does not match its validation"
            )
        if validation.normalized_plan is None or validation.daily_flighting is None:
            raise LifecycleContractValidationError(
                "Validated campaign artifacts are missing"
            )
        if (
            validation.normalized_plan.sha256 != job.normalized_plan.sha256
            or validation.daily_flighting.sha256 != job.daily_flighting.sha256
        ):
            raise LifecycleContractValidationError(
                "Job campaign artifacts do not match its validation"
            )

    def _dispatch_job(self, job: DecisionJobV1) -> None:
        cancel_event = threading.Event()
        with self._lock:
            if job.job_id in self._cancel_events:
                raise RuntimeError(f"Job is already dispatched: {job.job_id}")
            self._cancel_events[job.job_id] = cancel_event
        self._executor.submit(self._execute, job, cancel_event)

    def _execute(self, job: DecisionJobV1, cancel_event: threading.Event) -> None:
        try:
            worker = self._worker_factory(job, cancel_event.is_set)
            outcome = worker.run(job)
            overview: Mapping[str, Any] | None = None
            if outcome.succeeded:
                storage_prefix = f"optimizer-runs/{job.job_id}/attempt-{outcome.final_job.attempt_number:03d}"
                overview = self._overview_builder(
                    outcome.attempt_root / "optimizer_output",
                    job.job_id,
                    job.workflow_config.sha256,
                    storage_prefix,
                )
            self.state.write_outcome(outcome, overview=overview)
        except Exception:
            log_path = (
                self.settings.runtime_root
                / "api_internal_errors"
                / f"{job.job_id}.log"
            )
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(traceback.format_exc(), encoding="utf-8")
            self.state.fail_background_job(
                job.job_id,
                code="HTTP_BACKGROUND_FAILURE",
                display_text=(
                    "Не удалось завершить фоновую обработку. "
                    "Попробуйте повторить расчет после технической проверки."
                ),
            )
            self.state.write_internal_error(job.job_id)
        finally:
            with self._lock:
                self._cancel_events.pop(job.job_id, None)

    def _default_worker_factory(
        self, job: DecisionJobV1, cancellation_probe: Callable[[], bool]
    ) -> ExecutionWorker:
        return ExecutionWorker(
            ExecutionWorkerSettings(
                runtime_root=self.settings.runtime_root,
                timeout_seconds=self.settings.timeout_seconds,
                project_root=self.settings.project_root,
                python_executable=self.settings.python_executable,
                registry_root=self.settings.registry_root,
                model_verification_mode=self.settings.model_verification_mode,
            ),
            LocalArtifactStore(self.settings.artifact_root),
            journal_factory=lambda attempt_root: MirroredWorkerJournal(
                attempt_root,
                self.state,
                job.job_id,
            ),
            cancellation_probe=cancellation_probe,
        )

    @staticmethod
    def _default_overview_builder(
        output_dir: Path,
        job_id: str,
        workflow_config_sha256: str,
        storage_prefix: str,
    ) -> Mapping[str, Any]:
        return build_result_overview(
            output_dir,
            job_id=job_id,
            workflow_config_sha256=workflow_config_sha256,
            storage_prefix=storage_prefix,
        )

    def progress_view(self, job_id: str) -> dict[str, Any]:
        """Build one deterministic product snapshot for browser polling."""

        job = self.state.read_job(job_id)
        try:
            validation = self.state.read_validation(str(job["validation_id"]))
        except (KeyError, FileNotFoundError) as exc:
            raise ProgressProjectionError(
                "Job validation is unavailable"
            ) from exc

        def optional_resource(name: str, default: Any) -> Any:
            try:
                return self.state.read_resource(job_id, name)
            except FileNotFoundError:
                return default

        progress = optional_resource("progress", [])
        errors = optional_resource("errors", [])
        result = optional_resource("result", None)
        if not isinstance(progress, list) or not isinstance(errors, list):
            raise ProgressProjectionError("Progress resources have an invalid shape")
        if result is not None and not isinstance(result, Mapping):
            raise ProgressProjectionError("Result resource has an invalid shape")
        queue_position, queued_total = self.state.queue_snapshot(job_id)
        return build_job_progress_view(
            job_payload=job,
            validation_payload=validation,
            progress_payloads=progress,
            error_payloads=errors,
            result_payload=result,
            queue_position=queue_position,
            queued_jobs_total=queued_total,
        ).to_dict()

    def result_view(self, job_id: str) -> dict[str, Any]:
        """Build the browser result projection from published job resources."""

        job = self.state.read_job(job_id)
        result = self.state.read_resource(job_id, "result")
        overview = self.state.read_resource(job_id, "overview")
        if not isinstance(result, Mapping) or not isinstance(overview, Mapping):
            raise ResultProjectionStateError("Published result resources have an invalid shape")
        return build_job_result_view(
            job_id=job_id,
            job=job,
            result=result,
            overview=overview,
            artifact_resolver=lambda artifact_id: self.state.resolve_artifact(
                artifact_id,
                self.settings.runtime_root,
            ),
        )

    def media_plan(
        self,
        job_id: str,
        *,
        scenario_id: str,
        page: int,
        page_size: int,
        channel: str | None,
        geo: str | None,
        date: str | None,
    ) -> dict[str, Any]:
        """Build one paginated scenario media-plan projection."""

        job = self.state.read_job(job_id)
        result = self.state.read_resource(job_id, "result")
        overview = self.state.read_resource(job_id, "overview")
        if not isinstance(result, Mapping) or not isinstance(overview, Mapping):
            raise ResultProjectionStateError("Published result resources have an invalid shape")
        return build_scenario_media_plan(
            job_id=job_id,
            job=job,
            result=result,
            overview=overview,
            artifact_resolver=lambda artifact_id: self.state.resolve_artifact(
                artifact_id,
                self.settings.runtime_root,
            ),
            scenario_id=scenario_id,
            page=page,
            page_size=page_size,
            channel=channel,
            geo=geo,
            date=date,
        )

    def cancel(self, job_id: str) -> bool:
        self.state.read_job(job_id)
        with self._lock:
            event = self._cancel_events.get(job_id)
            if event is None:
                return False
            event.set()
            return True


class MirroredWorkerJournal:
    """Persist worker audit locally and mirror browser-safe state for polling."""

    def __init__(self, attempt_root: Path, state: LocalApiState, job_id: str) -> None:
        self.local = LocalWorkerJournal(attempt_root)
        self.state = state
        self.job_id = job_id

    def append_job_event(self, event: Any) -> None:
        self.local.append_job_event(event)
        self.state.append_resource(self.job_id, "job_events", event.to_dict())

    def append_progress(self, event: Any) -> None:
        self.local.append_progress(event)
        self.state.append_resource(self.job_id, "progress", event.to_dict())

    def append_error(self, error: Any) -> None:
        self.local.append_error(error)
        self.state.append_resource(self.job_id, "errors", error.to_dict())

    def write_job(self, job: DecisionJobV1) -> None:
        self.local.write_job(job)
        if job.status.code not in {"succeeded", "failed", "cancelled", "timed_out"}:
            self.state.write_job(job)

    def write_result(self, payload: Mapping[str, Any]) -> None:
        self.local.write_result(payload)
        self.state.write_result(self.job_id, payload)

    def write_worker_card(self, payload: Mapping[str, Any]) -> None:
        self.local.write_worker_card(payload)


def _multipart_file(content_type: str, body: bytes) -> tuple[str, bytes]:
    if not content_type.lower().startswith("multipart/form-data"):
        raise ValueError("multipart/form-data is required")
    message = BytesParser(policy=email.policy.default).parsebytes(
        b"MIME-Version: 1.0\r\n"
        + f"Content-Type: {content_type}\r\n\r\n".encode("utf-8")
        + body
    )
    files = [part for part in message.iter_attachments() if part.get_param("name", header="content-disposition") == "file"]
    if len(files) != 1:
        raise ValueError("Exactly one multipart field named 'file' is required")
    filename = files[0].get_filename() or ""
    content = files[0].get_payload(decode=True)
    if not isinstance(content, bytes):
        raise ValueError("Multipart file payload is invalid")
    return filename, content


def _local_actor_id() -> str:
    return "actor_" + hashlib.sha256(b"local-development-actor").hexdigest()[:20]


def _job_list_parameters(query: str) -> tuple[int, int, str | None]:
    parameters = parse_qs(query, keep_blank_values=True)
    unknown = set(parameters) - {"limit", "offset", "status"}
    if unknown:
        raise ValueError(f"Unsupported query parameters: {sorted(unknown)}")
    if any(len(values) != 1 for values in parameters.values()):
        raise ValueError("Each job-list query parameter may appear only once")
    try:
        limit = int(parameters.get("limit", ["50"])[0])
        offset = int(parameters.get("offset", ["0"])[0])
    except ValueError as exc:
        raise ValueError("limit and offset must be integers") from exc
    status = parameters.get("status", [None])[0]
    if status == "":
        raise ValueError("status must not be empty")
    return limit, offset, status


def _media_plan_parameters(
    query: str,
) -> tuple[str, int, int, str | None, str | None, str | None]:
    parameters = parse_qs(query, keep_blank_values=True)
    allowed = {"scenario_id", "page", "page_size", "channel", "geo", "date"}
    if set(parameters) - allowed:
        raise UnsupportedMediaPlanQuery(MEDIA_PLAN_UNKNOWN_QUERY_ERROR_TEXT)
    if any(len(values) != 1 for values in parameters.values()):
        raise UnsupportedMediaPlanQuery(MEDIA_PLAN_DUPLICATE_QUERY_ERROR_TEXT)
    scenario_id = parameters.get("scenario_id", [""])[0].strip()
    if scenario_id not in SCENARIO_IDS:
        raise UnsupportedMediaPlanQuery(MEDIA_PLAN_SCENARIO_ERROR_TEXT)
    try:
        page = int(parameters.get("page", ["1"])[0])
        page_size = int(parameters.get("page_size", ["100"])[0])
    except ValueError as exc:
        raise UnsupportedMediaPlanQuery(MEDIA_PLAN_PAGINATION_ERROR_TEXT) from exc
    if page < 1 or not 1 <= page_size <= 500:
        raise UnsupportedMediaPlanQuery(MEDIA_PLAN_PAGINATION_ERROR_TEXT)

    def optional_text(key: str, error_text: str) -> str | None:
        value = parameters.get(key, [None])[0]
        if value is None:
            return None
        value = value.strip()
        if not value or len(value) > 200:
            raise UnsupportedMediaPlanQuery(error_text)
        return value

    channel = optional_text("channel", MEDIA_PLAN_CHANNEL_ERROR_TEXT)
    geo = optional_text("geo", MEDIA_PLAN_GEO_ERROR_TEXT)
    date = optional_text("date", MEDIA_PLAN_DATE_ERROR_TEXT)
    if date is not None:
        raise UnsupportedMediaPlanQuery(MEDIA_PLAN_DATE_ERROR_TEXT)

    return (
        scenario_id,
        page,
        page_size,
        channel,
        geo,
        None,
    )


def make_handler(application: HttpSmokeApplication) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = f"X5MMMHTTP/{SERVER_VERSION}"

        def log_message(self, format: str, *args: Any) -> None:
            sys.stderr.write("http_smoke: " + (format % args) + "\n")

        def _origin(self) -> str | None:
            origin = self.headers.get("Origin")
            return origin if origin in application.settings.allowed_origins else None

        def _common_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            origin = self._origin()
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")

        def _json(self, status: HTTPStatus, payload: Any) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status.value)
            self._common_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _binary(
            self,
            status: HTTPStatus,
            body: bytes,
            *,
            media_type: str,
            filename: str,
        ) -> None:
            self.send_response(status.value)
            self._common_headers()
            self.send_header("Content-Type", media_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header(
                "Content-Disposition",
                f"attachment; filename={json.dumps(filename)}",
            )
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: HTTPStatus, code: str, text: str) -> None:
            catalog_entry = HTTP_ERROR_CATALOG.get(code)
            if catalog_entry is None:
                raise RuntimeError(f"HTTP error code is not registered: {code}")
            if int(catalog_entry["http_status"]) != status.value:
                raise RuntimeError(
                    f"HTTP error status mismatch for {code}: "
                    f"catalog={catalog_entry['http_status']}, actual={status.value}"
                )
            self._json(
                status,
                {
                    "error": {
                        "code": code,
                        "display_text": text or str(catalog_entry["display_text"]),
                        "retryable": bool(catalog_entry["retryable"]),
                        "user_action": str(catalog_entry["user_action"]),
                    }
                },
            )

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(HTTPStatus.NO_CONTENT.value)
            self._common_headers()
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Idempotency-Key")
            self.send_header("Access-Control-Max-Age", "600")
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if path == "/api/v1/uploads":
                if application.campaign_service is None:
                    self._error(HTTPStatus.SERVICE_UNAVAILABLE, "UPLOAD_SERVICE_DISABLED", "Upload service не настроен.")
                    return
                idempotency_key = self.headers.get("Idempotency-Key", "")
                if not _IDEMPOTENCY_RE.fullmatch(idempotency_key):
                    self._error(HTTPStatus.BAD_REQUEST, "IDEMPOTENCY_KEY_REQUIRED", "Нужен Idempotency-Key длиной не менее 16 символов.")
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = -1
                if length <= 0 or length > application.settings.max_upload_bytes + 1024 * 1024:
                    self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "INVALID_UPLOAD_SIZE", "Размер файла недопустим.")
                    return
                try:
                    filename, content = _multipart_file(
                        self.headers.get("Content-Type", ""),
                        self.rfile.read(length),
                    )
                    record, created = application.campaign_service.create_upload(
                        filename=filename,
                        content=content,
                        idempotency_key=idempotency_key,
                        actor_id=_local_actor_id(),
                    )
                except FileExistsError as exc:
                    self._error(HTTPStatus.CONFLICT, "IDEMPOTENCY_CONFLICT", str(exc))
                    return
                except ValueError as exc:
                    self._error(HTTPStatus.UNPROCESSABLE_ENTITY, "INVALID_UPLOAD", str(exc))
                    return
                self._json(HTTPStatus.ACCEPTED if created else HTTPStatus.OK, record)
                return

            upload_match = _UPLOAD_PATH_RE.fullmatch(path)
            if upload_match and upload_match.group("resource") == "validations":
                if application.campaign_service is None:
                    self._error(HTTPStatus.SERVICE_UNAVAILABLE, "UPLOAD_SERVICE_DISABLED", "Upload service не настроен.")
                    return
                idempotency_key = self.headers.get("Idempotency-Key", "")
                if not _IDEMPOTENCY_RE.fullmatch(idempotency_key):
                    self._error(HTTPStatus.BAD_REQUEST, "IDEMPOTENCY_KEY_REQUIRED", "Нужен Idempotency-Key длиной не менее 16 символов.")
                    return
                try:
                    record, created = application.campaign_service.request_validation(
                        upload_match.group("upload_id"),
                        idempotency_key,
                    )
                except FileNotFoundError:
                    self._error(HTTPStatus.NOT_FOUND, "UPLOAD_NOT_FOUND", "Загрузка не найдена.")
                    return
                except FileExistsError as exc:
                    self._error(HTTPStatus.CONFLICT, "IDEMPOTENCY_CONFLICT", str(exc))
                    return
                except ValueError as exc:
                    self._error(HTTPStatus.CONFLICT, "UPLOAD_NOT_READY", str(exc))
                    return
                self._json(HTTPStatus.ACCEPTED if created else HTTPStatus.OK, record)
                return

            validation_match = _VALIDATION_PATH_RE.fullmatch(path)
            if validation_match and validation_match.group("resource") == "jobs":
                if application.campaign_service is None:
                    self._error(HTTPStatus.SERVICE_UNAVAILABLE, "UPLOAD_SERVICE_DISABLED", "Upload service не настроен.")
                    return
                idempotency_key = self.headers.get("Idempotency-Key", "")
                if not _IDEMPOTENCY_RE.fullmatch(idempotency_key):
                    self._error(HTTPStatus.BAD_REQUEST, "IDEMPOTENCY_KEY_REQUIRED", "Нужен Idempotency-Key длиной не менее 16 символов.")
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    options = json.loads(self.rfile.read(length)) if length > 0 else {}
                    if not isinstance(options, dict):
                        raise ValueError("Job options must be a JSON object")
                    record, created = application.campaign_service.create_job(
                        validation_match.group("validation_id"),
                        idempotency_key,
                        options,
                    )
                except FileNotFoundError:
                    self._error(HTTPStatus.NOT_FOUND, "VALIDATION_NOT_FOUND", "Validation не найдена.")
                    return
                except (ValueError, LifecycleContractValidationError) as exc:
                    self._error(HTTPStatus.CONFLICT, "JOB_CREATION_BLOCKED", str(exc))
                    return
                self._json(HTTPStatus.ACCEPTED if created else HTTPStatus.OK, record)
                return

            if path == "/api/v1/jobs":
                content_type = self.headers.get("Content-Type", "")
                if not content_type.lower().startswith("application/json"):
                    self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "JSON_REQUIRED", "Ожидается JSON job contract.")
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = -1
                if length <= 0 or length > MAX_JSON_BYTES:
                    self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "INVALID_BODY_SIZE", "Размер job request недопустим.")
                    return
                try:
                    payload = json.loads(self.rfile.read(length))
                    if not isinstance(payload, dict):
                        raise ValueError("JSON object required")
                    record, created = application.submit_job(payload)
                except FileExistsError as exc:
                    self._error(HTTPStatus.CONFLICT, "IDEMPOTENCY_CONFLICT", str(exc))
                    return
                except (json.JSONDecodeError, ValueError, LifecycleContractValidationError) as exc:
                    self._error(HTTPStatus.UNPROCESSABLE_ENTITY, "INVALID_JOB", str(exc))
                    return
                self._json(HTTPStatus.ACCEPTED if created else HTTPStatus.OK, record)
                return

            match = _JOB_PATH_RE.fullmatch(path)
            if match and match.group("resource") == "cancel":
                try:
                    accepted = application.cancel(match.group("job_id"))
                except FileNotFoundError:
                    self._error(HTTPStatus.NOT_FOUND, "JOB_NOT_FOUND", "Задача не найдена.")
                    return
                if not accepted:
                    self._error(
                        HTTPStatus.CONFLICT,
                        "CANCELLATION_NOT_ACCEPTED",
                        "Расчет уже завершен или отмена больше не может быть принята.",
                    )
                    return
                self._json(
                    HTTPStatus.ACCEPTED,
                    {"job_id": match.group("job_id"), "cancellation_requested": True},
                )
                return
            self._error(HTTPStatus.NOT_FOUND, "ROUTE_NOT_FOUND", "Маршрут не найден.")

        def do_GET(self) -> None:  # noqa: N802
            request_url = urlsplit(self.path)
            path = request_url.path
            if path == "/health":
                self._json(
                    HTTPStatus.OK,
                    {
                        "status": "ok",
                        "service": "x5-mmm-product-api",
                        "version": SERVER_VERSION,
                        "mode": (
                            "local_development_only"
                            if application.settings.deployment_profile == "local_development"
                            else "research_pilot"
                        ),
                        "deployment_profile": application.settings.deployment_profile,
                        "capabilities": {
                            "job_execution": True,
                            "campaign_upload": application.campaign_service is not None,
                            "campaign_validation": application.campaign_service is not None,
                        },
                        "recovery": application.recovery_summary,
                    },
                )
                return
            if path == "/ready":
                ready, payload = application.readiness()
                self._json(HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE, payload)
                return
            if path == "/api/v1/openapi.json":
                self._json(HTTPStatus.OK, load_openapi_document())
                return
            if path == "/api/v1/templates/campaign-plan.xlsx":
                self._binary(
                    HTTPStatus.OK,
                    build_campaign_plan_template(),
                    media_type=(
                        "application/vnd.openxmlformats-officedocument."
                        "spreadsheetml.sheet"
                    ),
                    filename=TEMPLATE_FILENAME,
                )
                return
            schema_match = _SCHEMA_PATH_RE.fullmatch(path)
            if schema_match:
                schema_path = _CONTRACT_SCHEMA_FILES.get(schema_match.group("contract_name"))
                if schema_path is None or not schema_path.is_file():
                    self._error(
                        HTTPStatus.NOT_FOUND,
                        "SCHEMA_NOT_FOUND",
                        "Запрошенная JSON Schema не опубликована.",
                    )
                    return
                self._json(HTTPStatus.OK, _read_json(schema_path))
                return
            if path == "/api/v1/meta/errors":
                self._json(HTTPStatus.OK, build_error_catalog_payload())
                return
            if path == "/api/v1/meta/mmm-facts":
                self._json(HTTPStatus.OK, build_mmm_fact_catalog())
                return
            if path == "/api/v1/models/active":
                if application.model_passport is None:
                    self._error(
                        HTTPStatus.SERVICE_UNAVAILABLE,
                        "MODEL_PASSPORT_UNAVAILABLE",
                        "Паспорт активной модели временно недоступен.",
                    )
                    return
                self._json(HTTPStatus.OK, application.model_passport)
                return
            if path == "/api/v1/calculation-profile":
                if application.campaign_service is None:
                    self._error(
                        HTTPStatus.SERVICE_UNAVAILABLE,
                        "UPLOAD_SERVICE_DISABLED",
                        "Параметры расчета временно недоступны.",
                    )
                    return
                if application.model_passport is None:
                    self._error(
                        HTTPStatus.SERVICE_UNAVAILABLE,
                        "MODEL_PASSPORT_UNAVAILABLE",
                        "Сведения об активной модели временно недоступны.",
                    )
                    return
                serving = application.model_passport["serving"]
                self._json(
                    HTTPStatus.OK,
                    build_calculation_profile_payload(
                        scenario6_attempt_budget=(
                            application.campaign_service.settings.default_sampling.scenario6_attempt_budget
                        ),
                        profile_label=application.settings.calculation_profile_label,
                        model_version_label=str(serving["display_name"]),
                    ),
                )
                return
            if path == "/api/v1/jobs":
                jobs = application.state.list_jobs()
                try:
                    limit, offset, status = _job_list_parameters(request_url.query)
                    listing = paginate_jobs(
                        jobs,
                        limit=limit,
                        offset=offset,
                        status=status,
                    )
                except ValueError as exc:
                    self._error(HTTPStatus.BAD_REQUEST, "INVALID_QUERY", str(exc))
                    return
                self._json(HTTPStatus.OK, listing)
                return
            upload_match = _UPLOAD_PATH_RE.fullmatch(path)
            if upload_match and upload_match.group("resource") is None:
                try:
                    payload = application.state.read_upload(upload_match.group("upload_id"))
                except FileNotFoundError:
                    self._error(HTTPStatus.NOT_FOUND, "UPLOAD_NOT_FOUND", "Загрузка не найдена.")
                    return
                self._json(HTTPStatus.OK, payload)
                return
            validation_match = _VALIDATION_PATH_RE.fullmatch(path)
            if validation_match and validation_match.group("resource") is None:
                try:
                    payload = application.state.read_validation(validation_match.group("validation_id"))
                except FileNotFoundError:
                    self._error(HTTPStatus.NOT_FOUND, "VALIDATION_NOT_FOUND", "Validation не найдена.")
                    return
                self._json(HTTPStatus.OK, payload)
                return
            artifact_match = _ARTIFACT_PATH_RE.fullmatch(path)
            if artifact_match:
                try:
                    file_path, metadata = application.state.resolve_artifact(
                        artifact_match.group("artifact_id"),
                        application.settings.runtime_root,
                    )
                except FileNotFoundError:
                    self._error(HTTPStatus.NOT_FOUND, "ARTIFACT_NOT_FOUND", "Артефакт не найден.")
                    return
                except PermissionError:
                    self._error(HTTPStatus.CONFLICT, "ARTIFACT_INTEGRITY_FAILED", "Целостность артефакта не подтверждена.")
                    return
                self.send_response(HTTPStatus.OK.value)
                self._common_headers()
                self.send_header(
                    "Content-Type",
                    metadata.get("media_type") or mimetypes.guess_type(file_path.name)[0] or "application/octet-stream",
                )
                self.send_header("Content-Length", str(file_path.stat().st_size))
                self.send_header(
                    "Content-Disposition",
                    f"attachment; filename={json.dumps(file_path.name)}",
                )
                self.end_headers()
                with file_path.open("rb") as handle:
                    while chunk := handle.read(1024 * 1024):
                        self.wfile.write(chunk)
                return
            match = _JOB_PATH_RE.fullmatch(path)
            if match:
                job_id = match.group("job_id")
                resource = match.group("resource")
                if resource in {"result-view", "media-plan"}:
                    try:
                        application.state.read_job(job_id)
                    except FileNotFoundError:
                        self._error(
                            HTTPStatus.NOT_FOUND,
                            "JOB_NOT_FOUND",
                            "Расчет не найден.",
                        )
                        return
                    if resource == "result-view" and request_url.query:
                        self._error(
                            HTTPStatus.BAD_REQUEST,
                            "INVALID_QUERY",
                            "Этот запрос не поддерживает параметры.",
                        )
                        return
                    try:
                        if resource == "result-view":
                            payload = application.result_view(job_id)
                        else:
                            (
                                scenario_id,
                                page,
                                page_size,
                                channel,
                                geo,
                                date,
                            ) = _media_plan_parameters(request_url.query)
                            payload = application.media_plan(
                                job_id,
                                scenario_id=scenario_id,
                                page=page,
                                page_size=page_size,
                                channel=channel,
                                geo=geo,
                                date=date,
                            )
                    except FileNotFoundError:
                        self._error(
                            HTTPStatus.NOT_FOUND,
                            "RESOURCE_NOT_READY",
                            "Результат еще не готов.",
                        )
                        return
                    except UnsupportedMediaPlanQuery as exc:
                        self._error(
                            HTTPStatus.UNPROCESSABLE_ENTITY,
                            "MEDIA_PLAN_QUERY_UNSUPPORTED",
                            str(exc),
                        )
                        return
                    except ResultProjectionStateError:
                        self._error(
                            HTTPStatus.CONFLICT,
                            "RESULT_VIEW_INCONSISTENT",
                            "Опубликованные данные результата не согласованы между собой.",
                        )
                        return
                    except ResultProjectionUnavailableError:
                        code = (
                            "MEDIA_PLAN_VIEW_UNAVAILABLE"
                            if resource == "media-plan"
                            else "RESULT_VIEW_UNAVAILABLE"
                        )
                        text = (
                            "Медиаплан временно недоступен."
                            if resource == "media-plan"
                            else "Представление результата временно недоступно."
                        )
                        self._error(HTTPStatus.SERVICE_UNAVAILABLE, code, text)
                        return
                    except Exception:
                        code = (
                            "MEDIA_PLAN_VIEW_UNAVAILABLE"
                            if resource == "media-plan"
                            else "RESULT_VIEW_UNAVAILABLE"
                        )
                        text = (
                            "Медиаплан временно недоступен."
                            if resource == "media-plan"
                            else "Представление результата временно недоступно."
                        )
                        self._error(HTTPStatus.SERVICE_UNAVAILABLE, code, text)
                        return
                    self._json(HTTPStatus.OK, payload)
                    return
                if resource == "progress-view":
                    try:
                        payload = application.progress_view(job_id)
                    except FileNotFoundError:
                        self._error(
                            HTTPStatus.NOT_FOUND,
                            "JOB_NOT_FOUND",
                            "Расчет не найден.",
                        )
                        return
                    except ProgressProjectionError:
                        self._error(
                            HTTPStatus.CONFLICT,
                            "PROGRESS_STATE_INCONSISTENT",
                            "Не удалось согласовать состояние расчета. Обновите страницу.",
                        )
                        return
                    except Exception:
                        self._error(
                            HTTPStatus.SERVICE_UNAVAILABLE,
                            "PROGRESS_VIEW_UNAVAILABLE",
                            "Сведения о ходе расчета временно недоступны.",
                        )
                        return
                    self._json(HTTPStatus.OK, payload)
                    return
                try:
                    payload = (
                        application.state.read_job(job_id)
                        if resource is None
                        else application.state.read_resource(job_id, resource)
                    )
                except FileNotFoundError:
                    code = "JOB_NOT_FOUND" if resource is None else "RESOURCE_NOT_READY"
                    self._error(HTTPStatus.NOT_FOUND, code, "Ресурс не найден или еще не готов.")
                    return
                self._json(HTTPStatus.OK, payload)
                return
            self._error(HTTPStatus.NOT_FOUND, "ROUTE_NOT_FOUND", "Маршрут не найден.")

    return Handler


def serve(application: HttpSmokeApplication, host: str, port: int) -> None:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("HTTP Smoke v1 may bind only to localhost")
    server = ThreadingHTTPServer((host, port), make_handler(application))
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
        application.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument("--registry-root", type=Path)
    parser.add_argument("--registry-channel", default="preprod")
    parser.add_argument("--expected-package-id")
    parser.add_argument("--optimizer-policy-path", type=Path)
    parser.add_argument("--business-policy-path", type=Path)
    parser.add_argument("--python-executable", type=Path, default=Path(sys.executable))
    parser.add_argument("--timeout-seconds", type=float, default=7200.0)
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    application = HttpSmokeApplication(
        HttpSmokeSettings(
            state_root=args.state_root,
            runtime_root=args.runtime_root,
            artifact_root=args.artifact_root,
            project_root=args.project_root,
            python_executable=args.python_executable,
            registry_root=args.registry_root,
            registry_channel=args.registry_channel,
            expected_package_id=args.expected_package_id,
            optimizer_policy_path=args.optimizer_policy_path,
            business_policy_path=args.business_policy_path,
            timeout_seconds=args.timeout_seconds,
            max_workers=args.max_workers,
        )
    )
    print(
        json.dumps(
            {
                "status": "starting",
                "url": f"http://{args.host}:{args.port}",
                "mode": "local_development_only",
                "pid": os.getpid(),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    serve(application, args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
