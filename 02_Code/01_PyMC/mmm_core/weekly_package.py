"""Serving package of a weekly joint model (Заноза, v13) for the platform forecast and optimizer.

The daily platform packages (model_package.py) hold one PyMC fit per segment x target with tanh saturation and
per-user denominators. A weekly joint model is different: one numpyro fit of log orders + log check for all four
segments, weekly geometric adstock (8 weeks) and saturation 1 - exp(-x / lam), ROAS level held at the industry
yardstick. Its package is a separate type (manifest package_type = weekly_joint_v1) that the platform reads through
the same entry points (ModelPackage, run_forecast_from_flighting) and serves with weekly_engine.WeeklyJointEngine.

The package is self-contained: the serving side needs numpy and pandas only (no JAX, no panel). Files:

    model_manifest.json            type, model name, labels, segments, channels, weeks, file hashes, fingerprint
    run_config.json                fit card of the source fit + the builder arguments
    capability_matrix.csv          segment x turnover_per_user x channel rows (the platform capability format)
    gate_results.csv, risk_registry.csv, posterior_index.json   platform gate files in their usual format
    historical_support_bounds.csv  per segment x geo x channel: daily-equivalent spend bounds from weekly history
    fit_design_metadata.json       serving inventory (one turnover fit per segment) for the platform checks
    weekly_units.csv               ad units (city or oblast rest within a segment): population, size tier, tau
    weekly_m_ref.csv               typical weekly spend per resident by segment x channel and the channel mask
    weekly_media_draws.npz         all posterior draws of the media parameters (chains flattened, chain-major)
    weekly_baseline_turnover.csv   observed weekly turnover per ad unit (sum of its model units), fit weeks only
    weekly_history_spend.csv       weekly spend per ad unit x channel in the fit window (rub)
    model_roas_table.csv           ROAS by segment x channel of the source fit (the parity reference)
    target_denominator_metadata.csv  per segment x ad unit x fit week: population, buyers, orders (the platform's
                                   denominator format, weekly dates; geo availability and federal allocation read it)
    weekly_geo_routing.csv         per segment x ad unit: kind (city / rest_of_oblast / region / district), its oblast
                                   and population: how media-plan rows on an oblast or a city outside the model reach
                                   the model units (weekly_plan_routing.py, the panel v3 rules)
    weekly_city_oblast_map.csv     city -> oblast dictionary of the panel (city_oblast_map_v8)

Build (on the Mac, read-only for the fit folder; the output folder must not exist):

    python -I 13_weekly_joint_package.py build --fit-dir FIT --profile production --panel P --national N \
        --city-oblast-map MAP --out PKG
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PACKAGE_TYPE = 'weekly_joint_v1'
PACKAGE_SCHEMA_VERSION = '0.5.0'
SERVING_TARGET = 'turnover_per_user'          # the platform serving target id; the effect is total extra turnover
ROAS_LEVEL_LABEL_RU = 'уровень ROAS по отрасли'
ROAS_LEVEL_FLAG = 'ROAS_LEVEL_INDUSTRY_ANCHOR'
OOT_FLAG = 'OOT_NOT_SEALED_Q3_PENDING'
# The pre-registered out-of-time check (train to 28.12.2025 -> Q1 2026, to 29.03.2026 -> Q2 2026) was not passed:
# total turnover within 1-2% on both cuts, but one segment off by about 10% on each (3 of 4 criteria).
OOT_PREREG_FLAG = 'OOT_PREREG_NOT_PASSED'
# National TV is bought for the whole country and the data cannot time it: the optimizer keeps its money as planned.
NATIONAL_TV_CHANNEL = 'Нац_ТВ'
NATIONAL_TV_FLAG = 'NATIONAL_TV_FIXED_AT_PLAN'
PACKAGE_FILES = [
    'run_config.json', 'capability_matrix.csv', 'gate_results.csv', 'risk_registry.csv', 'posterior_index.json',
    'historical_support_bounds.csv', 'fit_design_metadata.json', 'weekly_units.csv', 'weekly_m_ref.csv',
    'weekly_media_draws.npz', 'weekly_baseline_turnover.csv', 'weekly_history_spend.csv', 'model_roas_table.csv',
    'target_denominator_metadata.csv', 'weekly_geo_routing.csv', 'weekly_city_oblast_map.csv',
]
# How plan rows reach the model units (panel v3, campaign_routing.py): physical outdoor on an oblast -> the rest of the
# oblast; TV, radio, digital on an oblast -> by population over its cities and the rest; a city outside the model ->
# the rest of its oblast; РФ -> federal allocation over the units. Panel v4 agglomeration (Moscow / SPb broadcast over
# the oblast too) is not part of the v13 panel.
PLAN_ROUTING = dict(rules_version='panel_v3_plan_routing_v1', physical_channels=['OOH_Total', 'Indoor'], agglo=False)
PANEL_ROUTING_COLUMNS = ['segment', 'unit_label', 'geo_label', 'unit_kind', 'week_start', 'target_valid_week',
                         'population_k', 'buyers_daily_sum', 'n_days_valid', 'orders_cnt', 'turnover_total',
                         'size_tier']
# Media-plan channels the model merged into one of its own (panel v3: Indoor, АЗС and trains are inside OOH_Total).
# The package carries the grouping, so the platform maps a plan's Indoor row to the model channel it was fitted as.
CHANNEL_ALIASES = {'Indoor': 'OOH_Total'}
DRAW_KEYS = ['alpha', 'lam', 'logR_orders', 'sig_seg', 'z_seg', 'sig_tier', 'z_tier', 'sig_unit', 'z_unit', 'R_check',
             'gamma_geo']


class WeeklyPackageError(RuntimeError):
    pass


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(files: dict[str, str | None]) -> str:
    return hashlib.sha256(json.dumps(files, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def is_weekly_manifest(manifest: dict[str, Any] | None) -> bool:
    return str((manifest or {}).get('package_type') or '') == PACKAGE_TYPE


def verify_weekly_package_files(run_dir: str | Path, manifest: dict[str, Any]) -> None:
    """Fail if any package file changed after the manifest was written (the weekly package's own lineage)."""
    run_dir = Path(run_dir)
    expected = manifest.get('files') or {}
    if set(expected) != set(PACKAGE_FILES):
        raise WeeklyPackageError(f'weekly package manifest lists {sorted(expected)}, expected {PACKAGE_FILES}')
    current = {name: sha256_file(run_dir / name) for name in PACKAGE_FILES}
    bad = sorted(name for name in PACKAGE_FILES if current[name] != expected.get(name))
    if bad:
        raise WeeklyPackageError(f'weekly package is stale or incomplete: files differ from the manifest: {bad}')
    if fingerprint(current) != manifest.get('package_input_fingerprint'):
        raise WeeklyPackageError('weekly package fingerprint differs from the manifest')
    if current['run_config.json'] != manifest.get('run_config_sha256'):
        raise WeeklyPackageError('weekly package run_config.json differs from the manifest')


def _support_rows(units: pd.DataFrame, spend: pd.DataFrame, channels: list[str], mask: pd.DataFrame) -> list[dict]:
    """Daily-equivalent spend bounds (weekly spend / 7) per segment x geo x channel over active weeks.

    The platform support check compares the plan's daily spend with p95 / p99 / max of history; the weekly engine
    compares weekly plan spend / 7 with the same numbers, so the thresholds keep their meaning."""
    rows = []
    act = spend[spend.spend_rub > 0]
    grp = {k: g.spend_rub.to_numpy() / 7.0 for k, g in act.groupby(['a', 'channel'])}
    for u in units.itertuples(index=False):
        for c in channels:
            if not mask.loc[(u.segment, c), 'mask']:
                continue
            v = grp.get((u.a, c), np.zeros(0))
            rows.append(dict(segment=u.segment, target=SERVING_TARGET, channel=c, fit_key=fit_key(u.segment),
                             scope='geo', geo_label=u.unit_label, market_size_tier=u.tier,
                             daily_spend_p95_rub=float(np.percentile(v, 95)) if len(v) else 0.0,
                             daily_spend_p99_rub=float(np.percentile(v, 99)) if len(v) else 0.0,
                             daily_spend_max_rub=float(v.max()) if len(v) else 0.0,
                             active_days=int(7 * len(v)), active_weeks=int(len(v)),
                             weekly_spend_median_rub=float(np.median(v) * 7) if len(v) else 0.0,
                             support_basis='weekly_spend_div_7'))
    return rows


def fit_key(segment: str) -> str:
    return f'{segment}|{SERVING_TARGET}'


def _routing_and_denominators(panel: str, units: pd.DataFrame, c2o: dict[str, str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Unit kinds / oblasts of the ad units and their weekly denominators (fit weeks) from the panel."""
    p = pd.read_parquet(panel, columns=PANEL_ROUTING_COLUMNS)
    p = p.merge(units[['segment', 'unit_label']], on=['segment', 'unit_label'], how='inner')
    kind = p.groupby(['segment', 'unit_label'], as_index=False).agg(unit_kind=('unit_kind', 'first'),
                                                                   geo_label=('geo_label', 'first'),
                                                                   kinds_n=('unit_kind', 'nunique'))
    if (kind.kinds_n > 1).any():
        raise WeeklyPackageError('an ad unit has more than one unit kind in the panel')
    routing = units[['segment', 'unit_label', 'pop_k']].merge(kind.drop(columns='kinds_n'), on=['segment', 'unit_label'],
                                                             how='left')
    if routing.unit_kind.isna().any():
        raise WeeklyPackageError(f'ad units missing in the panel: {routing[routing.unit_kind.isna()].unit_label.tolist()[:5]}')
    routing['oblast_label'] = np.where(routing.unit_kind.isin(['rest_of_oblast', 'region']), routing.geo_label,
                                       routing.geo_label.map(c2o).fillna(''))
    routing = routing.rename(columns={'pop_k': 'population_k'})[
        ['segment', 'unit_label', 'unit_kind', 'geo_label', 'oblast_label', 'population_k']]
    v = p[p.target_valid_week.astype(bool)].copy()
    v['unique_users'] = v.buyers_daily_sum / v.n_days_valid.clip(lower=1)
    den = pd.DataFrame(dict(segment=v.segment, geo_label=v.unit_label,
                            date=pd.to_datetime(v.week_start).dt.strftime('%Y-%m-%d'),
                            population_k=v.population_k, market_size_tier=v.size_tier.fillna('').astype(str),
                            unique_users=v.unique_users, orders_cnt=v.orders_cnt, turnover_total=v.turnover_total,
                            avg_basket=v.turnover_total / v.orders_cnt.where(v.orders_cnt > 0)))
    den = den.sort_values(['segment', 'geo_label', 'date']).reset_index(drop=True)
    return routing, den


def build_weekly_package(fit_dir: str | Path, profile: str, panel: str, national: str, out_dir: str | Path, *,
                         city_oblast_map: str | Path, model_name: str = 'Заноза', model_run_id: str | None = None,
                         source_code_version: str = '', builder_code_version: str = '') -> dict[str, Any]:
    from . import weekly_joint as wj                       # numpy / pandas only; JAX is imported lazily there

    fit_dir, out_dir = Path(fit_dir), Path(out_dir)
    if out_dir.exists():
        raise WeeklyPackageError(f'{out_dir} exists: packages are never overwritten, choose a new folder')
    card_path = fit_dir / f'fit_card_{profile}.json'
    npz_path = fit_dir / f'posterior_roas_params_{profile}.npz'
    table_path = fit_dir / f'roas_by_segment_channel_{profile}.csv'
    for p in (card_path, npz_path, table_path, Path(city_oblast_map)):
        if not p.exists():
            raise WeeklyPackageError(f'missing {p}')
    cmap = pd.read_csv(city_oblast_map, encoding='utf-8-sig')
    if list(cmap.columns[:2]) != ['city', 'oblast'] or cmap.city.duplicated().any():
        raise WeeklyPackageError('city -> oblast map: columns city, oblast and one row per city expected')
    card = json.loads(card_path.read_text(encoding='utf-8'))
    for key in ('inject', 'placebo'):
        if card.get(key):
            raise WeeklyPackageError(f'fit card has {key}={card[key]!r}: not a production fit')
    if card.get('fit_window_end'):
        raise WeeklyPackageError('fit with a holdout window end: not a production fit')
    if card.get('m_ref'):
        raise WeeklyPackageError('fits with an external m_ref (v14) are not packaged yet')

    # only the media part is read (units, spend, m_ref, fit rows); trend and season options do not touch it, so the
    # weekly_joint.py of the fit's own code folder (v12-v15) gives the same arrays
    d = wj.prepare(panel, national, fit_window_end=None, top_units_per_segment=None)
    dims = card.get('dims') or {}
    for k, v in (('A', len(d.ad_units)), ('N', len(d.obs)), ('W', len(d.weeks))):
        if k in dims and int(dims[k]) != v:
            raise WeeklyPackageError(f'panel gives {k}={v}, the fit card {dims[k]}: not the panel of this fit')
    if card.get('media_geo', 'unit') not in ('unit', 'tier'):
        raise WeeklyPackageError(f"unknown media_geo {card.get('media_geo')}")
    arr = wj.model_arrays(d, city_wave=False, adstock=card.get('adstock', 'short'),
                          roas_scale=card.get('roas_scale', 'equal'), media_geo=card.get('media_geo', 'unit'))
    if arr.get('adstock_pad_steady'):
        raise WeeklyPackageError('long adstock (pad_steady) is not served by the weekly engine yet')

    post = np.load(npz_path)
    keys = wj.roas_keys(arr)
    draws = {}
    for k in keys:
        x = np.asarray(post[k])
        draws[k] = x.reshape((-1,) + x.shape[2:]).astype(np.float32)      # [chains, draws, ...] -> chain-major
    if not np.asarray(arr['local_c']).any():
        draws.pop('z_unit')                                            # media_geo tier: no own city deviation
    n_draws = int(draws['alpha'].shape[0])

    ad = d.ad_units
    S = wj.SEGMENTS
    C = wj.CHANNELS
    units = pd.DataFrame(dict(a=np.arange(len(ad)), segment=np.array(S)[ad.seg_i.to_numpy()],
                              unit_label=ad.unit_label.to_numpy(), seg_i=ad.seg_i.to_numpy(),
                              tier=ad.tier.fillna('').astype(str).to_numpy(), tier_i=ad.tier_i.to_numpy(),
                              pop_k=ad.pop_k.to_numpy(float), tau=ad.tau.to_numpy(float),
                              geo_ratio=np.asarray(arr['geo_ratio_a'], float)))
    if units.duplicated(['segment', 'unit_label']).any():
        raise WeeklyPackageError('ad unit labels repeat within a segment')
    routing, denominators = _routing_and_denominators(panel, units, dict(zip(cmap.city, cmap.oblast)))
    m_ref = pd.DataFrame([dict(segment=s, channel=c, m_ref=float(d.m_ref[i, j]), mask=int(d.chan_mask[i, j]))
                          for i, s in enumerate(S) for j, c in enumerate(C)])
    o = d.obs
    T = np.exp(o.y_orders.to_numpy(float) + o.y_check.to_numpy(float))
    base = (pd.DataFrame(dict(a=arr['a_i'], week_start=o.week_start.to_numpy(), turnover_rub=T))
            .groupby(['a', 'week_start'], as_index=False).agg(turnover_rub=('turnover_rub', 'sum'),
                                                              obs_n=('turnover_rub', 'size')))
    pop = ad.pop_k.to_numpy(float) * 1000.0
    sp = d.spend_pr * pop[:, None, None] * d.chan_mask[ad.seg_i.to_numpy()][:, None, :]
    ai, wi, ci = np.nonzero(sp > 0)
    spend = pd.DataFrame(dict(a=ai, week_start=d.weeks[wi], channel=np.array(C)[ci], spend_rub=sp[ai, wi, ci]))

    out_dir.mkdir(parents=True)
    run_config = dict(source_fit_dir=str(fit_dir), profile=profile, fit_card=card, panel=str(panel),
                      national=str(national), panel_sha256=sha256_file(Path(panel)),
                      national_sha256=sha256_file(Path(national)), npz_sha256=sha256_file(npz_path),
                      roas_table_sha256=sha256_file(table_path), city_oblast_map=str(city_oblast_map),
                      city_oblast_map_sha256=sha256_file(Path(city_oblast_map)), source_code_version=source_code_version,
                      builder_code_version=builder_code_version)
    (out_dir / 'run_config.json').write_text(json.dumps(run_config, ensure_ascii=False, indent=2, default=str),
                                             encoding='utf-8')
    np.savez_compressed(out_dir / 'weekly_media_draws.npz', **draws)
    units.to_csv(out_dir / 'weekly_units.csv', index=False)
    m_ref.to_csv(out_dir / 'weekly_m_ref.csv', index=False)
    base.assign(week_start=pd.to_datetime(base.week_start).dt.strftime('%Y-%m-%d')).to_csv(
        out_dir / 'weekly_baseline_turnover.csv', index=False)
    spend.assign(week_start=spend.week_start.dt.strftime('%Y-%m-%d')).to_csv(
        out_dir / 'weekly_history_spend.csv', index=False)
    table = pd.read_csv(table_path)
    table.to_csv(out_dir / 'model_roas_table.csv', index=False)
    routing.to_csv(out_dir / 'weekly_geo_routing.csv', index=False)
    denominators.to_csv(out_dir / 'target_denominator_metadata.csv', index=False)
    cmap[['city', 'oblast']].to_csv(out_dir / 'weekly_city_oblast_map.csv', index=False)

    mask_idx = m_ref.set_index(['segment', 'channel'])
    support = _support_rows(units, spend, C, mask_idx)

    gate_cols = ['segment', 'target', 'channel', 'fit_key', 'gate_policy_version', 'fit_allowed_use',
                 'allowed_use', 'forecast_policy', 'optimizer_policy', 'objective_role', 'gate_reason_codes',
                 'marketer_message']
    message = ('Прогноз по недельной модели «%s»: отдача на уровне отраслевого ориентира, распределение по сетям, '
               'городам и неделям из данных. Проверка на отложенных кварталах формально не пройдена: общий оборот '
               'точен до 1-2%%, но по одному сегменту расхождение около 10%%. Закрытая проверка на 3 квартале впереди.'
               % model_name)
    message_natl = message + ' Национальное ТВ покупается на всю страну: оптимизатор оставляет его бюджет как в плане.'
    cap_rows, gate_rows, risk_rows = [], [], []
    for r in m_ref.itertuples(index=False):
        if not r.mask or r.channel == wj.NATIONAL_TV_CROSS:
            continue
        geos_n = int(((units.segment == r.segment)).sum())
        act = spend[(spend.channel == r.channel) & spend.a.isin(units.a[units.segment == r.segment])]
        reasons = f'{ROAS_LEVEL_FLAG}|{OOT_PREREG_FLAG}|{OOT_FLAG}'
        natl = r.channel == NATIONAL_TV_CHANNEL
        opt_use = 'fixed_at_plan' if natl else 'optimize'
        if natl:
            reasons += f'|{NATIONAL_TV_FLAG}'
        msg = message_natl if natl else message
        gate_rows.append(dict(segment=r.segment, target=SERVING_TARGET, channel=r.channel, fit_key=fit_key(r.segment),
                              gate_policy_version=PACKAGE_TYPE, fit_allowed_use='primary', allowed_use='primary',
                              forecast_policy='allowed', optimizer_policy=opt_use,
                              objective_role='primary_objective', gate_reason_codes=reasons, marketer_message=msg))
        cap_rows.append(dict(segment=r.segment, target=SERVING_TARGET, channel=r.channel, fit_key=fit_key(r.segment),
                             configured=True, posterior_status='present', posterior_file='weekly_media_draws.npz',
                             diagnostics_status='ok', rhat_max=(card.get('max_r_hat_roas_params') or {}).get('lam', ''),
                             n_divergences=card.get('divergences', ''), beta_structure='weekly_joint_tier',
                             media_scaling_mode='spend_per_resident_over_m_ref', media_response_mode='exp_saturation',
                             l_max=int(arr['adstock_l']), channel_reliability_flags=reasons,
                             active_days=int(7 * act.week_start.nunique()), active_geos=int(act.a.nunique()),
                             pct_nonzero_rows=round(100.0 * len(act) / max(geos_n * len(d.weeks), 1), 3),
                             fixed_saturation_shape=False, gate_reason_codes=reasons, risk_level='medium',
                             allowed_use='primary', allowed_use_reason=ROAS_LEVEL_FLAG, analysis_included=True,
                             forecast_use='allowed', optimizer_use=opt_use, objective_role='primary_objective',
                             marketer_message=msg))
        risk_rows.append(dict(scope='channel', segment=r.segment, target=SERVING_TARGET, channel=r.channel,
                              fit_key=fit_key(r.segment), risk_type='roas_level_from_industry_anchor',
                              risk_level='medium', reason=ROAS_LEVEL_LABEL_RU, affects_forecast=True,
                              affects_optimizer=True))
    for alias, target in CHANNEL_ALIASES.items():          # plan channels merged into a model channel
        flag = f'|MAPPED_TO_{target}'
        cap_rows += [dict(r, channel=alias, gate_reason_codes=r['gate_reason_codes'] + flag,
                          channel_reliability_flags=r['channel_reliability_flags'] + flag)
                     for r in list(cap_rows) if r['channel'] == target]
        gate_rows += [dict(r, channel=alias, gate_reason_codes=r['gate_reason_codes'] + flag)
                      for r in list(gate_rows) if r['channel'] == target]
        risk_rows += [dict(r, channel=alias, reason=f"{r['reason']}; в модели входит в {target}")
                      for r in list(risk_rows) if r['channel'] == target]
        support += [dict(r, channel=alias, support_basis=f"{r['support_basis']}_of_{target}")
                    for r in list(support) if r['channel'] == target]
    pd.DataFrame(support).to_csv(out_dir / 'historical_support_bounds.csv', index=False)
    pd.DataFrame(cap_rows).to_csv(out_dir / 'capability_matrix.csv', index=False)
    pd.DataFrame(gate_rows, columns=gate_cols).to_csv(out_dir / 'gate_results.csv', index=False)
    pd.DataFrame(risk_rows).to_csv(out_dir / 'risk_registry.csv', index=False)
    (out_dir / 'posterior_index.json').write_text(json.dumps(
        {fit_key(s): dict(file_name='weekly_media_draws.npz', draws=n_draws) for s in S}, ensure_ascii=False,
        indent=2), encoding='utf-8')
    served = sorted({r['channel'] for r in cap_rows} - set(CHANNEL_ALIASES))
    fits = {fit_key(s): dict(segment=s, target=SERVING_TARGET,
                             channels=[c for c in C if c in served and mask_idx.loc[(s, c), 'mask']]
                             + [a for a, t in CHANNEL_ALIASES.items() if t in served and mask_idx.loc[(s, t), 'mask']],
                             geos=units.unit_label[units.segment == s].tolist(), l_max_weeks=int(arr['adstock_l']),
                             time_step='week', y_scaling='log_orders_plus_log_check')
            for s in S}
    (out_dir / 'fit_design_metadata.json').write_text(json.dumps(dict(package_type=PACKAGE_TYPE, fits=fits),
                                                                 ensure_ascii=False, indent=2), encoding='utf-8')

    files = {name: sha256_file(out_dir / name) for name in PACKAGE_FILES}
    manifest = dict(
        package_type=PACKAGE_TYPE, package_schema_version=PACKAGE_SCHEMA_VERSION, package_stage='posterior_ready',
        activation_status='preprod_restricted',
        gate_policy_version=PACKAGE_TYPE,                   # the capability rows' gate (all primary, see capability_matrix)
        production_blockers=[ROAS_LEVEL_FLAG, OOT_PREREG_FLAG, OOT_FLAG],
        oot_status=dict(flag=OOT_PREREG_FLAG, cuts=['train_to_2025-12-28_test_2026Q1', 'train_to_2026-03-29_test_2026Q2'],
                        total_turnover_abs_error='1-2%', worst_segment_abs_error='about 10%', criteria_passed='3 of 4',
                        sealed_q3='pending'),
        optimizer_rules=dict(directions_separate=True, channel_aliases_merged=True,
                             fixed_at_plan_channels=[NATIONAL_TV_CHANNEL]),
        plan_routing=dict(PLAN_ROUTING, unit_kinds=routing.unit_kind.value_counts().to_dict()),
        model_name=model_name, model_run_id=model_run_id or f'{model_name}_{fit_dir.name}_{profile}',
        roas_level_label_ru=ROAS_LEVEL_LABEL_RU,
        mode='weekly_joint', run_label=fit_dir.name, run_variant=profile,
        segments=S, targets=[SERVING_TARGET], channels=served,
        channel_aliases={a: t for a, t in CHANNEL_ALIASES.items() if t in served},
        time_step='week', week_anchor='monday', adstock_l_weeks=int(arr['adstock_l']),
        roas_scale=arr['roas_scale'], media_geo=arr['media_geo'],
        fit_weeks=[str(d.weeks[0].date()), str(d.weeks[-1].date())], n_draws=n_draws,
        train_start=str(d.weeks[0].date()),                # first day of the first fit week (Monday)
        train_end=str((d.weeks[-1] + pd.Timedelta(days=6)).date()),   # last day of the last fit week (Sunday)
        panel_weeks=[str(w.date()) for w in d.weeks],       # the adstock runs over every panel week
        baseline_rule='same_week_52_weeks_earlier_per_ad_unit_else_unit_median',
        counterfactual='plan_spend_only_no_campaign',
        carryover_weeks_after_plan=int(arr['adstock_l']) - 1,
        artifact_status=dict(posterior_files_n=1),
        files=files, package_input_fingerprint=fingerprint(files), run_config_sha256=files['run_config.json'],
        created_at_utc=datetime.now(timezone.utc).isoformat(),
    )
    (out_dir / 'model_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest
