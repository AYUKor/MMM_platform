from __future__ import annotations

import copy
import csv
import hashlib
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import Any, Mapping


WEB_APP_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(os.environ.get("MMM_EVIDENCE_PROJECT_ROOT", WEB_APP_DIR.parent)).resolve()
if str(WEB_APP_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_APP_DIR))

from adapters.optimizer_result_adapter import build_decision_result  # noqa: E402
from adapters.result_overview_adapter import build_result_overview  # noqa: E402
from contracts.job_result_view_v1 import (  # noqa: E402
    JobResultViewContractError,
    validate_job_result_view_payload,
)
from contracts.scenario_media_plan_v1 import (  # noqa: E402
    validate_scenario_media_plan_payload,
)
from services.job_result_view import (  # noqa: E402
    ResultProjectionStateError,
    UnsupportedMediaPlanQuery,
    build_job_result_view,
    build_scenario_media_plan,
)

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None


OVERVIEW_FIXTURE = WEB_APP_DIR / "tests" / "fixtures" / "result_overview_v1_real_sanitized.json"
RESULT_SCHEMA = WEB_APP_DIR / "contracts" / "job_result_view_v1.schema.json"
PLAN_SCHEMA = WEB_APP_DIR / "contracts" / "scenario_media_plan_v1.schema.json"
RUN_16 = (
    PROJECT_ROOT
    / "03_Outputs"
    / "02_Budget_optimizer_outputs"
    / "16_Budget_optimizer_14072026_agency_may_ts5_surgical_s6_v3"
)


def _opaque_id(prefix: str, seed: str) -> str:
    return f"{prefix}_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:20]}"


