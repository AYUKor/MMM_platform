"""Campaign-aware routing of the agency ledger to the units of the weekly joint model (fourth pass, panel v3).

Same rules as route_media() in panels/04_2025_2026Q2_fourth_pass/v3_20261102/build_weekly_panel_v3.py (copied below,
only change: the extra key columns, e.g. the catalog campaign, stay in every grouping, so the routed money keeps its
campaign). Every rule is linear in the ledger rows, so the routed money summed over campaigns equals the panel's
media_units_daily file; check_against_panel() verifies it to the ruble.

Rules (panel v3): national «РФ» by population over units with sales that day; «ДРУГИЕ РЕГИОНЫ» by population over units
with sales outside the regions named in the same agency campaign the same day; a city label on its unit inside the
unit's period, otherwise on the rest of its oblast; physical outdoor on an oblast label to the rest of the oblast;
TV, radio, digital on an oblast label by population over its cities and the rest that day.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

LAST_DAY = pd.Timestamp('2026-06-30')
FIRST_DAY = pd.Timestamp('2025-01-01')
GARBAGE_UNITS = {('ТС5', 'Онлайн', 'ЯКУТСК'), ('ТС5', 'Оффлайн', 'БАБУШКИН')}
PHYSICAL = {'OOH', 'ООН РТБ', 'Indoor'}
DIGITAL = {'App Ads', 'Marketplace Ads', 'Other Digital', 'Paid Search', 'Paid Social',
           'Premium Publishers', 'Programmatic', 'Telecom Ads', 'Video Ads'}
MODEL_CHANNEL = {'Нац ТВ': 'Нац_ТВ', 'Рег ТВ': 'Рег_ТВ', 'Радио': 'Радио',
                 'OOH': 'OOH_Total', 'ООН РТБ': 'OOH_Total', 'Indoor': 'OOH_Total',
                 **{d: 'Digital_Performance' for d in DIGITAL}}
SEGKEY = ['network', 'channel']
NO_SALES = 'остаток <= 0'
LEDGER_COLS = ['date', 'network', 'channel', 'channel_type', 'action', 'media_geo_norm', 'geo_label', 'budget',
               'source_row_id', 'campaign_id_for_audit']


def is_oblast_label(label: str) -> bool:
    return any(w in label for w in ('ОБЛАСТЬ', 'КРАЙ', 'РЕСПУБЛИКА', 'АВТОНОМНЫЙ ОКРУГ'))


def read_ledger(path: str) -> pd.DataFrame:
    """Ledger v3: one file or a folder of *.parquet parts."""
    m = pd.read_parquet(path, columns=LEDGER_COLS)
    m['date'] = pd.to_datetime(m['date'])
    m['campaign_id_for_audit'] = m['campaign_id_for_audit'].fillna('').astype(str)
    return m


def load_units(targets_path: str) -> pd.DataFrame:
    t = pd.read_parquet(targets_path)
    t['date'] = pd.to_datetime(t['date'])
    assert t['date'].max() <= LAST_DAY, 'в таргетах есть даты после 30.06.2026'
    keep = ~t.apply(lambda r: (r.network, r.channel, r.geo_label) in GARBAGE_UNITS, axis=1)
    t = t.loc[keep].copy()
    assert not t.duplicated(['date', 'network', 'channel', 'unit_label']).any()
    return t


def spread(budget: pd.DataFrame, units: pd.DataFrame, on: list[str], rule: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    w = units.copy()
    w['w'] = w['population_k'] / w.groupby(on)['population_k'].transform('sum')
    x = budget.merge(w[on + ['unit_label', 'w']], on=on, how='left')
    lost = x[x['unit_label'].isna()].drop(columns=['unit_label', 'w'])
    x = x[x['unit_label'].notna()].copy()
    x['budget'] = x['budget'] * x['w']
    x['rule'] = rule
    return x.drop(columns=['w']), lost


def route_media(m: pd.DataFrame, units: pd.DataFrame, c2o: dict[str, str], extra: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """m: ledger rows (LEDGER_COLS + extra). Returns routed money [date, network, channel, channel_type, unit_label,
    budget, rule, *extra] and money with no unit [.., reason, *extra]."""
    assert m['date'].between(FIRST_DAY, LAST_DAY).all(), 'журнал выходит за 01.01.2025-30.06.2026'
    assert set(m['channel_type']) <= set(MODEL_CHANNEL), set(m['channel_type']) - set(MODEL_CHANNEL)
    pres = units[['date', 'network', 'channel', 'unit_label', 'geo_label', 'unit_kind', 'population_k', 'invalid_reason']].copy()
    pres['oblast'] = np.where(pres.unit_kind == 'rest_of_oblast', pres.geo_label, pres.geo_label.map(c2o))
    sales = pres[pres.invalid_reason.fillna('') != NO_SALES].drop(columns='invalid_reason')
    pres = pres.drop(columns='invalid_reason')
    seg_units = pres.drop_duplicates(SEGKEY + ['unit_label'])
    span = pres.groupby(SEGKEY + ['unit_label']).date.agg(lo='min', hi='max').reset_index()
    routed, unmodeled = [], []
    keyb = ['date', 'network', 'channel', 'channel_type'] + list(extra)

    # 1) РФ
    nat = m[m.action == 'pro_rata_to_eligible_geos']
    assert set(nat.media_geo_norm) <= {'РФ', 'ДРУГИЕ РЕГИОНЫ'}, set(nat.media_geo_norm)
    p = nat[nat.media_geo_norm == 'РФ'].groupby(keyb + ['media_geo_norm'], as_index=False)['budget'].sum()
    x, lost = spread(p, sales, ['date', 'network', 'channel'], 'national_pro_rata_by_population')
    routed.append(x)
    unmodeled.append(lost.assign(reason='в этот день у направления нет ни одной единицы с продажами'))

    # 1b) ДРУГИЕ РЕГИОНЫ (exclusion by the agency campaign of the same day, as in the panel)
    camp = ['date', 'network', 'channel', 'campaign_id_for_audit']
    gb = keyb + (['campaign_id_for_audit'] if 'campaign_id_for_audit' not in keyb else []) + ['media_geo_norm']
    o = nat[nat.media_geo_norm == 'ДРУГИЕ РЕГИОНЫ'].groupby(gb, as_index=False)['budget'].sum()
    named = m[m.action != 'pro_rata_to_eligible_geos']
    named = pd.concat([named[camp + ['geo_label']].rename(columns={'geo_label': 'name'}),
                       named[camp + ['media_geo_norm']].rename(columns={'media_geo_norm': 'name'})]).drop_duplicates()
    oc = o[camp].drop_duplicates().merge(sales, on=['date', 'network', 'channel'])
    hit_geo = oc.merge(named, left_on=camp + ['geo_label'], right_on=camp + ['name'], how='left').name.notna().to_numpy()
    hit_ob = oc.merge(named, left_on=camp + ['oblast'], right_on=camp + ['name'], how='left').name.notna().to_numpy()
    oc['excluded'] = hit_geo | hit_ob
    left = oc[~oc.excluded].copy()
    has_left = left[camp].drop_duplicates().assign(ok=True)
    oc = oc.merge(has_left, on=camp, how='left')
    elig = pd.concat([left, oc[oc.ok.isna()].drop(columns='ok')])
    x, lost = spread(o, elig.drop(columns=['excluded']), camp, 'other_regions_pro_rata_excl_named')
    routed.append(x)
    unmodeled.append(lost.assign(reason='в этот день у направления нет ни одной единицы с продажами'))

    # 2) by label type
    d = m[m.action != 'pro_rata_to_eligible_geos'].copy()
    d = d.groupby(keyb + ['action', 'media_geo_norm', 'geo_label'], as_index=False)['budget'].sum()
    oblast_with_cities = {}
    for (net, ch), g in seg_units.groupby(SEGKEY):
        cities_ob = set(g.loc[g.unit_kind == 'city', 'geo_label'].map(c2o).dropna())
        rests = set(g.loc[g.unit_kind == 'rest_of_oblast', 'geo_label'])
        oblast_with_cities[(net, ch)] = (cities_ob | rests, rests)

    def kind(r):
        obs, rests = oblast_with_cities.get((r.network, r.channel), (set(), set()))
        if r.geo_label in obs:
            src_is_oblast = r.action == 'split_to_components' or is_oblast_label(r.media_geo_norm)
            if not src_is_oblast:
                return 'city_inside_oblast_rest'
            return 'oblast_physical' if r.channel_type in PHYSICAL else 'oblast_broadcast'
        return 'direct'
    d['label_kind'] = d.apply(kind, axis=1) if len(d) else pd.Series(dtype=str)

    # 2a) direct to the unit, inside the unit's period
    dd = d[d.label_kind == 'direct']
    direct_map = seg_units[seg_units.unit_kind != 'rest_of_oblast'][SEGKEY + ['geo_label', 'unit_label']].merge(span, on=SEGKEY + ['unit_label'])
    x = dd.merge(direct_map, on=SEGKEY + ['geo_label'], how='left')
    outside_span = x.unit_label.notna() & ~x.date.between(x.lo, x.hi)
    x.loc[outside_span, 'unit_label'] = np.nan
    x = x.drop(columns=['lo', 'hi'])
    routed.append(x[x.unit_label.notna()].assign(rule='direct_to_unit'))
    rest_map = seg_units[seg_units.unit_kind == 'rest_of_oblast'][SEGKEY + ['geo_label', 'unit_label']]
    miss = x[x.unit_label.isna()].drop(columns=['unit_label']).copy()
    miss['oblast'] = miss['geo_label'].map(c2o)
    y = miss.merge(rest_map.rename(columns={'geo_label': 'oblast'}), on=SEGKEY + ['oblast'], how='left')
    routed.append(y[y.unit_label.notna()].drop(columns=['oblast']).assign(rule='city_not_in_model_to_oblast_rest'))
    unmodeled.append(y[y.unit_label.isna()].drop(columns=['unit_label', 'oblast']).assign(
        reason='метки нет среди единиц направления, и её области нет остатком'))

    # 2b) to the rest of the oblast
    for lk, rule in (('city_inside_oblast_rest', 'city_not_in_model_to_oblast_rest'),
                     ('oblast_physical', 'oblast_physical_to_oblast_rest')):
        dr = d[d.label_kind == lk]
        x = dr.merge(rest_map, on=SEGKEY + ['geo_label'], how='left')
        unmodeled.append(x[x.unit_label.isna()].drop(columns=['unit_label']).assign(
            reason='остаток области исключён (области почти целиком из её городов)'))
        routed.append(x[x.unit_label.notna()].assign(rule=rule))

    # 2c) TV, radio, digital on an oblast label
    db = d[d.label_kind == 'oblast_broadcast'].rename(columns={'geo_label': 'oblast'})
    x, lost = spread(db, sales.dropna(subset=['oblast']), ['date', 'network', 'channel', 'oblast'],
                     'oblast_broadcast_by_population')
    routed.append(x.rename(columns={'oblast': 'geo_label_src'}))
    unmodeled.append(lost.rename(columns={'oblast': 'geo_label'}).assign(reason='в этот день у области нет единиц'))

    keep = ['date', 'network', 'channel', 'channel_type', 'unit_label', 'budget', 'rule'] + list(extra)
    r = pd.concat([x_[keep] for x_ in routed], ignore_index=True)
    ukeep = ['date', 'network', 'channel', 'channel_type', 'geo_label', 'budget', 'reason'] + list(extra)
    u = pd.concat([x_.reindex(columns=ukeep) for x_ in unmodeled], ignore_index=True)
    total_in, total_out = m['budget'].sum(), r['budget'].sum() + u['budget'].sum()
    assert abs(total_in - total_out) < 1.0, (total_in, total_out)
    return r, u


def check_against_panel(routed: pd.DataFrame, media_units_daily: pd.DataFrame) -> dict:
    """Routed money summed over the extra keys vs the panel's media_units_daily file, per day x unit x type x rule."""
    key = ['date', 'network', 'channel', 'unit_label', 'channel_type', 'rule']
    a = routed.groupby(key).budget.sum()
    b = media_units_daily.assign(date=pd.to_datetime(media_units_daily.date)).groupby(key).budget.sum()
    j = pd.concat([a.rename('campaigns'), b.rename('panel')], axis=1).fillna(0.0)
    diff = (j.campaigns - j.panel).abs()
    return dict(rows=int(len(j)), max_abs_diff_rub=float(diff.max()), sum_abs_diff_rub=float(diff.sum()),
                campaigns_total_rub=float(j.campaigns.sum()), panel_total_rub=float(j.panel.sum()))
