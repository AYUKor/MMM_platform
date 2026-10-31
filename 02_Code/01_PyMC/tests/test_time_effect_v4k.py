"""Tests of the time_effect (v4k) switches of fit.py: analytic city-level likelihood, switches-off identity, contract block, post-processing, adequacy.

The switches-off identity test compares the model of this fit.py with the previous fit.py in a separate process; set MMM_REFERENCE_FIT_DIR to the 01_PyMC directory of the
previous code (e.g. the code of B) to run it, otherwise it is skipped.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

PYMC_CODE_DIR = Path(__file__).resolve().parents[1]
if str(PYMC_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(PYMC_CODE_DIR))

import pytensor  # noqa: E402
import pytensor.tensor as pt  # noqa: E402
from mmm_core import fit  # noqa: E402

GEOS = [f"G{i}" for i in range(8)]


def synthetic_panel(seed: int = 3, days: int = 140) -> pd.DataFrame:
    """Small TSX/Online panel: two media channels, a control with cross-city variation and a time-only control."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2025-01-01", periods=days, freq="D")
    rows = []
    for gi, geo in enumerate(GEOS):
        level = 1500.0 + 40 * gi
        drift = np.cumsum(rng.normal(0, 3.0, days))
        for di, date in enumerate(dates):
            rows.append({
                "date": date, "geo_label": geo, "network": "ТСХ", "channel": "Онлайн", "population_k": 100.0 + gi * 20,
                "market_size_tier": ["small", "medium", "large"][gi % 3], "anomaly_period_jul2025": 0,
                "unique_users": 5000 + 100 * gi + rng.integers(0, 50),
                "turnover_per_user": level + drift[di] + 15 * np.sin(di / 9.0) + rng.normal(0, 12),
                "orders_per_user": 1.1 + di / 1000, "avg_basket": 1400.0 + di,
                "spend_Радио": float(max(0.0, 100 + 30 * np.sin(di / 20.0 + gi) + rng.normal(0, 20))),
                "spend_Рег_ТВ": float(rng.choice([0.0, 0.0, 300.0, 500.0]) * (gi % 2)),
                "temp_dev": float(rng.normal(0, 1) + 0.1 * gi),      # varies across cities inside a date
                "cos_w": float(np.cos(2 * np.pi * di / 7.0)),          # a function of the date alone
            })
    return pd.DataFrame(rows)


PRIORS = {"ТСХ/Онлайн": {"turnover_per_user": {
    "spend_Радио": {"decay": 0.5, "beta_FE": 0.01, "beta_SE": 0.001},
    "spend_Рег_ТВ": {"decay": 0.65, "beta_FE": 0.01, "beta_SE": 0.001}}}}
TIME_EFFECT = {
    "mode": "analytic_level", "eta_sd_prior": 0.02, "level_sd0": 1.0, "no_rounding_priors": True,
    "roas_priors": {"targets": ["turnover_per_user"], "default": [1.2, 0.28, 5.4], "by_channel": {"Радио": [1.0, 0.2, 4.0]}},
    "assumption_channels": ["Радио"], "alpha_prior": {"Рег_ТВ": {"mean": 0.65, "concentration": 2.5}},
}


