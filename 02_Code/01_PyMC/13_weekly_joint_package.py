"""Serving package of the weekly joint model (Заноза) for the platform forecast, and its parity checks.

    build  : package from a finished fit folder (fit card, posterior npz, roas table) + the panel it was fitted on.
             The output folder must not exist; the fit folder is only read.
    check  : the package against the model, through the platform's own forecast entry point
             (ModelPackage -> prepare_campaign_from_config -> run_forecast_from_flighting -> WeeklyJointEngine):
               1. ROAS by segment x channel recomputed from the package alone == roas table of the fit (200 draws);
               2. the plan of 07_weekly_joint_plan_forecast.py through the platform == the 07 output
                  (total median and 90% interval to 1e-4; channels within 3%: 07 shows each channel alone, the
                  platform splits the joint effect of a unit-week over its channels so that cells add up);
               3. directions do not mix: the plan's ТС5/Онлайн numbers stay the same when the same rows are added
                  for ТС5/Оффлайн, and every effect row belongs to the segment of its own spend;
               4. the package files are unchanged after the run (lineage check);
               5. a plan's Indoor rows go into OOH_Total, as the model merged them (same total when half of the OOH
                  money is labelled Indoor).
             Writes check_card.json, the platform forecast outputs and a short CSV per check into --out.

Run: python -I 13_weekly_joint_package.py build --fit-dir FIT --profile production --panel P --national N --out PKG
     python -I 13_weekly_joint_package.py check --package PKG --plan PLAN.csv --plan-07-dir DIR07 --out OUT
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))     # run with python -I: the script folder is not on the path

import numpy as np
import pandas as pd

CODE_VERSION = 'weekly_joint_package_v1_20261105'


def build(a: argparse.Namespace) -> None:
    from mmm_core.weekly_package import build_weekly_package
    m = build_weekly_package(a.fit_dir, a.profile, a.panel, a.national, a.out, model_name=a.model_name,
                             model_run_id=a.model_run_id, source_code_version=a.source_code_version,
                             builder_code_version=CODE_VERSION)
    print(json.dumps({k: m[k] for k in ('package_type', 'model_name', 'model_run_id', 'n_draws', 'fit_weeks',
                                        'channels', 'activation_status', 'package_input_fingerprint')},
                     ensure_ascii=False, indent=1))


def _platform_forecast(pkg: Path, plan_csv: Path, out: Path, run_id: str, n_samples: int) -> dict:
    from mmm_core.campaign_plan import prepare_campaign_from_config
    from mmm_core.forecast_engine import run_forecast_from_flighting
    from mmm_core.model_package_reader import ModelPackage
    work = out / run_id
    work.mkdir(parents=True, exist_ok=False)
    config = {'run_id': run_id,
              'paths': {'campaign_brief': str(plan_csv), 'validated_output_dir': str(work / 'validated'),
                        'flighting_output_dir': str(work / 'flighting')},
              'validation': {'fail_on_parse_issues': True, 'fail_on_unsupported': True},
              'forecast': {'posterior_samples': n_samples, 'random_seed': 42}}
    cfg_path = work / 'config.json'
    cfg_path.write_text(json.dumps(config, ensure_ascii=False, indent=1), encoding='utf-8')
    package = ModelPackage.from_run_dir(pkg, require_posterior_ready=True, validate_hash=True)
    package.check_card(purpose='forecast')
    prep = prepare_campaign_from_config(config, cfg_path, package, work, purpose='forecast')
    card = run_forecast_from_flighting(pkg, prep.flighting_path, work, run_id, n_samples=n_samples, seed=42)
    return dict(card=card, flighting=prep.flighting_path, summary=pd.read_csv(card['outputs']['summary_csv']),
                detail=pd.read_csv(card['outputs']['detail_csv']))


def check(a: argparse.Namespace) -> None:
    from mmm_core.forecast_engine import read_daily_flighting
    from mmm_core.weekly_engine import WeeklyJointEngine
    from mmm_core.weekly_package import PACKAGE_FILES, sha256_file
    pkg, out = Path(a.package).resolve(), Path(a.out).resolve()     # platform paths resolve against the project root
    out.mkdir(parents=True, exist_ok=False)
    before = {n: sha256_file(pkg / n) for n in PACKAGE_FILES + ['model_manifest.json']}
    eng = WeeklyJointEngine.from_run_dir(pkg)
    res: dict = dict(code_version=CODE_VERSION, package=str(pkg), model=eng.package.manifest.get('model_run_id'))

    # 1. ROAS table of the fit from the package alone
    rep = eng.replay_roas_table(200)
    tab = pd.read_csv(pkg / 'model_roas_table.csv')
    m = rep.merge(tab[['segment', 'channel', 'roas_q05', 'roas_median', 'roas_q95', 'spend_rub']],
                  on=['segment', 'channel'], how='outer', suffixes=('_package', '_fit'))
    for c in ('roas_q05', 'roas_median', 'roas_q95', 'spend_rub'):
        m[f'{c}_rel_diff'] = (m[f'{c}_package'] / m[f'{c}_fit'] - 1).abs()
    m.to_csv(out / 'check1_roas_table_parity.csv', index=False)
    worst = float(m[[f'{c}_rel_diff' for c in ('roas_q05', 'roas_median', 'roas_q95', 'spend_rub')]].max().max())
    res['check1_roas_table'] = dict(rows=int(len(m)), missing=int(m.isna().any(axis=1).sum()),
                                    max_rel_diff=worst, passed=bool(worst < 2e-3 and not m.isna().any(axis=1).any()))
    print(f'check 1 ROAS table: max rel diff {worst:.2e}', flush=True)

    # 2. the 07 plan through the platform entry point
    plan_csv = Path(a.plan).resolve()
    pf = _platform_forecast(pkg, plan_csv, out, 'plan07', a.draws)
    s = pf['summary']
    tot = s[(s.channel == '__TOTAL__') & (s.segment == '__ALL__')].iloc[0]
    _, _, draws = eng.forecast_daily_rows(read_daily_flighting(pf['flighting']), n_samples=a.draws,
                                          return_campaign_draws=True)
    e = draws.groupby('draw_index').total_effect.sum().to_numpy()
    r07 = pd.read_csv(Path(a.plan_07_dir) / 'plan_forecast_by_channel.csv')
    t07 = r07[r07.channel.str.startswith('ВСЕГО')].iloc[0]
    platform_total = dict(budget_rub=float(s[(s.channel == '__TOTAL__') & (s.segment == '__ALL__')].spend_rub.iloc[0]),
                          effect_q05=float(np.quantile(e, .05)), effect_median=float(np.quantile(e, .5)),
                          effect_q95=float(np.quantile(e, .95)), effect_p50_summary=float(tot.total_effect_p50))
    rel = {k: abs(platform_total[k] / float(t07[k]) - 1) for k in ('budget_rub', 'effect_q05', 'effect_median', 'effect_q95')}
    chans = (s[(s.channel != '__TOTAL__')].groupby('channel', as_index=False)
             .agg(budget_rub=('spend_rub', 'sum'), effect_p50_platform=('total_effect_p50', 'sum')))
    ch = chans.merge(r07[['channel', 'budget_rub', 'effect_median']], on='channel', suffixes=('', '_07'))
    ch['rel_diff'] = (ch.effect_p50_platform / ch.effect_median - 1).abs()
    ch.to_csv(out / 'check2_plan07_channels.csv', index=False)
    res['check2_plan07'] = dict(platform=platform_total, plan07={k: float(t07[k]) for k in platform_total if k in t07},
                                rel_diff=rel, channel_max_rel_diff=float(ch.rel_diff.max()),
                                passed=bool(max(rel.values()) < 1e-4 and ch.rel_diff.max() < 0.03))
    print('check 2 plan 07:', json.dumps(res['check2_plan07'], ensure_ascii=False, default=float), flush=True)

    # 3. directions do not mix
    plan = pd.read_csv(plan_csv)
    seg_from, seg_to = 'ТС5/Онлайн', 'ТС5/Оффлайн'
    both = [(s_, g) for s_, g in eng.key if s_ == seg_to]
    add = plan[(plan.segment == seg_from) & plan.geo.isin({g for _, g in both})].assign(segment=seg_to)
    plan2 = pd.concat([plan, add], ignore_index=True)
    p2 = out / 'plan_with_offline_copy.csv'
    plan2.to_csv(p2, index=False)
    pf2 = _platform_forecast(pkg, p2, out, 'plan07_plus_offline', a.draws)
    d1, d2 = pf['detail'], pf2['detail']
    k = ['segment', 'geo', 'channel']
    j = d1.merge(d2, on=k, suffixes=('', '_2'))
    online_same = float((j.total_effect_p50_2 / j.total_effect_p50 - 1).abs().max())
    spend_seg = pd.read_csv(pf2['flighting']).groupby(['segment', 'geo', 'channel']).budget_rub.sum()
    stray = [tuple(r) for r in d2[k].itertuples(index=False) if tuple(r) not in spend_seg.index]
    res['check3_directions'] = dict(online_rows=int(len(j)), online_max_rel_change=online_same,
                                    offline_rows=int((d2.segment == seg_to).sum()), rows_without_own_spend=len(stray),
                                    passed=bool(online_same < 1e-9 and not stray and len(j) == len(d1)))
    print('check 3 directions:', res['check3_directions'], flush=True)

    # 5. a plan's Indoor rows land on the model channel they were fitted as (OOH_Total): half of every OOH row moved
    #    to Indoor gives the same total, and the Indoor rows carry their own money
    if eng.aliases:
        alias, target = next(iter(eng.aliases.items()))
        half = plan[plan.channel == target].assign(budget_rub=lambda x: x.budget_rub / 2)
        plan3 = pd.concat([plan[plan.channel != target], half, half.assign(channel=alias)], ignore_index=True)
        p3 = out / 'plan_with_indoor_half.csv'
        plan3.to_csv(p3, index=False)
        pf3 = _platform_forecast(pkg, p3, out, 'plan07_indoor_half', a.draws)
        s3 = pf3['summary']
        t3 = float(s3[(s3.channel == '__TOTAL__') & (s3.segment == '__ALL__')].total_effect_p50.iloc[0])
        t1 = float(tot.total_effect_p50)
        ind = s3[s3.channel == alias]
        res['check5_channel_alias'] = dict(alias=alias, model_channel=target, total_rel_change=abs(t3 / t1 - 1),
                                           alias_spend_rub=float(ind.spend_rub.sum()),
                                           passed=bool(abs(t3 / t1 - 1) < 1e-9 and len(ind) > 0))
        print('check 5 channel alias:', res['check5_channel_alias'], flush=True)

    # 4. lineage
    after = {n: sha256_file(pkg / n) for n in before}
    res['check4_package_unchanged'] = dict(passed=before == after)
    res['passed_all'] = all(v.get('passed') for kk, v in res.items() if kk.startswith('check'))
    (out / 'check_card.json').write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding='utf-8')
    print('ALL PASSED' if res['passed_all'] else 'SOME CHECKS FAILED', flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build')
    b.add_argument('--fit-dir', required=True)
    b.add_argument('--profile', default='production')
    b.add_argument('--panel', required=True)
    b.add_argument('--national', required=True)
    b.add_argument('--out', required=True)
    b.add_argument('--model-name', default='Заноза')
    b.add_argument('--model-run-id', default=None)
    b.add_argument('--source-code-version', default='')
    c = sub.add_parser('check')
    c.add_argument('--package', required=True)
    c.add_argument('--plan', required=True, help='the plan CSV that 07 forecast (campaign_name, start_date, end_date, segment, geo, channel, budget_rub)')
    c.add_argument('--plan-07-dir', required=True, help='07 output folder of the same model and plan (plan_forecast_by_channel.csv)')
    c.add_argument('--out', required=True)
    c.add_argument('--draws', type=int, default=400, help='as 07 (400)')
    a = ap.parse_args()
    build(a) if a.cmd == 'build' else check(a)


if __name__ == '__main__':
    main()
