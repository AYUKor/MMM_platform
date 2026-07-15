from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from dataclasses import replace
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping


WEB_APP_DIR = Path(__file__).resolve().parents[1]
if str(WEB_APP_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_APP_DIR))

from api.http_smoke import (  # noqa: E402
    HttpSmokeApplication,
    HttpSmokeSettings,
    LocalApiState,
    MirroredWorkerJournal,
    make_handler,
    serve,
)
from contracts.application_lifecycle_v1 import (  # noqa: E402
    DecisionJobV1,
    LifecycleStatus,
    parse_lifecycle_contract,
)
from worker.execution_worker import ExecutionOutcome  # noqa: E402
from services.local_campaign_service import (  # noqa: E402
    LocalCampaignService,
    LocalCampaignServiceSettings,
)


LIFECYCLE_FIXTURE = WEB_APP_DIR / "tests" / "fixtures" / "application_lifecycle_v1_happy_path_synthetic.json"


class _FakeResult:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = dict(payload)
        self.result_id = str(payload["result_id"])

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)


class _BlockingRunner:
    def __init__(
        self,
        job: DecisionJobV1,
        runtime_root: Path,
        started: threading.Event,
        release: threading.Event,
    ) -> None:
        self.job = job
        self.runtime_root = runtime_root
        self.started = started
        self.release = release

    def run(self, job: DecisionJobV1) -> ExecutionOutcome:
        self.started.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("test runner release was not set")
        attempt_root = self.runtime_root / job.job_id / "attempt_001"
        output_dir = attempt_root / "optimizer_output"
        output_dir.mkdir(parents=True, exist_ok=False)
        report_path = output_dir / "marketer_report.xlsx"
        report_path.write_bytes(b"synthetic excel bytes")
        digest = hashlib.sha256(report_path.read_bytes()).hexdigest()
        result_id = "result_999999999999"
        payload = {
            "result_id": result_id,
            "artifacts": [
                {
                    "artifact_id": "artifact_aaaaaaaaaaaa",
                    "kind": "marketer_report_xlsx",
                    "display_name": "Отчет для маркетолога",
                    "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "sha256": digest,
                    "size_bytes": report_path.stat().st_size,
                    "storage_key": "optimizer-runs/synthetic/marketer_report.xlsx",
                }
            ],
        }
        final_job = replace(
            job,
            status=LifecycleStatus("succeeded", "Расчет завершен"),
            started_at_utc="2026-07-15T10:00:01+00:00",
            finished_at_utc="2026-07-15T10:00:02+00:00",
            attempt_number=1,
            result_id=result_id,
        )
        final_job.validate()
        return ExecutionOutcome(
            final_job=final_job,
            job_events=(),
            progress_events=(),
            errors=(),
            decision_result=_FakeResult(payload),
            attempt_root=attempt_root,
            process_return_code=0,
        )