def build(time_effect: dict | None, mode: str = "tight", fixed_lambda: tuple = ()):
    spec = type("S", (), {})()
    spec.time_effect = fit._parse_time_effect_config(time_effect)
    spec.mode = mode
    frame = synthetic_panel()
    old = (fit.MEDIA_GROUPING_ENABLED, getattr(fit, "panel", None), fit.SPEND_ACTIVE_BASE, fit.TC5_OFFLINE_SPECIFIC_POLICY_ENABLED)
    try:
        fit._configure_runtime_globals(spec)
        fit.MEDIA_GROUPING_ENABLED = False; fit.panel = frame; fit.SPEND_ACTIVE_BASE = ["spend_Радио", "spend_Рег_ТВ"]; fit.TC5_OFFLINE_SPECIFIC_POLICY_ENABLED = False
        seg, coords, data = fit.build_single_target_data(frame, "ТСХ", "Онлайн", "turnover_per_user", ["spend_Радио", "spend_Рег_ТВ"], ["temp_dev", "cos_w"], PRIORS, 14)
        if fixed_lambda:    # the stock bookkeeping of config key fixed_lambda_channels_by_fit (fit._prepare_one_fit)
            names_ = [c.removeprefix("spend_") for c in data["spend_active"]]
            data["fixed_lambda_channels"] = list(fixed_lambda)
            data["fixed_lambda_channel_idx"] = np.asarray([i for i, n in enumerate(names_) if n in fixed_lambda], dtype=int)
            data["free_lambda_channel_idx"] = np.asarray([i for i, n in enumerate(names_) if n not in fixed_lambda], dtype=int)
            coords["lambda_free_channel"] = [names_[i] for i in data["free_lambda_channel_idx"]]
        model = fit.build_pymc_model(coords, data)
    finally:
        fit.MEDIA_GROUPING_ENABLED, fit.panel, fit.SPEND_ACTIVE_BASE, fit.TC5_OFFLINE_SPECIFIC_POLICY_ENABLED = old
        fit._configure_runtime_globals(type("S", (), {"time_effect": None, "mode": "tight"})())
    return seg, coords, data, model


def brute_marginal(r, geo, wk, G, W, sig_g, sigma_eta, s0):
    ll = 0.0
    idx = np.arange(W)
    C = s0 ** 2 + sigma_eta ** 2 * np.minimum(idx[:, None], idx[None, :])
    for g in range(G):
        rows = np.where(geo == g)[0]
        if len(rows) == 0:
            continue
        A = np.zeros((len(rows), W)); A[np.arange(len(rows)), wk[rows]] = 1.0
        S = A @ C @ A.T + sig_g[g] ** 2 * np.eye(len(rows))
        _, logdet = np.linalg.slogdet(S)
        ll += -0.5 * (r[rows] @ np.linalg.solve(S, r[rows])) - 0.5 * logdet - 0.5 * len(rows) * np.log(2 * np.pi)
    return ll


class AnalyticCityLevelTests(unittest.TestCase):
    def test_loglik_matches_brute_force_and_gradients(self) -> None:
        rng = np.random.default_rng(7)
        for G, W, nmax in [(3, 5, 3), (5, 9, 2), (4, 12, 4)]:
            geo, wk = [], []
            for g in range(G):
                for w in range(W):
                    if rng.random() < 0.15:
                        continue
                    for _ in range(rng.integers(1, nmax + 1)):
                        geo.append(g); wk.append(w)
            geo, wk = np.array(geo), np.array(wk)
            r = rng.normal(0, 0.1, len(geo)); sig_g = rng.uniform(0.05, 0.2, G); eta, s0 = 0.03, 1.0
            ref = brute_marginal(r, geo, wk, G, W, sig_g, eta, s0)
            for solver in ("scan", "chol"):
                rv, sv, ev = pt.dvector("r"), pt.dvector("s"), pt.dscalar("e")
                ll = fit.city_level_loglik(rv, geo, wk, G, W, sv, ev, s0, solver=solver)
                f = pytensor.function([rv, sv, ev], [ll, pt.grad(ll, ev), pt.grad(ll, sv)])
                val, g_e, g_s = f(r, sig_g, eta)
                h = 1e-6
                fd_e = (brute_marginal(r, geo, wk, G, W, sig_g, eta + h, s0) - brute_marginal(r, geo, wk, G, W, sig_g, eta - h, s0)) / (2 * h)
                self.assertAlmostEqual(float(val), ref, delta=1e-8 * max(1.0, abs(ref)))
                self.assertLess(abs(float(g_e) - fd_e) / max(abs(fd_e), 1.0), 1e-4)


