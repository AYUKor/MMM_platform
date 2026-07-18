"""Regression tests for the reviewed static geo catalog and map aggregates."""

from __future__ import annotations

import csv
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_APP_DIR = PROJECT_ROOT / "04_Web_app"
PYMC_CODE_DIR = PROJECT_ROOT / "02_Code" / "01_PyMC"
for entry in (WEB_APP_DIR, PYMC_CODE_DIR):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from services.business_semantics_v2 import (  # noqa: E402
    build_geo_catalog,
    build_validation_result_v2,
    build_workspace_geo_budget_v1,
)
from services.geo_catalog import (  # noqa: E402
    ALIASES_PATH,
    CATALOG_PATH,
    COORDINATES_SOURCE,
    COORDINATES_SOURCE_DATE,
    GEO_CATALOG_VERSION,
    CanonicalGeoCatalog,
    GeoCatalogError,
    assert_active_serving_geo_coverage,
    load_canonical_geo_catalog,
    normalize_geo_name,
    stable_geo_id,
)
from mmm_core.campaign_plan import (  # noqa: E402
    load_geo_alias_catalog,
    prepare_campaign_from_config,
)


CONTROL_GEOS = (
    "Волгоград",
    "Воронеж",
    "Краснодар",
    "Красноярск",
    "Новосибирск",
    "Омск",
    "Ростов-на-Дону",
    "Самара",
    "Санкт-Петербург",
    "Саратов",
    "Тюмень",
    "Уфа",
    "Чебоксары",
    "Челябинск",
    "Ярославль",
)
CONTROL_CHANNELS = ("Digital_Performance", "OOH_Total", "Радио")
CONTROL_BUDGET_RUB = 267_818_706.0


def _validation(
    geographies: tuple[str, ...] = CONTROL_GEOS,
    *,
    budget_rub: float = CONTROL_BUDGET_RUB,
    campaign_id: str = "campaign_geo_catalog_test",
    validation_id: str = "validation_geo_catalog_test",
) -> dict:
    equal = budget_rub / len(geographies)
    budget_rows = [
        {"geo": geo, "total_budget_rub": equal} for geo in geographies
    ]
    budget_rows[-1]["total_budget_rub"] += budget_rub - sum(
        float(row["total_budget_rub"]) for row in budget_rows
    )
    return {
        "validation_id": validation_id,
        "status": {"code": "valid", "display_text": "План можно рассчитать"},
        "job_creation_allowed": True,
        "campaigns": [
            {
                "campaign_id": campaign_id,
                "campaign_name": "Контрольная региональная кампания",
                "geographies": list(geographies),
                "channels": list(CONTROL_CHANNELS),
            }
        ],
        "totals": {
            "source_rows_n": len(geographies) * len(CONTROL_CHANNELS),
            "uploaded_budget_rub": budget_rub,
            "model_input_budget_rub": budget_rub,
        },
        "blocking_errors": [],
        "warnings": [],
        "preview": {"budget_by_geo": budget_rows, "checks": []},
    }


