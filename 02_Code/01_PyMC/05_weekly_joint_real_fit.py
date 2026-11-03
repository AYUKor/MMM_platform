"""Fourth-pass joint weekly model on the real panel: ROAS by segment and channel with honest intervals.

Same model and the same sampling route as the simulated-world check (04_weekly_joint_sim_check.py, code v6, which
recovered the known ROAS in both worlds on all 621 units on 02.11): mode search from 8 starts by mean-field VI,
chains start at draws from the best start, NUTS. The only difference is the target: the observed log orders and log
average check of panel v3 instead of simulated ones. July-September 2026 are not in the panel and are never read.

Pre-registered stop rules (doc «Новая модель MMM», checks): sampling is skipped if the centre of the best start has
a channel ROAS above --stop-if-roas-above (10); after sampling every segment x channel with median ROAS above 10 or
with a share of the media effect more than 5 times its share of the media spend is flagged in the card.

Outputs (OUTDIR): multistart_{profile}.csv, posterior_roas_params_{profile}.npz, roas_draws_{profile}.csv,
roas_by_segment_channel_{profile}.csv (turnover ROAS q05/median/q95, part through orders, spend, effect, shares),
roas_by_chain_{profile}.csv, fit_card_{profile}.json. Store ads act only on store sales and delivery ads only on
delivery sales (owner 02.11): the tables are per segment; there is no cross-direction channel.

Run: python -I 05_weekly_joint_real_fit.py --panel P.parquet --national N.csv --out OUTDIR
     --profile fast|medium|pilot|production [--prior-set moderate|wide] [--fit-window-end YYYY-MM-DD]
     [--inject "Нац_ТВ=2,..."]   (injection check: real data plus a known effect; the fit must find it on top)
"""
from __future__ import annotations

import argparse
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

CODE_VERSION = 'v12_real_geo_check_20261103'

PROFILES = {
    'fast': dict(top_units=20, chains=2, warmup=300, draws=300, target_accept=0.90, max_tree_depth=8),
    'medium': dict(top_units=20, chains=4, warmup=1000, draws=1000, target_accept=0.99, max_tree_depth=10),
    'pilot': dict(top_units=None, chains=2, warmup=1000, draws=1000, target_accept=0.99, max_tree_depth=10),
    'production': dict(top_units=None, chains=4, warmup=2000, draws=2000, target_accept=0.99, max_tree_depth=10),
}
FLAG_ROAS_ABOVE = 10.0
FLAG_EFFECT_TO_SPEND_SHARE = 5.0


