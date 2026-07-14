"""Synthetic contract tests for OOT and independent response replay."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

PYMC_CODE_DIR = Path(__file__).resolve().parents[1]
if str(PYMC_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(PYMC_CODE_DIR))

from mmm_core.validation import (  # noqa: E402
    OOTSplit,
    build_oot_feature_snapshot,
    classify_oot_metrics,
    evaluate_historical_response_replay,
    evaluate_oot_input_coverage,
    evaluate_predictive_oot,
    validate_oot_split,
)


class OOTContractTests(unittest.TestCase):
    @staticmethod
    def _required_inputs() -> list[dict[str, str]]:
        return [
            {"input_kind": "targets", "segment": "ТС5/Онлайн", "name": "turnover_per_user"},
            {"input_kind": "own_media", "segment": "ТС5/Онлайн", "name": "spend_Радио"},
            {"input_kind": "competitor_media", "segment": "ТС5/Онлайн", "name": "compet_spend_OOH"},
            {"input_kind": "controls", "segment": "ТС5/Онлайн", "name": "ruonia_change"},
        ]

    @staticmethod
    def _complete_coverage_manifest() -> dict:
        source_hash = "a" * 64
        rows = []
        for required in OOTContractTests._required_inputs():
            rows.append(
                {
                    **required,
                    "status": "complete",
                    "coverage_start": "2026-03-01",
                    "coverage_end": "2026-04-30",
                    "missing_dates_n": 0,
                    "missing_rows_n": 0,
                    "source_sha256": source_hash,
                }
            )
        return {
            "schema_version": "1.0.0",
            "status": "complete",
            "panel_sha256": "panel-hash",
            "oot_start": "2026-03-21",
            "oot_end": "2026-04-30",
            "missing_delivery_is_zero": False,
            "coverage_rows": rows,
        }

    def test_complete_input_coverage_passes(self) -> None:
        result = evaluate_oot_input_coverage(
            self._complete_coverage_manifest(),
            OOTSplit(
                train_end="2026-03-20",
                oot_start="2026-03-21",
                oot_end="2026-04-30",
            ),
            self._required_inputs(),
            panel_sha256="panel-hash",
        )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["reason_codes"], ["OK"])

    def test_incomplete_delivery_is_unavailable_not_model_failure(self) -> None:
        manifest = self._complete_coverage_manifest()
        manifest["status"] = "incomplete"
        manifest["blockers"] = [{"code": "COMPETITOR_OOH_COVERAGE_END_TOO_EARLY"}]
        result = evaluate_oot_input_coverage(
            manifest,
            OOTSplit(
                train_end="2026-03-20",
                oot_start="2026-03-21",
                oot_end="2026-04-30",
            ),
            self._required_inputs(),
            panel_sha256="panel-hash",
        )
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("COVERAGE_MANIFEST_STATUS_INCOMPLETE", result["reason_codes"])

    def test_trailing_zero_without_source_coverage_fails_closed(self) -> None:
        manifest = self._complete_coverage_manifest()
        competitor = next(
            row for row in manifest["coverage_rows"] if row["input_kind"] == "competitor_media"
        )
        competitor["coverage_end"] = "2025-12-29"
        result = evaluate_oot_input_coverage(
            manifest,
            OOTSplit(
                train_end="2026-03-20",
                oot_start="2026-03-21",
                oot_end="2026-04-30",
            ),
            self._required_inputs(),
            panel_sha256="panel-hash",
        )
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("INVALID_REQUIRED_INPUT_COVERAGE", result["reason_codes"])

    def test_temporal_overlap_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "OOT leakage"):
            validate_oot_split(
                OOTSplit(
                    train_end="2026-03-21",
                    oot_start="2026-03-21",
                    oot_end="2026-04-30",
                )
            )

    def test_development_seen_split_cannot_be_activation_evidence(self) -> None:
        split = validate_oot_split(
            OOTSplit(
                train_end="2026-03-20",
                oot_start="2026-03-21",
                oot_end="2026-05-31",
                development_seen=True,
            )
        )
        self.assertFalse(split["activation_evidence_allowed"])
        self.assertEqual(split["evidence_role"], "shadow_development_seen")

    def test_feature_snapshot_excludes_target_and_derived_outcomes(self) -> None:
        dates = pd.date_range("2026-03-07", "2026-04-20", freq="D")
        panel = pd.DataFrame(
            {
                "date": dates,
                "geo_label": "G",
                "network": "ТС5",
                "channel": "Онлайн",
                "population_k": 100.0,
                "market_size_tier": "small",
                "spend_Радио": 10.0,
                "ruonia_change": 0.1,
                "turnover_per_user": 1000.0,
                "orders_cnt": 100,
                "unique_users": 90,
            }
        )
        transform = {
            "fit_key": "ТС5/Онлайн::turnover_per_user",
            "geos": ["G"],
            "spend_active": ["spend_Радио"],
            "controls": ["ruonia_change"],
        }
        snapshot, outcomes = build_oot_feature_snapshot(
            panel,
            transform,
            OOTSplit(
                train_end="2026-03-20",
                oot_start="2026-03-21",
                oot_end="2026-04-20",
            ),
        )
        self.assertNotIn("turnover_per_user", snapshot.columns)
        self.assertNotIn("orders_cnt", snapshot.columns)
        self.assertNotIn("unique_users", snapshot.columns)
        self.assertIn("turnover_per_user", outcomes.columns)

    def test_unknown_geos_are_filtered_only_for_development_seen_shadow(self) -> None:
        dates = pd.date_range("2026-03-07", "2026-04-20", freq="D")
        panel = pd.concat(
            [
                pd.DataFrame(
                    {
                        "date": dates,
                        "geo_label": geo,
                        "network": "ТС5",
                        "channel": "Онлайн",
                        "population_k": 100.0,
                        "market_size_tier": "small",
                        "spend_Радио": 10.0,
                        "ruonia_change": 0.1,
                        "turnover_per_user": 1000.0,
                    }
                )
                for geo in ["KNOWN", "NEW"]
            ],
            ignore_index=True,
        )
        transform = {
            "fit_key": "ТС5/Онлайн::turnover_per_user",
            "geos": ["KNOWN"],
            "spend_active": ["spend_Радио"],
            "controls": ["ruonia_change"],
        }
        sealed = OOTSplit(
            train_end="2026-03-20",
            oot_start="2026-03-21",
            oot_end="2026-04-20",
        )
        with self.assertRaisesRegex(ValueError, "unknown geos"):
            build_oot_feature_snapshot(panel, transform, sealed)

        snapshot, outcomes = build_oot_feature_snapshot(
            panel,
            transform,
            OOTSplit(
                train_end=sealed.train_end,
                oot_start=sealed.oot_start,
                oot_end=sealed.oot_end,
                development_seen=True,
            ),
        )
        self.assertEqual(set(snapshot["geo_label"]), {"KNOWN"})
        self.assertEqual(set(outcomes["geo_label"]), {"KNOWN"})
        self.assertEqual(snapshot.attrs["geo_coverage"]["unknown_geos_excluded_n"], 1)
        self.assertAlmostEqual(snapshot.attrs["geo_coverage"]["known_geo_row_coverage"], 0.5)

    def test_predictive_metrics_and_gate(self) -> None:
        dates = pd.date_range("2026-04-01", periods=30, freq="D")
        actual = np.linspace(100.0, 129.0, 30)
        predictions = pd.DataFrame(
            {
                "date": dates,
                "geo_label": "G",
                "mean": actual,
                "p05": actual - 1,
                "p95": actual + 1,
            }
        )
        predictions.loc[:2, "p05"] = actual[:3] + 2
        predictions.loc[:2, "p95"] = actual[:3] + 3
        draws = np.repeat(actual[:, None], 20, axis=1)
        outcomes = pd.DataFrame({"date": dates, "geo_label": "G", "target": actual})
        train_dates = pd.date_range("2026-01-01", periods=60, freq="D")
        training = pd.DataFrame(
            {
                "date": train_dates,
                "geo_label": "G",
                "target": np.linspace(40.0, 99.0, 60),
            }
        )
        metrics = evaluate_predictive_oot(predictions, draws, outcomes, training, target="target")
        self.assertEqual(classify_oot_metrics(metrics), "primary")
        self.assertAlmostEqual(float(metrics["mase"]), 0.0)
        self.assertAlmostEqual(float(metrics["coverage_90"]), 0.9)


class HistoricalReplayContractTests(unittest.TestCase):
    @staticmethod
    def _frames(delta: float = 0.0) -> tuple[pd.DataFrame, pd.DataFrame]:
        rows = []
        for draw in [0, 1]:
            rows.append(
                {
                    "fit_key": "S::T",
                    "channel": "C",
                    "chain": 0,
                    "draw": draw,
                    "row_id": "R",
                    "effect_value": 100.0 + draw,
                    "effect_unit": "incremental_turnover_rub",
                    "spend_rub": 50.0,
                    "producer": "model_side_reference",
                }
            )
        reference = pd.DataFrame(rows)
        replayed = reference.copy()
        replayed["producer"] = "forecast_engine"
        replayed["effect_value"] += delta
        return reference, replayed

    def test_independent_replay_passes_inside_unit_tolerance(self) -> None:
        reference, replayed = self._frames(delta=0.5)
        verdict = evaluate_historical_response_replay(
            reference,
            replayed,
            expected_fits=1,
            expected_effects=1,
            expected_draws=2,
        )
        self.assertEqual(verdict["status"], "passed")

    def test_replay_mismatch_fails(self) -> None:
        reference, replayed = self._frames(delta=2.0)
        verdict = evaluate_historical_response_replay(
            reference,
            replayed,
            expected_fits=1,
            expected_effects=1,
            expected_draws=2,
        )
        self.assertEqual(verdict["status"], "failed")
        self.assertEqual(verdict["effect_mismatch_rows"], 2)

    def test_same_producer_is_not_independent(self) -> None:
        reference, replayed = self._frames()
        replayed["producer"] = "model_side_reference"
        with self.assertRaisesRegex(ValueError, "not independent"):
            evaluate_historical_response_replay(
                reference,
                replayed,
                expected_fits=1,
                expected_effects=1,
                expected_draws=2,
            )


if __name__ == "__main__":
    unittest.main()
