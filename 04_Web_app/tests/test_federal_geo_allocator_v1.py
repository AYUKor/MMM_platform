from __future__ import annotations

import ast
import csv
import hashlib
import json
import math
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np


WEB_APP_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = WEB_APP_DIR.parent
PYMC_CODE_DIR = PROJECT_ROOT / "02_Code" / "01_PyMC"
for entry in (WEB_APP_DIR, PYMC_CODE_DIR):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from mmm_core.federal_geo_allocator import (  # noqa: E402
    CONSERVATION_TOLERANCE_RUB,
    POLICY_VERSION,
    SUPPORTED_CHANNELS,
    EligibleGeo,
    FederalGeoAllocationContext,
    FederalGeoAllocationError,
    FederalGeoAllocator,
    assert_no_federal_geo,
    is_federal_geo,
)
from mmm_core.model_package import sha256_file  # noqa: E402
from mmm_core.model_package_reader import ModelPackage  # noqa: E402


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "federal_geo_allocation_v1"
POPULATION_PATH = (
    WEB_APP_DIR / "data" / "federal_geo_allocation" / "geo_reference_v2.csv"
)
CATALOG_PATH = WEB_APP_DIR / "data" / "geo_catalog" / "geo_catalog_v1.csv"
POPULATION_SHA256 = (
    "dcda497e151969506f9d65e6e8d294852a21aa92f066667efecb61ac41636043"
)
CATALOG_SHA256 = (
    "097b1db2891184ae4a11577ee0e33696eda48e21917d339a07d330e055bedeab"
)
PACKAGE_ID = "pkg_807d3ddbae57a52a_9aacd3beb350725b"


def _json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _hash_lines(lines: list[str]) -> str:
    payload = "".join(f"{line}\n" for line in lines).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _context() -> FederalGeoAllocationContext:
    snapshot = _json("B2_0_SUPPORTED_GEO_SNAPSHOT.json")
    population = {
        row["geo_label"]: float(row["population_k"])
        for row in _csv_rows(POPULATION_PATH)
    }
    eligible_by_direction: dict[str, tuple[EligibleGeo, ...]] = {}
    geo_by_label: dict[str, EligibleGeo] = {}
    capability_pairs: set[tuple[str, str]] = set()
    checksums: dict[str, str] = {}
    for direction in snapshot["directions"]:
        name = direction["business_direction"]
        eligible = tuple(
            EligibleGeo(
                geo_id=row["geo_id"],
                geo_label=row["geo_label"],
                geo_display_name=row["geo_display_name"],
                population_k=population[row["geo_label"]],
            )
            for row in direction["supported_geographies"]
        )
        eligible_by_direction[name] = eligible
        geo_by_label.update({row.geo_label: row for row in eligible})
        capability_pairs.update(
            (name, channel)
            for channel in direction["package_capability_channels"]
            if channel in SUPPORTED_CHANNELS
        )
        checksums[name] = hashlib.sha256(
            "\n".join(
                sorted(f"{row.geo_id}|{row.geo_label}" for row in eligible)
            ).encode("utf-8")
        ).hexdigest()
    return FederalGeoAllocationContext(
        policy_version=POLICY_VERSION,
        package_id=PACKAGE_ID,
        package_pointer_sha256="1" * 64,
        registration_content_sha256="2" * 64,
        support_source_sha256="3" * 64,
        denominator_source_sha256="4" * 64,
        capability_source_sha256="5" * 64,
        population_source_sha256=POPULATION_SHA256,
        geo_catalog_sha256=CATALOG_SHA256,
        eligible_by_direction=eligible_by_direction,
        capability_pairs=frozenset(capability_pairs),
        geo_by_label=geo_by_label,
        eligible_geo_set_checksums=checksums,
    )


def _row(
    *,
    source_row_id: str = "row:1",
    direction: str = "ТС5/Онлайн",
    channel: str = "Нац_ТВ",
    geo: str = "РФ",
    budget: float = 100_000_000.0,
    date: str = "2026-09-01",
) -> dict:
    return {
        "source_row_id": source_row_id,
        "campaign_name": "B2.1 test",
        "creative_name": "",
        "segment": direction,
        "date": date,
        "channel": channel,
        "geo": geo,
        "budget_rub": budget,
    }


