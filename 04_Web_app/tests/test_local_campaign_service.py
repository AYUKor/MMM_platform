from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import patch


WEB_APP_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = WEB_APP_DIR.parent
EVIDENCE_ROOT = Path(os.environ.get("MMM_EVIDENCE_PROJECT_ROOT", PROJECT_ROOT)).resolve()
if str(WEB_APP_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_APP_DIR))

from api.http_smoke import LocalApiState, _multipart_file  # noqa: E402
from contracts.application_lifecycle_v1 import (  # noqa: E402
    DecisionJobV1,
    SamplingProfile,
    parse_lifecycle_contract,
)
from services.local_campaign_service import (  # noqa: E402
    LocalCampaignService,
    LocalCampaignServiceSettings,
)
from services.business_semantics_v2 import build_validation_result_v2  # noqa: E402


REGISTRY_ROOT = EVIDENCE_ROOT / "03_Outputs" / "01_PyMC_outputs" / "00_Model_registry"
PACKAGE_ID = "pkg_807d3ddbae57a52a_9aacd3beb350725b"


class LocalCampaignServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.state = LocalApiState(root / "state")
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.submitted_jobs: list[dict[str, Any]] = []

        def submit(payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
            parsed = parse_lifecycle_contract(payload)
            self.assertIsInstance(parsed, DecisionJobV1)
            self.submitted_jobs.append(payload)
            return payload, True

        registry_root = REGISTRY_ROOT
        if REGISTRY_ROOT.is_dir():
            registry_root = root / "registry"
            (registry_root / "channels").mkdir(parents=True)
            (registry_root / "registrations").mkdir(parents=True)
            channel_pointer = json.loads(
                (REGISTRY_ROOT / "channels" / "preprod.json").read_text(encoding="utf-8")
            )
            source_registration = REGISTRY_ROOT / "registrations" / f"{PACKAGE_ID}.json"
            registration = json.loads(source_registration.read_text(encoding="utf-8"))
            registration["run_dir"] = str((EVIDENCE_ROOT / registration["run_dir"]).resolve())
            registration["panel"]["path"] = str((EVIDENCE_ROOT / registration["panel"]["path"]).resolve())
            immutable_registration = dict(registration)
            for key in (
                "registered_at_utc",
                "registered_by",
                "reason",
                "registration_content_sha256",
            ):
                immutable_registration.pop(key, None)
            registration_sha256 = hashlib.sha256(
                json.dumps(
                    immutable_registration,
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                ).encode("utf-8")
            ).hexdigest()
            registration["registration_content_sha256"] = registration_sha256
            channel_pointer["run_dir"] = registration["run_dir"]
            channel_pointer["registration_content_sha256"] = registration_sha256
            (registry_root / "registrations" / f"{PACKAGE_ID}.json").write_text(
                json.dumps(registration, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            (registry_root / "channels" / "preprod.json").write_text(
                json.dumps(channel_pointer, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        self.settings = LocalCampaignServiceSettings(
            project_root=EVIDENCE_ROOT,
            artifact_root=root / "artifacts",
            validation_runtime_root=root / "runtime" / "validations",
            registry_root=registry_root,
            registry_channel="preprod",
            expected_package_id=PACKAGE_ID,
            optimizer_policy_path=PROJECT_ROOT / "02_Code" / "02_Budget_optimizer" / "optimizer_decision_policy_v2.yaml",
            business_policy_path=PROJECT_ROOT / "02_Code" / "02_Budget_optimizer" / "business_threshold_policy_v1.yaml",
            model_verification_mode="serving_bundle",
            default_sampling=SamplingProfile(64, 16, 32, 42, 10042),
        )
        self.service = LocalCampaignService(
            self.settings,
            self.state,
            self.executor,
            submit,
        )
        self.campaign_csv = (
            "campaign_name,segment,geo,channel,start_date,end_date,budget_rub\n"
            "Local test,ТС5/Онлайн,г. Москва,Рег_ТВ,2026-08-01,2026-08-07,1000000\n"
        ).encode("utf-8")

    def tearDown(self) -> None:
        self.executor.shutdown(wait=True, cancel_futures=False)
        self.temporary.cleanup()

    def _wait_upload(self, upload_id: str, expected: str = "parsed") -> dict[str, Any]:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            record = self.state.read_upload(upload_id)
            if record["status"]["code"] == expected:
                return record
            time.sleep(0.02)
        self.fail(f"Upload did not reach {expected}")

    def _wait_validation(self, validation_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            record = self.state.read_validation(validation_id)
            if record["status"]["code"] in {"valid", "invalid"}:
                return record
            time.sleep(0.05)
        self.fail("Validation did not finish")

    def test_canonical_upload_is_parsed_in_background_and_idempotent(self) -> None:
        record, created = self.service.create_upload(
            filename="campaign.csv",
            content=self.campaign_csv,
            idempotency_key="upload-test-key-0001",
            actor_id="actor_222222222222",
        )
        self.assertTrue(created)
        self.assertEqual(record["status"]["code"], "received")
        parsed = self._wait_upload(record["upload_id"])
        self.assertEqual(parsed["source_rows_n"], 1)
        self.assertEqual(parsed["detected_campaigns_n"], 1)
        parsed_path = self.settings.artifact_root / parsed["parsed_payload"]["storage_key"]
        self.assertTrue(parsed_path.is_file())
        self.assertEqual(hashlib.sha256(parsed_path.read_bytes()).hexdigest(), parsed["parsed_payload"]["sha256"])

        duplicate, duplicate_created = self.service.create_upload(
            filename="campaign.csv",
            content=self.campaign_csv,
            idempotency_key="upload-test-key-0001",
            actor_id="actor_222222222222",
        )
        self.assertFalse(duplicate_created)
        self.assertEqual(duplicate["upload_id"], record["upload_id"])

        with self.assertRaisesRegex(ValueError, "path"):
            self.service.create_upload(
                filename="../campaign.csv",
                content=self.campaign_csv,
                idempotency_key="upload-test-key-0002",
                actor_id="actor_222222222222",
            )

    def test_stdlib_multipart_parser_extracts_only_file_field(self) -> None:
        boundary = "----x5-mmm-test-boundary"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="campaign.csv"\r\n'
            "Content-Type: text/csv\r\n\r\n"
        ).encode() + self.campaign_csv + f"\r\n--{boundary}--\r\n".encode()
        filename, content = _multipart_file(f"multipart/form-data; boundary={boundary}", body)
        self.assertEqual(filename, "campaign.csv")
        self.assertEqual(content, self.campaign_csv)

    @unittest.skipUnless(REGISTRY_ROOT.is_dir(), "canonical preprod model registry is unavailable")
    def test_real_package_validation_builds_immutable_job_inputs(self) -> None:
        upload, _ = self.service.create_upload(
            filename="campaign.csv",
            content=self.campaign_csv,
            idempotency_key="upload-real-validation-0001",
            actor_id="actor_222222222222",
        )
        self._wait_upload(upload["upload_id"])
        validation, created = self.service.request_validation(
            upload["upload_id"],
            "validation-real-key-0001",
        )
        self.assertTrue(created)
        final = self._wait_validation(validation["validation_id"])
        validation_log = (
            self.settings.validation_runtime_root
            / validation["validation_id"]
            / "protected_validation.log"
        )
        failure_detail = (
            validation_log.read_text(encoding="utf-8")
            if validation_log.is_file()
            else final.get("blocking_errors")
        )
        self.assertEqual(final["status"]["code"], "valid", failure_detail)
        self.assertEqual(final["model"]["package_id"], PACKAGE_ID)
        self.assertTrue(final["job_creation_allowed"])
        self.assertTrue(final["campaigns"])
        self.assertTrue(final["warnings"])
        self.assertNotIn("geo_points", final["preview"])
        self.assertAlmostEqual(
            sum(row["total_budget_rub"] for row in final["preview"]["budget_by_channel"]),
            final["totals"]["model_input_budget_rub"],
        )
        self.assertAlmostEqual(
            sum(row["total_budget_rub"] for row in final["preview"]["budget_by_geo"]),
            final["totals"]["model_input_budget_rub"],
        )
        self.assertAlmostEqual(
            sum(row["daily_budget_rub"] for row in final["preview"]["channel_flighting"]),
            final["totals"]["daily_budget_rub"],
        )
        serialized = json.dumps(final, ensure_ascii=False)
        self.assertNotIn("/Users/", serialized)
        for key in ("normalized_plan", "daily_flighting", "model_validation"):
            path = self.settings.artifact_root / final[key]["storage_key"]
            self.assertTrue(path.is_file())
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), final[key]["sha256"])
        normalized_path = (
            self.settings.artifact_root / final["normalized_plan"]["storage_key"]
        )
        with normalized_path.open("r", encoding="utf-8-sig", newline="") as handle:
            normalized_rows = list(csv.DictReader(handle))
        self.assertEqual(normalized_rows[0]["input_geo_name"], "г. Москва")
        self.assertEqual(normalized_rows[0]["geo"], "МОСКВА")
        self.assertEqual(
            normalized_rows[0]["canonical_geo_display_name"], "Москва"
        )
        self.assertEqual(normalized_rows[0]["geo_normalization_status"], "alias")

        with patch.object(
            self.service,
            "_code_reference",
            return_value="git:synthetic-test",
        ):
            job, job_created = self.service.create_job(
                final["validation_id"],
                "job-real-validation-0001",
                {"sampling": {"scenario6_attempt_budget": 64}},
            )
        self.assertTrue(job_created)
        parsed_job = parse_lifecycle_contract(job)
        self.assertIsInstance(parsed_job, DecisionJobV1)
        self.assertEqual(parsed_job.status.code, "queued")
        self.assertEqual(parsed_job.model_selector.package_id, PACKAGE_ID)
        self.assertEqual(parsed_job.sampling.scenario6_attempt_budget, 64)
        self.assertEqual(len(self.submitted_jobs), 1)

    @unittest.skipUnless(REGISTRY_ROOT.is_dir(), "canonical preprod model registry is unavailable")
    def test_unknown_geo_keeps_budget_and_map_evidence_when_model_blocks_job(self) -> None:
        content = (
            "campaign_name,segment,geo,channel,start_date,end_date,budget_rub\n"
            "Partial map,ТС5/Онлайн,г. Москва,Рег_ТВ,2026-08-01,2026-08-07,500000\n"
            "Partial map,ТС5/Онлайн,НЕИЗВЕСТНОЕ ГЕО,Рег_ТВ,2026-08-01,2026-08-07,500000\n"
        ).encode("utf-8")
        upload, _ = self.service.create_upload(
            filename="partial-map.csv",
            content=content,
            idempotency_key="upload-partial-map-0001",
            actor_id="actor_222222222222",
        )
        self._wait_upload(upload["upload_id"])
        validation, _ = self.service.request_validation(
            upload["upload_id"],
            "validation-partial-map-0001",
        )
        final = self._wait_validation(validation["validation_id"])
        self.assertEqual(final["status"]["code"], "invalid")
        self.assertFalse(final["job_creation_allowed"])
        self.assertEqual(
            final["blocking_errors"][0]["code"], "UNSUPPORTED_MODEL_CELLS"
        )
        self.assertEqual(final["totals"]["model_input_budget_rub"], 1_000_000.0)
        normalized_path = (
            self.settings.artifact_root / final["normalized_plan"]["storage_key"]
        )
        view = build_validation_result_v2(
            final,
            normalized_plan_path=normalized_path,
        )
        self.assertEqual(view["map_coverage"]["status"], "partial")
        self.assertEqual(view["map_coverage"]["located_geographies_n"], 1)
        self.assertEqual(view["map_coverage"]["unlocated_geographies_n"], 1)
        self.assertEqual(
            view["map_coverage"]["unlocated_budget_rub"], 500_000.0
        )
        self.assertEqual(
            sum(row["budget_rub"] for row in view["geo_points"]),
            1_000_000.0,
        )
        unknown = next(
            row
            for row in view["geo_points"]
            if row["normalization_status"] == "unknown"
        )
        self.assertIsNone(unknown["latitude"])
        self.assertEqual(unknown["budget_rub"], 500_000.0)


if __name__ == "__main__":
    unittest.main()
