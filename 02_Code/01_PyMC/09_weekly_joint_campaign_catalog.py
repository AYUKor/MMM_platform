"""Past-campaign catalog on a fitted weekly joint model (fourth pass): effect and ROAS of every campaign (no sampling).

For each campaign of the ledger (name + period, names directory rules) and each of N posterior draws: turnover with all
ads minus turnover without this campaign's money, over the model's fit unit-weeks; incremental orders per 1000 buyers
and the average check change over the campaign's zone (its units, from its first week to its last week + adstock);
ROAS = turnover effect / full ledger budget. Ranges = 10th / 50th / 90th percentile over draws.
--tail-weeks 7: the carry-over after the last panel week is counted too, as the plan forecast (07) counts 7 weeks after
a plan (ledger money of 29-30.06.2026 enters the first tail week; baseline turnover of a tail week = the same unit 52
weeks earlier; other spend there: --tail-other analog = the model's spend a year earlier, none = no other spend, an
upper-side estimate). Default 0 = as before (nothing after 28.06.2026).

Checks written to checks.json: routing by campaign == the panel's media_units_daily (to the ruble); campaign money in
model cells summed over campaigns == the model's spend array; numpy media part == wj.media_contrib_draw; per draw and
segment x channel the sum of campaign effects <= the full channel effect (diminishing returns); catalog channel ROAS
next to the model's channel ROAS.

Run: python -I 09_weekly_joint_campaign_catalog.py --panel P.parquet --national N.csv --npz posterior_roas_params_X.npz
     --ledger LEDGER_DIR --targets T.parquet --city-map MAP.csv --media-units-daily MUD.parquet --names NAMES.csv
     --out OUTDIR [--draws 400] [--procs 4] [--top-units 20] [--adstock short] [--roas-scale equal]
"""
from __future__ import annotations

import os
for _v in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
    os.environ.setdefault(_v, '1')

import argparse
import hashlib
import json
import multiprocessing as mp
import pickle
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

from mmm_core import campaign_catalog as cc
from mmm_core import campaign_routing as cr
from mmm_core import weekly_joint as wj

CODE_VERSION = 'campaign_catalog_weekly_joint_v4_20261104'
G = {}


def sha(path) -> str:
    path = Path(path)
    if path.is_dir():
        return hashlib.sha256('\n'.join(f'{p.name}:{sha(p)}' for p in sorted(path.glob('*.parquet'))).encode()).hexdigest()
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def work(idx_chunk):
    camp, arr, flat, keys = G['camp'], G['arr'], G['flat'], G['keys']
    res = []
    for i in idx_chunk:
        draw = {k: np.asarray(flat[k][i]) for k in keys}
        res.append(camp.effects(arr, draw))
    return idx_chunk, res


def q3(v):
    return tuple(float(x) for x in np.percentile(v, [10, 50, 90]))