class SyntheticEvidence:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.job_id = "job_777777777777"
        self.overview = json.loads(OVERVIEW_FIXTURE.read_text(encoding="utf-8"))
        self.campaign = self.overview["campaigns"][0]
        self.result_id = self.overview["source_result_id"]
        self.job = {
            "job_id": self.job_id,
            "result_id": self.result_id,
            "status": {"code": "succeeded", "display_text": "Расчет завершен"},
            "finished_at_utc": "2026-07-16T10:00:00+00:00",
        }
        self.result = {"result_id": self.result_id, "artifacts": []}
        self.candidates = {scenario_id: f"synthetic-{scenario_id.lower()}" for scenario_id in ("S01", "S02", "S03", "S04", "S05", "S06")}
        self.raw_candidate = "synthetic-s06-best-raw"
        self.paths: dict[str, Path] = {}
        self.artifacts: dict[str, dict[str, Any]] = {}
        self._build()

    def _write_csv(self, kind: str, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
        path = self.root / f"{kind}.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        self._register(kind, path, "text/csv")

    def _write_xlsx(self) -> None:
        path = self.root / "marketer_report.xlsx"
        workbook_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="00_Итог" sheetId="1" r:id="rId1"/>'
            '<sheet name="01_Кампания" sheetId="2" r:id="rId2"/></sheets></workbook>'
        )
        with zipfile.ZipFile(path, "w") as workbook:
            workbook.writestr("xl/workbook.xml", workbook_xml)
        self._register(
            "marketer_report_xlsx",
            path,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def _register(self, kind: str, path: Path, media_type: str) -> None:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        artifact_id = _opaque_id("artifact", kind)
        item = {
            "artifact_id": artifact_id,
            "kind": kind,
            "display_name": {
                "marketer_report_xlsx": "Отчет для маркетолога",
                "scenario_results_csv": "Результаты сценариев",
                "decision_pool_csv": "Пул сценариев",
                "recommendations_csv": "Рекомендации",
                "recommended_allocations_csv": "Распределения бюджета",
            }[kind],
            "media_type": media_type,
            "sha256": digest,
            "size_bytes": path.stat().st_size,
            "storage_key": f"synthetic/{path.name}",
            "download_path": f"/api/v1/artifacts/{artifact_id}/download",
        }
        self.paths[artifact_id] = path
        self.artifacts[artifact_id] = item

    def _build(self) -> None:
        campaign_name = self.campaign["passport"]["campaign_name"]
        scenario_rows = [
            {
                "campaign_name": campaign_name,
                "scenario_no": scenario_id,
                "candidate_name": self.candidates[scenario_id],
            }
            for scenario_id in ("S01", "S02", "S03", "S04", "S05")
        ]
        self._write_csv(
            "scenario_results_csv",
            ["campaign_name", "scenario_no", "candidate_name"],
            scenario_rows,
        )
        self._write_csv(
            "decision_pool_csv",
            ["campaign_name", "scenario_no", "candidate_name"],
            [
                {
                    "campaign_name": campaign_name,
                    "scenario_no": "S06",
                    "candidate_name": self.candidates["S06"],
                }
            ],
        )
        self._write_csv(
            "recommendations_csv",
            ["campaign_name", "scenario_no", "candidate_name"],
            [
                {
                    "campaign_name": campaign_name,
                    "scenario_no": "S06",
                    "candidate_name": self.candidates["S06"],
                }
            ],
        )

        safe_ranks = {"S01": 2, "S02": 6, "S03": 5, "S04": 4, "S05": 3, "S06": 1}
        raw_ranks = {"S01": 7, "S02": 6, "S03": 5, "S04": 4, "S05": 3, "S06": 2}
        allocation_rows = []
        for scenario in self.campaign["scenarios"]:
            scenario_id = scenario["scenario_id"]
            allocation_rows.append(
                {
                    "source_campaign_name": campaign_name,
                    "candidate_name": self.candidates[scenario_id],
                    "optimizer_raw_rank": raw_ranks[scenario_id],
                    "optimizer_reliable_rank": safe_ranks[scenario_id],
                    "segment": self.campaign["passport"]["segments"][0],
                    "geo": self.campaign["passport"]["geographies"][0],
                    "channel": self.campaign["passport"]["source_channels"][0],
                    "budget_rub": scenario["budget"]["allocated_budget_rub"],
                    "allowed_use": "primary",
                    "optimizer_policy": "optimize",
                    "gate_reason_codes": "OK",
                }
            )
        allocation_rows.append(
            {
                "source_campaign_name": campaign_name,
                "candidate_name": self.raw_candidate,
                "optimizer_raw_rank": 1,
                "optimizer_reliable_rank": 7,
                "segment": self.campaign["passport"]["segments"][0],
                "geo": self.campaign["passport"]["geographies"][0],
                "channel": self.campaign["passport"]["source_channels"][0],
                "budget_rub": self.campaign["scenarios"][-1]["budget"]["allocated_budget_rub"],
                "allowed_use": "primary",
                "optimizer_policy": "optimize",
                "gate_reason_codes": "FUTURE_DAILY_SPEND_GT_2X_HIST_P95",
            }
        )
        self._write_csv(
            "recommended_allocations_csv",
            list(allocation_rows[0]),
            allocation_rows,
        )
        self._write_xlsx()
        self.overview["artifacts"] = list(self.artifacts.values())
        self.result["artifacts"] = [
            {key: value for key, value in item.items() if key != "download_path"}
            for item in self.artifacts.values()
        ]

        safe_id = _opaque_id("candidate", self.candidates["S06"])
        raw_id = _opaque_id("candidate", self.raw_candidate)
        self.campaign["scenario6"]["audit"]["best_safe_candidate_id"] = safe_id
        self.campaign["scenario6"]["audit"]["best_raw_candidate_id"] = raw_id
        self.campaign["scenario6"]["best_safe"]["candidate_id"] = safe_id
        self.campaign["scenario6"]["best_raw"]["candidate_id"] = raw_id
        self.campaign["scenario6"]["raw_differs_from_safe"] = True
        self.campaign["recommendation"]["scenario_id"] = "S06"
        self.campaign["statuses"]["optimizer_status"] = {
            "code": "best_safe_available",
            "display_text": "Автоматическое распределение доступно",
        }

    def resolve(self, artifact_id: str) -> tuple[Path, Mapping[str, Any]]:
        if artifact_id not in self.paths:
            raise FileNotFoundError(artifact_id)
        return self.paths[artifact_id], self.artifacts[artifact_id]

    def result_view(self) -> dict[str, Any]:
        return build_job_result_view(
            job_id=self.job_id,
            job=self.job,
            result=self.result,
            overview=self.overview,
            artifact_resolver=self.resolve,
        )

    def media_plan(self, **kwargs: Any) -> dict[str, Any]:
        return build_scenario_media_plan(
            job_id=self.job_id,
            job=self.job,
            result=self.result,
            overview=self.overview,
            artifact_resolver=self.resolve,
            scenario_id=kwargs.pop("scenario_id", "S06"),
            **kwargs,
        )


class ProductResultContractsV1Test(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.evidence = SyntheticEvidence(Path(self.temporary.name))
        self.result_schema = json.loads(RESULT_SCHEMA.read_text(encoding="utf-8"))
        self.plan_schema = json.loads(PLAN_SCHEMA.read_text(encoding="utf-8"))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _schema_valid(self, payload: Mapping[str, Any], schema: Mapping[str, Any]) -> None:
        if jsonschema is None:
            return
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(
            payload,
            schema,
            format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
        )

    def _public_texts(self, value: Any) -> list[str]:
        texts: list[str] = []
        if isinstance(value, Mapping):
            for key, nested in value.items():
                if key in {"title", "display_text", "recommended_action", "description", "decision_scope_text"} and isinstance(nested, str):
                    texts.append(nested)
                texts.extend(self._public_texts(nested))
        elif isinstance(value, list):
            for nested in value:
                texts.extend(self._public_texts(nested))
        return texts

    def test_result_view_is_schema_valid_and_exposes_honest_availability(self) -> None:
        payload = self.evidence.result_view()
        validate_job_result_view_payload(payload)
        self._schema_valid(payload, self.result_schema)
        self.assertEqual(payload["recommendation"]["scenario_id"], "S06")
        self.assertEqual(payload["recommendation"]["safe_rank"], 1)
        self.assertEqual(payload["recommendation"]["raw_rank"], 2)
        self.assertIsNone(payload["reliability"]["score"])
        self.assertEqual(
            {component["component_id"] for component in payload["reliability"]["components"]},
            {
                "historical_support",
                "model_support",
                "extrapolation",
                "posterior_uncertainty",
                "business_constraints",
                "data_completeness",
            },
        )
        scenario = payload["scenarios"][0]
        orders = scenario["metrics"]["incremental_orders"]
        budget = scenario["budget"]["allocated_budget_rub"]
        self.assertAlmostEqual(
            scenario["metrics"]["orders_per_100k_rub"]["p50"],
            orders["p50"] / budget * 100_000.0,
        )
        self.assertEqual(scenario["metrics"]["avg_basket_delta_rub"]["status"], "unavailable")
        self.assertIsNone(scenario["metrics"]["avg_basket_delta_rub"]["p50"])
        self.assertEqual(payload["report"]["status"], "ready")
        self.assertEqual([sheet["sheet_name"] for sheet in payload["report"]["sheets"]], ["00_Итог", "01_Кампания"])
        self.assertEqual(payload["media_plan"]["map"]["status"], "unavailable")
        self.assertIsNone(payload["media_plan"]["map"]["geo_points"])
        self.assertTrue(payload["best_raw"]["available"])
        self.assertEqual(payload["best_raw"]["raw_rank"], 1)
        self.assertEqual(payload["best_raw"]["blocking_cells_status"], "available")
        self.assertIn(
            "campaign_launch_threshold_unavailable",
            {warning["code"] for warning in payload["warnings"]},
        )
        self.assertNotIn("/Users/", json.dumps(payload, ensure_ascii=False))
        public_copy = "\n".join(self._public_texts(payload)).lower()
        for forbidden in (
            "backend",
            "model package",
            "model-aware validation",
            "daily flighting",
            "candidate_name",
            "optimizer_policy",
            "allowed_use",
        ):
            self.assertNotIn(forbidden, public_copy)

    def test_result_view_contract_rejects_core_invariant_failures(self) -> None:
        cases: list[tuple[str, Any]] = []
        duplicate = copy.deepcopy(self.evidence.result_view())
        duplicate["scenarios"][1]["scenario_id"] = "S01"
        cases.append(("ordered", duplicate))
        missing_source = copy.deepcopy(self.evidence.result_view())
        missing_source["scenarios"] = missing_source["scenarios"][1:]
        cases.append(("ordered", missing_source))
        quantile = copy.deepcopy(self.evidence.result_view())
        quantile["scenarios"][0]["metrics"]["incremental_turnover_rub"]["p10"] = (
            quantile["scenarios"][0]["metrics"]["incremental_turnover_rub"]["p90"] + 1
        )
        cases.append(("p10", quantile))
        rank = copy.deepcopy(self.evidence.result_view())
        rank["scenarios"][1]["safe_rank"] = rank["scenarios"][0]["safe_rank"]
        cases.append(("unique", rank))
        budget = copy.deepcopy(self.evidence.result_view())
        budget["overview"]["channel_summary"][0]["selected_budget_rub"] += 10
        cases.append(("reconcile", budget))
        recommendation = copy.deepcopy(self.evidence.result_view())
        recommendation["recommendation"]["scenario_id"] = "S05"
        cases.append(("Recommended", recommendation))
        path = copy.deepcopy(self.evidence.result_view())
        path["limitations"][0]["display_text"] = "/Users/example/private"
        cases.append(("Local path", path))
        for expected, payload in cases:
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(JobResultViewContractError, expected):
                    validate_job_result_view_payload(payload)

    def test_no_safe_recommendation_does_not_promote_source_or_raw_candidate(self) -> None:
        self.evidence.campaign["statuses"]["optimizer_status"] = {
            "code": "no_safe_candidate",
            "display_text": "Автоматическое распределение недоступно",
        }
        self.evidence.campaign["scenario6"]["best_safe"] = None
        self.evidence.campaign["scenario6"]["audit"]["best_safe_candidate_id"] = None
        payload = self.evidence.result_view()
        self.assertEqual(payload["recommendation"]["status"], "no_safe_recommendation")
        self.assertIsNone(payload["recommendation"]["scenario_id"])
        self.assertEqual(payload["overview"]["selected_scenario_id"], "S01")
        self.assertFalse(any(row["is_recommended"] for row in payload["scenarios"]))
        self.assertTrue(payload["best_raw"]["available"])
        self.assertIn(
            "automatic_reallocation_unavailable",
            {warning["code"] for warning in payload["warnings"]},
        )

    def test_report_unavailable_and_failed_contract_states_are_explicit(self) -> None:
        ready = self.evidence.result_view()
        unavailable = copy.deepcopy(ready)
        unavailable["report"].update(
            {
                "status": "unavailable",
                "display_text": "Excel-отчет недоступен.",
                "generated_at_utc": None,
                "artifact": None,
                "sheets": [],
            }
        )
        validate_job_result_view_payload(unavailable)
        self._schema_valid(unavailable, self.result_schema)

        failed = copy.deepcopy(unavailable)
        failed["report"].update(
            {
                "status": "failed",
                "display_text": "Не удалось подготовить Excel-отчет.",
            }
        )
        validate_job_result_view_payload(failed)
        self._schema_valid(failed, self.result_schema)

        report_id = next(
            artifact_id
            for artifact_id, item in self.evidence.artifacts.items()
            if item["kind"] == "marketer_report_xlsx"
        )
        self.evidence.overview["artifacts"] = [
            item
            for item in self.evidence.overview["artifacts"]
            if item["artifact_id"] != report_id
        ]
        self.evidence.result["artifacts"] = [
            item
            for item in self.evidence.result["artifacts"]
            if item["artifact_id"] != report_id
        ]
        with self.assertRaisesRegex(ResultProjectionStateError, "marketer_report_xlsx"):
            self.evidence.result_view()

    def test_selected_s6_can_use_canonical_recommendation_compatibility_fallback(self) -> None:
        pool_id = next(
            artifact_id
            for artifact_id, item in self.evidence.artifacts.items()
            if item["kind"] == "decision_pool_csv"
        )
        pool_path = self.evidence.paths[pool_id]
        pool_path.write_text("campaign_name,scenario_no,candidate_name\n", encoding="utf-8")
        pool_item = self.evidence.artifacts[pool_id]
        pool_item["sha256"] = hashlib.sha256(pool_path.read_bytes()).hexdigest()
        pool_item["size_bytes"] = pool_path.stat().st_size
        for item in self.evidence.result["artifacts"]:
            if item["artifact_id"] == pool_id:
                item["sha256"] = pool_item["sha256"]
                item["size_bytes"] = pool_item["size_bytes"]
        payload = self.evidence.result_view()
        self.assertEqual(payload["recommendation"]["scenario_id"], "S06")
        self.assertEqual(payload["recommendation"]["safe_rank"], 1)

    def test_media_plan_paginates_filters_and_reconciles_backend_aggregates(self) -> None:
        payload = self.evidence.media_plan(page=1, page_size=1)
        validate_scenario_media_plan_payload(payload)
        self._schema_valid(payload, self.plan_schema)
        self.assertEqual(payload["pagination"], {"page": 1, "page_size": 1, "total_rows": 1, "total_pages": 1})
        self.assertEqual(payload["grain"], "geo_channel_total")
        self.assertEqual(payload["aggregates"]["by_date"]["status"], "unavailable")
        self.assertEqual(payload["aggregates"]["channel_date_matrix"]["status"], "unavailable")
        self.assertEqual(payload["aggregates"]["geo_channel_matrix"]["status"], "ready")
        self.assertAlmostEqual(
            payload["totals"]["selected_budget_rub"]
            + payload["totals"]["unallocated_budget_rub"],
            payload["totals"]["requested_budget_rub"],
        )
        self.assertAlmostEqual(
            sum(row["selected_budget_rub"] for row in payload["aggregates"]["by_channel"]),
            payload["totals"]["selected_budget_rub"],
        )
        filtered = self.evidence.media_plan(channel="UNKNOWN_CHANNEL")
        self.assertEqual(filtered["pagination"]["total_rows"], 0)
        self.assertEqual(filtered["rows"], [])
        self.assertEqual(filtered["filtered_totals"]["selected_budget_rub"], 0)

    def test_media_plan_rejects_unavailable_scenario_date_and_tampered_artifact(self) -> None:
        with self.assertRaises(UnsupportedMediaPlanQuery) as invalid_scenario:
            self.evidence.media_plan(scenario_id="S99")
        self.assertEqual(
            str(invalid_scenario.exception),
            "Не удалось определить сценарий для просмотра медиаплана.",
        )
        with self.assertRaises(UnsupportedMediaPlanQuery) as invalid_page:
            self.evidence.media_plan(page=0)
        self.assertEqual(
            str(invalid_page.exception),
            "Номер страницы и количество строк на странице заполнены некорректно.",
        )
        with self.assertRaises(UnsupportedMediaPlanQuery) as invalid_page_size:
            self.evidence.media_plan(page_size=501)
        self.assertEqual(
            str(invalid_page_size.exception),
            "Номер страницы и количество строк на странице заполнены некорректно.",
        )
        with self.assertRaises(UnsupportedMediaPlanQuery) as invalid_date:
            self.evidence.media_plan(date="2026-08-01")
        self.assertEqual(str(invalid_date.exception), "Дата заполнена некорректно.")
        self.evidence.campaign["scenarios"][-1]["available"] = False
        with self.assertRaisesRegex(UnsupportedMediaPlanQuery, "недоступен"):
            self.evidence.media_plan(scenario_id="S06")
        self.evidence.campaign["scenarios"][-1]["available"] = True
        allocation_artifact = next(
            item
            for item in self.evidence.artifacts.values()
            if item["kind"] == "recommended_allocations_csv"
        )
        self.evidence.paths[allocation_artifact["artifact_id"]].write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(ResultProjectionStateError, "integrity|reconcile"):
            self.evidence.result_view()

    @unittest.skipUnless(RUN_16.is_dir(), "canonical optimizer run 16 is unavailable")
    def test_canonical_run_16_projects_without_optimizer_rerun(self) -> None:
        result = build_decision_result(RUN_16, job_id="job_777777777777").to_dict()
        overview = build_result_overview(RUN_16, job_id="job_777777777777")
        artifacts = {item["artifact_id"]: item for item in overview["artifacts"]}

        def resolve(artifact_id: str) -> tuple[Path, Mapping[str, Any]]:
            item = artifacts[artifact_id]
            return RUN_16 / Path(item["storage_key"]).name, item

        job = {
            "job_id": "job_777777777777",
            "result_id": result["result_id"],
            "status": {"code": "succeeded"},
            "finished_at_utc": "2026-07-16T10:00:00+00:00",
        }
        payload = build_job_result_view(
            job_id=job["job_id"],
            job=job,
            result=result,
            overview=overview,
            artifact_resolver=resolve,
        )
        self._schema_valid(payload, self.result_schema)
        self.assertEqual(payload["recommendation"]["scenario_id"], "S06")
        self.assertEqual(len(payload["overview"]["geo_channel_summary"]), 537)
        self.assertNotIn(
            "blocked",
            {row["quality_status"] for row in payload["overview"]["geo_channel_summary"]},
        )
        plan = build_scenario_media_plan(
            job_id=job["job_id"],
            job=job,
            result=result,
            overview=overview,
            artifact_resolver=resolve,
            scenario_id="S06",
            page=1,
            page_size=100,
        )
        self.assertEqual(plan["pagination"]["total_rows"], 537)
        self.assertAlmostEqual(
            plan["totals"]["selected_budget_rub"],
            payload["scenarios"][-1]["budget"]["allocated_budget_rub"],
            places=2,
        )


if __name__ == "__main__":
    unittest.main()
