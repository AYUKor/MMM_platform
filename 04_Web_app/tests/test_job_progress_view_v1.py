from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from typing import Any


WEB_APP_DIR = Path(__file__).resolve().parents[1]
if str(WEB_APP_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_APP_DIR))

from contracts.application_lifecycle_v1 import parse_lifecycle_contract  # noqa: E402
from contracts.job_progress_view_v1 import (  # noqa: E402
    STAGE_IDS,
    job_progress_view_from_dict,
)
from services.job_progress_view import (  # noqa: E402
    ProgressProjectionError,
    build_job_progress_view,
)

try:
    import jsonschema
except ImportError:  # pragma: no cover - CI installs schema validation
    jsonschema = None


FIXTURE_PATH = (
    WEB_APP_DIR / "tests" / "fixtures" / "application_lifecycle_v1_happy_path_synthetic.json"
)
SCHEMA_PATH = WEB_APP_DIR / "contracts" / "job_progress_view_v1.schema.json"
TERMINAL = {"succeeded", "failed", "cancelled", "timed_out"}


class JobProgressViewV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def _job(self, status: str) -> dict[str, Any]:
        job = copy.deepcopy(self.fixture["jobs"][0])
        job["status"] = {
            "code": status,
            "display_text": {
                "queued": "В очереди",
                "running": "Выполняется",
                "cancel_requested": "Запрошена отмена",
                "succeeded": "Расчет завершен",
                "failed": "Ошибка",
                "cancelled": "Отменено",
                "timed_out": "Превышен лимит времени",
            }[status],
        }
        job.update(
            {
                "started_at_utc": "2026-07-15T08:00:12Z",
                "cancel_requested_at_utc": None,
                "finished_at_utc": None,
                "attempt_number": 1,
                "result_id": None,
                "terminal_error_id": None,
            }
        )
        if status == "queued":
            job.update({"started_at_utc": None, "attempt_number": 0})
        elif status == "cancel_requested":
            job["cancel_requested_at_utc"] = "2026-07-15T08:01:30Z"
        elif status == "succeeded":
            job.update(
                {
                    "finished_at_utc": "2026-07-15T08:02:00Z",
                    "result_id": "result_888888888888",
                }
            )
        elif status in {"failed", "timed_out"}:
            job.update(
                {
                    "finished_at_utc": "2026-07-15T08:01:40Z",
                    "terminal_error_id": "error_111111111111",
                }
            )
        elif status == "cancelled":
            job.update(
                {
                    "cancel_requested_at_utc": "2026-07-15T08:01:30Z",
                    "finished_at_utc": "2026-07-15T08:01:40Z",
                }
            )
        parse_lifecycle_contract(job)
        return job

    def _error(
        self,
        stage: str | None,
        *,
        retryable: bool = False,
        occurred_at: str = "2026-07-15T08:01:40Z",
    ) -> dict[str, Any]:
        return {
            "contract_name": "application_error_v1",
            "schema_version": "1.0.0",
            "record_origin": "synthetic_fixture",
            "error_id": "error_111111111111",
            "resource_type": "job",
            "resource_id": "job_777777777777",
            "occurred_at_utc": occurred_at,
            "component": "report" if stage == "report" else "worker",
            "stage": stage,
            "code": "SYNTHETIC_PROGRESS_FAILURE",
            "category": "timeout" if retryable else "calculation",
            "severity": "error",
            "retryable": retryable,
            "display_text": "Не удалось завершить выбранный этап.",
            "support_reference": None,
            "source_row_ids": [],
            "affected_cells": [],
        }

    @staticmethod
    def _result(*, scenario6_status: str = "completed_best_safe") -> dict[str, Any]:
        return {
            "result_id": "result_888888888888",
            "campaign_results": [
                {
                    "scenario6": {
                        "run_status": {
                            "code": scenario6_status,
                            "display_text": "Итог поиска",
                        },
                        "attempt_budget": 2048,
                        "attempts_evaluated": 1706,
                        "finalists": 11,
                    }
                }
            ],
            "artifacts": [
                {
                    "artifact_id": "artifact_aaaaaaaaaaaa",
                    "kind": "marketer_report_xlsx",
                }
            ],
        }

    def _build(
        self,
        status: str,
        *,
        progress: list[dict[str, Any]] | None = None,
        errors: list[dict[str, Any]] | None = None,
        result: dict[str, Any] | None = None,
        validation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = build_job_progress_view(
            job_payload=self._job(status),
            validation_payload=validation or self.fixture["validations"][0],
            progress_payloads=progress or [],
            error_payloads=errors or [],
            result_payload=result,
            queue_position=1 if status == "queued" else None,
            queued_jobs_total=1 if status == "queued" else 0,
        )
        return record.to_dict()

    def test_queued_projection_always_contains_fixed_nine_stage_catalog(self) -> None:
        payload = self._build("queued")
        self.assertEqual(payload["contract_name"], "job_progress_view_v1")
        self.assertEqual(tuple(stage["stage_id"] for stage in payload["stages"]), STAGE_IDS)
        self.assertEqual(payload["current_stage_id"], "P01")
        self.assertEqual(payload["stages"][0]["status"], "active")
        self.assertTrue(all(stage["status"] == "pending" for stage in payload["stages"][1:]))
        self.assertEqual(payload["queue"]["position"], 1)
        self.assertTrue(payload["can_cancel"])
        self.assertFalse(payload["result_available"])

    def test_queued_projection_allows_temporarily_unknown_position(self) -> None:
        record = build_job_progress_view(
            job_payload=self._job("queued"),
            validation_payload=self.fixture["validations"][0],
            progress_payloads=[],
            error_payloads=[],
            result_payload=None,
            queue_position=None,
            queued_jobs_total=0,
        )
        payload = record.to_dict()
        self.assertIsNone(payload["queue"]["position"])
        self.assertEqual(
            payload["queue"]["display_text"],
            "Положение в очереди уточняется.",
        )

    def test_running_projection_maps_real_scenario6_counters(self) -> None:
        progress = copy.deepcopy(self.fixture["progress_events"][:3])
        payload = self._build("running", progress=progress)
        self.assertEqual(payload["current_stage_id"], "P06")
        self.assertEqual(payload["stages"][5]["status"], "active")
        self.assertEqual(payload["scenario6"]["status"], "running")
        self.assertEqual(payload["scenario6"]["attempt_budget"], 2048)
        self.assertEqual(payload["scenario6"]["attempts_checked"], 1536)
        self.assertIsNone(payload["scenario6"]["safe_candidates"])
        self.assertIsNone(payload["scenario6"]["blocked_candidates"])
        self.assertIsNone(payload["stages"][3]["progress"])
        self.assertIn("1 536", payload["stages"][5]["display_text"])

    def test_completed_projection_requires_result_and_report_publication(self) -> None:
        payload = self._build(
            "succeeded",
            progress=copy.deepcopy(self.fixture["progress_events"]),
            result=self._result(),
        )
        self.assertEqual(payload["current_stage_id"], "P09")
        self.assertTrue(payload["result_available"])
        self.assertEqual(payload["report"]["status"], "completed")
        self.assertEqual(payload["scenario6"]["status"], "completed")
        self.assertEqual(payload["scenario6"]["attempts_checked"], 1706)
        self.assertEqual(payload["scenario6"]["finalists_scored"], 11)
        self.assertFalse(any(stage["status"] == "active" for stage in payload["stages"]))
        with self.assertRaisesRegex(ProgressProjectionError, "required result or report"):
            self._build(
                "succeeded",
                progress=copy.deepcopy(self.fixture["progress_events"]),
            )

    def test_unavailable_scenario6_is_not_presented_as_completed_search(self) -> None:
        payload = self._build(
            "succeeded",
            progress=copy.deepcopy(self.fixture["progress_events"]),
            result=self._result(scenario6_status="gate_policy_blocked"),
        )
        self.assertEqual(payload["scenario6"]["status"], "unavailable")
        self.assertEqual(payload["stages"][5]["status"], "skipped")

    def test_preparation_scenario6_and_report_failures_map_to_product_stages(self) -> None:
        cases = (
            ("prepare", [], "P02"),
            ("scenario6", copy.deepcopy(self.fixture["progress_events"][:3]), "P06"),
            ("report", copy.deepcopy(self.fixture["progress_events"]), "P08"),
        )
        for internal_stage, progress, expected_stage in cases:
            with self.subTest(stage=internal_stage):
                payload = self._build(
                    "failed",
                    progress=progress,
                    errors=[self._error(internal_stage)],
                )
                failed = [stage for stage in payload["stages"] if stage["status"] == "failed"]
                self.assertEqual([stage["stage_id"] for stage in failed], [expected_stage])
                self.assertEqual(payload["errors"][0]["stage_id"], expected_stage)
                self.assertTrue(payload["errors"][0]["blocking"])
                self.assertFalse(any(stage["status"] == "active" for stage in payload["stages"]))
                if internal_stage == "report":
                    self.assertEqual(payload["report"]["status"], "failed")

    def test_cancel_requested_cancelled_and_timeout_have_coherent_terminal_states(self) -> None:
        cancel_requested = self._build(
            "cancel_requested",
            progress=copy.deepcopy(self.fixture["progress_events"][:3]),
        )
        self.assertFalse(cancel_requested["can_cancel"])
        self.assertTrue(any(stage["status"] == "active" for stage in cancel_requested["stages"]))

        cancelled = self._build(
            "cancelled",
            progress=copy.deepcopy(self.fixture["progress_events"][:3]),
        )
        self.assertFalse(any(stage["status"] == "active" for stage in cancelled["stages"]))
        self.assertEqual(cancelled["report"]["status"], "not_required")

        timed_out = self._build(
            "timed_out",
            progress=copy.deepcopy(self.fixture["progress_events"][:3]),
            errors=[self._error("scenario6", retryable=True)],
        )
        self.assertEqual(timed_out["job_status"]["code"], "timed_out")
        self.assertTrue(timed_out["errors"][0]["retryable"])
        self.assertFalse(any(stage["status"] == "active" for stage in timed_out["stages"]))

    def test_missing_optional_counters_remain_null(self) -> None:
        progress = copy.deepcopy(self.fixture["progress_events"][:2])
        progress[-1]["counters"] = []
        payload = self._build("running", progress=progress)
        self.assertIsNone(payload["scenario6"]["attempts_checked"])
        self.assertIsNone(payload["scenario6"]["finalists_scored"])

    def test_counter_budget_mismatch_and_non_monotonic_events_fail_closed(self) -> None:
        mismatch = copy.deepcopy(self.fixture["progress_events"][:3])
        mismatch[-1]["counters"][0]["total"] = 4096
        with self.assertRaisesRegex(ProgressProjectionError, "immutable job"):
            self._build("running", progress=mismatch)

        reversed_events = copy.deepcopy(self.fixture["progress_events"][:2])
        reversed_events.reverse()
        with self.assertRaisesRegex(ProgressProjectionError, "sequence"):
            self._build("running", progress=reversed_events)

    def test_campaign_summary_requires_exactly_one_campaign(self) -> None:
        validation = copy.deepcopy(self.fixture["validations"][0])
        validation["campaigns"].append(copy.deepcopy(validation["campaigns"][0]))
        validation["campaigns"][1]["campaign_id"] = "campaign_777777777777"
        validation["campaigns"][1]["campaign_name"] = "Synthetic B"
        with self.assertRaisesRegex(ProgressProjectionError, "invalid"):
            self._build("queued", validation=validation)

    def test_duplicate_polling_is_deterministic_and_does_not_mutate_state(self) -> None:
        progress = copy.deepcopy(self.fixture["progress_events"][:3])
        first = self._build("running", progress=progress)
        second = self._build("running", progress=progress)
        self.assertEqual(first, second)
        self.assertEqual(progress, self.fixture["progress_events"][:3])

    def test_recovery_uses_only_current_attempt_progress(self) -> None:
        job = self._job("running")
        job["attempt_number"] = 2
        job["started_at_utc"] = "2026-07-15T08:03:00Z"
        old_attempt = copy.deepcopy(self.fixture["progress_events"][:3])
        current_attempt = copy.deepcopy(self.fixture["progress_events"][:3])
        for index, event in enumerate(current_attempt, start=1):
            event["attempt_number"] = 2
            event["sequence"] = index
            event["emitted_at_utc"] = f"2026-07-15T08:03:{index:02d}Z"
        record = build_job_progress_view(
            job_payload=job,
            validation_payload=self.fixture["validations"][0],
            progress_payloads=[*old_attempt, *current_attempt],
            error_payloads=[],
            result_payload=None,
            queue_position=None,
            queued_jobs_total=0,
        )
        self.assertEqual(record.current_stage_id, "P06")
        self.assertEqual(record.scenario6.attempts_checked, 1536)
        self.assertEqual(record.updated_at_utc, "2026-07-15T08:03:03Z")

    def test_timestamps_are_chronological_and_payload_is_path_safe(self) -> None:
        payload = self._build(
            "succeeded",
            progress=copy.deepcopy(self.fixture["progress_events"]),
            result=self._result(),
        )
        starts = [
            stage["started_at_utc"]
            for stage in payload["stages"]
            if stage["started_at_utc"] is not None
        ]
        self.assertEqual(starts, sorted(starts))
        serialized = json.dumps(payload, ensure_ascii=False).lower()
        for forbidden in (
            "/users/",
            "file://",
            "posterior",
            "worker",
            "optimizer_progress",
            "final_scoring",
            "candidate_generation",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_old_progress_event_contract_remains_compatible(self) -> None:
        for event in self.fixture["progress_events"]:
            self.assertEqual(parse_lifecycle_contract(event).to_dict(), event)

    @unittest.skipIf(jsonschema is None, "jsonschema is unavailable")
    def test_json_schema_and_python_round_trip(self) -> None:
        jsonschema.Draft202012Validator.check_schema(self.schema)
        payload = self._build(
            "succeeded",
            progress=copy.deepcopy(self.fixture["progress_events"]),
            result=self._result(),
        )
        validator = jsonschema.Draft202012Validator(
            self.schema,
            format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
        )
        self.assertEqual(list(validator.iter_errors(payload)), [])
        self.assertEqual(job_progress_view_from_dict(payload).to_dict(), payload)


if __name__ == "__main__":
    unittest.main()
