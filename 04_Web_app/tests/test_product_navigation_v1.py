from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path


WEB_APP_DIR = Path(__file__).resolve().parents[1]
if str(WEB_APP_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_APP_DIR))

from contracts.calculation_history_v1 import (  # noqa: E402
    CalculationHistoryContractError,
    load_calculation_history_schema,
    validate_calculation_history_payload,
)
from contracts.help_catalog_v1 import (  # noqa: E402
    HelpCatalogContractError,
    load_help_catalog_schema,
    validate_help_catalog_payload,
)
from contracts.model_overview_v1 import (  # noqa: E402
    ModelOverviewContractError,
    load_model_overview_schema,
    validate_model_overview_payload,
)
from contracts.workspace_home_v1 import (  # noqa: E402
    WorkspaceHomeContractError,
    load_workspace_home_schema,
    validate_workspace_home_payload,
)
from services.product_navigation import (  # noqa: E402
    ProductNavigationQueryError,
    build_calculation_history,
    build_model_overview,
    build_workspace_home,
    load_help_catalog,
)


FIXTURES = WEB_APP_DIR / "tests" / "fixtures"
NOW = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class NavigationFixture:
    def __init__(self) -> None:
        lifecycle = _load_json(
            FIXTURES / "application_lifecycle_v1_happy_path_synthetic.json"
        )
        self.base_job = lifecycle["jobs"][0]
        self.base_campaign = lifecycle["validations"][0]["campaigns"][0]
        self.base_validation = lifecycle["validations"][0]
        self.result = _load_json(FIXTURES / "decision_result_v1_real_sanitized.json")
        self.overview = _load_json(FIXTURES / "result_overview_v1_real_sanitized.json")
        self.passport = _load_json(FIXTURES / "model_passport_v1_synthetic.json")
        self.resources: dict[tuple[str, str], dict] = {}
        self.validations: dict[str, dict] = {}

    def record(
        self,
        index: int,
        *,
        status: str,
        created_at: str,
        finished_at: str | None,
        campaign_name: str,
        publish_result: bool = False,
        publish_report: bool = True,
    ) -> dict:
        job = copy.deepcopy(self.base_job)
        job_id = f"job_{index:012x}"
        validation_id = f"validation_{index:012x}"
        job.update(
            {
                "job_id": job_id,
                "validation_id": validation_id,
                "status": {"code": status, "display_text": status},
                "created_at_utc": created_at,
                "finished_at_utc": finished_at,
                "result_id": f"result_{index:012x}" if status == "succeeded" else None,
            }
        )
        campaign = copy.deepcopy(self.base_campaign)
        campaign["campaign_id"] = f"campaign_{index:012x}"
        campaign["campaign_name"] = campaign_name
        validation = copy.deepcopy(self.base_validation)
        validation["validation_id"] = validation_id
        validation["campaigns"] = [campaign]
        self.validations[validation_id] = validation
        if publish_result:
            overview = copy.deepcopy(self.overview)
            if not publish_report:
                overview["artifacts"] = [
                    item
                    for item in overview["artifacts"]
                    if item["kind"] != "marketer_report_xlsx"
                ]
            self.resources[(job_id, "result")] = copy.deepcopy(self.result)
            self.resources[(job_id, "overview")] = overview
        return {"job": job, "campaigns": [campaign]}

    def resource_reader(self, job_id: str, resource: str) -> dict:
        try:
            return self.resources[(job_id, resource)]
        except KeyError as exc:
            raise FileNotFoundError(f"{job_id}/{resource}") from exc

    def validation_reader(self, validation_id: str) -> dict:
        try:
            return self.validations[validation_id]
        except KeyError as exc:
            raise FileNotFoundError(validation_id) from exc


class ProductNavigationProjectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = NavigationFixture()
        self.model = build_model_overview(
            self.fixture.passport,
            registry_root=None,
            registry_channel="preprod",
            now=NOW,
            record_origin="synthetic_fixture",
        )

    def test_all_contracts_are_schema_valid(self) -> None:
        record = self.fixture.record(
            1,
            status="succeeded",
            created_at="2026-07-15T08:00:00+00:00",
            finished_at="2026-07-15T08:02:00+00:00",
            campaign_name="Кампания A",
            publish_result=True,
        )
        history = build_calculation_history(
            [record],
            resource_reader=self.fixture.resource_reader,
            validation_reader=self.fixture.validation_reader,
            now=NOW,
            record_origin="synthetic_fixture",
        )
        home = build_workspace_home(
            [record],
            model_overview=self.model,
            resource_reader=self.fixture.resource_reader,
            validation_reader=self.fixture.validation_reader,
            progress_view_builder=lambda _: {},
            now=NOW,
            record_origin="synthetic_fixture",
        )
        help_catalog = load_help_catalog()
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema is optional in the source-only runtime")
        pairs = (
            (home, load_workspace_home_schema()),
            (history, load_calculation_history_schema()),
            (self.model, load_model_overview_schema()),
            (help_catalog, load_help_catalog_schema()),
        )
        for payload, schema in pairs:
            with self.subTest(contract=payload["contract_name"]):
                jsonschema.Draft202012Validator(schema).validate(payload)

    def test_home_projects_active_recent_failures_and_missing_report(self) -> None:
        active = self.fixture.record(
            1,
            status="running",
            created_at="2026-07-17T10:00:00+00:00",
            finished_at=None,
            campaign_name="Активная кампания",
        )
        success = self.fixture.record(
            2,
            status="succeeded",
            created_at="2026-07-16T08:00:00+00:00",
            finished_at="2026-07-16T08:03:00+00:00",
            campaign_name="Готовая кампания",
            publish_result=True,
            publish_report=False,
        )
        failure = self.fixture.record(
            3,
            status="failed",
            created_at="2026-07-15T08:00:00+00:00",
            finished_at="2026-07-15T08:01:00+00:00",
            campaign_name="Кампания с ошибкой",
        )

        def progress(_: str) -> dict:
            return {
                "current_stage_id": "P04",
                "stages": [
                    {
                        "stage_id": "P04",
                        "title": "Рассчитываем контрольные сценарии",
                        "status": "active",
                        "display_text": "Идет расчет сценариев",
                    }
                ],
            }

        payload = build_workspace_home(
            [failure, active, success],
            model_overview=self.model,
            resource_reader=self.fixture.resource_reader,
            validation_reader=self.fixture.validation_reader,
            progress_view_builder=progress,
            now=NOW,
            record_origin="synthetic_fixture",
        )
        self.assertEqual(payload["summary"], {
            "running": 1,
            "queued": 0,
            "completed_30d": 1,
            "failed_30d": 1,
        })
        self.assertEqual(payload["active_calculations"][0]["current_stage"]["stage_id"], "P04")
        self.assertFalse(payload["recent_calculations"][0]["report_available"])
        self.assertEqual(
            {warning["code"] for warning in payload["warnings"]},
            {"recent_calculation_failures", "recent_report_unavailable"},
        )

    def test_home_empty_and_model_unavailable_are_explicit(self) -> None:
        model = build_model_overview(
            None,
            registry_root=None,
            registry_channel="preprod",
            now=NOW,
            record_origin="synthetic_fixture",
        )
        payload = build_workspace_home(
            [],
            model_overview=model,
            resource_reader=self.fixture.resource_reader,
            validation_reader=self.fixture.validation_reader,
            progress_view_builder=lambda _: {},
            now=NOW,
            record_origin="synthetic_fixture",
        )
        self.assertEqual(payload["summary"], {
            "running": 0,
            "queued": 0,
            "completed_30d": 0,
            "failed_30d": 0,
        })
        self.assertEqual(payload["model"]["status"]["code"], "unavailable")
        self.assertIsNone(payload["model"]["model_id"])
        self.assertEqual(payload["warnings"][0]["code"], "active_model_unavailable")

    def test_history_pagination_search_filters_dates_and_sorting(self) -> None:
        records = [
            self.fixture.record(
                1,
                status="succeeded",
                created_at="2026-07-14T08:00:00+00:00",
                finished_at="2026-07-14T08:05:00+00:00",
                campaign_name="Бета",
                publish_result=True,
            ),
            self.fixture.record(
                2,
                status="running",
                created_at="2026-07-16T08:00:00+00:00",
                finished_at=None,
                campaign_name="Альфа активная",
            ),
            self.fixture.record(
                3,
                status="failed",
                created_at="2026-07-15T08:00:00+00:00",
                finished_at="2026-07-15T08:01:00+00:00",
                campaign_name="Альфа ошибка",
            ),
        ]
        first_page = build_calculation_history(
            records,
            resource_reader=self.fixture.resource_reader,
            validation_reader=self.fixture.validation_reader,
            page=1,
            page_size=2,
            sort="created_desc",
            now=NOW,
            record_origin="synthetic_fixture",
        )
        self.assertEqual(first_page["pagination"]["total_pages"], 2)
        self.assertEqual([item["job_id"] for item in first_page["items"]], ["job_000000000002", "job_000000000003"])
        filtered = build_calculation_history(
            records,
            resource_reader=self.fixture.resource_reader,
            validation_reader=self.fixture.validation_reader,
            status="active",
            search="альфа",
            created_from=date(2026, 7, 16),
            created_to=date(2026, 7, 16),
            sort="campaign_asc",
            now=NOW,
            record_origin="synthetic_fixture",
        )
        self.assertEqual(filtered["pagination"]["total_items"], 1)
        self.assertEqual(filtered["items"][0]["status"], "running")
        self.assertEqual(filtered["summary"]["all"], 3)
        empty = build_calculation_history(
            records,
            resource_reader=self.fixture.resource_reader,
            validation_reader=self.fixture.validation_reader,
            search="нет такой кампании",
            now=NOW,
            record_origin="synthetic_fixture",
        )
        self.assertEqual(empty["items"], [])
        with self.assertRaises(ProductNavigationQueryError):
            build_calculation_history(
                records,
                resource_reader=self.fixture.resource_reader,
                page_size=101,
            )

    def test_model_uses_real_registry_entries_and_honest_limitations(self) -> None:
        active_id = self.fixture.passport["package"]["package_id"]
        previous_id = "pkg_3333333333333333_4444444444444444"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for package_id, registered_at in (
                (previous_id, "2026-07-10T10:00:00+00:00"),
                (active_id, "2026-07-15T10:00:00+00:00"),
            ):
                _write_json(
                    root / "registrations" / f"{package_id}.json",
                    {
                        "package_id": package_id,
                        "model_run_id": f"run_{package_id[-4:]}",
                        "package_stage": "posterior_ready",
                        "activation_status_at_registration": "preprod_restricted",
                        "registered_at_utc": registered_at,
                    },
                )
            _write_json(
                root / "channels" / "preprod.json",
                {
                    "package_id": active_id,
                    "updated_at_utc": "2026-07-15T11:00:00+00:00",
                },
            )
            payload = build_model_overview(
                self.fixture.passport,
                registry_root=root,
                registry_channel="preprod",
                now=NOW,
                record_origin="synthetic_fixture",
            )
        self.assertEqual(payload["active_model"]["published_at_utc"], "2026-07-15T11:00:00+00:00")
        self.assertEqual(len(payload["versions"]), 2)
        self.assertEqual(
            [item["model_id"] for item in payload["versions"] if item["status"] == "active"],
            [active_id],
        )
        serialized = json.dumps(payload, ensure_ascii=False).casefold()
        self.assertNotIn("quality_score", serialized)
        self.assertNotIn("reliability_score\"", serialized)
        limitation_codes = {item["code"] for item in payload["limitations"]}
        self.assertIn("sealed_oot_unavailable", limitation_codes)
        self.assertIn("allocation_only", limitation_codes)

        blocked_passport = copy.deepcopy(self.fixture.passport)
        blocked_passport["serving"]["calculation_allowed"] = False
        blocked = build_model_overview(
            blocked_passport,
            registry_root=None,
            registry_channel="preprod",
            now=NOW,
            record_origin="synthetic_fixture",
        )
        self.assertEqual(
            {item["status"] for item in blocked["capabilities"]},
            {"unavailable"},
        )

    def test_help_catalog_is_complete_and_deterministic(self) -> None:
        first = load_help_catalog()
        second = load_help_catalog()
        self.assertEqual(first, second)
        self.assertEqual(len(first["sections"]), 9)
        self.assertEqual(
            [section["order"] for section in first["sections"]],
            list(range(1, 10)),
        )
        serialized = json.dumps(first, ensure_ascii=False).casefold()
        self.assertNotIn("<script", serialized)
        self.assertNotIn("/users/", serialized)


class ProductNavigationContractGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        fixture = NavigationFixture()
        record = fixture.record(
            1,
            status="succeeded",
            created_at="2026-07-15T08:00:00+00:00",
            finished_at="2026-07-15T08:02:00+00:00",
            campaign_name="Кампания A",
            publish_result=True,
        )
        self.history = build_calculation_history(
            [record],
            resource_reader=fixture.resource_reader,
            validation_reader=fixture.validation_reader,
            now=NOW,
            record_origin="synthetic_fixture",
        )
        self.model = build_model_overview(
            fixture.passport,
            registry_root=None,
            registry_channel="preprod",
            now=NOW,
            record_origin="synthetic_fixture",
        )
        self.home = build_workspace_home(
            [record],
            model_overview=self.model,
            resource_reader=fixture.resource_reader,
            validation_reader=fixture.validation_reader,
            progress_view_builder=lambda _: {},
            now=NOW,
            record_origin="synthetic_fixture",
        )
        self.help = load_help_catalog()

    def test_wrong_versions_and_extra_keys_are_rejected(self) -> None:
        cases = (
            (self.home, validate_workspace_home_payload, WorkspaceHomeContractError),
            (self.history, validate_calculation_history_payload, CalculationHistoryContractError),
            (self.model, validate_model_overview_payload, ModelOverviewContractError),
            (self.help, validate_help_catalog_payload, HelpCatalogContractError),
        )
        for payload, validator, error in cases:
            with self.subTest(contract=payload["contract_name"], mutation="version"):
                value = copy.deepcopy(payload)
                value["schema_version"] = "9.9.9"
                with self.assertRaises(error):
                    validator(value)
            with self.subTest(contract=payload["contract_name"], mutation="extra"):
                value = copy.deepcopy(payload)
                value["internal_debug"] = True
                with self.assertRaises(error):
                    validator(value)

    def test_paths_timestamps_duplicates_and_relations_are_rejected(self) -> None:
        home = copy.deepcopy(self.home)
        home["model"]["description"] = "/Users/example/private-model"
        with self.assertRaises(WorkspaceHomeContractError):
            validate_workspace_home_payload(home)
        home = copy.deepcopy(self.home)
        home["updated_at_utc"] = "2026-07-17"
        with self.assertRaises(WorkspaceHomeContractError):
            validate_workspace_home_payload(home)
        home = copy.deepcopy(self.home)
        home["summary"]["queued"] = 1
        with self.assertRaises(WorkspaceHomeContractError):
            validate_workspace_home_payload(home)
        home = copy.deepcopy(self.home)
        home["quick_actions"][0]["description"] = "backend details"
        with self.assertRaises(WorkspaceHomeContractError):
            validate_workspace_home_payload(home)

        history = copy.deepcopy(self.history)
        history["items"].append(copy.deepcopy(history["items"][0]))
        history["pagination"]["total_items"] = 2
        history["pagination"]["total_pages"] = 1
        with self.assertRaises(CalculationHistoryContractError):
            validate_calculation_history_payload(history)
        history = copy.deepcopy(self.history)
        history["items"][0]["progress_path"] = "/Users/example/job"
        with self.assertRaises(CalculationHistoryContractError):
            validate_calculation_history_payload(history)
        history = copy.deepcopy(self.history)
        history["items"][0]["result_available"] = False
        with self.assertRaises(CalculationHistoryContractError):
            validate_calculation_history_payload(history)
        history = copy.deepcopy(self.history)
        history["items"][0]["status_display_text"] = "worker failed"
        with self.assertRaises(CalculationHistoryContractError):
            validate_calculation_history_payload(history)

        model = copy.deepcopy(self.model)
        model["versions"] = []
        with self.assertRaises(ModelOverviewContractError):
            validate_model_overview_payload(model)
        model = copy.deepcopy(self.model)
        model["active_model"]["description"] = "backend model package"
        with self.assertRaises(ModelOverviewContractError):
            validate_model_overview_payload(model)
        model = copy.deepcopy(self.model)
        model["quality_score"] = 10
        with self.assertRaises(ModelOverviewContractError):
            validate_model_overview_payload(model)

        help_catalog = copy.deepcopy(self.help)
        help_catalog["sections"][0]["articles"][0]["body"][0] = {
            "block_type": "paragraph",
            "text": "<script>alert(1)</script>",
        }
        with self.assertRaises(HelpCatalogContractError):
            validate_help_catalog_payload(help_catalog)
        help_catalog = copy.deepcopy(self.help)
        help_catalog["sections"][0]["articles"][0]["summary"] = "backend details"
        with self.assertRaises(HelpCatalogContractError):
            validate_help_catalog_payload(help_catalog)
        help_catalog = copy.deepcopy(self.help)
        help_catalog["sections"][0]["articles"][0]["related_article_ids"] = [
            "unknown_article"
        ]
        with self.assertRaises(HelpCatalogContractError):
            validate_help_catalog_payload(help_catalog)
        help_catalog = copy.deepcopy(self.help)
        help_catalog["sections"][1]["articles"][0]["article_id"] = "quick_start"
        with self.assertRaises(HelpCatalogContractError):
            validate_help_catalog_payload(help_catalog)


if __name__ == "__main__":
    unittest.main()
