"""Prints a sha256 of the predictions of validation._score_fit_snapshot for a stock-style transform (no time_effect) and a stock-style posterior: the switches-off identity of the scorer."""
import hashlib, sys
from pathlib import Path
import numpy as np, pandas as pd
code_dir = sys.argv[1]
sys.path.insert(0, code_dir); sys.path.insert(1, str(Path(__file__).resolve().parent))
from mmm_core import fit, validation as val  # noqa: E402
import test_time_effect_v4k as helper  # noqa: E402
fit.MEDIA_RESPONSE_MODE = "tight"
frame = helper.synthetic_panel(seed=3, days=168)
fit.MEDIA_GROUPING_ENABLED = False; fit.panel = frame; fit.SPEND_ACTIVE_BASE = ["spend_Радио", "spend_Рег_ТВ"]; fit.TC5_OFFLINE_SPECIFIC_POLICY_ENABLED = False
train = frame[frame["date"] <= "2025-05-20"]
_, coords, data = fit.build_single_target_data(train, "ТСХ", "Онлайн", "turnover_per_user", ["spend_Радио", "spend_Рег_ТВ"], ["temp_dev", "cos_w"], helper.PRIORS, 14)
rng = np.random.default_rng(1); S, G, M, K = 6, int(data["G"]), int(data["M"]), int(data["K_ctrl"]); T = len(data["market_size_tiers"])
arrays = {"alpha": (np.tile(np.asarray(data["alpha_prior_mean"], float)[:, None], (1, S)), ["channel"]), "lam": (np.tile(np.asarray(data["lam_prior_mean"], float)[:, None], (1, S)), ["channel"]),
          "beta": (np.exp(rng.normal(-5, 0.1, (M, S))), ["channel"]), "tau_g": (rng.normal(1.0, 0.05, (G, S)), ["geo_label"]), "gamma": (rng.normal(0, 0.01, (K, S)), ["ctrl"]),
          "sigma": (None, []), "sigma_tier": (rng.uniform(0.05, 0.1, (T, S)), ["market_size_tier"])}
transform = {"fit_key": "ТСХ/Онлайн::turnover_per_user", "spend_active": data["spend_active"], "controls": data["ctrl_active"], "geos": data["geos"], "geo_tier_idx": np.asarray(data["geo_tier_idx"], int).tolist(),
             "ctrl_mean": np.asarray(data["ctrl_mean"], float).tolist(), "ctrl_std": np.asarray(data["ctrl_std"], float).tolist(), "x_scale_geo": np.asarray(data["x_scale_geo"], float).tolist(),
             "y_scale": float(data["y_scale"]), "y_offset": float(data["y_offset"]), "y_scaling": data["y_scaling"], "l_max": int(data["l_max"])}
split = val.OOTSplit(train_end="2025-05-20", oot_start="2025-05-21", oot_end="2025-06-17", pre_roll_days=14, development_seen=True)
snap = frame[frame["date"] >= pd.Timestamp("2025-05-21") - pd.Timedelta(days=14)][["date", "geo_label", "network", "channel", "population_k", "market_size_tier", *data["spend_active"], *data["ctrl_active"]]]
res, draws = val._score_fit_snapshot(snap, transform, {"arrays": arrays}, split, seed=5)
print(hashlib.sha256(np.ascontiguousarray(draws).tobytes()).hexdigest())
