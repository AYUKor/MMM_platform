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
                  money is labelled Indoor);
               6. the platform optimizer (run_optimizer_from_flighting + marketer report) on a test plan: the 07 plan
                  at 40% of its money, a copy for ТС5/Оффлайн, 30% of OOH in three cities labelled Indoor and national
                  TV rows in three cities at twice the most ever spent there. The search kernel of a cell equals the
                  forecast of that cell alone; every candidate keeps the money of its own direction; Indoor is
                  optimized as OOH_Total; national TV stays at plan in every optimized candidate and does not stop
                  the search; every optimized cell stays within the corridor around its plan budget; the adaptive
                  search runs for each direction; the report's sheet 00 carries the model caveats.
             Writes check_card.json, the platform forecast outputs and a short CSV per check into --out.

Run: python -I 13_weekly_joint_package.py build --fit-dir FIT --profile production --panel P --national N --out PKG
     python -I 13_weekly_joint_package.py check --package PKG --plan PLAN.csv --plan-07-dir DIR07 --out OUT \
            [--optimizer-dir DIR_WITH_optimizer_decision_policy_v3.yaml_AND_marketer_report.py]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))     # run with python -I: the script folder is not on the path

import numpy as np
import pandas as pd

CODE_VERSION = 'weekly_joint_package_v3_20261105'


def build(a: argparse.Namespace) -> None:
    from mmm_core.weekly_package import build_weekly_package
    m = build_weekly_package(a.fit_dir, a.profile, a.panel, a.national, a.out, model_name=a.model_name,
                             model_run_id=a.model_run_id, source_code_version=a.source_code_version,
                             builder_code_version=CODE_VERSION)
    print(json.dumps({k: m[k] for k in ('package_type', 'model_name', 'model_run_id', 'n_draws', 'fit_weeks',
                                        'channels', 'activation_status', 'package_input_fingerprint')},
                     ensure_ascii=False, indent=1))


def _prepare(pkg: Path, plan_csv: Path, work: Path, run_id: str, n_samples: int, purpose: str):
    """The platform's plan preparation (as ac_forecast.py / budget_optimizer.py): daily flighting of the plan."""
    from mmm_core.campaign_plan import prepare_campaign_from_config
    from mmm_core.model_package_reader import ModelPackage
    work.mkdir(parents=True, exist_ok=False)
    config = {'run_id': run_id,
              'paths': {'campaign_brief': str(plan_csv), 'validated_output_dir': str(work / 'validated'),
                        'flighting_output_dir': str(work / 'flighting')},
              'validation': {'fail_on_parse_issues': True, 'fail_on_unsupported': True},
              'forecast': {'posterior_samples': n_samples, 'random_seed': 42}}
    cfg_path = work / 'config.json'
    cfg_path.write_text(json.dumps(config, ensure_ascii=False, indent=1), encoding='utf-8')
    package = ModelPackage.from_run_dir(pkg, require_posterior_ready=purpose == 'forecast', validate_hash=True)
    package.check_card(purpose=purpose, optimizer_policy='balanced')
    return prepare_campaign_from_config(config, cfg_path, package, work, purpose=purpose)


def _platform_forecast(pkg: Path, plan_csv: Path, out: Path, run_id: str, n_samples: int) -> dict:
    from mmm_core.forecast_engine import run_forecast_from_flighting
    work = out / run_id
    prep = _prepare(pkg, plan_csv, work, run_id, n_samples, 'forecast')
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

    # 6. the platform optimizer
    res['check6_optimizer'] = _optimizer_check(eng, pkg, plan, out, a)
    print('check 6 optimizer:', json.dumps(res['check6_optimizer'], ensure_ascii=False, default=float), flush=True)

    # 4. lineage
    after = {n: sha256_file(pkg / n) for n in before}
    res['check4_package_unchanged'] = dict(passed=before == after)
    res['passed_all'] = all(v.get('passed') for kk, v in res.items() if kk.startswith('check'))
    (out / 'check_card.json').write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding='utf-8')
    print('ALL PASSED' if res['passed_all'] else 'SOME CHECKS FAILED', flush=True)


