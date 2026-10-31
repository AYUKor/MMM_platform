"""The serving replay must reproduce the ROAS the REAL fit code publishes (national-index parity gate).

The fixture runs the real data preparation of ``fit.py`` (including the cross-city averaging of the
assumption channels) on a synthetic panel and computes the ROAS table the way the fit does
(``compute_revenue_roas``, 200 draws of ``RandomState(42)``).  The serving geo loop and the
independent reference producer then replay the same draws from the frozen artifacts.  Needs the fit
stack (pymc, arviz, xarray); it is skipped where those are not installed.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent))
sys.path.insert(0, str(TESTS_DIR))

try:
    import arviz as az
    import xarray as xr
    from mmm_core import fit
    from mmm_core import validation as val
    from mmm_core.forecast_engine import ForecastEngine, build_historical_forecast_replay_rows
    import test_time_effect_v4k as v4k
    from test_time_effect_v4k import TIME_EFFECT, build
except Exception as exc:  # pragma: no cover - the fit stack is optional for this module
    raise unittest.SkipTest(f"fit stack is not installed: {exc!r}")

FIT_KEY = "ТСХ/Онлайн::turnover_per_user"
SEGMENT = "ТСХ/Онлайн"
N_CHAIN, N_DRAW = 2, 8


class _PackageStub:
    activation_status = "preprod_restricted"
    manifest: dict = {}


def _canonical(payload: dict) -> dict:
    return json.loads(json.dumps(payload, ensure_ascii=False, default=float))


class RealFitParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        original_panel = v4k.synthetic_panel

        def heterogeneous_panel(*args, **kwargs):
            """A big city gets a lot of digital money per resident, the others little (as in the real ledger)."""
            frame = original_panel(*args, **kwargs)
            weight = {"G0": 12.0, "G1": 3.0}
            frame["spend_Радио"] = frame["spend_Радио"] * frame["geo_label"].map(lambda geo: weight.get(geo, 0.2))
            return frame

        with mock.patch.object(v4k, "synthetic_panel", heterogeneous_panel):
            seg, coords, data, _ = build(TIME_EFFECT)
        cls.data = data
        cls.safe = fit._safe_fit_key(FIT_KEY)
        cls.channels = [column.removeprefix("spend_") for column in data["spend_active"]]
        m = len(cls.channels)

        # Posterior with spread in every parameter, beta pooled per channel (as in the V4k fits).
        rng = np.random.default_rng(11)
        ds = xr.Dataset(
            {
                "alpha": (("chain", "draw", "channel"), rng.uniform(0.3, 0.7, (N_CHAIN, N_DRAW, m))),
                "lam": (("chain", "draw", "channel"), rng.uniform(0.8, 2.0, (N_CHAIN, N_DRAW, m))),
                "beta": (("chain", "draw", "channel"), rng.uniform(0.02, 0.2, (N_CHAIN, N_DRAW, m))),
            },
            coords={"chain": np.arange(N_CHAIN), "draw": np.arange(N_DRAW), "channel": cls.channels},
        )
        cls.idata = az.InferenceData(posterior=ds)
        cls.idata.to_netcdf(cls.root / f"posterior_{cls.safe}.nc")

        # What the fit publishes: the ROAS table, from the real training code path.
        cls.training_roas = fit.compute_revenue_roas(cls.idata, data, seg, n_samples=200)
        table_rows = []
        for index, channel in enumerate(cls.channels):
            table_rows.append(
                {
                    "segment": SEGMENT, "target": "turnover_per_user", "channel": channel,
                    "roas_rub_p5": float(np.percentile(cls.training_roas[index], 5)),
                    "roas_rub_median": float(np.percentile(cls.training_roas[index], 50)),
                    "roas_rub_p95": float(np.percentile(cls.training_roas[index], 95)),
                }
            )
        cls.table = pd.DataFrame(table_rows)
        cls.table.to_csv(cls.root / "roas_rub_all_fits.csv", index=False)

        # Frozen artifacts as the fit writes them.
        transform = {
            "schema_version": "1.0.0", "fit_key": FIT_KEY, "channels": cls.channels,
            "spend_active": list(data["spend_active"]), "controls": list(data["ctrl_active"]),
            "geos": list(data["geos"]), "market_size_tiers": list(data["market_size_tiers"]),
            "geo_tier_idx": np.asarray(data["geo_tier_idx"], int).tolist(),
            "x_scale_geo": np.asarray(data["x_scale_geo"], float).tolist(),
            "y_scale": float(data["y_scale"]), "y_offset": float(data["y_offset"]),
            "y_scaling": data["y_scaling"], "l_max": int(data["l_max"]),
            # build() switches the fit globals off again, so name the mode the fit wrote while it was on
            "time_effect": {**fit._time_effect_block(data), "mode": "analytic_level"},
        }
        cls.transform = _canonical(transform)
        cls._write_transform(cls.transform)
        (cls.root / "run_config.json").write_text(
            json.dumps({"train_start": str(seg["date"].min().date()), "train_end": str(seg["date"].max().date()),
                        "cfg": {"l_max": int(data["l_max"])}, "expected_fit_keys": [FIT_KEY]}),
            encoding="utf-8",
        )

        panel = seg.copy()
        panel["orders_cnt"] = panel["unique_users"] * 1.2
        cls.panel = panel
        cls.row_index = panel[["date", "geo_label", "network", "channel"]].assign(
            fit_key=FIT_KEY, row_position=np.arange(len(panel))
        )
        geo_tier = {geo: data["market_size_tiers"][int(tier)] for geo, tier in zip(data["geos"], data["geo_tier_idx"])}
        cls.geo_tier = geo_tier

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    @classmethod
    def _write_transform(cls, transform: dict) -> None:
        payload = dict(transform)
        payload.pop("transform_sha256", None)
        payload["transform_sha256"] = val._canonical_hash(payload)
        (cls.root / f"fit_transform_{cls.safe}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _engine(self, assumption: list[str] | None) -> ForecastEngine:
        data = self.data
        media_scales = pd.DataFrame(
            [
                {"fit_key": FIT_KEY, "geo_label": geo, "channel": channel,
                 "market_size_tier": self.geo_tier[geo], "x_scale": float(data["x_scale_geo"][g][m])}
                for g, geo in enumerate(data["geos"]) for m, channel in enumerate(self.channels)
            ]
        )
        meta = {
            "segment": SEGMENT, "target": "turnover_per_user", "posterior_file": f"posterior_{self.safe}.nc",
            "channels": list(self.channels), "geos": list(data["geos"]), "l_max": int(data["l_max"]),
        }
        if assumption is not None:
            meta["assumption_channels"] = assumption
        denominators = pd.DataFrame(
            columns=["segment", "geo_label", "date", "population_k", "unique_users", "orders_cnt", "market_size_tier"]
        )
        return ForecastEngine(
            run_dir=self.root, package=_PackageStub(), metadata={"fits": {FIT_KEY: meta}},
            media_scales=media_scales, denominators=denominators, support_bounds=pd.DataFrame(),
            warm_start=pd.DataFrame(), capability=pd.DataFrame(),
        )

    def _replayed_roas(self, engine: ForecastEngine) -> dict[str, np.ndarray]:
        pairs = val.roas_table_draw_pairs(self.root, FIT_KEY)
        rows = build_historical_forecast_replay_rows(engine, self.panel, self.row_index, pairs, fit_keys=[FIT_KEY])
        out = {}
        for channel, sub in rows.groupby("channel", sort=False):
            out[str(channel)] = sub["effect_value"].to_numpy(float) / float(sub["spend_rub"].iloc[0])
        return out

    def test_serving_replay_reproduces_the_real_training_roas_draw_by_draw(self):
        replayed = self._replayed_roas(self._engine(["Радио"]))
        for index, channel in enumerate(self.channels):
            with self.subTest(channel=channel):
                np.testing.assert_allclose(replayed[channel], self.training_roas[index], rtol=1e-9, atol=1e-12)

    def test_the_averaged_channel_really_differs_from_the_city_level_rule(self):
        """Guards the guard: the cross-city mean changes the ROAS of the averaged channel, not of the other."""
        transform = json.loads(json.dumps(self.transform))
        transform["time_effect"]["assumption_channels"] = []
        self._write_transform(transform)
        try:
            city_level = self._replayed_roas(self._engine([]))
        finally:
            self._write_transform(self.transform)
        index = self.channels.index("Радио")
        other = self.channels.index("Рег_ТВ")
        self.assertGreater(float(np.max(np.abs(city_level["Радио"] / self.training_roas[index] - 1.0))), 0.10)
        np.testing.assert_allclose(city_level["Рег_ТВ"], self.training_roas[other], rtol=1e-9, atol=1e-12)

    def test_reference_producer_and_serving_replay_agree_with_each_other(self):
        engine = self._engine(["Радио"])
        pairs = val.roas_table_draw_pairs(self.root, FIT_KEY)
        reference = val.build_model_side_historical_replay_rows(self.root, self.panel, self.row_index, [FIT_KEY], pairs)
        served = build_historical_forecast_replay_rows(engine, self.panel, self.row_index, pairs)
        verdict = val.evaluate_historical_response_replay(
            reference, served, expected_fits=1, expected_effects=len(self.channels), expected_draws=len(pairs),
        )
        self.assertEqual(verdict["status"], "passed", verdict)

    def test_parity_gate_passes_when_serving_follows_the_fit(self):
        report = val.run_serving_roas_parity(self.root, self.panel, self.row_index, self._engine(["Радио"]), [FIT_KEY])
        self.assertEqual(report["status"], "passed", report)
        self.assertEqual(report["compared_n"], len(self.channels))
        self.assertLess(report["max_abs_rel_diff_median"], 1e-9)
        basis = {row["channel"]: row["exposure_basis"] for row in report["rows"]}
        self.assertEqual(basis, {"Радио": "national_mean_index", "Рег_ТВ": "city_level"})

    def test_parity_gate_fails_when_the_serving_side_ignores_the_fit_averaging(self):
        """The old blind spot: serving on city-level exposure while the fit averaged the channel."""
        transform = json.loads(json.dumps(self.transform))
        transform["time_effect"]["assumption_channels"] = []
        self._write_transform(transform)
        try:
            report = val.run_serving_roas_parity(self.root, self.panel, self.row_index, self._engine([]), [FIT_KEY])
        finally:
            self._write_transform(self.transform)
        self.assertEqual(report["status"], "failed")
        failed = [row for row in report["rows"] if not row["ok"]]
        self.assertEqual({row["channel"] for row in failed}, {"Радио"})

    def test_parity_gate_fails_when_serving_classifies_channels_differently_from_the_fit(self):
        report = val.run_serving_roas_parity(self.root, self.panel, self.row_index, self._engine([]), [FIT_KEY])
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["classification_mismatch"][0]["fit_averaged"], ["Радио"])
        self.assertEqual(report["classification_mismatch"][0]["serving_averages"], [])

    def test_parity_gate_fails_when_the_published_table_disagrees(self):
        broken = self.table.copy()
        broken.loc[broken["channel"].eq("Рег_ТВ"), ["roas_rub_p5", "roas_rub_median", "roas_rub_p95"]] *= 1.5
        broken.to_csv(self.root / "roas_rub_all_fits.csv", index=False)
        try:
            report = val.run_serving_roas_parity(self.root, self.panel, self.row_index, self._engine(["Радио"]), [FIT_KEY])
        finally:
            self.table.to_csv(self.root / "roas_rub_all_fits.csv", index=False)
        self.assertEqual(report["status"], "failed")
        self.assertEqual({row["channel"] for row in report["rows"] if not row["ok"]}, {"Рег_ТВ"})

    def test_parity_gate_fails_closed_without_a_published_table(self):
        path = self.root / "roas_rub_all_fits.csv"
        saved = path.read_bytes()
        path.unlink()
        try:
            report = val.run_serving_roas_parity(self.root, self.panel, self.row_index, self._engine(["Радио"]), [FIT_KEY])
        finally:
            path.write_bytes(saved)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["reason"], "ROAS_TABLE_MISSING")

    def test_engine_reads_the_assumption_channels_from_the_frozen_transform_of_an_older_export(self):
        engine = self._engine(None)  # metadata exported before this rule carries no assumption_channels key
        self.assertEqual(engine.assumption_channels_for(FIT_KEY, engine.metadata["fits"][FIT_KEY]), frozenset({"Радио"}))


if __name__ == "__main__":
    unittest.main()
