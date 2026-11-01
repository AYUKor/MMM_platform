"""Check 1 of the fourth-pass model: a simulated world with known ROAS on real spend, units and weeks.

Builds targets from the joint weekly model (mmm_core/weekly_joint.py) with known ROAS, fits the same model with
the owner's moderate priors and compares the recovered turnover ROAS with the truth, per channel and per
segment. Two worlds: A (TV 1, regional TV 3, radio 1, OOH 5, digital 3) and B (TV 5, regional TV 1, radio 3,
OOH 1, digital 5), so it shows whether the model tells 1 from 5 on our data.

Run: python -I 04_weekly_joint_sim_check.py --panel P.parquet --national N.csv --out OUTDIR [--world A|B]
     [--warmup 500 --draws 500 --chains 4]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault('XLA_FLAGS', '--xla_force_host_platform_device_count=4')
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

from mmm_core import weekly_joint as wj

WORLDS = {
    'A': {'Нац_ТВ': 1.0, 'Рег_ТВ': 3.0, 'Радио': 1.0, 'OOH_Total': 5.0, 'Digital_Performance': 3.0},
    'B': {'Нац_ТВ': 5.0, 'Рег_ТВ': 1.0, 'Радио': 3.0, 'OOH_Total': 1.0, 'Digital_Performance': 5.0},
}


def truth_for(world: str, sig_week: tuple[float, float]) -> dict:
    r = WORLDS[world] | {wj.NATIONAL_TV_CROSS: 0.3}
    check = {c: 0.0 for c in wj.CHANNELS} | {'Нац_ТВ': 0.2}
    return dict(R_orders=r, R_check=check,
                alpha={'Нац_ТВ': 0.6, 'Рег_ТВ': 0.5, 'Радио': 0.4, 'OOH_Total': 0.4, 'Digital_Performance': 0.2,
                       wj.NATIONAL_TV_CROSS: 0.6},
                lam={c: 1.0 for c in wj.CHANNELS}, unit_sd=0.3, rho=(0.84, 0.64), sigma=(0.045, 0.02),
                sig_week=sig_week, b_check_on_orders=-0.3)


def real_week_noise(d: wj.ModelData) -> tuple[float, float]:
    """Robust sd of the segment-week mean of unit-demeaned log target around its 5-week smooth (real data)."""
    o = d.obs
    out = []
    for col in ['y_orders', 'y_check']:
        dm = o[col] - o.groupby('m_i')[col].transform('mean')
        sw = dm.groupby([o.seg_i, o.w_i]).mean().unstack(0).sort_index()
        dev = sw - sw.rolling(5, center=True, min_periods=1).mean()
        # robust sd (MAD): holiday spikes are modelled by dummies and should not inflate the week noise
        out.append(float((1.4826 * (dev - dev.median()).abs().median()).mean()))
    return out[0], out[1]


def summarize(d, arr, samples, turnover, n_draws=200) -> pd.DataFrame:
    keys = ['alpha', 'lam', 'logR_orders', 'sig_seg', 'z_seg', 'sig_tier', 'z_tier', 'sig_unit', 'z_unit', 'R_check']
    total = samples['alpha'].shape[0]
    idx = np.linspace(0, total - 1, min(n_draws, total)).astype(int)
    tabs = []
    for i in idx:
        draw = {k: np.asarray(samples[k][i]) for k in keys}
        t = wj.roas_from_contrib(d, arr, wj.media_contrib_draw(arr, draw), turnover)
        tabs.append(t.assign(draw=i))
    return pd.concat(tabs)


def by_channel(t: pd.DataFrame) -> pd.DataFrame:
    g = t.groupby(['draw', 'channel'] if 'draw' in t else ['channel'])[['effect_rub', 'spend_rub']].sum()
    return (g.effect_rub / g.spend_rub).rename('roas').reset_index()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--panel', required=True)
    ap.add_argument('--national', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--world', default='A', choices=list(WORLDS))
    ap.add_argument('--warmup', type=int, default=500)
    ap.add_argument('--draws', type=int, default=500)
    ap.add_argument('--chains', type=int, default=4)
    ap.add_argument('--seed', type=int, default=20261102)
    ap.add_argument('--prior-set', default='moderate', choices=list(wj.PRIOR_SETS))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    import jax
    import numpyro
    from numpyro.infer import MCMC, NUTS
    numpyro.set_host_device_count(a.chains)

    t0 = time.time()
    d = wj.prepare(a.panel, a.national)
    arr = wj.model_arrays(d)
    sw = real_week_noise(d)
    truth = truth_for(a.world, sw)
    y, tr = wj.simulate(d, arr, truth, seed=a.seed)
    arr_s = wj.with_targets(arr, y)
    print('dims', d.dims, 'real week noise', sw, f'prep {time.time()-t0:.0f}s', flush=True)

    kernel = NUTS(wj.numpyro_model, target_accept_prob=0.85, max_tree_depth=8)
    mcmc = MCMC(kernel, num_warmup=a.warmup, num_samples=a.draws, num_chains=a.chains, chain_method='parallel',
                progress_bar=False)
    t1 = time.time()
    mcmc.run(jax.random.PRNGKey(a.seed), arr_s, d.dims, a.prior_set, y=y)
    fit_s = time.time() - t1
    samples = mcmc.get_samples()
    extra = mcmc.get_extra_fields()
    div = int(np.asarray(extra['diverging']).sum())
    from numpyro.diagnostics import summary
    summ = summary(mcmc.get_samples(group_by_chain=True), group_by_chain=True)
    rh = {k: float(np.nanmax(v['r_hat'])) for k, v in summ.items()}
    ess = {k: float(np.nanmin(v['n_eff'])) for k, v in summ.items()}

    est = summarize(d, arr_s, samples, tr['turnover'])
    est.to_csv(out / f'roas_draws_world{a.world}.csv', index=False)
    true_seg = tr['roas']
    true_ch = by_channel(true_seg.assign(draw=0)).drop(columns='draw')
    q = by_channel(est).groupby('channel').roas.quantile([0.05, 0.5, 0.95]).unstack()
    q.columns = ['q05', 'median', 'q95']
    res = true_ch.rename(columns={'roas': 'true'}).merge(q.reset_index(), on='channel')
    res['inside_90'] = (res.true >= res.q05) & (res.true <= res.q95)
    qs = est.groupby(['segment', 'channel']).roas.quantile([0.05, 0.5, 0.95]).unstack()
    qs.columns = ['q05', 'median', 'q95']
    res_seg = true_seg[['segment', 'channel', 'roas', 'spend_rub']].rename(columns={'roas': 'true'}).merge(
        qs.reset_index(), on=['segment', 'channel'])
    res_seg['inside_90'] = (res_seg.true >= res_seg.q05) & (res_seg.true <= res_seg.q95)
    res.to_csv(out / f'recovery_by_channel_world{a.world}.csv', index=False)
    res_seg.to_csv(out / f'recovery_by_segment_channel_world{a.world}.csv', index=False)
    card = dict(world=a.world, truth=truth | {'sig_week': list(sw)}, prior_set=a.prior_set, dims=d.dims,
                warmup=a.warmup, draws=a.draws, chains=a.chains, fit_seconds=round(fit_s), divergences=div,
                max_r_hat={k: round(v, 3) for k, v in sorted(rh.items(), key=lambda x: -x[1])[:8]},
                min_ess={k: round(v) for k, v in sorted(ess.items(), key=lambda x: x[1])[:8]},
                rho_post=np.asarray(samples['rho']).mean(0).round(3).tolist(),
                alpha_post=np.asarray(samples['alpha']).mean(0).round(3).tolist(),
                lam_post=np.asarray(samples['lam']).mean(0).round(3).tolist(),
                sig_week_post=np.asarray(samples['sig_week']).mean(0).round(4).tolist())
    (out / f'sim_card_world{a.world}.json').write_text(json.dumps(card, ensure_ascii=False, indent=2, default=str))
    print(json.dumps(card, ensure_ascii=False, indent=1, default=str))
    print(res.round(2).to_string())
    print(res_seg.round(2).to_string())


if __name__ == '__main__':
    main()
