"""Local execution worker for immutable forecast and optimizer jobs.

The worker owns orchestration only. It verifies immutable job inputs, resolves
the pinned model package and policies, launches the existing optimizer CLI in
an isolated process, translates its JSON stdout into lifecycle progress, and
adapts completed artifacts into DecisionResult v1. It does not implement MMM
or optimizer mathematics and it is not an HTTP, queue, or database service.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


WEB_APP_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT_ROOT = WEB_APP_DIR.parent
if str(WEB_APP_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_APP_DIR))

from contracts.application_lifecycle_v1 import (  # noqa: E402
    APPLICATION_ERROR_CONTRACT,
    JOB_EVENT_CONTRACT,
    PROGRESS_EVENT_CONTRACT,
    SCHEMA_VERSION,
    ApplicationErrorV1,
    ArtifactIdentity,
    DecisionJobV1,
    JobEventV1,
    LifecycleContractValidationError,
    LifecycleStatus,
    ProgressCounter,
    ProgressEventV1,
    parse_lifecycle_contract,
)


WORKER_VERSION = "1.0.0"
WORKER_CARD_NAME = "local_execution_worker_run_card_v1.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _opaque_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(payload), ensure_ascii=False) + "\n")
        handle.flush()


def _safe_child(root: Path, *parts: str) -> Path:
    resolved_root = root.expanduser().resolve()
    candidate = resolved_root.joinpath(*parts).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise WorkerFailure(
            code="UNSAFE_RUNTIME_PATH",
            component="storage",
            category="artifact_integrity",
            stage="prepare",
            retryable=False,
            display_text="Worker отклонил небезопасный путь к артефакту.",
        ) from exc
    return candidate


class WorkerFailure(RuntimeError):
    """A classified worker failure with browser-safe public semantics."""

    def __init__(
        self,
        *,
        code: str,
        component: str,
        category: str,
        stage: str | None,
        retryable: bool,
        display_text: str,
        terminal_status: str = "failed",
    ) -> None:
        super().__init__(display_text)
        self.code = code
        self.component = component
        self.category = category
        self.stage = stage
        self.retryable = retryable
        self.display_text = display_text
        self.terminal_status = terminal_status


@dataclass(frozen=True)
class VerifiedModel:
    package_id: str
    package_fingerprint: str
    run_dir: Path
    registry_channel: str
    registry_event_id: str
    gate_policy_version: str
    activation_status: str


class ArtifactResolver(Protocol):
    def resolve(self, identity: ArtifactIdentity) -> Path:
        """Return a local, hash-verified file for one artifact identity."""


class WorkerJournal(Protocol):
    def append_job_event(self, event: JobEventV1) -> None: ...

    def append_progress(self, event: ProgressEventV1) -> None: ...

    def append_error(self, error: ApplicationErrorV1) -> None: ...

    def write_job(self, job: DecisionJobV1) -> None: ...

    def write_result(self, payload: Mapping[str, Any]) -> None: ...

    def write_worker_card(self, payload: Mapping[str, Any]) -> None: ...


class LocalArtifactStore:
    """Development artifact resolver rooted at one local storage directory."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()

    def resolve(self, identity: ArtifactIdentity) -> Path:
        identity.validate("artifact")
        path = _safe_child(self.root, *identity.storage_key.split("/"))
        if not path.is_file():
            raise WorkerFailure(
                code="ARTIFACT_NOT_FOUND",
                component="storage",
                category="artifact_integrity",
                stage="prepare",
                retryable=False,
                display_text=f"Не найден обязательный артефакт {identity.display_name}.",
            )
        if path.stat().st_size != identity.size_bytes or _sha256(path) != identity.sha256:
            raise WorkerFailure(
                code="ARTIFACT_HASH_MISMATCH",
                component="storage",
                category="artifact_integrity",
                stage="prepare",
                retryable=False,
                display_text=f"Целостность артефакта {identity.display_name} не подтверждена.",
            )
        return path