class SwitchesTests(unittest.TestCase):
    def test_config_parsing(self) -> None:
        self.assertIsNone(fit._parse_time_effect_config(None))
        self.assertIsNone(fit._parse_time_effect_config({"mode": "off"}))
        parsed = fit._parse_time_effect_config(TIME_EFFECT)
        self.assertEqual(parsed["mode"], "analytic_level")
        with self.assertRaises(ValueError):
            fit._parse_time_effect_config({"mode": "analytic_level", "unknown_key": 1})
        with self.assertRaises(ValueError):
            fit._parse_time_effect_config({"mode": "analytic_level", "roas_priors": {"default": [1.2, 5.4, 0.28]}})

    def test_assumption_channels_can_differ_by_fit(self) -> None:
        te = dict(TIME_EFFECT); te["assumption_channels"] = {"default": ["Радио"], "ТСХ/Онлайн::turnover_per_user": ["Рег_ТВ"]}
        parsed = fit._parse_time_effect_config(te)
        self.assertEqual(parsed["assumption_channels"], {"default": ["Радио"], "by_fit": {"ТСХ/Онлайн::turnover_per_user": ["Рег_ТВ"]}})
        _, _, data, _ = build(te)
        self.assertEqual(data["assumption_channels_applied"], ["spend_Рег_ТВ"])               # the per-fit entry replaces the default for this fit
        with self.assertRaises(ValueError):
            fit._parse_time_effect_config({**TIME_EFFECT, "assumption_channels": {"unknown/fit::x": ["Радио"]}})

    def test_switches_off_leave_the_stock_structure(self) -> None:
        _, _, data, model = build(None)
        names = {v.name for v in model.free_RVs}
        self.assertIn("mu_tau", names); self.assertIn("sigma_tau", names | {"sigma_tau"}); self.assertEqual([v.name for v in model.observed_RVs], ["y_obs"])
        self.assertFalse(model.potentials)
        self.assertEqual(data.get("city_level", "off"), "off")
        self.assertEqual(fit.TIME_EFFECT_MODE, "off")

    def test_analytic_structure_and_contract_block(self) -> None:
        seg, coords, data, model = build(TIME_EFFECT)
        names = {v.name for v in model.free_RVs}
        for gone in ("mu_tau", "sigma_tau", "tau_raw"):
            self.assertNotIn(gone, names)
        self.assertIn("sigma_eta", names); self.assertEqual(len(model.observed_RVs), 0); self.assertEqual([p.name for p in model.potentials], ["y_ll"])
        self.assertEqual(data["time_only_controls_dropped"], ["cos_w"])            # a function of the date alone: absorbed by the date effect, not modelled
        self.assertEqual(data["ctrl_active"], ["temp_dev"])
        self.assertEqual(data["assumption_channels_applied"], ["spend_Радио"])
        # nationalised exposure: identical across cities on a date
        m = data["spend_active"].index("spend_Радио")
        by_date = pd.DataFrame({"d": data["date_idx"], "x": data["X_lagged"][0, :, m]}).groupby("d")["x"].nunique()
        self.assertTrue((by_date == 1).all())
        # ROAS-space prior applied to the assumption channel, default to the other one, alpha prior widened for Рег_ТВ
        self.assertEqual({r["spend_col"] for r in data["v4_roas_prior_rows"]}, {"spend_Радио", "spend_Рег_ТВ"})
        k = data["spend_active"].index("spend_Рег_ТВ")
        self.assertAlmostEqual(float(data["a_pars"][k] + data["b_pars"][k]), 2.5, places=6)
        # the model's initial logp is finite and the gradient exists
        point = model.initial_point()
        self.assertTrue(np.isfinite(float(model.compile_logp()(point))))
        self.assertTrue(all(np.all(np.isfinite(g)) for g in model.compile_dlogp()(point)))

    def test_fixed_lambda_channels_stay_constant_in_the_analytic_model(self) -> None:
        """fixed_lambda_channels_by_fit (the stock mechanism, used for the assumption channels): lambda of the listed channel is its prior mean whatever the sampler does,
        lam_unit_free exists only for the free channels, and the analytic likelihood is intact."""
        seg, coords, data, model = build(TIME_EFFECT, mode="tight", fixed_lambda=("Радио",))
        names = {v.name for v in model.free_RVs}
        self.assertIn("lam_unit_free", names); self.assertNotIn("lam_unit", names); self.assertIn("sigma_eta", names)
        self.assertEqual(list(coords["lambda_free_channel"]), ["Рег_ТВ"]); self.assertEqual([p.name for p in model.potentials], ["y_ll"])
        k_fix, k_free = data["spend_active"].index("spend_Радио"), data["spend_active"].index("spend_Рег_ТВ")
        point = model.initial_point(); value_var = model.rvs_to_values[model["lam_unit_free"]]
        lam_fn = pytensor.function(model.value_vars, model.replace_rvs_by_values([model["lam"]])[0], on_unused_input="ignore")      # lam as a function of the value variables
        base = [np.asarray(point[v.name]) for v in model.value_vars]
        lam_a = np.asarray(lam_fn(*base))
        lam_b = np.asarray(lam_fn(*[b + 0.9 if v is value_var else b for v, b in zip(model.value_vars, base)]))
        self.assertEqual(float(lam_a[k_fix]), float(data["lam_prior_mean"][k_fix])); self.assertEqual(float(lam_a[k_fix]), float(lam_b[k_fix]))      # constant
        self.assertNotEqual(float(lam_a[k_free]), float(lam_b[k_free]))                                                                                # the free channel moves
        self.assertTrue(np.isfinite(float(model.compile_logp()(point))))
        self.assertTrue(all(np.all(np.isfinite(g)) for g in model.compile_dlogp()(point)))

    def test_switches_off_identical_to_reference_fit(self) -> None:
        ref = os.environ.get("MMM_REFERENCE_FIT_DIR")
        if not ref:
            self.skipTest("MMM_REFERENCE_FIT_DIR is not set")
        probe = Path(__file__).with_name("_probe_model_structure.py")
        out = []
        for code_dir in (str(PYMC_CODE_DIR), ref):
            res = subprocess.run([sys.executable, str(probe), code_dir], capture_output=True, text=True, check=True)
            out.append(json.loads(res.stdout.strip().splitlines()[-1]))
        self.assertEqual(out[0]["free_rvs"], out[1]["free_rvs"]); self.assertEqual(out[0]["observed_rvs"], out[1]["observed_rvs"])
        self.assertEqual(out[0]["initial_logp"], out[1]["initial_logp"]); self.assertEqual(out[0]["grad_sha256"], out[1]["grad_sha256"])
        self.assertEqual(out[0]["arrays_sha256"], out[1]["arrays_sha256"])


