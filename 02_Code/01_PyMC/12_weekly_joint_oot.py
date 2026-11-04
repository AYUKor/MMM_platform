"""OOT check of the weekly joint model (Alex 04.11: «давай тогда сверим по оот модель»).

The model with the settings of «Заноза» (production v13) is fitted only on the weeks up to --fit-window-end
(default 23.03.2026, the week 23.03-29.03), as if the data ended there. Then it forecasts the following weeks of
the panel (30.03-28.06.2026) with their actual media spend, the way the forecaster gets a media plan, and the
forecast is compared with the actual orders, average check and turnover by network x direction, week, city group
and unit. A simple forecast is scored on the same rows: the same week a year earlier x the unit's growth over its
last 12 fitted weeks against the same weeks a year earlier.

Why a cut panel and not 05 --fit-window-end: with the flag the week-level terms (trend knots, the centring and
orthogonalisation of hinges, Fourier and holidays, the week-shock basis) are still built on all 78 weeks, so the
weeks after the cut carry parameters with no data (flat ridges for the sampler) and the construction sees the
future calendar. Here the panel is cut first (a new file in OUT; the panel itself is not touched), so the fit is
exactly the production model on fewer weeks, and the forecast extends each term the way the model defines it:
- level, unit slope, own city wave, segment and resort season, holidays: their formulas at the new weeks (the
  hinges continue with their last slope; centring and orthogonalisation use the fitted weeks' constants);
- new trend knots every 7 weeks after the last fitted knot, slope change tau_trend x N(0, 1) per target and
  segment (the prior the fitted knots have);
- week shock: N(0, sig_week^2 x R/W) per segment-week (the average per-week variance of the fitted shock);
- AR(1) error: from the unit's last fitted residual, rho^h decay plus Student-t(6) innovations with the fitted
  sigma and the check-on-orders link;
- weather controls: 0, the segment-week mean (the weather of the forecast weeks is not known in advance);
- media: the model's adstock and saturation on the actual spend of all weeks (carry-over from the fitted weeks
  included).
Every part that the fitted model already has is computed by the model code itself (numpyro_model with emit_parts,
part_mu). The script checks that the extended week arrays equal the fitted ones on the fitted weeks and that on the
last fitted week part_mu from the extended arrays equals part_mu from the fitted arrays.

Known leak, written into the card: --lam-prior data takes the saturation shape from real_production_v6, fitted on
all 78 weeks; it touches only the media part. Run this script with the v6 settings (--no-city-wave, --prior-set
moderate, no anchor, --media-geo unit, --check-sd 0.5, no --lam-prior) on the same cut: its lam medians are the
honest ones (card: lam_median). If one differs by more than 10% from LAM_DATA_ONLY, refit with
--lam-prior "C=median:0.1,...".

v2 (04.11, after the fast runs): the fast runs showed that continuing the last fitted slope for 13 weeks drives
the forecast down (delivery -30..-50% by June) and pulls orders and check apart; the last knot (16.03) has one
fitted week after it and the week shock cannot take a segment-wide move of the last week (it is orthogonal to the
hinges), so that week sets the last slope. The fit is not affected; the forecast is now made under three trend
rules side by side (--trend-rules): continue (the model's own formulas), hold (trend part held at the last fitted
week), hold4 (held at its mean over the last 4 fitted weeks). Also added: the ad response check, a regression of
log(actual / forecast without ads) on the forecast log ad effect with unit and segment-week fixed effects (the ad
part is 0.2-0.4% of turnover, so the turnover level cannot confirm or refute ROAS; this looks at the timing and the
spread of the local channels). With --reuse on a v1 folder only the forecast is recomputed; v1 files stay.

July-September 2026 are not in the panel and are never read.

Outputs (OUT): panel_fit_window.parquet, multistart_{p}.csv, posterior_all_{p}.npz, oot_fit_diag_{p}.json,
roas_by_segment_channel_{p}.csv; per trend rule r: oot_rows_{p}_{r}.csv, oot_by_segment_{p}_{r}.csv,
oot_by_segment_week_{p}_{r}.csv, oot_by_city_group_{p}_{r}.csv, oot_by_unit_{p}_{r}.csv; oot_card_{p}_v2.json.

Run: python -I 12_weekly_joint_oot.py --panel P.parquet --national N.csv --out OUT --profile fast|pilot
     [--fit-window-end 2026-03-23] [--m-ref m_ref_v3.csv] [model flags as in 05] [--reuse]
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault('XLA_FLAGS', '--xla_force_host_platform_device_count=4')
sys.path.insert(0, str(Path(__file__).resolve().parent))     # run with python -I: the script folder is not on the path

import numpy as np
import pandas as pd

from mmm_core import weekly_joint as wj

CODE_VERSION = 'oot_v2_20261104'
DETERMINISTIC = {'R_orders_seg', 'roas_realized'}
CITY = {'МОСКВА': 'Москва', 'САНКТ-ПЕТЕРБУРГ': 'Санкт-Петербург'}
NAIVE_WINDOW_WEEKS = 12      # growth of the last 12 fitted weeks against the same weeks a year earlier
NAIVE_MIN_PAIRS = 10
LAM_HONEST_TOL = 0.10        # |log(lam honest / lam used)| above this -> refit with the honest lam prior


def load_05():
    path = Path(__file__).resolve().parent / '05_weekly_joint_real_fit.py'
    spec = importlib.util.spec_from_file_location('weekly_joint_real_fit', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


# ---------------------------------------------------------------- week-level terms at all weeks

def fourier_raw(weeks: pd.DatetimeIndex) -> np.ndarray:
    doy = (weeks + pd.Timedelta(days=3)).dayofyear.to_numpy() / 365.25
    return np.column_stack([np.sin(2 * np.pi * doy), np.cos(2 * np.pi * doy),
                            np.sin(4 * np.pi * doy), np.cos(4 * np.pi * doy)])


def extend_week_terms(weeks_fit: pd.DatetimeIndex, weeks_all: pd.DatetimeIndex) -> dict:
    """The week arrays of wj.prepare() at all weeks, built with the constants of the fitted weeks only (the same
    steps as prepare: hinges at every 7th week but the last, centred; Fourier and holidays centred; hinges made
    orthogonal to [1, t, Fourier] over the fitted weeks; that linear map is then applied to every week)."""
    k = wj.KNOT_EVERY_WEEKS
    t_f = (weeks_fit - weeks_fit[0]).days.to_numpy() / 365.25
    t_a = (weeks_all - weeks_fit[0]).days.to_numpy() / 365.25
    knot_idx = np.arange(k, len(t_f) - 1, k)
    knots = t_f[knot_idx]
    hinge_f = np.maximum(0.0, t_f[:, None] - knots[None, :])
    h_mean = hinge_f.mean(0)
    F_f = fourier_raw(weeks_fit)
    f_mean = F_f.mean(0)
    H_f, _ = wj._holiday_matrix(weeks_fit)
    hol_mean = H_f.mean(0)
    G_f = np.column_stack([np.ones_like(t_f), t_f - t_f.mean(), F_f - f_mean])
    coef = np.linalg.lstsq(G_f, hinge_f - h_mean, rcond=None)[0]
    F_a = fourier_raw(weeks_all) - f_mean
    G_a = np.column_stack([np.ones_like(t_a), t_a - t_f.mean(), F_a])
    basis_a = np.maximum(0.0, t_a[:, None] - knots[None, :]) - h_mean - G_a @ coef
    H_a = wj._holiday_matrix(weeks_all)[0] - hol_mean
    return dict(t=t_a - t_f.mean(), t_raw=t_a, basis=basis_a, F=F_a, H=H_a, knot_idx=knot_idx,
                hinge_raw=np.maximum(0.0, t_a[:, None] - knots[None, :]), h_mean=h_mean, coef=coef, t_fit_mean=t_f.mean())


TREND_RULES = ('continue', 'hold', 'hold4')


def week_terms_rule(ext: dict, W_f: int, rule: str) -> dict:
    """Week arrays for the weeks after the cut under a trend rule (v2, after the fast runs of 04.11: continuing the
    last fitted slope for 13 weeks drove the forecast 30-50% down in delivery and split orders and check apart).
    continue: the model's own formulas (the line, unit slopes and hinges go on with their last slope);
    hold: the trend part (segment line, unit slopes, hinges with their linear part) stays at the last fitted week;
    hold4: it stays at its mean over the last 4 fitted weeks (less weight on one week).
    Season (Fourier, also inside the orthogonalised hinges), holidays, own city waves, shocks and AR(1) go on."""
    if rule == 'continue':
        return ext
    n = {'hold': 1, 'hold4': 4}[rule]
    t_raw = ext['t_raw'].copy()
    hinge = ext['hinge_raw'].copy()
    t_raw[W_f:] = t_raw[W_f - n:W_f].mean()
    hinge[W_f:] = hinge[W_f - n:W_f].mean(0)
    G = np.column_stack([np.ones_like(t_raw), t_raw - ext['t_fit_mean'], ext['F']])
    return dict(ext, t=t_raw - ext['t_fit_mean'], basis=hinge - ext['h_mean'] - G @ ext['coef'])


def demean2(v: np.ndarray, g1: np.ndarray, g2: np.ndarray, iters: int = 100) -> np.ndarray:
    """v minus two sets of group means (alternating projections)."""
    v = v.astype(float).copy()
    n1, n2 = g1.max() + 1, g2.max() + 1
    for _ in range(iters):
        v -= (np.bincount(g1, v, n1) / np.bincount(g1, minlength=n1))[g1]
        v -= (np.bincount(g2, v, n2) / np.bincount(g2, minlength=n2))[g2]
    return v


def media_response(z: np.ndarray, x: np.ndarray, unit: np.ndarray, segweek: np.ndarray) -> dict:
    """Slope of z = log(actual / forecast without ads) on x = forecast log ad effect, with unit and segment-week
    fixed effects (national TV timing and the common week go into the fixed effects; the local channels' timing
    and spread across cities is left). Slope near 1: the forecast ad response matches the actual weeks; near 0: it
    does not. SE clustered by unit."""
    zd, xd = demean2(z, unit, segweek), demean2(x, unit, segweek)
    sxx = float((xd ** 2).sum())
    if sxx <= 0:
        return dict(slope=None)
    b = float((xd * zd).sum() / sxx)
    e = zd - b * xd
    se = float(np.sqrt((np.bincount(unit, xd * e) ** 2).sum()) / sxx)
    return dict(slope=round(b, 3), se_cluster_unit=round(se, 3), n=int(len(z)), sd_x_after_fe=float(np.round(xd.std(), 5)),
                sd_x_raw=float(np.round(x.std(), 5)), sd_resid=float(np.round(e.std(), 4)))


def rows_arr(base: dict, rows: dict, ybar_m: np.ndarray, weeks: dict, spend_norm: np.ndarray,
             week_basis: np.ndarray) -> dict:
    """Model arrays for arbitrary unit-weeks (rows) with the fitted model's settings."""
    n = len(rows['m_i'])
    return dict(base, m_i=rows['m_i'], a_i=rows['a_i'], w_i=rows['w_i'], s_i=rows['s_i'], tier_i=rows['tier_i'],
                prev=np.full(n, -1), resort=rows['resort'].astype(float), X=rows['X'],
                ybar=ybar_m[rows['m_i']], t=weeks['t'], basis=weeks['basis'], F=weeks['F'], H=weeks['H'],
                week_basis=week_basis, spend_norm=spend_norm, emit_parts=True)


