"""Past-campaign catalog on the weekly joint model: campaigns, names directory, per-campaign spend, counterfactual effect.

Campaign = normalized name (lowercase, no punctuation, no «РК» prefix) + continuous period: a pause of more than 30 days
without spend starts a new campaign, a continuous period longer than 365 days is cut at the calendar-year boundary
(same rules as the names directory of 28.10; numbers stay the same at every recompute, new campaigns get the next ones).

Effect of a campaign for one posterior draw = turnover with all ads minus turnover without this campaign's money, over
the fit unit-weeks of the model (as the model's own channel ROAS): T * (1 - exp(-dM)), dM = drop of the log orders and
log check contributions when the campaign's spend is taken out of the units and weeks it was routed to (panel v3 rules,
campaign_routing). Adstock carries the effect into the following weeks. By default nothing after the last panel week
(22.06-28.06.2026) is counted; with tail weeks (Campaigns(..., tail=tail_rows(d, 7))) the carry-over of the last weeks
is counted too, as the plan forecast does (07: plan weeks + 7 carry-over weeks): ledger money of 29-30.06.2026 enters
the first tail week, and the baseline turnover of a tail week is the same unit's real turnover 52 weeks earlier
(analog year, as 07; July-September 2026 are never read). Other spend in the tail weeks (the ledger ends 30.06.2026):
tail_other='analog' (default) = the model's spend of the same week one year earlier (always-on campaigns go on, so the
tail is as crowded as a year before); 'none' = no other spend (an upper-side estimate: the tail is unsaturated).
ROAS = turnover effect / full ledger budget of the campaign (money the model cannot see included).
"""
from __future__ import annotations

import re
import unicodedata

import numpy as np
import pandas as pd

from . import campaign_routing as cr
from . import weekly_joint as wj

PAUSE_DAYS = 30
MAX_DAYS = 365
LONG_DAYS = 120
# channel groups of the Excel (ledger facts; Indoor keeps its own budget column, the model counts it inside OOH_Total)
XL_GROUP = {**{d: 'Digital_Performance' for d in cr.DIGITAL}, 'OOH': 'OOH_Total', 'ООН РТБ': 'OOH_Total',
            'Indoor': 'Indoor', 'Радио': 'Радио', 'Нац ТВ': 'Нац_ТВ', 'Рег ТВ': 'Рег_ТВ'}
XL_CHANNELS = [('Digital_Performance', 'Цифровая реклама'), ('OOH_Total', 'Наружная реклама'), ('Indoor', 'Indoor'),
               ('Радио', 'Радио'), ('Нац_ТВ', 'Национальное ТВ'), ('Рег_ТВ', 'Региональное ТВ')]
XL_KEYS = {'Digital_Performance': 'dig', 'OOH_Total': 'ooh', 'Indoor': 'ind', 'Радио': 'rad', 'Нац_ТВ': 'ntv', 'Рег_ТВ': 'rtv'}
FEDERAL = {'Нац_ТВ'}
LOWER_WORDS = {'на', 'под', 'при', 'в', 'у', 'и', 'край', 'область', 'республика', 'округ', 'автономный', 'автономная', 'городской'}
# reliability flag: a segment x channel cell is "ok" when the fit converged there and the data have enough spend in it
FLAG_RHAT_MAX = 1.05
FLAG_MIN_WEEKS = 13
FLAG_MIN_UNITS = 5
FLAG_MIN_SHARE = 0.5


# ---------------------------------------------------------------- names and campaigns

def norm_name(s: str) -> str:
    t = re.sub(r'[^0-9a-zа-яё]+', '', str(s).lower())
    if t.startswith('рк') and len(t) > 5:
        t = t[2:]
    return t


def clean(s: str) -> str:
    t = unicodedata.normalize('NFC', str(s)).replace('\xa0', ' ')
    t = re.sub(r'\s+', ' ', t).strip()
    t = re.sub(r'^(?:РК|рк|Рк|рК)[\s\-_:]+', '', t)
    return t.strip()


def pretty_geo(label: str) -> str:
    parts = []
    for word in str(label).lower().split(' '):
        hy = word.split('-')
        hy = [h if (i > 0 and h in LOWER_WORDS) else h[:1].upper() + h[1:] for i, h in enumerate(hy)]
        w = '-'.join(hy)
        parts.append(w.lower() if w.lower() in LOWER_WORDS else w)
    out = ' '.join(parts)
    return out[:1].upper() + out[1:]