class CanonicalGeoCatalogV1Test(unittest.TestCase):
    def setUp(self) -> None:
        load_canonical_geo_catalog.cache_clear()
        self.catalog = load_canonical_geo_catalog()

    def test_static_catalog_is_complete_deterministic_and_reviewed(self) -> None:
        entries = self.catalog.entries
        self.assertEqual(len(entries), 220)
        self.assertEqual(len({row["geo_id"] for row in entries}), len(entries))
        self.assertEqual(
            len({row["geo_normalized_name"] for row in entries}), len(entries)
        )
        self.assertTrue(
            all(
                row["geo_id"] == stable_geo_id(row["geo_normalized_name"])
                for row in entries
            )
        )
        self.assertTrue(
            all(
                row["geo_id"]
                == "geo_"
                + hashlib.sha256(
                    row["geo_normalized_name"].encode("utf-8")
                ).hexdigest()[:16]
                for row in entries
            )
        )
        self.assertTrue(all(-90 <= row["latitude"] <= 90 for row in entries))
        self.assertTrue(all(-180 <= row["longitude"] <= 180 for row in entries))
        self.assertTrue(all(40 <= row["latitude"] <= 82 for row in entries))
        self.assertTrue(all(19 <= row["longitude"] <= 181 for row in entries))
        self.assertEqual(
            {row["coordinates_source"] for row in entries}, {COORDINATES_SOURCE}
        )
        self.assertEqual(
            {row["coordinates_source_version_or_date"] for row in entries},
            {COORDINATES_SOURCE_DATE},
        )
        self.assertEqual(
            {row["catalog_version"] for row in entries}, {GEO_CATALOG_VERSION}
        )
        self.assertIs(load_canonical_geo_catalog(), self.catalog)

    def test_aliases_are_unique_and_resolution_is_fail_closed(self) -> None:
        with ALIASES_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
            aliases = list(csv.DictReader(handle))
        normalized_aliases = [row["alias_normalized_name"] for row in aliases]
        self.assertEqual(len(normalized_aliases), len(set(normalized_aliases)))

        canonical = self.catalog.resolve("Санкт-Петербург")
        spaced = self.catalog.resolve("  санкт   петербург ")
        abbreviation = self.catalog.resolve("СПБ")
        self.assertEqual(canonical.normalization_status, "canonical")
        self.assertEqual(spaced.normalization_status, "alias")
        self.assertEqual(abbreviation.normalization_status, "alias")
        self.assertEqual(
            {canonical.geo_id, spaced.geo_id, abbreviation.geo_id},
            {stable_geo_id("САНКТ-ПЕТЕРБУРГ")},
        )
        self.assertEqual(normalize_geo_name("  орёл  "), "ОРЕЛ")

        unknown = self.catalog.resolve("Санкт Петербур")
        self.assertEqual(unknown.normalization_status, "unknown")
        self.assertEqual(unknown.coordinates_status, "unavailable")
        self.assertIsNone(unknown.latitude)
        self.assertIsNone(unknown.canonical_geo_id)

    def test_campaign_preparation_canonicalizes_alias_before_model_validation(self) -> None:
        class SupportedPackage:
            targets = ["turnover_per_user"]
            capability_rows = [
                {
                    "segment": "ТС5/Оффлайн",
                    "target": "turnover_per_user",
                    "channel": "OOH_Total",
                    "allowed_use": "primary",
                    "risk_level": "low",
                }
            ]

            @staticmethod
            def supported_geos_for(
                segment: str,
                target: str,
                channel: str,
            ) -> set[str]:
                del segment, target, channel
                return {"САНКТ-ПЕТЕРБУРГ"}

            @staticmethod
            def summary() -> dict:
                return {"package_id": "synthetic_geo_alias_package"}

        aliases = load_geo_alias_catalog(CATALOG_PATH, ALIASES_PATH)
        self.assertEqual(aliases["СПБ"]["geo_display_name"], "Санкт-Петербург")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign_path = root / "campaign.csv"
            campaign_path.write_text(
                "campaign_name,segment,geo,channel,start_date,end_date,budget_rub\n"
                "alias-test,ТС5/Оффлайн,СПБ,OOH_Total,2026-08-01,2026-08-02,100\n",
                encoding="utf-8",
            )
            config_path = root / "workflow.json"
            config_path.write_text("{}\n", encoding="utf-8")
            config = {
                "run_id": "geo_alias_integration",
                "paths": {
                    "campaign_input_dir": str(root),
                    "campaign_file": campaign_path.name,
                    "validated_output_dir": str(root / "validated"),
                    "flighting_output_dir": str(root / "flighting"),
                },
                "validation": {
                    "fail_on_parse_issues": True,
                    "fail_on_unsupported": True,
                    "geo_catalog_file": str(CATALOG_PATH),
                    "geo_alias_catalog_file": str(ALIASES_PATH),
                },
                "optimizer": {"targets": ["turnover_per_user"]},
            }
            prepared = prepare_campaign_from_config(
                config,
                config_path,
                SupportedPackage(),
                root / "output",
                purpose="optimizer",
            )
            with Path(prepared.normalized_path).open(
                "r", encoding="utf-8-sig", newline=""
            ) as handle:
                normalized = list(csv.DictReader(handle))
            self.assertEqual(normalized[0]["geo"], "САНКТ-ПЕТЕРБУРГ")
            self.assertEqual(
                normalized[0]["canonical_geo_display_name"],
                "Санкт-Петербург",
            )
            self.assertEqual(normalized[0]["input_geo_name"], "СПБ")
            self.assertEqual(normalized[0]["geo_normalization_status"], "alias")
            self.assertEqual(prepared.summary["validation"]["unsupported_rows_n"], 0)
            self.assertEqual(prepared.summary["geo_normalization"]["alias_rows_n"], 1)
            audit = prepared.summary["geo_normalization"]["catalog_audit"]
            self.assertEqual(audit["catalog_version"], GEO_CATALOG_VERSION)
            self.assertEqual(
                audit["catalog_sha256"],
                hashlib.sha256(CATALOG_PATH.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                audit["aliases_sha256"],
                hashlib.sha256(ALIASES_PATH.read_bytes()).hexdigest(),
            )

    def test_ambiguous_registered_alias_is_explicit_and_forbidden_in_production(self) -> None:
        entries = list(self.catalog.entries[:2])
        canonical_aliases = [
            {
                "alias": row["geo_normalized_name"],
                "alias_normalized_name": row["geo_normalized_name"],
                "canonical_geo_id": row["geo_id"],
                "canonical_geo_normalized_name": row["geo_normalized_name"],
                "normalization_rule": "canonical_name",
                "catalog_version": GEO_CATALOG_VERSION,
            }
            for row in entries
        ]
        ambiguous_aliases = [
            {
                "alias": "ТЕСТОВОЕ ГЕО",
                "alias_normalized_name": "ТЕСТОВОЕ ГЕО",
                "canonical_geo_id": row["geo_id"],
                "canonical_geo_normalized_name": row["geo_normalized_name"],
                "normalization_rule": "test_ambiguous_alias",
                "catalog_version": GEO_CATALOG_VERSION,
            }
            for row in entries
        ]
        with self.assertRaisesRegex(GeoCatalogError, "ambiguous"):
            CanonicalGeoCatalog(entries, [*canonical_aliases, *ambiguous_aliases])
        test_catalog = CanonicalGeoCatalog(
            entries,
            [*canonical_aliases, *ambiguous_aliases],
            strict_aliases=False,
        )
        resolution = test_catalog.resolve("ТЕСТОВОЕ ГЕО")
        self.assertEqual(resolution.normalization_status, "ambiguous")
        self.assertEqual(resolution.coordinates_status, "unavailable")
        self.assertIsNone(resolution.canonical_geo_id)

    def test_active_serving_coverage_guard_fails_closed(self) -> None:
        active = [row["geo_normalized_name"] for row in self.catalog.entries]
        coverage = assert_active_serving_geo_coverage(active, self.catalog)
        self.assertEqual(coverage["active_serving_geographies_n"], 220)
        self.assertEqual(coverage["covered_geographies_n"], 220)
        with self.assertRaisesRegex(GeoCatalogError, "missing canonical coordinates"):
            assert_active_serving_geo_coverage([*active, "НЕИЗВЕСТНОЕ ГЕО"], self.catalog)

    def test_control_campaign_keeps_all_15_geographies_and_budget(self) -> None:
        payload = build_validation_result_v2(_validation(), catalog=self.catalog)
        self.assertEqual(payload["file_validation"]["rows_n"], 45)
        self.assertEqual(payload["file_validation"]["geographies_n"], 15)
        self.assertEqual(payload["file_validation"]["channels_n"], 3)
        self.assertEqual(len(payload["geo_points"]), 15)
        self.assertEqual(payload["map_coverage"]["status"], "available")
        self.assertEqual(payload["map_coverage"]["located_geographies_n"], 15)
        self.assertEqual(payload["map_coverage"]["unlocated_geographies_n"], 0)
        self.assertAlmostEqual(
            sum(row["budget_rub"] for row in payload["geo_points"]),
            CONTROL_BUDGET_RUB,
        )
        self.assertAlmostEqual(
            sum(row["budget_share"] for row in payload["geo_points"]), 1.0
        )
        self.assertTrue(
            all(row["coordinates_status"] == "canonical" for row in payload["geo_points"])
        )
        self.assertTrue(
            all(
                len(row["channels"]) == len(CONTROL_CHANNELS)
                for row in payload["geo_points"]
            )
        )
        self.assertNotIn("... ещё", str(payload))

    def test_partial_validation_keeps_unknown_geography_and_budget(self) -> None:
        payload = build_validation_result_v2(
            _validation(("Москва", "НЕИЗВЕСТНОЕ ГЕО"), budget_rub=120.0),
            catalog=self.catalog,
        )
        self.assertEqual(payload["map_coverage"]["status"], "partial")
        self.assertEqual(payload["map_coverage"]["unlocated_geographies_n"], 1)
        unknown = next(
            row
            for row in payload["geo_points"]
            if row["normalization_status"] == "unknown"
        )
        self.assertIsNone(unknown["latitude"])
        self.assertEqual(unknown["budget_rub"], 60.0)
        self.assertEqual(payload["map_coverage"]["unlocated_budget_rub"], 60.0)
        self.assertEqual(payload["map_coverage"]["unlocated_budget_share"], 0.5)
        self.assertAlmostEqual(
            sum(row["budget_rub"] for row in payload["geo_points"]), 120.0
        )

    def test_workspace_merges_aliases_and_deduplicates_campaigns(self) -> None:
        validation = _validation(
            ("Санкт-Петербург", "СПБ"),
            budget_rub=200.0,
            campaign_id="campaign_alias_test",
        )
        payload = build_workspace_geo_budget_v1([validation], catalog=self.catalog)
        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["geographies_n"], 1)
        self.assertEqual(payload["campaigns_n"], 1)
        self.assertEqual(payload["rows"][0]["campaigns_n"], 1)
        self.assertEqual(payload["rows"][0]["total_budget_rub"], 200.0)
        self.assertEqual(payload["rows"][0]["budget_share"], 1.0)

    def test_workspace_deduplicates_validation_and_separates_same_name_campaigns(self) -> None:
        first = _validation(
            ("Москва",),
            budget_rub=100.0,
            campaign_id="campaign_same_name",
            validation_id="validation_first",
        )
        second = _validation(
            ("Москва",),
            budget_rub=150.0,
            campaign_id="campaign_same_name",
            validation_id="validation_second",
        )
        payload = build_workspace_geo_budget_v1(
            [first, first, second],
            catalog=self.catalog,
        )
        self.assertEqual(payload["campaigns_n"], 2)
        self.assertEqual(payload["rows"][0]["campaigns_n"], 2)
        self.assertEqual(payload["total_budget_rub"], 250.0)
        self.assertEqual(payload["rows"][0]["total_budget_rub"], 250.0)

    def test_workspace_partial_and_empty_states_reconcile(self) -> None:
        partial = build_workspace_geo_budget_v1(
            [_validation(("Москва", "НЕИЗВЕСТНОЕ ГЕО"), budget_rub=120.0)],
            catalog=self.catalog,
        )
        self.assertEqual(partial["status"], "partial")
        self.assertEqual(partial["geographies_n"], 2)
        self.assertEqual(partial["coverage"]["unlocated_budget_rub"], 60.0)
        self.assertAlmostEqual(
            sum(row["total_budget_rub"] for row in partial["rows"]), 120.0
        )

        empty = build_workspace_geo_budget_v1([], catalog=self.catalog)
        self.assertEqual(empty["status"], "unavailable")
        self.assertEqual(empty["geographies_n"], 0)
        self.assertEqual(empty["total_budget_rub"], 0.0)
        self.assertEqual(empty["coverage"]["unlocated_budget_share"], None)

    def test_full_catalog_endpoint_is_available(self) -> None:
        payload = build_geo_catalog(catalog=self.catalog)
        self.assertEqual(payload["catalog_version"], GEO_CATALOG_VERSION)
        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["geographies_n"], 220)
        self.assertEqual(payload["coverage"]["located_geographies_n"], 220)


if __name__ == "__main__":
    unittest.main()
