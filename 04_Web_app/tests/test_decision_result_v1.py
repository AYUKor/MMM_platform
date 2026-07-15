from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Iterator


WEB_APP_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(os.environ.get("MMM_EVIDENCE_PROJECT_ROOT", WEB_APP_DIR.parent)).resolve()
if str(WEB_APP_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_APP_DIR))

from adapters.optimizer_result_adapter import (  # noqa: E402
    OptimizerResultAdapterError,
    _status,
    build_decision_result,
)

try:
    import jsonschema
except ImportError:  # pragma: no cover - schema QA runs in the project environment
    jsonschema = None


SCHEMA_PATH = WEB_APP_DIR / "contracts" / "decision_result_v1.schema.json"
FIXTURE_PATH = WEB_APP_DIR / "tests" / "fixtures" / "decision_result_v1_real_sanitized.json"
GATE_BLOCKED_FIXTURE_PATH = (
    WEB_APP_DIR / "tests" / "fixtures" / "decision_result_v1_gate_blocked_sanitized.json"
)
OPTIMIZER_OUTPUTS = PROJECT_ROOT / "03_Outputs" / "02_Budget_optimizer_outputs"
RUN_16 = OPTIMIZER_OUTPUTS / "16_Budget_optimizer_14072026_agency_may_ts5_surgical_s6_v3"
RUN_17 = OPTIMIZER_OUTPUTS / "17_Budget_optimizer_14072026_agency_may_tsx_surgical_s6_v3"
RUN_18 = OPTIMIZER_OUTPUTS / "18_Budget_optimizer_14072026_agency_gender_boost_contract_v1"


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for nested in value.values():
            yield from _strings(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            yield from _strings(nested)
    elif isinstance(value, str):
        yield value


class DecisionResultV1ContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.gate_blocked_fixture = json.loads(GATE_BLOCKED_FIXTURE_PATH.read_text(encoding="utf-8"))

    def _assert_schema_valid(self, payload: dict[str, Any]) -> None:
        if jsonschema is None:
            return
        jsonschema.Draft202012Validator.check_schema(self.schema)
        jsonschema.validate(
            payload,
            self.schema,
            format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
        )

    @unittest.skipIf(jsonschema is None, "jsonschema is unavailable in this Python environment")
    def test_json_schema_and_fixtures_are_valid(self) -> None:
        jsonschema.Draft202012Validator.check_schema(self.schema)
        jsonschema.validate(
            self.fixture,
            self.schema,
            format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
        )
        jsonschema.validate(
            self.gate_blocked_fixture,
            self.schema,
            format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
        )

    def test_sanitized_real_derived_fixture_matches_contract(self) -> None:
        self._assert_schema_valid(self.fixture)
        self.assertEqual(self.fixture["contract_name"], "decision_result_v1")
        self.assertEqual(self.fixture["schema_version"], "1.0.0")
        self.assertEqual(self.fixture["result_origin"], "sanitized_fixture")
        self.assertEqual(self.fixture["job"]["adapter_name"], "optimizer_result_adapter")
        self.assertEqual(self.fixture["job"]["adapter_version"], "1.0.1")
        self.assertTrue(self.fixture["campaign_results"])

        warning_codes = {warning["code"] for warning in self.fixture["warnings"]}
        self.assertIn("sanitized_fixture_not_production_evidence", warning_codes)
        for campaign in self.fixture["campaign_results"]:
            self.assertEqual(
                [scenario["scenario_id"] for scenario in campaign["scenarios"]],
                ["S01", "S02", "S03", "S04", "S05", "S06"],
            )
            self.assertEqual(campaign["scenario6"]["run_status"]["code"], "completed_best_safe")
            self.assertEqual(campaign["recommendation"]["scenario_id"], "S06")
            self.assertIsNotNone(campaign["scenarios"][-1]["metrics"]["incremental_turnover"])

        serialized = json.dumps(self.fixture, ensure_ascii=False)
        self.assertNotIn("/Users/", serialized)
        self.assertNotIn("file://", serialized)
        self.assertNotIn("Майские", serialized)
        self.assertNotIn("МОСКВА", serialized)
        self.assertNotIn("АЗС", serialized)
        self.assertNotIn("Электрички", serialized)
        self.assertNotIn(
            "807d3ddbae57a52ad184f94cd5442cdefd97764fe3903e5b250b5d04cd26c62c",
            serialized,
        )
        self.assertEqual(
            self.fixture["campaign_results"][0]["passport"]["source_start_date"],
            "2026-01-01",
        )

    def test_gate_blocked_fixture_matches_contract(self) -> None:
        self._assert_schema_valid(self.gate_blocked_fixture)
        campaign = self.gate_blocked_fixture["campaign_results"][0]
        self.assertEqual(campaign["scenario6"]["run_status"]["code"], "gate_policy_blocked")
        self.assertEqual(campaign["recommendation"]["scenario_id"], "S01")
        self.assertIsNone(campaign["scenarios"][-1]["metrics"]["incremental_turnover"])
        self.assertNotIn("/Users/", json.dumps(self.gate_blocked_fixture, ensure_ascii=False))

    @unittest.skipUnless(RUN_17.is_dir(), "canonical optimizer run 17 is unavailable")
    def test_run_17_maps_gate_block_and_partial_coverage(self) -> None:
        payload = build_decision_result(RUN_17).to_dict()
        self._assert_schema_valid(payload)
        self.assertEqual(len(payload["campaign_results"]), 1)
        adapter_path = WEB_APP_DIR / "adapters" / "optimizer_result_adapter.py"
        self.assertEqual(
            payload["job"]["adapter_sha256"],
            hashlib.sha256(adapter_path.read_bytes()).hexdigest(),
        )

        campaign = payload["campaign_results"][0]
        self.assertEqual(campaign["statuses"]["calculation_status"]["code"], "partially_calculated")
        self.assertEqual(campaign["scenario6"]["run_status"]["code"], "gate_policy_blocked")
        self.assertEqual(campaign["recommendation"]["scenario_id"], "S01")
        self.assertEqual(
            [scenario["scenario_id"] for scenario in campaign["scenarios"]],
            ["S01", "S02", "S03", "S04", "S05", "S06"],
        )
        self.assertIsNone(campaign["scenarios"][-1]["metrics"]["incremental_turnover"])

        for artifact in payload["artifacts"]:
            self.assertFalse(Path(artifact["storage_key"]).is_absolute())
            self.assertNotIn("..", Path(artifact["storage_key"]).parts)
        self.assertFalse(any(re.match(r"^(?:/|[A-Za-z]:[\\/])", value) for value in _strings(payload)))

    @unittest.skipUnless(RUN_16.is_dir(), "canonical optimizer run 16 is unavailable")
    def test_run_16_maps_successful_safe_scenario_6(self) -> None:
        payload = build_decision_result(RUN_16).to_dict()
        self._assert_schema_valid(payload)
        campaign = payload["campaign_results"][0]

        self.assertEqual(campaign["scenario6"]["run_status"]["code"], "completed_best_safe")
        self.assertIsNotNone(campaign["scenario6"]["best_safe_candidate_id"])
        self.assertEqual(campaign["recommendation"]["scenario_id"], "S06")
        self.assertEqual(campaign["statuses"]["optimizer_status"]["code"], "best_safe_available")
        self.assertGreater(campaign["scenario6"]["attempt_budget"], 0)
        self.assertGreater(campaign["scenario6"]["attempts_evaluated"], 0)
        self.assertGreater(campaign["scenario6"]["kernel_evaluations"], 0)
        self.assertGreater(campaign["scenario6"]["unique_allocations"], 0)
        self.assertGreater(campaign["scenario6"]["candidates_scored"], 0)

        candidate_values = [
            campaign["scenario6"]["best_raw_candidate_id"],
            campaign["scenario6"]["best_safe_candidate_id"],
            campaign["recommendation"]["candidate_id"],
        ]
        self.assertTrue(all(value is None or value.startswith("candidate_") for value in candidate_values))
        self.assertFalse(any("__scenario6" in str(value) for value in candidate_values))

    @unittest.skipUnless(RUN_18.is_dir(), "canonical optimizer run 18 is unavailable")
    def test_run_18_maps_multiple_campaigns_in_one_job_result(self) -> None:
        payload = build_decision_result(RUN_18).to_dict()
        self._assert_schema_valid(payload)

        campaigns = payload["campaign_results"]
        self.assertEqual(len(campaigns), 2)
        self.assertEqual(len({campaign["campaign_id"] for campaign in campaigns}), 2)
        self.assertEqual(
            {campaign["scenario6"]["run_status"]["code"] for campaign in campaigns},
            {"completed_best_safe", "gate_policy_blocked"},
        )
        safe_campaign = next(
            campaign
            for campaign in campaigns
            if campaign["scenario6"]["run_status"]["code"] == "completed_best_safe"
        )
        self.assertEqual(safe_campaign["recommendation"]["scenario_id"], "S01")
        self.assertTrue(safe_campaign["scenarios"][-1]["available"])
        self.assertIsNotNone(safe_campaign["scenarios"][-1]["metrics"]["incremental_turnover"])
        self.assertIsNotNone(safe_campaign["scenarios"][-1]["metrics"]["incremental_orders"])
        self.assertGreater(safe_campaign["scenario6"]["attempts_evaluated"], 0)

        blocked_campaign = next(
            campaign
            for campaign in campaigns
            if campaign["scenario6"]["run_status"]["code"] == "gate_policy_blocked"
        )
        self.assertFalse(blocked_campaign["scenarios"][-1]["available"])
        self.assertEqual(blocked_campaign["scenario6"]["attempts_evaluated"], 0)
        for campaign in campaigns:
            self.assertEqual(
                [scenario["scenario_id"] for scenario in campaign["scenarios"]],
                ["S01", "S02", "S03", "S04", "S05", "S06"],
            )

    @unittest.skipUnless(RUN_18.is_dir(), "canonical optimizer run 18 is unavailable")
    def test_run_18_preserves_order_counts_and_basket_bridge_semantics(self) -> None:
        payload = build_decision_result(RUN_18).to_dict()
        scenario_path = RUN_18 / "marketer_report_scenario_results.csv"
        with scenario_path.open(encoding="utf-8-sig", newline="") as handle:
            source_rows = {
                (row["campaign_name"], row["scenario_no"]): row
                for row in csv.DictReader(handle)
            }

        for campaign in payload["campaign_results"]:
            campaign_name = campaign["passport"]["campaign_name"]
            for scenario in campaign["scenarios"][:5]:
                source = source_rows[(campaign_name, scenario["scenario_id"])]
                orders = scenario["metrics"]["incremental_orders"]
                basket = scenario["metrics"]["avg_basket_bridge"]
                self.assertAlmostEqual(orders["p50"], float(source["orders_p50_mln"]))
                self.assertEqual(orders["unit"], "orders")
                self.assertAlmostEqual(
                    basket["p50"], float(source["basket_p50_mln"]) * 1_000_000.0
                )
                self.assertEqual(
                    basket["unit"], "turnover_bridge_from_avg_basket_rub"
                )

    @unittest.skipUnless(RUN_18.is_dir(), "canonical optimizer run 18 is unavailable")
    def test_worker_can_preserve_preexisting_job_identity(self) -> None:
        job_id = "job_1234567890ab"
        workflow_sha256 = "f" * 64

        payload = build_decision_result(
            RUN_18,
            job_id=job_id,
            workflow_config_sha256=workflow_sha256,
        ).to_dict()

        self.assertEqual(payload["job"]["job_id"], job_id)
        self.assertEqual(payload["job"]["workflow_config_sha256"], workflow_sha256)

    @unittest.skipUnless(RUN_17.is_dir(), "canonical optimizer run 17 is unavailable")
    def test_adapter_rejects_tampered_hashed_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            copied_run = Path(temporary_dir) / "run"
            shutil.copytree(RUN_17, copied_run)
            report_card = json.loads((copied_run / "marketer_report_card.json").read_text(encoding="utf-8"))
            scenario_path = copied_run / Path(report_card["scenario_results_csv"]).name
            scenario_path.write_text(
                scenario_path.read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(OptimizerResultAdapterError, "Hash mismatch"):
                build_decision_result(copied_run)

    def test_status_mapping_is_fail_closed(self) -> None:
        with self.assertRaisesRegex(OptimizerResultAdapterError, "Unmapped quality_status"):
            _status("quality_status", "Неизвестный новый статус")

    def test_optimizer_default_policy_is_v2(self) -> None:
        source = (
            PROJECT_ROOT / "02_Code" / "02_Budget_optimizer" / "budget_optimizer.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'config.get("decision_policy_file") or "optimizer_decision_policy_v2.yaml"',
            source,
        )


if __name__ == "__main__":
    unittest.main()