class PostprocessTests(unittest.TestCase):
    def fake_idata(self, data, n_chain=2, n_draw=6, seed=0):
        import xarray as xr
        rng = np.random.default_rng(seed)
        M, K, T = data["M"], data["K_ctrl"], len(data["market_size_tiers"])
        post = {
            "alpha": (("chain", "draw", "channel"), np.tile(np.asarray(data["alpha_prior_mean"], float), (n_chain, n_draw, 1))),
            "lam": (("chain", "draw", "channel"), np.tile(np.asarray(data["lam_prior_mean"], float), (n_chain, n_draw, 1))),
            "beta": (("chain", "draw", "channel"), np.exp(rng.normal(np.log(np.maximum(data["beta_prior_medians"], 1e-4)), 0.1, (n_chain, n_draw, M)))),
            "gamma": (("chain", "draw", "ctrl"), rng.normal(0, 0.01, (n_chain, n_draw, K))),
            "sigma_tier": (("chain", "draw", "market_size_tier"), rng.uniform(0.05, 0.1, (n_chain, n_draw, T))),
            "sigma_eta": (("chain", "draw"), rng.uniform(0.005, 0.02, (n_chain, n_draw))),
        }
        coords = {"chain": np.arange(n_chain), "draw": np.arange(n_draw), "channel": data["spend_active"], "ctrl": data["ctrl_active"], "market_size_tier": data["market_size_tiers"]}
        ds = xr.Dataset({k: xr.DataArray(v[1], dims=v[0], coords={d: coords[d] for d in v[0]}) for k, v in post.items()})
        import arviz as az
        return az.InferenceData(posterior=ds)

    def test_beta_in_synthetic_idata_is_pooled_per_channel(self) -> None:
        _, _, data, _ = build(TIME_EFFECT)
        idata = self.fake_idata(data)
        st = fit._analytic_setup(idata, data)
        self.assertEqual(st["beta_kind"], "pooled")

    def test_end_of_training_level_matches_dense_gp_posterior(self) -> None:
        _, _, data, _ = build(TIME_EFFECT)
        idata = self.fake_idata(data)
        st = fit._analytic_setup(idata, data)
        d = fit._analytic_level_draw(data, 3, st)
        # dense check for city 0: posterior mean of c[g, W-1] given the cross-city-centred residual u of that city
        Y = np.asarray(data["Y"], float); gt = np.asarray(data["geo_idx"], int); wt = np.asarray(data["week_idx"], int); dt = np.asarray(data["date_idx"], int)
        e = Y - d["f"]; nat = np.bincount(dt, weights=e) / np.bincount(dt); u = e - nat[dt]
        W = int(data["n_week"]); eta = float(st["eta"][3]); s0 = float(data["level_sd0"]); g = 0
        rows = np.where(gt == g)[0]; A = np.zeros((len(rows), W)); A[np.arange(len(rows)), wt[rows]] = 1.0
        idx = np.arange(W); C = s0 ** 2 + eta ** 2 * np.minimum(idx[:, None], idx[None, :])
        S = A @ C @ A.T + d["sig_g"][g] ** 2 * np.eye(len(rows))
        mean_end = (C @ A.T @ np.linalg.solve(S, u[rows]))[-1]
        var_end = C[-1, -1] - (C @ A.T @ np.linalg.solve(S, A @ C))[-1, -1]
        self.assertAlmostEqual(float(d["m_end"][g]), float(mean_end), places=8)
        self.assertAlmostEqual(float(d["P_end"][g]), float(var_end), places=8)

    def test_postprocess_adds_derived_variables_and_adequacy_is_sane(self) -> None:
        _, _, data, _ = build(TIME_EFFECT)
        idata = self.fake_idata(data)
        out = fit._postprocess_analytic_levels(idata, data)
        post = out.posterior
        self.assertEqual(tuple(post["tau_g"].dims), ("chain", "draw", "geo_label"))
        self.assertEqual(post["tau_g"].shape, (2, 6, len(GEOS)))
        self.assertTrue(np.all(np.isfinite(post["tau_g"].values)) and np.all(post["city_level_end_sd"].values >= 0) and np.all(post["date_effect_sd"].values >= 0))
        diag_in = {"rhat_max": 1.001, "ess_bulk_min": 999.0, "ess_per_draw": 0.9, "n_params": 5, "n_divergences": 0, "status": "OK ✓"}
        diag_out = fit._refresh_final_file_diagnostics(idata, diag_in, 8, 2)
        self.assertEqual(diag_out["diagnostics_scope"], "final_posterior_file_incl_derived_variables"); self.assertEqual(diag_out["sampler_only_rhat_max"], 1.001)
        self.assertGreater(diag_out["n_params"], 5)                                                 # derived variables (tau_g, city_level_end_sd, ...) are counted
        self.assertTrue(np.isfinite(diag_out["rhat_max"]) and diag_out["ess_bulk_min"] > 0)
        adequacy = fit._adequacy_metrics_analytic(idata, data, "ТСХ/Онлайн::turnover_per_user", max_draws=6)
        for key in ("r2_mean", "r2_point", "coverage_90", "r2_media_controls_only"):
            self.assertTrue(np.isfinite(adequacy[key]), key)
        self.assertLessEqual(adequacy["r2_mean"], 1.0)
        self.assertGreaterEqual(adequacy["r2_point"], adequacy["r2_media_controls_only"] - 1e-9)       # flexible components can only add explained variance in sample


