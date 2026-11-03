"""Which units carry a channel's ROAS: per-unit media effect from a fitted weekly joint model (no sampling).

Reads the posterior draws saved by 05_weekly_joint_real_fit.py (posterior_roas_params_{profile}.npz), recomputes
the turnover effect of every channel in every ad unit for a thinned set of draws, and writes one row per
segment x channel x unit with spend, effect, ROAS (q05 / median / q95), the unit's ROAS through orders and its city
deviation, plus two data facts that can fake an ad effect: the unit's turnover growth over the fit window (last
13 vs first 13 fit weeks) and the correlation of its weekly spend with its log turnover.

Run: python -I 06_weekly_joint_unit_effects.py --panel P.parquet --national N.csv --npz posterior.npz --out OUTDIR
     [--draws 200] [--show "ТС5/Оффлайн|OOH_Total,ТС5/Онлайн|Digital_Performance"]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))     # run with python -I: the script folder is not on the path

import numpy as np
import pandas as pd

from mmm_core import weekly_joint as wj


def unit_facts(d, arr, turnover) -> pd.DataFrame:
    o = d.obs.assign(T=turnover, a_i=arr['a_i'])
    o = o.sort_values(['a_i', 'week_start'])
    g = o.groupby('a_i')
    first = g.T.apply(lambda s: s.head(13).mean())
    last = g.T.apply(lambda s: s.tail(13).mean())
    return pd.DataFrame({'turnover_growth': last / first - 1, 'fit_weeks': g.size()})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--panel', required=True)
    ap.add_argument('--national', required=True)
    ap.add_argument('--npz', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--draws', type=int, default=200)
    ap.add_argument('--top-units', type=int, default=None, help='same as the fit (fast/medium: 20); pilot/production: all')
    ap.add_argument('--adstock', default='short', choices=['short', 'long'], help='the same as the fit')
    ap.add_argument('--roas-scale', default='equal', choices=['equal', 'turnover', 'gamma'], help='the same as the fit')
    ap.add_argument('--media-geo', default='unit', choices=['unit', 'tier'], help='v12: unit = own ROAS deviation per city (v6-v11), tier = cities differ only by size tier and spend per resident; the same as the fit')
    ap.add_argument('--show', default='ТС5/Оффлайн|OOH_Total,ТС5/Онлайн|Digital_Performance,ТСХ/Оффлайн|Рег_ТВ')
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    d = wj.prepare(a.panel, a.national, top_units_per_segment=a.top_units)
    arr = wj.model_arrays(d, adstock=a.adstock, roas_scale=a.roas_scale, media_geo=a.media_geo)
    o = d.obs
    y = np.vstack([o.y_orders.to_numpy(float), o.y_check.to_numpy(float)])
    turnover = np.exp(y[0] + y[1])
    a_i, w_i = arr['a_i'], arr['w_i']
    A, C = len(d.ad_units), len(wj.CHANNELS)
    pop = d.ad_units.pop_k.to_numpy()[a_i] * 1000
    spend_n = d.spend_pr[a_i, w_i, :] * pop[:, None]                                  # [N, C]
    spend_u = np.stack([np.bincount(a_i, spend_n[:, j], minlength=A) for j in range(C)], 1)   # [A, C]
    logT = np.log(turnover)
    corr = np.full((A, C), np.nan)
    for u in range(A):
        m = a_i == u
        for j in range(C):
            x = spend_n[m, j]
            if m.sum() > 5 and x.std() > 0:
                corr[u, j] = np.corrcoef(x, logT[m])[0, 1]

    post = np.load(a.npz)
    flat = {k: post[k].reshape((-1,) + post[k].shape[2:]) for k in wj.roas_keys(arr)}
    n = flat['alpha'].shape[0]
    idx = np.linspace(0, n - 1, min(a.draws, n)).astype(int)
    eff = np.zeros((len(idx), A, C))
    r_orders = np.zeros((len(idx), A, C))
    for t, i in enumerate(idx):
        draw = {k: np.asarray(flat[k][i]) for k in wj.roas_keys(arr)}
        contrib = wj.media_contrib_draw(arr, draw)                                    # [2, A, W, C]
        c = contrib[0][a_i, w_i, :] + contrib[1][a_i, w_i, :]
        inc = turnover[:, None] * (1 - np.exp(-c))
        eff[t] = np.stack([np.bincount(a_i, inc[:, j], minlength=A) for j in range(C)], 1)
        logR_s = draw['logR_orders'][None, :] + draw['sig_seg'] * draw['z_seg']
        r_orders[t] = np.exp(logR_s[arr['seg_a']] + draw['sig_tier'] * draw['z_tier'][arr['tier_a']]
                             + draw['sig_unit'] * draw['z_unit'] * arr['local_c'][None, :])

    facts = unit_facts(d, arr, turnover)
    rows = []
    for u in range(A):
        s = int(d.ad_units.seg_i.iloc[u])
        for j, ch in enumerate(wj.CHANNELS):
            if spend_u[u, j] <= 0 or d.chan_mask[s, j] == 0:
                continue
            e = eff[:, u, j]
            rows.append(dict(segment=wj.SEGMENTS[s], channel=ch, unit=d.ad_units.unit_label.iloc[u],
                             tier=d.ad_units.tier.iloc[u], spend_mln=spend_u[u, j] / 1e6,
                             effect_mln_median=np.median(e) / 1e6, roas_q05=np.quantile(e, 0.05) / spend_u[u, j],
                             roas_median=np.median(e) / spend_u[u, j], roas_q95=np.quantile(e, 0.95) / spend_u[u, j],
                             roas_orders_unit_median=np.median(r_orders[:, u, j]),
                             turnover_growth=facts.turnover_growth.get(u, np.nan), corr_spend_logturnover=corr[u, j]))
    t = pd.DataFrame(rows)
    seg_eff = t.groupby(['segment', 'channel']).effect_mln_median.transform('sum')
    t['effect_share_in_segment_channel'] = t.effect_mln_median / seg_eff
    t = t.sort_values(['segment', 'channel', 'effect_mln_median'], ascending=[True, True, False])
    t.to_csv(out / 'unit_effects.csv', index=False)

    summ = []
    for (s, ch), g in t.groupby(['segment', 'channel']):
        g = g.sort_values('effect_mln_median', ascending=False)
        tot_e, tot_s = g.effect_mln_median.sum(), g.spend_mln.sum()
        top5 = g.head(5)
        rest = g.iloc[5:]
        summ.append(dict(segment=s, channel=ch, units=len(g), roas_all=tot_e / tot_s,
                         top5_effect_share=top5.effect_mln_median.sum() / tot_e if tot_e else np.nan,
                         top5_spend_share=top5.spend_mln.sum() / tot_s,
                         roas_without_top5=rest.effect_mln_median.sum() / rest.spend_mln.sum() if len(rest) else np.nan,
                         top5_units=', '.join(top5.unit)))
    summ = pd.DataFrame(summ)
    summ.to_csv(out / 'unit_effects_summary.csv', index=False)
    pd.set_option('display.width', 250)
    print(summ.round(3).to_string())
    for key in [k for k in a.show.split(',') if k]:
        s, ch = key.split('|')
        g = t[(t.segment == s) & (t.channel == ch)].head(15)
        print(f'\n{s} | {ch}: top units by effect')
        print(g.drop(columns=['segment', 'channel']).round(3).to_string(index=False))


if __name__ == '__main__':
    main()