def assign_waves(ledger: pd.DataFrame, pause_days: int = PAUSE_DAYS, max_days: int | None = MAX_DAYS):
    """Adds column wave (0, 1, ... per name_key); returns (ledger, periods)."""
    md = ledger.groupby(['name_key', 'date'], as_index=False).budget.sum().sort_values(['name_key', 'date'])
    md['gap'] = md.groupby('name_key').date.diff().dt.days - 1
    md['wave'] = (md.gap.fillna(0) > pause_days).groupby(md.name_key).cumsum()
    md['cut'] = 0
    if max_days:
        span = md.groupby(['name_key', 'wave']).date.agg(['min', 'max'])
        too_long = span[(span['max'] - span['min']).dt.days + 1 > max_days].index
        is_long = pd.MultiIndex.from_frame(md[['name_key', 'wave']]).isin(too_long)
        md.loc[is_long, 'cut'] = md.loc[is_long, 'date'].dt.year
    md['grp_first'] = md.groupby(['name_key', 'wave', 'cut']).date.transform('min')
    md['wave'] = (md.groupby('name_key').grp_first.rank(method='dense').astype(int) - 1)
    waves = md.groupby(['name_key', 'wave']).agg(first=('date', 'min'), last=('date', 'max'), money=('budget', 'sum')).reset_index()
    waves['days'] = (waves['last'] - waves['first']).dt.days + 1
    starts = waves[['name_key', 'wave', 'first']].sort_values('first')
    led = ledger[['date', 'name_key']].reset_index().sort_values('date')
    m = pd.merge_asof(led, starts, left_on='date', right_on='first', by='name_key', direction='backward')
    out = ledger.copy()
    out['wave'] = m.set_index('index').wave.reindex(out.index).astype(int)
    return out, waves


