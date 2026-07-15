from __future__ import annotations

import json
import os
import re
import sys
import unittest
from pathlib import Path
from typing import Any, Iterator


WEB_APP_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(os.environ.get("MMM_EVIDENCE_PROJECT_ROOT", WEB_APP_DIR.parent)).resolve()
if str(WEB_APP_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_APP_DIR))

from adapters.result_overview_adapter import (  # noqa: E402
    ResultOverviewAdapterError,
    build_result_overview,
    validate_result_overview,
)

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None


SCHEMA_PATH = WEB_APP_DIR / "contracts" / "result_overview_v1.schema.json"
FIXTURE_PATH = WEB_APP_DIR / "tests" / "fixtures" / "result_overview_v1_real_sanitized.json"
OUTPUTS = PROJECT_ROOT / "03_Outputs" / "02_Budget_optimizer_outputs"
RUN_16 = OUTPUTS / "16_Budget_optimizer_14072026_agency_may_ts5_surgical_s6_v3"
RUN_17 = OUTPUTS / "17_Budget_optimizer_14072026_agency_may_tsx_surgical_s6_v3"
RUN_18 = OUTPUTS / "18_Budget_optimizer_14072026_agency_gender_boost_contract_v1"


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for nested in value.values():
            yield from _strings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _strings(nested)
    elif isinstance(value, str):
        yield value


class ResultOverviewV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def _assert_schema_valid(self, payload: dict[str, Any]) -> None:
        if jsonschema is None:
            return
        jsonschema.Draft202012Validator.check_schema(self.schema)
        jsonschema.validate(
            payload,
            self.schema,
            format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
        )

    def test_sanitized_fixture_is_schema_valid_and_browser_safe(self) -> None:
        validate_result_overview(self.fixture)
        self._assert_schema_valid(self.fixture)
        self.assertEqual(self.fixture["contract_name"], "result_overview_v1")
        self.assertEqual(self.fixture["schema_version"], "1.0.0")
        self.assertEqual(self.fixture["result_origin"], "sanitized_fixture")
        serialized = json.dumps(self.fixture, ensure_ascii=False)
        self.assertNotIn("/Users/", serialized)
        self.assertNotIn("file://", serialized)
        self.assertNotIn("Майские", serialized)
        self.assertNotIn("МОСКВА", serialized)
        self.assertFalse(any("__scenario6_" in value for value in _strings(self.fixture)))
        for artifact in self.fixture["artifacts"]:
            self.assertRegex(
                artifact["download_path"],
                r"^/api/v1/artifacts/[a-z][a-z0-9_]*_[0-9a-f]{12,64}/download$",
            )

    @unittest.skipUnless(RUN_16.is_dir(), "canonical optimizer run 16 is unavailable")
    def test_run_16_exposes_roas_quantiles_and_allocation_delta(self) -> None:
        payload = build_result_overview(RUN_16)
        self._assert_schema_valid(payload)
        campaign = payload["campaigns"][0]
        self.assertEqual(
            [scenario["scenario_id"] for scenario in campaign["scenarios"]],
            ["S01", "S02", "S03", "S04", "S05", "S06"],
        )
        for scenario in campaign["scenarios"]:
            if not scenario["available"]:
                continue
            turnover = scenario["metrics"]["incremental_turnover"]
            roas = scenario["metrics"]["turnover_roas"]
            budget = scenario["budget"]["allocated_budget_rub"]
            self.assertAlmostEqual(roas["p50"], turnover["p50"] / budget)
            self.assertLessEqual(roas["p10"], roas["p50"])
            self.assertLessEqual(roas["p50"], roas["p90"])
            self.assertEqual(
                scenario["metrics"]["incremental_orders_usage"], "diagnostic_only"
            )
        moved = 0.5 * sum(
            abs(line["delta_budget_rub"])
            for line in campaign["allocation_comparison"]
        )
        self.assertAlmostEqual(
            moved,
            campaign["recommendation"]["versus_uploaded_plan"]["moved_budget_rub"],
        )
        self.assertTrue(campaign["scenario6"]["raw_differs_from_safe"])

    @unittest.skipUnless(RUN_17.is_dir(), "canonical optimizer run 17 is unavailable")
    def test_run_17_keeps_gate_blocked_scenario6_explicit(self) -> None:
        payload = build_result_overview(RUN_17)
        self._assert_schema_valid(payload)
        campaign = payload["campaigns"][0]
        self.assertFalse(campaign["scenarios"][-1]["available"])
        self.assertIsNone(campaign["scenario6"]["best_raw"])
        self.assertIsNone(campaign["scenario6"]["best_safe"])
        self.assertEqual(
            campaign["scenario6"]["audit"]["run_status"]["code"],
            "gate_policy_blocked",
        )

    @unittest.skipUnless(RUN_18.is_dir(), "canonical optimizer run 18 is unavailable")
    def test_run_18_supports_multiple_campaigns_without_raw_names(self) -> None:
        payload = build_result_overview(RUN_18)
        self._assert_schema_valid(payload)
        self.assertEqual(len(payload["campaigns"]), 2)
        self.assertFalse(any("__scenario" in value for value in _strings(payload)))
        for campaign in payload["campaigns"]:
            self.assertTrue(campaign["allocation_comparison"])
            for line in campaign["allocation_comparison"]:
                self.assertAlmostEqual(
                    line["delta_budget_rub"],
                    line["recommended_budget_rub"] - line["uploaded_budget_rub"],
                )

    def test_validator_rejects_noncanonical_download_path(self) -> None:
        payload = json.loads(json.dumps(self.fixture))
        payload["artifacts"][0]["download_path"] = "/tmp/report.xlsx"
        with self.assertRaisesRegex(ResultOverviewAdapterError, "download path"):
            validate_result_overview(payload)


if __name__ == "__main__":
    unittest.main()
