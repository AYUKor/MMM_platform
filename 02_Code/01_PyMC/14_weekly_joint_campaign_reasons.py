"""Reasons for the numbers of the past-campaign catalog (weekly joint model): why each campaign got its ROAS.

Runs on the SAME inputs and options as the catalog run (09_weekly_joint_campaign_catalog.py) and the same posterior
draws. For each campaign it splits the first-ruble potential into kept effect, loss to the campaign's own saturation
and loss to other ads in the same weeks and units (mmm_core.campaign_reasons), compares its first-ruble return with
the typical return of its channels, reads facts about its money from the ledger (where and how densely it spent,
which campaign ran next to it) and labels it with the reasons of the rule file
configs/campaign_catalog/reason_rules_v3.json (norms: campaigns of the same build with the same main channel).
A campaign with nothing specific to say gets no reasons (the card shows the bar only).
Catalog numbers do not change: the kept effect must equal the catalog turnover effect of every campaign (checked
against --catalog-dir/catalog_results.json, the run fails otherwise).

Every new catalog build (a new quarter of data, a new model) runs this step after 09 with the same arguments; the
catalog extension (mmm_core.campaign_catalog_extension) takes the reasons from --out.

Run: python -I 14_weekly_joint_campaign_reasons.py <the 09 arguments, same values> --catalog-dir CATALOG_RUN_DIR
     --out OUTDIR [--rules configs/campaign_catalog/reason_rules_v3.json]
New rule file only (seconds, no model run): the numbers of an earlier green run of this script, new labels:
     python -I 14_weekly_joint_campaign_reasons.py --catalog-dir CATALOG_RUN_DIR --relabel-from EARLIER_OUT
     --out OUTDIR [--ledger LEDGER --names NAMES [--names-sparse]] [--rules ...]
     (--ledger is needed when the earlier run has no ledger facts)
"""
from __future__ import annotations

import os
for _v in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
    os.environ.setdefault(_v, '1')

import argparse
import hashlib
import json
import multiprocessing as mp
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

from mmm_core import campaign_catalog as cc
from mmm_core import campaign_reasons as cre
from mmm_core import campaign_routing as cr
from mmm_core import weekly_joint as wj

CODE_VERSION = 'campaign_reasons_weekly_joint_v3_20261105'
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
        res.append(cre.decompose(camp, arr, draw))
    return idx_chunk, res