def scorer_inputs(data, seed=5):
    """Transform / snapshot / split for validation._score_fit_snapshot built from the synthetic panel (28 scored days, 14 pre-roll days)."""
    frame = synthetic_panel(seed=3, days=168)
    train_end = pd.Timestamp("2025-01-01") + pd.Timedelta(days=139)
    oot_start, oot_end = train_end + pd.Timedelta(days=1), train_end + pd.Timedelta(days=28)
    snap = frame[frame["date"] >= oot_start - pd.Timedelta(days=14)].copy()
    return frame, snap, train_end, oot_start, oot_end


class ScorerTests(unittest.TestCase):
    def test_time_effect_branch_runs_and_block_changes_the_date_effect(self) -> None:
        from mmm_core import validation as val
        _, _, data, _ = build(TIME_EFFECT)
        idata = PostprocessTests().fake_idata(data, n_chain=2, n_draw=8)
        idata = fit._postprocess_analytic_levels(idata, data)
        post = idata.posterior
        arrays = {}
        for name in ["alpha", "lam", "beta", "tau_g", "gamma", "sigma", "sigma_tier", "sigma_eta", "city_level_end_sd", "date_effect_sd", "nat_block_coef", "nat_block_resid_sd"]:
            if name not in post:
                arrays[name] = (None, []); continue
            da = post[name].stack(sample=("chain", "draw")); nd = [d for d in da.dims if d != "sample"]
            arrays[name] = (da.transpose(*nd, "sample").values, nd)
        frame, snap, train_end, oot_start, oot_end = scorer_inputs(data)
        nb = {"controls": list(data["nat_block_names"]), "mean": [float(v) for v in data["nat_block_mean"]], "std": [float(v) for v in data["nat_block_std"]]}
        transform = {"fit_key": "ТСХ/Онлайн::turnover_per_user", "spend_active": data["spend_active"], "controls": data["ctrl_active"], "geos": data["geos"],
                     "geo_tier_idx": np.asarray(data["geo_tier_idx"], int).tolist(), "ctrl_mean": np.asarray(data["ctrl_mean"], float).tolist(), "ctrl_std": np.asarray(data["ctrl_std"], float).tolist(),
                     "x_scale_geo": np.asarray(data["x_scale_geo"], float).tolist(), "y_scale": float(data["y_scale"]), "y_offset": float(data["y_offset"]), "y_scaling": data["y_scaling"], "l_max": int(data["l_max"]),
                     "time_effect": {"mode": "analytic_level", "assumption_channels": list(data["assumption_channels_applied"]), "national_block": nb}}
        split = val.OOTSplit(train_end=str(train_end.date()), oot_start=str(oot_start.date()), oot_end=str(oot_end.date()), pre_roll_days=14, development_seen=True)
        snap = snap[["date", "geo_label", "network", "channel", "population_k", "market_size_tier", *data["spend_active"], *data["ctrl_active"], *nb["controls"]]]
        res_block, draws_block = val._score_fit_snapshot(snap, transform, {"arrays": arrays}, split, seed=11, national_block=True)
        res_spec, draws_spec = val._score_fit_snapshot(snap, transform, {"arrays": arrays}, split, seed=11, national_block=False)
        self.assertEqual(draws_block.shape, draws_spec.shape); self.assertEqual(draws_block.shape[1], 16)
        self.assertTrue(np.all(np.isfinite(draws_block)) and np.all(np.isfinite(draws_spec)))
        self.assertGreater(float(np.abs(draws_block - draws_spec).mean()), 0.0)             # the block predicts a non-zero national component
        self.assertEqual(len(res_block), 8 * 28)                                            # 8 cities x 28 scored days

    def test_stock_scorer_path_identical_to_reference(self) -> None:
        ref = os.environ.get("MMM_REFERENCE_FIT_DIR")
        if not ref:
            self.skipTest("MMM_REFERENCE_FIT_DIR is not set")
        probe = Path(__file__).with_name("_probe_scorer_identity.py")
        out = [subprocess.run([sys.executable, str(probe), d], capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1] for d in (str(PYMC_CODE_DIR), ref)]
        self.assertEqual(out[0], out[1])


if __name__ == "__main__":
    unittest.main()
