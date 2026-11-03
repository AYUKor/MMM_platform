"""Average and marginal turnover ROAS of a fitted weekly joint model, with the saturation it implies (no sampling).

Average ROAS = turnover effect of all the channel's money / that money (the model table). Marginal ROAS = extra
turnover from one more percent of the channel's money in every unit-week / that percent (what the optimizer and a
leave-one-out campaign see). Last-10% ROAS = turnover lost when the channel's money is cut by 10% / that 10%.
An always-on channel can have an average ROAS near the industry level and a marginal ROAS near zero: the model then
carries it as a constant block of sales that no single campaign moves (deep saturation). Also per channel: the
posterior of lam and alpha, the mean saturation and the mean adstocked spend over lam on the unit-weeks with spend.

Per segment x channel and per city size group (Moscow and SPb apart). Ranges = 5th / 50th / 95th percentile over draws.

Run: python -I 11_weekly_joint_marginal_roas.py --panel P.parquet --national N.csv --npz posterior_roas_params_X.npz
     --out OUTDIR [--draws 200] [--media-geo unit|tier] [--adstock short] [--roas-scale equal] [--top-units N]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))     # run with python -I: the script folder is not on the path

import numpy as np
import pandas as pd

from mmm_core import weekly_joint as wj

CODE_VERSION = 'marginal_roas_weekly_joint_v1_20261103'
BUMP = 0.01
CUT = 0.10


def contrib(arr: dict, draw: dict, scale: float, a_i, w_i) -> np.ndarray:
    """[N, C] log contribution (orders + check) of each channel on the fit rows, its money scaled by `scale` everywhere."""
    a2 = dict(arr)
    a2['spend_norm'] = arr['spend_norm'] * scale
    c = wj.media_contrib_draw(a2, draw)
    return c[0][a_i, w_i, :] + c[1][a_i, w_i, :]


def main() -> None:
    ap = argparse.ArgumentParser()
    for x in ('--panel', '--national', '--npz', '--out'):
        ap.add_argument(x, required=True)
    ap.add_argument('--draws', type=int, default=200)
    ap.add_argument('--top-units', type=int, default=None, help='same as the fit (fast/medium: 20); pilot/production: all')
    ap.add_argument('--adstock', default='short', choices=['short', 'long'], help='the same as the fit')
    ap.add_argument('--roas-scale', default='equal', choices=['equal', 'turnover', 'gamma'], help='the same as the fit')
    ap.add_argument('--media-geo', default='unit', choices=['unit', 'tier'], help='the same as the fit')
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    d = wj.prepare(a.panel, a.national, top_units_per_segment=a.top_units)
    arr = wj.model_arrays(d, adstock=a.adstock, roas_scale=a.roas_scale, media_geo=a.media_geo)
    a_i, w_i, s_i = arr['a_i'], arr['w_i'], arr['s_i']
    T = d.obs.turnover_total.to_numpy(float)
    spend = d.spend_pr[a_i, w_i, :] * (d.ad_units.pop_k.to_numpy()[a_i] * 1000.0)[:, None]
    lab = d.ad_units.unit_label.to_numpy()[a_i]
    tier = d.ad_units.tier.fillna('other').astype(str).to_numpy()[a_i]
    grp = np.where(np.isin(lab, ['МОСКВА', 'САНКТ-ПЕТЕРБУРГ']), lab, tier)
    S, C = len(wj.SEGMENTS), len(wj.CHANNELS)

    post = np.load(a.npz)
    keys = wj.roas_keys(arr)
    flat = {k: post[k].reshape((-1,) + post[k].shape[2:]) for k in keys}
    nd = flat['alpha'].shape[0]
    idx = np.linspace(0, nd - 1, min(a.draws, nd)).astype(int)

    cells = [(s, sname, j, c, g) for s, sname in enumerate(wj.SEGMENTS) for j, c in enumerate(wj.CHANNELS)
             for g in ['все'] + sorted(np.unique(grp[s_i == s]).tolist()) if d.chan_mask[s, j]]
    sel_of = {}
    for s, sname, j, c, g in cells:
        sel = (s_i == s) if g == 'все' else (s_i == s) & (grp == g)
        if spend[sel, j].sum() > 0:
            sel_of[(s, j, g)] = sel
    rec = {k: [] for k in sel_of}
    sat_rows = []
    for i in idx:
        draw = {k: np.asarray(flat[k][i]) for k in keys}
        c1 = contrib(arr, draw, 1.0, a_i, w_i)
        cu = contrib(arr, draw, 1.0 + BUMP, a_i, w_i)
        cd = contrib(arr, draw, 1.0 - CUT, a_i, w_i)
        avg = T[:, None] * (1 - np.exp(-c1))
        up = T[:, None] * (np.exp(cu - c1) - 1)          # extra turnover from +1% money
        down = T[:, None] * (1 - np.exp(-(c1 - cd)))     # turnover lost with -10% money
        for (s, j, g), sel in sel_of.items():
            sp = spend[sel, j].sum()
            rec[(s, j, g)].append((avg[sel, j].sum() / sp, up[sel, j].sum() / (BUMP * sp), down[sel, j].sum() / (CUT * sp)))
        # saturation actually reached on unit-weeks with spend (adstocked spend over lam)
        lam = np.asarray(draw['lam'])
        sat, _ = wj.adstock_sat(arr['spend_norm'], np.asarray(draw['alpha']), lam, arr.get('adstock_l', wj.ADSTOCK_L),
                                arr.get('adstock_pad_steady', False))
        sat = np.asarray(sat)[a_i, w_i, :]
        for s, sname in enumerate(wj.SEGMENTS):
            for j, c in enumerate(wj.CHANNELS):
                m = (s_i == s) & (spend[:, j] > 0)
                if m.any() and d.chan_mask[s, j]:
                    x_over_lam = -np.log(np.clip(1 - sat[m, j], 1e-12, None))
                    sat_rows.append(dict(draw=int(i), segment=sname, channel=c, lam=float(lam[j]), alpha=float(draw['alpha'][j]),
                                         sat_mean=float(sat[m, j].mean()), x_over_lam_median=float(np.median(x_over_lam)),
                                         x_over_lam_p90=float(np.percentile(x_over_lam, 90))))
    rows = []
    for (s, j, g), v in rec.items():
        v = np.asarray(v)
        q = np.percentile(v, [5, 50, 95], axis=0)
        sel = sel_of[(s, j, g)]
        rows.append(dict(segment=wj.SEGMENTS[s], channel=wj.CHANNELS[j], group=g, spend_mln=round(spend[sel, j].sum() / 1e6, 3),
                         roas_avg=round(q[1, 0], 3), roas_avg_q05=round(q[0, 0], 3), roas_avg_q95=round(q[2, 0], 3),
                         roas_marginal=round(q[1, 1], 3), roas_marginal_q05=round(q[0, 1], 3), roas_marginal_q95=round(q[2, 1], 3),
                         roas_last10=round(q[1, 2], 3), roas_last10_q05=round(q[0, 2], 3), roas_last10_q95=round(q[2, 2], 3),
                         marginal_over_avg=round(float(np.median(v[:, 1] / np.where(v[:, 0] > 0, v[:, 0], np.nan))), 3)))
    tab = pd.DataFrame(rows)
    tab.to_csv(out / 'marginal_roas.csv', index=False, encoding='utf-8-sig')
    sr = pd.DataFrame(sat_rows)
    st = sr.groupby(['segment', 'channel']).agg(lam=('lam', 'median'), alpha=('alpha', 'median'), sat_mean=('sat_mean', 'median'),
                                                x_over_lam_median=('x_over_lam_median', 'median'),
                                                x_over_lam_p90=('x_over_lam_p90', 'median')).round(3).reset_index()
    lam_q = sr.drop_duplicates(['draw', 'channel']).groupby('channel').lam.quantile([0.05, 0.5, 0.95]).unstack().round(3)
    st.to_csv(out / 'saturation_by_cell.csv', index=False, encoding='utf-8-sig')
    card = dict(code_version=CODE_VERSION, npz=str(a.npz), draws=int(len(idx)), bump=BUMP, cut=CUT, media_geo=a.media_geo,
                adstock=a.adstock, roas_scale=a.roas_scale, top_units=a.top_units, seconds=round(time.time() - t0),
                lam_by_channel={c: lam_q.loc[c].tolist() for c in lam_q.index})
    (out / 'marginal_card.json').write_text(json.dumps(card, ensure_ascii=False, indent=1), encoding='utf-8')
    pd.set_option('display.width', 250)
    print(tab[tab.group == 'все'].to_string(index=False))
    print(st.to_string(index=False))
    print(json.dumps(card, ensure_ascii=False))


if __name__ == '__main__':
    main()