def main() -> None:
    ap = argparse.ArgumentParser()
    for a in ('--out', '--catalog-dir'):
        ap.add_argument(a, required=True)
    for a in ('--panel', '--national', '--npz', '--ledger', '--targets', '--city-map'):
        ap.add_argument(a, default=None, help='required unless --relabel-from')
    ap.add_argument('--relabel-from', default=None,
                    help='output folder of an earlier green run for the same catalog: reuse its numbers, new labels only')
    ap.add_argument('--rules', default=str(cre.DEFAULT_RULES))
    ap.add_argument('--media-units-daily', default=None, help='accepted for the same command line as 09; not used')
    ap.add_argument('--names', default=None)
    ap.add_argument('--names-sparse', action='store_true')
    ap.add_argument('--roas-draws', default=None, help='accepted for the same command line as 09; not used')
    ap.add_argument('--draws', type=int, default=400)
    ap.add_argument('--procs', type=int, default=4)
    ap.add_argument('--top-units', type=int, default=None)
    ap.add_argument('--adstock', default='short', choices=['short', 'long'])
    ap.add_argument('--roas-scale', default='equal', choices=['equal', 'turnover', 'gamma'])
    ap.add_argument('--media-geo', default='unit', choices=['unit', 'tier'])
    ap.add_argument('--only', default='', help='test: comma-separated campaign numbers')
    ap.add_argument('--agglo', action='store_true')
    ap.add_argument('--m-ref', default=None)
    ap.add_argument('--tail-weeks', type=int, default=0)
    ap.add_argument('--tail-other', default='analog', choices=['analog', 'none'])
    ap.add_argument('--tolerance', type=float, default=1e-6, help='relative: kept effect vs catalog turnover median')
    a = ap.parse_args()
    if not a.relabel_from:
        missing = [k for k in ('panel', 'national', 'npz', 'ledger', 'targets', 'city_map') if not getattr(a, k)]
        if missing:
            ap.error('needed for a full run: ' + ', '.join('--' + k.replace('_', '-') for k in missing))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=False)
    logf = open(out / 'reasons_run.log', 'a', buffering=1)

    def log(*x):
        s = time.strftime('%H:%M:%S') + ' ' + ' '.join(str(v) for v in x)
        print(s, flush=True)
        logf.write(s + '\n')

    T0 = time.time()
    rules = cre.load_rules(a.rules)
    catalog = json.loads((Path(a.catalog_dir) / 'catalog_results.json').read_text(encoding='utf-8'))
    cat_meta = catalog['meta']
    if a.relabel_from:
        relabel(a, out, rules, catalog, log, T0)
        return
    # the catalog run must be the same configuration
    for key, mine in (('adstock', a.adstock), ('roas_scale', a.roas_scale), ('media_geo', a.media_geo),
                      ('agglo', bool(a.agglo)), ('m_ref', a.m_ref), ('top_units', a.top_units),
                      ('tail_weeks', a.tail_weeks), ('n_draws', None)):
        if key == 'n_draws':
            continue
        theirs = cat_meta.get(key)
        if key == 'tail_weeks' and theirs is None:
            theirs = 0
        if key == 'agglo' and theirs is None:  # catalogs built before --agglo existed
            theirs = False
        if theirs != mine:
            raise SystemExit(f'catalog run differs: {key} = {theirs!r}, here {mine!r}')
    for key, path in (('panel', a.panel), ('national', a.national), ('npz', a.npz), ('ledger', a.ledger),
                      ('targets', a.targets), ('city_map', a.city_map)):
        want = cat_meta.get('inputs', {}).get(key, {}).get('sha256')
        if want and want != sha(path):
            raise SystemExit(f'catalog run used another {key} (sha differs)')
    checks = {}

    # ---- model data and campaigns: exactly as 09
    d = wj.prepare(a.panel, a.national, top_units_per_segment=a.top_units, m_ref_csv=a.m_ref)
    arr = wj.model_arrays(d, adstock=a.adstock, roas_scale=a.roas_scale, media_geo=a.media_geo)
    log(f'model data: {len(d.ad_units)} units, {len(d.weeks)} weeks, {len(d.obs)} fit rows')
    led, directory = cre.load_campaign_ledger(a.ledger, a.names, a.names_sparse)
    n = len(directory)
    units = cr.load_units(a.targets)
    cmap = pd.read_csv(a.city_map, encoding='utf-8-sig')
    routed, unmod = cr.route_media(led[cr.LEDGER_COLS + ['cat']], units, dict(zip(cmap.city, cmap.oblast)), ['cat'],
                                   agglo=a.agglo)
    present = cc.present_cells(a.panel, d)
    tail = None
    if a.tail_weeks > 0:
        sp = cc.campaign_spend(routed, units, d, cc.present_tail(present, a.tail_weeks), n,
                               weeks=cc.tail_weeks(d, a.tail_weeks))
        tail = cc.tail_rows(d, arr, a.tail_weeks)
    else:
        sp = cc.campaign_spend(routed, units, d, present, n)
    camp = cc.Campaigns(d, arr, sp['cells'], n, tail=tail, tail_other=a.tail_other)
    by_id = same_numbers(directory, catalog)
    log(f'campaigns: {n}, arrays ready, {time.time() - T0:.0f} s')

    # ---- draws: the same indices as the catalog run
    post = np.load(a.npz)
    keys = wj.roas_keys(arr)
    flat = {k: post[k].reshape((-1,) + post[k].shape[2:]) for k in keys}
    nd = flat['alpha'].shape[0]
    if int(cat_meta['n_draws']) != min(a.draws, nd):
        raise SystemExit(f'catalog run used {cat_meta["n_draws"]} draws, here {min(a.draws, nd)}')
    idx = np.linspace(0, nd - 1, min(a.draws, nd)).astype(int)
    if a.only:
        want = {int(x) for x in a.only.split(',')}
        keep = set(directory.cat[directory.id.isin(want)])
        camp.items = [it if k in keep else None for k, it in enumerate(camp.items)]

    draw0 = {k: np.asarray(flat[k][idx[0]]) for k in keys}
    x0 = cre.adstock_np(arr['spend_norm'], np.asarray(draw0['alpha']), camp.L, camp.pad)
    s0 = cc.adstock_sat_np(arr['spend_norm'], np.asarray(draw0['alpha']), np.asarray(draw0['lam']), camp.L, camp.pad)
    checks['adstock_split_max_abs'] = float(np.abs((1 - np.exp(-x0 / np.asarray(draw0['lam'])[None, None, :])) - s0).max())

    G.update(camp=camp, arr=arr, flat=flat, keys=keys)
    D = len(idx)
    S, C = len(wj.SEGMENTS), len(wj.CHANNELS)
    lin, alone, loo, loo_tail = (np.zeros((D, n)) for _ in range(4))
    sc_sum = {key: np.zeros((n, S, C)) for key in ('lin_sc', 'alone_sc', 'loo_sc')}
    unit_sum: dict[int, np.ndarray] = {}
    pos = {int(i): t for t, i in enumerate(idx)}
    chunks = [list(map(int, c)) for c in np.array_split(idx, max(1, min(len(idx), a.procs * 8)))]
    T1 = time.time()
    with mp.get_context('fork').Pool(a.procs) as pool:
        for m, (ch, res) in enumerate(pool.imap_unordered(work, chunks), 1):
            for i, r in zip(ch, res):
                t = pos[i]
                lin[t], alone[t], loo[t], loo_tail[t] = r['lin'], r['alone'], r['loo'], r['loo_tail']
                for key in sc_sum:
                    sc_sum[key] += r[key]
                for k, v in r['units'].items():
                    unit_sum[k] = unit_sum.get(k, 0.0) + v
            if m % max(1, len(chunks) // 10) == 0:
                log(f'draws {m}/{len(chunks)} chunks, {time.time() - T1:.0f} s')
    log(f'{D} draws x {n} campaigns: {time.time() - T1:.0f} s')

    # ---- checks: order of the three effects in every draw; kept effect == catalog turnover
    tol = lambda x: 1e-9 * np.abs(x) + 1e-6
    checks['loo_le_alone_violations'] = int((loo > alone + tol(alone)).sum())
    checks['alone_le_lin_violations'] = int((alone > lin + tol(lin)).sum())
    diffs = []
    for k in range(n):
        if camp.items[k] is None:
            continue
        ref = catalog['results'][str(k)]['turnover']
        if ref is None or ref[1] is None:
            continue
        mine = float(np.percentile(loo[:, k], 50))
        diffs.append(abs(mine - float(ref[1])) / max(abs(float(ref[1])), 1.0))
    checks['kept_vs_catalog_turnover_max_rel'] = float(max(diffs)) if diffs else None
    checks['kept_vs_catalog_campaigns'] = len(diffs)
    failed = [key for key in ('loo_le_alone_violations', 'alone_le_lin_violations') if checks[key]]
    if checks['adstock_split_max_abs'] > 1e-9:
        failed.append('adstock_split_max_abs')
    if checks['kept_vs_catalog_turnover_max_rel'] is None or checks['kept_vs_catalog_turnover_max_rel'] > a.tolerance:
        failed.append('kept_vs_catalog_turnover_max_rel')
    log('checks:', json.dumps(checks))

    # ---- money the model sees, by campaign x segment x model channel
    seen_sc = np.zeros((n, S, C))
    seg_idx = {s: i for i, s in enumerate(wj.SEGMENTS)}
    for k, g in sp['cells'].items():
        g = g[g.kind == 'present']
        for (s, j), v in g.groupby(['segment', 'j']).budget.sum().items():
            seen_sc[k, seg_idx[s], int(j)] += float(v)
    bud = led.groupby('cat').budget.sum().reindex(range(n), fill_value=0.0).to_numpy()
    modeled = np.array([camp.items[k] is not None and seen_sc[k].sum() > 0 for k in range(n)])
    lin_sc_mean = sc_sum['lin_sc'] / D
    seen_tot_sc = seen_sc[modeled].sum(0)
    typical_sc = np.divide(lin_sc_mean[modeled].sum(0), seen_tot_sc, out=np.full((S, C), np.nan), where=seen_tot_sc > 0)
    typ_rows = [dict(segment=s, channel=ch, first_ruble_roas=float(typical_sc[si, j]),
                     campaigns_seen_money_mln=float(seen_tot_sc[si, j]) / 1e6)
                for si, s in enumerate(wj.SEGMENTS) for j, ch in enumerate(wj.CHANNELS) if seen_tot_sc[si, j] > 0]
    pd.DataFrame(typ_rows).to_csv(out / 'typical_first_ruble.csv', index=False)

    unit_names = [cc.pretty_geo(x) for x in d.ad_units.unit_label]
    entries = {}
    for k in range(n):
        number = int(by_id[k])
        entry = dict(number=number, modeled=bool(modeled[k]), factors=None, reasons=[], own_loss_cities=[],
                     overlap_loss_cities=[])
        if modeled[k]:
            seen = float(seen_sc[k].sum())
            expected = float(np.nansum(seen_sc[k] * np.nan_to_num(typical_sc)))
            f = cre.factors(budget=float(bud[k]), seen=seen, lin=lin[:, k], alone=alone[:, k], loo=loo[:, k],
                            loo_tail=loo_tail[:, k], expected_lin=expected)
            if f:
                us = unit_sum[k] / D
                names = [unit_names[a_] for a_ in camp.items[k]['units']]
                entry.update(factors=f, own_loss_cities=cre.top_units(names, us[0] - us[1]),
                             overlap_loss_cities=cre.top_units(names, us[1] - us[2]))
        entries[str(number)] = entry
    facts = cre.facts_by_number(cre.ledger_facts(led, n), by_id)
    for number, entry in entries.items():
        entry['facts'] = facts[number]
    meta = dict(code_version=CODE_VERSION, n_draws=D, decomposition_seconds=round(time.time() - T0),
                code_sha256={p.name: sha(p) for p in [Path(__file__), Path(cre.__file__), Path(cc.__file__),
                                                      Path(cr.__file__), Path(wj.__file__)]})
    finish(a, out, rules, catalog, entries, checks, failed, meta, log, T0)


def same_numbers(directory: pd.DataFrame, catalog: dict) -> dict[int, int]:
    """cat -> catalog number; stops when the ledger gives other campaigns than the catalog run."""
    by_id = {int(k): int(v) for k, v in zip(directory.cat, directory.id)}
    n = len(directory)
    if set(map(int, catalog['results'])) != set(range(n)) or any(
            int(catalog['results'][str(k)]['id']) != by_id[k] for k in range(n)):
        raise SystemExit('campaign numbers differ from the catalog run')
    return by_id


def relabel(a, out: Path, rules: dict, catalog: dict, log, T0: float) -> None:
    """New labels on the numbers of an earlier green run for the same catalog (a new rule file version).
    The ledger facts come from --ledger (with --names as for 09) or from the earlier run when it has them."""
    src = Path(a.relabel_from)
    prev = json.loads((src / 'catalog_reasons.json').read_text(encoding='utf-8'))
    prev_checks = json.loads((src / 'checks.json').read_text(encoding='utf-8'))
    if prev_checks.get('failed'):
        raise SystemExit(f'{src}: that run failed its checks: {prev_checks["failed"]}')
    if prev['meta'].get('catalog_results_sha256') != sha(Path(a.catalog_dir) / 'catalog_results.json'):
        raise SystemExit(f'{src}: computed for another catalog run (catalog_results.json sha differs)')
    numbers = {str(int(row['id'])) for row in catalog['results'].values()}
    if set(prev['campaigns']) != numbers:
        raise SystemExit(f'{src}: campaign numbers differ from the catalog run')
    keep = ('number', 'modeled', 'factors', 'facts', 'own_loss_cities', 'overlap_loss_cities')
    entries = {num: {key: e.get(key) for key in keep} for num, e in prev['campaigns'].items()}
    for e in entries.values():
        e['reasons'] = []
        e['factors'] = {key: v for key, v in (e['factors'] or {}).items()} or None
    ledger_meta = None
    if a.ledger:
        led, directory = cre.load_campaign_ledger(a.ledger, a.names, a.names_sparse)
        by_id = same_numbers(directory, catalog)
        budgets = led.groupby('cat').budget.sum()
        gap = max(abs(float(budgets.get(k, 0.0)) - float(catalog['results'][str(k)]['budget'])) for k in by_id)
        if gap > 1.0:
            raise SystemExit(f'ledger budgets differ from the catalog run by up to {gap:.2f} rub')
        facts = cre.facts_by_number(cre.ledger_facts(led, len(directory)), by_id)
        for number, entry in entries.items():
            entry['facts'] = facts[number]
        ledger_meta = dict(path=str(a.ledger), sha256=sha(a.ledger) if Path(a.ledger).is_file() else None,
                           names=str(a.names) if a.names else None, names_sparse=bool(a.names_sparse),
                           max_budget_gap_rub=gap)
        log(f'ledger facts: {len(facts)} campaigns, budgets match the catalog (max gap {gap:.3f} rub)')
    elif any(e['facts'] is None for e in entries.values()):
        raise SystemExit(f'{src}: the earlier run has no ledger facts; pass --ledger (and --names as for 09)')
    shutil.copy2(src / 'typical_first_ruble.csv', out / 'typical_first_ruble.csv')
    checks = {key: v for key, v in prev_checks['checks'].items() if key != 'reason_counts'}
    meta = dict(code_version=CODE_VERSION, n_draws=prev['meta'].get('n_draws'), relabel_from=str(src),
                relabel_from_meta=prev['meta'], relabel_ledger=ledger_meta,
                code_sha256={p.name: sha(p) for p in [Path(__file__), Path(cre.__file__)]})
    log(f'relabel: {len(entries)} campaigns from {src}')
    finish(a, out, rules, catalog, entries, checks, [], meta, log, T0)


def finish(a, out: Path, rules: dict, catalog: dict, entries: dict, checks: dict, failed: list, meta: dict, log,
           T0: float) -> None:
    """Norms by main channel, reasons, and the output files (the same for a full run and a relabel)."""
    names = {}
    for row in catalog['results'].values():
        number = str(int(row['id']))
        entries[number]['main_channel'], entries[number]['main_nationwide'] = cre.main_channel_of(row.get('card') or {})
        names[number] = str(row.get('name') or '')
    tail_weeks = int(catalog['meta'].get('tail_weeks') or 0)
    norms = cre.label_catalog(entries, rules, tail_weeks=tail_weeks, names=names)
    pd.DataFrame(norms).to_csv(out / 'reason_norms.csv', index=False, encoding='utf-8-sig')
    rows = []
    for number in sorted(entries, key=int):
        entry = entries[number]
        fx = entry['factors'] or {}
        facts = entry.get('facts') or {}
        r4 = lambda key: round(fx[key], 4) if fx and isinstance(fx.get(key), float) and np.isfinite(fx[key]) else ''  # noqa: E731
        r4f = lambda key: round(facts[key], 4) if isinstance(facts.get(key), float) and np.isfinite(facts[key]) else ''  # noqa: E731
        rows.append(dict(номер=int(number), кампания=names.get(number, ''), модель_считает=int(bool(entry['modeled'])),
                         основной_канал=entry.get('main_channel', ''),
                         эффект_первых_рублей_млн=round(fx['potential_turnover_rub'] / 1e6, 4) if fx else '',
                         сохранено_доля=r4('kept_share'), насыщение_кампанией_доля=r4('own_loss_share'),
                         пересечения_доля=r4('overlap_loss_share'), норма_сохранено=r4('norm_kept_share'),
                         норма_насыщение=r4('norm_own_loss_share'), норма_пересечения=r4('norm_overlap_loss_share'),
                         отдача_первых_рублей=r4('first_ruble_roas'), обычная_отдача_каналов=r4('typical_first_ruble_roas'),
                         города_против_обычного=r4('geo_factor'), деньги_вне_модели_доля=r4('unseen_share'),
                         хвост_доля=r4('tail_share'),
                         мест_с_деньгами=facts.get('n_geo', ''), главное_место=facts.get('top_geo', ''),
                         доля_бюджета_в_главном_месте=r4f('top_geo_share'), плотность_к_обычной=r4('density_ratio'),
                         недель=facts.get('weeks_n', ''), за_две_недели_доля=r4f('burn_2w_share'),
                         сосед=names.get(str(facts.get('neighbor_number')), ''),
                         сосед_млн=round(facts['neighbor_rub'] / 1e6, 4) if facts.get('neighbor_number') else '',
                         насыщение_больше_всего=', '.join(entry['own_loss_cities']),
                         пересечения_больше_всего=', '.join(entry['overlap_loss_cities']),
                         причины=' | '.join(r['code'] for r in entry['reasons']),
                         причины_текст=' '.join(r['display_text'] for r in entry['reasons'])))
    pd.DataFrame(rows).to_csv(out / 'catalog_reasons.csv', index=False, encoding='utf-8-sig')
    counts = {}
    for e in entries.values():
        for r in e['reasons']:
            counts[r['code']] = counts.get(r['code'], 0) + 1
    checks['reason_counts'] = counts
    meta.update(rules_version=rules['version'], rules_sha256=sha(a.rules), catalog_dir=str(a.catalog_dir),
                catalog_code_version=catalog['meta'].get('code_version'),
                catalog_results_sha256=sha(Path(a.catalog_dir) / 'catalog_results.json'),
                n_campaigns=len(entries), tail_weeks=tail_weeks, calc_seconds=round(time.time() - T0),
                finished_utc=time.strftime('%d.%m.%Y %H:%M', time.gmtime()))
    (out / 'catalog_reasons.json').write_text(json.dumps(dict(meta=meta, checks=checks, campaigns=entries),
                                                         ensure_ascii=False, indent=1, default=float), encoding='utf-8')
    (out / 'checks.json').write_text(json.dumps(dict(meta=meta, checks=checks, failed=failed), ensure_ascii=False,
                                                indent=1, default=float), encoding='utf-8')
    log('reasons:', json.dumps(counts, ensure_ascii=False))
    if failed:
        log('FAILED:', failed)
        raise SystemExit(2)
    log(f'done in {time.time() - T0:.0f} s')

if __name__ == '__main__':
    main()