class LocalWorkerJournal:
    """File-backed development journal implementing the future persistence port."""

    def __init__(self, attempt_root: Path | str) -> None:
        self.root = Path(attempt_root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def append_job_event(self, event: JobEventV1) -> None:
        event.validate()
        _append_jsonl(self.root / "job_events.jsonl", event.to_dict())

    def append_progress(self, event: ProgressEventV1) -> None:
        event.validate()
        _append_jsonl(self.root / "progress_events.jsonl", event.to_dict())

    def append_error(self, error: ApplicationErrorV1) -> None:
        error.validate()
        _append_jsonl(self.root / "application_errors.jsonl", error.to_dict())

    def write_job(self, job: DecisionJobV1) -> None:
        job.validate()
        _write_json_atomic(self.root / "decision_job_state.json", job.to_dict())

    def write_result(self, payload: Mapping[str, Any]) -> None:
        _write_json_atomic(self.root / "decision_result_manifest_v1.json", payload)

    def write_worker_card(self, payload: Mapping[str, Any]) -> None:
        _write_json_atomic(self.root / WORKER_CARD_NAME, payload)


@dataclass(frozen=True)
class ExecutionWorkerSettings:
    runtime_root: Path
    timeout_seconds: float | None
    project_root: Path = DEFAULT_PROJECT_ROOT
    python_executable: Path = Path(sys.executable)
    optimizer_cli: Path | None = None
    policy_dir: Path | None = None
    registry_root: Path | None = None
    terminate_grace_seconds: float = 10.0
    poll_seconds: float = 0.1
    next_sequence: int = 2
    result_storage_prefix: str = "optimizer-runs"

    def validate(self) -> None:
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive or None")
        if self.terminate_grace_seconds <= 0 or self.poll_seconds <= 0:
            raise ValueError("Worker polling and termination intervals must be positive")
        if self.next_sequence <= 0:
            raise ValueError("next_sequence must be positive")
        if Path(self.result_storage_prefix).is_absolute() or ".." in Path(
            self.result_storage_prefix
        ).parts:
            raise ValueError("result_storage_prefix must be a safe relative key")

    @property
    def resolved_project_root(self) -> Path:
        return self.project_root.expanduser().resolve()

    @property
    def resolved_optimizer_cli(self) -> Path:
        value = self.optimizer_cli or (
            self.resolved_project_root
            / "02_Code"
            / "02_Budget_optimizer"
            / "budget_optimizer.py"
        )
        return value.expanduser().resolve()

    @property
    def resolved_policy_dir(self) -> Path:
        value = self.policy_dir or (
            self.resolved_project_root / "02_Code" / "02_Budget_optimizer"
        )
        return value.expanduser().resolve()

    @property
    def resolved_registry_root(self) -> Path:
        value = self.registry_root or (
            self.resolved_project_root
            / "03_Outputs"
            / "01_PyMC_outputs"
            / "00_Model_registry"
        )
        return value.expanduser().resolve()


@dataclass(frozen=True)
class ExecutionOutcome:
    final_job: DecisionJobV1
    job_events: tuple[JobEventV1, ...]
    progress_events: tuple[ProgressEventV1, ...]
    errors: tuple[ApplicationErrorV1, ...]
    decision_result: Any | None
    attempt_root: Path
    process_return_code: int | None

    @property
    def succeeded(self) -> bool:
        return self.final_job.status.code == "succeeded"


@dataclass(frozen=True)
class _PreparedExecution:
    source_config_path: Path
    execution_config_path: Path
    output_dir: Path
    pinned_flighting_path: Path
    verified_model: VerifiedModel
    optimizer_policy_path: Path
    business_policy_path: Path


@dataclass(frozen=True)
class _ProcessOutcome:
    return_code: int
    cancelled: bool
    timed_out: bool


ModelVerifier = Callable[
    [DecisionJobV1, Mapping[str, Any], Path, ExecutionWorkerSettings], VerifiedModel
]
CodeVerifier = Callable[[str, Path], None]
ResultBuilder = Callable[[Path, str, str, str], Any]
CancellationProbe = Callable[[], bool]


class ExecutionWorker:
    """Execute one queued DecisionJob through the existing optimizer CLI."""

    def __init__(
        self,
        settings: ExecutionWorkerSettings,
        artifact_resolver: ArtifactResolver,
        *,
        journal_factory: Callable[[Path], WorkerJournal] = LocalWorkerJournal,
        model_verifier: ModelVerifier | None = None,
        code_verifier: CodeVerifier | None = None,
        result_builder: ResultBuilder | None = None,
        cancellation_probe: CancellationProbe | None = None,
    ) -> None:
        settings.validate()
        self.settings = settings
        self.artifact_resolver = artifact_resolver
        self.journal_factory = journal_factory
        self.model_verifier = model_verifier or _verify_model_package
        self.code_verifier = code_verifier or _verify_code_reference
        self.result_builder = result_builder or _build_decision_result
        self.cancellation_probe = cancellation_probe or (lambda: False)

        self._sequence = settings.next_sequence
        self._last_percent = 0.0
        self._job_events: list[JobEventV1] = []
        self._progress_events: list[ProgressEventV1] = []
        self._errors: list[ApplicationErrorV1] = []
        self._journal: WorkerJournal | None = None
        self._attempt_number = 0
        self._started_at = ""
        self._current_status: str | None = None
        self._cancel_requested_at: str | None = None
        self._campaign_positions: dict[str, tuple[float, float]] = {}

    def run(self, job_or_payload: DecisionJobV1 | Mapping[str, Any]) -> ExecutionOutcome:
        job = self._parse_job(job_or_payload)
        if job.status.code != "queued":
            raise LifecycleContractValidationError(
                "ExecutionWorker accepts only a queued DecisionJob"
            )
        self._attempt_number = job.attempt_number + 1
        attempt_root = _safe_child(
            self.settings.runtime_root,
            job.job_id,
            f"attempt_{self._attempt_number:03d}",
        )
        if attempt_root.exists():
            raise LifecycleContractValidationError(
                "Execution attempt directory already exists; refusing to overwrite audit evidence"
            )
        attempt_root.mkdir(parents=True, exist_ok=False)
        self._journal = self.journal_factory(attempt_root)
        execution_log = attempt_root / "protected_execution.log"
        self._started_at = _utc_now()
        self._current_status = "queued"
        running_job = replace(
            job,
            status=LifecycleStatus("running", "Расчет выполняется"),
            started_at_utc=self._started_at,
            attempt_number=self._attempt_number,
        )
        self._emit_job_event(
            job.job_id,
            from_status="queued",
            to_status="running",
            display_text="Worker начал проверку и расчет кампании",
        )
        self._journal.write_job(running_job)
        process_return_code: int | None = None
        prepared: _PreparedExecution | None = None

        try:
            self._emit_progress(
                job.job_id,
                stage="prepare",
                phase="immutable_input_check",
                state="started",
                display_text="Проверяются входные файлы, модель и правила расчета",
                percent=2.0,
            )
            prepared = self._prepare(job, attempt_root)
            self._emit_progress(
                job.job_id,
                stage="prepare",
                phase="immutable_input_check",
                state="completed",
                display_text="Входные файлы и версия модели подтверждены",
                percent=15.0,
            )
            process_outcome = self._run_optimizer_process(
                job,
                prepared.execution_config_path,
                execution_log,
            )
            process_return_code = process_outcome.return_code
            if process_outcome.cancelled:
                return self._finish_cancelled(
                    running_job,
                    attempt_root,
                    prepared,
                    process_return_code,
                )
            if process_outcome.timed_out:
                raise WorkerFailure(
                    code="CALCULATION_TIMEOUT",
                    component="worker",
                    category="timeout",
                    stage="final_scoring",
                    retryable=True,
                    display_text="Расчет превысил заданный лимит времени и был остановлен.",
                    terminal_status="timed_out",
                )
            if process_outcome.return_code != 0:
                raise WorkerFailure(
                    code="OPTIMIZER_PROCESS_FAILED",
                    component="optimizer",
                    category="calculation",
                    stage="scenario6",
                    retryable=False,
                    display_text=(
                        "Расчет не завершился. Подробности сохранены для технической поддержки."
                    ),
                )

            run_card = self._verify_completed_run(job, prepared)
            self._emit_progress(
                job.job_id,
                stage="report",
                phase="result_adapter",
                state="started",
                display_text="Проверяется отчет и собирается результат для интерфейса",
                percent=95.0,
            )
            storage_prefix = (
                f"{self.settings.result_storage_prefix}/{job.job_id}/"
                f"attempt-{self._attempt_number:03d}"
            )
            try:
                result = self.result_builder(
                    prepared.output_dir,
                    job.job_id,
                    job.workflow_config.sha256,
                    storage_prefix,
                )
                result.validate()
            except WorkerFailure:
                raise
            except Exception as exc:
                raise WorkerFailure(
                    code="DECISION_RESULT_BUILD_FAILED",
                    component="result_adapter",
                    category="artifact_integrity",
                    stage="report",
                    retryable=False,
                    display_text=(
                        "Готовые optimizer artifacts не удалось преобразовать в проверенный результат."
                    ),
                ) from exc
            self._verify_result_lineage(job, result)
            self._journal.write_result(result.to_dict())
            self._emit_progress(
                job.job_id,
                stage="report",
                phase="result_adapter",
                state="completed",
                display_text="Прогноз, рекомендация и Excel-отчет готовы",
                percent=100.0,
            )
            finished_at = _utc_now()
            final_job = replace(
                running_job,
                status=LifecycleStatus("succeeded", "Расчет завершен"),
                finished_at_utc=finished_at,
                result_id=result.result_id,
            )
            self._emit_job_event(
                job.job_id,
                from_status="running",
                to_status="succeeded",
                display_text="Результат и отчет сформированы",
            )
            self._journal.write_job(final_job)
            self._write_worker_card(
                job,
                final_job,
                prepared,
                process_return_code,
                result_id=result.result_id,
                run_id=str(run_card.get("run_id") or ""),
            )
            return self._outcome(
                final_job,
                result,
                attempt_root,
                process_return_code,
            )
        except WorkerFailure as failure:
            with execution_log.open("a", encoding="utf-8") as handle:
                handle.write("\n[worker_failure]\n")
                handle.write(traceback.format_exc())
            return self._finish_failed(
                running_job,
                failure,
                attempt_root,
                prepared,
                process_return_code,
            )
        except Exception as exc:  # fail closed; raw exception stays in protected log
            with execution_log.open("a", encoding="utf-8") as handle:
                handle.write("\n[unexpected_worker_failure]\n")
                handle.write(traceback.format_exc())
            failure = WorkerFailure(
                code="UNEXPECTED_WORKER_FAILURE",
                component="worker",
                category="internal",
                stage="prepare" if prepared is None else "report",
                retryable=False,
                display_text=(
                    "Worker столкнулся с внутренней ошибкой. Подробности доступны технической поддержке."
                ),
            )
            failure.__cause__ = exc
            return self._finish_failed(
                running_job,
                failure,
                attempt_root,
                prepared,
                process_return_code,
            )

    @staticmethod
    def _parse_job(job_or_payload: DecisionJobV1 | Mapping[str, Any]) -> DecisionJobV1:
        if isinstance(job_or_payload, DecisionJobV1):
            job = job_or_payload
            job.validate()
            return job
        parsed = parse_lifecycle_contract(job_or_payload)
        if not isinstance(parsed, DecisionJobV1):
            raise LifecycleContractValidationError("Worker input must be decision_job_v1")
        return parsed

    def _prepare(self, job: DecisionJobV1, attempt_root: Path) -> _PreparedExecution:
        normalized_path = self.artifact_resolver.resolve(job.normalized_plan)
        pinned_flighting_path = self.artifact_resolver.resolve(job.daily_flighting)
        source_config_path = self.artifact_resolver.resolve(job.workflow_config)
        source_config = _load_config(source_config_path, self.settings.resolved_project_root)
        _validate_source_config(job, source_config)
        self.code_verifier(job.code_reference, self.settings.resolved_project_root)
        verified_model = self.model_verifier(
            job,
            source_config,
            source_config_path,
            self.settings,
        )
        if verified_model.gate_policy_version != job.policies.gate_policy_version:
            raise WorkerFailure(
                code="GATE_POLICY_VERSION_MISMATCH",
                component="worker",
                category="model_policy",
                stage="prepare",
                retryable=False,
                display_text="Версия model gate policy не совпадает с зафиксированной в задаче.",
            )
        optimizer_policy_path = _resolve_policy_file(
            self.settings.resolved_policy_dir,
            expected_sha256=job.policies.optimizer_policy_sha256,
            expected_id=job.policies.optimizer_policy_id,
            id_field="policy_id",
            project_root=self.settings.resolved_project_root,
        )
        business_policy_path = _resolve_policy_file(
            self.settings.resolved_policy_dir,
            expected_sha256=job.policies.business_policy_sha256,
            expected_id=job.policies.business_policy_id,
            id_field="policy_id",
            project_root=self.settings.resolved_project_root,
        )
        business_policy = _load_config(
            business_policy_path,
            self.settings.resolved_project_root,
        )
        _validate_config_policy_references(
            source_config,
            optimizer_policy_path,
            business_policy_path,
        )
        business_mode = str((business_policy.get("decision") or {}).get("mode") or "")
        if business_mode != job.policies.business_decision_mode:
            raise WorkerFailure(
                code="BUSINESS_POLICY_MODE_MISMATCH",
                component="worker",
                category="model_policy",
                stage="prepare",
                retryable=False,
                display_text="Business policy не совпадает с режимом решения в задаче.",
            )

        inputs_dir = attempt_root / "inputs"
        inputs_dir.mkdir(parents=True, exist_ok=False)
        normalized_copy = inputs_dir / job.normalized_plan.display_name
        flighting_copy = inputs_dir / job.daily_flighting.display_name
        shutil.copy2(normalized_path, normalized_copy)
        shutil.copy2(pinned_flighting_path, flighting_copy)
        if _sha256(normalized_copy) != job.normalized_plan.sha256:
            raise WorkerFailure(
                code="INPUT_COPY_HASH_MISMATCH",
                component="storage",
                category="artifact_integrity",
                stage="prepare",
                retryable=True,
                display_text="Не удалось подготовить неизменную копию медиаплана для расчета.",
            )

        output_dir = attempt_root / "optimizer_output"
        execution_config = _materialize_execution_config(
            source_config,
            job,
            attempt_number=self._attempt_number,
            normalized_plan_path=normalized_copy,
            output_dir=output_dir,
            registry_root=self.settings.resolved_registry_root,
            optimizer_policy_path=optimizer_policy_path,
            business_policy_path=business_policy_path,
        )
        config_dir = attempt_root / "config"
        config_dir.mkdir(parents=True, exist_ok=False)
        execution_config_path = config_dir / "execution_config.json"
        _write_json_atomic(execution_config_path, execution_config)
        return _PreparedExecution(
            source_config_path=source_config_path,
            execution_config_path=execution_config_path,
            output_dir=output_dir,
            pinned_flighting_path=flighting_copy,
            verified_model=verified_model,
            optimizer_policy_path=optimizer_policy_path,
            business_policy_path=business_policy_path,
        )

    def _run_optimizer_process(
        self,
        job: DecisionJobV1,
        execution_config_path: Path,
        execution_log: Path,
    ) -> _ProcessOutcome:
        optimizer_cli = self.settings.resolved_optimizer_cli
        if not optimizer_cli.is_file():
            raise WorkerFailure(
                code="OPTIMIZER_CLI_NOT_FOUND",
                component="worker",
                category="infrastructure",
                stage="prepare",
                retryable=False,
                display_text="Исполняемый optimizer workflow не найден.",
            )
        command = [
            str(self.settings.python_executable),
            "-B",
            str(optimizer_cli),
            "--config",
            str(execution_config_path),
        ]
        environment = os.environ.copy()
        environment["PYTHONUNBUFFERED"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            process = subprocess.Popen(
                command,
                cwd=self.settings.resolved_project_root,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                start_new_session=True,
            )
        except OSError as exc:
            raise WorkerFailure(
                code="OPTIMIZER_PROCESS_START_FAILED",
                component="worker",
                category="infrastructure",
                stage="prepare",
                retryable=True,
                display_text="Worker не смог запустить процесс расчета.",
            ) from exc

        lines: queue.Queue[str | None] = queue.Queue()

        def _read_stdout() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                lines.put(line)
            lines.put(None)

        reader = threading.Thread(target=_read_stdout, name="optimizer-stdout", daemon=True)
        reader.start()
        started = time.monotonic()
        reader_done = False
        cancelled = False
        timed_out = False
        try:
            with execution_log.open("a", encoding="utf-8") as log_handle:
                log_handle.write("[optimizer_process_started]\n")
                while True:
                    reader_done = self._drain_process_lines(
                        job,
                        lines,
                        log_handle,
                        reader_done,
                    )
                    return_code = process.poll()
                    if return_code is not None and reader_done:
                        break
                    if return_code is None and self.cancellation_probe():
                        cancelled = True
                        self._emit_job_event(
                            job.job_id,
                            from_status="running",
                            to_status="cancel_requested",
                            display_text="Получен запрос на остановку расчета",
                            reason_code="USER_CANCELLATION_REQUESTED",
                        )
                        self._stop_process(process)
                    elif (
                        return_code is None
                        and self.settings.timeout_seconds is not None
                        and time.monotonic() - started >= self.settings.timeout_seconds
                    ):
                        timed_out = True
                        self._stop_process(process)
                    if cancelled or timed_out:
                        process.wait()
                        while not reader_done:
                            reader_done = self._drain_process_lines(
                                job,
                                lines,
                                log_handle,
                                reader_done,
                            )
                            if not reader_done:
                                time.sleep(self.settings.poll_seconds)
                        break
                    time.sleep(self.settings.poll_seconds)
                log_handle.write(
                    f"[optimizer_process_finished return_code={process.returncode}]\n"
                )
        finally:
            if process.poll() is None:
                self._stop_process(process)
            reader.join(timeout=self.settings.terminate_grace_seconds)
            if process.stdout is not None:
                process.stdout.close()
        return _ProcessOutcome(
            return_code=int(process.returncode if process.returncode is not None else -1),
            cancelled=cancelled,
            timed_out=timed_out,
        )

    def _drain_process_lines(
        self,
        job: DecisionJobV1,
        lines: queue.Queue[str | None],
        log_handle: Any,
        reader_done: bool,
    ) -> bool:
        while True:
            try:
                line = lines.get_nowait()
            except queue.Empty:
                return reader_done
            if line is None:
                reader_done = True
                continue
            log_handle.write(line)
            log_handle.flush()
            self._translate_progress_line(job, line)

    def _translate_progress_line(self, job: DecisionJobV1, line: str) -> None:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict):
            return
        event = payload.get("event")
        phase = str(payload.get("phase") or "")
        if event == "forecast_progress" and phase == "fit_scoring":
            current = _safe_counter(payload.get("fit_index"))
            total = _safe_counter(payload.get("fits_total"))
            percent = 20.0
            if current is not None and total:
                percent = 20.0 + 45.0 * current / total
            self._emit_progress(
                job.job_id,
                stage="forecast",
                phase="fit_scoring",
                state="running",
                display_text="Рассчитывается posterior-прогноз",
                percent=percent,
                counters=_counter_tuple("fits", current, total, "fits"),
            )
            return
        if event != "optimizer_progress":
            return

        campaign_name = str(payload.get("campaign") or "")
        campaign_index = _safe_counter(payload.get("campaign_index"))
        campaigns_total = _safe_counter(payload.get("campaigns_total"))
        if campaign_name and campaign_index is not None and campaigns_total:
            self._campaign_positions[campaign_name] = (campaign_index, campaigns_total)
        elif campaign_name in self._campaign_positions:
            campaign_index, campaigns_total = self._campaign_positions[campaign_name]
        campaign_counters = _counter_tuple(
            "campaigns",
            campaign_index,
            campaigns_total,
            "campaigns",
        )
        if phase == "candidate_generation":
            self._emit_progress(
                job.job_id,
                stage="benchmarks",
                phase=phase,
                state="running",
                display_text="Формируются базовые сценарии и допустимые перераспределения",
                percent=_campaign_phase_percent(
                    campaign_index,
                    campaigns_total,
                    phase_fraction=0.0,
                ),
                counters=campaign_counters,
            )
        elif phase == "adaptive_search_complete":
            attempts = _safe_counter(payload.get("search_attempts_evaluated_n"))
            attempt_budget = _safe_counter(payload.get("search_max_evaluations_n"))
            counters = list(campaign_counters)
            counters.extend(_counter_tuple("attempts", attempts, attempt_budget, "allocations"))
            self._emit_progress(
                job.job_id,
                stage="scenario6",
                phase=phase,
                state="running",
                display_text="Scenario 6 завершил поиск допустимых вариантов для кампании",
                percent=_campaign_phase_percent(
                    campaign_index,
                    campaigns_total,
                    phase_fraction=0.25,
                ),
                counters=tuple(counters),
            )
        elif phase == "search_scoring":
            candidates = _safe_counter(payload.get("candidates_to_score"))
            counters = list(campaign_counters)
            counters.extend(_counter_tuple("candidates", candidates, None, "allocations"))
            self._emit_progress(
                job.job_id,
                stage="forecast",
                phase=phase,
                state="running",
                display_text="MMM оценивает базовые сценарии и варианты Scenario 6",
                percent=_campaign_phase_percent(
                    campaign_index,
                    campaigns_total,
                    phase_fraction=0.5,
                ),
                counters=tuple(counters),
            )
        elif phase == "finalist_scoring_complete":
            finalists = _safe_counter(payload.get("finalists_scored"))
            counters = list(campaign_counters)
            counters.extend(_counter_tuple("finalists", finalists, None, "allocations"))
            self._emit_progress(
                job.job_id,
                stage="final_scoring",
                phase=phase,
                state="running",
                display_text="Финалисты пересчитаны на полном posterior-наборе",
                percent=_campaign_phase_percent(
                    campaign_index,
                    campaigns_total,
                    phase_fraction=1.0,
                ),
                counters=tuple(counters),
            )

    def _stop_process(self, process: subprocess.Popen[str]) -> None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            process.terminate()
        try:
            process.wait(timeout=self.settings.terminate_grace_seconds)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            process.kill()
        process.wait(timeout=self.settings.terminate_grace_seconds)

    def _verify_completed_run(
        self,
        job: DecisionJobV1,
        prepared: _PreparedExecution,
    ) -> dict[str, Any]:
        run_cards = sorted(prepared.output_dir.glob("*_optimizer_run_card.json"))
        if len(run_cards) != 1:
            raise WorkerFailure(
                code="OPTIMIZER_RUN_CARD_MISSING",
                component="optimizer",
                category="artifact_integrity",
                stage="report",
                retryable=False,
                display_text="Optimizer не сформировал однозначный run card.",
            )
        run_card = _read_json(run_cards[0])
        model_resolution = _read_json(prepared.output_dir / "model_resolution_optimizer.json")
        expected_pairs = {
            "flighting_sha256": (
                str(run_card.get("flighting_sha256") or ""),
                job.daily_flighting.sha256,
            ),
            "package_id": (
                str(model_resolution.get("package_id") or ""),
                job.model_selector.package_id or "",
            ),
            "package_fingerprint": (
                str(model_resolution.get("package_input_fingerprint") or ""),
                job.model_selector.expected_package_fingerprint or "",
            ),
            "optimizer_policy_sha256": (
                str(run_card.get("decision_policy_sha256") or ""),
                job.policies.optimizer_policy_sha256,
            ),
            "business_policy_sha256": (
                str((run_card.get("objective") or {}).get("business_threshold_policy_sha256") or ""),
                job.policies.business_policy_sha256,
            ),
        }
        mismatches = [name for name, (actual, expected) in expected_pairs.items() if actual != expected]
        sampling_pairs = {
            "search_candidates_per_campaign": (
                int(run_card.get("search_candidates_per_campaign") or 0),
                job.sampling.scenario6_attempt_budget,
            ),
            "search_samples": (
                int(run_card.get("search_samples") or 0),
                job.sampling.search_posterior_draws,
            ),
            "final_samples": (
                int(run_card.get("final_samples") or 0),
                job.sampling.final_posterior_draws,
            ),
            "search_seed": (
                int(run_card.get("search_seed") or run_card.get("seed") or -1),
                job.sampling.search_seed,
            ),
            "final_seed": (
                int(run_card.get("final_seed") or -1),
                job.sampling.final_seed,
            ),
        }
        mismatches.extend(
            name for name, (actual, expected) in sampling_pairs.items() if actual != expected
        )
        if mismatches:
            raise WorkerFailure(
                code="COMPLETED_RUN_LINEAGE_MISMATCH",
                component="result_adapter",
                category="artifact_integrity",
                stage="report",
                retryable=False,
                display_text=(
                    "Готовые артефакты не совпадают с зафиксированной задачей; результат отклонен."
                ),
            )
        return run_card

    @staticmethod
    def _verify_result_lineage(job: DecisionJobV1, result: Any) -> None:
        checks = {
            "job_id": (result.job.job_id, job.job_id),
            "workflow_config_sha256": (
                result.job.workflow_config_sha256,
                job.workflow_config.sha256,
            ),
            "flighting_sha256": (
                result.job.input_flighting_sha256,
                job.daily_flighting.sha256,
            ),
            "package_id": (result.model.package_id, job.model_selector.package_id),
            "package_fingerprint": (
                result.model.package_fingerprint,
                job.model_selector.expected_package_fingerprint,
            ),
            "optimizer_policy_sha256": (
                result.policies.optimizer_policy_sha256,
                job.policies.optimizer_policy_sha256,
            ),
            "business_policy_sha256": (
                result.policies.business_policy_sha256,
                job.policies.business_policy_sha256,
            ),
        }
        if any(actual != expected for actual, expected in checks.values()):
            raise WorkerFailure(
                code="DECISION_RESULT_LINEAGE_MISMATCH",
                component="result_adapter",
                category="artifact_integrity",
                stage="report",
                retryable=False,
                display_text="DecisionResult не прошел проверку lineage и не будет опубликован.",
            )

    def _finish_failed(
        self,
        running_job: DecisionJobV1,
        failure: WorkerFailure,
        attempt_root: Path,
        prepared: _PreparedExecution | None,
        process_return_code: int | None,
    ) -> ExecutionOutcome:
        error = ApplicationErrorV1(
            contract_name=APPLICATION_ERROR_CONTRACT,
            schema_version=SCHEMA_VERSION,
            record_origin="application_runtime",
            error_id=_opaque_id("error"),
            resource_type="job",
            resource_id=running_job.job_id,
            occurred_at_utc=_utc_now(),
            component=failure.component,
            stage=failure.stage,
            code=failure.code,
            category=failure.category,
            severity="error" if failure.terminal_status == "failed" else "fatal",
            retryable=failure.retryable,
            display_text=failure.display_text,
            support_reference=_opaque_id("support"),
        )
        error.validate()
        self._errors.append(error)
        assert self._journal is not None
        self._journal.append_error(error)
        finished_at = _utc_now()
        final_job = replace(
            running_job,
            status=LifecycleStatus(
                failure.terminal_status,
                "Превышен лимит времени"
                if failure.terminal_status == "timed_out"
                else "Расчет завершился ошибкой",
            ),
            finished_at_utc=finished_at,
            cancel_requested_at_utc=self._cancel_requested_at,
            terminal_error_id=error.error_id,
        )
        self._emit_job_event(
            running_job.job_id,
            from_status=self._current_status,
            to_status=failure.terminal_status,
            display_text=failure.display_text,
            reason_code=failure.code,
        )
        self._journal.write_job(final_job)
        self._write_worker_card(
            running_job,
            final_job,
            prepared,
            process_return_code,
            error_id=error.error_id,
        )
        return self._outcome(final_job, None, attempt_root, process_return_code)

    def _finish_cancelled(
        self,
        running_job: DecisionJobV1,
        attempt_root: Path,
        prepared: _PreparedExecution,
        process_return_code: int,
    ) -> ExecutionOutcome:
        cancel_time = self._cancel_requested_at or _utc_now()
        finished_at = _utc_now()
        final_job = replace(
            running_job,
            status=LifecycleStatus("cancelled", "Расчет отменен"),
            cancel_requested_at_utc=cancel_time,
            finished_at_utc=finished_at,
        )
        self._emit_job_event(
            running_job.job_id,
            from_status="cancel_requested",
            to_status="cancelled",
            display_text="Worker остановил расчет по запросу пользователя",
            reason_code="USER_CANCELLATION",
        )
        assert self._journal is not None
        self._journal.write_job(final_job)
        self._write_worker_card(
            running_job,
            final_job,
            prepared,
            process_return_code,
        )
        return self._outcome(final_job, None, attempt_root, process_return_code)

    def _emit_job_event(
        self,
        job_id: str,
        *,
        from_status: str | None,
        to_status: str,
        display_text: str,
        reason_code: str | None = None,
    ) -> None:
        if from_status != self._current_status:
            raise LifecycleContractValidationError(
                f"Worker transition expected from {self._current_status}, got {from_status}"
            )
        display_by_status = {
            "running": "Выполняется",
            "cancel_requested": "Запрошена отмена",
            "succeeded": "Завершено",
            "failed": "Ошибка",
            "timed_out": "Лимит времени превышен",
            "cancelled": "Отменено",
        }
        emitted_at = _utc_now()
        event = JobEventV1(
            contract_name=JOB_EVENT_CONTRACT,
            schema_version=SCHEMA_VERSION,
            record_origin="application_runtime",
            event_id=_opaque_id("event"),
            job_id=job_id,
            sequence=self._next_sequence(),
            attempt_number=self._attempt_number,
            emitted_at_utc=emitted_at,
            actor_type="worker",
            actor_id=None,
            from_status_code=from_status,
            to_status=LifecycleStatus(to_status, display_by_status[to_status]),
            reason_code=reason_code,
            display_text=display_text,
        )
        event.validate()
        self._job_events.append(event)
        assert self._journal is not None
        self._journal.append_job_event(event)
        self._current_status = to_status
        if to_status == "cancel_requested":
            self._cancel_requested_at = emitted_at

    def _emit_progress(
        self,
        job_id: str,
        *,
        stage: str,
        phase: str,
        state: str,
        display_text: str,
        percent: float,
        counters: tuple[ProgressCounter, ...] = (),
    ) -> None:
        percent = max(self._last_percent, min(100.0, float(percent)))
        self._last_percent = percent
        event = ProgressEventV1(
            contract_name=PROGRESS_EVENT_CONTRACT,
            schema_version=SCHEMA_VERSION,
            record_origin="application_runtime",
            progress_event_id=_opaque_id("progress"),
            job_id=job_id,
            sequence=self._next_sequence(),
            attempt_number=self._attempt_number,
            emitted_at_utc=_utc_now(),
            stage=stage,
            phase=phase,
            state=state,
            display_text=display_text,
            campaign_id=None,
            percent_complete=percent,
            counters=counters,
        )
        event.validate()
        self._progress_events.append(event)
        assert self._journal is not None
        self._journal.append_progress(event)

    def _next_sequence(self) -> int:
        value = self._sequence
        self._sequence += 1
        return value

    def _write_worker_card(
        self,
        source_job: DecisionJobV1,
        final_job: DecisionJobV1,
        prepared: _PreparedExecution | None,
        process_return_code: int | None,
        *,
        result_id: str | None = None,
        error_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        assert self._journal is not None
        self._journal.write_worker_card(
            {
                "card_name": "local_execution_worker_run_card_v1",
                "schema_version": "1.0.0",
                "worker_version": WORKER_VERSION,
                "job_id": source_job.job_id,
                "attempt_number": self._attempt_number,
                "status": final_job.status.code,
                "started_at_utc": self._started_at,
                "finished_at_utc": final_job.finished_at_utc,
                "source_workflow_config_sha256": source_job.workflow_config.sha256,
                "normalized_plan_sha256": source_job.normalized_plan.sha256,
                "daily_flighting_sha256": source_job.daily_flighting.sha256,
                "package_id": source_job.model_selector.package_id,
                "package_fingerprint": source_job.model_selector.expected_package_fingerprint,
                "optimizer_policy_sha256": source_job.policies.optimizer_policy_sha256,
                "business_policy_sha256": source_job.policies.business_policy_sha256,
                "process_return_code": process_return_code,
                "result_id": result_id,
                "terminal_error_id": error_id,
                "source_run_id": run_id,
                "execution_config_sha256": (
                    _sha256(prepared.execution_config_path) if prepared is not None else None
                ),
            }
        )

    def _outcome(
        self,
        final_job: DecisionJobV1,
        result: Any | None,
        attempt_root: Path,
        process_return_code: int | None,
    ) -> ExecutionOutcome:
        return ExecutionOutcome(
            final_job=final_job,
            job_events=tuple(self._job_events),
            progress_events=tuple(self._progress_events),
            errors=tuple(self._errors),
            decision_result=result,
            attempt_root=attempt_root,
            process_return_code=process_return_code,
        )


def _safe_counter(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _campaign_phase_percent(
    campaign_index: float | None,
    campaigns_total: float | None,
    *,
    phase_fraction: float,
) -> float:
    if campaign_index is None or not campaigns_total:
        return 20.0 + 70.0 * phase_fraction
    completed_equivalents = max(0.0, campaign_index - 1.0) + phase_fraction
    return 20.0 + 70.0 * min(1.0, completed_equivalents / campaigns_total)


def _counter_tuple(
    name: str,
    current: float | None,
    total: float | None,
    unit: str,
) -> tuple[ProgressCounter, ...]:
    if current is None:
        return ()
    if total is not None and current > total:
        total = None
    return (ProgressCounter(name=name, current=current, total=total, unit=unit),)


def _load_config(path: Path, project_root: Path) -> dict[str, Any]:
    pymc_code_dir = project_root / "02_Code" / "01_PyMC"
    if str(pymc_code_dir) not in sys.path:
        sys.path.insert(0, str(pymc_code_dir))
    try:
        from mmm_core.io import load_config

        value = load_config(path)
    except Exception as exc:
        raise WorkerFailure(
            code="WORKFLOW_CONFIG_INVALID",
            component="worker",
            category="input_validation",
            stage="prepare",
            retryable=False,
            display_text="Workflow config не удалось прочитать или разобрать.",
        ) from exc
    if not isinstance(value, dict):
        raise WorkerFailure(
            code="WORKFLOW_CONFIG_INVALID",
            component="worker",
            category="input_validation",
            stage="prepare",
            retryable=False,
            display_text="Workflow config должен содержать JSON/YAML object.",
        )
    return value


def _validate_source_config(job: DecisionJobV1, config: Mapping[str, Any]) -> None:
    if config.get("layer") not in {None, "budget_optimizer"}:
        raise WorkerFailure(
            code="WORKFLOW_LAYER_MISMATCH",
            component="worker",
            category="input_validation",
            stage="prepare",
            retryable=False,
            display_text="Workflow config относится не к budget optimizer.",
        )
    if config.get("campaign_adapter"):
        raise WorkerFailure(
            code="RAW_CAMPAIGN_ADAPTER_FORBIDDEN",
            component="worker",
            category="input_validation",
            stage="prepare",
            retryable=False,
            display_text=(
                "Execution job должен использовать уже нормализованный медиаплан, а не raw campaign adapter."
            ),
        )
    model_ref = config.get("model_ref") or {}
    if str(model_ref.get("source") or "registry") != "registry":
        raise WorkerFailure(
            code="UNSUPPORTED_MODEL_SELECTOR",
            component="worker",
            category="model_policy",
            stage="prepare",
            retryable=False,
            display_text="Worker v1 поддерживает только pinned package через model registry channel.",
        )
    if job.model_selector.mode != "registry_channel":
        raise WorkerFailure(
            code="UNSUPPORTED_MODEL_SELECTOR",
            component="worker",
            category="model_policy",
            stage="prepare",
            retryable=False,
            display_text="Worker v1 пока не исполняет explicit-package jobs.",
        )
    configured_channel = model_ref.get("channel")
    configured_package = model_ref.get("expected_package_id")
    if configured_channel not in {None, job.model_selector.registry_channel}:
        raise WorkerFailure(
            code="MODEL_CHANNEL_MISMATCH",
            component="worker",
            category="model_policy",
            stage="prepare",
            retryable=False,
            display_text="Registry channel в workflow config не совпадает с immutable job.",
        )
    if configured_package not in {None, job.model_selector.package_id}:
        raise WorkerFailure(
            code="MODEL_PACKAGE_MISMATCH",
            component="worker",
            category="model_policy",
            stage="prepare",
            retryable=False,
            display_text="Model package в workflow config не совпадает с immutable job.",
        )
    scenario6 = ((config.get("optimizer") or {}).get("scenario_6") or {})
    if scenario6.get("enabled") is False:
        raise WorkerFailure(
            code="SCENARIO6_DISABLED_FOR_COMPOSITE_JOB",
            component="worker",
            category="input_validation",
            stage="prepare",
            retryable=False,
            display_text="Полный forecast-optimizer job не может отключать Scenario 6.",
        )
    expected = {
        "search_candidates": job.sampling.scenario6_attempt_budget,
        "search_posterior_samples": job.sampling.search_posterior_draws,
        "final_posterior_samples": job.sampling.final_posterior_draws,
        "random_seed": job.sampling.search_seed,
        "final_random_seed": job.sampling.final_seed,
    }
    mismatches = [
        key
        for key, expected_value in expected.items()
        if scenario6.get(key) is not None and int(scenario6[key]) != expected_value
    ]
    if mismatches:
        raise WorkerFailure(
            code="SAMPLING_PROFILE_MISMATCH",
            component="worker",
            category="input_validation",
            stage="prepare",
            retryable=False,
            display_text="Draws, seeds или search budget не совпадают с immutable job.",
        )


def _verify_code_reference(code_reference: str, project_root: Path) -> None:
    if not code_reference.startswith("git:"):
        raise WorkerFailure(
            code="UNSUPPORTED_CODE_REFERENCE",
            component="worker",
            category="artifact_integrity",
            stage="prepare",
            retryable=False,
            display_text="Worker v1 ожидает code_reference в формате git:<commit>.",
        )
    expected = code_reference.split(":", 1)[1].strip()
    try:
        actual = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise WorkerFailure(
            code="CODE_REFERENCE_UNVERIFIED",
            component="worker",
            category="artifact_integrity",
            stage="prepare",
            retryable=False,
            display_text="Не удалось подтвердить версию кода для расчета.",
        ) from exc
    if not expected or not actual.startswith(expected):
        raise WorkerFailure(
            code="CODE_REFERENCE_MISMATCH",
            component="worker",
            category="artifact_integrity",
            stage="prepare",
            retryable=False,
            display_text="Текущая версия кода не совпадает с зафиксированной в задаче.",
        )


def _validate_config_policy_references(
    config: Mapping[str, Any],
    optimizer_policy_path: Path,
    business_policy_path: Path,
) -> None:
    references = {
        "optimizer": (
            config.get("decision_policy_file"),
            optimizer_policy_path.name,
        ),
        "business": (
            (config.get("objective") or {}).get("business_threshold_policy"),
            business_policy_path.name,
        ),
    }
    mismatches = [
        name
        for name, (configured, expected_name) in references.items()
        if configured is not None and Path(str(configured)).name != expected_name
    ]
    if mismatches:
        raise WorkerFailure(
            code="WORKFLOW_POLICY_REFERENCE_MISMATCH",
            component="worker",
            category="model_policy",
            stage="prepare",
            retryable=False,
            display_text="Policy reference в workflow config не совпадает с immutable job.",
        )


def _verify_model_package(
    job: DecisionJobV1,
    config: Mapping[str, Any],
    config_path: Path,
    settings: ExecutionWorkerSettings,
) -> VerifiedModel:
    del config, config_path
    pymc_code_dir = settings.resolved_project_root / "02_Code" / "01_PyMC"
    if str(pymc_code_dir) not in sys.path:
        sys.path.insert(0, str(pymc_code_dir))
    try:
        from mmm_core.model_registry import resolve_channel

        resolved = resolve_channel(
            str(job.model_selector.registry_channel),
            expected_package_id=job.model_selector.package_id,
            registry_root=settings.resolved_registry_root,
        )
        registration = resolved["registration"]
        run_dir = Path(registration["run_dir"]).expanduser().resolve()
        manifest_path = run_dir / "model_manifest.json"
        manifest = _read_json(manifest_path)
    except Exception as exc:
        raise WorkerFailure(
            code="MODEL_PACKAGE_VERIFICATION_FAILED",
            component="worker",
            category="model_policy",
            stage="prepare",
            retryable=False,
            display_text="Pinned model package не прошел registry integrity check.",
        ) from exc
    fingerprint = str(registration.get("package_input_fingerprint") or "")
    if fingerprint != job.model_selector.expected_package_fingerprint:
        raise WorkerFailure(
            code="MODEL_FINGERPRINT_MISMATCH",
            component="worker",
            category="model_policy",
            stage="prepare",
            retryable=False,
            display_text="Fingerprint model package изменился или не совпадает с задачей.",
        )
    return VerifiedModel(
        package_id=str(resolved.get("package_id") or ""),
        package_fingerprint=fingerprint,
        run_dir=run_dir,
        registry_channel=str(resolved.get("channel") or job.model_selector.registry_channel),
        registry_event_id=str(resolved.get("event_id") or ""),
        gate_policy_version=str(manifest.get("gate_policy_version") or ""),
        activation_status=str(manifest.get("activation_status") or ""),
    )


def _resolve_policy_file(
    policy_dir: Path,
    *,
    expected_sha256: str,
    expected_id: str,
    id_field: str,
    project_root: Path,
) -> Path:
    candidates = sorted(
        path
        for path in policy_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".yaml", ".yml", ".json"}
    )
    for path in candidates:
        if _sha256(path) != expected_sha256:
            continue
        payload = _load_config(path, project_root)
        if str(payload.get(id_field) or "") == expected_id:
            return path.resolve()
    raise WorkerFailure(
        code="POLICY_ARTIFACT_NOT_FOUND",
        component="worker",
        category="model_policy",
        stage="prepare",
        retryable=False,
        display_text="Не найден policy-файл с зафиксированными ID и SHA-256.",
    )


def _materialize_execution_config(
    source_config: Mapping[str, Any],
    job: DecisionJobV1,
    *,
    attempt_number: int,
    normalized_plan_path: Path,
    output_dir: Path,
    registry_root: Path,
    optimizer_policy_path: Path,
    business_policy_path: Path,
) -> dict[str, Any]:
    config = copy.deepcopy(dict(source_config))
    config["run_id"] = f"web_{job.job_id}_attempt_{attempt_number:03d}"
    config["layer"] = "budget_optimizer"
    config.pop("campaign_adapter", None)
    config["model_ref"] = {
        "source": "registry",
        "registry_root": str(registry_root),
        "channel": job.model_selector.registry_channel,
        "expected_package_id": job.model_selector.package_id,
    }
    paths = config.setdefault("paths", {})
    paths["campaign_input_dir"] = str(normalized_plan_path.parent)
    paths["campaign_file"] = normalized_plan_path.name
    paths["campaign_sheet"] = None
    paths["output_dir"] = str(output_dir)
    intermediate_dir = output_dir.parent / "campaign_intermediates"
    paths["validated_output_dir"] = str(intermediate_dir / "validated")
    paths["flighting_output_dir"] = str(intermediate_dir / "flighting")
    paths.pop("model_run_dir", None)
    paths.pop("model_artifacts_dir", None)
    paths.pop("model_ready_panel", None)
    config["decision_policy_file"] = str(optimizer_policy_path)
    objective = config.setdefault("objective", {})
    objective["business_threshold_policy"] = str(business_policy_path)
    validation = config.setdefault("validation", {})
    validation["fail_on_parse_issues"] = True
    validation["fail_on_unsupported"] = True
    scenario6 = config.setdefault("optimizer", {}).setdefault("scenario_6", {})
    scenario6.update(
        {
            "enabled": True,
            "search_candidates": job.sampling.scenario6_attempt_budget,
            "runtime_safety_max_candidates": max(
                int(scenario6.get("runtime_safety_max_candidates") or 0),
                job.sampling.scenario6_attempt_budget,
            ),
            "search_posterior_samples": job.sampling.search_posterior_draws,
            "final_posterior_samples": job.sampling.final_posterior_draws,
            "random_seed": job.sampling.search_seed,
            "final_random_seed": job.sampling.final_seed,
        }
    )
    config["worker_execution"] = {
        "worker_version": WORKER_VERSION,
        "job_id": job.job_id,
        "attempt_number": attempt_number,
        "source_workflow_config_sha256": job.workflow_config.sha256,
        "normalized_plan_sha256": job.normalized_plan.sha256,
        "pinned_daily_flighting_sha256": job.daily_flighting.sha256,
    }
    return config


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkerFailure(
            code="INVALID_JSON_ARTIFACT",
            component="result_adapter",
            category="artifact_integrity",
            stage="report",
            retryable=False,
            display_text="Технический JSON-артефакт отсутствует или поврежден.",
        ) from exc
    if not isinstance(payload, dict):
        raise WorkerFailure(
            code="INVALID_JSON_ARTIFACT",
            component="result_adapter",
            category="artifact_integrity",
            stage="report",
            retryable=False,
            display_text="Технический JSON-артефакт имеет неверный формат.",
        )
    return payload


def _build_decision_result(
    output_dir: Path,
    job_id: str,
    workflow_config_sha256: str,
    storage_prefix: str,
) -> Any:
    from adapters.optimizer_result_adapter import build_decision_result

    return build_decision_result(
        output_dir,
        storage_prefix=storage_prefix,
        job_id=job_id,
        workflow_config_sha256=workflow_config_sha256,
    )


def _cancel_file_probe(path: Path | None) -> CancellationProbe:
    if path is None:
        return lambda: False
    resolved = path.expanduser().resolve()
    return resolved.exists


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True, type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument("--registry-root", type=Path)
    parser.add_argument("--python-executable", type=Path, default=Path(sys.executable))
    parser.add_argument("--timeout-seconds", required=True, type=float)
    parser.add_argument("--cancel-file", type=Path)
    parser.add_argument("--next-sequence", type=int, default=2)
    args = parser.parse_args(argv)

    payload = json.loads(args.job.read_text(encoding="utf-8"))
    worker = ExecutionWorker(
        ExecutionWorkerSettings(
            runtime_root=args.runtime_root,
            timeout_seconds=args.timeout_seconds,
            project_root=args.project_root,
            python_executable=args.python_executable,
            registry_root=args.registry_root,
            next_sequence=args.next_sequence,
        ),
        LocalArtifactStore(args.artifact_root),
        cancellation_probe=_cancel_file_probe(args.cancel_file),
    )
    outcome = worker.run(payload)
    print(
        json.dumps(
            {
                "status": outcome.final_job.status.code,
                "job_id": outcome.final_job.job_id,
                "attempt_number": outcome.final_job.attempt_number,
                "result_id": outcome.final_job.result_id,
                "terminal_error_id": outcome.final_job.terminal_error_id,
            },
            ensure_ascii=False,
        )
    )
    return 0 if outcome.succeeded else 2


if __name__ == "__main__":
    raise SystemExit(main())
