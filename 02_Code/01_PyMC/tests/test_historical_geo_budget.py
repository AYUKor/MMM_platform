from __future__ import annotations

import hashlib
import json
import math
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


PYMC_DIR = Path(__file__).resolve().parents[1]
import sys

if str(PYMC_DIR) not in sys.path:
    sys.path.insert(0, str(PYMC_DIR))

from mmm_core.historical_geo_budget import (  # noqa: E402
    ARTIFACT_VERSION,
    METADATA_FILENAME,
    PACKAGE_ARTIFACTS_MANIFEST_FILENAME,
    PARQUET_FILENAME,
    HistoricalGeoBudgetError,
    RegistryPackageIdentity,
    aggregate_panel,
    build_historical_geo_budget_artifact,
    load_registry_package_identity,
    load_spend_columns_policy,
    resolve_registered_panel,
    sha256_file,
)


POLICY_PATH = (
    PYMC_DIR / "configs" / "historical_geo_budget_spend_columns_v1.json"
)
PACKAGE_ID = "pkg_0123456789abcdef_fedcba9876543210"
GENERATED_AT = "2026-07-19T08:00:00+00:00"


def _canonical_sha(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_panel(
    path: Path,
    *,
    digital: list[float] | None = None,
    omit_column: str | None = None,
) -> None:
    columns: dict[str, object] = {
        "date": [
            datetime(2025, 1, 1),
            datetime(2025, 1, 1),
            datetime(2025, 1, 2),
            datetime(2025, 1, 1),
            datetime(2025, 1, 2),
        ],
        "geo_label": ["ГЕО А", "ГЕО А", "ГЕО А", "ГЕО Б", "ГЕО Б"],
        "spend_Digital_Performance": digital or [10.0, 5.0, 0.0, 0.0, 3.0],
        "spend_OOH_Total": [1.0, 0.0, 0.0, 0.0, 0.0],
        "spend_Indoor": [0.0] * 5,
        "spend_Радио": [0.0] * 5,
        "spend_Нац_ТВ": [0.0] * 5,
        "spend_Рег_ТВ": [0.0] * 5,
        "spend_OOH": [1000.0] * 5,
        "spend_ООН_РТБ": [2000.0] * 5,
        "unrelated_target": [1.0] * 5,
    }
    if omit_column:
        columns.pop(omit_column)
    pq.write_table(pa.table(columns), path)


def _identity(panel: Path) -> RegistryPackageIdentity:
    return RegistryPackageIdentity(
        package_id=PACKAGE_ID,
        package_input_fingerprint="a" * 64,
        model_run_id="synthetic_run/synthetic_variant",
        panel_recorded_path="data/panel.parquet",
        panel_sha256=sha256_file(panel),
        panel_size_bytes=panel.stat().st_size,
        registration_content_sha256="b" * 64,
    )


class HistoricalGeoBudgetBuilderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_spend_columns_policy(POLICY_PATH)

    def test_policy_is_the_only_selected_spend_definition(self) -> None:
        self.assertEqual(
            self.policy.spend_columns,
            (
                "spend_Digital_Performance",
                "spend_OOH_Total",
                "spend_Indoor",
                "spend_Радио",
                "spend_Нац_ТВ",
                "spend_Рег_ТВ",
            ),
        )
        self.assertNotIn("spend_OOH", self.policy.spend_columns)
        self.assertNotIn("spend_ООН_РТБ", self.policy.spend_columns)

    def test_exact_aggregation_ignores_overlapping_source_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            panel = Path(temporary) / "panel.parquet"
            _write_panel(panel)
            result = aggregate_panel(panel, self.policy, batch_size=2)
        self.assertEqual(result.source_rows_n, 5)
        self.assertEqual(result.source_columns_n, 11)
        self.assertEqual(result.period_start, "2025-01-01")
        self.assertEqual(result.period_end, "2025-01-02")
        self.assertEqual(result.geographies_n, 2)
        self.assertEqual(result.total_budget_rub, 19.0)
        self.assertEqual(result.selected_column_totals_rub["spend_OOH_Total"], 1.0)
        self.assertEqual(result.active_rows_n, 3)
        self.assertEqual(result.zero_spend_rows_n, 2)
        first, second = result.rows
        self.assertEqual(first["geo_model_name"], "ГЕО А")
        self.assertEqual(first["historical_total_budget_rub"], 16.0)
        self.assertEqual(first["active_days_n"], 1)
        self.assertEqual(first["active_rows_n"], 2)
        self.assertEqual(first["source_rows_n"], 3)
        self.assertEqual(second["historical_total_budget_rub"], 3.0)
        self.assertEqual(second["active_days_n"], 1)
        self.assertEqual(second["active_rows_n"], 1)
        self.assertAlmostEqual(
            math.fsum(row["budget_share"] for row in result.rows),
            1.0,
        )

    def test_schema_and_value_failures_are_explicit(self) -> None:
        cases = (
            ([10.0, -1.0, 0.0, 0.0, 3.0], None, "negative"),
            ([10.0, float("nan"), 0.0, 0.0, 3.0], None, "NaN or infinite"),
            ([10.0, float("inf"), 0.0, 0.0, 3.0], None, "NaN or infinite"),
            (None, "spend_Indoor", "missing required columns"),
        )
        for index, (digital, missing, message) in enumerate(cases):
            with self.subTest(case=index), tempfile.TemporaryDirectory() as temporary:
                panel = Path(temporary) / "panel.parquet"
                _write_panel(panel, digital=digital, omit_column=missing)
                with self.assertRaisesRegex(HistoricalGeoBudgetError, message):
                    aggregate_panel(panel, self.policy)

    def test_overlap_policy_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "policy.json"
            payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
            payload["spend_columns"].append("spend_OOH")
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(HistoricalGeoBudgetError, "overlaps"):
                load_spend_columns_policy(path)

    def test_artifact_and_metadata_are_deterministic_and_path_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            panel = root / "panel.parquet"
            _write_panel(panel)
            identity = _identity(panel)
            first = root / "first" / ARTIFACT_VERSION
            second = root / "second" / ARTIFACT_VERSION
            first_result = build_historical_geo_budget_artifact(
                identity=identity,
                panel_path=panel,
                policy=self.policy,
                output_dir=first,
                generated_at_utc=GENERATED_AT,
                batch_size=2,
            )
            second_result = build_historical_geo_budget_artifact(
                identity=identity,
                panel_path=panel,
                policy=self.policy,
                output_dir=second,
                generated_at_utc=GENERATED_AT,
                batch_size=3,
            )
            self.assertEqual(
                (first / PARQUET_FILENAME).read_bytes(),
                (second / PARQUET_FILENAME).read_bytes(),
            )
            self.assertEqual(
                (first / METADATA_FILENAME).read_bytes(),
                (second / METADATA_FILENAME).read_bytes(),
            )
            self.assertEqual(
                (first.parent / PACKAGE_ARTIFACTS_MANIFEST_FILENAME).read_bytes(),
                (second.parent / PACKAGE_ARTIFACTS_MANIFEST_FILENAME).read_bytes(),
            )
            metadata = first_result["metadata"]
            self.assertEqual(metadata, second_result["metadata"])
            self.assertEqual(metadata["artifact_version"], ARTIFACT_VERSION)
            self.assertEqual(metadata["total_budget_rub"], 19.0)
            self.assertEqual(metadata["rows_n"], 2)
            self.assertEqual(metadata["source_rows_n"], 5)
            self.assertEqual(metadata["source_columns_n"], 11)
            self.assertEqual(metadata["relative_path"], PARQUET_FILENAME)
            serialized = json.dumps(metadata, ensure_ascii=False)
            self.assertNotIn(str(root), serialized)
            self.assertNotIn("/mnt/data", serialized)
            self.assertEqual(
                metadata["sha256"], sha256_file(first / PARQUET_FILENAME)
            )
            manifest_entry = first_result["package_artifacts_manifest"]["artifacts"][0]
            for field in (
                "source_panel_sha256",
                "period_start",
                "period_end",
                "spend_columns",
                "spend_columns_version",
                "rows_n",
                "geographies_n",
                "total_budget_rub",
                "generated_at_utc",
            ):
                self.assertEqual(manifest_entry[field], metadata[field])
            # An idempotent rerun accepts byte-identical immutable artifacts.
            build_historical_geo_budget_artifact(
                identity=identity,
                panel_path=panel,
                policy=self.policy,
                output_dir=first,
                generated_at_utc=GENERATED_AT,
                batch_size=5,
            )
            with self.assertRaises(FileExistsError):
                build_historical_geo_budget_artifact(
                    identity=identity,
                    panel_path=panel,
                    policy=self.policy,
                    output_dir=first,
                    generated_at_utc="2026-07-19T09:00:00+00:00",
                )

    def test_registry_metadata_resolves_panel_without_mnt_hardcode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            panel = root / "data" / "panel.parquet"
            panel.parent.mkdir()
            _write_panel(panel)
            registry = root / "registry"
            registration_path = registry / "registrations" / f"{PACKAGE_ID}.json"
            registration_path.parent.mkdir(parents=True)
            registration = {
                "registry_schema_version": "1.0.0",
                "package_id": PACKAGE_ID,
                "model_run_id": "synthetic_run/synthetic_variant",
                "run_dir": "outputs/package",
                "package_input_fingerprint": "a" * 64,
                "package_schema_version": "0.4.0",
                "panel": {
                    "path": "data/panel.parquet",
                    "sha256": sha256_file(panel),
                    "size_bytes": panel.stat().st_size,
                },
                "inventory_sha256": {},
                "registered_at_utc": GENERATED_AT,
                "registered_by": "Synthetic test",
                "reason": "Synthetic package binding",
            }
            immutable = dict(registration)
            for key in ("registered_at_utc", "registered_by", "reason"):
                immutable.pop(key)
            registration["registration_content_sha256"] = _canonical_sha(immutable)
            registration_path.write_text(
                json.dumps(registration, ensure_ascii=False),
                encoding="utf-8",
            )
            identity = load_registry_package_identity(registry, PACKAGE_ID)
            self.assertEqual(
                resolve_registered_panel(identity, project_root=root),
                panel.resolve(),
            )
            self.assertNotEqual(identity.panel_recorded_path, "/mnt/data/panel.parquet")
            panel.write_bytes(b"mutated")
            with self.assertRaisesRegex(HistoricalGeoBudgetError, "size has changed"):
                resolve_registered_panel(identity, project_root=root)


if __name__ == "__main__":
    unittest.main()