class FederalAliasContractTest(unittest.TestCase):
    def test_approved_aliases_allow_outer_whitespace_and_case_variants(self) -> None:
        contract = _json("B2_1_ALIAS_CLARIFICATION.json")
        accepted = tuple(contract["accepted_examples"])
        self.assertTrue(all(is_federal_geo(value) for value in accepted))

    def test_fuzzy_and_unapproved_aliases_are_rejected(self) -> None:
        contract = _json("B2_1_ALIAS_CLARIFICATION.json")
        rejected = tuple(contract["rejected_examples"])
        self.assertTrue(all(not is_federal_geo(value) for value in rejected))


class FederalGeoAllocatorGoldenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.context = _context()
        cls.allocator = FederalGeoAllocator(cls.context)

    def _allocation_checksum(self, rows: tuple[dict, ...]) -> str:
        ordered = sorted(rows, key=lambda row: row["geo_id"])
        return _hash_lines(
            [
                f'{row["geo_id"]}|{row["allocation_weight"]:.15f}|'
                f'{row["allocated_spend_rub"]:.12f}'
                for row in ordered
            ]
        )

    def _aggregate_checksum(self, rows: tuple[dict, ...]) -> str:
        ordered = sorted(rows, key=lambda row: row["geo_id"])
        return _hash_lines(
            [f'{row["geo_id"]}|{row["budget_rub"]:.12f}' for row in ordered]
        )

    def test_all_six_serving_channels_use_same_direction_weights(self) -> None:
        expected_checksum = _json("B2_0_SYNTHETIC_CHANNEL_CASES.json")["cases"][0][
            "expected"
        ]["allocation_vector_sha256"]
        for channel in sorted(SUPPORTED_CHANNELS):
            with self.subTest(channel=channel):
                result = self.allocator.allocate([_row(channel=channel)])
                self.assertEqual(len(result.expanded_rows), 211)
                self.assertEqual(
                    self._allocation_checksum(result.expanded_rows),
                    expected_checksum,
                )
                self.assertLessEqual(
                    result.audit["totals"]["difference_rub"],
                    CONSERVATION_TOLERANCE_RUB,
                )

    def test_b2_synthetic_ooh_indoor_and_regional_tv_golden_cases(self) -> None:
        cases = _json("B2_0_SYNTHETIC_CHANNEL_CASES.json")["cases"]
        for case in cases:
            source = case["source"]
            with self.subTest(case=case["case_id"]):
                result = self.allocator.allocate(
                    [
                        _row(
                            source_row_id=source["source_row_id"],
                            direction=source["business_direction"],
                            channel=source["canonical_channel"],
                            geo=source["geo"],
                            budget=source["budget_rub"],
                            date=source["date"],
                        )
                    ]
                )
                self.assertEqual(
                    len(result.expanded_rows),
                    case["expected"]["eligible_geo_count"],
                )
                self.assertEqual(
                    self._allocation_checksum(result.expanded_rows),
                    case["expected"]["allocation_vector_sha256"],
                )

    def test_mixed_federal_and_moscow_is_additive_with_one_warning(self) -> None:
        case = _json("B2_0_MIXED_GEO_CASE.json")
        rows = [
            _row(
                source_row_id=source["source_row_id"],
                direction=source["business_direction"],
                channel="Нац_ТВ",
                geo="РФ" if source["geo"] == "РФ" else "МОСКВА",
                budget=source["budget_rub"],
                date=source["date"],
            )
            for source in case["source_rows"]
        ]
        result = self.allocator.allocate(rows)
        self.assertEqual(len(result.warnings), 1)
        self.assertEqual(result.warnings[0]["code"], case["expected"]["warning_code"])
        self.assertEqual(
            self._aggregate_checksum(result.aggregated_rows),
            case["expected"]["aggregated_vector_sha256"],
        )
        moscow = next(row for row in result.aggregated_rows if row["geo"] == "МОСКВА")
        self.assertAlmostEqual(
            moscow["budget_rub"],
            case["expected"]["moscow_total_budget_rub"],
            places=8,
        )

    def test_multiple_federal_rows_expand_separately_then_aggregate(self) -> None:
        case = _json("B2_0_MULTIPLE_RF_ROWS_CASE.json")
        rows = [
            _row(
                source_row_id=source["source_row_id"],
                channel="Digital_Performance",
                budget=source["budget_rub"],
            )
            for source in case["source"]["rows"]
        ]
        result = self.allocator.allocate(rows)
        self.assertEqual(
            len(result.expanded_rows),
            case["expected"]["expanded_rows_before_aggregation"],
        )
        self.assertEqual(
            len(result.aggregated_rows),
            case["expected"]["aggregated_geo_count"],
        )
        self.assertEqual(
            self._aggregate_checksum(result.aggregated_rows),
            case["expected"]["aggregated_vector_sha256"],
        )
        for expected in case["expected"]["source_allocations"]:
            source_rows = tuple(
                row
                for row in result.expanded_rows
                if row["source_row_id"] == expected["source_row_id"]
            )
            self.assertEqual(
                self._allocation_checksum(source_rows),
                expected["allocation_vector_sha256"],
            )

    def test_period_specific_ready_universe_is_supplied_by_orchestration(self) -> None:
        declared = self.context.eligible_by_direction["ТС5/Онлайн"]
        first_ready = tuple(geo.geo_label for geo in declared[:175])
        second_ready = tuple(geo.geo_label for geo in declared[:174])
        rows = [
            _row(source_row_id="row:period:1", budget=10_000_000.0),
            _row(
                source_row_id="row:period:2",
                budget=20_000_000.0,
                date="2026-10-01",
            ),
        ]
        audit = {
            "row:period:1": {
                "declared_geo_count": 211,
                "ready_geo_count": 175,
                "excluded_geo_count": 36,
                "required_start": "2026-09-01",
                "required_end": "2026-09-15",
                "lmax": 14,
                "denominator_policy_version": "FORECAST_DENOMINATOR_RESOLUTION_V1",
                "availability_policy_version": "FORECAST_GEO_AVAILABILITY_V1",
            },
            "row:period:2": {
                "declared_geo_count": 211,
                "ready_geo_count": 174,
                "excluded_geo_count": 37,
                "required_start": "2026-10-01",
                "required_end": "2026-10-15",
                "lmax": 14,
                "denominator_policy_version": "FORECAST_DENOMINATOR_RESOLUTION_V1",
                "availability_policy_version": "FORECAST_GEO_AVAILABILITY_V1",
            },
        }
        result = self.allocator.allocate(
            rows,
            eligible_geo_labels_by_source_row_id={
                "row:period:1": first_ready,
                "row:period:2": second_ready,
            },
            eligibility_audit_by_source_row_id=audit,
        )
        counts = {
            row["source_row_id"]: row["eligible_geo_count"]
            for row in result.audit["source_row_reconciliation"]
        }
        self.assertEqual(counts, {"row:period:1": 175, "row:period:2": 174})
        self.assertLessEqual(
            result.audit["totals"]["difference_rub"],
            CONSERVATION_TOLERANCE_RUB,
        )
        self.assertTrue(all(row["source_row_id"] == "" for row in result.aggregated_rows))

    def test_historical_b1_goldens_keep_formula_controls_explicit(self) -> None:
        cases = _json("B2_0_GOLDEN_HISTORICAL_CASES.json")["cases"]
        eligibility = {
            row["case_id"]: row["eligible_geo_labels"]
            for row in _json("B2_1_HISTORICAL_ELIGIBLE_GEOS.json")["cases"]
        }
        population = {
            # B1 historical preprocessing loaded this column through pandas;
            # retaining numpy.float64 here makes the serialized golden vector
            # byte-for-byte comparable at the 12th decimal place.
            row["geo_label"]: np.float64(row["population_k"])
            for row in _csv_rows(POPULATION_PATH)
        }
        geo_ids = {
            row["geo_normalized_name"]: row["geo_id"]
            for row in _csv_rows(CATALOG_PATH)
        }
        for case in cases:
            expected = case["expected"]
            with self.subTest(case=case["case_id"]):
                labels = eligibility[case["case_id"]]
                denominator = math.fsum(population[label] for label in labels)
                rows = []
                for label in labels:
                    weight = population[label] / denominator
                    rows.append(
                        (
                            geo_ids[label],
                            weight,
                            case["source"]["budget_rub"] * weight,
                        )
                    )
                rows.sort()
                checksum = _hash_lines(
                    [
                        f"{geo_id}|{weight:.15f}|{budget:.12f}"
                        for geo_id, weight, budget in rows
                    ]
                )
                self.assertEqual(len(rows), expected["eligible_geo_count"])
                self.assertAlmostEqual(
                    denominator,
                    expected["population_denominator_k"],
                    places=6,
                )
                self.assertEqual(checksum, expected["allocation_vector_sha256"])
                self.assertLessEqual(
                    abs(math.fsum(row[2] for row in rows) - case["source"]["budget_rub"]),
                    CONSERVATION_TOLERANCE_RUB,
                )

    def test_audit_payload_contains_pinned_lineage_and_full_totals(self) -> None:
        result = self.allocator.allocate([_row()])
        audit = result.audit
        for key in (
            "policy_version",
            "package_id",
            "package_pointer_sha256",
            "registration_content_sha256",
            "support_source_sha256",
            "population_source_sha256",
            "geo_catalog_sha256",
            "source_row_reconciliation",
            "totals",
            "warnings",
            "errors",
        ):
            self.assertIn(key, audit)
        self.assertEqual(audit["federal_source_rows_n"], 1)
        self.assertEqual(audit["expanded_rows_before_aggregation_n"], 211)
        self.assertTrue(audit["totals"]["conservation_pass"])


class FederalGeoAllocatorFailureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.context = _context()
        self.allocator = FederalGeoAllocator(self.context)

    def _assert_code(self, code: str, rows: list[dict]) -> None:
        with self.assertRaises(FederalGeoAllocationError) as caught:
            self.allocator.allocate(rows)
        self.assertEqual(caught.exception.code, code)

    def test_unknown_alias(self) -> None:
        self._assert_code("UNKNOWN_GEO_VALUE", [_row(geo="Russia")])

    def test_unsupported_direction_channel_pair(self) -> None:
        self._assert_code(
            "DIRECTION_CHANNEL_NOT_SUPPORTED_BY_PACKAGE",
            [_row(direction="ТС5/Оффлайн", channel="Digital_Performance")],
        )

    def test_invalid_direction(self) -> None:
        self._assert_code("INVALID_BUSINESS_DIRECTION", [_row(direction="UNKNOWN")])

    def test_duplicate_source_row_id_on_same_day(self) -> None:
        self._assert_code(
            "DUPLICATE_SOURCE_ROW_ID",
            [_row(), _row(budget=1.0)],
        )

    def test_missing_source_row_id(self) -> None:
        self._assert_code("MISSING_SOURCE_ROW_ID", [_row(source_row_id="")])

    def test_nonfinite_and_negative_budget(self) -> None:
        for value in (math.nan, math.inf, -1.0):
            with self.subTest(value=value):
                self._assert_code("INVALID_BUDGET", [_row(budget=value)])

    def test_empty_supported_geo_set(self) -> None:
        empty = FederalGeoAllocationContext(
            **{
                **self.context.__dict__,
                "eligible_by_direction": {"ТС5/Онлайн": ()},
            }
        )
        with self.assertRaises(FederalGeoAllocationError) as caught:
            FederalGeoAllocator(empty).allocate([_row()])
        self.assertEqual(caught.exception.code, "EMPTY_SUPPORTED_GEO_SET")

    def test_forecast_boundary_rejects_any_approved_federal_alias(self) -> None:
        for geo in ("РФ", " россия ", "РОССИЙСКАЯ ФЕДЕРАЦИЯ"):
            with self.subTest(geo=geo):
                with self.assertRaises(FederalGeoAllocationError) as caught:
                    assert_no_federal_geo([{"geo": geo}])
                self.assertEqual(
                    caught.exception.code,
                    "FEDERAL_ROW_REACHED_FORECAST_BOUNDARY",
                )

    def test_context_is_pinned_and_allocator_performs_no_file_io(self) -> None:
        before = self.allocator.allocate([_row()])
        started = time.perf_counter()
        rows = [
            _row(source_row_id=f"perf:{index}", budget=1_000.0 + index)
            for index in range(100)
        ]
        with patch.object(Path, "open", side_effect=AssertionError("unexpected row I/O")):
            after = self.allocator.allocate(rows)
        self.assertLess(time.perf_counter() - started, 5.0)
        self.assertEqual(before.audit["package_id"], after.audit["package_id"])
        self.assertEqual(before.audit["package_pointer_sha256"], "1" * 64)

    def test_concurrent_pointer_change_cannot_mix_pinned_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pointer = Path(temporary) / "preprod.json"
            pointer.write_text(
                json.dumps({"package_id": self.context.package_id}),
                encoding="utf-8",
            )
            barrier = threading.Barrier(2)

            def change_pointer() -> None:
                barrier.wait()
                pointer.write_text(
                    json.dumps({"package_id": "pkg_changed_during_run"}),
                    encoding="utf-8",
                )

            worker = threading.Thread(target=change_pointer)
            worker.start()
            barrier.wait()
            result = self.allocator.allocate(
                [
                    _row(
                        source_row_id=f"concurrent:{index}",
                        budget=10_000.0,
                    )
                    for index in range(20)
                ]
            )
            worker.join(timeout=2.0)
            self.assertFalse(worker.is_alive())
            self.assertEqual(result.audit["package_id"], PACKAGE_ID)
            self.assertTrue(
                all(row["package_id"] == PACKAGE_ID for row in result.expanded_rows)
            )
            self.assertEqual(
                json.loads(pointer.read_text(encoding="utf-8"))["package_id"],
                "pkg_changed_during_run",
            )


class FederalContextLoaderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.snapshot = _json("B2_0_SUPPORTED_GEO_SNAPSHOT.json")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def _package(self, *, support_mismatch: bool = False) -> tuple[ModelPackage, dict[str, str]]:
        directions = self.snapshot["directions"]
        denominator: list[dict[str, str]] = []
        support: list[dict[str, str]] = []
        capabilities: list[dict[str, str]] = []
        for direction in directions:
            name = direction["business_direction"]
            for geo in direction["supported_geographies"]:
                denominator.append(
                    {"segment": name, "geo_label": geo["geo_label"]}
                )
                support.append(
                    {
                        "segment": name,
                        "target": "turnover_per_user",
                        "scope": "geo",
                        "geo_label": geo["geo_label"],
                    }
                )
            for channel in direction["package_capability_channels"]:
                capabilities.append(
                    {
                        "segment": name,
                        "target": "turnover_per_user",
                        "channel": channel,
                        "allowed_use": "primary",
                    }
                )
        if support_mismatch:
            support.pop()
        paths = {
            "target_denominator_metadata.csv": (
                denominator,
                ["segment", "geo_label"],
            ),
            "historical_support_bounds.csv": (
                support,
                ["segment", "target", "scope", "geo_label"],
            ),
            "capability_matrix.csv": (
                capabilities,
                ["segment", "target", "channel", "allowed_use"],
            ),
        }
        inventory: dict[str, str] = {}
        for name, (rows, fields) in paths.items():
            path = self.root / name
            self._write_csv(path, rows, fields)
            inventory[name] = sha256_file(path) or ""
        package = ModelPackage(
            self.root,
            {"segments": [row["business_direction"] for row in directions]},
            capabilities,
            [],
            {},
            support_rows=support,
        )
        return package, inventory

    def _load(
        self,
        package: ModelPackage,
        inventory: dict[str, str],
        *,
        population_path: Path = POPULATION_PATH,
        population_sha256: str = POPULATION_SHA256,
    ) -> FederalGeoAllocationContext:
        return FederalGeoAllocationContext.from_package(
            package,
            package_id=PACKAGE_ID,
            package_pointer_sha256="1" * 64,
            registration_content_sha256="2" * 64,
            registered_inventory_sha256=inventory,
            population_path=population_path,
            expected_population_sha256=population_sha256,
            geo_catalog_path=CATALOG_PATH,
            expected_geo_catalog_sha256=CATALOG_SHA256,
        )

    def test_loads_verified_support_once_and_crosschecks_all_directions(self) -> None:
        package, inventory = self._package()
        context = self._load(package, inventory)
        self.assertEqual(
            {key: len(value) for key, value in context.eligible_by_direction.items()},
            {"ТС5/Онлайн": 211, "ТС5/Оффлайн": 220, "ТСХ/Онлайн": 114, "ТСХ/Оффлайн": 117},
        )

    def test_corrupted_registered_hash_is_rejected(self) -> None:
        package, inventory = self._package()
        inventory["historical_support_bounds.csv"] = "0" * 64
        with self.assertRaises(FederalGeoAllocationError) as caught:
            self._load(package, inventory)
        self.assertEqual(caught.exception.code, "PACKAGE_POINTER_OR_HASH_MISMATCH")

    def test_support_denominator_mismatch_is_rejected(self) -> None:
        package, inventory = self._package(support_mismatch=True)
        with self.assertRaises(FederalGeoAllocationError) as caught:
            self._load(package, inventory)
        self.assertEqual(caught.exception.code, "PACKAGE_POINTER_OR_HASH_MISMATCH")

    def test_missing_population_blocks_only_when_geo_is_in_ready_universe(self) -> None:
        package, inventory = self._package()
        rows = _csv_rows(POPULATION_PATH)
        for row in rows:
            if row["geo_label"] == "МОСКВА":
                row["population_k"] = ""
        mutated = self.root / "population.csv"
        self._write_csv(mutated, rows, list(rows[0]))
        context = self._load(
            package,
            inventory,
            population_path=mutated,
            population_sha256=sha256_file(mutated) or "",
        )
        allocator = FederalGeoAllocator(context)
        with self.assertRaises(FederalGeoAllocationError) as caught:
            allocator.allocate([_row()])
        self.assertEqual(
            caught.exception.code,
            "FEDERAL_POPULATION_MISSING_OR_NONPOSITIVE",
        )
        ready_without_moscow = tuple(
            geo.geo_label
            for geo in context.eligible_by_direction["ТС5/Онлайн"]
            if geo.geo_label != "МОСКВА"
        )
        result = allocator.allocate(
            [_row()],
            eligible_geo_labels_by_source_row_id={"row:1": ready_without_moscow},
        )
        self.assertEqual(len(result.aggregated_rows), 210)

    def test_supported_geo_missing_from_catalog_is_rejected(self) -> None:
        package, inventory = self._package()
        denominator_path = self.root / "target_denominator_metadata.csv"
        support_path = self.root / "historical_support_bounds.csv"
        with denominator_path.open("a", encoding="utf-8") as handle:
            handle.write("ТС5/Онлайн,НЕСУЩЕСТВУЮЩЕЕ ГЕО\n")
        with support_path.open("a", encoding="utf-8") as handle:
            handle.write(
                "ТС5/Онлайн,turnover_per_user,geo,НЕСУЩЕСТВУЮЩЕЕ ГЕО\n"
            )
        inventory[denominator_path.name] = sha256_file(denominator_path) or ""
        inventory[support_path.name] = sha256_file(support_path) or ""
        with self.assertRaises(FederalGeoAllocationError) as caught:
            self._load(package, inventory)
        self.assertEqual(caught.exception.code, "SUPPORTED_GEO_NOT_IN_CATALOG")


class FederalGeoAllocationEntrypointTest(unittest.TestCase):
    def test_forecast_and_optimizer_forward_verified_model_resolution(self) -> None:
        """Every executable preparation path must carry the pinned package identity."""

        entrypoints = (
            PROJECT_ROOT / "02_Code" / "02_Budget_optimizer" / "budget_optimizer.py",
            PROJECT_ROOT / "02_Code" / "03_AC_forecast" / "ac_forecast.py",
        )
        for path in entrypoints:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            calls = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "prepare_campaign_from_config"
            ]
            self.assertTrue(calls, path.name)
            for call in calls:
                forwarded = next(
                    (
                        keyword.value
                        for keyword in call.keywords
                        if keyword.arg == "model_resolution"
                    ),
                    None,
                )
                self.assertIsInstance(forwarded, ast.Name, path.name)
                self.assertEqual(forwarded.id, "model_resolution", path.name)


if __name__ == "__main__":
    unittest.main()
