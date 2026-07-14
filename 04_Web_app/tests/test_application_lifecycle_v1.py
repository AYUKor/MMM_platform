from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from typing import Any, Iterator


WEB_APP_DIR = Path(__file__).resolve().parents[1]
if str(WEB_APP_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_APP_DIR))

from contracts import (  # noqa: E402
    LifecycleContractValidationError,
    parse_lifecycle_contract,
    validate_lifecycle_payload,
)

try:
    import jsonschema
except ImportError:  # pragma: no cover - schema QA runs in the project environment
    jsonschema = None


SCHEMA_PATH = WEB_APP_DIR / "contracts" / "application_lifecycle_v1.schema.json"
FIXTURE_DIR = WEB_APP_DIR / "tests" / "fixtures"
HAPPY_FIXTURE_PATH = (
    FIXTURE_DIR / "application_lifecycle_v1_happy_path_synthetic.json"
)
FAILURE_FIXTURE_PATH = (
    FIXTURE_DIR / "application_lifecycle_v1_failure_path_synthetic.json"
)
RESOURCE_KEYS = (
    "uploads",
    "validations",
    "jobs",
    "job_events",
    "progress_events",
    "errors",
)


def _records(bundle: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for key in RESOURCE_KEYS:
        yield from bundle[key]


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for nested in value.values():
            yield from _strings(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            yield from _strings(nested)
    elif isinstance(value, str):
        yield value


class ApplicationLifecycleV1ContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.happy = json.loads(HAPPY_FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.failure = json.loads(FAILURE_FIXTURE_PATH.read_text(encoding="utf-8"))

    @unittest.skipIf(jsonschema is None, "jsonschema is unavailable")
    def test_json_schema_and_all_fixture_records_are_valid(self) -> None:
        jsonschema.Draft202012Validator.check_schema(self.schema)
        validator = jsonschema.Draft202012Validator(
            self.schema,
            format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
        )
        for bundle in (self.happy, self.failure):
            for record in _records(bundle):
                with self.subTest(
                    fixture=bundle["fixture_name"],
                    contract=record["contract_name"],
                ):
                    self.assertEqual(list(validator.iter_errors(record)), [])

    def test_fixture_records_pass_semantic_validation_and_round_trip(self) -> None:
        for bundle in (self.happy, self.failure):
            self.assertEqual(set(bundle), {"fixture_name", "fixture_origin", *RESOURCE_KEYS})
            for record in _records(bundle):
                with self.subTest(
                    fixture=bundle["fixture_name"],
                    contract=record["contract_name"],
                ):
                    self.assertEqual(validate_lifecycle_payload(record), record)
                    self.assertEqual(parse_lifecycle_contract(record).to_dict(), record)

    def test_fixtures_are_explicitly_synthetic_and_path_safe(self) -> None:
        for bundle in (self.happy, self.failure):
            self.assertEqual(
                bundle["fixture_origin"],
                "synthetic_contract_fixture_not_production_evidence",
            )
            for record in _records(bundle):
                self.assertEqual(record["record_origin"], "synthetic_fixture")
            serialized = json.dumps(bundle, ensure_ascii=False)
            self.assertNotIn("/Users/", serialized)
            self.assertNotIn("file://", serialized.lower())
            self.assertFalse(any(value.startswith("C:\\") for value in _strings(bundle)))

    def test_happy_path_links_upload_validation_job_and_result(self) -> None:
        upload = self.happy["uploads"][0]
        validation = self.happy["validations"][0]
        job = self.happy["jobs"][0]

        self.assertEqual(upload["status"]["code"], "parsed")
        self.assertEqual(validation["status"]["code"], "valid")
        self.assertTrue(validation["job_creation_allowed"])
        self.assertEqual(job["status"]["code"], "succeeded")
        self.assertIsNotNone(job["result_id"])
        self.assertEqual(validation["upload_id"], upload["upload_id"])
        self.assertEqual(job["upload_id"], upload["upload_id"])
        self.assertEqual(job["validation_id"], validation["validation_id"])
        job_event_sequences = [
            event["sequence"] for event in self.happy["job_events"]
        ]
        self.assertEqual(job_event_sequences, sorted(set(job_event_sequences)))
        self.assertEqual(
            [event["to_status"]["code"] for event in self.happy["job_events"]],
            ["queued", "running", "succeeded"],
        )
        all_sequences = [
            event["sequence"]
            for key in ("job_events", "progress_events")
            for event in self.happy[key]
        ]
        self.assertEqual(len(all_sequences), len(set(all_sequences)))
        self.assertEqual(max(all_sequences), self.happy["job_events"][-1]["sequence"])

    def test_failure_path_preserves_actionable_errors(self) -> None:
        rejected_upload, parsed_upload = self.failure["uploads"]
        validation = self.failure["validations"][0]
        job = self.failure["jobs"][0]
        errors = {item["error_id"]: item for item in self.failure["errors"]}

        self.assertEqual(rejected_upload["status"]["code"], "rejected")
        self.assertIn(rejected_upload["rejection_error_id"], errors)
        self.assertEqual(parsed_upload["status"]["code"], "parsed")
        self.assertEqual(validation["status"]["code"], "invalid")
        self.assertFalse(validation["job_creation_allowed"])
        self.assertEqual(validation["blocking_errors"][0]["code"], "MISSING_CHANNEL")
        self.assertEqual(job["status"]["code"], "failed")
        self.assertIn(job["terminal_error_id"], errors)
        terminal_error = errors[job["terminal_error_id"]]
        self.assertEqual(terminal_error["category"], "artifact_integrity")
        self.assertFalse(terminal_error["retryable"])

    def test_parsed_upload_requires_parser_payload_and_counts(self) -> None:
        for field_name in (
            "parser_name",
            "parser_version",
            "parsed_at_utc",
            "parsed_payload",
            "source_rows_n",
            "detected_campaigns_n",
        ):
            payload = copy.deepcopy(self.happy["uploads"][0])
            payload[field_name] = None
            with self.subTest(field=field_name), self.assertRaises(
                LifecycleContractValidationError
            ):
                validate_lifecycle_payload(payload)

    def test_received_upload_cannot_claim_parser_outcome(self) -> None:
        payload = copy.deepcopy(self.happy["uploads"][0])
        payload.update(
            {
                "status": {"code": "received", "display_text": "Файл получен"},
                "parsed_at_utc": None,
                "parsed_payload": None,
                "source_rows_n": None,
                "detected_campaigns_n": None,
                "rejection_error_id": None,
            }
        )
        with self.assertRaisesRegex(
            LifecycleContractValidationError,
            "received upload must not contain",
        ):
            validate_lifecycle_payload(payload)

    def test_valid_validation_cannot_contain_blockers(self) -> None:
        payload = copy.deepcopy(self.happy["validations"][0])
        payload["blocking_errors"] = [
            {
                "code": "UNSUPPORTED_CELL",
                "severity": "blocking",
                "display_text": "Связка не поддерживается моделью.",
                "scope": "cell",
                "recoverable": True,
                "source_row_ids": [],
                "affected_cells": [],
            }
        ]
        with self.assertRaisesRegex(
            LifecycleContractValidationError,
            "valid validation must have no blockers",
        ):
            validate_lifecycle_payload(payload)

    def test_succeeded_job_requires_result_and_failed_job_requires_error(self) -> None:
        succeeded = copy.deepcopy(self.happy["jobs"][0])
        succeeded["result_id"] = None
        with self.assertRaisesRegex(
            LifecycleContractValidationError,
            "succeeded job requires",
        ):
            validate_lifecycle_payload(succeeded)

        failed = copy.deepcopy(self.failure["jobs"][0])
        failed["terminal_error_id"] = None
        with self.assertRaisesRegex(
            LifecycleContractValidationError,
            "failed job requires",
        ):
            validate_lifecycle_payload(failed)

    def test_cancelled_job_is_not_misclassified_as_failed(self) -> None:
        payload = copy.deepcopy(self.failure["jobs"][0])
        payload.update(
            {
                "status": {"code": "cancelled", "display_text": "Расчет отменен"},
                "cancel_requested_at_utc": "2026-07-15T09:20:20Z",
                "terminal_error_id": "error_111111111111",
            }
        )
        with self.assertRaisesRegex(
            LifecycleContractValidationError,
            "cancelled job must not contain",
        ):
            validate_lifecycle_payload(payload)

    def test_job_event_rejects_unsupported_transition(self) -> None:
        payload = copy.deepcopy(self.happy["job_events"][2])
        payload["from_status_code"] = "queued"
        with self.assertRaisesRegex(
            LifecycleContractValidationError,
            "Unsupported job transition",
        ):
            validate_lifecycle_payload(payload)

    def test_progress_rejects_impossible_percent_and_counter(self) -> None:
        percent = copy.deepcopy(self.happy["progress_events"][0])
        percent["percent_complete"] = 101.0
        with self.assertRaisesRegex(
            LifecycleContractValidationError,
            "percent_complete must be between 0 and 100",
        ):
            validate_lifecycle_payload(percent)

        counter = copy.deepcopy(self.happy["progress_events"][2])
        counter["counters"][0]["current"] = counter["counters"][0]["total"] + 1
        with self.assertRaisesRegex(
            LifecycleContractValidationError,
            "current must not exceed total",
        ):
            validate_lifecycle_payload(counter)

    def test_model_selector_requires_resolved_immutable_package_pin(self) -> None:
        payload = copy.deepcopy(self.happy["jobs"][0])
        payload["model_selector"]["package_id"] = None
        with self.assertRaisesRegex(
            LifecycleContractValidationError,
            "package_id is required",
        ):
            validate_lifecycle_payload(payload)

        explicit = copy.deepcopy(self.happy["jobs"][0])
        explicit["model_selector"]["mode"] = "explicit_package"
        with self.assertRaisesRegex(
            LifecycleContractValidationError,
            "must not set registry_channel",
        ):
            validate_lifecycle_payload(explicit)

    def test_validation_totals_must_equal_campaign_sums(self) -> None:
        payload = copy.deepcopy(self.happy["validations"][0])
        payload["totals"]["daily_rows_n"] += 1
        with self.assertRaisesRegex(
            LifecycleContractValidationError,
            "totals.daily_rows_n does not match campaigns",
        ):
            validate_lifecycle_payload(payload)

    def test_artifacts_reject_workstation_paths_and_backslash_keys(self) -> None:
        display_path = copy.deepcopy(self.happy["uploads"][0])
        display_path["original_file"]["display_name"] = "C:\\Users\\user\\campaign.xlsx"
        with self.assertRaises(LifecycleContractValidationError):
            validate_lifecycle_payload(display_path)

        storage_path = copy.deepcopy(self.happy["uploads"][0])
        storage_path["original_file"]["storage_key"] = "uploads\\campaign.xlsx"
        with self.assertRaisesRegex(
            LifecycleContractValidationError,
            "safe relative key",
        ):
            validate_lifecycle_payload(storage_path)

        url_key = copy.deepcopy(self.happy["uploads"][0])
        url_key["original_file"]["storage_key"] = "https://storage/campaign.xlsx"
        with self.assertRaisesRegex(
            LifecycleContractValidationError,
            "safe relative key",
        ):
            validate_lifecycle_payload(url_key)

    def test_unknown_contract_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            LifecycleContractValidationError,
            "Unknown lifecycle contract_name",
        ):
            parse_lifecycle_contract({"contract_name": "future_contract_v2"})


if __name__ == "__main__":
    unittest.main()
