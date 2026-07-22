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
from unittest.mock import patch


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
    ValidationIssue,
    ValidationResultV1,
    parse_lifecycle_contract,
)
from contracts.job_progress_view_v1 import (  # noqa: E402
    validate_job_progress_view_payload,
)
from worker.execution_worker import ExecutionOutcome  # noqa: E402
from services.local_campaign_service import (  # noqa: E402
    LocalCampaignService,
    LocalCampaignServiceSettings,
)
from services.job_result_view import (  # noqa: E402
    ResultProjectionStateError,
)


LIFECYCLE_FIXTURE = WEB_APP_DIR / "tests" / "fixtures" / "application_lifecycle_v1_happy_path_synthetic.json"
PASSPORT_FIXTURE = WEB_APP_DIR / "tests" / "fixtures" / "model_passport_v1_synthetic.json"
TEST_AUTH_SECRET = "http-smoke-test-session-secret-2026"
TEST_ADMIN_PASSWORD = "Http-smoke-admin-2026"


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


class _FailingRunner:
    def run(self, job: DecisionJobV1) -> ExecutionOutcome:
        del job
        raise RuntimeError("synthetic unexpected background failure")


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
        self.validation = parse_lifecycle_contract(fixture["validations"][0])
        assert isinstance(self.validation, ValidationResultV1)
        self.started = threading.Event()
        self.release = threading.Event()
        self.overview_started = threading.Event()
        self.overview_release = threading.Event()

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
            self.overview_started.set()
            if not self.overview_release.wait(timeout=5):
                raise TimeoutError("test overview release was not set")
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
                auth_database_path=root / "auth.sqlite3",
                auth_session_secret=TEST_AUTH_SECRET,
                auth_argon2_time_cost=2,
                auth_argon2_memory_cost_kib=19_456,
                auth_argon2_parallelism=1,
            ),
            worker_factory=worker_factory,
            overview_builder=overview_builder,
            model_passport=json.loads(PASSPORT_FIXTURE.read_text(encoding="utf-8")),
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
        self.application.state.write_validation(self.validation)
        self.application.auth.identity_provider.bootstrap_admin(
            email="admin@example.org",
            password=TEST_ADMIN_PASSWORD,
            display_name="Тестовый администратор",
            update_existing=False,
        )
        _, token = self.application.auth.identity_provider.authenticate(
            "admin@example.org",
            TEST_ADMIN_PASSWORD,
            request_id="req_aaaaaaaaaaaaaaaaaaaaaaaa",
            client_key="127.0.0.1",
        )
        self.session_cookie = f"mmm_session={token}"
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_handler(self.application),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.release.set()
        self.overview_release.set()
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
        headers = {"Cookie": self.session_cookie}
        if method in {"POST", "PATCH"}:
            headers["Origin"] = "http://localhost:4173"
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

        status, listing, _ = self._request("GET", "/api/v1/jobs")
        self.assertEqual(status, 200)
        self.assertEqual(listing["total"], 1)
        self.assertEqual(listing["items"][0]["job"]["job_id"], self.job.job_id)
        self.assertEqual(len(listing["items"][0]["campaigns"]), 1)

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
        self.assertTrue(self.overview_started.wait(timeout=1))
        status, in_flight, _ = self._request("GET", f"/api/v1/jobs/{self.job.job_id}")
        self.assertEqual(status, 200)
        self.assertNotEqual(in_flight["status"]["code"], "succeeded")
        status, _, _ = self._request("GET", f"/api/v1/jobs/{self.job.job_id}/overview")
        self.assertEqual(status, 404)
        self.overview_release.set()
        final_job = self._wait_for_status("succeeded")
        self.assertEqual(final_job["result_id"], "result_999999999999")
        status, result, _ = self._request("GET", f"/api/v1/jobs/{self.job.job_id}/result")
        self.assertEqual(status, 200)
        status, progress_view, _ = self._request(
            "GET", f"/api/v1/jobs/{self.job.job_id}/progress-view"
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            validate_job_progress_view_payload(progress_view),
            progress_view,
        )
        self.assertTrue(progress_view["result_available"])
        self.assertEqual(progress_view["report"]["status"], "completed")
        self.assertEqual(progress_view["current_stage_id"], "P09")
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

    def test_direct_job_endpoint_cannot_bypass_one_campaign_validation(self) -> None:
        invalid = replace(
            self.validation,
            status=LifecycleStatus("invalid", "План нельзя отправить в расчет"),
            job_creation_allowed=False,
            campaigns=(),
            totals=None,
            model=None,
            normalized_plan=None,
            daily_flighting=None,
            model_validation=None,
            blocking_errors=(
                ValidationIssue(
                    code="CAMPAIGN_COUNT_NOT_ONE",
                    severity="blocking",
                    display_text="Для расчета требуется ровно одна кампания.",
                    scope="upload",
                    recoverable=True,
                ),
            ),
        )
        invalid.validate()
        self.application.state.write_validation(invalid)
        status, error, _ = self._request("POST", "/api/v1/jobs", self.job_payload)
        self.assertEqual(status, 422)
        self.assertEqual(error["error"]["code"], "INVALID_JOB")

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

    def test_progress_view_http_queue_polling_and_safe_failures(self) -> None:
        self.application.state.create_job(self.job, "d" * 64)
        path = f"/api/v1/jobs/{self.job.job_id}/progress-view"
        status, first, _ = self._request("GET", path)
        self.assertEqual(status, 200)
        self.assertEqual(first["queue"]["position"], 1)
        self.assertEqual(first["current_stage_id"], "P01")
        self.assertEqual(len(first["stages"]), 9)
        status, second, _ = self._request("GET", path)
        self.assertEqual(status, 200)
        self.assertEqual(first, second)

        status, error, _ = self._request(
            "GET", "/api/v1/jobs/job_aaaaaaaaaaaa/progress-view"
        )
        self.assertEqual(status, 404)
        self.assertEqual(error["error"]["code"], "JOB_NOT_FOUND")

        succeeded_without_resources = replace(
            self.job,
            status=LifecycleStatus("succeeded", "Расчет завершен"),
            started_at_utc="2026-07-15T10:00:01+00:00",
            finished_at_utc="2026-07-15T10:00:02+00:00",
            attempt_number=1,
            result_id="result_aaaaaaaaaaaa",
        )
        self.application.state.write_job(succeeded_without_resources)
        status, error, _ = self._request("GET", path)
        self.assertEqual(status, 409)
        self.assertEqual(error["error"]["code"], "PROGRESS_STATE_INCONSISTENT")
        self.assertNotIn("worker", json.dumps(error, ensure_ascii=False).lower())

        with patch.object(
            self.application,
            "progress_view",
            side_effect=RuntimeError("synthetic protected detail"),
        ):
            status, error, _ = self._request("GET", path)
        self.assertEqual(status, 503)
        self.assertEqual(error["error"]["code"], "PROGRESS_VIEW_UNAVAILABLE")
        self.assertNotIn("synthetic protected detail", json.dumps(error, ensure_ascii=False))

    def test_health_cors_and_localhost_bind_guard(self) -> None:
        status, payload, _ = self._request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["mode"], "local_development_only")

        frontend_request = urllib.request.Request(
            self.base_url + "/health",
            headers={"Origin": "http://127.0.0.1:4173"},
            method="GET",
        )
        with urllib.request.urlopen(frontend_request, timeout=3) as response:
            self.assertEqual(
                response.headers.get("Access-Control-Allow-Origin"),
                "http://127.0.0.1:4173",
            )

        with self.assertRaisesRegex(ValueError, "localhost"):
            serve(self.application, "0.0.0.0", 0)

    def test_product_metadata_readiness_schemas_and_job_query(self) -> None:
        status, readiness, _ = self._request("GET", "/ready")
        self.assertEqual(status, 200)
        self.assertEqual(readiness["status"], "ready")
        self.assertTrue(readiness["checks"]["model_passport"])
        self.assertNotIn("/Users/", json.dumps(readiness, ensure_ascii=False))

        status, passport, _ = self._request("GET", "/api/v1/models/active")
        self.assertEqual(status, 200)
        self.assertEqual(passport["contract_name"], "model_passport_v1")

        status, turnover_passport, _ = self._request(
            "GET", "/api/v1/models/active-v2"
        )
        self.assertEqual(status, 200)
        self.assertEqual(turnover_passport["contract_name"], "model_passport_v2")
        self.assertEqual(turnover_passport["serving"]["target_id"], "turnover")
        self.assertEqual(turnover_passport["serving"]["serving_targets_n"], 1)
        self.assertEqual(turnover_passport["serving"]["active_serving_models_n"], 4)

        status, turnover_overview, _ = self._request(
            "GET", "/api/v1/model/overview-v2"
        )
        self.assertEqual(status, 200)
        self.assertEqual(turnover_overview["contract_name"], "model_overview_v2")
        self.assertNotIn(
            "orders_per_user", json.dumps(turnover_overview, ensure_ascii=False)
        )

        status, geo_catalog, _ = self._request(
            "GET", "/api/v1/meta/geo-catalog"
        )
        self.assertEqual(status, 200)
        self.assertEqual(geo_catalog["contract_name"], "geo_catalog_v1")
        self.assertEqual(geo_catalog["status"], "available")
        self.assertEqual(geo_catalog["geographies_n"], 220)
        self.assertEqual(geo_catalog["coverage"]["located_geographies_n"], 220)
        self.assertEqual(geo_catalog["coordinates_license"], "CC BY 4.0")

        status, geo_budget, _ = self._request(
            "GET", "/api/v1/workspace/geo-budget"
        )
        self.assertEqual(status, 200)
        self.assertEqual(geo_budget["contract_name"], "workspace_geo_budget_v1")
        self.assertEqual(geo_budget["status"], "unavailable")
        self.assertEqual(geo_budget["coverage"]["unlocated_budget_rub"], 0.0)

        status, historical_geo_budget, _ = self._request(
            "GET", "/api/v1/model/historical-geo-budget"
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            historical_geo_budget["contract_name"],
            "historical_model_geo_budget_v1",
        )
        self.assertEqual(historical_geo_budget["status"], "unavailable")
        self.assertEqual(historical_geo_budget["rows"], [])
        self.assertNotIn(
            "campaigns_n",
            json.dumps(historical_geo_budget, ensure_ascii=False),
        )
        status, invalid_historical_query, _ = self._request(
            "GET", "/api/v1/model/historical-geo-budget?mode=workspace"
        )
        self.assertEqual(status, 400)
        self.assertEqual(invalid_historical_query["error"]["code"], "INVALID_QUERY")
        with patch.object(
            self.application,
            "historical_model_geo_budget",
            side_effect=RuntimeError("synthetic protected filesystem detail"),
        ):
            status, unavailable_historical, _ = self._request(
                "GET", "/api/v1/model/historical-geo-budget"
            )
        self.assertEqual(status, 503)
        self.assertEqual(
            unavailable_historical["error"]["code"],
            "HISTORICAL_MODEL_GEO_BUDGET_UNAVAILABLE",
        )
        self.assertNotIn(
            "synthetic protected filesystem detail",
            json.dumps(unavailable_historical, ensure_ascii=False),
        )

        status, profile, _ = self._request("GET", "/api/v1/calculation-profile")
        self.assertEqual(status, 200)
        self.assertEqual(profile["contract_name"], "calculation_profile_v1")
        self.assertEqual(profile["scenario6_attempt_budget"], 2048)
        self.assertEqual(
            profile["model_version_label"],
            passport["serving"]["display_name"],
        )

        status, template, headers = self._request(
            "GET",
            "/api/v1/templates/campaign-plan.xlsx",
        )
        self.assertEqual(status, 200)
        self.assertTrue(template.startswith(b"PK"))
        self.assertIn("campaign-plan-template.xlsx", headers["Content-Disposition"])

        status, catalog, _ = self._request("GET", "/api/v1/meta/errors")
        self.assertEqual(status, 200)
        self.assertEqual(catalog["contract_name"], "http_error_catalog_v1")

        status, facts, _ = self._request("GET", "/api/v1/meta/mmm-facts")
        self.assertEqual(status, 200)
        self.assertEqual(facts["contract_name"], "mmm_fact_catalog_v1")
        self.assertGreaterEqual(len(facts["facts"]), 20)

        status, openapi, _ = self._request("GET", "/api/v1/openapi.json")
        self.assertEqual(status, 200)
        self.assertEqual(openapi["info"]["version"], "1.10.0")
        self.assertIn("/api/v1/auth/register", openapi["paths"])
        self.assertIn("/api/v1/jobs/{job_id}/progress-view", openapi["paths"])
        self.assertIn("/api/v1/jobs/{job_id}/result-view", openapi["paths"])
        self.assertIn("/api/v1/jobs/{job_id}/result-view-v2", openapi["paths"])
        self.assertIn("/api/v1/jobs/{job_id}/media-plan", openapi["paths"])
        self.assertIn("/api/v1/jobs/{job_id}/media-plan-v2", openapi["paths"])
        self.assertIn("/api/v1/workspace/home", openapi["paths"])
        self.assertIn("/api/v1/calculations/history", openapi["paths"])
        self.assertIn("/api/v1/model/overview", openapi["paths"])
        self.assertIn("/api/v1/model/overview-v2", openapi["paths"])
        self.assertIn("/api/v1/models/active-v2", openapi["paths"])
        self.assertIn("/api/v1/meta/geo-catalog", openapi["paths"])
        self.assertIn("/api/v1/workspace/geo-budget", openapi["paths"])
        self.assertIn("/api/v1/model/historical-geo-budget", openapi["paths"])
        self.assertIn("/api/v1/help/catalog", openapi["paths"])
        for contract in (
            "application-lifecycle-v1",
            "decision-result-v1",
            "result-overview-v1",
            "product-api-v1",
            "job-progress-view-v1",
            "job-result-view-v1",
            "job-result-view-v2",
            "validation-result-v2",
            "model-passport-v2",
            "model-overview-v2",
            "geo-catalog-v1",
            "workspace-geo-budget-v1",
            "historical-model-geo-budget-v1",
            "scenario-media-plan-v1",
            "scenario-media-plan-v2",
            "mmm-fact-catalog-v1",
            "workspace-home-v1",
            "calculation-history-v1",
            "model-overview-v1",
            "help-catalog-v1",
        ):
            status, schema, _ = self._request(
                "GET", f"/api/v1/contracts/{contract}.json"
            )
            self.assertEqual(status, 200)
            self.assertIn("$schema", schema)
        for schema_name in (
            "JobResultViewV2",
            "ValidationResultV2",
            "ModelPassportV2",
            "ModelOverviewV2",
            "GeoCatalogV1",
            "WorkspaceGeoBudgetV1",
            "HistoricalModelGeoBudgetV1",
            "ScenarioMediaPlanV2",
        ):
            reference = openapi["components"]["schemas"][schema_name]["$ref"]
            self.assertTrue(reference.startswith("/api/v1/contracts/"))
            status, _, _ = self._request("GET", reference)
            self.assertEqual(status, 200)
        status, error, _ = self._request(
            "GET", "/api/v1/contracts/unknown-contract.json"
        )
        self.assertEqual(status, 404)
        self.assertEqual(error["error"]["code"], "SCHEMA_NOT_FOUND")

        self.application.state.create_job(self.job, "e" * 64)
        status, listing, _ = self._request(
            "GET", "/api/v1/jobs?limit=1&offset=0&status=queued"
        )
        self.assertEqual(status, 200)
        self.assertEqual(listing["contract_name"], "job_list_v1")
        self.assertEqual(listing["total"], 1)
        status, error, _ = self._request("GET", "/api/v1/jobs?limit=0")
        self.assertEqual(status, 400)
        self.assertEqual(error["error"]["code"], "INVALID_QUERY")
        self.assertIn("user_action", error["error"])

    def test_product_result_routes_and_controlled_failures(self) -> None:
        self.application.state.create_job(self.job, "a" * 64)
        result_view_payload = {
            "contract_name": "job_result_view_v1",
            "schema_version": "1.0.0",
        }
        with patch.object(
            self.application,
            "result_view",
            return_value=result_view_payload,
        ):
            status, payload, _ = self._request(
                "GET", f"/api/v1/jobs/{self.job.job_id}/result-view"
            )
        self.assertEqual(status, 200)
        self.assertEqual(payload, result_view_payload)

        status, error, _ = self._request(
            "GET", f"/api/v1/jobs/{self.job.job_id}/result-view?unknown=1"
        )
        self.assertEqual(status, 400)
        self.assertEqual(error["error"]["code"], "INVALID_QUERY")

        media_plan_payload = {
            "contract_name": "scenario_media_plan_v1",
            "schema_version": "1.0.0",
        }
        with patch.object(
            self.application,
            "media_plan",
            return_value=media_plan_payload,
        ) as projection:
            status, payload, _ = self._request(
                "GET",
                f"/api/v1/jobs/{self.job.job_id}/media-plan"
                "?scenario_id=S05&page=2&page_size=25&channel=RegionalTV&geo=Moscow",
            )
        self.assertEqual(status, 200)
        self.assertEqual(payload, media_plan_payload)
        projection.assert_called_once_with(
            self.job.job_id,
            scenario_id="S05",
            page=2,
            page_size=25,
            channel="RegionalTV",
            geo="Moscow",
            date=None,
        )

        media_plan_v2_payload = {
            "contract_name": "scenario_media_plan_v2",
            "schema_version": "2.0.0",
        }
        with patch.object(
            self.application,
            "media_plan_v2",
            return_value=media_plan_v2_payload,
        ) as projection_v2:
            status, payload, _ = self._request(
                "GET",
                f"/api/v1/jobs/{self.job.job_id}/media-plan-v2"
                "?scenario_id=S05&page=1&page_size=100",
            )
        self.assertEqual(status, 200)
        self.assertEqual(payload, media_plan_v2_payload)
        projection_v2.assert_called_once_with(
            self.job.job_id,
            scenario_id="S05",
            page=1,
            page_size=100,
            channel=None,
            geo=None,
            date=None,
        )

        browser_error_cases = (
            ("", "Не удалось определить сценарий для просмотра медиаплана."),
            ("?scenario_id=S99", "Не удалось определить сценарий для просмотра медиаплана."),
            (
                "?scenario_id=S01&page=zero",
                "Номер страницы и количество строк на странице заполнены некорректно.",
            ),
            (
                "?scenario_id=S01&page_size=501",
                "Номер страницы и количество строк на странице заполнены некорректно.",
            ),
            ("?scenario_id=S01&channel=", "Название канала заполнено некорректно."),
            ("?scenario_id=S01&geo=", "Название географии заполнено некорректно."),
            ("?scenario_id=S01&date=2026-08-01", "Дата заполнена некорректно."),
            (
                "?scenario_id=S01&internal_name=1",
                "Запрос содержит неподдерживаемые параметры.",
            ),
            (
                "?scenario_id=S01&scenario_id=S02",
                "Каждый параметр запроса можно указать только один раз.",
            ),
        )
        for query, expected_text in browser_error_cases:
            with self.subTest(query=query):
                status, error, _ = self._request(
                    "GET", f"/api/v1/jobs/{self.job.job_id}/media-plan{query}"
                )
                self.assertEqual(status, 422)
                self.assertEqual(
                    error["error"]["code"],
                    "MEDIA_PLAN_QUERY_UNSUPPORTED",
                )
                self.assertEqual(error["error"]["display_text"], expected_text)

        with patch.object(
            self.application,
            "result_view",
            side_effect=ResultProjectionStateError("protected detail"),
        ):
            status, error, _ = self._request(
                "GET", f"/api/v1/jobs/{self.job.job_id}/result-view"
            )
        self.assertEqual(status, 409)
        self.assertEqual(error["error"]["code"], "RESULT_VIEW_INCONSISTENT")
        self.assertNotIn("protected detail", json.dumps(error, ensure_ascii=False))

        with patch.object(
            self.application,
            "result_view",
            side_effect=RuntimeError("protected detail"),
        ):
            status, error, _ = self._request(
                "GET", f"/api/v1/jobs/{self.job.job_id}/result-view"
            )
        self.assertEqual(status, 503)
        self.assertEqual(error["error"]["code"], "RESULT_VIEW_UNAVAILABLE")
        self.assertNotIn("protected detail", json.dumps(error, ensure_ascii=False))

        status, error, _ = self._request(
            "GET", "/api/v1/jobs/job_aaaaaaaaaaaa/result-view"
        )
        self.assertEqual(status, 404)
        self.assertEqual(error["error"]["code"], "JOB_NOT_FOUND")

    def test_calculation_profile_unavailable_messages_are_user_facing(self) -> None:
        campaign_service = self.application.campaign_service
        model_passport = self.application.model_passport
        try:
            self.application.campaign_service = None
            status, error, _ = self._request("GET", "/api/v1/calculation-profile")
            self.assertEqual(status, 503)
            self.assertEqual(error["error"]["code"], "UPLOAD_SERVICE_DISABLED")
            self.assertEqual(
                error["error"]["display_text"],
                "Параметры расчета временно недоступны.",
            )

            self.application.campaign_service = campaign_service
            self.application.model_passport = None
            status, error, _ = self._request("GET", "/api/v1/calculation-profile")
            self.assertEqual(status, 503)
            self.assertEqual(
                error["error"]["code"],
                "MODEL_PASSPORT_UNAVAILABLE",
            )
            self.assertEqual(
                error["error"]["display_text"],
                "Сведения об активной модели временно недоступны.",
            )
        finally:
            self.application.campaign_service = campaign_service
            self.application.model_passport = model_passport

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
                "Cookie": self.session_cookie,
                "Origin": "http://localhost:4173",
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
            headers={
                "Idempotency-Key": "http-validation-key-0001",
                "Cookie": self.session_cookie,
                "Origin": "http://localhost:4173",
            },
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
                "Cookie": self.session_cookie,
                "Origin": "http://localhost:4173",
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
        validation = parse_lifecycle_contract(fixture["validations"][0])
        assert isinstance(validation, ValidationResultV1)
        self.validation = validation

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _settings(self) -> HttpSmokeSettings:
        return HttpSmokeSettings(
            state_root=self.root / "state",
            runtime_root=self.root / "runtime",
            artifact_root=self.root / "artifacts",
            project_root=WEB_APP_DIR.parent,
            timeout_seconds=5,
            auth_database_path=self.root / "auth.sqlite3",
            auth_session_secret=TEST_AUTH_SECRET,
            auth_argon2_time_cost=2,
            auth_argon2_memory_cost_kib=19_456,
            auth_argon2_parallelism=1,
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

    def test_unexpected_runner_failure_is_terminal_and_auditable(self) -> None:
        application = HttpSmokeApplication(
            self._settings(),
            worker_factory=lambda *_: _FailingRunner(),
        )
        try:
            application.state.write_validation(self.validation)
            application.submit_job(self.job.to_dict())
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                final = application.state.read_job(self.job.job_id)
                if final["status"]["code"] == "failed":
                    break
                time.sleep(0.02)
            else:
                self.fail("Unexpected background failure left a non-terminal job")
            errors = application.state.read_resource(self.job.job_id, "errors")
            self.assertEqual(errors[-1]["code"], "HTTP_BACKGROUND_FAILURE")
            self.assertTrue(errors[-1]["retryable"])
            protected_log = (
                self.root
                / "runtime"
                / "api_internal_errors"
                / f"{self.job.job_id}.log"
            )
            self.assertIn("synthetic unexpected", protected_log.read_text(encoding="utf-8"))
        finally:
            application.close()

    def test_default_worker_factory_keeps_job_identity_for_journal(self) -> None:
        application = HttpSmokeApplication(self._settings())
        try:
            worker = application._default_worker_factory(self.job, lambda: False)
            journal = worker.journal_factory(self.root / "runtime" / "journal_probe")
            self.assertIsInstance(journal, MirroredWorkerJournal)
            self.assertEqual(journal.job_id, self.job.job_id)
        finally:
            application.close()


if __name__ == "__main__":
    unittest.main()
