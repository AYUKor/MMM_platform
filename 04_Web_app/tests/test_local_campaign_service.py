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
from io import BytesIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

from openpyxl import Workbook


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
    def test_dictionary_context_uses_active_package_support_counts(self) -> None:
        context = self.service.federal_allocation_context()
        self.assertEqual(context.package_id, PACKAGE_ID)
        self.assertEqual(
            {
                direction: len(geographies)
                for direction, geographies in context.eligible_by_direction.items()
            },
            {
                "ТС5/Онлайн": 211,
                "ТС5/Оффлайн": 220,
                "ТСХ/Онлайн": 114,
                "ТСХ/Оффлайн": 117,
            },
        )

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
    def test_federal_plan_expands_before_forecast_and_persists_audit(self) -> None:
        content = (
            "campaign_name,segment,geo,channel,start_date,end_date,budget_rub\n"
            "Federal test,ТС5/Онлайн, россия ,Digital_Performance,2026-09-01,2026-09-01,60000000\n"
            "Federal test,ТС5/Онлайн,РОССИЙСКАЯ ФЕДЕРАЦИЯ,Digital_Performance,2026-09-01,2026-09-01,40000000\n"
            "Federal test,ТС5/Онлайн,Москва,Digital_Performance,2026-09-01,2026-09-01,20000000\n"
        ).encode("utf-8")
        upload, _ = self.service.create_upload(
            filename="federal-plan.csv",
            content=content,
            idempotency_key="upload-federal-plan-0001",
            actor_id="actor_222222222222",
        )
        parsed_upload = self._wait_upload(upload["upload_id"])
        validation, _ = self.service.request_validation(
            upload["upload_id"],
            "validation-federal-plan-0001",
        )
        final = self._wait_validation(validation["validation_id"])
        failure_log = (
            self.settings.validation_runtime_root
            / validation["validation_id"]
            / "protected_validation.log"
        )
        self.assertEqual(
            final["status"]["code"],
            "valid",
            failure_log.read_text(encoding="utf-8") if failure_log.is_file() else final,
        )
        self.assertAlmostEqual(final["totals"]["uploaded_budget_rub"], 120_000_000.0)
        self.assertAlmostEqual(final["totals"]["daily_budget_rub"], 120_000_000.0)
        self.assertEqual(final["totals"]["source_rows_n"], 3)
        warning_codes = {row["code"] for row in final["warnings"]}
        self.assertIn("FEDERAL_AND_LOCAL_GEO_OVERLAP", warning_codes)

        daily_path = self.settings.artifact_root / final["daily_flighting"]["storage_key"]
        with daily_path.open("r", encoding="utf-8-sig", newline="") as handle:
            daily_rows = list(csv.DictReader(handle))
        self.assertEqual(len(daily_rows), 175)
        self.assertFalse(
            any(
                str(row["geo"]).strip().casefold()
                in {"рф", "россия", "российская федерация"}
                for row in daily_rows
            )
        )
        self.assertAlmostEqual(
            sum(float(row["budget_rub"]) for row in daily_rows),
            120_000_000.0,
            places=6,
        )
        moscow = next(row for row in daily_rows if row["geo"] == "МОСКВА")
        self.assertGreater(float(moscow["budget_rub"]), 20_000_000.0)

        inputs = self.state.read_validation_inputs(validation["validation_id"])
        federal = inputs["federal_geo_allocation"]
        self.assertEqual(set(federal), {"provenance", "audit"})
        provenance_path = (
            self.settings.artifact_root / federal["provenance"]["storage_key"]
        )
        audit_path = self.settings.artifact_root / federal["audit"]["storage_key"]
        with provenance_path.open("r", encoding="utf-8-sig", newline="") as handle:
            provenance = list(csv.DictReader(handle))
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        self.assertEqual(len(provenance), 351)
        self.assertEqual(audit["federal_source_rows_n"], 2)
        self.assertEqual(audit["expanded_rows_before_aggregation_n"], 351)
        self.assertEqual(audit["aggregated_rows_n"], 175)
        self.assertTrue(audit["totals"]["conservation_pass"])
        self.assertEqual(
            audit["input"]["file_sha256"],
            parsed_upload["parsed_payload"]["sha256"],
        )
        self.assertEqual(audit["package_id"], PACKAGE_ID)
        availability = inputs["forecast_geo_availability"]
        availability_path = (
            self.settings.artifact_root / availability["audit"]["storage_key"]
        )
        availability_audit = json.loads(
            availability_path.read_text(encoding="utf-8")
        )
        self.assertEqual(availability_audit["source_rows_n"], 3)
        self.assertTrue(
            all(
                row["ready_geo_count"] == 175
                for row in availability_audit["source_rows"]
            )
        )
        product = build_validation_result_v2(
            final,
            normalized_plan_path=(
                self.settings.artifact_root
                / final["normalized_plan"]["storage_key"]
            ),
            federal_allocation_audit=audit,
        )
        self.assertEqual(product["federal_allocation"]["declared_geo_count"], 211)
        self.assertEqual(product["federal_allocation"]["ready_geo_count"], 175)
        self.assertEqual(product["federal_allocation"]["excluded_geo_count"], 36)
        self.assertEqual(product["federal_allocation"]["lmax"], 14)
        self.assertEqual(len(product["geo_points"]), 175)
        self.assertEqual(product["map_coverage"]["unlocated_geographies_n"], 0)
        self.assertNotIn("/Users/", json.dumps(final, ensure_ascii=False))

    @unittest.skipUnless(REGISTRY_ROOT.is_dir(), "canonical preprod model registry is unavailable")
    def test_federal_provenance_survives_request_and_fresh_state_read(self) -> None:
        content = (
            "campaign_name,segment,geo,channel,start_date,end_date,budget_rub\n"
            "Federal durable,ТС5/Онлайн,Россия,Digital_Performance,2026-09-01,2026-09-01,60000000\n"
            "Federal durable,ТС5/Онлайн,Российская Федерация,Digital_Performance,2026-09-01,2026-09-01,40000000\n"
            "Federal durable,ТС5/Онлайн,Москва,Digital_Performance,2026-09-01,2026-09-01,20000000\n"
        ).encode("utf-8")
        upload, _ = self.service.create_upload(
            filename="federal-durable.csv",
            content=content,
            idempotency_key="upload-federal-durable-0001",
            actor_id="actor_222222222222",
        )
        self._wait_upload(upload["upload_id"])
        validation, _ = self.service.request_validation(
            upload["upload_id"],
            "validation-federal-durable-0001",
        )
        final = self._wait_validation(validation["validation_id"])
        self.assertEqual(final["status"]["code"], "valid", final)

        # The asynchronous validation call is complete. Read the record through a
        # new state object so the assertions cannot depend on allocator/service
        # objects or their in-memory FederalGeoAllocationResult.
        persisted_state = LocalApiState(self.state.root)
        persisted_validation = persisted_state.read_validation(
            validation["validation_id"]
        )
        persisted_inputs = persisted_state.read_validation_inputs(
            validation["validation_id"]
        )
        warning_codes = {
            item["code"] for item in persisted_validation["warnings"]
        }
        self.assertIn("FEDERAL_AND_LOCAL_GEO_OVERLAP", warning_codes)

        federal = persisted_inputs["federal_geo_allocation"]
        self.assertEqual(set(federal), {"provenance", "audit"})
        persisted_paths: dict[str, Path] = {}
        for name, identity in federal.items():
            path = self.settings.artifact_root / identity["storage_key"]
            self.assertTrue(path.is_file())
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(),
                identity["sha256"],
            )
            persisted_paths[name] = path

        audit = json.loads(persisted_paths["audit"].read_text(encoding="utf-8"))
        with persisted_paths["provenance"].open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            provenance = list(csv.DictReader(handle))

        self.assertEqual(audit["policy_version"], "FEDERAL_GEO_ALLOCATION_V1")
        self.assertEqual(audit["package_id"], PACKAGE_ID)
        self.assertEqual(audit["federal_source_rows_n"], 2)
        self.assertEqual(
            {item["code"] for item in audit["warnings"]},
            {"FEDERAL_AND_LOCAL_GEO_OVERLAP"},
        )

        expected_budget_by_geo = {
            "Россия": 60_000_000.0,
            "Российская Федерация": 40_000_000.0,
        }
        reconciliation = audit["source_row_reconciliation"]
        self.assertEqual(len(reconciliation), 2)
        self.assertEqual(
            {item["original_geo"] for item in reconciliation},
            set(expected_budget_by_geo),
        )
        source_ids = {item["source_row_id"] for item in reconciliation}
        self.assertEqual(len(source_ids), 2)
        self.assertNotIn("", source_ids)
        for item in reconciliation:
            expected_budget = expected_budget_by_geo[item["original_geo"]]
            self.assertEqual(item["eligible_geo_count"], 175)
            self.assertEqual(item["declared_geo_count"], 211)
            self.assertEqual(item["ready_geo_count"], 175)
            self.assertEqual(item["excluded_geo_count"], 36)
            self.assertEqual(item["lmax"], 14)
            self.assertEqual(item["required_start"], "2026-09-01")
            self.assertEqual(item["required_end"], "2026-09-15")
            self.assertAlmostEqual(item["source_budget_rub"], expected_budget)
            self.assertAlmostEqual(item["allocated_total_rub"], expected_budget)
            self.assertLessEqual(item["difference_rub"], 0.01)
            self.assertTrue(item["conservation_pass"])

        federal_rows = [
            row for row in provenance if row["row_type"] == "federal_expansion"
        ]
        self.assertEqual(len(federal_rows), 350)
        for item in reconciliation:
            rows = [
                row
                for row in federal_rows
                if row["source_row_id"] == item["source_row_id"]
            ]
            self.assertEqual(len(rows), item["eligible_geo_count"])
            self.assertTrue(
                all(row["original_geo"] == item["original_geo"] for row in rows)
            )
            self.assertTrue(
                all(row["policy_version"] == audit["policy_version"] for row in rows)
            )
            self.assertTrue(
                all(row["package_id"] == audit["package_id"] for row in rows)
            )
            self.assertTrue(
                all(
                    float(row["original_spend_rub"]) == item["source_budget_rub"]
                    for row in rows
                )
            )

        daily_path = (
            self.settings.artifact_root
            / persisted_validation["daily_flighting"]["storage_key"]
        )
        with daily_path.open("r", encoding="utf-8-sig", newline="") as handle:
            aggregated_rows = list(csv.DictReader(handle))
        self.assertEqual(len(aggregated_rows), 175)
        self.assertTrue(all(row["source_row_id"] == "" for row in aggregated_rows))

    @unittest.skipUnless(REGISTRY_ROOT.is_dir(), "canonical preprod model registry is unavailable")
    def test_local_geo_is_blocked_by_period_before_job_creation(self) -> None:
        content = (
            "campaign_name,segment,geo,channel,start_date,end_date,budget_rub\n"
            "Yakutsk blocked,ТС5/Онлайн,Якутск,Digital_Performance,2026-09-01,2026-09-01,1000000\n"
        ).encode("utf-8")
        upload, _ = self.service.create_upload(
            filename="yakutsk-blocked.csv",
            content=content,
            idempotency_key="upload-yakutsk-blocked-0001",
            actor_id="actor_222222222222",
        )
        self._wait_upload(upload["upload_id"])
        validation, _ = self.service.request_validation(
            upload["upload_id"],
            "validation-yakutsk-blocked-0001",
        )
        final = self._wait_validation(validation["validation_id"])
        self.assertEqual(final["status"]["code"], "invalid", final)
        self.assertFalse(final["job_creation_allowed"])
        self.assertEqual(
            {row["code"] for row in final["blocking_errors"]},
            {"GEO_NOT_FORECAST_READY_FOR_PERIOD"},
        )
        self.assertEqual(
            final["blocking_errors"][0]["display_text"],
            "Для выбранного периода модель не может надежно рассчитать "
            "географию «Якутск». Измените географию или период кампании.",
        )
        persisted = self.state.read_validation_inputs(validation["validation_id"])
        availability_path = (
            self.settings.artifact_root
            / persisted["forecast_geo_availability"]["audit"]["storage_key"]
        )
        audit = json.loads(availability_path.read_text(encoding="utf-8"))
        self.assertEqual(audit["blocking_local_source_rows_n"], 1)
        self.assertEqual(audit["source_rows"][0]["required_end"], "2026-09-15")

    @unittest.skipUnless(REGISTRY_ROOT.is_dir(), "canonical preprod model registry is unavailable")
    def test_local_moscow_is_ready_for_september(self) -> None:
        content = (
            "campaign_name,segment,geo,channel,start_date,end_date,budget_rub\n"
            "Moscow ready,ТС5/Онлайн,Москва,Digital_Performance,2026-09-01,2026-09-01,1000000\n"
        ).encode("utf-8")
        upload, _ = self.service.create_upload(
            filename="moscow-ready.csv",
            content=content,
            idempotency_key="upload-moscow-ready-0001",
            actor_id="actor_222222222222",
        )
        self._wait_upload(upload["upload_id"])
        validation, _ = self.service.request_validation(
            upload["upload_id"],
            "validation-moscow-ready-0001",
        )
        final = self._wait_validation(validation["validation_id"])
        self.assertEqual(final["status"]["code"], "valid", final)
        self.assertTrue(final["job_creation_allowed"])

    @unittest.skipUnless(REGISTRY_ROOT.is_dir(), "canonical preprod model registry is unavailable")
    def test_mixed_federal_and_unready_local_geo_blocks_but_keeps_federal_audit(self) -> None:
        content = (
            "campaign_name,segment,geo,channel,start_date,end_date,budget_rub\n"
            "Mixed blocked,ТС5/Онлайн,РФ,Digital_Performance,2026-09-01,2026-09-01,100000000\n"
            "Mixed blocked,ТС5/Онлайн,Якутск,Digital_Performance,2026-09-01,2026-09-01,1000000\n"
        ).encode("utf-8")
        upload, _ = self.service.create_upload(
            filename="mixed-yakutsk.csv",
            content=content,
            idempotency_key="upload-mixed-yakutsk-0001",
            actor_id="actor_222222222222",
        )
        self._wait_upload(upload["upload_id"])
        validation, _ = self.service.request_validation(
            upload["upload_id"],
            "validation-mixed-yakutsk-0001",
        )
        final = self._wait_validation(validation["validation_id"])
        self.assertEqual(final["status"]["code"], "invalid", final)
        self.assertFalse(final["job_creation_allowed"])
        self.assertIn(
            "GEO_NOT_FORECAST_READY_FOR_PERIOD",
            {row["code"] for row in final["blocking_errors"]},
        )
        self.assertIn(
            "FEDERAL_AND_LOCAL_GEO_OVERLAP",
            {row["code"] for row in final["warnings"]},
        )
        persisted = self.state.read_validation_inputs(validation["validation_id"])
        federal_audit_path = (
            self.settings.artifact_root
            / persisted["federal_geo_allocation"]["audit"]["storage_key"]
        )
        audit = json.loads(federal_audit_path.read_text(encoding="utf-8"))
        self.assertEqual(audit["source_row_reconciliation"][0]["ready_geo_count"], 175)
        self.assertAlmostEqual(audit["totals"]["federal_source_budget_rub"], 100_000_000.0)
        self.assertAlmostEqual(audit["totals"]["federal_allocated_budget_rub"], 100_000_000.0)

    @unittest.skipUnless(REGISTRY_ROOT.is_dir(), "canonical preprod model registry is unavailable")
    def test_federal_source_rows_with_different_periods_get_different_universes(self) -> None:
        content = (
            "campaign_name,segment,geo,channel,start_date,end_date,budget_rub\n"
            "Period rows,ТС5/Онлайн,РФ,Digital_Performance,2026-09-01,2026-09-01,60000000\n"
            "Period rows,ТС5/Онлайн,Россия,Digital_Performance,2026-01-01,2026-01-01,40000000\n"
        ).encode("utf-8")
        upload, _ = self.service.create_upload(
            filename="federal-periods.csv",
            content=content,
            idempotency_key="upload-federal-periods-0001",
            actor_id="actor_222222222222",
        )
        self._wait_upload(upload["upload_id"])
        validation, _ = self.service.request_validation(
            upload["upload_id"],
            "validation-federal-periods-0001",
        )
        final = self._wait_validation(validation["validation_id"])
        self.assertEqual(final["status"]["code"], "valid", final)
        persisted = self.state.read_validation_inputs(validation["validation_id"])
        audit_path = (
            self.settings.artifact_root
            / persisted["federal_geo_allocation"]["audit"]["storage_key"]
        )
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        counts = {
            row["required_start"]: row["ready_geo_count"]
            for row in audit["source_row_reconciliation"]
        }
        self.assertEqual(counts, {"2026-09-01": 175, "2026-01-01": 210})
        self.assertLessEqual(audit["totals"]["difference_rub"], 0.01)

    @unittest.skipUnless(REGISTRY_ROOT.is_dir(), "canonical preprod model registry is unavailable")
    def test_federal_xlsx_uses_the_same_period_aware_validation(self) -> None:
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(
            [
                "campaign_name",
                "segment",
                "geo",
                "channel",
                "start_date",
                "end_date",
                "budget_rub",
            ]
        )
        sheet.append(
            [
                "Federal XLSX",
                "ТС5/Онлайн",
                "РФ",
                "Digital_Performance",
                "2026-09-01",
                "2026-09-01",
                100_000_000,
            ]
        )
        buffer = BytesIO()
        workbook.save(buffer)
        upload, _ = self.service.create_upload(
            filename="federal.xlsx",
            content=buffer.getvalue(),
            idempotency_key="upload-federal-xlsx-0001",
            actor_id="actor_222222222222",
        )
        self._wait_upload(upload["upload_id"])
        validation, _ = self.service.request_validation(
            upload["upload_id"],
            "validation-federal-xlsx-0001",
        )
        final = self._wait_validation(validation["validation_id"])
        self.assertEqual(final["status"]["code"], "valid", final)
        self.assertEqual(final["campaigns"][0]["daily_rows_n"], 175)

    @unittest.skipUnless(REGISTRY_ROOT.is_dir(), "canonical preprod model registry is unavailable")
    def test_unknown_vsia_rossia_alias_is_rejected_with_human_guidance(self) -> None:
        content = (
            "campaign_name,segment,geo,channel,start_date,end_date,budget_rub\n"
            "Partial map,ТС5/Онлайн,г. Москва,Рег_ТВ,2026-08-01,2026-08-07,500000\n"
            "Partial map,ТС5/Онлайн,Вся Россия,Рег_ТВ,2026-08-01,2026-08-07,500000\n"
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
            final["blocking_errors"][0]["code"], "UNKNOWN_GEO_VALUE"
        )
        self.assertIn("«РФ», «Россия»", final["blocking_errors"][0]["display_text"])
        self.assertIsNone(final["totals"])
        self.assertIsNone(final["normalized_plan"])
        serialized = json.dumps(final, ensure_ascii=False)
        self.assertNotIn("/Users/", serialized)


if __name__ == "__main__":
    unittest.main()
