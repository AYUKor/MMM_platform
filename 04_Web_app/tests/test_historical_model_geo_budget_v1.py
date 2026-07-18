from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


WEB_APP_DIR = Path(__file__).resolve().parents[1]
PYMC_DIR = WEB_APP_DIR.parent / "02_Code" / "01_PyMC"
for entry in (WEB_APP_DIR, PYMC_DIR):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from contracts.historical_model_geo_budget_v1 import (  # noqa: E402
    HistoricalModelGeoBudgetContractError,
    load_historical_model_geo_budget_v1_schema,
    validate_historical_model_geo_budget_v1,
)
from mmm_core.historical_geo_budget import (  # noqa: E402
    ARTIFACT_VERSION,
    METADATA_FILENAME,
    PACKAGE_ARTIFACTS_MANIFEST_FILENAME,
    PARQUET_FILENAME,
    load_spend_columns_policy,
)
from services.historical_model_geo_budget import (  # noqa: E402
    HistoricalModelGeoBudgetError,
    SPEND_POLICY_PATH,
    build_historical_model_geo_budget_v1,
)


PACKAGE_ID = "pkg_0123456789abcdef_fedcba9876543210"
SOURCE_SHA = "9" * 64
FINGERPRINT = "8" * 64
REGISTRATION_TIME = "2026-07-19T08:00:00+00:00"


