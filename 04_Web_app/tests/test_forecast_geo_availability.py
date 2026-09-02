from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

import pandas as pd


WEB_APP_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = WEB_APP_DIR.parent
PYMC_CODE_DIR = REPO_DIR / "02_Code" / "01_PyMC"
for entry in (WEB_APP_DIR, PYMC_CODE_DIR):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from mmm_core.forecast_geo_availability import (  # noqa: E402
    ForecastGeoAvailabilityResolver,
    HistoricalDenominatorResolver,
)
from mmm_core.model_package_reader import ModelPackage  # noqa: E402


PACKAGE_ID = "pkg_807d3ddbae57a52a_9aacd3beb350725b"
PACKAGE_DIR = (
    REPO_DIR.parents[1]
    / "02_Predfin"
    / "MMM_platform"
    / "03_Outputs"
    / "01_PyMC_outputs"
    / "09_PyMC_14072026_panel_v3_serving_policy_v3"
    / "production_panel_v3_q1_2026_guarded_serving_v3"
)


class ForecastGeoAvailabilityPolicyTest(unittest.TestCase):
    def test_nearest_observation_boundary_is_seven_days_not_eight(self) -> None:
        rows = [
            {
                "segment": "S",
                "geo_label": "G",
                "date": "2025-01-01",
                "population_k": 1.0,
                "unique_users": 2.0,
                "orders_cnt": 3.0,
                "market_size_tier": "small",
            }
        ]
        resolver = HistoricalDenominatorResolver(pd.DataFrame(rows))
        resolver.resolve(
            "S",
            "G",
            date(2026, 1, 8),
            analog_year=2025,
            missing_geo_policy="nearest_available_year_same_geo",
        )
        with self.assertRaisesRegex(ValueError, "max_nearest_gap_days=7"):
            resolver.resolve(
                "S",
                "G",
                date(2026, 1, 9),
                analog_year=2025,
                missing_geo_policy="nearest_available_year_same_geo",
            )


@unittest.skipUnless(PACKAGE_DIR.exists(), "canonical preprod package is unavailable")
class CurrentPackageForecastGeoAvailabilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        package = ModelPackage.from_run_dir(
            PACKAGE_DIR,
            require_posterior_ready=False,
            validate_hash=False,
        )
        cls.resolver = ForecastGeoAvailabilityResolver.from_package(
            package,
            package_id=PACKAGE_ID,
        )

    def resolve(self, direction: str, start: date, end: date | None = None):
        channel = (
            "Нац_ТВ" if direction == "ТС5/Оффлайн" else "Digital_Performance"
        )
        return self.resolver.resolve(
            direction=direction,
            channel=channel,
            campaign_start=start,
            campaign_end=end or start,
            analog_year=2025,
            missing_geo_policy="nearest_available_year_same_geo",
        )

    def test_current_lmax_and_september_counts_are_pinned(self) -> None:
        expected = {
            "ТС5/Онлайн": (211, 175),
            "ТС5/Оффлайн": (220, 182),
            "ТСХ/Онлайн": (114, 103),
            "ТСХ/Оффлайн": (117, 104),
        }
        for direction, (declared, ready) in expected.items():
            with self.subTest(direction=direction):
                result = self.resolve(direction, date(2026, 9, 1))
                self.assertEqual(result.lmax, 14)
                self.assertEqual(result.required_start, "2026-09-01")
                self.assertEqual(result.required_end, "2026-09-15")
                self.assertEqual(len(result.declared_geos), declared)
                self.assertEqual(len(result.ready_geos), ready)
                self.assertEqual(len(result.unavailable_geos), declared - ready)

    def test_each_active_channel_uses_the_same_direction_period_universe(self) -> None:
        channels = {
            "ТС5/Онлайн": (
                "Digital_Performance", "OOH_Total", "Indoor", "Радио", "Нац_ТВ", "Рег_ТВ"
            ),
            "ТС5/Оффлайн": ("OOH_Total", "Indoor", "Радио", "Нац_ТВ", "Рег_ТВ"),
            "ТСХ/Онлайн": ("Digital_Performance", "OOH_Total", "Радио", "Рег_ТВ"),
            "ТСХ/Оффлайн": ("Digital_Performance", "OOH_Total", "Радио", "Нац_ТВ", "Рег_ТВ"),
        }
        expected_ready = {
            "ТС5/Онлайн": 175,
            "ТС5/Оффлайн": 182,
            "ТСХ/Онлайн": 103,
            "ТСХ/Оффлайн": 104,
        }
        for direction, direction_channels in channels.items():
            for channel in direction_channels:
                with self.subTest(direction=direction, channel=channel):
                    result = self.resolver.resolve(
                        direction=direction,
                        channel=channel,
                        campaign_start=date(2026, 9, 1),
                        campaign_end=date(2026, 9, 1),
                        analog_year=2025,
                        missing_geo_policy="nearest_available_year_same_geo",
                    )
                    self.assertEqual(len(result.ready_geos), expected_ready[direction])

    def test_another_period_has_a_different_ready_universe(self) -> None:
        expected = {
            "ТС5/Онлайн": 210,
            "ТС5/Оффлайн": 220,
            "ТСХ/Онлайн": 114,
            "ТСХ/Оффлайн": 117,
        }
        for direction, ready in expected.items():
            with self.subTest(direction=direction):
                self.assertEqual(
                    len(self.resolve(direction, date(2026, 1, 1)).ready_geos),
                    ready,
                )

    def test_moscow_is_ready_and_yakutsk_is_not_for_september(self) -> None:
        result = self.resolve("ТС5/Онлайн", date(2026, 9, 1))
        self.assertIn("МОСКВА", result.ready_geos)
        self.assertIn(
            "ЯКУТСК",
            {item.geo for item in result.unavailable_geos},
        )

    def test_multi_day_campaign_extends_required_horizon_by_lmax(self) -> None:
        result = self.resolve(
            "ТС5/Онлайн",
            date(2026, 9, 1),
            date(2026, 9, 3),
        )
        self.assertEqual(result.required_start, "2026-09-01")
        self.assertEqual(result.required_end, "2026-09-17")

    def test_internal_gap_over_seven_days_is_not_bridged(self) -> None:
        pass_result = self.resolve("ТС5/Онлайн", date(2026, 6, 18))
        fail_result = self.resolve("ТС5/Онлайн", date(2026, 7, 3))
        self.assertIn("ОЛЕНЕГОРСК", pass_result.ready_geos)
        self.assertIn(
            "ОЛЕНЕГОРСК",
            {item.geo for item in fail_result.unavailable_geos},
        )


if __name__ == "__main__":
    unittest.main()
