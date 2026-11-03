"""Forecast of a media plan with a fitted weekly joint model: extra turnover per city and channel, with intervals.

Reads the posterior draws saved by 05_weekly_joint_real_fit.py (posterior_roas_params_{profile}.npz) and a media
plan (CSV: campaign_name, start_date, end_date, segment, geo, channel, budget_rub). Each plan row's budget is spread
evenly over its days and summed into Monday weeks. For every draw, the plan spend of a city goes through the same
adstock, saturation and city ROAS as in the model (media_contrib_draw), against a no-campaign counterfactual (only
the plan's own spend, as the platform forecast does), and the extra turnover is

    baseline turnover[city, week] * (1 - exp(-(orders part + check part)))

over the plan weeks plus the 7 carry-over weeks after the last one. Baseline turnover of a plan week = the city's
real turnover in the same week one year earlier (analog year, no growth added); the panel ends 28.06.2026 and
July-September 2026 are never read. The plan's spend intensity is shown against the model's typical spend (m_ref)
so that saturation is visible.

Panel v4 (--agglo-city-map): a plan row of regional TV or radio in МОСКВА or САНКТ-ПЕТЕРБУРГ is spread by population
over the city and every unit of its oblast in the model (the same rule as the panel), so the forecast counts the
oblast sales too; the rows of the by-city table then include those oblast units.

Run: python -I 07_weekly_joint_plan_forecast.py --panel P.parquet --national N.csv --npz posterior.npz
     --plan plan.csv --out OUTDIR [--draws 400] [--segment-table roas_by_segment_channel_pilot.csv]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))     # run with python -I: the script folder is not on the path

import numpy as np
import pandas as pd

from mmm_core import campaign_routing as cr
from mmm_core import weekly_joint as wj


def weekly_plan(plan: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for r in plan.itertuples(index=False):
        days = pd.date_range(r.start_date, r.end_date, freq='D')
        per_day = float(r.budget_rub) / len(days)
        wk = (days - pd.to_timedelta(days.weekday, unit='D')).normalize()
        for w, n in pd.Series(1, index=wk).groupby(level=0).sum().items():
            rows.append(dict(segment=r.segment, geo=r.geo, plan_geo=r.geo, channel=r.channel, week_start=w, spend=per_day * n))
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--panel', required=True)
    ap.add_argument('--national', required=True)
    ap.add_argument('--npz', required=True)
    ap.add_argument('--plan', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--draws', type=int, default=400)
    ap.add_argument('--adstock', default='short', choices=['short', 'long'], help='the same as the fit that wrote the npz')
    ap.add_argument('--roas-scale', default='equal', choices=['equal', 'turnover', 'gamma'], help='the same as the fit that wrote the npz')
    ap.add_argument('--media-geo', default='unit', choices=['unit', 'tier'], help='v12: unit = own ROAS deviation per city (v6-v11), tier = cities differ only by size tier and spend per resident; the same as the fit')
    ap.add_argument('--segment-table', default=None, help='roas_by_segment_channel_*.csv of the same fit: budget x segment ROAS for comparison')
    ap.add_argument('--agglo-city-map', default=None, help='panel v4: city_oblast_map csv; Moscow/SPb regional TV and radio of the plan over the city and its oblast')
    ap.add_argument('--m-ref', default=None, help='v14: typical spend per resident from panel v3 (m_ref_v3 csv); the same as the fit')
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    plan = pd.read_csv(a.plan, parse_dates=['start_date', 'end_date'])
    bad_ch = sorted(set(plan.channel) - set(wj.CHANNELS[:5]))
    bad_seg = sorted(set(plan.segment) - set(wj.SEGMENTS))
    if bad_ch or bad_seg:
        raise SystemExit(f'unknown channels {bad_ch} or segments {bad_seg} in the plan')
    wp = weekly_plan(plan)

    d = wj.prepare(a.panel, a.national, top_units_per_segment=None, m_ref_csv=a.m_ref)
    arr = wj.model_arrays(d, city_wave=False, adstock=a.adstock, roas_scale=a.roas_scale, media_geo=a.media_geo)   # media part only; the city wave does not enter the forecast
    L = arr['adstock_l']
    ad = d.ad_units
    if a.agglo_city_map:   # panel v4: the plan's Moscow / SPb broadcast over the agglomeration, by population
        cmap = pd.read_csv(a.agglo_city_map, encoding='utf-8-sig')
        c2o = dict(zip(cmap.city, cmap.oblast))
        seg_name = np.array(wj.SEGMENTS)[ad.seg_i.to_numpy()]
        rows = []
        for r in wp.itertuples(index=False):
            if r.geo in cr.AGGLO and r.channel in cr.AGGLO_MODEL_CHANNELS:
                ob = cr.AGGLO[r.geo]
                mem = np.where((seg_name == r.segment) & ((ad.unit_label == r.geo) | ad.unit_label.map(c2o).eq(ob)
                                                         | ad.unit_label.str.startswith(ob)).to_numpy())[0]
                w = ad.pop_k.to_numpy()[mem] / ad.pop_k.to_numpy()[mem].sum()
                rows += [dict(segment=r.segment, geo=ad.unit_label.iloc[i], plan_geo=r.geo, channel=r.channel,
                              week_start=r.week_start, spend=r.spend * wi) for i, wi in zip(mem, w)]
            else:
                rows.append(r._asdict())
        wp = pd.DataFrame(rows).groupby(['segment', 'geo', 'plan_geo', 'channel', 'week_start'], as_index=False).spend.sum()
    key = {(wj.SEGMENTS[s], u): i for i, (s, u) in enumerate(zip(ad.seg_i, ad.unit_label))}
    missing = sorted({(s, g) for s, g in zip(wp.segment, wp.geo) if (s, g) not in key})
    if missing:
        raise SystemExit(f'plan cities not in the model: {missing}')

    weeks = pd.date_range(wp.week_start.min(), wp.week_start.max() + pd.Timedelta(weeks=L - 1), freq='7D')
    A, Wp, C = len(ad), len(weeks), len(wj.CHANNELS)
    widx = {w: i for i, w in enumerate(weeks)}
    spend = np.zeros((A, Wp, C))
    for r in wp.itertuples(index=False):
        spend[key[(r.segment, r.geo)], widx[r.week_start], wj.CHANNELS.index(r.channel)] += r.spend
    pop = ad.pop_k.to_numpy() * 1000.0
    m_ref_a = d.m_ref[ad.seg_i.to_numpy()]
    spend_pr = spend / pop[:, None, None]
    arr_p = dict(arr, adstock_pad_steady=False, spend_norm=np.where(m_ref_a[:, None, :] > 0, spend_pr / np.where(m_ref_a > 0, m_ref_a, 1.0)[:, None, :], 0.0))

    # baseline turnover: the same week one year earlier, per ad unit (sum of its model units)
    o = d.obs
    T = pd.Series(np.exp(o.y_orders.to_numpy(float) + o.y_check.to_numpy(float)))
    hist = T.groupby([arr['a_i'], o.week_start.to_numpy()]).sum()
    base = np.zeros((A, Wp))
    used_analog = np.zeros((A, Wp), bool)
    plan_units = sorted({key[(s, g)] for s, g in zip(wp.segment, wp.geo)})
    for u in plan_units:
        for j, w in enumerate(weeks):
            v = hist.get((u, w - pd.Timedelta(weeks=52)), np.nan)
            used_analog[u, j] = np.isfinite(v)
            base[u, j] = v if np.isfinite(v) else hist.xs(u, level=0).median()

    post = np.load(a.npz)
    flat = {k: post[k].reshape((-1,) + post[k].shape[2:]) for k in wj.roas_keys(arr)}
    n = flat['alpha'].shape[0]
    idx = np.linspace(0, n - 1, min(a.draws, n)).astype(int)
    U = np.array(plan_units)
    eff_c = np.zeros((len(idx), len(U), C))          # extra turnover by channel (channel alone)
    eff_t = np.zeros((len(idx), len(U)))             # extra turnover of the whole plan in the city
    for t, i in enumerate(idx):
        draw = {k: np.asarray(flat[k][i]) for k in wj.roas_keys(arr)}
        contrib = wj.media_contrib_draw(arr_p, draw)                                  # [2, A, Wp, C]
        c = (contrib[0] + contrib[1])[U]                                              # [U, Wp, C]
        b = base[U][:, :, None]
        eff_c[t] = (b * (1 - np.exp(-c))).sum(1)
        eff_t[t] = (base[U] * (1 - np.exp(-c.sum(-1)))).sum(1)

    budget = spend[U].sum(1)                                                          # [U, C]
    q = lambda x, p: np.quantile(x, p, axis=0)
    rows = []
    for k, u in enumerate(U):
        s = int(ad.seg_i.iloc[u])
        for j, ch in enumerate(wj.CHANNELS):
            if budget[k, j] <= 0:
                continue
            act = spend[u, :, j] > 0
            inten = spend_pr[u, act, j].mean() / m_ref_a[u, j] if m_ref_a[u, j] > 0 else np.nan
            e = eff_c[:, k, j]
            rows.append(dict(segment=wj.SEGMENTS[s], geo=ad.unit_label.iloc[u], channel=ch, budget_rub=budget[k, j],
                             effect_q05=q(e, .05), effect_median=q(e, .5), effect_q95=q(e, .95),
                             roas_q05=q(e, .05) / budget[k, j], roas_median=q(e, .5) / budget[k, j],
                             roas_q95=q(e, .95) / budget[k, j], weekly_spend_vs_typical=inten,
                             baseline_turnover_plan_weeks=base[u].sum(), analog_weeks_share=used_analog[u].mean()))
    by_unit = pd.DataFrame(rows)
    by_unit.to_csv(out / 'plan_forecast_by_city_channel.csv', index=False)

    ch_rows = []
    for j, ch in enumerate(wj.CHANNELS):
        bj = budget[:, j].sum()
        if bj <= 0:
            continue
        e = eff_c[:, :, j].sum(1)
        ch_rows.append(dict(channel=ch, budget_rub=bj, effect_q05=q(e, .05), effect_median=q(e, .5), effect_q95=q(e, .95),
                            roas_q05=q(e, .05) / bj, roas_median=q(e, .5) / bj, roas_q95=q(e, .95) / bj,
                            prob_roas_above_1=float((e / bj > 1).mean())))
    e = eff_t.sum(1)
    btot = budget.sum()
    ch_rows.append(dict(channel='ВСЕГО (весь план вместе)', budget_rub=btot, effect_q05=q(e, .05), effect_median=q(e, .5),
                        effect_q95=q(e, .95), roas_q05=q(e, .05) / btot, roas_median=q(e, .5) / btot, roas_q95=q(e, .95) / btot,
                        prob_roas_above_1=float((e / btot > 1).mean())))
    by_ch = pd.DataFrame(ch_rows)
    if a.segment_table:
        st = pd.read_csv(a.segment_table)
        seg = plan.segment.iloc[0] if plan.segment.nunique() == 1 else None
        if seg is not None:
            m = st[st.segment == seg].set_index('channel').roas_median
            by_ch['segment_roas_median_of_fit'] = by_ch.channel.map(m)
            by_ch['budget_x_segment_roas'] = by_ch.budget_rub * by_ch.segment_roas_median_of_fit
    by_ch.to_csv(out / 'plan_forecast_by_channel.csv', index=False)

    pd.set_option('display.width', 250)
    print(f'plan weeks {weeks[0].date()} .. {weeks[-1].date()} (incl. {L - 1} carry-over weeks), draws {len(idx)}, '
          f'cities {len(U)}, analog-year weeks used {used_analog[U].mean():.0%}')
    print(by_ch.round(3).to_string(index=False))
    print()
    print(by_unit.drop(columns=['segment']).round(3).to_string(index=False))


if __name__ == '__main__':
    main()