def main() -> None:
    ap = argparse.ArgumentParser()
    for a in ('--panel', '--national', '--npz', '--ledger', '--targets', '--city-map', '--out'):
        ap.add_argument(a, required=True)
    ap.add_argument('--media-units-daily', default=None, help="the panel's routed money, for the routing check")
    ap.add_argument('--names', default=None, help='saved names directory (xlsx or its csv copy): numbers stay the same')
    ap.add_argument('--names-sparse', action='store_true', help='--names holds only the overrides (numbers_overrides)')
    ap.add_argument('--roas-draws', default=None, help='roas_draws_*.csv of the same fit (default: next to the npz)')
    ap.add_argument('--draws', type=int, default=400)
    ap.add_argument('--procs', type=int, default=4)
    ap.add_argument('--top-units', type=int, default=None, help='same as the fit (fast/medium: 20); pilot/production: all')
    ap.add_argument('--adstock', default='short', choices=['short', 'long'], help='the same as the fit')
    ap.add_argument('--roas-scale', default='equal', choices=['equal', 'turnover', 'gamma'], help='the same as the fit')
    ap.add_argument('--media-geo', default='unit', choices=['unit', 'tier'], help='v12: unit = own ROAS deviation per city (v6-v11), tier = cities differ only by size tier and spend per resident; the same as the fit')
    ap.add_argument('--only', default='', help='test: comma-separated campaign numbers')
    ap.add_argument('--agglo', action='store_true', help='panel v4: Moscow/SPb regional TV and radio over the city and its oblast; the same as the panel')
    ap.add_argument('--m-ref', default=None, help='v14: typical spend per resident from panel v3 (m_ref_v3 csv); the same as the fit')
    ap.add_argument('--tail-weeks', type=int, default=0, help='count the carry-over after the last panel week (7 = as the plan forecast); 0 = as before')
    ap.add_argument('--tail-other', default='analog', choices=['analog', 'none'], help='other spend in the tail weeks: the same week a year earlier (analog) or none (upper-side)')
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    logf = open(out / 'catalog_run.log', 'a', buffering=1)

    def log(*x):
        s = time.strftime('%H:%M:%S') + ' ' + ' '.join(str(v) for v in x)
        print(s, flush=True)
        logf.write(s + '\n')

    T0 = time.time()
    checks = {}
    # ---- model data, as the fit
    d = wj.prepare(a.panel, a.national, top_units_per_segment=a.top_units, m_ref_csv=a.m_ref)
    arr = wj.model_arrays(d, adstock=a.adstock, roas_scale=a.roas_scale, media_geo=a.media_geo)
    log(f'model data: {len(d.ad_units)} units, {len(d.weeks)} weeks, {len(d.obs)} fit rows')

    # ---- campaigns and names
    led = cr.read_ledger(a.ledger)
    led['name_key'] = led.campaign_id_for_audit.map(cc.norm_name)
    led, waves = cc.assign_waves(led)
    directory, groups = cc.build_directory(led, waves)
    if a.names:
        names = cc.read_names_xlsx(a.names)
        directory, num_info = cc.keep_numbers(directory, names, sparse=bool(a.names_sparse))
    else:
        directory['id'], directory['id_match'] = np.arange(1, len(directory) + 1), 'new'
        num_info = {}
    checks['numbers'] = num_info
    n = len(directory)
    directory['cat'] = np.arange(n)
    led = led.merge(directory[['name_key', 'wave', 'cat']], on=['name_key', 'wave'], how='left')
    assert led.cat.notna().all()
    log(f'campaigns: {n}; numbers {json.dumps({k: v for k, v in num_info.items() if k != "old_not_found"}, ensure_ascii=False)}; '
        f'old not found: {len(num_info.get("old_not_found", []))}')

    # ---- routing by campaign (panel v3 rules; --agglo: panel v4)
    units = cr.load_units(a.targets)
    cmap = pd.read_csv(a.city_map, encoding='utf-8-sig')
    c2o = dict(zip(cmap.city, cmap.oblast))
    routed, unmod = cr.route_media(led[cr.LEDGER_COLS + ['cat']], units, c2o, ['cat'], agglo=a.agglo)
    if a.media_units_daily:
        checks['routing_vs_panel'] = cr.check_against_panel(routed, pd.read_parquet(a.media_units_daily))
        log('routing vs panel:', checks['routing_vs_panel'])
    present = cc.present_cells(a.panel, d)
    tail = None
    if a.tail_weeks > 0:
        sp = cc.campaign_spend(routed, units, d, cc.present_tail(present, a.tail_weeks), n,
                               weeks=cc.tail_weeks(d, a.tail_weeks))
        tail = cc.tail_rows(d, arr, a.tail_weeks)
        tail_money = sum(float(g.budget[g.w.to_numpy(int) >= len(d.weeks)].sum()) for g in sp['cells'].values())
        checks['tail'] = dict(weeks=a.tail_weeks, first_week=tail['first_week'], last_week=tail['last_week'],
                              rows=int(len(tail['T'])), analog_share=tail['analog_share'], ledger_money_in_tail_rub=tail_money,
                              other_spend=a.tail_other)
        log('tail weeks:', checks['tail'])
    else:
        sp = cc.campaign_spend(routed, units, d, present, n)
    checks['spend_rebuild'] = cc.check_spend_rebuild(sp['cells'], d)
    log('campaign money in model cells vs model spend:', checks['spend_rebuild'])

    camp = cc.Campaigns(d, arr, sp['cells'], n, tail=tail, tail_other=a.tail_other)
    log(f'campaign arrays ready, {time.time() - T0:.0f} s')

    # ---- posterior draws
    post = np.load(a.npz)
    keys = wj.roas_keys(arr)
    flat = {k: post[k].reshape((-1,) + post[k].shape[2:]) for k in keys}
    nd = flat['alpha'].shape[0]
    idx = np.linspace(0, nd - 1, min(a.draws, nd)).astype(int)
    if a.only:
        want = {int(x) for x in a.only.split(',')}
        keep = set(directory.cat[directory.id.isin(want)])
        camp.items = [it if k in keep else None for k, it in enumerate(camp.items)]
    G.update(camp=camp, arr=arr, flat=flat, keys=keys)
    D = len(idx)
    S, C = len(wj.SEGMENTS), len(wj.CHANNELS)
    turn = np.zeros((D, n)); orders = np.zeros((D, n)); check_num = np.zeros((D, n))
    by_sc = np.zeros((D, n, S, C), np.float32); full_sc = np.zeros((D, S, C)); full_all = np.zeros((D, S, C))
    pos = {int(i): t for t, i in enumerate(idx)}
    chunks = [list(map(int, c)) for c in np.array_split(idx, max(1, min(len(idx), a.procs * 8)))]
    T1 = time.time()
    with mp.get_context('fork').Pool(a.procs) as pool:
        for m, (ch, res) in enumerate(pool.imap_unordered(work, chunks), 1):
            for i, r in zip(ch, res):
                t = pos[i]
                turn[t], orders[t], check_num[t] = r['turn'], r['orders'], r['check_num']
                by_sc[t], full_sc[t], full_all[t] = r['by_sc'], r['full_sc'], r['full_sc_all']
            if m % max(1, len(chunks) // 10) == 0:
                log(f'draws {m}/{len(chunks)} chunks, {time.time() - T1:.0f} s')
    log(f'{D} draws x {n} campaigns: {time.time() - T1:.0f} s')

    # ---- check: numpy media part == the model's own function (one draw)
    draw0 = {k: np.asarray(flat[k][idx[0]]) for k in keys}
    ref = wj.media_contrib_draw(arr, draw0)
    mine = cc.beta_draw(arr, draw0)[:, :, None, :] * cc.adstock_sat_np(arr['spend_norm'], draw0['alpha'], draw0['lam'],
                                                                       camp.L, camp.pad)[None]
    checks['media_part_vs_model_max_rel'] = float(np.abs(mine - ref).max() / max(np.abs(ref).max(), 1e-12))
    # ---- check: diminishing returns, sum of campaign effects <= full effect per segment x channel and draw
    sum_sc = by_sc.astype(float).sum(1)
    viol = sum_sc > full_all * (1 + 1e-6) + 1.0          # full effect over the same rows (with the tail rows if any)
    checks['sum_campaigns_le_full'] = dict(violations=int(viol.sum()), cells=int(viol.size),
                                           max_ratio=float(np.nanmax(np.where(full_all > 0, sum_sc / np.where(full_all > 0, full_all, 1), 0))))

    # ---- money per campaign x segment x channel: ledger and seen by the model
    led['segment'] = led.network + '/' + led.channel
    led['mch'] = led.channel_type.map(cr.MODEL_CHANNEL)
    bud = led.groupby('cat').budget.sum().reindex(range(n), fill_value=0.0).to_numpy()
    bud_sc = led.groupby(['cat', 'segment', 'mch']).budget.sum()
    bud_seg_ch = led.groupby(['segment', 'mch']).budget.sum()
    seen_sc = {}
    for k, g in sp['cells'].items():
        g = g[g.kind == 'present']
        for (s, j), v in g.groupby(['segment', 'j']).budget.sum().items():
            seen_sc[(k, s, wj.CHANNELS[int(j)])] = float(v)

    # ---- reliability per segment x channel, flag per campaign
    rd_path = a.roas_draws or str(Path(a.npz)).replace('posterior_roas_params_', 'roas_draws_').replace('.npz', '.csv')
    rd = pd.read_csv(rd_path) if Path(rd_path).exists() else None
    cells_ok = cc.cell_support(d, arr, rd)
    cells_ok.to_csv(out / 'cell_support.csv', index=False)
    okset = {(r.segment, r.channel) for r in cells_ok.itertuples() if r.ok}
    log('cells ok:', len(okset), 'of', len(cells_ok), '; R-hat from', rd_path if rd is not None else 'none')

    # ---- model table for the check: full effect / spend on fit rows
    pop = d.ad_units.pop_k.to_numpy()[arr['a_i']] * 1000.0
    spn = d.spend_pr[arr['a_i'], arr['w_i'], :] * pop[:, None]
    spend_fit = np.zeros((S, C))
    np.add.at(spend_fit, arr['s_i'], spn)

    # ---- per campaign rows
    results, rows, chrows = {}, [], []
    led_by = dict(tuple(led.groupby('cat')))
    seen_k = {}
    for (kk, s, ch), v in seen_sc.items():
        seen_k.setdefault(kk, {})[(s, ch)] = v
    for r in directory.itertuples():
        k = r.cat
        sub = led_by[k]
        it = camp.items[k]
        c = cc.card(sub)
        b = float(bud[k])
        seen = sum(seen_k.get(k, {}).values())
        ok_money = sum(v for sc, v in seen_k.get(k, {}).items() if sc in okset)
        modeled = it is not None and seen > 0
        flag = int(modeled and b > 0 and ok_money / b >= cc.FLAG_MIN_SHARE)
        tq = q3(turn[:, k])
        o1000 = q3(1000.0 * orders[:, k] / it['zone_buyers']) if modeled and it['zone_buyers'] > 0 else (np.nan,) * 3
        bask = q3(check_num[:, k] / it['zone_orders']) if modeled and it['zone_orders'] > 0 else (np.nan,) * 3
        byc = {}
        for s_i, s in enumerate(wj.SEGMENTS):
            for j, ch in enumerate(wj.CHANNELS):
                v = by_sc[:, k, s_i, j]
                bb = float(bud_sc.get((k, s, ch), 0.0))
                if bb > 0 or np.any(v != 0):
                    byc[(s, ch)] = q3(v.astype(float))
                    chrows.append(dict(номер=int(r.id), кампания=r.name, направление=s, канал=ch, бюджет_млн=round(bb / 1e6, 4),
                                       бюджет_видит_модель_млн=round(seen_sc.get((k, s, ch), 0.0) / 1e6, 4),
                                       оборот_оценка_млн=round(byc[(s, ch)][1] / 1e6, 4), оборот_от_млн=round(byc[(s, ch)][0] / 1e6, 4),
                                       оборот_до_млн=round(byc[(s, ch)][2] / 1e6, 4),
                                       roas_оценка=round(byc[(s, ch)][1] / bb, 4) if bb else '',
                                       ячейка_надёжна=int((s, ch) in okset)))
        results[k] = dict(id=int(r.id), name=r.name, card=c, budget=b, modeled=modeled, flag=flag,
                          turnover=tq, roas=tuple(v / b for v in tq) if b else (np.nan,) * 3,
                          orders1000=o1000, basket=bask, by_channel=byc, seen_rub=seen, ok_rub=ok_money,
                          unseen_rub=float(b - seen), overlap=0)
    ov = cc.overlaps(led, led.cat.to_numpy(np.int64), n)
    for k in results:
        results[k]['overlap'] = int(ov[k])
    for k, x in sorted(results.items(), key=lambda kv: kv[1]['id']):
        c = x['card']
        m = x['modeled']
        row = dict(номер=x['id'], кампания=x['name'], направления=', '.join(c['dirs']), старт=c['start'], конец=c['end'],
                   дней=c['days'], лист='длиннее 120 дней' if c['days'] >= cc.LONG_DAYS else 'до 120 дней',
                   бюджет_млн=round(x['budget'] / 1e6, 4))
        for ch in c['channels']:
            row['бюджет_' + ch['name'] + '_млн'] = round(ch['budget'] / 1e6, 4)
        row.update(модель_считает=int(m),
                   оборот_оценка_млн=round(x['turnover'][1] / 1e6, 4) if m else '', оборот_от_млн=round(x['turnover'][0] / 1e6, 4) if m else '',
                   оборот_до_млн=round(x['turnover'][2] / 1e6, 4) if m else '',
                   roas_оценка=round(x['roas'][1], 4) if m else '', roas_от=round(x['roas'][0], 4) if m else '',
                   roas_до=round(x['roas'][2], 4) if m else '',
                   заказы_на_1000_оценка=round(x['orders1000'][1], 4) if m else '', заказы_на_1000_от=round(x['orders1000'][0], 4) if m else '',
                   заказы_на_1000_до=round(x['orders1000'][2], 4) if m else '',
                   чек_руб_оценка=round(x['basket'][1], 4) if m else '', чек_руб_от=round(x['basket'][0], 4) if m else '',
                   чек_руб_до=round(x['basket'][2], 4) if m else '',
                   флаг=x['flag'], доля_бюджета_видит_модель=round(x['seen_rub'] / x['budget'], 4) if x['budget'] else 0,
                   доля_бюджета_в_надёжных_ячейках=round(x['ok_rub'] / x['budget'], 4) if x['budget'] else 0,
                   пересечения=x['overlap'])
        rows.append(row)
    pd.DataFrame(rows).to_csv(out / 'catalog_numbers.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(chrows).to_csv(out / 'catalog_by_channel.csv', index=False, encoding='utf-8-sig')
    directory.drop(columns=['spellings']).to_csv(out / 'names_directory.csv', index=False, encoding='utf-8-sig')

    # ---- check: catalog channel ROAS next to the model's channel ROAS (medians)
    tab = []
    med_sum = np.median(sum_sc, 0)
    med_full = np.median(full_sc, 0)
    med_full_all = np.median(full_all, 0)
    for s_i, s in enumerate(wj.SEGMENTS):
        for j, ch in enumerate(wj.CHANNELS):
            seen_tot = sum(v for (kk, ss, cch), v in seen_sc.items() if ss == s and cch == ch)
            if d.chan_mask[s_i, j] == 0 or (spend_fit[s_i, j] <= 0 and seen_tot <= 0):
                continue
            tab.append(dict(segment=s, channel=ch, model_roas_fit_rows=med_full[s_i, j] / spend_fit[s_i, j] if spend_fit[s_i, j] else np.nan,
                            catalog_roas_seen_money=med_sum[s_i, j] / seen_tot if seen_tot else np.nan,
                            sum_campaign_effect_over_full=med_sum[s_i, j] / med_full_all[s_i, j] if med_full_all[s_i, j] else np.nan,
                            model_spend_fit_rows_mln=spend_fit[s_i, j] / 1e6, campaigns_seen_money_mln=seen_tot / 1e6,
                            ledger_money_mln=float(bud_seg_ch.get((s, ch), 0.0)) / 1e6))
    tab = pd.DataFrame(tab)
    tab.to_csv(out / 'check_catalog_vs_model_roas.csv', index=False)
    checks['budget_total_rub'] = float(bud.sum())
    checks['ledger_total_rub'] = float(led.budget.sum())
    checks['unmodeled_by_routing_rub'] = float(unmod.budget.sum())
    checks['seen_by_model_rub'] = float(sum(seen_sc.values()))
    checks['flag1'] = int(sum(x['flag'] for x in results.values()))
    checks['modeled'] = int(sum(x['modeled'] for x in results.values()))
    meta = dict(code_version=CODE_VERSION, n_campaigns=n, n_draws=D, calc_seconds=round(time.time() - T0),
                finished_utc=time.strftime('%d.%m.%Y %H:%M', time.gmtime()), adstock=a.adstock, roas_scale=a.roas_scale, media_geo=a.media_geo,
                agglo=bool(a.agglo), m_ref=a.m_ref, adstock_weeks=camp.L, top_units=a.top_units, tail_weeks=a.tail_weeks,
                tail_other=a.tail_other if a.tail_weeks else '',
                inputs={k: dict(path=str(v), sha256=sha(v)) for k, v in
                        (('panel', a.panel), ('national', a.national), ('npz', a.npz), ('ledger', a.ledger),
                         ('targets', a.targets), ('city_map', a.city_map)) if v},
                code_sha256={p.name: sha(p) for p in [Path(__file__), Path(cc.__file__), Path(cr.__file__), Path(wj.__file__)]})
    (out / 'checks.json').write_text(json.dumps(dict(meta=meta, checks=checks), ensure_ascii=False, indent=1, default=str),
                                     encoding='utf-8')
    js = {str(k): {**{kk: vv for kk, vv in x.items() if kk != 'by_channel'},
                   'by_channel': {f'{sc[0]}|{sc[1]}': v for sc, v in x['by_channel'].items()}} for k, x in results.items()}
    (out / 'catalog_results.json').write_text(json.dumps(dict(results=js, meta=meta, checks=checks), ensure_ascii=False,
                                                         default=lambda v: None if isinstance(v, float) and np.isnan(v) else float(v)),
                                              encoding='utf-8')
    with open(out / 'catalog_results.pkl', 'wb') as f:
        pickle.dump(dict(results=results, directory=directory, groups=groups, meta=meta, checks=checks,
                         cells=cells_ok, roas_check=tab), f)
    pd.set_option('display.width', 250)
    log(tab.round(3).to_string(index=False))
    log(json.dumps(checks, ensure_ascii=False, default=str)[:3000])
    log(f'done in {time.time() - T0:.0f} s')


if __name__ == '__main__':
    main()
