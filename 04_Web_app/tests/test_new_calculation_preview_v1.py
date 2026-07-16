from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

from openpyxl import load_workbook


WEB_APP_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = WEB_APP_DIR.parent
if str(WEB_APP_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_APP_DIR))

from api.http_smoke import LocalApiState  # noqa: E402
from contracts.application_lifecycle_v1 import (  # noqa: E402
    BudgetByChannelPreview,
    BudgetByGeoPreview,
    ChannelFlightingPreview,
    LifecycleStatus,
    SamplingProfile,
    ValidationPreview,
    ValidationPreviewCheck,
    ValidationResultV1,
    parse_lifecycle_contract,
)
from services.campaign_template import build_campaign_plan_template  # noqa: E402
from services.local_campaign_service import (  # noqa: E402
    MAX_XLSX_WORKBOOK_XML_BYTES,
    LocalCampaignService,
    LocalCampaignServiceSettings,
    _xlsx_sheet_names,
)


HAPPY_FIXTURE = (
    WEB_APP_DIR
    / "tests"
    / "fixtures"
    / "application_lifecycle_v1_happy_path_synthetic.json"
)


class _DeferredExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[Callable[..., Any], tuple[Any, ...]]] = []

    def submit(self, function: Callable[..., Any], *args: Any) -> None:
        self.calls.append((function, args))

    def run_next(self) -> None:
        function, args = self.calls.pop(0)
        function(*args)