def _optimizer_check(eng, pkg: Path, plan: pd.DataFrame, out: Path, a: argparse.Namespace) -> dict:
    from mmm_core.forecast_engine import _campaign_cell_rows, run_optimizer_from_flighting
    from mmm_core.io import load_config
    opt_dir = Path(a.optimizer_dir).resolve()
    sys.path.insert(1, str(opt_dir))
    from marketer_report import ReportPaths, build_marketer_report

    # test plan: 40% of the 07 money; the same rows for ТС5/Оффлайн where the city is in the model; 30% of OOH in
    # three cities labelled Indoor
    base = plan.assign(budget_rub=(plan.budget_rub * a.optimizer_scale).round())
    off = {g for s_, g in eng.key if s_ == 'ТС5/Оффлайн'}
    copy = base[(base.segment == 'ТС5/Онлайн') & base.geo.isin(off)].assign(segment='ТС5/Оффлайн')
    alias, target = next(iter(eng.aliases.items()))
    m = (base.channel == target) & base.geo.isin(sorted(base.geo.unique())[:3])
    ind = base[m].assign(channel=alias, budget_rub=(base[m].budget_rub * 0.3).round())
    base.loc[m, 'budget_rub'] = base.loc[m, 'budget_rub'] - ind.budget_rub.to_numpy()
    # national TV in three cities at twice the most ever spent there (robust upper week x plan weeks x 2): fixed at plan
    from mmm_core.forecast_engine import _robust_support_upper
    natl_ch = 'Нац_ТВ'
    sb = eng.support_bounds.set_index(['segment', 'geo_label', 'channel'])
    nat_rows = []
    for g in sorted(base.geo.unique())[:3]:
        key = ('ТС5/Онлайн', g, natl_ch)
        if key not in sb.index:
            continue
        r = sb.loc[key]
        up_week = 7.0 * _robust_support_upper(r.daily_spend_p95_rub, r.daily_spend_p99_rub, r.daily_spend_max_rub,
                                              int(r.active_days))
        src = base[(base.geo == g) & (base.segment == 'ТС5/Онлайн')].iloc[0]
        weeks = (pd.Timestamp(src.end_date) - pd.Timestamp(src.start_date)).days / 7.0 + 1
        nat_rows.append(src.to_frame().T.assign(channel=natl_ch, budget_rub=round(2.0 * up_week * weeks)))
    p6 = pd.concat([base, copy, ind] + nat_rows, ignore_index=True)
    p6_path = out / 'plan_optimizer_test.csv'
    p6.to_csv(p6_path, index=False)
    work = out / 'optimizer'
    prep = _prepare(pkg, p6_path, work, 'optimizer_test', a.draws, 'optimizer')
    wf = dict(decision_policy=load_config(opt_dir / 'optimizer_decision_policy_v3.yaml'),
              objective=dict(primary='maximize_incremental_turnover_p50', model_risk_policy='balanced', guardrails={}),
              optimizer=dict(scenario_6=dict(enabled=True, default_method='adaptive_marginal_posterior',
                                             allocation_quantum_rub=100000, beam_width=8, max_candidate_pool=12,
                                             transfer_steps_rub=[5_000_000, 1_000_000, 250_000, 50_000],
                                             support_limits=['p99', 'robust_upper'], final_random_seed=10042)))
    card = run_optimizer_from_flighting(pkg, prep.flighting_path, work, 'optimizer_test', search_candidates=2048,
                                        search_samples=128, final_samples=600, seed=42, finalists=6, workflow_config=wf)
    rep = build_marketer_report(ReportPaths(model_run_dir=pkg, flighting_path=Path(card['optimizer_flighting_path']),
                                            optimizer_output_dir=work, output_xlsx=work / 'marketer_report.xlsx',
                                            run_id='optimizer_test'))
    fl = pd.read_csv(card['optimizer_flighting_path'])
    fl['date'] = pd.to_datetime(fl['date']).dt.date
    al = pd.read_csv(card['outputs']['recommended_allocations_csv'])
    cs = pd.read_csv(card['outputs']['candidate_scores_csv'])
    fs = pd.read_csv(card['outputs']['finalist_summary_csv'])
    seg_of = fl.groupby('campaign_name').segment.agg(lambda x: sorted(set(x)))
    money = fl.groupby('campaign_name').budget_rub.sum()

    # the kernel of a cell == the forecast of the cell alone; all kernels together vs the joint forecast
    camp = str(seg_of.index[0])
    cells = _campaign_cell_rows(fl, camp)
    kern = eng.turnover_response_kernels(fl, cells, camp, n_samples=128)
    worst = 0.0
    for k, (_, c) in zip(kern, cells.iterrows()):
        sub = fl[(fl.campaign_name == camp) & (fl.segment == c.segment) & (fl.geo == c.geo) & (fl.channel == c.channel)]
        _, _, dr = eng.forecast_daily_rows(sub.to_dict('records'), n_samples=128, return_campaign_draws=True)
        e = dr.groupby('draw_index').total_effect.sum().to_numpy()
        worst = max(worst, float(np.max(np.abs(k.response_draws(c.budget_rub) / e - 1))))
    _, _, dr = eng.forecast_daily_rows(fl[fl.campaign_name == camp].to_dict('records'), n_samples=128,
                                      return_campaign_draws=True)
    joint = dr.groupby('draw_index').total_effect.sum().to_numpy()
    sep = sum(k.response_draws(b) for k, b in zip(kern, cells.budget_rub))
    sep_rel = float(np.median(sep / joint) - 1)

    # directions: one segment per candidate, its own money; Indoor inside OOH_Total; national TV fixed
    per = al.groupby(['source_campaign_name', 'candidate_name']).agg(segs=('segment', lambda x: sorted(set(x))),
                                                                     money=('budget_rub', 'sum'),
                                                                     status=('scenario_feasibility_status', 'first'))
    wrong_seg = [i for i, r in per.iterrows() if r.segs != seg_of[i[0]]]
    full = per[per.status == 'feasible_full']
    money_gap = float((full.money - full.index.get_level_values(0).map(money)).abs().max()) if len(full) else 0.0
    natl = [r for r in eng.package.capability_rows if r['channel'] == 'Нац_ТВ']
    # optimized candidates (S5, S6): national TV at plan, every optimize cell inside the corridor
    cur = fl.groupby(['campaign_name', 'segment', 'geo', 'channel']).budget_rub.sum()
    corr = card['weekly_optimizer_plan']['cell_corridor']
    opt = al[al.candidate_name.str.contains('__scenario5_|__scenario6_')].copy()
    opt['plan_rub'] = [cur.get((r.source_campaign_name, r.segment, r.geo, r.channel), 0.0) for r in opt.itertuples()]
    nat_moved = opt[(opt.channel == natl_ch) & ((opt.budget_rub - opt.plan_rub).abs() > 1.0)]
    o = opt[opt.optimizer_policy == 'optimize'].copy()
    # the support cap of the candidate's own limit: a plan cell above history may be cut below the corridor floor
    o['cap'] = [r.robust_support_cap_rub if 'robust_upper' in r.candidate_name else
                r.automatic_support_cap_rub if '_p99' in r.candidate_name else r.safe_support_cap_rub
                for r in o.itertuples()]
    out_corr = o[(o.budget_rub > np.minimum(corr['max_increase_ratio'] * o.plan_rub, o.cap) + 1.0)
                 | (o.budget_rub < np.minimum(corr['min_keep_ratio'] * o.plan_rub, o.cap) - 1.0)]
    nat_plan_rows = int((fl.channel == natl_ch).sum())
    # the report: recommended candidate per direction and the caveats on sheet 00
    recs = pd.read_csv(work / 'marketer_report_recommendations.csv')
    from openpyxl import load_workbook
    sheet0 = ' '.join(str(c.value) for row in load_workbook(rep['output_xlsx'], read_only=True)
                      .worksheets[0].iter_rows() for c in row if c.value is not None)
    caveats = all(w in sheet0 for w in ('отраслев', 'отложенных', 'Вероятность улучшения', 'Ограничения оптимизатора'))
    s6 = {c: int(((cs.campaign_name == c) & cs.candidate_name.str.contains('__scenario6_adaptive_marginal')
                  & (cs.precheck_status == 'scored')).sum()) for c in money.index}
    # what the report recommends per direction (and the reliable rank 1) vs the plan
    tot = fs[(fs.channel == '__TOTAL__') & (fs.segment == '__ALL__')]
    rec = {}
    for c in money.index:
        t = tot[tot.source_campaign_name == c]
        plan_p50 = float(t[t.candidate_name.str.endswith('__scenario1_current_plan')].total_effect_p50.iloc[0])
        chosen = recs[recs.campaign_name == c]
        best_name = str(chosen.candidate_name.iloc[0]) if len(chosen) else str(t.sort_values('optimizer_rank').iloc[0].candidate_name)
        best = t[t.candidate_name == best_name].iloc[0]
        reliable = t.sort_values('optimizer_rank').iloc[0]
        a_best = al[al.candidate_name == best_name].groupby('channel').budget_rub.sum()
        a_plan = fl[fl.campaign_name == c].groupby('channel').budget_rub.sum()
        rec[c] = dict(recommended=best_name.split('__', 1)[1],
                      recommendation_type=str(chosen.recommendation_type.iloc[0]) if len(chosen) and 'recommendation_type' in chosen else '',
                      plan_effect_p50=plan_p50, recommended_effect_p50=float(best.total_effect_p50),
                      gain=float(best.total_effect_p50 / plan_p50 - 1),
                      reliable_rank1=str(reliable.candidate_name).split('__', 1)[1],
                      reliable_rank1_gain=float(reliable.total_effect_p50 / plan_p50 - 1),
                      plan_by_channel=a_plan.round(0).to_dict(), recommended_by_channel=a_best.round(0).to_dict())
    pd.DataFrame([dict(campaign=c, **{k: v for k, v in r.items() if not isinstance(v, dict)}) for c, r in rec.items()]
                 ).to_csv(out / 'check6_optimizer_recommendation.csv', index=False)
    return dict(kernel_alone_max_rel_diff=worst, kernels_sum_vs_joint_median_rel=sep_rel,
                candidates_with_foreign_segment=len(wrong_seg), full_candidates_money_gap_rub=money_gap,
                indoor_rows_in_allocations=int((al.channel == alias).sum()),
                national_tv_rows=len(natl), national_tv_not_fixed=sum(r['optimizer_use'] != 'fixed_at_plan' for r in natl),
                national_tv_plan_rows=nat_plan_rows, national_tv_moved_rows=int(len(nat_moved)),
                corridor=corr, cells_outside_corridor=int(len(out_corr)), report_caveats_on_sheet0=caveats,
                adaptive_candidates_scored=s6, directions=card['weekly_optimizer_plan'], recommendation=rec,
                marketer_report=str(rep['output_xlsx']),
                passed=bool(worst < 1e-9 and abs(sep_rel) < 0.02 and not wrong_seg and money_gap < 1.0
                            and not (al.channel == alias).any() and all(r['optimizer_use'] == 'fixed_at_plan' for r in natl)
                            and all(v > 0 for v in s6.values()) and len(money) == 2 and nat_plan_rows > 0
                            and nat_moved.empty and out_corr.empty and caveats))


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
    c.add_argument('--optimizer-dir', default=str(next((d for d in (Path(__file__).resolve().parent / '02_Budget_optimizer',
                                                                   Path(__file__).resolve().parents[1] / '02_Budget_optimizer')
                                                        if d.is_dir()), Path(__file__).resolve().parents[1] / '02_Budget_optimizer')),
                   help='folder with optimizer_decision_policy_v3.yaml and marketer_report.py')
    c.add_argument('--optimizer-scale', type=float, default=0.4, help='share of the 07 plan money in the optimizer test')
    a = ap.parse_args()
    build(a) if a.cmd == 'build' else check(a)


if __name__ == '__main__':
    main()
