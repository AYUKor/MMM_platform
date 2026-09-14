"""An unavailable automatic scenario must not discard the other campaign results.

The real orchestration, support bounds, candidate generators, risk checks and
artifact writers run here. Only package loading and expensive posterior scoring
are replaced with a tiny in-memory package and deterministic synthetic draws.
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd

PYMC_CODE_DIR = Path(__file__).resolve().parents[1]
if str(PYMC_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(PYMC_CODE_DIR))

from mmm_core import forecast_engine as forecast  # noqa: E402


class InfeasibleScenarioOrchestrationTests(unittest.TestCase):
    def _fixture(self, root: Path, *, allow_optimization: bool) -> tuple[forecast.ForecastEngine, Path]:
        """Two editable cells plus one diagnostic TV cell with zero support."""
        target = "turnover_per_user"
        plan = pd.DataFrame([
            {"campaign_name": "TCX", "segment": "S", "geo": geo,
             "channel": channel, "date": "2026-08-25", "budget_rub": budget}
            for geo, channel, budget in [
                ("City", "Digital", 100.0),
                ("Region", "Digital", 100.0),
                ("Region", "TV", 250.0),
            ]
        ])
        flighting = root / "daily.csv"
        plan.to_csv(flighting, index=False)
        (root / "model_manifest.json").write_text("{}", encoding="utf-8")
        support = pd.DataFrame([
            {"fit_key": f"S::{target}", "segment": "S", "target": target,
             "geo_label": row.geo, "channel": row.channel,
             "daily_spend_p95_rub": 100.0 if row.channel == "Digital" else 0.0,
             "daily_spend_p99_rub": 100.0 if row.channel == "Digital" else 0.0,
             "daily_spend_max_rub": 100.0 if row.channel == "Digital" else 0.0,
             "active_days": 100}
            for row in plan.itertuples()
        ])
        capability = pd.DataFrame([
            {"segment": "S", "target": target, "channel": "Digital",
             "allowed_use": "primary" if allow_optimization else "caution",
             "optimizer_use": "optimize" if allow_optimization else "no_increase"},
            {"segment": "S", "target": target, "channel": "TV",
             "allowed_use": "diagnostic", "optimizer_use": "fixed_at_plan"},
        ])
        denominators = pd.DataFrame([
            {"segment": "S", "geo_label": geo, "date": "2026-08-25",
             "population_k": 1.0, "unique_users": 1.0, "orders_cnt": 1.0,
             "market_size_tier": "small"}
            for geo in ("City", "Region")
        ])
        engine = forecast.ForecastEngine(
            run_dir=root,
            package=SimpleNamespace(activation_status="preprod_restricted", manifest={}),
            metadata={"fits": {f"S::{target}": {"segment": "S", "target": target}}},
            media_scales=pd.DataFrame(), denominators=denominators,
            support_bounds=support, warm_start=pd.DataFrame(), capability=capability,
        )
        return engine, flighting

    @staticmethod
    def _synthetic_scoring(engine: forecast.ForecastEngine, daily_rows: list[dict], **kwargs):
        """Return deterministic draws; keep real aggregation and support warnings."""
        rows = []
        grouped = pd.DataFrame(daily_rows).groupby(
            ["campaign_name", "segment", "geo", "channel"], sort=False,
        )
        for (campaign, segment, geo, channel), daily in grouped:
            spend = float(daily["budget_rub"].sum())
            capability = engine._capability_row(segment, "turnover_per_user", channel)
            support = engine._support_assessment(
                f"{segment}::turnover_per_user", geo, channel,
                daily["budget_rub"].to_numpy(dtype=float),
            )
            draws = spend * np.linspace(0.008, 0.012, kwargs["n_samples"])
            rows.append({
                "campaign_name": campaign, "segment": segment, "geo": geo,
                "channel": channel, "target": "turnover_per_user",
                "spend_rub": spend, "effect_unit": "rub_per_user",
                "total_effect_unit": "rub", "allowed_use": capability["allowed_use"],
                "optimizer_use": capability["optimizer_use"], "risk_level": "low",
                "support_flags": support.flags_text, "support_level": support.level,
                "_total_effect_draws": draws, "_effect_unit_draws": draws,
                "_effect_unit_weight": 1.0,
            })
        detail = pd.DataFrame(rows)
        summary = forecast.summarize_forecast_detail(detail)
        public = detail.drop(columns=["_total_effect_draws", "_effect_unit_draws", "_effect_unit_weight"])
        if kwargs.get("return_campaign_draws"):
            return public, summary, forecast._campaign_total_draw_rows(detail)
        return public, summary

    def _run(self, *, allow_optimization: bool, scenario6_enabled: bool):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine, flighting = self._fixture(root, allow_optimization=allow_optimization)
            original_support = engine.support_bounds.copy(deep=True)
            original_capability = engine.capability.copy(deep=True)
            with (
                patch.object(forecast.ForecastEngine, "from_run_dir", return_value=engine),
                patch.object(engine, "forecast_daily_rows", side_effect=lambda rows, **kw: self._synthetic_scoring(engine, rows, **kw)) as scoring,
                patch.object(forecast, "_runtime_lineage", return_value={"fixture": "synthetic"}),
                patch.object(forecast, "_build_turnover_response_kernels", side_effect=AssertionError("Infeasible S6 must stop before posterior kernels")) as kernels,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                card = forecast.run_optimizer_from_flighting(
                    root, flighting, root / "outputs", "fixed_support",
                    search_candidates=8, search_samples=4, final_samples=4, finalists=1,
                    workflow_config={"optimizer": {"scenario_6": {"enabled": scenario6_enabled}}},
                )
            self.assertEqual(scoring.call_count, 2)
            self.assertEqual(
                [call.kwargs["progress_context"] for call in scoring.call_args_list],
                ["optimizer_search", "optimizer_finalists"],
            )
            kernels.assert_not_called()
            pd.testing.assert_frame_equal(original_support, engine.support_bounds)
            pd.testing.assert_frame_equal(original_capability, engine.capability)
            self.assertTrue(Path(card["outputs"]["xlsx"]).is_file())
            scores = pd.read_csv(card["outputs"]["candidate_scores_csv"])
            finalists = pd.read_csv(card["outputs"]["finalist_summary_csv"])
            allocations = pd.read_csv(card["outputs"]["recommended_allocations_csv"])
            final_names = finalists["candidate_name"].unique()
            self.assertEqual(len(final_names), 5)
            for scenario in range(1, 6):
                self.assertTrue(any(f"__scenario{scenario}_" in name for name in final_names))
            self.assertFalse(any("__scenario6_" in name for name in final_names))
            source = allocations[allocations["candidate_name"].str.contains("__scenario1_")]
            partial = allocations[allocations["candidate_name"].str.contains("__scenario5_")]
            self.assertEqual(float(source["budget_rub"].sum()), 450.0)
            self.assertEqual(float(source.loc[source["channel"].eq("TV"), "budget_rub"].sum()), 250.0)
            self.assertEqual(set(partial["scenario_variant"]), {"safe_partial"})
            self.assertEqual(float(partial.loc[partial["channel"].eq("TV"), "budget_rub"].sum()), 0.0)
            self.assertEqual(set(partial["unallocated_budget_rub"]), {250.0})
            return scores[scores["candidate_name"].str.contains("__scenario6_")]

    def test_no_increase_and_fixed_over_cap_preserves_five_scenarios(self):
        status = self._run(allow_optimization=False, scenario6_enabled=True)
        self.assertEqual(len(status), 1)
        self.assertEqual(status.iloc[0]["precheck_status"], "not_run_no_modifiable_cells")
        self.assertEqual(int(status.iloc[0]["modifiable_cells_n"]), 2)

    def test_optimizable_campaign_records_infeasible_six_without_losing_results(self):
        status = self._run(allow_optimization=True, scenario6_enabled=True)
        self.assertEqual(len(status), 1)
        self.assertEqual(status.iloc[0]["precheck_status"], "rejected_infeasible")
        self.assertIn("fixed-at-plan", status.iloc[0]["precheck_reason"])
        self.assertIn("approved risk limits", status.iloc[0]["precheck_reason"])

    def test_disabled_six_does_not_validate_an_unrequested_full_allocation(self):
        status = self._run(allow_optimization=True, scenario6_enabled=False)
        self.assertTrue(status.empty)


if __name__ == "__main__":
    unittest.main()
