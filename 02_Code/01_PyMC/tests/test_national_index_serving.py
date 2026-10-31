"""Serving of assumption channels: the forecast and the optimizer must use the fit's exposure rule.

A fit with ``time_effect.mode = analytic_level`` replaces the lagged exposure of its assumption
channels (national TV and digital in the "Halloween" model) by the cross-city mean of the same
date.  These tests pin the serving side to that rule with an independent, loop-based
implementation of the training formula, on a synthetic mini package (no sampling, no NetCDF).
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mmm_core.forecast_engine import (  # noqa: E402
    EXPOSURE_BASIS_CITY,
    EXPOSURE_BASIS_NATIONAL_MEAN,
    ForecastEngine,
    _allocation_response_draws,
    _assumption_channels_from_transform,
    _beta_draw_vector,
    _build_turnover_response_kernels,
)

FIT_KEY = "S::turnover_per_user"
SEGMENT = "S"
GEOS = ["A", "B", "C", "D", "E"]
TIER_OF = {"A": "large", "B": "large", "C": "small", "D": "small", "E": "small"}
TIERS = ["large", "small"]
CHANNELS = ["Digital_Performance", "OOH_Total"]
L_MAX = 3
Y_SCALE = 2.5
N_DRAWS = 6
ANALOG_YEAR = 2025
X_SCALE = {  # (geo, channel) -> x_scale of the fit
    ("A", "Digital_Performance"): 3.0, ("B", "Digital_Performance"): 3.0,
    ("C", "Digital_Performance"): 2.0, ("D", "Digital_Performance"): 2.0, ("E", "Digital_Performance"): 2.0,
    ("A", "OOH_Total"): 5.0, ("B", "OOH_Total"): 5.0,
    ("C", "OOH_Total"): 4.0, ("D", "OOH_Total"): 4.0, ("E", "OOH_Total"): 4.0,
}


class _PackageStub:
    activation_status = "preprod_restricted"
    manifest: dict = {}


def _samples(beta_dims=("channel", "market_size_tier", "sample")) -> dict:
    rng = np.random.RandomState(7)
    alpha = rng.uniform(0.2, 0.8, size=(len(CHANNELS), N_DRAWS))
    lam = rng.uniform(0.6, 2.2, size=(len(CHANNELS), N_DRAWS))
    if beta_dims == ("channel", "market_size_tier", "sample"):
        beta = rng.uniform(0.05, 0.6, size=(len(CHANNELS), len(TIERS), N_DRAWS))
    elif beta_dims == ("channel", "geo_label", "sample"):
        beta = rng.uniform(0.05, 0.6, size=(len(CHANNELS), len(GEOS), N_DRAWS))
    else:
        beta = rng.uniform(0.05, 0.6, size=(len(CHANNELS), N_DRAWS))
    return {"alpha": alpha, "lam": lam, "beta": beta, "beta_dims": beta_dims, "sample_idx": np.arange(N_DRAWS)}


def _denominator_frame(skip_geo: str | None = None) -> pd.DataFrame:
    rows = []
    for day in pd.date_range("2025-01-01", "2025-12-31"):
        for index, geo in enumerate(GEOS):
            if geo == skip_geo:
                continue
            rows.append(
                {
                    "segment": SEGMENT,
                    "geo_label": geo,
                    "date": day.date().isoformat(),
                    "population_k": 100.0 * (index + 1) + 3.0 * (day.dayofyear % 5),
                    "unique_users": 1000.0 * (index + 1) * (1.0 + 0.02 * (day.dayofyear % 7)),
                    "orders_cnt": 700.0 * (index + 1),
                    "market_size_tier": TIER_OF[geo],
                }
            )
    return pd.DataFrame(rows)


def _warm_frame(as_of: str) -> pd.DataFrame:
    rows = []
    for g_index, geo in enumerate(GEOS):
        for c_index, channel in enumerate(CHANNELS):
            for lag in range(1, L_MAX + 1):
                rows.append(
                    {
                        "fit_key": FIT_KEY,
                        "geo_label": geo,
                        "channel": channel,
                        "as_of_date": as_of,
                        "lag": lag,
                        "scaled_spend": 0.05 * (g_index + 1) * (c_index + 1) / lag,
                    }
                )
    return pd.DataFrame(rows)


def _fit_meta(assumption: list[str] | None) -> dict:
    meta = {
        "segment": SEGMENT,
        "target": "turnover_per_user",
        "posterior_file": "unused.nc",
        "channels": list(CHANNELS),
        "spend_active": [f"spend_{name}" for name in CHANNELS],
        "geos": list(GEOS),
        "market_size_tiers": list(TIERS),
        "geo_to_tier": dict(TIER_OF),
        "l_max": L_MAX,
        "y_scale": Y_SCALE,
        "y_scaling": "p95abs",
        "y_offset": 0.0,
    }
    if assumption is not None:
        meta["assumption_channels"] = assumption
    return meta


def make_engine(
    *,
    assumption: list[str] | None = ("Digital_Performance",),
    as_of: str = "2026-02-27",
    beta_dims=("channel", "market_size_tier", "sample"),
    skip_geo: str | None = None,
    run_dir: Path | None = None,
) -> ForecastEngine:
    media_scales = pd.DataFrame(
        [
            {"fit_key": FIT_KEY, "geo_label": geo, "channel": channel, "market_size_tier": TIER_OF[geo], "x_scale": scale}
            for (geo, channel), scale in X_SCALE.items()
        ]
    )
    support = pd.DataFrame(
        [
            {
                "fit_key": FIT_KEY, "segment": SEGMENT, "target": "turnover_per_user", "channel": channel,
                "geo_label": geo, "daily_spend_p95_rub": 1e9, "daily_spend_p99_rub": 1e9,
                "daily_spend_max_rub": 1e9, "active_days": 365,
            }
            for geo in GEOS for channel in CHANNELS
        ]
    )
    capability = pd.DataFrame(
        [
            {"segment": SEGMENT, "target": "turnover_per_user", "channel": channel,
             "allowed_use": "primary", "optimizer_use": "optimize", "risk_level": "low"}
            for channel in CHANNELS
        ]
    )
    engine = ForecastEngine(
        run_dir=run_dir or Path("."),
        package=_PackageStub(),
        metadata={"fits": {FIT_KEY: _fit_meta(None if assumption is None else list(assumption))}},
        media_scales=media_scales,
        denominators=_denominator_frame(skip_geo),
        support_bounds=support,
        warm_start=_warm_frame(as_of),
        capability=capability,
    )
    samples = _samples(beta_dims)
    engine._posterior_samples = lambda fit_meta, n_samples, seed: samples  # type: ignore[method-assign]
    return engine


def plan_rows(start: date, budgets: dict[tuple[str, str], list[float]], campaign: str = "camp") -> list[dict]:
    rows = []
    for (geo, channel), daily in budgets.items():
        for offset, amount in enumerate(daily):
            rows.append(
                {
                    "campaign_name": campaign, "segment": SEGMENT, "geo": geo, "channel": channel,
                    "date": start + timedelta(days=offset), "budget_rub": float(amount),
                }
            )
    return rows


# ---- independent implementation of the training formula (explicit loops, no engine code) -------
def _user_matrix(engine: ForecastEngine, horizon: list[date]) -> np.ndarray:
    frame = engine.denominators.set_index(["geo_label", "date"])
    users = np.zeros((len(GEOS), len(horizon)))
    for g, geo in enumerate(GEOS):
        for t, day in enumerate(horizon):
            key = (geo, day.replace(year=ANALOG_YEAR).isoformat())
            users[g, t] = float(frame.loc[key, "unique_users"]) if key in frame.index else 0.0
    return users


def _exposure_matrix(engine: ForecastEngine, channel: str, budgets: dict, horizon: list[date]) -> np.ndarray:
    """Scaled per-resident exposure x[g, t] of the plan (zero for geographies without spend)."""
    frame = engine.denominators.set_index(["geo_label", "date"])
    x = np.zeros((len(GEOS), len(horizon)))
    for (geo, plan_channel), daily in budgets.items():
        if plan_channel != channel:
            continue
        g = GEOS.index(geo)
        for t, amount in enumerate(daily):
            day = horizon[t]
            population = float(frame.loc[(geo, day.replace(year=ANALOG_YEAR).isoformat()), "population_k"])
            x[g, t] = amount / population / X_SCALE[(geo, channel)]
    return x


def _warm_matrix(engine: ForecastEngine, channel: str, use_warm: bool) -> np.ndarray:
    warm = np.zeros((len(GEOS), L_MAX))
    if not use_warm:
        return warm
    frame = engine.warm_start
    for g, geo in enumerate(GEOS):
        sub = frame[(frame.geo_label == geo) & (frame.channel == channel)].sort_values("lag", ascending=False)
        warm[g] = sub["scaled_spend"].to_numpy(float)  # oldest .. newest
    return warm


def _betas(samples: dict, channel: str) -> np.ndarray:
    """beta[g, s] of one channel, read with plain loops."""
    ch = CHANNELS.index(channel)
    beta = samples["beta"]
    dims = samples["beta_dims"]
    out = np.zeros((len(GEOS), N_DRAWS))
    for g, geo in enumerate(GEOS):
        for s in range(N_DRAWS):
            if dims == ("channel", "market_size_tier", "sample"):
                out[g, s] = beta[ch, TIERS.index(TIER_OF[geo]), s]
            elif dims == ("channel", "geo_label", "sample"):
                out[g, s] = beta[ch, g, s]
            else:
                out[g, s] = beta[ch, s]
    return out


def training_formula_total(
    engine, samples, channel, budgets, horizon, use_warm, *, national_index, skip_users_of=(),
    keep_skipped_in_mean=False,
) -> np.ndarray:
    """Campaign effect per posterior draw as the fit would score it (mean index or city level).

    ``skip_users_of`` are the geographies without a usable denominator: they carry no users and, for
    the mean index, are left out of the mean (``keep_skipped_in_mean=True`` gives the previous rule that
    still divided by them; it is only used to show that the tests can fail).
    """
    ch = CHANNELS.index(channel)
    x = _exposure_matrix(engine, channel, budgets, horizon)
    warm = _warm_matrix(engine, channel, use_warm)
    users = _user_matrix(engine, horizon)
    for geo in skip_users_of:
        users[GEOS.index(geo)] = 0.0
    beta = _betas(samples, channel)
    n_geo, n_t = x.shape
    members = [g for g in range(n_geo) if keep_skipped_in_mean or GEOS[g] not in skip_users_of]
    totals = np.zeros(N_DRAWS)
    for s in range(N_DRAWS):
        alpha = samples["alpha"][ch, s]
        lam = samples["lam"][ch, s]
        w = alpha ** np.arange(L_MAX + 1)
        w = w / w.sum()
        extended = np.concatenate([warm, x], axis=1)
        extended0 = np.concatenate([warm, np.zeros_like(x)], axis=1)

        def lagged(series, g, t, k):
            return series[g, L_MAX + t - k]

        for t in range(n_t):
            if national_index:
                ads = sum(w[k] * np.mean([lagged(extended, g, t, k) for g in members]) for k in range(L_MAX + 1))
                ads0 = sum(w[k] * np.mean([lagged(extended0, g, t, k) for g in members]) for k in range(L_MAX + 1))
                sat = np.tanh(lam * ads / 2.0) - np.tanh(lam * ads0 / 2.0)
                totals[s] += Y_SCALE * sum(beta[g, s] * users[g, t] * sat for g in range(n_geo))
            else:
                for g in range(n_geo):
                    ads = sum(w[k] * lagged(extended, g, t, k) for k in range(L_MAX + 1))
                    ads0 = sum(w[k] * lagged(extended0, g, t, k) for k in range(L_MAX + 1))
                    sat = np.tanh(lam * ads / 2.0) - np.tanh(lam * ads0 / 2.0)
                    totals[s] += Y_SCALE * beta[g, s] * users[g, t] * sat
    return totals


def forecast_channel_totals(engine, rows, analog_year=ANALOG_YEAR) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return engine.forecast_daily_rows(
        rows, n_samples=N_DRAWS, seed=1, analog_year=analog_year, return_campaign_draws=True,
    )


class NationalIndexForecastTests(unittest.TestCase):
    BUDGETS = {
        ("A", "Digital_Performance"): [900.0, 1100.0, 0.0, 1300.0, 700.0],
        ("C", "Digital_Performance"): [250.0, 250.0, 400.0, 0.0, 300.0],
        ("B", "OOH_Total"): [500.0, 500.0, 500.0, 500.0, 500.0],
    }

    def _horizon(self, start: date) -> list[date]:
        return [start + timedelta(days=i) for i in range(5 + L_MAX)]

    def _run(self, start: date, as_of: str, **engine_kwargs):
        engine = make_engine(as_of=as_of, **engine_kwargs)
        detail, summary, draws = forecast_channel_totals(engine, plan_rows(start, self.BUDGETS))
        return engine, detail, summary, draws

    def _channel_total(self, detail: pd.DataFrame, channel: str) -> np.ndarray:
        sub = detail[detail["channel"].eq(channel)]
        return sum(np.asarray(value, dtype=float) for value in sub["_total_effect_draws"]) if "_total_effect_draws" in sub else None

    def _internal_totals(self, engine, rows, channel):
        # forecast_daily_rows drops the private draw columns; the campaign draw export sums every channel,
        # so compare channel by channel with plans that contain one channel only.
        only = [row for row in rows if row["channel"] == channel]
        _, _, draws = forecast_channel_totals(engine, only)
        return draws.sort_values("draw_index")["total_effect"].to_numpy(float)

    def test_digital_forecast_equals_training_formula_without_carryover(self):
        start = date(2026, 3, 10)  # more than l_max days after the last training day: no warm start
        engine, detail, _, _ = self._run(start, "2026-02-27")
        rows = plan_rows(start, self.BUDGETS)
        expected = training_formula_total(
            engine, engine._posterior_samples(None, 0, 0), "Digital_Performance", self.BUDGETS,
            self._horizon(start), use_warm=False, national_index=True,
        )
        actual = self._internal_totals(engine, rows, "Digital_Performance")
        np.testing.assert_allclose(actual, expected, rtol=1e-11, atol=1e-9)
        digital = detail[detail["channel"].eq("Digital_Performance")]
        self.assertTrue((digital["exposure_basis"] == EXPOSURE_BASIS_NATIONAL_MEAN).all())
        self.assertFalse(digital["warm_start_used"].any())

    def test_digital_forecast_equals_training_formula_with_carryover_from_training(self):
        start = date(2026, 2, 28)  # the day after the last training day: carryover of the training tail
        engine, detail, _, _ = self._run(start, "2026-02-27")
        rows = plan_rows(start, self.BUDGETS)
        expected = training_formula_total(
            engine, engine._posterior_samples(None, 0, 0), "Digital_Performance", self.BUDGETS,
            self._horizon(start), use_warm=True, national_index=True,
        )
        actual = self._internal_totals(engine, rows, "Digital_Performance")
        np.testing.assert_allclose(actual, expected, rtol=1e-11, atol=1e-9)
        self.assertTrue(detail[detail["channel"].eq("Digital_Performance")]["warm_start_used"].all())

    def test_city_level_channel_next_to_a_national_index_channel_is_unchanged(self):
        start = date(2026, 3, 10)
        engine, detail, _, _ = self._run(start, "2026-02-27")
        rows = plan_rows(start, self.BUDGETS)
        expected = training_formula_total(
            engine, engine._posterior_samples(None, 0, 0), "OOH_Total", self.BUDGETS,
            self._horizon(start), use_warm=False, national_index=False,
        )
        actual = self._internal_totals(engine, rows, "OOH_Total")
        np.testing.assert_allclose(actual, expected, rtol=1e-11, atol=1e-9)
        ooh = detail[detail["channel"].eq("OOH_Total")]
        self.assertTrue((ooh["exposure_basis"] == EXPOSURE_BASIS_CITY).all())

    def test_fit_without_assumption_channels_keeps_the_city_level_computation(self):
        """Model B and every older fit: digital stays city level, bit for bit the previous behaviour."""
        start = date(2026, 3, 10)
        engine = make_engine(assumption=[])
        detail, _, _ = forecast_channel_totals(engine, plan_rows(start, self.BUDGETS))
        expected = training_formula_total(
            engine, engine._posterior_samples(None, 0, 0), "Digital_Performance", self.BUDGETS,
            self._horizon(start), use_warm=False, national_index=False,
        )
        rows = plan_rows(start, self.BUDGETS)
        actual = self._internal_totals(engine, rows, "Digital_Performance")
        np.testing.assert_allclose(actual, expected, rtol=1e-11, atol=1e-9)
        self.assertTrue((detail["exposure_basis"] == EXPOSURE_BASIS_CITY).all())
        # the two rules really differ on this plan, so the tests above can fail
        mean_rule = training_formula_total(
            engine, engine._posterior_samples(None, 0, 0), "Digital_Performance", self.BUDGETS,
            self._horizon(start), use_warm=False, national_index=True,
        )
        self.assertGreater(float(np.max(np.abs(mean_rule / expected - 1.0))), 0.2)

    def test_geography_rows_share_the_channel_effect_in_proportion_to_spend(self):
        start = date(2026, 3, 10)
        engine, detail, _, _ = self._run(start, "2026-02-27")
        digital = detail[detail["channel"].eq("Digital_Performance")].set_index("geo")
        spend = digital["spend_rub"]
        share = spend / spend.sum()
        total_p50 = float(digital["total_effect_p50"].sum())
        # rows are scaled copies of one draw vector, so every row has the same ROAS
        roas = digital["roas_p50"].astype(float)
        self.assertLess(float(roas.max() - roas.min()), 1e-9 * max(float(roas.max()), 1.0))
        self.assertAlmostEqual(float(digital["total_effect_p50"].loc["A"]) / total_p50, float(share.loc["A"]), places=9)
        self.assertEqual(set(digital.index), {"A", "C"})

    def test_effect_reaches_geographies_without_spend_and_is_diluted_by_the_geographies_of_the_index(self):
        """Money in one city moves the national index by 1/N (N geographies in the index); the response reaches every city's users."""
        start = date(2026, 3, 10)
        budgets = {("A", "Digital_Performance"): [900.0, 1100.0, 0.0, 1300.0, 700.0]}
        engine = make_engine()
        samples = engine._posterior_samples(None, 0, 0)
        _, _, draws = forecast_channel_totals(engine, plan_rows(start, budgets))
        actual = draws.sort_values("draw_index")["total_effect"].to_numpy(float)
        horizon = self._horizon(start)
        expected = training_formula_total(
            engine, samples, "Digital_Performance", budgets, horizon, use_warm=False, national_index=True,
        )
        np.testing.assert_allclose(actual, expected, rtol=1e-11, atol=1e-9)
        # the city-level rule would book the whole response on city A's own users only
        city_level = training_formula_total(
            engine, samples, "Digital_Performance", budgets, horizon, use_warm=False, national_index=False,
        )
        self.assertFalse(np.allclose(actual, city_level, rtol=0.05))

    def test_geography_without_denominator_is_left_out_of_the_mean_and_carries_no_users(self):
        start = date(2026, 3, 10)
        engine = make_engine(skip_geo="E")
        budgets = {("A", "Digital_Performance"): [900.0, 1100.0, 0.0, 1300.0, 700.0]}
        detail, _, draws = forecast_channel_totals(engine, plan_rows(start, budgets))
        samples = engine._posterior_samples(None, 0, 0)
        expected = training_formula_total(
            engine, samples, "Digital_Performance", budgets,
            self._horizon(start), use_warm=False, national_index=True, skip_users_of=("E",),
        )
        actual = draws.sort_values("draw_index")["total_effect"].to_numpy(float)
        np.testing.assert_allclose(actual, expected, rtol=1e-11, atol=1e-9)
        self.assertEqual(int(detail["national_index_geos_without_denominator_n"].iloc[0]), 1)
        # the previous rule divided by the skipped geography too: the test must be able to tell them apart
        divided_by_all = training_formula_total(
            engine, samples, "Digital_Performance", budgets,
            self._horizon(start), use_warm=False, national_index=True, skip_users_of=("E",), keep_skipped_in_mean=True,
        )
        self.assertGreater(float(np.max(np.abs(divided_by_all / expected - 1.0))), 0.05)

    def test_geography_without_denominator_is_left_out_of_the_carryover_mean_too(self):
        start = date(2026, 2, 28)  # the day after the last training day: carryover of the training tail
        engine = make_engine(skip_geo="E", as_of="2026-02-27")
        budgets = {("A", "Digital_Performance"): [900.0, 1100.0, 0.0, 1300.0, 700.0]}
        detail, _, draws = forecast_channel_totals(engine, plan_rows(start, budgets))
        expected = training_formula_total(
            engine, engine._posterior_samples(None, 0, 0), "Digital_Performance", budgets,
            self._horizon(start), use_warm=True, national_index=True, skip_users_of=("E",),
        )
        np.testing.assert_allclose(draws.sort_values("draw_index")["total_effect"].to_numpy(float), expected, rtol=1e-11, atol=1e-9)
        self.assertTrue(detail["warm_start_used"].all())

    def test_nationwide_plan_gets_the_city_level_effect_whatever_the_number_of_skipped_geographies(self):
        """A plan with the same per-resident exposure in every geography the forecast can compute.

        This is the case of a federal row spread by population: the national index must stay at
        that exposure, so the effect equals the city-level effect of the same plan, and does not
        shrink with the number of fit geographies that have no denominator.
        """
        start = date(2026, 3, 10)
        engine = make_engine(skip_geo="E")
        frame = engine.denominators.set_index(["geo_label", "date"])
        level = 0.9  # scaled per-resident exposure, the same everywhere
        budgets = {}
        for geo in ("A", "B", "C", "D"):
            daily = []
            for offset in range(5):
                day = start + timedelta(days=offset)
                population = float(frame.loc[(geo, day.replace(year=ANALOG_YEAR).isoformat()), "population_k"])
                daily.append(level * population * X_SCALE[(geo, "Digital_Performance")])
            budgets[(geo, "Digital_Performance")] = daily
        samples = engine._posterior_samples(None, 0, 0)
        _, _, draws = forecast_channel_totals(engine, plan_rows(start, budgets))
        actual = draws.sort_values("draw_index")["total_effect"].to_numpy(float)
        horizon = self._horizon(start)
        city_level = training_formula_total(
            engine, samples, "Digital_Performance", budgets, horizon,
            use_warm=False, national_index=False, skip_users_of=("E",),
        )
        np.testing.assert_allclose(actual, city_level, rtol=1e-10, atol=1e-9)
        divided_by_all = training_formula_total(
            engine, samples, "Digital_Performance", budgets, horizon,
            use_warm=False, national_index=True, skip_users_of=("E",), keep_skipped_in_mean=True,
        )
        self.assertGreater(float(np.max(np.abs(divided_by_all / city_level - 1.0))), 0.08)

    def test_plan_row_in_a_geography_without_denominator_still_fails_closed(self):
        """Money in a city the forecast cannot compute is refused, never silently dropped from the index."""
        start = date(2026, 3, 10)
        engine = make_engine(skip_geo="E")
        budgets = {("E", "Digital_Performance"): [500.0] * 5, ("A", "Digital_Performance"): [900.0] * 5}
        with self.assertRaises(ValueError):
            forecast_channel_totals(engine, plan_rows(start, budgets))

    def test_every_beta_layout_gives_the_same_result_as_the_loop_formula(self):
        start = date(2026, 3, 10)
        for dims in [("channel", "market_size_tier", "sample"), ("channel", "geo_label", "sample"), ("channel", "sample")]:
            with self.subTest(beta_dims=dims):
                engine = make_engine(beta_dims=dims)
                _, _, draws = forecast_channel_totals(engine, plan_rows(start, {k: v for k, v in self.BUDGETS.items() if k[1] == "Digital_Performance"}))
                expected = training_formula_total(
                    engine, engine._posterior_samples(None, 0, 0), "Digital_Performance", self.BUDGETS,
                    self._horizon(start), use_warm=False, national_index=True,
                )
                np.testing.assert_allclose(draws.sort_values("draw_index")["total_effect"].to_numpy(float), expected, rtol=1e-11, atol=1e-9)

    def test_beta_draw_vector_matches_the_scalar_lookup(self):
        engine = make_engine()
        for dims in [("channel", "market_size_tier", "sample"), ("channel", "geo_label", "sample"), ("channel", "sample")]:
            samples = _samples(dims)
            for channel_idx in range(len(CHANNELS)):
                for geo_idx in range(len(GEOS)):
                    for tier_idx in range(len(TIERS)):
                        vector = _beta_draw_vector(samples["beta"], dims, channel_idx, geo_idx, tier_idx)
                        scalar = [engine._beta_value(samples["beta"], dims, s, channel_idx, geo_idx, tier_idx) for s in range(N_DRAWS)]
                        np.testing.assert_array_equal(vector, np.asarray(scalar))

    def test_assumption_channels_are_read_from_the_fit_transform_when_metadata_has_no_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            from mmm_core.forecast_engine import _safe_id

            transform = {
                "channels": list(CHANNELS), "spend_active": [f"spend_{name}" for name in CHANNELS],
                "time_effect": {"mode": "analytic_level", "assumption_channels": ["spend_Digital_Performance"]},
            }
            (root / f"fit_transform_{_safe_id(FIT_KEY)}.json").write_text(json.dumps(transform), encoding="utf-8")
            engine = make_engine(assumption=None, run_dir=root)
            self.assertEqual(engine.assumption_channels_for(FIT_KEY, engine.metadata["fits"][FIT_KEY]), frozenset({"Digital_Performance"}))
            # mode off or key absent: the fit never averaged anything
            transform["time_effect"] = {"mode": "off", "assumption_channels": ["spend_Digital_Performance"]}
            self.assertEqual(_assumption_channels_from_transform(transform, list(CHANNELS)), frozenset())
            self.assertEqual(_assumption_channels_from_transform({}, list(CHANNELS)), frozenset())
            self.assertEqual(_assumption_channels_from_transform(None, list(CHANNELS)), frozenset())


