from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


WEB_APP_DIR = Path(__file__).resolve().parents[1]
if str(WEB_APP_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_APP_DIR))

from contracts.product_api_v1 import (  # noqa: E402
    build_calculation_profile_payload,
    ProductApiContractError,
    build_error_catalog_payload,
    load_openapi_document,
    load_product_api_schema,
    validate_error_catalog,
    validate_job_list,
    validate_model_passport,
)
from services.product_api_service import (  # noqa: E402
    RuntimeRetentionManager,
    build_model_passport,
    paginate_jobs,
)


PASSPORT_FIXTURE = (
    WEB_APP_DIR / "tests" / "fixtures" / "model_passport_v1_synthetic.json"
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class ProductApiContractTest(unittest.TestCase):
    def test_calculation_profile_is_public_safe_and_schema_valid(self) -> None:
        payload = build_calculation_profile_payload(
            scenario6_attempt_budget=2048,
            profile_label="Стандартный расчет",
            model_version_label="Синтетическая исследовательская модель",
        )
        self.assertEqual(payload["contract_name"], "calculation_profile_v1")
        self.assertNotIn("seed", json.dumps(payload).lower())
        self.assertNotIn("/Users/", json.dumps(payload))
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema is optional in the source-only runtime")
        jsonschema.Draft202012Validator(load_product_api_schema()).validate(payload)

    def test_model_passport_is_path_safe_and_schema_valid(self) -> None:
        payload = json.loads(PASSPORT_FIXTURE.read_text(encoding="utf-8"))
        validate_model_passport(payload)
        self.assertNotIn("/Users/", json.dumps(payload, ensure_ascii=False))
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema is optional in the source-only runtime")
        jsonschema.Draft202012Validator(load_product_api_schema()).validate(payload)

    def test_model_passport_rejects_production_claim_and_local_path(self) -> None:
        payload = json.loads(PASSPORT_FIXTURE.read_text(encoding="utf-8"))
        payload["serving"]["production_claim_allowed"] = True
        with self.assertRaisesRegex(ProductApiContractError, "cannot claim"):
            validate_model_passport(payload)
        payload["serving"]["production_claim_allowed"] = False
        payload["caveats"][0]["display_text"] = "/Users/example/model"
        with self.assertRaisesRegex(ProductApiContractError, "absolute path"):
            validate_model_passport(payload)

    def test_error_catalog_and_openapi_are_published_contracts(self) -> None:
        catalog = build_error_catalog_payload()
        validate_error_catalog(catalog)
        self.assertIn("MODEL_PASSPORT_UNAVAILABLE", {row["code"] for row in catalog["errors"]})
        document = load_openapi_document()
        self.assertEqual(document["openapi"], "3.1.0")
        self.assertIn("/api/v1/models/active", document["paths"])
        self.assertIn("/api/v1/calculation-profile", document["paths"])
        self.assertIn("/api/v1/jobs/{job_id}/progress-view", document["paths"])
        self.assertIn("/api/v1/jobs/{job_id}/result-view", document["paths"])
        self.assertIn("/api/v1/jobs/{job_id}/media-plan", document["paths"])
        self.assertIn("/api/v1/meta/mmm-facts", document["paths"])
        self.assertIn("/api/v1/templates/campaign-plan.xlsx", document["paths"])
        self.assertIn("/ready", document["paths"])
        self.assertEqual(document["info"]["version"], "1.4.0")
        error_codes = {row["code"] for row in catalog["errors"]}
        self.assertIn("RESULT_VIEW_INCONSISTENT", error_codes)
        self.assertIn("MEDIA_PLAN_QUERY_UNSUPPORTED", error_codes)

    def test_job_pagination_and_filter_are_deterministic(self) -> None:
        records = [
            {"job": {"job_id": f"job_{index:012x}", "status": {"code": status}}}
            for index, status in enumerate(("succeeded", "running", "succeeded"), start=1)
        ]
        page = paginate_jobs(records, limit=1, offset=0, status="succeeded")
        validate_job_list(page)
        self.assertEqual(page["total"], 2)
        self.assertEqual(page["next_offset"], 1)
        self.assertEqual(page["items"][0]["job"]["status"]["code"], "succeeded")
        with self.assertRaisesRegex(ValueError, "status"):
            paginate_jobs(records, limit=50, offset=0, status="unknown")

    def test_passport_preserves_target_specific_channel_policy(self) -> None:
        fingerprint = "b" * 64
        capability_rows = [
            {
                "segment": "ТС5/Онлайн",
                "channel": "Рег_ТВ",
                "target": "turnover_per_user",
                "allowed_use": "primary",
                "forecast_use": "allowed",
                "optimizer_use": "optimize",
                "objective_role": "primary_objective",
                "marketer_message": "Основной KPI разрешен.",
            },
            {
                "segment": "ТС5/Онлайн",
                "channel": "Рег_ТВ",
                "target": "orders_per_user",
                "allowed_use": "diagnostic",
                "forecast_use": "diagnostic_only",
                "optimizer_use": "fixed_at_plan",
                "objective_role": "side_metric_only",
                "marketer_message": "Заказы только для диагностики.",
            },
        ]
        manifest = {
            "package_input_fingerprint": fingerprint,
            "package_schema_version": "0.4.0",
            "gate_policy_version": "1.2.0",
            "train_start": "2025-01-01",
            "train_end": "2026-03-20",
            "holdout_start": "2026-03-21",
            "holdout_end": "2026-05-31",
            "artifact_status": {"oot_validation_passed": False},
            "production_blockers": ["MISSING_OR_FAILED_OOT_VALIDATION"],
        }
        package = SimpleNamespace(
            manifest=manifest,
            capability_rows=capability_rows,
            support_rows=[{"scope": "geo", "geo_label": "МОСКВА"}],
            segments=["ТС5/Онлайн"],
            package_stage="posterior_ready",
            activation_status="preprod_restricted",
            model_run_id="synthetic_run",
        )
        resolved = {
            "channel": "preprod",
            "event_id": "event_synthetic",
            "package_id": "pkg_1111111111111111_2222222222222222",
            "registration": {
                "run_dir": "03_Outputs/model",
                "package_input_fingerprint": fingerprint,
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            package_dir = Path(temporary) / "03_Outputs" / "model"
            _write_json(
                package_dir / "oot_validation.json",
                {
                    "status": "failed",
                    "generated_at_utc": "2026-07-15T10:00:00+00:00",
                },
            )
            with patch(
                "services.product_api_service.ModelPackage.from_run_dir",
                autospec=True,
                return_value=package,
            ):
                payload = build_model_passport(
                    resolved,
                    project_root=Path(temporary),
                    deployment_profile="local_development",
                )
        policies = payload["coverage"]["channel_policies"]
        self.assertEqual(len(policies), 2)
        self.assertEqual(
            {row["target"]: row["allowed_use"] for row in policies},
            {"orders_per_user": "diagnostic", "turnover_per_user": "primary"},
        )
        target_counts = {
            row["target"]: row["allowed_use_counts"]
            for row in payload["coverage"]["targets"]
        }
        self.assertEqual(
            target_counts,
            {
                "orders_per_user": {
                    "caution": 0,
                    "diagnostic": 1,
                    "primary": 0,
                    "unavailable": 0,
                },
                "turnover_per_user": {
                    "caution": 0,
                    "diagnostic": 0,
                    "primary": 1,
                    "unavailable": 0,
                },
            },
        )
        self.assertEqual(payload["validation"]["sealed_oot"]["status"], "failed")
        self.assertEqual(payload["caveats"][-1]["code"], "sealed_oot_failed")


class RuntimeRetentionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.state = root / "state"
        self.runtime = root / "runtime"
        self.artifacts = root / "artifacts"
        self.manager = RuntimeRetentionManager(self.state, self.runtime, self.artifacts)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _build_state(self) -> None:
        old = "2026-05-01T10:00:00+00:00"
        recent = "2026-07-14T10:00:00+00:00"
        old_job = "job_111111111111"
        old_validation = "validation_222222222222"
        old_upload = "upload_333333333333"
        active_job = "job_aaaaaaaaaaaa"
        active_validation = "validation_bbbbbbbbbbbb"
        active_upload = "upload_cccccccccccc"

        _write_json(
            self.state / "jobs" / old_job / "job.json",
            {
                "job_id": old_job,
                "validation_id": old_validation,
                "status": {"code": "succeeded"},
                "finished_at_utc": old,
            },
        )
        _write_json(
            self.state / "validations" / old_validation / "validation.json",
            {
                "validation_id": old_validation,
                "upload_id": old_upload,
                "status": {"code": "valid"},
                "finished_at_utc": old,
            },
        )
        _write_json(
            self.state / "uploads" / old_upload / "upload.json",
            {
                "upload_id": old_upload,
                "status": {"code": "parsed"},
                "parsed_at_utc": old,
            },
        )
        _write_json(
            self.state / "jobs" / active_job / "job.json",
            {
                "job_id": active_job,
                "validation_id": active_validation,
                "status": {"code": "running"},
                "finished_at_utc": None,
            },
        )
        _write_json(
            self.state / "validations" / active_validation / "validation.json",
            {
                "validation_id": active_validation,
                "upload_id": active_upload,
                "status": {"code": "valid"},
                "finished_at_utc": recent,
            },
        )
        _write_json(
            self.state / "uploads" / active_upload / "upload.json",
            {
                "upload_id": active_upload,
                "status": {"code": "parsed"},
                "parsed_at_utc": recent,
            },
        )
        for path in (
            self.runtime / old_job / "attempt_001" / "worker.json",
            self.artifacts / "validations" / old_validation / "plan.csv",
            self.artifacts / "uploads" / old_upload / "campaign.csv",
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("old", encoding="utf-8")
        _write_json(
            self.state / "idempotency.json",
            {
                "old": {"job_id": old_job, "request_sha256": "1" * 64},
                "active": {"job_id": active_job, "request_sha256": "2" * 64},
            },
        )
        _write_json(
            self.state / "validation_idempotency.json",
            {
                "old": {
                    "resource_id": old_validation,
                    "record_path": f"validations/{old_validation}/validation.json",
                },
                "active": {
                    "resource_id": active_validation,
                    "record_path": f"validations/{active_validation}/validation.json",
                },
            },
        )
        _write_json(
            self.state / "upload_idempotency.json",
            {
                "old": {
                    "resource_id": old_upload,
                    "record_path": f"uploads/{old_upload}/upload.json",
                },
                "active": {
                    "resource_id": active_upload,
                    "record_path": f"uploads/{active_upload}/upload.json",
                },
            },
        )

    def test_retention_dry_run_and_apply_keep_active_resources(self) -> None:
        self._build_state()
        now = datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc)
        plan = self.manager.plan(30, now=now)
        self.assertEqual(plan.job_ids, ("job_111111111111",))
        self.assertEqual(plan.validation_ids, ("validation_222222222222",))
        self.assertEqual(plan.upload_ids, ("upload_333333333333",))
        self.assertTrue((self.state / "jobs" / plan.job_ids[0]).exists())

        event = self.manager.apply(plan)
        self.assertEqual(event["status"], "applied")
        self.assertFalse((self.state / "jobs" / plan.job_ids[0]).exists())
        self.assertTrue((self.state / "jobs" / "job_aaaaaaaaaaaa").exists())
        index = json.loads((self.state / "idempotency.json").read_text(encoding="utf-8"))
        self.assertEqual(set(index), {"active"})
        validation_index = json.loads(
            (self.state / "validation_idempotency.json").read_text(encoding="utf-8")
        )
        upload_index = json.loads(
            (self.state / "upload_idempotency.json").read_text(encoding="utf-8")
        )
        self.assertEqual(set(validation_index), {"active"})
        self.assertEqual(set(upload_index), {"active"})
        self.assertTrue((self.state / "retention" / "events.jsonl").is_file())

    def test_retention_rejects_untrusted_resource_id(self) -> None:
        _write_json(
            self.state / "jobs" / "record" / "job.json",
            {
                "job_id": "../../outside",
                "validation_id": "validation_222222222222",
                "status": {"code": "succeeded"},
                "finished_at_utc": "2026-05-01T10:00:00+00:00",
            },
        )
        with self.assertRaisesRegex(ValueError, "resource ID"):
            self.manager.plan(
                30,
                now=datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc),
            )


if __name__ == "__main__":
    unittest.main()