class HttpSmokeV1Test(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.state_root = root / "state"
        self.runtime_root = root / "runtime"
        self.artifact_root = root / "artifacts"
        self.artifact_root.mkdir(parents=True)
        fixture = json.loads(LIFECYCLE_FIXTURE.read_text(encoding="utf-8"))
        payload = dict(fixture["jobs"][0])
        payload.update(
            {
                "status": {"code": "queued", "display_text": "В очереди"},
                "started_at_utc": None,
                "cancel_requested_at_utc": None,
                "finished_at_utc": None,
                "attempt_number": 0,
                "result_id": None,
                "terminal_error_id": None,
            }
        )
        self.job_payload = payload
        self.job = parse_lifecycle_contract(payload)
        assert isinstance(self.job, DecisionJobV1)
        self.started = threading.Event()
        self.release = threading.Event()

        def worker_factory(
            job: DecisionJobV1, cancellation_probe: Any
        ) -> _BlockingRunner:
            del cancellation_probe
            return _BlockingRunner(job, self.runtime_root, self.started, self.release)

        def overview_builder(
            output_dir: Path,
            job_id: str,
            workflow_config_sha256: str,
            storage_prefix: str,
        ) -> Mapping[str, Any]:
            self.assertTrue(output_dir.is_dir())
            self.assertEqual(job_id, self.job.job_id)
            self.assertEqual(workflow_config_sha256, self.job.workflow_config.sha256)
            self.assertFalse(Path(storage_prefix).is_absolute())
            return {
                "contract_name": "result_overview_v1",
                "schema_version": "1.0.0",
                "source_result_id": "result_999999999999",
            }

        self.application = HttpSmokeApplication(
            HttpSmokeSettings(
                state_root=self.state_root,
                runtime_root=self.runtime_root,
                artifact_root=self.artifact_root,
                project_root=WEB_APP_DIR.parent,
                timeout_seconds=5,
            ),
            worker_factory=worker_factory,
            overview_builder=overview_builder,
        )
        self.application.campaign_service = LocalCampaignService(
            LocalCampaignServiceSettings(
                project_root=WEB_APP_DIR.parent,
                artifact_root=self.artifact_root,
                validation_runtime_root=self.runtime_root / "validations",
                registry_root=root / "missing_registry",
                registry_channel="preprod",
                expected_package_id="pkg_local_http_smoke",
                optimizer_policy_path=(
                    WEB_APP_DIR.parent
                    / "02_Code"
                    / "02_Budget_optimizer"
                    / "optimizer_decision_policy_v2.yaml"
                ),
                business_policy_path=(
                    WEB_APP_DIR.parent
                    / "02_Code"
                    / "02_Budget_optimizer"
                    / "business_threshold_policy_v1.yaml"
                ),
            ),
            self.application.state,
            self.application._executor,
            self.application.submit_job,
        )
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_handler(self.application),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.application.close()
        self.temporary.cleanup()

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
    ) -> tuple[int, Any, Mapping[str, str]]:
        body = None
        headers = {}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            headers=headers,
            method=method,
        )
        try:
            response = urllib.request.urlopen(request, timeout=3)
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read()), dict(exc.headers)
        with response:
            content_type = response.headers.get("Content-Type", "")
            content = response.read()
            parsed = json.loads(content) if content_type.startswith("application/json") else content
            return response.status, parsed, dict(response.headers)

    def _wait_for_status(self, expected: str) -> dict[str, Any]:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            status, payload, _ = self._request("GET", f"/api/v1/jobs/{self.job.job_id}")
            if status == 200 and payload["status"]["code"] == expected:
                return payload
            time.sleep(0.02)
        self.fail(f"Job did not reach {expected}")

    def test_background_job_idempotency_result_and_artifact_integrity(self) -> None:
        started_at = time.monotonic()
        status, payload, _ = self._request("POST", "/api/v1/jobs", self.job_payload)
        elapsed = time.monotonic() - started_at
        self.assertEqual(status, 202)
        self.assertLess(elapsed, 1.0)
        self.assertEqual(payload["status"]["code"], "queued")
        self.assertTrue(self.started.wait(timeout=1))

        status, _, _ = self._request("GET", f"/api/v1/jobs/{self.job.job_id}/result")
        self.assertEqual(status, 404)
        status, duplicate, _ = self._request("POST", "/api/v1/jobs", self.job_payload)
        self.assertEqual(status, 200)
        self.assertEqual(duplicate["job_id"], self.job.job_id)

        conflicting = json.loads(json.dumps(self.job_payload))
        conflicting["sampling"]["search_seed"] += 1
        status, error, _ = self._request("POST", "/api/v1/jobs", conflicting)
        self.assertEqual(status, 409)
        self.assertEqual(error["error"]["code"], "IDEMPOTENCY_CONFLICT")

        self.release.set()
        final_job = self._wait_for_status("succeeded")
        self.assertEqual(final_job["result_id"], "result_999999999999")
        status, result, _ = self._request("GET", f"/api/v1/jobs/{self.job.job_id}/result")
        self.assertEqual(status, 200)
        status, overview, _ = self._request("GET", f"/api/v1/jobs/{self.job.job_id}/overview")
        self.assertEqual(status, 200)
        self.assertEqual(overview["contract_name"], "result_overview_v1")

        artifact_id = result["artifacts"][0]["artifact_id"]
        status, body, headers = self._request(
            "GET", f"/api/v1/artifacts/{artifact_id}/download"
        )
        self.assertEqual(status, 200)
        self.assertEqual(hashlib.sha256(body).hexdigest(), result["artifacts"][0]["sha256"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

        artifact_path = self.runtime_root / self.job.job_id / "attempt_001" / "optimizer_output" / "marketer_report.xlsx"
        artifact_path.write_bytes(b"tampered")
        status, error, _ = self._request(
            "GET", f"/api/v1/artifacts/{artifact_id}/download"
        )
        self.assertEqual(status, 409)
        self.assertEqual(error["error"]["code"], "ARTIFACT_INTEGRITY_FAILED")

    def test_mirrored_journal_exposes_progress_without_paths(self) -> None:
        self.application.state.create_job(self.job, "f" * 64)
        attempt = self.runtime_root / self.job.job_id / "attempt_001"
        journal = MirroredWorkerJournal(attempt, self.application.state, self.job.job_id)
        fixture = json.loads(LIFECYCLE_FIXTURE.read_text(encoding="utf-8"))
        progress = parse_lifecycle_contract(fixture["progress_events"][0])
        journal.append_progress(progress)
        status, records, _ = self._request(
            "GET", f"/api/v1/jobs/{self.job.job_id}/progress"
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(records), 1)
        serialized = json.dumps(records, ensure_ascii=False)
        self.assertNotIn("/Users/", serialized)
        self.assertNotIn(str(self.runtime_root), serialized)

    def test_health_cors_and_localhost_bind_guard(self) -> None:
        status, payload, _ = self._request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["mode"], "local_development_only")
        with self.assertRaisesRegex(ValueError, "localhost"):
            serve(self.application, "0.0.0.0", 0)

    def test_multipart_upload_parse_and_invalid_validation_are_fail_closed(self) -> None:
        boundary = "----x5-http-upload-boundary"
        campaign = (
            "campaign_name,segment,geo,channel,start_date,end_date,budget_rub\n"
            "HTTP test,ТС5/Онлайн,МОСКВА,Рег_ТВ,2026-08-01,2026-08-07,1000000\n"
        ).encode("utf-8")
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="campaign.csv"\r\n'
            "Content-Type: text/csv\r\n\r\n"
        ).encode() + campaign + f"\r\n--{boundary}--\r\n".encode()
        request = urllib.request.Request(
            self.base_url + "/api/v1/uploads",
            data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Idempotency-Key": "http-upload-key-0001",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            self.assertEqual(response.status, 202)
            upload = json.loads(response.read())
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            status, current, _ = self._request("GET", f"/api/v1/uploads/{upload['upload_id']}")
            if status == 200 and current["status"]["code"] == "parsed":
                break
            time.sleep(0.02)
        else:
            self.fail("Upload was not parsed")

        validation_request = urllib.request.Request(
            self.base_url + f"/api/v1/uploads/{upload['upload_id']}/validations",
            data=b"",
            headers={"Idempotency-Key": "http-validation-key-0001"},
            method="POST",
        )
        with urllib.request.urlopen(validation_request, timeout=3) as response:
            self.assertEqual(response.status, 202)
            validation = json.loads(response.read())
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            status, current, _ = self._request(
                "GET", f"/api/v1/validations/{validation['validation_id']}"
            )
            if status == 200 and current["status"]["code"] == "invalid":
                break
            time.sleep(0.02)
        else:
            self.fail("Validation did not fail closed")

        job_request = urllib.request.Request(
            self.base_url + f"/api/v1/validations/{validation['validation_id']}/jobs",
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": "http-job-key-0000001",
            },
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(job_request, timeout=3)
        self.assertEqual(context.exception.code, 409)


class HttpSmokeRecoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        fixture = json.loads(LIFECYCLE_FIXTURE.read_text(encoding="utf-8"))
        payload = dict(fixture["jobs"][0])
        payload.update(
            {
                "status": {"code": "queued", "display_text": "В очереди"},
                "started_at_utc": None,
                "cancel_requested_at_utc": None,
                "finished_at_utc": None,
                "attempt_number": 0,
                "result_id": None,
                "terminal_error_id": None,
            }
        )
        parsed = parse_lifecycle_contract(payload)
        assert isinstance(parsed, DecisionJobV1)
        self.job = parsed

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _settings(self) -> HttpSmokeSettings:
        return HttpSmokeSettings(
            state_root=self.root / "state",
            runtime_root=self.root / "runtime",
            artifact_root=self.root / "artifacts",
            project_root=WEB_APP_DIR.parent,
            timeout_seconds=5,
        )

    def test_queued_job_is_dispatched_after_restart(self) -> None:
        state = LocalApiState(self.root / "state")
        state.create_job(self.job, "a" * 64)
        started = threading.Event()
        release = threading.Event()
        release.set()

        def worker_factory(job: DecisionJobV1, cancellation_probe: Any) -> _BlockingRunner:
            del cancellation_probe
            return _BlockingRunner(job, self.root / "runtime", started, release)

        application = HttpSmokeApplication(
            self._settings(),
            worker_factory=worker_factory,
            overview_builder=lambda *_: {"contract_name": "result_overview_v1"},
        )
        try:
            self.assertEqual(application.recovery_summary["queued_jobs_resumed"], 1)
            self.assertTrue(started.wait(timeout=1))
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                record = application.state.read_job(self.job.job_id)
                if record["status"]["code"] == "succeeded":
                    break
                time.sleep(0.02)
            else:
                self.fail("Recovered queued job did not finish")
        finally:
            application.close()

    def test_interrupted_running_job_becomes_retryable_failure(self) -> None:
        state = LocalApiState(self.root / "state")
        state.create_job(self.job, "b" * 64)
        running = replace(
            self.job,
            status=LifecycleStatus("running", "Выполняется"),
            started_at_utc="2026-07-15T10:00:01+00:00",
            attempt_number=1,
        )
        running.validate()
        state.write_job(running)
        application = HttpSmokeApplication(
            self._settings(),
            worker_factory=lambda *_: self.fail("Interrupted job must not be dispatched"),
        )
        try:
            self.assertEqual(application.recovery_summary["interrupted_jobs_failed"], 1)
            final = application.state.read_job(self.job.job_id)
            self.assertEqual(final["status"]["code"], "failed")
            errors = application.state.read_resource(self.job.job_id, "errors")
            self.assertEqual(errors[-1]["code"], "LOCAL_BACKEND_RESTARTED")
            self.assertTrue(errors[-1]["retryable"])
        finally:
            application.close()


if __name__ == "__main__":
    unittest.main()
