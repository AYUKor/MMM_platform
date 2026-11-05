"""Campaign catalog extension: synthetic catalog and package folders only, no real model files."""

from __future__ import annotations

import csv
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

PYMC_CODE_DIR = Path(__file__).resolve().parents[1]
if str(PYMC_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(PYMC_CODE_DIR))

from mmm_core import campaign_catalog_extension as extension  # noqa: E402
from mmm_core.campaign_catalog_synthetic import (  # noqa: E402
    synthetic_results,
    write_synthetic_catalog_dir,
    write_synthetic_package_dir,
)

GENERATED_AT = "2026-11-05T05:00:00+00:00"


class CampaignCatalogExtensionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.catalog_dir = write_synthetic_catalog_dir(self.root / "catalog")
        self.package_dir, self.package_id = write_synthetic_package_dir(self.root / "package")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _build(self, out_name: str = "first") -> tuple[dict, Path]:
        out_dir = self.root / out_name / extension.ARTIFACT_VERSION
        metadata = extension.build_extension(
            source=extension.load_source_catalog(self.catalog_dir),
            identity=extension.package_identity_from_dir(self.package_dir, self.package_id),
            out_dir=out_dir,
            catalog_version="synthetic_catalog_v1",
            generated_at_utc=GENERATED_AT,
        )
        return metadata, out_dir

    def _rewrite_csv(self, name: str, change) -> None:
        path = self.catalog_dir / name
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        change(rows)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def _check_status(self) -> dict[str, str]:
        source = extension.load_source_catalog(self.catalog_dir)
        identity = extension.package_identity_from_dir(self.package_dir, self.package_id)
        records = sorted((extension.normalize_campaign(row) for row in source.results), key=lambda row: row["number"])
        return {row["check_id"]: row["status"] for row in extension.catalog_checks(records, source, identity)}

    def test_build_writes_bound_files_and_every_check_passes(self) -> None:
        metadata, out_dir = self._build()
        self.assertEqual(sorted(path.name for path in out_dir.iterdir()), sorted(extension.EXTENSION_FILES))
        self.assertEqual(extension.failed_checks(metadata), [])
        self.assertEqual(
            [row["check_id"] for row in metadata["checks"]],
            [
                "numbers_unique",
                "catalog_equals_numbers_csv",
                "sum_campaigns_le_channel_effect",
                "catalog_fit_equals_package_fit",
                "catalog_model_roas_equals_package_table",
                "workbook_equals_catalog",
            ],
        )
        on_disk = json.loads((out_dir / extension.METADATA_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(on_disk, json.loads(json.dumps(metadata, ensure_ascii=False, default=str)))
        extension.validate_metadata(on_disk)
        manifest = json.loads((self.package_dir / "model_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["package_id"], self.package_id)
        self.assertEqual(metadata["package_input_fingerprint"], manifest["package_input_fingerprint"])
        self.assertEqual(metadata["model_run_id"], manifest["model_run_id"])
        for key, name in (("data", extension.DATA_FILENAME), ("workbook", extension.WORKBOOK_FILENAME)):
            path = out_dir / name
            self.assertEqual(metadata[key]["sha256"], extension.sha256_file(path))
            self.assertEqual(metadata[key]["size_bytes"], path.stat().st_size)
        self.assertEqual(
            metadata["workbook"]["download_file_name"], "Каталог_прошлых_кампаний_Заноза_20261105.xlsx"
        )

    def test_records_keep_catalog_numbers_and_explain_missing_estimates(self) -> None:
        _, out_dir = self._build()
        data = json.loads((out_dir / extension.DATA_FILENAME).read_text(encoding="utf-8"))
        extension.validate_catalog_data(data)
        source = synthetic_results()
        self.assertEqual([row["number"] for row in data["campaigns"]], sorted(row["id"] for row in source))
        self.assertNotIn(6, [row["number"] for row in data["campaigns"]])
        by_number = {row["number"]: row for row in data["campaigns"]}
        for raw in source:
            record = by_number[raw["id"]]
            self.assertEqual(record["name"], raw["name"])
            self.assertAlmostEqual(record["budget_rub"], raw["budget"], places=6)
            self.assertEqual(record["reliable"], raw["flag"])
            self.assertEqual(record["overlaps_n"], raw["overlap"])
            if raw["modeled"]:
                self.assertEqual(record["status"], "computed")
                self.assertIsNone(record["status_display_text"])
                self.assertEqual(
                    [record["turnover_increment_rub"][part] for part in ("low", "estimate", "high")],
                    raw["turnover"],
                )
            else:
                self.assertEqual(record["status"], "not_computed")
                self.assertEqual(record["status_display_text"], extension.NOT_COMPUTED_TEXT)
                for field in extension.EFFECT_FIELDS:
                    self.assertIsNone(record[field])
                self.assertEqual(record["reliable"], 0)
        summary = data["summary"]
        computed = [row for row in data["campaigns"] if row["status"] == "computed"]
        self.assertEqual(summary["campaigns_n"], len(source))
        self.assertEqual(summary["computed_n"], len(source) - 1)
        self.assertAlmostEqual(
            summary["weighted_roas"],
            sum(row["turnover_increment_rub"]["estimate"] for row in computed)
            / sum(row["budget_rub"] for row in computed),
        )
        self.assertEqual(summary["up_to_120_days_n"] + summary["longer_120_days_n"], len(source))
        self.assertEqual(data["roas_level_label"], "уровень ROAS по отрасли")
        self.assertIn("campaign_effect_leave_one_out", [row["code"] for row in data["notes"]])

    def test_workbook_holds_values_only_and_matches_the_records(self) -> None:
        from openpyxl import load_workbook

        _, out_dir = self._build()
        data = json.loads((out_dir / extension.DATA_FILENAME).read_text(encoding="utf-8"))
        workbook_path = out_dir / extension.WORKBOOK_FILENAME
        report = extension.verify_catalog_workbook(workbook_path, data["campaigns"])
        self.assertEqual(report["campaigns"], len(data["campaigns"]))
        workbook = load_workbook(workbook_path)
        self.assertEqual(
            workbook.sheetnames, ["Тех. информация", "Кампании до 120 дней", "Кампании длиннее 120 дней"]
        )
        texts = [
            str(cell.value)
            for sheet in workbook.worksheets
            for row in sheet.iter_rows()
            for cell in row
            if cell.value is not None
        ]
        self.assertFalse(any(text.startswith("=") for text in texts))
        self.assertFalse(any("ЧЕРНОВИК" in text.upper() for text in texts))
        self.assertIn(self.package_id, texts)

        sheet = workbook["Кампании до 120 дней"]
        sheet["O6"] = float(sheet["O6"].value) + 1.0
        tampered = self.root / "tampered.xlsx"
        workbook.save(tampered)
        with self.assertRaises(extension.CampaignCatalogExtensionError):
            extension.verify_catalog_workbook(tampered, data["campaigns"])

    def test_new_versions_only(self) -> None:
        self._build()
        with self.assertRaises(FileExistsError):
            self._build()
        with self.assertRaises(extension.CampaignCatalogExtensionError):
            extension.build_extension(
                source=extension.load_source_catalog(self.catalog_dir),
                identity=extension.package_identity_from_dir(self.package_dir, self.package_id),
                out_dir=self.root / "wrong_name",
                catalog_version="synthetic_catalog_v1",
                generated_at_utc=GENERATED_AT,
            )

    def test_package_identity_refuses_changed_files_and_foreign_ids(self) -> None:
        other_id = "pkg_0000000000000000_" + self.package_id.rsplit("_", 1)[1]
        with self.assertRaises(extension.CampaignCatalogExtensionError):
            extension.package_identity_from_dir(self.package_dir, other_id)
        with (self.package_dir / "model_roas_table.csv").open("a", encoding="utf-8") as handle:
            handle.write("ТС5/Онлайн,Радио,9.9\n")
        with self.assertRaises(extension.CampaignCatalogExtensionError):
            extension.package_identity_from_dir(self.package_dir, self.package_id)

    def test_other_fit_fails_the_fit_check(self) -> None:
        write_synthetic_catalog_dir(self.catalog_dir, npz_sha256="e" * 64)
        status = self._check_status()
        self.assertEqual(status["catalog_fit_equals_package_fit"], "failed")
        self.assertEqual(status["catalog_equals_numbers_csv"], "passed")

    def test_model_roas_off_the_package_table_fails(self) -> None:
        def scale(rows: list[dict[str, str]]) -> None:
            rows[0]["model_roas_fit_rows"] = str(float(rows[0]["model_roas_fit_rows"]) * 1.05)

        self._rewrite_csv("check_catalog_vs_model_roas.csv", scale)
        self.assertEqual(self._check_status()["catalog_model_roas_equals_package_table"], "failed")

    def test_model_roas_within_draw_noise_passes_and_far_off_fails(self) -> None:
        # Package table with a 90% interval of median -/+ 15%: draw noise of 200 vs 40 draws is ~2% of the median.
        package_dir, package_id = write_synthetic_package_dir(self.root / "package_interval", roas_interval=0.15)
        identity = extension.package_identity_from_dir(package_dir, package_id)

        def parity(factor: float) -> tuple[bool, dict]:
            def scale(rows: list[dict[str, str]]) -> None:
                rows[0]["model_roas_fit_rows"] = str(float(rows[0]["model_roas_fit_rows"]) * factor)

            write_synthetic_catalog_dir(self.catalog_dir)
            self._rewrite_csv("check_catalog_vs_model_roas.csv", scale)
            return extension.model_roas_parity(extension.load_source_catalog(self.catalog_dir), identity)

        passed, value = parity(1.05)
        self.assertTrue(passed)
        self.assertAlmostEqual(value["max_relative_difference"], 0.05, places=6)
        self.assertLess(value["max_z"], extension.MODEL_ROAS_MAX_Z)
        self.assertEqual((value["catalog_draws"], value["package_table_draws"], value["failed_cells"]), (40, 200, []))

        passed, value = parity(1.12)
        self.assertFalse(passed)
        self.assertGreater(value["max_z"], extension.MODEL_ROAS_MAX_Z)
        self.assertEqual(len(value["failed_cells"]), 1)

        passed, value = parity(1.0)
        self.assertTrue(passed)
        self.assertEqual(value["max_relative_difference"], 0.0)

    def test_numbers_csv_difference_fails(self) -> None:
        def change(rows: list[dict[str, str]]) -> None:
            rows[1]["бюджет_млн"] = str(float(rows[1]["бюджет_млн"]) + 0.01)

        self._rewrite_csv("catalog_numbers.csv", change)
        self.assertEqual(self._check_status()["catalog_equals_numbers_csv"], "failed")

    def test_campaign_sum_above_channel_effect_fails(self) -> None:
        def change(rows: list[dict[str, str]]) -> None:
            rows[2]["sum_campaign_effect_over_full"] = "1.2"

        self._rewrite_csv("check_catalog_vs_model_roas.csv", change)
        self.assertEqual(self._check_status()["sum_campaigns_le_channel_effect"], "failed")

    def test_cli_refuses_failed_checks_and_writes_nothing(self) -> None:
        write_synthetic_catalog_dir(self.catalog_dir, npz_sha256="e" * 64)
        out_dir = self.root / "cli" / extension.ARTIFACT_VERSION
        arguments = [
            "--catalog-dir", str(self.catalog_dir),
            "--package-dir", str(self.package_dir),
            "--package-id", self.package_id,
            "--catalog-version", "synthetic_catalog_v1",
            "--out-dir", str(out_dir),
            "--generated-at-utc", GENERATED_AT,
        ]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(extension.main(arguments), 2)
        self.assertFalse(out_dir.exists())

    def test_cli_builds_when_checks_pass(self) -> None:
        out_dir = self.root / "cli_ok" / extension.ARTIFACT_VERSION
        output = io.StringIO()
        with redirect_stdout(output):
            code = extension.main(
                [
                    "--catalog-dir", str(self.catalog_dir),
                    "--package-dir", str(self.package_dir),
                    "--package-id", self.package_id,
                    "--catalog-version", "synthetic_catalog_v1",
                    "--out-dir", str(out_dir),
                    "--generated-at-utc", GENERATED_AT,
                ]
            )
        self.assertEqual(code, 0)
        printed = json.loads(output.getvalue())
        self.assertEqual(printed["package_id"], self.package_id)
        self.assertTrue((out_dir / extension.METADATA_FILENAME).is_file())

    def test_metadata_validation_and_failed_checks(self) -> None:
        metadata, _ = self._build()
        broken = dict(metadata)
        broken["extra"] = 1
        with self.assertRaises(extension.CampaignCatalogExtensionError):
            extension.validate_metadata(broken)
        failing = json.loads(json.dumps(metadata, ensure_ascii=False, default=str))
        failing["checks"][0]["status"] = "failed"
        self.assertEqual(extension.failed_checks(failing), ["numbers_unique"])

    def test_record_validation_rejects_inconsistent_rows(self) -> None:
        _, out_dir = self._build()
        data = json.loads((out_dir / extension.DATA_FILENAME).read_text(encoding="utf-8"))
        record = dict(data["campaigns"][0])
        record["duration_group"] = (
            extension.DURATION_LONG
            if record["duration_group"] == extension.DURATION_SHORT
            else extension.DURATION_SHORT
        )
        with self.assertRaises(extension.CampaignCatalogExtensionError):
            extension.validate_campaign_record(record)
        changed = dict(data)
        changed["campaigns"] = list(reversed(data["campaigns"]))
        with self.assertRaises(extension.CampaignCatalogExtensionError):
            extension.validate_catalog_data(changed)


if __name__ == "__main__":
    unittest.main()