class NewCalculationPreviewV1Test(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.executor = _DeferredExecutor()
        self.state = LocalApiState(root / "state")
        self.settings = LocalCampaignServiceSettings(
            project_root=PROJECT_ROOT,
            artifact_root=root / "artifacts",
            validation_runtime_root=root / "runtime" / "validations",
            registry_root=root / "registry",
            registry_channel="preprod",
            expected_package_id="pkg_synthetic_preview",
            optimizer_policy_path=(
                PROJECT_ROOT
                / "02_Code"
                / "02_Budget_optimizer"
                / "optimizer_decision_policy_v2.yaml"
            ),
            business_policy_path=(
                PROJECT_ROOT
                / "02_Code"
                / "02_Budget_optimizer"
                / "business_threshold_policy_v1.yaml"
            ),
            default_sampling=SamplingProfile(64, 16, 32, 42, 10042),
        )
        self.service = LocalCampaignService(
            self.settings,
            self.state,
            self.executor,
            lambda _: (_ for _ in ()).throw(AssertionError("job must not be submitted")),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _upload_and_parse(self, filename: str, content: bytes) -> dict[str, Any]:
        upload, _ = self.service.create_upload(
            filename=filename,
            content=content,
            idempotency_key=f"preview-upload-{filename}-0001",
            actor_id="actor_11111111111111111111",
        )
        self.executor.run_next()
        return self.state.read_upload(upload["upload_id"])

    def _validate_count(self, upload: dict[str, Any]) -> dict[str, Any]:
        validation, _ = self.service.request_validation(
            upload["upload_id"],
            f"preview-validation-{upload['upload_id']}",
        )
        self.executor.run_next()
        return self.state.read_validation(validation["validation_id"])

    def test_csv_and_xlsx_are_accepted_while_xls_and_tsv_are_rejected(self) -> None:
        csv_content = (
            "campaign_name,segment,geo,channel,start_date,end_date,budget_rub\n"
            "Synthetic A,SYNTHETIC_SEGMENT,SYNTHETIC_GEO,SYNTHETIC_CHANNEL,"
            "2026-01-01,2026-01-02,1000\n"
        ).encode("utf-8")
        csv_upload, _ = self.service.create_upload(
            filename="campaign.csv",
            content=csv_content,
            idempotency_key="preview-csv-upload-0001",
            actor_id="actor_11111111111111111111",
        )
        xlsx_upload, _ = self.service.create_upload(
            filename="campaign.xlsx",
            content=build_campaign_plan_template(),
            idempotency_key="preview-xlsx-upload-0001",
            actor_id="actor_11111111111111111111",
        )
        self.executor.run_next()
        self.executor.run_next()
        parsed_csv = self.state.read_upload(csv_upload["upload_id"])
        parsed_xlsx = self.state.read_upload(xlsx_upload["upload_id"])
        self.assertEqual(parsed_csv["status"]["code"], "parsed")
        self.assertEqual(parsed_xlsx["status"]["code"], "parsed")
        for filename in ("campaign.xls", "campaign.tsv"):
            with self.subTest(filename=filename), self.assertRaisesRegex(
                ValueError,
                "CSV и XLSX",
            ):
                self.service.create_upload(
                    filename=filename,
                    content=b"synthetic",
                    idempotency_key=f"preview-rejected-{filename}-0001",
                    actor_id="actor_11111111111111111111",
                )

    def test_blank_campaign_name_is_rejected_instead_of_collapsing_to_fallback(self) -> None:
        content = (
            "campaign_name,segment,geo,channel,start_date,end_date,budget_rub\n"
            ",SYNTHETIC_SEGMENT,SYNTHETIC_GEO,SYNTHETIC_CHANNEL,"
            "2026-01-01,2026-01-02,1000\n"
        ).encode("utf-8")
        upload = self._upload_and_parse("blank-name.csv", content)
        self.assertEqual(upload["status"]["code"], "rejected")
        self.assertIsNone(upload["detected_campaigns_n"])

    def test_zero_campaigns_block_validation_and_job_creation(self) -> None:
        header_only = (
            "campaign_name,segment,geo,channel,start_date,end_date,budget_rub\n"
        ).encode("utf-8")
        upload = self._upload_and_parse("zero.csv", header_only)
        self.assertEqual(upload["detected_campaigns_n"], 0)
        validation = self._validate_count(upload)
        self.assertEqual(validation["status"]["code"], "invalid")
        self.assertFalse(validation["job_creation_allowed"])
        self.assertEqual(
            validation["blocking_errors"][0]["code"],
            "CAMPAIGN_COUNT_NOT_ONE",
        )
        with self.assertRaises(ValueError):
            self.service.create_job(
                validation["validation_id"],
                "preview-zero-job-0001",
            )

    def test_multiple_campaigns_are_not_auto_split_or_sent_to_model_validation(self) -> None:
        content = (
            "campaign_name,segment,geo,channel,start_date,end_date,budget_rub\n"
            "Synthetic A,SYNTHETIC_SEGMENT,SYNTHETIC_GEO,SYNTHETIC_CHANNEL,2026-01-01,2026-01-02,1000\n"
            "Synthetic B,SYNTHETIC_SEGMENT,SYNTHETIC_GEO,SYNTHETIC_CHANNEL,2026-01-01,2026-01-02,2000\n"
        ).encode("utf-8")
        upload = self._upload_and_parse("multiple.csv", content)
        self.assertEqual(upload["detected_campaigns_n"], 2)
        validation = self._validate_count(upload)
        self.assertEqual(validation["status"]["code"], "invalid")
        self.assertFalse(validation["job_creation_allowed"])
        self.assertIn("не разделяет", validation["blocking_errors"][0]["display_text"])
        self.assertEqual(self.executor.calls, [])

    def test_one_campaign_continues_to_normal_model_aware_validation(self) -> None:
        content = (
            "campaign_name,segment,geo,channel,start_date,end_date,budget_rub\n"
            "Synthetic A,SYNTHETIC_SEGMENT,SYNTHETIC_GEO,SYNTHETIC_CHANNEL,2026-01-01,2026-01-02,1000\n"
        ).encode("utf-8")
        upload = self._upload_and_parse("single.csv", content)
        validation, _ = self.service.request_validation(
            upload["upload_id"],
            "preview-single-validation-0001",
        )
        self.assertEqual(upload["detected_campaigns_n"], 1)
        self.assertEqual(validation["status"]["code"], "running")
        self.assertEqual(len(self.executor.calls), 1)
        function, args = self.executor.calls[0]
        self.assertEqual(function.__name__, "_validate_campaign")
        self.assertEqual(args[0].detected_campaigns_n, 1)

    def test_preview_aggregates_reconcile_and_contain_no_model_metrics(self) -> None:
        normalized = [
            {"channel": "A", "geo": "G1", "budget_rub": "100"},
            {"channel": "A", "geo": "G2", "budget_rub": "200"},
            {"channel": "B", "geo": "G1", "budget_rub": "300"},
        ]
        daily = [
            {"channel": "A", "geo": "G1", "date": "2026-01-01", "budget_rub": "50"},
            {"channel": "A", "geo": "G2", "date": "2026-01-01", "budget_rub": "100"},
            {"channel": "A", "geo": "G1", "date": "2026-01-02", "budget_rub": "50"},
            {"channel": "A", "geo": "G2", "date": "2026-01-02", "budget_rub": "100"},
            {"channel": "B", "geo": "G1", "date": "2026-01-01", "budget_rub": "150"},
            {"channel": "B", "geo": "G1", "date": "2026-01-02", "budget_rub": "150"},
        ]
        preview = self.service._validation_preview(normalized, daily, ())
        self.assertEqual(
            sum(row.total_budget_rub for row in preview.budget_by_channel or ()),
            600,
        )
        self.assertEqual(
            sum(row.total_budget_rub for row in preview.budget_by_geo or ()),
            600,
        )
        self.assertEqual(
            sum(row.daily_budget_rub for row in preview.channel_flighting or ()),
            600,
        )
        self.assertEqual(
            {row.channel: row.max_daily_budget_rub for row in preview.budget_by_channel or ()},
            {"A": 150, "B": 150},
        )
        serialized = json.dumps(preview, default=lambda value: value.__dict__)
        for forbidden in ("roas", "posterior", "incremental", "optimizer", "forecast"):
            self.assertNotIn(forbidden, serialized.lower())

    def test_preview_is_optional_and_geo_points_are_omitted_without_reference(self) -> None:
        fixture = json.loads(HAPPY_FIXTURE.read_text(encoding="utf-8"))
        old_payload = fixture["validations"][0]
        old_record = parse_lifecycle_contract(old_payload)
        self.assertIsInstance(old_record, ValidationResultV1)
        self.assertEqual(old_record.to_dict(), old_payload)

        total = old_record.totals.model_input_budget_rub  # type: ignore[union-attr]
        daily_total = old_record.totals.daily_budget_rub  # type: ignore[union-attr]
        preview = ValidationPreview(
            budget_by_channel=(
                BudgetByChannelPreview("SYNTHETIC_CHANNEL", total, daily_total),
            ),
            budget_by_geo=(
                BudgetByGeoPreview("SYNTHETIC_GEO", total, daily_total),
            ),
            channel_flighting=(
                ChannelFlightingPreview(
                    "SYNTHETIC_CHANNEL",
                    old_record.campaigns[0].start_date,
                    daily_total,
                ),
            ),
            geo_points=None,
            checks=(
                ValidationPreviewCheck(
                    "CAMPAIGN_COUNT",
                    "passed",
                    "В файле найдена ровно одна кампания.",
                ),
            ),
        )
        current = replace(old_record, preview=preview)
        current.validate()
        payload = current.to_dict()
        self.assertIn("preview", payload)
        self.assertNotIn("geo_points", payload["preview"])

    def test_template_is_valid_openxml_with_required_synthetic_sheets(self) -> None:
        content = build_campaign_plan_template()
        self.assertTrue(content.startswith(b"PK"))
        with zipfile.ZipFile(BytesIO(content)) as archive:
            self.assertIsNone(archive.testzip())
        workbook = load_workbook(BytesIO(content), data_only=True)
        self.assertIn("01_Daily", workbook.sheetnames)
        self.assertIn("02_Interval", workbook.sheetnames)
        cell_text = "\n".join(
            str(cell.value or "")
            for sheet in workbook.worksheets
            for row in sheet.iter_rows()
            for cell in row
        )
        self.assertIn("SYNTHETIC_DAILY_CAMPAIGN", cell_text)
        self.assertIn("SYNTHETIC_INTERVAL_CAMPAIGN", cell_text)
        for forbidden in ("МОСКВА", "ТС5", "РЕГ_ТВ", "X5"):
            self.assertNotIn(forbidden, cell_text.upper())

    def test_xlsx_archive_expansion_is_bounded_before_xml_parsing(self) -> None:
        path = Path(self.temporary.name) / "oversized.xlsx"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "xl/workbook.xml",
                b"x" * (MAX_XLSX_WORKBOOK_XML_BYTES + 1),
            )
        with self.assertRaisesRegex(ValueError, "metadata exceeds"):
            _xlsx_sheet_names(path)


if __name__ == "__main__":
    unittest.main()