class NationalIndexOptimizerKernelTests(unittest.TestCase):
    START = date(2026, 3, 10)
    BUDGETS = {
        ("A", "Digital_Performance"): [900.0, 1100.0, 0.0, 1300.0, 700.0],
        ("C", "Digital_Performance"): [250.0, 250.0, 400.0, 100.0, 300.0],
        ("D", "Digital_Performance"): [100.0, 0.0, 100.0, 100.0, 100.0],
        ("B", "OOH_Total"): [500.0, 500.0, 500.0, 500.0, 500.0],
    }

    def _setup(self, factor: float = 1.0, as_of: str = "2026-02-27", skip_geo: str | None = None):
        engine = make_engine(as_of=as_of, skip_geo=skip_geo)
        rows = plan_rows(self.START, self.BUDGETS)
        plan = pd.DataFrame(rows)
        cells = (
            plan.groupby(["segment", "geo", "channel"], sort=False, as_index=False)["budget_rub"].sum()
        )
        kernels = _build_turnover_response_kernels(
            engine, plan, cells, "camp", n_samples=N_DRAWS, seed=1,
            analog_year=ANALOG_YEAR, analog_missing_geo_policy="fail",
        )
        allocation = cells["budget_rub"].to_numpy(float) * factor
        scaled_rows = plan_rows(self.START, {k: [value * factor for value in v] for k, v in self.BUDGETS.items()})
        return engine, kernels, allocation, scaled_rows

    def test_kernels_reproduce_the_exact_forecast_at_the_plan_proportions(self):
        for factor in (1.0, 0.4, 1.7):
            with self.subTest(factor=factor):
                engine, kernels, allocation, rows = self._setup(factor)
                kernel_total, _ = _allocation_response_draws(kernels, allocation)
                _, _, draws = engine.forecast_daily_rows(
                    rows, n_samples=N_DRAWS, seed=1, analog_year=ANALOG_YEAR, return_campaign_draws=True,
                )
                exact = draws.sort_values("draw_index")["total_effect"].to_numpy(float)
                np.testing.assert_allclose(kernel_total, exact, rtol=1e-11, atol=1e-9)

    def test_kernels_reproduce_the_exact_forecast_with_carryover(self):
        engine, kernels, allocation, rows = self._setup(1.0, as_of="2026-03-09")
        kernel_total, _ = _allocation_response_draws(kernels, allocation)
        _, _, draws = engine.forecast_daily_rows(rows, n_samples=N_DRAWS, seed=1, analog_year=ANALOG_YEAR, return_campaign_draws=True)
        np.testing.assert_allclose(kernel_total, draws.sort_values("draw_index")["total_effect"].to_numpy(float), rtol=1e-11, atol=1e-9)

    def test_kernels_reproduce_the_exact_forecast_when_a_fit_geography_has_no_denominator(self):
        for as_of in ("2026-02-27", "2026-03-09"):
            with self.subTest(as_of=as_of):
                engine, kernels, allocation, rows = self._setup(1.3, as_of=as_of, skip_geo="E")
                kernel_total, _ = _allocation_response_draws(kernels, allocation)
                _, _, draws = engine.forecast_daily_rows(
                    rows, n_samples=N_DRAWS, seed=1, analog_year=ANALOG_YEAR, return_campaign_draws=True,
                )
                exact = draws.sort_values("draw_index")["total_effect"].to_numpy(float)
                np.testing.assert_allclose(kernel_total, exact, rtol=1e-11, atol=1e-9)

    def test_moving_money_between_cities_inside_a_national_channel_is_not_rewarded_by_the_search(self):
        _, kernels, allocation, _ = self._setup()
        base_total, _ = _allocation_response_draws(kernels, allocation)
        cells_digital = [i for i, k in enumerate(kernels) if k.channel == "Digital_Performance"]
        moved = allocation.copy()
        shift = 0.5 * moved[cells_digital[0]]
        moved[cells_digital[0]] -= shift
        moved[cells_digital[-1]] += shift
        moved_total, _ = _allocation_response_draws(kernels, moved)
        self.assertTrue((moved_total <= base_total + 1e-9).all())

    def test_city_level_cells_keep_a_unit_share_and_national_cells_share_the_channel(self):
        _, kernels, allocation, _ = self._setup()
        digital = [k for k in kernels if k.channel == "Digital_Performance"]
        ooh = [k for k in kernels if k.channel == "OOH_Total"]
        self.assertTrue(all(k.share == 1.0 for k in ooh))
        self.assertAlmostEqual(sum(k.share for k in digital), 1.0, places=12)
        self.assertEqual(len({id(k.effect_multiplier) for k in digital}), 1)


if __name__ == "__main__":
    unittest.main()
