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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from email.parser import BytesParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlsplit


WEB_APP_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT_ROOT = WEB_APP_DIR.parent
if str(WEB_APP_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_APP_DIR))

from adapters.result_overview_adapter import build_result_overview  # noqa: E402
from contracts.application_lifecycle_v1 import (  # noqa: E402
    CampaignUploadV1,
    DecisionJobV1,
    LifecycleContractValidationError,
    ValidationResultV1,
    parse_lifecycle_contract,
)
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


API_VERSION = "v1"
SERVER_VERSION = "0.1.0"
MAX_JSON_BYTES = 2 * 1024 * 1024
_JOB_PATH_RE = re.compile(
    r"^/api/v1/jobs/(?P<job_id>[a-z][a-z0-9_]*_[0-9a-f]{12,64})(?:/(?P<resource>progress|errors|result|overview|cancel))?$"
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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
    optimizer_policy_path: Path | None = None
    business_policy_path: Path | None = None
    timeout_seconds: float = 7200.0
    max_workers: int = 1
    max_upload_bytes: int = 50 * 1024 * 1024
    allowed_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )

    def validate(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_workers <= 0:
            raise ValueError("max_workers must be positive")
        if self.max_upload_bytes <= 0:
            raise ValueError("max_upload_bytes must be positive")
        for origin in self.allowed_origins:
            if not origin.startswith(("http://localhost:", "http://127.0.0.1:")):
                raise ValueError("HTTP Smoke v1 accepts localhost CORS origins only")


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

    def write_outcome(self, outcome: ExecutionOutcome) -> None:
        with self._lock:
            job_dir = self._job_dir(outcome.final_job.job_id)
            _write_json_atomic(job_dir / "job.json", outcome.final_job.to_dict())
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
                    "display_text": "Локальный backend не смог завершить фоновую обработку.",
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
    ) -> None:
        settings.validate()
        self.settings = settings
        self.state = LocalApiState(settings.state_root)
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

    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)

    def submit_job(self, payload: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        parsed = parse_lifecycle_contract(payload)
        if not isinstance(parsed, DecisionJobV1):
            raise LifecycleContractValidationError("POST /jobs requires decision_job_v1")
        if parsed.status.code != "queued":
            raise LifecycleContractValidationError("POST /jobs accepts only queued jobs")
        record, created = self.state.create_job(parsed, _json_sha256(payload))
        if created:
            cancel_event = threading.Event()
            with self._lock:
                self._cancel_events[parsed.job_id] = cancel_event
            self._executor.submit(self._execute, parsed, cancel_event)
        return record, created

    def _execute(self, job: DecisionJobV1, cancel_event: threading.Event) -> None:
        try:
            worker = self._worker_factory(job, cancel_event.is_set)
            outcome = worker.run(job)
            self.state.write_outcome(outcome)
            if outcome.succeeded:
                storage_prefix = f"optimizer-runs/{job.job_id}/attempt-{outcome.final_job.attempt_number:03d}"
                overview = self._overview_builder(
                    outcome.attempt_root / "optimizer_output",
                    job.job_id,
                    job.workflow_config.sha256,
                    storage_prefix,
                )
                self.state.write_overview(job.job_id, overview)
        except Exception:
            self.state.write_internal_error(job.job_id)
        finally:
            with self._lock:
                self._cancel_events.pop(job.job_id, None)

    def _default_worker_factory(
        self, job: DecisionJobV1, cancellation_probe: Callable[[], bool]
    ) -> ExecutionWorker:
        del job
        return ExecutionWorker(
            ExecutionWorkerSettings(
                runtime_root=self.settings.runtime_root,
                timeout_seconds=self.settings.timeout_seconds,
                project_root=self.settings.project_root,
                python_executable=self.settings.python_executable,
                registry_root=self.settings.registry_root,
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

        def _error(self, status: HTTPStatus, code: str, text: str) -> None:
            self._json(status, {"error": {"code": code, "display_text": text}})

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
                self._json(
                    HTTPStatus.ACCEPTED if accepted else HTTPStatus.CONFLICT,
                    {"job_id": match.group("job_id"), "cancellation_requested": accepted},
                )
                return
            self._error(HTTPStatus.NOT_FOUND, "ROUTE_NOT_FOUND", "Маршрут не найден.")

        def do_GET(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if path == "/health":
                self._json(
                    HTTPStatus.OK,
                    {
                        "status": "ok",
                        "service": "x5-mmm-http-smoke",
                        "version": SERVER_VERSION,
                        "mode": "local_development_only",
                        "capabilities": {
                            "job_execution": True,
                            "campaign_upload": application.campaign_service is not None,
                            "campaign_validation": application.campaign_service is not None,
                        },
                    },
                )
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