def predict_parts(arr_x: dict, dims: dict, prior_set: str, samples: dict) -> tuple[np.ndarray, np.ndarray]:
    """part_mu and part_media [D, 2, N] for every draw in samples (draws one after another, compiled once)."""
    import jax
    from numpyro.infer import Predictive
    pred = Predictive(wj.numpyro_model, posterior_samples=samples, return_sites=['part_mu', 'part_media'],
                      parallel=False)
    r = pred(jax.random.PRNGKey(0), arr_x, dims, prior_set, y=None)
    return np.asarray(r['part_mu'], float), np.asarray(r['part_media'], float)


def rows_of(o: pd.DataFrame, midx: dict, aidx: dict, X: np.ndarray) -> dict:
    return dict(m_i=o.mu_key.map(midx).to_numpy(int), a_i=o.ad_key.map(aidx).to_numpy(int),
                w_i=o.w_i.to_numpy(int), s_i=o.seg_i.to_numpy(int), tier_i=o.tier_i.to_numpy(int),
                resort=o.resort.to_numpy(), X=X)


# ---------------------------------------------------------------- simple forecast

def naive_forecast(panel: pd.DataFrame, rows: pd.DataFrame, fit_end: pd.Timestamp) -> pd.DataFrame:
    """Same week a year earlier (364 days, same weekdays) x the unit's growth over the last 12 fitted weeks
    against the same weeks a year earlier (at least 10 week pairs), for turnover and orders separately."""
    v = panel[panel.target_valid_week & panel.fit_exclude_reason.fillna('').eq('')
              & (panel.turnover_total > 0) & (panel.orders_cnt > 0)].copy()
    v['mu_key'] = v.segment + '|' + v.model_unit_id
    v = v.drop_duplicates(['mu_key', 'week_start'])
    T = dict(zip(zip(v.mu_key, v.week_start), v.turnover_total.astype(float)))
    O = dict(zip(zip(v.mu_key, v.week_start), v.orders_cnt.astype(float)))
    yr = pd.Timedelta(days=364)
    win = pd.date_range(end=fit_end, periods=NAIVE_WINDOW_WEEKS, freq='7D')
    growth = {}
    for key in rows.mu_key.unique():
        now = [(key, w) for w in win]
        ago = [(key, w - yr) for w in win]
        ok = [i for i in range(len(win)) if now[i] in T and ago[i] in T]
        if len(ok) < NAIVE_MIN_PAIRS:
            continue
        gT = sum(T[now[i]] for i in ok) / sum(T[ago[i]] for i in ok)
        gO = sum(O[now[i]] for i in ok) / sum(O[ago[i]] for i in ok)
        growth[key] = (gT, gO, len(ok))
    out = []
    for r in rows.itertuples(index=False):
        g = growth.get(r.mu_key)
        ago = (r.mu_key, r.week_start - yr)
        if g is None or ago not in T:
            out.append((np.nan, np.nan))
        else:
            out.append((T[ago] * g[0], O[ago] * g[1]))
    return pd.DataFrame(out, columns=['naive_turnover', 'naive_orders'], index=rows.index)