def build_directory(led: pd.DataFrame, waves: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Catalog name of each campaign (dates added only where the same name has several periods)."""
    raw = led.groupby(['name_key', 'campaign_id_for_audit']).budget.sum().reset_index()
    raw['clean'] = raw.campaign_id_for_audit.map(clean)
    sp = raw.groupby(['name_key', 'clean']).budget.sum().reset_index().sort_values(['name_key', 'budget'], ascending=[True, False])
    canon = sp.groupby('name_key').clean.first()
    nw = waves.groupby('name_key').size()
    d = waves.copy()
    d['base_name'] = d.name_key.map(canon)
    d['n_waves'] = d.name_key.map(nw)
    d['spellings'] = d.name_key.map(sp.groupby('name_key').clean.apply(list))
    fmt = lambda t: t.strftime('%d.%m.%Y')
    d['name'] = np.where(d.n_waves > 1, d.base_name + ' (' + d['first'].map(fmt) + '–' + d['last'].map(fmt) + ')', d.base_name)
    d = d.sort_values(['first', 'name', 'name_key']).reset_index(drop=True)
    assert d.name.is_unique, d[d.name.duplicated(keep=False)][['name_key', 'wave', 'name']]
    groups = sp[sp.groupby('name_key').clean.transform('nunique') > 1].copy()
    return d, groups


def read_names_xlsx(path: str) -> pd.DataFrame:
    """Numbers of the saved names directory: the Excel (sheet «Кампании») or its CSV copy (id, name, start, end, budget_mln)."""
    if str(path).lower().endswith('.csv'):
        t = pd.read_csv(path, encoding='utf-8-sig', parse_dates=['start', 'end'])
        t['id'] = t.id.astype(int)
        t['base_name'] = t.name.astype(str).str.replace(r'\s*\(\d\d\.\d\d\.\d{4}–\d\d\.\d\d\.\d{4}\)$', '', regex=True)
        return t
    x = pd.read_excel(path, sheet_name='Кампании', header=None)
    hdr = x.index[x.iloc[:, 0].astype(str).str.strip().eq('№')][0]
    t = x.iloc[hdr + 1:, :8].copy()
    t.columns = ['id', 'name', 'spellings', 'start', 'end', 'days', 'budget_mln', 'sheet']
    t = t[pd.to_numeric(t.id, errors='coerce').notna()].copy()
    t['id'] = t.id.astype(int)
    t['start'] = pd.to_datetime(t.start)
    t['end'] = pd.to_datetime(t.end)
    t['base_name'] = t.name.astype(str).str.replace(r'\s*\(\d\d\.\d\d\.\d{4}–\d\d\.\d\d\.\d{4}\)$', '', regex=True)
    return t.reset_index(drop=True)


def numbers_overrides(d: pd.DataFrame, old: pd.DataFrame) -> pd.DataFrame:
    """Short form of the saved directory: only the rows whose number is not their place in the start-date order (plus rows
    whose saved name differs from the computed one). keep_numbers(d, overrides, sparse=True) gives the same numbers."""
    full, _ = keep_numbers(d, old)
    pos = d.sort_values(['first', 'name', 'name_key']).reset_index(drop=True).assign(pos=lambda x: np.arange(1, len(x) + 1))
    j = full.merge(pos[['name_key', 'wave', 'pos', 'name']].rename(columns={'name': 'name_computed'}), on=['name_key', 'wave'])
    need = j[(j.id != j.pos) | (j.name != j.name_computed)]
    return old[old.id.isin(need.id)][['id', 'name', 'start', 'end', 'budget_mln']].reset_index(drop=True)


def keep_numbers(d: pd.DataFrame, old: pd.DataFrame, sparse: bool = False) -> tuple[pd.DataFrame, dict]:
    """Give each campaign the number it has in the saved directory; new campaigns get the next numbers by start date.
    Match: same catalog name, else same base name with overlapping dates (one candidate only).
    sparse=True: old holds only the overrides (numbers_overrides); every other campaign keeps its place in the
    start-date order as its number, as when the directory was made."""
    if sparse:
        d = d.sort_values(['first', 'name', 'name_key']).reset_index(drop=True)
        d['pos'] = np.arange(1, len(d) + 1)
        x, info = keep_numbers(d.drop(columns='pos'), old)
        x = x.merge(d[['name_key', 'wave', 'pos']], on=['name_key', 'wave'])
        x.loc[x.id_match.eq('new'), 'id'] = x.pos
        x.loc[x.id_match.eq('new'), 'id_match'] = 'place_in_order'
        assert x.id.is_unique, 'номера из краткого справочника совпали с местами по порядку: нужен полный справочник'
        info = dict(campaigns=int(len(x)), kept_by_name=int((x.id_match == 'name').sum()),
                    kept_by_base_name_and_dates=int((x.id_match == 'base_name_dates').sum()),
                    by_place_in_order=int((x.id_match == 'place_in_order').sum()), new=0,
                    old_not_found=[dict(id=int(k), name='') for k in sorted(set(range(1, int(x.id.max()) + 1)) - set(x.id))])
        return x.drop(columns='pos').sort_values('id').reset_index(drop=True), info
    d = d.copy()
    d['id'] = -1
    d['id_match'] = ''
    used = set()
    by_name = dict(zip(old.name, old.id))
    for i, r in d.iterrows():
        k = by_name.get(r['name'])
        if k is not None and k not in used:
            d.at[i, 'id'], d.at[i, 'id_match'] = k, 'name'
            used.add(k)
    for i, r in d[d.id < 0].iterrows():
        c = old[(old.base_name == r.base_name) & ~old.id.isin(used) & (old.start <= r['last']) & (old.end >= r['first'])]
        if len(c) == 1:
            k = int(c.id.iloc[0])
            d.at[i, 'id'], d.at[i, 'id_match'] = k, 'base_name_dates'
            used.add(k)
            # the name stays as in the directory when its dates are still the campaign's dates
            if c.start.iloc[0] == r['first'] and c.end.iloc[0] == r['last'] and c.name.iloc[0] not in set(d.name):
                d.at[i, 'name'] = c.name.iloc[0]
    nxt = int(old.id.max()) + 1
    for i in d[d.id < 0].sort_values(['first', 'name']).index:
        d.at[i, 'id'], d.at[i, 'id_match'] = nxt, 'new'
        nxt += 1
    gone = old[~old.id.isin(used)]
    d = d.sort_values('id').reset_index(drop=True)
    assert d.id.is_unique
    info = dict(campaigns=int(len(d)), kept_by_name=int((d.id_match == 'name').sum()),
                kept_by_base_name_and_dates=int((d.id_match == 'base_name_dates').sum()), new=int((d.id_match == 'new').sum()),
                old_not_found=gone[['id', 'name']].to_dict('records'))
    return d, info


def overlaps(led: pd.DataFrame, cid: np.ndarray, n: int) -> np.ndarray:
    """Other campaigns sharing at least one (direction, ledger geo label, day) cell with spend > 0."""
    pos = led.budget.to_numpy() > 0
    seg_c = (led.network + '/' + led.channel).astype('category').cat.codes.to_numpy(np.int64)
    geo_c = led.geo_label.astype('category').cat.codes.to_numpy(np.int64)
    day = (led.date - led.date.min()).dt.days.to_numpy(np.int64)
    G, ND = int(geo_c.max()) + 1, int(day.max()) + 1
    cell = (seg_c * G + geo_c) * ND + day
    pairs = np.unique(cell[pos] * n + cid[pos])
    p_cell, p_cid = pairs // n, pairs % n
    order = np.argsort(p_cid, kind='stable')
    bounds = np.searchsorted(p_cid[order], np.arange(n + 1))
    out = np.zeros(n, int)
    for i in range(n):
        mine = np.unique(p_cell[order[bounds[i]:bounds[i + 1]]])
        lo, hi = np.searchsorted(p_cell, mine, 'left'), np.searchsorted(p_cell, mine, 'right')
        others = np.unique(np.concatenate([p_cid[a:b] for a, b in zip(lo, hi)])) if len(mine) else np.array([i])
        out[i] = len(others) - 1
    return out


def card(sub: pd.DataFrame) -> dict:
    """Descriptive fields of a catalog row (ledger facts): dates, directions, budget by channel, cities."""
    g = sub.channel_type.map(XL_GROUP)
    by_ch = sub.groupby(g).budget.sum()
    channels = [dict(key=XL_KEYS[m], name=name, budget=float(by_ch[m]), federal=m in FEDERAL)
                for m, name in XL_CHANNELS if by_ch.get(m, 0.0) > 0]
    regional = sub[~g.isin(FEDERAL)]
    cities = [pretty_geo(x) for x in regional.groupby('geo_label').budget.sum().sort_values(ascending=False).index]
    first, last = sub.date.min(), sub.date.max()
    return dict(dirs=sorted((sub.network + '/' + sub.channel).unique()), start=first.date().isoformat(),
                end=last.date().isoformat(), days=int((last - first).days) + 1, channels=channels, cities=cities,
                federal=[c['name'] for c in channels if c['federal']], budget=float(sub.budget.sum()))


# ---------------------------------------------------------------- campaign spend in model coordinates

def present_cells(panel_path: str, d: wj.ModelData) -> np.ndarray:
    """[A, W] True where the unit has a panel row (spend there comes from the panel; elsewhere national per 1000)."""
    p = pd.read_parquet(panel_path, columns=['segment', 'unit_label', 'week_start'])
    aidx = {k: i for i, k in enumerate(d.ad_units.ad_key)}
    widx = {w: i for i, w in enumerate(d.weeks)}
    a = (p.segment + '|' + p.unit_label).map(aidx)
    w = p.week_start.map(widx)
    ok = a.notna() & w.notna()
    out = np.zeros((len(d.ad_units), len(d.weeks)), bool)
    out[a[ok].astype(int).to_numpy(), w[ok].astype(int).to_numpy()] = True
    return out


def tail_weeks(d: wj.ModelData, n_tail: int) -> pd.DatetimeIndex:
    """The panel weeks plus n_tail Monday weeks after the last one."""
    last = d.weeks[-1]
    return d.weeks.append(pd.DatetimeIndex([last + pd.Timedelta(weeks=i) for i in range(1, n_tail + 1)]))


def present_tail(present: np.ndarray, n_tail: int) -> np.ndarray:
    """[A, W + n_tail]: a unit present in the last panel week stays present in the tail weeks."""
    return np.concatenate([present, np.repeat(present[:, -1:], n_tail, axis=1)], axis=1)


def tail_rows(d: wj.ModelData, arr: dict, n_tail: int) -> dict:
    """Rows of the tail weeks after the panel: one per model unit with a fit row in the last panel week, weeks W ..
    W + n_tail - 1. Baseline turnover, orders and buyers = the same model unit 52 weeks earlier (analog year, no growth,
    as 07); a unit without that week takes its median fit week."""
    o = d.obs
    W = len(d.weeks)
    weeks = tail_weeks(d, n_tail)
    last = o[o.w_i.to_numpy() == W - 1]
    hist = o.set_index(['mu_key', 'week_start'])[['turnover_total', 'orders_cnt', 'buyers_daily_sum']]
    med = o.groupby('mu_key')[['turnover_total', 'orders_cnt', 'buyers_daily_sum']].median()
    rows = []
    for r in last.itertuples(index=False):
        for t in range(n_tail):
            wk = weeks[W + t]
            key = (r.mu_key, wk - pd.Timedelta(weeks=52))
            if key in hist.index:
                v, analog = hist.loc[key], True
            else:
                v, analog = med.loc[r.mu_key], False
            rows.append((int(r.a_i), W + t, int(r.seg_i), float(v.turnover_total), float(v.orders_cnt),
                         float(v.buyers_daily_sum), analog))
    a, w, s, T, O, B, an = (np.array(x) for x in zip(*rows)) if rows else (np.zeros(0, int),) * 7
    return dict(n_tail=n_tail, a_i=a.astype(int), w_i=w.astype(int), s_i=s.astype(int), T=T.astype(float),
                O=O.astype(float), B=B.astype(float), analog_share=float(np.mean(an)) if len(an) else 0.0,
                first_week=str(weeks[W].date()) if n_tail else '', last_week=str(weeks[-1].date()) if n_tail else '')


def campaign_spend(routed: pd.DataFrame, units: pd.DataFrame, d: wj.ModelData, present: np.ndarray, n: int,
                   weeks: pd.DatetimeIndex | None = None) -> dict:
    """Per campaign (column cat = 0..n-1) the money in model cells, as (a, w, c, rub) lists.

    Present unit-weeks get the routed money (as the panel); weeks before a unit existed get the campaign's national
    money per 1000 residents x the unit's population (as wj.prepare). Money on units or weeks the model does not have
    is counted per campaign as not seen. weeks (default: the panel weeks) may add tail weeks after the panel
    (tail_weeks; present then has the same number of columns, present_tail)."""
    C = len(wj.CHANNELS)
    aidx = {k: i for i, k in enumerate(d.ad_units.ad_key)}
    widx = {w: i for i, w in enumerate(d.weeks if weeks is None else weeks)}
    r = routed.copy()
    r['week_start'] = r.date - pd.to_timedelta(r.date.dt.dayofweek, unit='D')
    r['segment'] = r.network + '/' + r.channel
    r['j'] = r.channel_type.map(cr.MODEL_CHANNEL).map({c: i for i, c in enumerate(wj.CHANNELS)})
    r['a'] = (r.segment + '|' + r.unit_label).map(aidx)
    r['w'] = r.week_start.map(widx)
    g = r.groupby(['cat', 'segment', 'a', 'w', 'j'], dropna=False, as_index=False).budget.sum()
    ok = g.a.notna() & g.w.notna()
    ok[ok] = present[g.a[ok].astype(int).to_numpy(), g.w[ok].astype(int).to_numpy()]
    seen = g[ok].astype({'a': int, 'w': int, 'j': int})
    unseen = g[~ok].groupby('cat').budget.sum()

    # national per 1000 residents, weeks before the unit existed
    nat = routed[routed.rule == 'national_pro_rata_by_population'].merge(
        units[['date', 'network', 'channel', 'unit_label', 'population_k']], on=['date', 'network', 'channel', 'unit_label'])
    nd = nat.groupby(['cat', 'date', 'network', 'channel', 'channel_type'], as_index=False)[['budget', 'population_k']].sum()
    nd['rub_per_1000'] = nd.budget / nd.population_k
    nd['week_start'] = nd.date - pd.to_timedelta(nd.date.dt.dayofweek, unit='D')
    nd['segment'] = nd.network + '/' + nd.channel
    nd['j'] = nd.channel_type.map(cr.MODEL_CHANNEL).map({c: i for i, c in enumerate(wj.CHANNELS)})
    nw = nd.groupby(['cat', 'segment', 'week_start', 'j'], as_index=False).rub_per_1000.sum()
    nw['w'] = nw.week_start.map(widx)
    nw = nw[nw.w.notna()].astype({'w': int})
    ad = d.ad_units
    absent_rows = []
    for (cat, seg), gg in nw.groupby(['cat', 'segment']):
        units_s = np.flatnonzero(ad.segment.to_numpy() == seg)
        for a in units_s:
            miss = ~present[a, gg.w.to_numpy()]
            if miss.any():
                h = gg[miss]
                absent_rows.append(pd.DataFrame(dict(cat=cat, segment=seg, a=a, w=h.w.to_numpy(), j=h.j.to_numpy(),
                                                     budget=h.rub_per_1000.to_numpy() * ad.pop_k.iloc[a])))
    absent = (pd.concat(absent_rows, ignore_index=True) if absent_rows
              else pd.DataFrame(columns=['cat', 'segment', 'a', 'w', 'j', 'budget']))
    cells = pd.concat([seen.assign(kind='present'), absent.assign(kind='absent')], ignore_index=True)
    out = {k: g_ for k, g_ in cells.groupby('cat')}
    return dict(cells=out, unseen=unseen.reindex(range(n), fill_value=0.0).to_numpy(),
                seen_present=seen.groupby('cat').budget.sum().reindex(range(n), fill_value=0.0).to_numpy())


def check_spend_rebuild(cells: dict, d: wj.ModelData) -> dict:
    """Sum over campaigns of the money in model cells vs the model's spend array (channels of the panel)."""
    A, W, C = d.spend_pr.shape
    tot = np.zeros((A, W, C))
    for g in cells.values():
        g = g[g.w.to_numpy(int) < W]                  # tail weeks after the panel are not in the model's array
        np.add.at(tot, (g.a.to_numpy(int), g.w.to_numpy(int), g.j.to_numpy(int)), g.budget.to_numpy(float))
    ref = d.spend_pr * (d.ad_units.pop_k.to_numpy()[:, None, None] * 1000.0)
    k = len(wj.CHANNELS) - 1          # the offline-TV-in-online channel is not a ledger channel (off in the model)
    diff = np.abs(tot[:, :, :k] - ref[:, :, :k])
    return dict(max_abs_diff_rub=float(diff.max()), sum_abs_diff_rub=float(diff.sum()),
                campaigns_rub=float(tot[:, :, :k].sum()), model_rub=float(ref[:, :, :k].sum()))


# ---------------------------------------------------------------- counterfactual

def adstock_sat_np(spend_norm: np.ndarray, alpha: np.ndarray, lam: np.ndarray, L: int, pad_steady: bool = False) -> np.ndarray:
    """numpy copy of wj.adstock_sat (checked against it in the runner)."""
    A, W, C = spend_norm.shape
    w = alpha[None, :] ** np.arange(L)[:, None]
    w = w / w.sum(0, keepdims=True)
    head = (np.broadcast_to(spend_norm[:, :L, :].mean(1, keepdims=True), (A, L - 1, C)) if pad_steady
            else np.zeros((A, L - 1, C)))
    pad = np.concatenate([head, spend_norm], axis=1)
    x = np.zeros((A, W, C))
    for l in range(L):
        x += w[l][None, None, :] * pad[:, L - 1 - l: L - 1 - l + W, :]
    return 1.0 - np.exp(-x / lam[None, None, :])


def beta_draw(arr: dict, draw: dict) -> np.ndarray:
    """[2, A, C] multipliers of sat in wj.media_contrib_draw (orders, check)."""
    lam = np.asarray(draw['lam'])
    sat1 = 1.0 - np.exp(-1.0 / lam)
    logR_s = draw['logR_orders'][None, :] + draw['sig_seg'] * draw['z_seg']
    logR_a = (logR_s[arr['seg_a']] + draw['sig_tier'] * draw['z_tier'][arr['tier_a']]
              + draw['sig_unit'] * draw['z_unit'] * arr['local_c'][None, :])
    rs = arr.get('roas_scale', 'equal')
    geo = (arr['geo_ratio_a'] ** float(draw['gamma_geo']) if rs == 'gamma'
           else arr['geo_ratio_a'] if rs == 'turnover' else np.ones(len(arr['tau_a'])))
    conv = arr['m_ref_a'] / (arr['tau_a'][:, None] * sat1[None, :]) * arr['mask_a'] * geo[:, None]
    return np.stack([np.exp(logR_a) * conv, draw['R_check'][arr['seg_a']] * conv])


class Campaigns:
    """Precomputed per-campaign arrays for the counterfactual loop."""

    def __init__(self, d: wj.ModelData, arr: dict, cells: dict, n: int, tail: dict | None = None,
                 tail_other: str = 'analog'):
        """tail (tail_rows): count the carry-over after the last panel week; the cells then carry tail weeks too.
        tail_other: other spend in the tail weeks, 'analog' (same week a year earlier) or 'none'."""
        self.n = n
        self.L = int(arr.get('adstock_l', wj.ADSTOCK_L))
        self.pad = bool(arr.get('adstock_pad_steady', False))
        o = d.obs
        self.n_fit = len(o)
        self.n_tail = int(tail['n_tail']) if tail else 0
        tl = tail if tail else dict(T=[], O=[], B=[], a_i=[], w_i=[], s_i=[])
        cat = lambda x, y, t: np.concatenate([np.asarray(x, t), np.asarray(y, t)])
        self.T = cat(o.turnover_total.to_numpy(float), tl['T'], float)
        self.O = cat(o.orders_cnt.to_numpy(float), tl['O'], float)
        self.B = cat(o.buyers_daily_sum.to_numpy(float), tl['B'], float)
        self.a_i = cat(arr['a_i'], tl['a_i'], int)
        self.w_i = cat(arr['w_i'], tl['w_i'], int)
        self.s_i = cat(arr['s_i'], tl['s_i'], int)
        Wx = len(d.weeks) + self.n_tail
        seg_a = d.ad_units.seg_i.to_numpy()
        m_ref_a = d.m_ref[seg_a]                                                          # [A, C]
        pop = d.ad_units.pop_k.to_numpy() * 1000.0
        rows_of = pd.Series(np.arange(len(self.T))).groupby(self.a_i).apply(np.asarray).to_dict()
        # spend of the tail weeks: background (tail_other) + all campaigns' ledger money there, as spend_norm
        self.sn_tail = np.zeros((len(d.ad_units), self.n_tail, len(wj.CHANNELS)))
        self.tail_other = tail_other if self.n_tail else ''
        if self.n_tail and tail_other == 'analog':
            widx = {w: i for i, w in enumerate(d.weeks)}
            for t in range(self.n_tail):
                i = widx.get(d.weeks[-1] + pd.Timedelta(weeks=t + 1 - 52))
                if i is not None:
                    self.sn_tail[:, t, :] = arr['spend_norm'][:, i, :]
        elif self.n_tail and tail_other != 'none':
            raise ValueError(tail_other)
        self.items = []
        for k in range(n):
            g = cells.get(k)
            if g is None or len(g) == 0:
                self.items.append(None)
                continue
            units = np.unique(g.a.to_numpy(int))
            loc = {a: i for i, a in enumerate(units)}
            dn = np.zeros((len(units), Wx, len(wj.CHANNELS)))
            a = g.a.to_numpy(int)
            j = g.j.to_numpy(int)
            v = g.budget.to_numpy(float) / pop[a]
            v = np.where(m_ref_a[a, j] > 0, v / np.where(m_ref_a[a, j] > 0, m_ref_a[a, j], 1.0), 0.0)
            np.add.at(dn, (np.array([loc[x] for x in a]), g.w.to_numpy(int), j), v)
            if self.n_tail:
                self.sn_tail[units] += dn[:, len(d.weeks):, :]
            rows = np.concatenate([rows_of.get(x, np.zeros(0, int)) for x in units]).astype(int)
            wk = g.w.to_numpy(int)
            lo, hi = wk.min(), wk.max() + self.L - 1
            zone = rows[(self.w_i[rows] >= lo) & (self.w_i[rows] <= hi)]
            self.items.append(dict(units=units, dn=dn, rows=rows, loc_rows=np.array([loc[x] for x in self.a_i[rows]], int),
                                   zone=zone, zone_buyers=float(np.nansum(self.B[zone])), zone_orders=float(self.O[zone].sum())))

    def effects(self, arr: dict, draw: dict, k_list=None) -> dict:
        """For one draw: per campaign turnover effect, incremental orders, check effect numerator, effect by segment x
        channel [S, C]; plus the full effect of each segment x channel (model table) for the check."""
        S, C = len(wj.SEGMENTS), len(wj.CHANNELS)
        alpha, lam = np.asarray(draw['alpha']), np.asarray(draw['lam'])
        beta = beta_draw(arr, draw)                                                       # [2, A, C]
        sn = arr['spend_norm']
        if self.n_tail:
            sn = np.concatenate([sn, self.sn_tail], axis=1)                               # [A, W + tail, C]
        sat = adstock_sat_np(sn, alpha, lam, self.L, self.pad)                           # [A, W(+tail), C]
        cfull = (beta[0][self.a_i] + beta[1][self.a_i]) * sat[self.a_i, self.w_i]        # [N(+tail rows), C]
        inc = self.T[:, None] * (1 - np.exp(-cfull))
        full_sc = np.zeros((S, C))                                                        # fit rows: the model table
        np.add.at(full_sc, self.s_i[:self.n_fit], inc[:self.n_fit])
        full_sc_all = full_sc.copy()                                                      # with the tail rows
        np.add.at(full_sc_all, self.s_i[self.n_fit:], inc[self.n_fit:])
        ks = range(self.n) if k_list is None else k_list
        out = dict(turn=np.zeros(self.n), orders=np.zeros(self.n), check_num=np.zeros(self.n),
                   by_sc=np.zeros((self.n, S, C)), full_sc=full_sc, full_sc_all=full_sc_all)
        for k in ks:
            it = self.items[k]
            if it is None:
                continue
            u = it['units']
            sn_wo = np.maximum(sn[u] - it['dn'], 0.0)
            dsat = sat[u] - adstock_sat_np(sn_wo, alpha, lam, self.L, self.pad)        # [U, W, C]
            r = it['rows']
            ds = dsat[it['loc_rows'], self.w_i[r]]                                        # [n_r, C]
            dO = beta[0][self.a_i[r]] * ds
            dC = beta[1][self.a_i[r]] * ds
            dM = (dO + dC).sum(1)
            out['turn'][k] = (self.T[r] * (1 - np.exp(-dM))).sum()
            out['orders'][k] = (self.O[r] * (1 - np.exp(-dO.sum(1)))).sum()
            out['check_num'][k] = (self.T[r] * (1 - np.exp(-dC.sum(1)))).sum()   # = orders x check change, rub
            e = self.T[r][:, None] * (1 - np.exp(-(dO + dC)))
            np.add.at(out['by_sc'][k], self.s_i[r], e)
        return out


# ---------------------------------------------------------------- reliability flag

def split_rhat(x: np.ndarray) -> float:
    """x [chains, draws]: split R-hat (Gelman et al. 2013)."""
    n = x.shape[1] // 2
    if n < 2:
        return float('nan')
    y = np.concatenate([x[:, :n], x[:, n:2 * n]], 0)
    m = y.shape[0]
    B = n * y.mean(1).var(ddof=1)
    Wv = y.var(1, ddof=1).mean()
    return float(np.sqrt(((n - 1) / n * Wv + B / n) / Wv)) if Wv > 0 else float('nan')


def cell_support(d: wj.ModelData, arr: dict, roas_draws: pd.DataFrame | None) -> pd.DataFrame:
    """Per segment x channel: fit weeks and units with spend, R-hat of its ROAS, ok (all three pass)."""
    o = d.obs
    pop = d.ad_units.pop_k.to_numpy()[arr['a_i']] * 1000.0
    sp = d.spend_pr[arr['a_i'], arr['w_i'], :] * pop[:, None]
    rows = []
    for s, sname in enumerate(wj.SEGMENTS):
        sel = arr['s_i'] == s
        for j, c in enumerate(wj.CHANNELS):
            if d.chan_mask[s, j] == 0:
                continue
            pos = sp[sel, j] > 0
            weeks = int(np.unique(arr['w_i'][sel][pos]).size)
            units = int(np.unique(arr['a_i'][sel][pos]).size)
            rh = float('nan')
            if roas_draws is not None:
                g = roas_draws[(roas_draws.segment == sname) & (roas_draws.channel == c)]
                if len(g):
                    g = g.sort_values(['chain', 'draw']).assign(k=lambda x: x.groupby('chain').cumcount())
                    piv = g.pivot_table(index='k', columns='chain', values='roas').dropna()   # draw = flat index
                    rh = split_rhat(piv.to_numpy().T)
            ok = weeks >= FLAG_MIN_WEEKS and units >= FLAG_MIN_UNITS and (np.isnan(rh) or rh <= FLAG_RHAT_MAX)
            if roas_draws is not None and np.isnan(rh):
                ok = False
            rows.append(dict(segment=sname, channel=c, fit_weeks_with_spend=weeks, units_with_spend=units,
                             rhat_roas=rh, ok=bool(ok)))
    return pd.DataFrame(rows)
