"""Injection check, part 2: where does the injected effect go?

The injection check (05_weekly_joint_real_fit.py --inject) adds a known media effect to the real log orders and
asks how much of it the model finds. On 03.11 the model found about half of it for OOH, two thirds for national TV
and radio, three quarters for digital and all of it for regional TV, with moderate and with wide ROAS priors alike,
so the rest is taken by other parts of the model. This script tells which ones.

It fits the approximation (multi_start_vi, start at the prior median) twice, to the real targets and to the real
targets plus the injected effect, with the same model and the same fixed own-wave spread. Then, for the log
orders of every observed unit-week,

    y = level + unit slope + trend + season + week shock + controls + city wave + media + AR part + innovation

where the AR part is rho * (previous week's residual) and the innovation is what is left. The injected effect g
equals the sum of the changes of all parts between the two fits, so each part's share of the injection is
<change of the part, g> / <g, g> (the shares add up to 1); by channel, the change of every part is regressed on
the channels' injected series (the coefficients of a channel add up to 1). The media part of the average check
is reported too: if it falls when orders get the injection, the check part eats turnover ROAS.

Run: python -I 08_weekly_joint_injection_absorption.py --panel P --national N --out OUTDIR
     --inject "Нац_ТВ=2,Рег_ТВ=2,Радио=2,OOH_Total=2,Digital_Performance=2" [--no-city-wave] [--wave-scale fixed]
     [--top-units 20] [--prior-set moderate] [--vi-steps 15000]
July-September 2026 are never read (the panel ends 28.06.2026).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))     # run with python -I: the script folder is not on the path

import numpy as np
import pandas as pd

from mmm_core import weekly_joint as wj

CODE_VERSION = 'v2_injection_absorption_long_adstock_20261103'
PARTS = ['level', 'unit_slope', 'trend', 'season', 'week_shock', 'controls', 'city_wave', 'media', 'ar_part', 'innovation']


def _real_fit_module():
    spec = importlib.util.spec_from_file_location('weekly_joint_real_fit', Path(__file__).resolve().parent / '05_weekly_joint_real_fit.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fit_parts(d, arr: dict, prior_set: str, y: np.ndarray, steps: int, seed: int) -> dict:
    """Approximation centre (start at the prior median) and the fitted parts of log y at that centre."""
    from numpyro import handlers
    st = wj.multi_start_vi(arr, d.dims, prior_set, y, n_starts=1, steps=steps, seed=seed)[0]
    point = st['point']
    tr = handlers.trace(handlers.substitute(wj.numpyro_model, data=point)).get_trace(
        dict(arr, emit_parts=True), d.dims, prior_set, y=y)
    parts = {k[len('part_'):]: np.asarray(v['value'], float) for k, v in tr.items() if k.startswith('part_')}
    r = y - parts.pop('mu')
    has_prev = arr['prev'] >= 0
    prev = np.where(has_prev, arr['prev'], 0)
    rho_n = np.asarray(point['rho'], float)[:, arr['s_i']]
    parts['ar_part'] = np.where(has_prev[None, :], rho_n * r[:, prev], 0.0)
    parts['innovation'] = r - parts['ar_part']
    draw = {k: np.asarray(point[k]) for k in wj.roas_keys(arr)}
    roas = wj.roas_from_contrib(d, arr, wj.media_contrib_draw(arr, draw), np.exp(y[0] + y[1]))
    return dict(parts=parts, roas=roas, loss=st['loss'], finite=st['finite'],
                rho=np.asarray(point['rho'], float).round(3).tolist(),
                sig_week=np.asarray(point['sig_week'], float).round(4).tolist(),
                tau_trend=np.asarray(point['tau_trend'], float).round(4).tolist(),
                sig_slope=np.asarray(point['sig_slope'], float).round(4).tolist())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--panel', required=True)
    ap.add_argument('--national', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--inject', required=True)
    ap.add_argument('--top-units', type=int, default=None, help='top units per segment (default: all, as the pilot)')
    ap.add_argument('--prior-set', default='moderate', choices=list(wj.PRIOR_SETS))
    ap.add_argument('--vi-steps', type=int, default=15000)
    ap.add_argument('--seed', type=int, default=20261102)
    ap.add_argument('--no-city-wave', action='store_true', help='v6 model (no own yearly wave per unit)')
    ap.add_argument('--wave-scale', default='fixed', choices=['learned', 'fixed'])
    ap.add_argument('--adstock', default='short', choices=['short', 'long'])
    ap.add_argument('--roas-scale', default='equal', choices=['equal', 'turnover', 'gamma'])
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rf = _real_fit_module()

    t0 = time.time()
    d = wj.prepare(a.panel, a.national, top_units_per_segment=a.top_units)
    arr = wj.model_arrays(d, city_wave=not a.no_city_wave, wave_centred=True, wave_scale=a.wave_scale, adstock=a.adstock, roas_scale=a.roas_scale)
    o = d.obs
    y_p = np.vstack([o.y_orders.to_numpy(float), o.y_check.to_numpy(float)])
    contrib = rf.injection_contrib(arr, a.inject)
    inj_ch = [c for c in wj.CHANNELS if c in rf.parse_inject(a.inject)[0]]
    a_i, w_i = arr['a_i'], arr['w_i']
    G = contrib[0][a_i, w_i, :][:, [wj.CHANNELS.index(c) for c in inj_ch]]          # [N, Ci] injected log orders
    g = G.sum(1)
    y_i = y_p.copy()
    y_i[0] = y_i[0] + g
    truth = wj.roas_from_contrib(d, arr, contrib, np.exp(y_i[0] + y_i[1]))
    truth = truth[truth.channel.isin(inj_ch)]

    arr_p = wj.with_fixed_wave_scale(d, wj.with_targets(arr, y_p), y_p)
    arr_i = wj.with_targets(arr, y_i)
    if 'wave_sd_fixed' in arr_p:
        arr_i = dict(arr_i, wave_sd_fixed=arr_p['wave_sd_fixed'])                     # the same model in both fits
    print('dims', d.dims, f'prep {time.time() - t0:.0f}s', flush=True)

    fits = {}
    for name, ar_, y in [('plain', arr_p, y_p), ('inject', arr_i, y_i)]:
        t1 = time.time()
        fits[name] = fit_parts(d, ar_, a.prior_set, y, a.vi_steps, a.seed)
        print(f'{name}: VI {time.time() - t1:.0f}s, loss {fits[name]["loss"]:.1f}, rho {fits[name]["rho"]}, '
              f'sig_week {fits[name]["sig_week"]}', flush=True)

    P, I = fits['plain']['parts'], fits['inject']['parts']
    delta = {k: I[k][0] - P[k][0] for k in PARTS}
    gap = float(np.abs(sum(delta.values()) - g).max())
    gg = float(g @ g)
    overall = pd.DataFrame([dict(part=k, share_of_injection=float(delta[k] @ g) / gg) for k in PARTS])
    overall.loc[len(overall)] = dict(part='media of the average check (not in the sum)',
                                     share_of_injection=float((I['media'][1] - P['media'][1]) @ g) / gg)
    B = np.linalg.lstsq(G, np.column_stack([delta[k] for k in PARTS]), rcond=None)[0]   # [Ci, parts]
    by_ch = pd.DataFrame(B.T, index=PARTS, columns=inj_ch)
    by_ch.loc['media of the average check (not in the sum)'] = np.linalg.lstsq(G, I['media'][1] - P['media'][1], rcond=None)[0]
    by_ch.loc['sum of the parts (should be 1)'] = B.sum(1)

    key = ['segment', 'channel']
    rc = (truth[key + ['roas']].rename(columns={'roas': 'injected_truth'})
          .merge(fits['plain']['roas'][key + ['roas']].rename(columns={'roas': 'plain'}), on=key, how='left')
          .merge(fits['inject']['roas'][key + ['roas']].rename(columns={'roas': 'inject'}), on=key, how='left'))
    rc['found_share'] = (rc.inject - rc.plain) / rc.injected_truth
    tot = lambda f: f.groupby('channel')[['spend_rub', 'effect_rub']].sum()
    t_tr, t_p, t_i = tot(truth), tot(fits['plain']['roas']), tot(fits['inject']['roas'])
    rch = pd.DataFrame({'injected_truth': t_tr.effect_rub / t_tr.spend_rub,
                        'plain': (t_p.effect_rub / t_p.spend_rub).reindex(t_tr.index),
                        'inject': (t_i.effect_rub / t_i.spend_rub).reindex(t_tr.index)})
    rch['found_share'] = (rch.inject - rch.plain) / rch.injected_truth

    overall.to_csv(out / 'absorption_overall.csv', index=False)
    by_ch.to_csv(out / 'absorption_by_channel.csv')
    rc.to_csv(out / 'roas_plain_vs_inject_by_segment_channel.csv', index=False)
    rch.to_csv(out / 'roas_plain_vs_inject_by_channel.csv')
    card = dict(code_version=CODE_VERSION, inject=a.inject, prior_set=a.prior_set, top_units=a.top_units,
                city_wave_model=not a.no_city_wave, wave_scale=a.wave_scale, adstock=a.adstock, roas_scale=a.roas_scale, vi_steps=a.vi_steps, seed=a.seed, dims=d.dims,
                wave_sd_fixed=(np.asarray(arr_p['wave_sd_fixed']).round(4).tolist() if 'wave_sd_fixed' in arr_p else None),
                max_abs_gap_parts_vs_injection=gap,
                fits={k: {kk: v for kk, v in f.items() if kk not in ('parts', 'roas')} for k, f in fits.items()},
                seconds=round(time.time() - t0))
    (out / 'absorption_card.json').write_text(json.dumps(card, ensure_ascii=False, indent=2, default=str))

    pd.set_option('display.width', 250)
    print(f'check: parts add up to the injection within {gap:.2e}')
    print(overall.round(3).to_string(index=False))
    print()
    print(by_ch.round(3).to_string())
    print()
    print(rch.round(3).to_string())


if __name__ == '__main__':
    main()