# ---------------------------------------------------------------- scoring

def q(x: np.ndarray, axis=0) -> dict:
    return dict(q05=np.quantile(x, 0.05, axis=axis), median=np.median(x, axis=axis),
                q95=np.quantile(x, 0.95, axis=axis), mean=x.mean(axis=axis))


def group_table(codes: np.ndarray, names: list, T_d: np.ndarray, O_d: np.ndarray, rows: pd.DataFrame,
                common: np.ndarray) -> pd.DataFrame:
    """Per group: actual and forecast (median, 90% band) turnover, orders and average check; on the rows where the
    simple forecast exists, the model and the simple forecast side by side."""
    G = len(names)
    oh = np.zeros((len(codes), G))
    oh[np.arange(len(codes)), codes] = 1.0
    ohc = oh * common[:, None]
    actT, actO = rows.turnover_total.to_numpy(float), rows.orders_cnt.to_numpy(float)
    fT, fO = T_d @ oh, O_d @ oh                               # [D, G]
    fTc = T_d @ ohc
    t = pd.DataFrame({'group': names})
    t['actual_turnover'] = actT @ oh
    for k, v in q(fT).items():
        t[f'fc_turnover_{k}'] = v
    t['err_turnover_pct'] = 100 * (t.fc_turnover_median / t.actual_turnover - 1)
    t['inside_90'] = (t.actual_turnover >= t.fc_turnover_q05) & (t.actual_turnover <= t.fc_turnover_q95)
    t['actual_orders'] = actO @ oh
    qo = q(fO)
    t['fc_orders_median'] = qo['median']
    t['err_orders_pct'] = 100 * (t.fc_orders_median / t.actual_orders - 1)
    t['actual_check'] = t.actual_turnover / t.actual_orders
    qc = q(fT / np.where(fO > 0, fO, np.nan))
    t['fc_check_median'], t['fc_check_q05'], t['fc_check_q95'] = qc['median'], qc['q05'], qc['q95']
    t['err_check_pct'] = 100 * (t.fc_check_median / t.actual_check - 1)
    t['common_share_of_turnover'] = (actT @ ohc) / t.actual_turnover
    t['common_actual_turnover'] = actT @ ohc
    t['common_fc_turnover_median'] = np.median(fTc, 0)
    t['common_naive_turnover'] = np.nan_to_num(rows.naive_turnover.to_numpy(float)) @ ohc
    t['common_err_model_pct'] = 100 * (t.common_fc_turnover_median / t.common_actual_turnover - 1)
    t['common_err_naive_pct'] = 100 * (t.common_naive_turnover / t.common_actual_turnover - 1)
    return t


