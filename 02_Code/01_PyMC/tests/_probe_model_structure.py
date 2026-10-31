"""Prints, as the last stdout line, a JSON fingerprint of the model built by the fit.py found in <code_dir> from the synthetic panel of test_time_effect_v4k.py with every
switch off: free / observed RV names, initial logp, sha256 of the gradient at the initial point and sha256 of the model input arrays.  Used by the switches-off identity test."""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

code_dir = sys.argv[1]
sys.path.insert(0, code_dir)
sys.path.insert(1, str(Path(__file__).resolve().parent))
from mmm_core import fit  # noqa: E402
import test_time_effect_v4k as helper  # noqa: E402

frame = helper.synthetic_panel()
fit.MEDIA_GROUPING_ENABLED = False; fit.panel = frame; fit.SPEND_ACTIVE_BASE = ["spend_Радио", "spend_Рег_ТВ"]; fit.TC5_OFFLINE_SPECIFIC_POLICY_ENABLED = False
fit.MEDIA_RESPONSE_MODE = "tight"
_, coords, data = fit.build_single_target_data(frame, "ТСХ", "Онлайн", "turnover_per_user", ["spend_Радио", "spend_Рег_ТВ"], ["temp_dev", "cos_w"], helper.PRIORS, 14)
model = fit.build_pymc_model(coords, data)
point = model.initial_point()
grads = model.compile_dlogp()(point)
sha = lambda a: hashlib.sha256(np.ascontiguousarray(np.asarray(a, dtype=float)).tobytes()).hexdigest()
print(json.dumps({
    "free_rvs": [v.name for v in model.free_RVs], "observed_rvs": [v.name for v in model.observed_RVs],
    "initial_logp": float(model.compile_logp()(point)), "grad_sha256": sha(np.concatenate([np.ravel(g) for g in grads])),
    "arrays_sha256": {k: sha(data[k]) for k in ("Y", "X_lagged", "X_ctrl", "a_pars", "b_pars", "beta_prior_medians", "beta_prior_log_sd", "sigma_tier_prior")},
}))