def _canonical_sha(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_package_artifact(
    registry: Path,
    *,
    geographies: tuple[tuple[str, float, float], ...] = (
        ("МОСКВА", 75.0, 0.75),
        ("СПБ", 25.0, 0.25),
    ),
) -> tuple[Path, dict]:
    registration = {
        "registry_schema_version": "1.0.0",
        "package_id": PACKAGE_ID,
        "model_run_id": "synthetic_run/turnover_only",
        "run_dir": "outputs/synthetic_package",
        "package_input_fingerprint": FINGERPRINT,
        "package_schema_version": "0.4.0",
        "panel": {
            "path": "data/panel.parquet",
            "sha256": SOURCE_SHA,
            "size_bytes": 12345,
        },
        "inventory_sha256": {},
        "registered_at_utc": REGISTRATION_TIME,
        "registered_by": "Synthetic test",
        "reason": "Synthetic historical geo-budget fixture",
    }
    immutable = dict(registration)
    for key in ("registered_at_utc", "registered_by", "reason"):
        immutable.pop(key)
    registration_sha = _canonical_sha(immutable)
    registration["registration_content_sha256"] = registration_sha
    _write_json(
        registry / "registrations" / f"{PACKAGE_ID}.json",
        registration,
    )

    policy = load_spend_columns_policy(SPEND_POLICY_PATH)
    artifact_root = registry / "package_artifacts" / PACKAGE_ID
    artifact_dir = artifact_root / ARTIFACT_VERSION
    artifact_dir.mkdir(parents=True)
    artifact_path = artifact_dir / PARQUET_FILENAME
    artifact_path.write_bytes(b"synthetic historical geo budget parquet evidence")
    rows = [
        {
            "geo_model_name": geo,
            "period_start": "2025-01-01",
            "period_end": "2026-05-31",
            "historical_total_budget_rub": budget,
            "active_days_n": index + 2,
            "active_rows_n": index + 3,
            "budget_share": share,
            "source_rows_n": index + 10,
            "artifact_version": ARTIFACT_VERSION,
            "source_panel_sha256": SOURCE_SHA,
            "spend_columns_version": policy.spend_columns_version,
        }
        for index, (geo, budget, share) in enumerate(geographies)
    ]
    metadata = {
        "metadata_schema_version": "1.0.0",
        "artifact_id": "artifact_0123456789abcdef01234567",
        "artifact_version": ARTIFACT_VERSION,
        "relative_path": PARQUET_FILENAME,
        "sha256": _sha(artifact_path),
        "size_bytes": artifact_path.stat().st_size,
        "package_id": PACKAGE_ID,
        "package_input_fingerprint": FINGERPRINT,
        "model_run_id": registration["model_run_id"],
        "registration_content_sha256": registration_sha,
        "source_panel_sha256": SOURCE_SHA,
        "source_panel_size_bytes": 12345,
        "source_rows_n": 20,
        "source_columns_n": 109,
        "source_row_groups_n": 1,
        "period_start": "2025-01-01",
        "period_end": "2026-05-31",
        "spend_columns": list(policy.spend_columns),
        "spend_columns_version": policy.spend_columns_version,
        "spend_columns_config_sha256": policy.config_sha256,
        "selected_column_totals_rub": {
            column: (sum(value[1] for value in geographies) if index == 0 else 0.0)
            for index, column in enumerate(policy.spend_columns)
        },
        "rows_n": len(rows),
        "geographies_n": len(rows),
        "total_budget_rub": sum(value[1] for value in geographies),
        "active_rows_n": sum(row["active_rows_n"] for row in rows),
        "zero_spend_rows_n": 0,
        "generated_at_utc": REGISTRATION_TIME,
        "row_sort": "geo_model_name_ascending",
        "null_policy": "fail_closed",
        "negative_policy": "fail_closed",
        "infinite_policy": "fail_closed",
        "rows": rows,
    }
    metadata_path = artifact_dir / METADATA_FILENAME
    _write_json(metadata_path, metadata)
    manifest = {
        "manifest_schema_version": "1.0.0",
        "package_id": PACKAGE_ID,
        "package_input_fingerprint": FINGERPRINT,
        "registration_content_sha256": registration_sha,
        "source_panel_sha256": SOURCE_SHA,
        "artifacts": [
            {
                "artifact_id": metadata["artifact_id"],
                "artifact_kind": ARTIFACT_VERSION,
                "artifact_version": ARTIFACT_VERSION,
                "relative_path": f"{ARTIFACT_VERSION}/{PARQUET_FILENAME}",
                "sha256": metadata["sha256"],
                "size_bytes": metadata["size_bytes"],
                "metadata_relative_path": f"{ARTIFACT_VERSION}/{METADATA_FILENAME}",
                "metadata_sha256": _sha(metadata_path),
                "source_panel_sha256": metadata["source_panel_sha256"],
                "period_start": metadata["period_start"],
                "period_end": metadata["period_end"],
                "spend_columns": metadata["spend_columns"],
                "spend_columns_version": metadata["spend_columns_version"],
                "rows_n": metadata["rows_n"],
                "geographies_n": metadata["geographies_n"],
                "total_budget_rub": metadata["total_budget_rub"],
                "generated_at_utc": metadata["generated_at_utc"],
            }
        ],
    }
    _write_json(artifact_root / PACKAGE_ARTIFACTS_MANIFEST_FILENAME, manifest)
    return artifact_path, metadata


class HistoricalModelGeoBudgetServiceTest(unittest.TestCase):
    def test_available_projection_uses_catalog_and_has_no_campaign_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            registry = Path(temporary) / "registry"
            _write_package_artifact(registry)
            payload = build_historical_model_geo_budget_v1(
                registry_root=registry,
                package_id=PACKAGE_ID,
            )
        validate_historical_model_geo_budget_v1(payload)
        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["total_budget_rub"], 100.0)
        self.assertEqual(payload["geographies_n"], 2)
        self.assertEqual(
            {row["geo_display_name"] for row in payload["rows"]},
            {"Москва", "Санкт-Петербург"},
        )
        self.assertEqual(payload["coverage"]["located_geographies_n"], 2)
        self.assertEqual(payload["coverage"]["unlocated_budget_rub"], 0.0)
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("campaigns_n", serialized)
        self.assertNotIn("/Users/", serialized)
        self.assertNotIn("/mnt/data", serialized)

    def test_partial_projection_keeps_unknown_geography_and_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            registry = Path(temporary) / "registry"
            _write_package_artifact(
                registry,
                geographies=(
                    ("МОСКВА", 75.0, 0.75),
                    ("НЕИЗВЕСТНАЯ ГЕОГРАФИЯ", 25.0, 0.25),
                ),
            )
            payload = build_historical_model_geo_budget_v1(
                registry_root=registry,
                package_id=PACKAGE_ID,
            )
        self.assertEqual(payload["status"], "partial")
        self.assertEqual(payload["coverage"]["unlocated_geographies_n"], 1)
        self.assertEqual(payload["coverage"]["unlocated_budget_rub"], 25.0)
        self.assertEqual(payload["coverage"]["unlocated_budget_share"], 0.25)
        unknown = next(
            row for row in payload["rows"] if row["coordinates_status"] == "unavailable"
        )
        self.assertEqual(unknown["historical_total_budget_rub"], 25.0)
        self.assertIsNone(unknown["latitude"])

    def test_all_unknown_geographies_remain_in_unavailable_map_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            registry = Path(temporary) / "registry"
            _write_package_artifact(
                registry,
                geographies=(("НЕИЗВЕСТНАЯ ГЕОГРАФИЯ", 100.0, 1.0),),
            )
            payload = build_historical_model_geo_budget_v1(
                registry_root=registry,
                package_id=PACKAGE_ID,
            )
        self.assertEqual(payload["record_origin"], "verified_model_package_artifact")
        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["geographies_n"], 1)
        self.assertEqual(payload["total_budget_rub"], 100.0)
        self.assertEqual(payload["coverage"]["unlocated_budget_rub"], 100.0)

    def test_old_package_without_artifact_is_controlled_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            registry = Path(temporary) / "registry"
            artifact_path, _ = _write_package_artifact(registry)
            artifact_root = artifact_path.parents[1]
            (artifact_root / PACKAGE_ARTIFACTS_MANIFEST_FILENAME).unlink()
            payload = build_historical_model_geo_budget_v1(
                registry_root=registry,
                package_id=PACKAGE_ID,
            )
        self.assertEqual(payload["record_origin"], "model_package_artifact_unavailable")
        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["rows"], [])
        self.assertIsNone(payload["total_budget_rub"])

    def test_tamper_and_duplicate_canonical_resolution_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            registry = Path(temporary) / "registry"
            artifact_path, _ = _write_package_artifact(registry)
            artifact_path.write_bytes(b"tampered")
            with self.assertRaisesRegex(HistoricalModelGeoBudgetError, "integrity"):
                build_historical_model_geo_budget_v1(
                    registry_root=registry,
                    package_id=PACKAGE_ID,
                )
        with tempfile.TemporaryDirectory() as temporary:
            registry = Path(temporary) / "registry"
            artifact_path, _ = _write_package_artifact(registry)
            manifest_path = (
                artifact_path.parents[1] / PACKAGE_ARTIFACTS_MANIFEST_FILENAME
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["artifacts"][0]["total_budget_rub"] = 999.0
            _write_json(manifest_path, manifest)
            with self.assertRaisesRegex(
                HistoricalModelGeoBudgetError,
                "manifest metadata differs",
            ):
                build_historical_model_geo_budget_v1(
                    registry_root=registry,
                    package_id=PACKAGE_ID,
                )
        with tempfile.TemporaryDirectory() as temporary:
            registry = Path(temporary) / "registry"
            _write_package_artifact(
                registry,
                geographies=(
                    ("МОСКВА", 50.0, 0.5),
                    ("г. Москва", 50.0, 0.5),
                ),
            )
            with self.assertRaisesRegex(HistoricalModelGeoBudgetError, "one canonical"):
                build_historical_model_geo_budget_v1(
                    registry_root=registry,
                    package_id=PACKAGE_ID,
                )

    def test_schema_and_semantic_validator_reject_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            registry = Path(temporary) / "registry"
            _write_package_artifact(registry)
            payload = build_historical_model_geo_budget_v1(
                registry_root=registry,
                package_id=PACKAGE_ID,
            )
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema is optional in the local source runtime")
        jsonschema.Draft202012Validator(
            load_historical_model_geo_budget_v1_schema(),
            format_checker=jsonschema.FormatChecker(),
        ).validate(payload)
        broken = copy.deepcopy(payload)
        broken["rows"][0]["historical_total_budget_rub"] += 1
        with self.assertRaisesRegex(
            HistoricalModelGeoBudgetContractError,
            "does not reconcile",
        ):
            validate_historical_model_geo_budget_v1(broken)
        broken = copy.deepcopy(payload)
        broken["campaigns_n"] = 2
        with self.assertRaisesRegex(
            HistoricalModelGeoBudgetContractError,
            "Campaign-count",
        ):
            validate_historical_model_geo_budget_v1(broken)


if __name__ == "__main__":
    unittest.main()