def wape(fc: np.ndarray, act: np.ndarray) -> float:
    return float(np.abs(fc - act).sum() / act.sum())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--panel', required=True)
    ap.add_argument('--national', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--profile', default='fast', choices=['fast', 'medium', 'pilot', 'production'])
    ap.add_argument('--fit-window-end', default='2026-03-23', help='last week_start in the fit')
    ap.add_argument('--seed', type=int, default=20261104)
    ap.add_argument('--prior-set', default='moderate', choices=list(wj.PRIOR_SETS))
    ap.add_argument('--chain-method', default='vectorized', choices=['sequential', 'vectorized'])
    ap.add_argument('--starts', type=int, default=8)
    ap.add_argument('--vi-steps', type=int, default=15000)
    ap.add_argument('--stop-if-roas-above', type=float, default=10.0)
    ap.add_argument('--jitter', type=float, default=0.05)
    ap.add_argument('--no-city-wave', action='store_true')
    ap.add_argument('--wave-scale', default='learned', choices=['learned', 'fixed'])
    ap.add_argument('--anchor', default='')
    ap.add_argument('--media-geo', default='unit', choices=['unit', 'tier'])
    ap.add_argument('--check-sd', type=float, default=0.5)
    ap.add_argument('--lam-prior', default='')
    ap.add_argument('--m-ref', default=None, help='typical spend per resident (m_ref_v3 csv) so lam means the same as in the full fit')
    ap.add_argument('--forecast-draws', type=int, default=500)
    ap.add_argument('--reuse', action='store_true', help='skip the fit when posterior_all_{profile}.npz exists in OUT')
    ap.add_argument('--trend-rules', default=','.join(TREND_RULES), help='trend after the cut, any of continue,hold,hold4')
    a = ap.parse_args()
    rf = load_05()
    prof = rf.PROFILES[a.profile]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    fe = pd.Timestamp(a.fit_window_end)

    import jax
    import numpyro
    numpyro.set_host_device_count(prof['chains'])

    t0 = time.time()
    p = pd.read_parquet(a.panel)
    assert p.week_start.max() <= pd.Timestamp('2026-06-22'), 'панель выходит за 28.06.2026'
    cut_path = out / 'panel_fit_window.parquet'
    if not cut_path.exists():
        p[p.week_start <= fe].to_parquet(cut_path, index=False)
    assert len(pd.read_parquet(cut_path, columns=['week_start'])) == int((p.week_start <= fe).sum()), 'old cut differs'
    d = wj.prepare(str(cut_path), a.national, top_units_per_segment=prof['top_units'], m_ref_csv=a.m_ref)
    arr = wj.model_arrays(d, city_wave=not a.no_city_wave, wave_centred=True, slope_centred=False,
                          wave_scale=a.wave_scale, adstock='short', roas_scale='equal', weaken='', anchor=a.anchor,
                          media_geo=a.media_geo, check_sd=a.check_sd, lam_prior=a.lam_prior)
    o = d.obs
    y = np.vstack([o.y_orders.to_numpy(float), o.y_check.to_numpy(float)])
    arr = wj.with_fixed_wave_scale(d, wj.with_targets(arr, y), y)
    turnover = np.exp(y[0] + y[1])
    turnover_by_seg = pd.Series(turnover).groupby(pd.Series(arr['s_i']).map(dict(enumerate(wj.SEGMENTS)))).sum()
    print('fit dims', d.dims, 'weeks', str(d.weeks[0].date()), '-', str(d.weeks[-1].date()),
          'fitted', str(o.week_start.min().date()), '-', str(o.week_start.max().date()), f'prep {time.time()-t0:.0f}s',
          flush=True)

    post_path = out / f'posterior_all_{a.profile}.npz'
    card = dict(profile=a.profile, code_version=CODE_VERSION, fit_window_end=a.fit_window_end, prior_set=a.prior_set,
                anchor=a.anchor, media_geo=a.media_geo, check_sd=a.check_sd, lam_prior=a.lam_prior,
                city_wave_model=not a.no_city_wave, wave_scale=a.wave_scale, m_ref=a.m_ref, dims_fit=d.dims,
                inputs=dict(panel=a.panel, panel_sha256=sha256(a.panel), national=a.national,
                            national_sha256=sha256(a.national), m_ref_sha256=sha256(a.m_ref) if a.m_ref else None,
                            panel_fit_window_rows=int((p.week_start <= fe).sum())),
                code=dict(script_sha256=sha256(__file__), weekly_joint_sha256=sha256(wj.__file__)),
                leak_note=('lam prior data:SD = medians of real_production_v6 fitted on all 78 weeks (media part only)'
                           if a.lam_prior.startswith('data:') else ''))
    if a.reuse and post_path.exists():
        z = np.load(post_path)
        by_chain = {k: z[k] for k in z.files if not k.startswith('_')}
        card['fit'] = json.loads((out / f'oot_fit_diag_{a.profile}.json').read_text())
        print('reusing', post_path, flush=True)
    else:
        from numpyro.infer import MCMC, NUTS
        from numpyro.infer.initialization import init_to_median
        init_params, ms_card = None, None
        if a.starts > 0:
            t_ms = time.time()
            starts = wj.multi_start_vi(arr, d.dims, a.prior_set, y, n_starts=a.starts, steps=a.vi_steps, seed=a.seed)
            rows = []
            for st in starts:
                r = pd.Series(dtype=float)
                if st['finite']:
                    g = rf.roas_at_point(d, arr, st['point'], turnover).groupby('channel')[['effect_rub', 'spend_rub']].sum()
                    r = g.effect_rub / g.spend_rub
                rows.append(dict(start=st['start'], init=st['init'], loss=st['loss'], finite=st['finite'])
                            | {f'roas_{c}': r.get(c, np.nan) for c in wj.CHANNELS})
            ms = pd.DataFrame(rows)
            ms['loss_minus_best'] = ms.loss - ms.loss[ms.finite].min()
            ms.to_csv(out / f'multistart_{a.profile}.csv', index=False)
            ib = int(ms.loss.where(ms.finite).idxmin())
            best = starts[ib]
            best_seg = rf.roas_at_point(d, arr, best['point'], turnover)
            ms_card = dict(seconds=round(time.time() - t_ms), best_start=best['start'],
                           loss_minus_best=ms.loss_minus_best.round(1).tolist(),
                           best_start_roas=ms.loc[ib, [f'roas_{c}' for c in wj.CHANNELS]].astype(float).round(2).to_dict())
            print('start search', json.dumps(ms_card, ensure_ascii=False, default=str), flush=True)
            if (best_seg.roas > a.stop_if_roas_above).any():
                card |= dict(status='stopped_start_roas_above_rule', mode_search=ms_card)
                (out / f'oot_card_{a.profile}.json').write_text(json.dumps(card, ensure_ascii=False, indent=2, default=str))
                print('STOPPED: the best start breaks the ROAS stop rule', flush=True)
                return
            init_params = wj.init_params_from(best, prof['chains'], jitter=a.jitter, seed=a.seed)
        kernel = NUTS(wj.numpyro_model, target_accept_prob=prof['target_accept'], max_tree_depth=prof['max_tree_depth'],
                      init_strategy=init_to_median(num_samples=15))
        mcmc = MCMC(kernel, num_warmup=prof['warmup'], num_samples=prof['draws'], num_chains=prof['chains'],
                    chain_method=a.chain_method, progress_bar=False)
        t1 = time.time()
        mcmc.run(jax.random.PRNGKey(a.seed), arr, d.dims, a.prior_set, y=y, init_params=init_params,
                 extra_fields=('diverging', 'potential_energy', 'num_steps'))
        by_chain = {k: np.asarray(v, np.float32) for k, v in mcmc.get_samples(group_by_chain=True).items()
                    if k not in DETERMINISTIC}
        fit_s = time.time() - t1
        extra = mcmc.get_extra_fields(group_by_chain=True)
        np.savez_compressed(post_path, **by_chain, _diverging=np.asarray(extra['diverging']),
                            _potential_energy=np.asarray(extra['potential_energy'], np.float32),
                            _num_steps=np.asarray(extra['num_steps'], np.int32))
        from numpyro.diagnostics import summary
        summ = summary(by_chain, group_by_chain=True)
        rh = {k: float(np.nanmax(v['r_hat'])) for k, v in summ.items()}
        ess = {k: float(np.nanmin(v['n_eff'])) for k, v in summ.items()}
        fit = dict(fit_seconds=round(fit_s), warmup=prof['warmup'], draws=prof['draws'], chains=prof['chains'],
                   divergences=int(np.asarray(extra['diverging']).sum()), mode_search=ms_card,
                   max_r_hat_roas_params={k: round(rh[k], 3) for k in wj.roas_keys(arr)},
                   max_r_hat={k: round(v, 3) for k, v in sorted(rh.items(), key=lambda x: -x[1])[:8]},
                   min_ess={k: round(v) for k, v in sorted(ess.items(), key=lambda x: x[1])[:8]},
                   num_steps_mean=np.asarray(extra['num_steps']).mean(1).round(1).tolist())
        (out / f'oot_fit_diag_{a.profile}.json').write_text(json.dumps(fit, ensure_ascii=False, indent=2))
        card['fit'] = fit
        print('fit', json.dumps(fit, ensure_ascii=False), flush=True)

    flat = {k: v.reshape((-1,) + v.shape[2:]) for k, v in by_chain.items()}
    n_tot = flat['alpha'].shape[0]
    card['lam_median'] = dict(zip(wj.CHANNELS, np.median(flat['lam'], 0).round(3).tolist()))
    lam_used = np.exp(arr['lam_loc']) if 'lam_loc' in arr else np.full(len(wj.CHANNELS), wj.LAM_PRIOR_DEFAULT[0])
    card['lam_prior_median_used'] = dict(zip(wj.CHANNELS, np.round(lam_used, 3).tolist()))
    card['lam_vs_data_only'] = {c: round(float(np.log(card['lam_median'][c] / m)), 3)
                                for c, m in wj.LAM_DATA_ONLY.items()}

    # ROAS of the cut fit (fitted weeks), as 05 reports it
    est = rf.roas_draws(d, arr, flat, turnover, prof['chains'])
    seg = rf.segment_table(est, turnover_by_seg)
    if not (out / f'roas_by_segment_channel_{a.profile}.csv').exists():
        seg.to_csv(out / f'roas_by_segment_channel_{a.profile}.csv', index=False)
    ch = est.groupby(['channel', 'draw'])[['effect_rub', 'spend_rub']].sum()
    ch = (ch.effect_rub / ch.spend_rub).groupby('channel')
    card['roas_channel'] = {c: [round(float(g.quantile(0.05)), 3), round(float(g.median()), 3),
                                round(float(g.quantile(0.95)), 3)] for c, g in ch}

    # ------------------------------------------------------------ forecast of the weeks after the cut
    d_all = wj.prepare(a.panel, a.national, m_ref_csv=a.m_ref)
    W_f, W_a = len(d.weeks), len(d_all.weeks)
    assert (d_all.weeks[:W_f] == d.weeks).all(), 'weeks of the cut are not the first weeks of the panel'
    ext = extend_week_terms(d.weeks, d_all.weeks)
    checks = dict(week_terms_max_abs_diff=float(max(np.abs(ext['t'][:W_f] - d.t_year).max(),
                                                    np.abs(ext['basis'][:W_f] - d.trend_basis).max(),
                                                    np.abs(ext['F'][:W_f] - d.fourier).max(),
                                                    np.abs(ext['H'][:W_f] - d.holidays).max())))
    assert checks['week_terms_max_abs_diff'] < 1e-9, checks
    aidx_all = {k: i for i, k in enumerate(d_all.ad_units.ad_key)}
    assert all(k in aidx_all for k in d.ad_units.ad_key)
    ia = np.array([aidx_all[k] for k in d.ad_units.ad_key])
    sp_all = d_all.spend_pr[ia]
    # the fitted weeks keep exactly the spend the fit saw; only the weeks after the cut come from the full panel
    checks['spend_pr_fit_weeks_max_abs_diff_before_splice'] = float(np.abs(sp_all[:, :W_f] - d.spend_pr).max())
    checks['ad_units_population_differs'] = int((np.abs(d_all.ad_units.pop_k.to_numpy()[ia]
                                                        - d.ad_units.pop_k.to_numpy()) > 1e-9).sum())
    sp_all = np.concatenate([d.spend_pr, sp_all[:, W_f:]], axis=1)
    mr = d.m_ref[d.ad_units.seg_i.to_numpy()]
    spend_norm_all = np.where(mr[:, None, :] > 0, sp_all / np.where(mr > 0, mr, 1.0)[:, None, :], 0.0)
    checks['spend_norm_fit_weeks_max_abs_diff'] = float(np.abs(spend_norm_all[:, :W_f] - arr['spend_norm']).max())
    assert checks['spend_norm_fit_weeks_max_abs_diff'] < 1e-9, checks
    R = arr['week_basis'].shape[1]
    wb_all = np.vstack([arr['week_basis'], np.zeros((W_a - W_f, R))])

    M = len(d.model_units)
    midx = {k: i for i, k in enumerate(d.model_units.mu_key)}
    aidx = {k: i for i, k in enumerate(d.ad_units.ad_key)}
    ybar_m = np.zeros((M, 2))
    ybar_m[arr['m_i']] = arr['ybar']
    fut = d_all.obs[d_all.obs.week_start > fe]
    keep = fut.mu_key.isin(midx) & fut.ad_key.isin(aidx)
    fc = fut[keep].reset_index(drop=True)
    lost = fut[~keep]
    card['forecast_rows'] = dict(rows=len(fc), units=int(fc.mu_key.nunique()),
                                 weeks=[str(fc.week_start.min().date()), str(fc.week_start.max().date())],
                                 n_weeks=int(fc.week_start.nunique()), rows_not_forecastable=len(lost),
                                 turnover_share_not_forecastable=round(float(lost.turnover_total.sum()
                                                                             / fut.turnover_total.sum()), 4),
                                 units_not_forecastable=sorted(lost.mu_key.unique().tolist())[:40])
    print('forecast rows', json.dumps(card['forecast_rows'], ensure_ascii=False), flush=True)

    idx = np.linspace(0, n_tot - 1, min(a.forecast_draws, n_tot)).astype(int)
    samp = {k: v[idx] for k, v in flat.items()}
    D = len(idx)
    weeks_fit = dict(t=arr['t'], basis=arr['basis'], F=arr['F'], H=arr['H'])

    # last fitted week of every model unit: residual for the AR(1) start, and the consistency check
    li = o.groupby('m_i').w_i.idxmax().to_numpy()
    last = o.loc[li]
    r_rows = rows_of(last, midx, aidx, arr['X'][li])
    mu_last, _ = predict_parts(rows_arr(arr, r_rows, ybar_m, weeks_fit, arr['spend_norm'], arr['week_basis']),
                               d.dims, a.prior_set, samp)
    mu_last_ext, _ = predict_parts(rows_arr(arr, r_rows, ybar_m, ext, spend_norm_all, wb_all),
                                   d.dims, a.prior_set, samp)
    checks['part_mu_last_week_max_abs_diff'] = float(np.abs(mu_last - mu_last_ext).max())
    assert checks['part_mu_last_week_max_abs_diff'] < 1e-3, checks
    y_last = np.vstack([last.y_orders.to_numpy(float), last.y_check.to_numpy(float)])
    r_last = np.zeros((D, 2, M))
    m_last = r_rows['m_i']
    r_last[:, :, m_last] = y_last[None] - mu_last
    w_last = np.zeros(M, int)
    w_last[m_last] = last.w_i.to_numpy()
    tier_m = np.zeros(M, int)
    tier_m[m_last] = last.tier_i.to_numpy()
    seg_m = d.model_units.seg_i.to_numpy()
    rho, sig, boc = samp['rho'], samp['sigma'], samp['b_check_on_orders']
    implied = sig[:, :, seg_m, tier_m] / np.sqrt(1 - rho[:, :, seg_m] ** 2)          # [D, 2, M]
    checks['last_residual_sd_over_model_sd'] = np.round(r_last.std(axis=(0, 2)) / np.median(implied, axis=(0, 2)), 3).tolist()

    # draws shared by every trend rule: new knots, week shocks, AR(1) path
    rng = np.random.default_rng(a.seed)
    k = wj.KNOT_EVERY_WEEKS
    new_idx = np.arange(ext['knot_idx'][-1] + k, W_a - 1, k)
    hinge_new = np.maximum(0.0, ext['t_raw'][:, None] - ext['t_raw'][new_idx][None, :])      # [W_a, J]
    z_new = rng.standard_normal((D, 2, len(wj.SEGMENTS), len(new_idx)))
    trend_new = samp['tau_trend'][:, :, None, None] * np.einsum('wj,dksj->dksw', hinge_new, z_new)
    shock_new = np.zeros((D, 2, len(wj.SEGMENTS), W_a))
    shock_new[..., W_f:] = (rng.standard_normal((D, 2, len(wj.SEGMENTS), W_a - W_f))
                            * samp['sig_week'][:, :, :, None] * np.sqrt(R / W_f))
    f_rows = rows_of(fc, midx, aidx, np.zeros((len(fc), arr['X'].shape[1])))     # X = 0: weather unknown in advance
    h_fc = f_rows['w_i'] - w_last[f_rows['m_i']]
    assert (h_fc >= 1).all()
    H = int(h_fc.max())
    rho_m, sc_m, b_m = rho[:, :, seg_m], sig[:, :, seg_m, tier_m], boc[:, seg_m]
    path = np.zeros((D, 2, M, H + 1))
    path[..., 0] = r_last
    r = r_last.copy()
    for h in range(1, H + 1):
        eo = rng.standard_t(6.0, (D, M)) * sc_m[:, 0]
        ec = b_m * eo * sc_m[:, 1] / sc_m[:, 0] + rng.standard_t(6.0, (D, M)) * sc_m[:, 1]
        r = rho_m * r + np.stack([eo, ec], 1)
        path[..., h] = r
    s_fc, w_fc, m_fc = f_rows['s_i'], f_rows['w_i'], f_rows['m_i']

    nv = naive_forecast(p, fc, fe)
    fc = pd.concat([fc, nv], axis=1)
    common = fc.naive_turnover.notna().to_numpy()
    fc['city_group'] = np.where(fc.unit_label.isin(list(CITY)), fc.unit_label.map(CITY),
                                fc.size_tier.fillna('other').astype(str))
    spend_rub = (sp_all[f_rows['a_i'], w_fc, :] * (d.ad_units.pop_k.to_numpy()[f_rows['a_i']] * 1000)[:, None]
                 * d.chan_mask[s_fc]).sum(1)
    seg_names = wj.SEGMENTS
    oh_s = np.eye(len(seg_names))[fc.seg_i.to_numpy()]
    sw = fc.segment + ' | ' + fc.week_start.dt.strftime('%Y-%m-%d')
    sw_names = sorted(sw.unique())
    sw_codes = sw.map({n: i for i, n in enumerate(sw_names)}).to_numpy()
    cg = fc.segment + ' | ' + fc.city_group
    cg_names = sorted(cg.unique())
    un_names = sorted(fc.mu_key.unique())
    un_codes = fc.mu_key.map({n: i for i, n in enumerate(un_names)}).to_numpy()

    by_rule = {}
    for rule in [x.strip() for x in a.trend_rules.split(',') if x.strip()]:
        wk = week_terms_rule(ext, W_f, rule)
        mu_fc, media_fc = predict_parts(rows_arr(arr, f_rows, ybar_m, wk, spend_norm_all, wb_all),
                                        d.dims, a.prior_set, samp)
        y_fc = (mu_fc + trend_new[:, :, s_fc, w_fc] + shock_new[:, :, s_fc, w_fc] + path[:, :, m_fc, h_fc])
        T_d = np.exp(y_fc[:, 0] + y_fc[:, 1])                                          # [D, N]
        O_d = np.exp(y_fc[:, 0])
        T_nomedia = np.exp(y_fc[:, 0] + y_fc[:, 1] - media_fc[:, 0] - media_fc[:, 1])
        tag = f'{a.profile}_{rule}'

        rows_out = fc[['segment', 'unit_label', 'mu_key', 'city_group', 'week_start', 'turnover_total', 'orders_cnt',
                       'naive_turnover', 'naive_orders']].copy()
        for kk, v in q(T_d).items():
            rows_out[f'fc_turnover_{kk}'] = v
        rows_out['fc_orders_median'] = np.median(O_d, 0)
        rows_out['fc_turnover_no_ads_median'] = np.median(T_nomedia, 0)
        rows_out['fc_ads_log_effect_median'] = np.median(media_fc[:, 0] + media_fc[:, 1], 0)
        rows_out['fc_media_effect_median'] = np.median(T_d - T_nomedia, 0)
        rows_out.to_csv(out / f'oot_rows_{tag}.csv', index=False)

        t_seg = group_table(fc.seg_i.to_numpy(), seg_names, T_d, O_d, fc, common)
        tot = group_table(np.zeros(len(fc), int), ['Всего'], T_d, O_d, fc, common)
        t_seg = pd.concat([t_seg, tot], ignore_index=True)
        inc = T_d - T_nomedia
        inc_s = np.concatenate([inc @ oh_s, inc.sum(1, keepdims=True)], 1)
        t_seg['media_spend_rub'] = np.append(spend_rub @ oh_s, spend_rub.sum())
        t_seg['media_effect_median'] = np.median(inc_s, 0)
        t_seg['media_effect_pct_of_fc'] = 100 * t_seg.media_effect_median / t_seg.fc_turnover_median
        t_seg.to_csv(out / f'oot_by_segment_{tag}.csv', index=False)
        t_sw = group_table(sw_codes, sw_names, T_d, O_d, fc, common)
        t_sw.to_csv(out / f'oot_by_segment_week_{tag}.csv', index=False)
        t_cg = group_table(cg.map({n: i for i, n in enumerate(cg_names)}).to_numpy(), cg_names, T_d, O_d, fc, common)
        t_cg.to_csv(out / f'oot_by_city_group_{tag}.csv', index=False)
        t_un = group_table(un_codes, un_names, T_d, O_d, fc, common)
        t_un.to_csv(out / f'oot_by_unit_{tag}.csv', index=False)

        full_units = t_un.common_share_of_turnover > 0.999
        z = np.log(fc.turnover_total.to_numpy(float)) - np.log(rows_out.fc_turnover_no_ads_median.to_numpy())
        by_rule[rule] = dict(
            total=t_seg.iloc[-1][['actual_turnover', 'fc_turnover_median', 'fc_turnover_q05', 'fc_turnover_q95',
                                  'err_turnover_pct', 'inside_90', 'err_orders_pct', 'err_check_pct',
                                  'common_share_of_turnover', 'common_err_model_pct', 'common_err_naive_pct',
                                  'media_effect_pct_of_fc']].to_dict(),
            by_segment=t_seg.set_index('group')[['err_turnover_pct', 'inside_90', 'err_orders_pct', 'err_check_pct',
                                                 'common_err_model_pct', 'common_err_naive_pct']].round(2).to_dict('index'),
            segment_week_wape_model=round(wape(t_sw.fc_turnover_median.to_numpy(), t_sw.actual_turnover.to_numpy()), 4),
            segment_week_inside_90=round(float(t_sw.inside_90.mean()), 3),
            segment_week_wape_common_model=round(wape(t_sw.common_fc_turnover_median.to_numpy(),
                                                      t_sw.common_actual_turnover.to_numpy()), 4),
            segment_week_wape_common_naive=round(wape(t_sw.common_naive_turnover.to_numpy(),
                                                      t_sw.common_actual_turnover.to_numpy()), 4),
            unit_wape_model=round(wape(t_un.fc_turnover_median.to_numpy(), t_un.actual_turnover.to_numpy()), 4),
            unit_inside_90=round(float(t_un.inside_90.mean()), 3),
            unit_inside_90_turnover_weighted=round(float((t_un.inside_90 * t_un.actual_turnover).sum()
                                                         / t_un.actual_turnover.sum()), 3),
            units_with_naive_all_weeks=int(full_units.sum()),
            unit_wape_common_model=round(wape(t_un.common_fc_turnover_median[full_units].to_numpy(),
                                              t_un.common_actual_turnover[full_units].to_numpy()), 4),
            unit_wape_common_naive=round(wape(t_un.common_naive_turnover[full_units].to_numpy(),
                                              t_un.common_actual_turnover[full_units].to_numpy()), 4),
            rows_with_naive_share=round(float(common.mean()), 3),
            media_response=media_response(z, rows_out.fc_ads_log_effect_median.to_numpy(), un_codes, sw_codes))
        print(rule, json.dumps(by_rule[rule], ensure_ascii=False, default=str), flush=True)
        print(t_seg.round(3).to_string(), flush=True)

    card |= dict(status='done', checks=checks, by_rule=by_rule, forecast_draws=D,
                 new_trend_knots=[str(d_all.weeks[i].date()) for i in new_idx],
                 week_shock_sd_factor=round(float(np.sqrt(R / W_f)), 3), seconds_total=round(time.time() - t0))
    (out / f'oot_card_{a.profile}_v2.json').write_text(json.dumps(card, ensure_ascii=False, indent=2, default=str))
    print(json.dumps({k: v for k, v in card.items() if k != 'by_rule'}, ensure_ascii=False, indent=1, default=str))

if __name__ == '__main__':
    main()