def roas_draws(d, arr, samples, turnover, n_chains, n_draws=200) -> pd.DataFrame:
    total = samples['alpha'].shape[0]
    per_chain = total // n_chains                      # get_samples() stacks the chains one after another
    idx = np.linspace(0, total - 1, min(n_draws, total)).astype(int)
    tabs = []
    for i in idx:
        draw = {k: np.asarray(samples[k][i]) for k in wj.roas_keys(arr)}
        t = wj.roas_from_contrib(d, arr, wj.media_contrib_draw(arr, draw), turnover)
        tabs.append(t.assign(draw=i, chain=i // per_chain))
    return pd.concat(tabs)


def roas_by_tier(d, arr, point, turnover) -> dict:
    """Turnover ROAS at a point by segment, channel and city size group (Moscow and SPb apart): how ROAS varies by geo."""
    contrib = wj.media_contrib_draw(arr, {k: np.asarray(point[k]) for k in wj.roas_keys(arr)})
    a_i, w_i = arr['a_i'], arr['w_i']
    tot = contrib[0][a_i, w_i, :] + contrib[1][a_i, w_i, :]
    inc = turnover[:, None] * (1 - np.exp(-tot))
    spend = d.spend_pr[a_i, w_i, :] * (d.ad_units.pop_k.to_numpy()[a_i] * 1000)[:, None]
    lab = d.ad_units.unit_label.to_numpy()[a_i]
    tier = d.ad_units.tier.fillna('other').astype(str).to_numpy()[a_i]
    grp = np.where(np.isin(lab, ['МОСКВА', 'САНКТ-ПЕТЕРБУРГ']), lab, tier)
    out = {}
    for s, sname in enumerate(wj.SEGMENTS):
        for g in np.unique(grp[arr['s_i'] == s]):
            sel = (arr['s_i'] == s) & (grp == g)
            for j, c in enumerate(wj.CHANNELS):
                sp = spend[sel, j].sum()
                if sp > 0 and d.chan_mask[s, j]:
                    out[f'{sname}|{c}|{g}'] = round(float(inc[sel, j].sum() / sp), 2)
    return out


def roas_at_point(d, arr, point, turnover) -> pd.DataFrame:
    return wj.roas_from_contrib(d, arr, wj.media_contrib_draw(arr, {k: np.asarray(point[k]) for k in wj.roas_keys(arr)}),
                                turnover)


def segment_table(est: pd.DataFrame, turnover_by_seg: pd.Series) -> pd.DataFrame:
    est = est.assign(roas_orders=est.effect_orders_rub / est.spend_rub)
    g = est.groupby(['segment', 'channel'])
    q = g.roas.quantile([0.05, 0.5, 0.95]).unstack()
    q.columns = ['roas_q05', 'roas_median', 'roas_q95']
    t = q.join(g.roas_orders.median().rename('roas_orders_part_median'))
    t = t.join(g.spend_rub.first().rename('spend_rub')).join(g.effect_rub.median().rename('effect_rub_median'))
    t = t.reset_index()
    t['turnover_rub'] = t.segment.map(turnover_by_seg)
    t['effect_pct_of_turnover'] = 100 * t.effect_rub_median / t.turnover_rub
    seg_spend = t.groupby('segment').spend_rub.transform('sum')
    seg_eff = t.groupby('segment').effect_rub_median.transform('sum')
    t['spend_share'] = t.spend_rub / seg_spend
    t['effect_share'] = t.effect_rub_median / seg_eff
    t['flag'] = np.where(t.roas_median > FLAG_ROAS_ABOVE, f'roas_above_{FLAG_ROAS_ABOVE:g}',
                         np.where(t.effect_share > FLAG_EFFECT_TO_SPEND_SHARE * t.spend_share,
                                  f'effect_share_above_{FLAG_EFFECT_TO_SPEND_SHARE:g}x_spend_share', ''))
    return t


INJECT_ALPHA = {'Нац_ТВ': 0.6, 'Рег_ТВ': 0.5, 'Радио': 0.4, 'OOH_Total': 0.4, 'Digital_Performance': 0.2,
                wj.NATIONAL_TV_CROSS: 0.6}          # same carry-over as the simulated worlds


def parse_inject(spec: str) -> tuple[dict, dict]:
    """'Нац_ТВ=2,OOH_Total=2@0.85' -> ROAS through orders by channel and the decay of each (default INJECT_ALPHA;
    '@a' gives a slow effect with decay a)."""
    roas, alpha = {}, {}
    for kv in spec.split(','):
        k, v = kv.split('=')
        r, _, al = v.partition('@')
        roas[k.strip()] = float(r)
        if al:
            alpha[k.strip()] = float(al)
    bad = set(roas) - set(wj.CHANNELS)
    if bad:
        raise SystemExit(f'unknown channels in --inject: {sorted(bad)}')
    return roas, alpha


def injection_contrib(arr: dict, spec: str) -> np.ndarray:
    """Per-channel log contributions [2, A, W, C] of an injection; the same for every model (zero spend before the
    panel; 26-week window when a slow decay is given, 8 weeks otherwise)."""
    inj, al = parse_inject(spec)
    S, C, A = len(wj.SEGMENTS), len(wj.CHANNELS), len(arr['tau_a'])
    draw = dict(alpha=np.array([al.get(c, INJECT_ALPHA[c]) for c in wj.CHANNELS]), lam=np.ones(C),
                logR_orders=np.log([max(inj.get(c, 0.0), 1e-12) for c in wj.CHANNELS]),
                sig_seg=0.0, z_seg=np.zeros((S, C)), sig_tier=0.0, z_tier=np.zeros((3, C)), sig_unit=0.0,
                z_unit=np.zeros((A, C)), R_check=np.zeros((S, C)))
    arr_inj = dict(arr, adstock_l=wj.ADSTOCK_L_LONG if al else wj.ADSTOCK_L, adstock_pad_steady=False,
                   roas_scale='equal')                                          # the same injection for every model
    contrib = wj.media_contrib_draw(arr_inj, draw)
    keep = np.array([c in inj for c in wj.CHANNELS], dtype=float)
    return contrib * keep[None, None, None, :]


def inject_effect(d, arr, y: np.ndarray, spec: str, truth_path: Path) -> np.ndarray:
    """Real targets plus a known media effect on log orders; writes the injected turnover ROAS by segment."""
    inj, _ = parse_inject(spec)
    contrib = injection_contrib(arr, spec)                                       # [2, A, W, C]
    y = y.copy()
    y[0] = y[0] + contrib[0].sum(-1)[arr['a_i'], arr['w_i']]
    truth = wj.roas_from_contrib(d, arr, contrib, np.exp(y[0] + y[1]))
    truth[truth.channel.isin(list(inj))].to_csv(truth_path, index=False)
    return y


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--panel', required=True)
    ap.add_argument('--national', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--profile', default='fast', choices=list(PROFILES))
    ap.add_argument('--seed', type=int, default=20261102)
    ap.add_argument('--prior-set', default='moderate', choices=list(wj.PRIOR_SETS))
    ap.add_argument('--fit-window-end', default=None, help='last week_start in the fit (holdout check); default all')
    ap.add_argument('--chain-method', default='vectorized', choices=['sequential', 'parallel', 'vectorized'])
    ap.add_argument('--starts', type=int, default=8)
    ap.add_argument('--vi-steps', type=int, default=15000)
    ap.add_argument('--stop-if-roas-above', type=float, default=10.0)
    ap.add_argument('--jitter', type=float, default=0.05)
    ap.add_argument('--no-city-wave', action='store_true', help='fit the v6 model (no own yearly wave per unit)')
    ap.add_argument('--wave-param', default='centred', choices=['centred', 'noncentred'],
                    help='coordinates of the own city waves (v7 = noncentred, v7b = centred); same model')
    ap.add_argument('--slope-param', default='noncentred', choices=['centred', 'noncentred'],
                    help='coordinates of the unit slopes; same model')
    ap.add_argument('--wave-scale', default='learned', choices=['learned', 'fixed'],
                    help='spread of the own city waves: learned (v7/v7b) or fixed from the data being fitted (v7c)')
    ap.add_argument('--adstock', default='short', choices=['short', 'long'],
                    help='short: 8-week window (v6/v7); long: 26-week window and the pre-panel weeks filled with early mean spend (v8); both use the industry decay priors')
    ap.add_argument('--anchor', default='', help='v10: industry yardstick on the realized turnover ROAS of each channel, SET:SD, e.g. moderate:0.3 (use with --prior-set wide); v11: SET:SD:segment puts it on each segment x channel')
    ap.add_argument('--media-geo', default='unit', choices=['unit', 'tier'], help='v12: unit = own ROAS deviation per city (v6-v11), tier = cities differ only by size tier and spend per resident; the same as the fit')
    ap.add_argument('--check-sd', type=float, default=0.5, help='v12: prior scale of the ROAS through the average check, Normal(0, SD) (v6-v11: 0.5)')
    ap.add_argument('--weaken', default='', help='v9: weaken baseline parts that take the ad effect, e.g. "rho=2:2,slope=0.1,wave=0.5,season=0.15" (rho prior Beta(a,b), default 8:2; unit-slope spread prior 0.2; own-wave spread multiplier 1; season prior 0.3)')
    ap.add_argument('--roas-scale', default='equal', choices=['equal', 'turnover', 'gamma'],
                    help='city ROAS = R * (turnover per resident / segment median) ** g: equal g=0 (v6/v7), turnover g=1, '
                         'gamma g learned (v8 options)')
    ap.add_argument('--placebo', default='',
                    help='placebo check: shift:K (spend K weeks later, circular) or swap:SEED (spend of another unit of '
                         'the segment); the fit should find ROAS near zero')
    ap.add_argument('--inject', default='',
                    help='injection check: add a known effect to the real orders, e.g. "Нац_ТВ=2,Digital_Performance=2" '
                         '(ROAS through orders at typical spend; no city deviations, no check part). The fit should find '
                         'its plain real ROAS plus about the injected amount; the truth is in injected_truth_{profile}.csv')
    a = ap.parse_args()
    prof = PROFILES[a.profile]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    import jax
    import numpyro
    from numpyro.infer import MCMC, NUTS
    from numpyro.infer.initialization import init_to_median
    numpyro.set_host_device_count(prof['chains'])

    t0 = time.time()
    d = wj.prepare(a.panel, a.national, fit_window_end=a.fit_window_end, top_units_per_segment=prof['top_units'])
    if a.placebo:
        if a.inject:
            raise SystemExit('--placebo and --inject together are not a check of anything')
        d = wj.placebo_spend(d, a.placebo)
    arr = wj.model_arrays(d, city_wave=not a.no_city_wave, wave_centred=a.wave_param == 'centred',
                           slope_centred=a.slope_param == 'centred', wave_scale=a.wave_scale,
                           adstock=a.adstock, roas_scale=a.roas_scale, weaken=a.weaken, anchor=a.anchor,
                           media_geo=a.media_geo, check_sd=a.check_sd)
    o = d.obs
    y = np.vstack([o.y_orders.to_numpy(float), o.y_check.to_numpy(float)])
    if a.inject:
        y = inject_effect(d, arr, y, a.inject, out / f'injected_truth_{a.profile}.csv')
    arr = wj.with_fixed_wave_scale(d, wj.with_targets(arr, y), y)
    turnover = np.exp(y[0] + y[1])
    turnover_by_seg = pd.Series(turnover).groupby(pd.Series(arr['s_i']).map(dict(enumerate(wj.SEGMENTS)))).sum()
    if 'wave_sd_fixed' in arr:
        print('fixed own-wave spread [orders; check] x segments', np.round(arr['wave_sd_fixed'], 4).tolist(), flush=True)
    print('dims', d.dims, 'weeks', str(d.weeks[0].date()), '-', str(o.week_start.max().date()),
          f'prep {time.time()-t0:.0f}s', flush=True)

    init_params, ms_card = None, None
    if a.starts > 0:
        t_ms = time.time()
        starts = wj.multi_start_vi(arr, d.dims, a.prior_set, y, n_starts=a.starts, steps=a.vi_steps, seed=a.seed)
        rows = []
        for st in starts:
            r = pd.Series(dtype=float)
            if st['finite']:
                g = roas_at_point(d, arr, st['point'], turnover).groupby('channel')[['effect_rub', 'spend_rub']].sum()
                r = g.effect_rub / g.spend_rub
            rows.append(dict(start=st['start'], init=st['init'], loss=st['loss'], loss_at_75pct=st['loss_at_75pct'],
                             finite=st['finite']) | {f'roas_{c}': r.get(c, np.nan) for c in wj.CHANNELS})
        ms = pd.DataFrame(rows)
        ms['loss_minus_best'] = ms.loss - ms.loss[ms.finite].min()
        ms.to_csv(out / f'multistart_{a.profile}.csv', index=False)
        ib = int(ms.loss.where(ms.finite).idxmin())
        best = starts[ib]
        init_params = wj.init_params_from(best, prof['chains'], jitter=a.jitter, seed=a.seed)
        best_seg = roas_at_point(d, arr, best['point'], turnover)
        best_roas = ms.loc[ib, [f'roas_{c}' for c in wj.CHANNELS]].astype(float)
        ms_card = dict(seconds=round(time.time() - t_ms), steps=a.vi_steps, best_start=best['start'],
                       loss_minus_best=ms.loss_minus_best.round(1).tolist(),
                       settled=(ms.loss_at_75pct - ms.loss).round(1).tolist(),
                       best_start_roas=best_roas.round(2).to_dict(),
                       best_start_roas_by_segment={f'{r.segment}|{r.channel}': round(float(r.roas), 2)
                                                   for r in best_seg.itertuples()},
                       best_start_loss=round(float(best['loss']), 1),
                       best_start_point={k: np.round(np.asarray(best['point'][k], float), 3).tolist()
                                         for k in ('alpha', 'lam', 'gamma_geo', 'logR_orders', 'rho', 'sig_week', 'sig_slope', 'tau_trend')
                                         if k in best['point']},
                       best_start_roas_by_size_tier=roas_by_tier(d, arr, best['point'], turnover))
        print('start search', json.dumps(ms_card, ensure_ascii=False, default=str), flush=True)
        print(ms.round(2).to_string(), flush=True)
        if (best_seg.roas > a.stop_if_roas_above).any():
            card = dict(profile=a.profile, status='stopped_start_roas_above_rule', code_version=CODE_VERSION,
                        stop_if_roas_above=a.stop_if_roas_above, mode_search=ms_card, dims=d.dims,
                        inject=a.inject, placebo=a.placebo, prior_set=a.prior_set, adstock=a.adstock, roas_scale=a.roas_scale,
                        weaken=a.weaken, anchor=a.anchor, media_geo=a.media_geo, check_sd=a.check_sd)
            (out / f'start_stopped_{a.profile}.json').write_text(json.dumps(card, ensure_ascii=False, indent=2, default=str))
            print('STOPPED: the centre of the best start breaks the ROAS stop rule, sampling skipped', flush=True)
            return

    kernel = NUTS(wj.numpyro_model, target_accept_prob=prof['target_accept'], max_tree_depth=prof['max_tree_depth'],
                  init_strategy=init_to_median(num_samples=15))
    mcmc = MCMC(kernel, num_warmup=prof['warmup'], num_samples=prof['draws'], num_chains=prof['chains'],
                chain_method=a.chain_method, progress_bar=False)
    t1 = time.time()
    mcmc.run(jax.random.PRNGKey(a.seed), arr, d.dims, a.prior_set, y=y, init_params=init_params,
             extra_fields=('diverging', 'potential_energy', 'num_steps'))
    samples = mcmc.get_samples()
    jax.block_until_ready(samples)
    fit_s = time.time() - t1
    extra = mcmc.get_extra_fields(group_by_chain=True)
    from numpyro.diagnostics import summary
    by_chain = mcmc.get_samples(group_by_chain=True)
    summ = summary(by_chain, group_by_chain=True)
    rh = {k: float(np.nanmax(v['r_hat'])) for k, v in summ.items()}
    ess = {k: float(np.nanmin(v['n_eff'])) for k, v in summ.items()}
    np.savez_compressed(out / f'posterior_roas_params_{a.profile}.npz',
                        **{k: np.asarray(by_chain[k], dtype=np.float32) for k in wj.roas_keys(arr)},
                        potential_energy=np.asarray(extra['potential_energy'], dtype=np.float32),
                        num_steps=np.asarray(extra['num_steps'], dtype=np.int32))

    est = roas_draws(d, arr, samples, turnover, prof['chains'])
    est.to_csv(out / f'roas_draws_{a.profile}.csv', index=False)
    seg = segment_table(est, turnover_by_seg)
    seg.to_csv(out / f'roas_by_segment_channel_{a.profile}.csv', index=False)
    per_chain = est.groupby(['segment', 'channel', 'chain']).roas.median().unstack('chain')
    per_chain.columns = [f'chain{c}' for c in per_chain.columns]
    per_chain.to_csv(out / f'roas_by_chain_{a.profile}.csv')
    card = dict(profile=a.profile, chain_method=a.chain_method, prior_set=a.prior_set, dims=d.dims,
                fit_window_end=a.fit_window_end, inject=a.inject, placebo=a.placebo, adstock=a.adstock, roas_scale=a.roas_scale, weaken=a.weaken, anchor=a.anchor, media_geo=a.media_geo, check_sd=a.check_sd, warmup=prof['warmup'], draws=prof['draws'], chains=prof['chains'],
                fit_seconds=round(fit_s), divergences=int(np.asarray(extra['diverging']).sum()),
                code_version=CODE_VERSION, city_wave_model=not a.no_city_wave, wave_param=a.wave_param, slope_param=a.slope_param, wave_scale=a.wave_scale,
                wave_sd_fixed=(np.asarray(arr['wave_sd_fixed']).round(4).tolist() if 'wave_sd_fixed' in arr else None), mode_search=ms_card,
                chains_stats=dict(potential_energy_mean=np.asarray(extra['potential_energy']).mean(1).round(1).tolist(),
                                  num_steps_mean=np.asarray(extra['num_steps']).mean(1).round(1).tolist(),
                                  divergences=np.asarray(extra['diverging']).sum(1).astype(int).tolist()),
                max_r_hat_roas_params={k: round(rh[k], 3) for k in wj.roas_keys(arr)},
                max_r_hat={k: round(v, 3) for k, v in sorted(rh.items(), key=lambda x: -x[1])[:8]},
                min_ess={k: round(v) for k, v in sorted(ess.items(), key=lambda x: x[1])[:8]},
                flags=seg.loc[seg.flag != '', ['segment', 'channel', 'roas_median', 'flag']].to_dict('records'),
                rho_post=np.asarray(samples['rho']).mean(0).round(3).tolist(),
                sigma_post=np.asarray(samples['sigma']).mean(0).round(4).tolist(),
                alpha_post=np.asarray(samples['alpha']).mean(0).round(3).tolist(),
                lam_post=np.asarray(samples['lam']).mean(0).round(3).tolist(),
                sig_week_post=np.asarray(samples['sig_week']).mean(0).round(4).tolist())
    (out / f'fit_card_{a.profile}.json').write_text(json.dumps(card, ensure_ascii=False, indent=2, default=str))
    print(json.dumps(card, ensure_ascii=False, indent=1, default=str))
    print(seg.round(3).to_string())
    print(per_chain.round(2).to_string())


if __name__ == '__main__':
    main()
