"""Joint weekly MMM for the fourth pass (panel v3): orders and average check together, turnover = orders x check.

One model for all four segments (ТС5/ТСХ x Онлайн/Оффлайн). For every model unit u (city, or oblast rest per
composition period) and week t, for target k in {orders, check}:

    log y[k,u,t] = a[k,u] + slope[k,u]*t + trend[k,s](t) + season[k,s](t) + city_wave[k,u](t) + holidays
                   + resort summer + gamma[k,s] . controls[u,t] + week_shock[k,s,t]
                   + sum_c beta[k,c,u] * sat_c(adstock_c(spend per resident[c,u,t] / m_ref[s,c])) + e[k,u,t]

    e[k,u,t] = rho[k,s] * e[k,u,t-1] + innovation;  check innovation regressed on the orders innovation.

beta is not sampled directly: it is computed from ROAS at the typical spend m_ref, so the priors are in ROAS
space. R_orders has the owner's moderate log-normal ranges (channel -> segment -> unit for local channels),
R_check is centred at 0. Turnover ROAS = R_orders + R_check at typical spend; the exact number is computed
afterwards by switching each channel off (roas_table).

week_shock is a common, shrunk shock of a segment-week (not a free effect per date): it carries the common
noise that made old intervals 3-5 times too narrow. Every week-level part has one owner (v6): the line belongs to
slope0, the yearly wave to Fourier, single weeks to holidays, the rest of the trend to the hinges, and the shock
only to what none of them can produce. v7: every unit has its own yearly wave around its segment's (shrunk, scale
sig_city_wave): in the real pilot of 03.11 the segment wave alone let cities whose spring rises more than their
segment's pass that rise to the ads that run in spring (OOH in ТС5 stores 9.6; simple fixed-effect fit 14 with a
common wave, 3 with own city waves). Controls enter as deviations from their segment-week mean (the common part
of the weather and of the calendar is owned by the week-level terms). Adstock (normalized geometric, 8 weeks) and saturation
(1 - exp(-x/lambda)) are shared by both targets and all segments of a channel.

Data: panels/04_2025_2026Q2_fourth_pass/v3_20261102 and the national per-1000 table next to it
(prepared/04_2025_2026Q2_fourth_pass/07_media_units_v3_20261102). July-September 2026 are never read.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

CHANNELS = ['Нац_ТВ', 'Рег_ТВ', 'Радио', 'OOH_Total', 'Digital_Performance', 'Нац_ТВ_офлайн_в_онлайн']
NATIONAL_TV_CROSS = 'Нац_ТВ_офлайн_в_онлайн'   # offline-label TV fed to online: off by default since v4 (owner 02.11)
LOCAL_UNIT_DEVIATION = {'Рег_ТВ', 'OOH_Total', 'Digital_Performance'}   # channels with city-level differences
SEGMENTS = ['ТС5/Онлайн', 'ТС5/Оффлайн', 'ТСХ/Онлайн', 'ТСХ/Оффлайн']
TIERS = ['small', 'medium', 'large']
TARGETS = ['orders', 'check']
RESORTS = {'СОЧИ', 'АНАПА', 'ГЕЛЕНДЖИК'}
ADSTOCK_L = 8
KNOT_EVERY_WEEKS = 7
WEEK_SHOCK_CENTRED_MIN_UNITS = 50   # v6: segments with at least this many units get the centred week shock
CITY_WAVE_SD = 0.05   # v7: prior scale of a unit's own yearly wave around its segment's (real spread 0.01-0.05)
# v6: nonworking_share left out: in panel v3 it is the same in every unit each week (national calendar), so after
# removing the segment-week mean nothing is left; the holiday dummies own the calendar.
CONTROLS = ['temp_dev_from_norm_c', 'log1p_precip', 'log1p_snow']

# ROAS priors, log-normal (median, sd of log). Owner's moderate set (30.10.2026): national TV 2 (90% 0.5-8),
# digital 3 (90% 0.5-12), other channels 1.2 (90% 0.28-5.4). Offline-label TV on online turnover: 0.3.
PRIOR_SETS = {
    'moderate': {'Нац_ТВ': (2.0, 0.843), 'Digital_Performance': (3.0, 0.97), 'Рег_ТВ': (1.22, 0.9),
                 'Радио': (1.22, 0.9), 'OOH_Total': (1.22, 0.9), NATIONAL_TV_CROSS: (0.3, 1.1)},
    'meridian': {c: (1.22, 0.9) for c in CHANNELS} | {NATIONAL_TV_CROSS: (0.3, 1.1)},
    'wide': {c: (1.5, 1.4) for c in CHANNELS} | {NATIONAL_TV_CROSS: (0.3, 1.4)},
}
CHECK_ROAS_SD = 0.5        # ROAS through the average check, Normal(0, 0.5) at segment level
ADSTOCK_PRIOR = {'Нац_ТВ': (6, 4), NATIONAL_TV_CROSS: (6, 4), 'Рег_ТВ': (6, 4), 'Радио': (4, 6),
                 'OOH_Total': (4, 6), 'Digital_Performance': (2, 8)}   # Beta(a, b) for weekly decay


@dataclass
class ModelData:
    weeks: pd.DatetimeIndex
    ad_units: pd.DataFrame          # one row per segment|unit_label: seg index, tier, tau, pop_k
    model_units: pd.DataFrame       # one row per segment|model_unit_id: seg index, ad unit index
    spend_pr: np.ndarray            # [A, W, C] rub per resident per week (full history for adstock)
    m_ref: np.ndarray               # [S, C] typical positive weekly spend per resident (0 = channel absent)
    chan_mask: np.ndarray           # [S, C] 1 if the channel is modelled in the segment
    obs: pd.DataFrame               # observations: indices, targets, controls
    trend_basis: np.ndarray         # [W, K] hinges made orthogonal to [1, t, Fourier] (v6)
    t_year: np.ndarray              # [W]
    fourier: np.ndarray             # [W, 4]
    holidays: np.ndarray            # [W, H]
    holiday_names: list
    controls_mean: np.ndarray = field(default_factory=lambda: np.zeros(0))
    controls_sd: np.ndarray = field(default_factory=lambda: np.zeros(0))
    trend_coef: np.ndarray = field(default_factory=lambda: np.zeros(0))   # basis(t) = hinges(t) - [1, t, F] @ coef

    @property
    def dims(self) -> dict:
        return dict(A=len(self.ad_units), M=len(self.model_units), W=len(self.weeks), C=len(CHANNELS),
                    S=len(SEGMENTS), N=len(self.obs), K=self.trend_basis.shape[1], H=self.holidays.shape[1])


def _holiday_matrix(weeks: pd.DatetimeIndex) -> tuple[np.ndarray, list]:
    """Weeks (Mon-Sun) containing Russian retail peaks. Dummies, not free week effects."""
    def contains(month, day):
        return np.array([any((w + pd.Timedelta(days=i)).month == month and (w + pd.Timedelta(days=i)).day == day
                             for i in range(7)) for w in weeks], dtype=float)
    pre_ny = np.array([any((w + pd.Timedelta(days=i)).month == 12 and 24 <= (w + pd.Timedelta(days=i)).day <= 30
                           for i in range(7)) for w in weeks], dtype=float)
    ny = contains(12, 31) + contains(1, 1)
    ny = (ny > 0).astype(float)
    jan_hol = np.array([(w + pd.Timedelta(days=3)).month == 1 and (w + pd.Timedelta(days=3)).day <= 10 for w in weeks],
                       dtype=float) * (1 - ny)
    cols = {'pre_new_year': pre_ny * (1 - ny), 'new_year': ny, 'jan_holidays': jan_hol,
            'feb23': contains(2, 23), 'mar8': contains(3, 8), 'may1': contains(5, 1), 'may9': contains(5, 9),
            'jun12': contains(6, 12), 'nov4': contains(11, 4)}
    return np.column_stack(list(cols.values())), list(cols)


def prepare(panel_path: str, national_csv: str, fit_window_end: str | None = None, cross_tv: bool = False,
            top_units_per_segment: int | None = None) -> ModelData:
    """top_units_per_segment: keep only the N largest units of each segment by turnover (fast/medium stages)."""
    p = pd.read_parquet(panel_path)
    assert p.week_start.max() <= pd.Timestamp('2026-06-22'), 'панель выходит за 28.06.2026'
    if top_units_per_segment:
        tot = p[p.target_valid_week & p.fit_exclude_reason.fillna('').eq('')].groupby(['segment', 'unit_label']).turnover_total.sum()
        keep = {(s, u) for s, g in tot.groupby(level=0) for (_, u) in g.nlargest(top_units_per_segment).index}
        p = p[[(s, u) in keep for s, u in zip(p.segment, p.unit_label)]].copy()
    nat = pd.read_csv(national_csv, encoding='utf-8-sig', parse_dates=['week_start'])
    weeks = pd.DatetimeIndex(sorted(p.week_start.unique()))
    W = len(weeks)
    widx = {w: i for i, w in enumerate(weeks)}
    sidx = {s: i for i, s in enumerate(SEGMENTS)}
    p['seg_i'] = p.segment.map(sidx)
    p['ad_key'] = p.segment + '|' + p.unit_label
    p['mu_key'] = p.segment + '|' + p.model_unit_id
    p['w_i'] = p.week_start.map(widx)

    ok = (p.target_valid_week & p.fit_exclude_reason.fillna('').eq('') & ~p.warmup_week
          & (p.turnover_total > 0) & (p.orders_cnt > 0))
    if fit_window_end is not None:
        ok &= p.week_start <= pd.Timestamp(fit_window_end)

    ad = (p.groupby('ad_key').agg(segment=('segment', 'first'), seg_i=('seg_i', 'first'), unit_label=('unit_label', 'first'),
                                  network=('network', 'first'), channel=('channel', 'first'), tier=('size_tier', 'first'),
                                  pop_k=('population_k', 'max'))
          .reset_index())
    tpr = (p[ok].assign(tpr=p.turnover_total / (p.population_k * 1000)).groupby('ad_key').tpr.median())
    ad['tau'] = ad.ad_key.map(tpr)
    ad['tier_i'] = ad.tier.map({t: i for i, t in enumerate(TIERS)}).fillna(0).astype(int)
    ad['resort'] = ad.unit_label.isin(RESORTS).astype(int)
    ad = ad[ad.tau.notna()].reset_index(drop=True)      # units with no usable week carry nothing
    aidx = {k: i for i, k in enumerate(ad.ad_key)}
    A, C, S = len(ad), len(CHANNELS), len(SEGMENTS)

    # full spend history per ad unit: own rows where present, national per-1000 where the unit did not exist yet
    spend = np.zeros((A, W, C))
    q = p[p.ad_key.isin(aidx)]
    a_i = q.ad_key.map(aidx).to_numpy()
    for j, c in enumerate(CHANNELS[:5]):
        spend[a_i, q.w_i.to_numpy(), j] = q[f'spend_{c}'].to_numpy()
    present = np.zeros((A, W), bool)
    present[a_i, q.w_i.to_numpy()] = True
    natp = nat.pivot_table(index=['segment', 'week_start'], columns='model_channel', values='rub_per_1000', aggfunc='sum').fillna(0)
    for i, r in ad.iterrows():
        for j, c in enumerate(CHANNELS[:5]):
            if c not in natp.columns:
                continue
            ser = natp[c].xs(r.segment, level='segment') if r.segment in natp.index.get_level_values(0) else None
            if ser is None:
                continue
            v = ser.reindex(weeks).fillna(0).to_numpy() * r.pop_k
            spend[i, ~present[i], j] = v[~present[i]]
        if r.channel == 'Онлайн':      # offline-label national TV of the same network, per resident x population
            off = f'{r.network}/Оффлайн'
            if off in natp.index.get_level_values(0) and 'Нац_ТВ' in natp.columns:
                spend[i, :, C - 1] = natp['Нац_ТВ'].xs(off, level='segment').reindex(weeks).fillna(0).to_numpy() * r.pop_k
    spend_pr = spend / (ad.pop_k.to_numpy()[:, None, None] * 1000.0)

    m_ref = np.zeros((S, C))
    for s in range(S):
        sel = ad.seg_i.to_numpy() == s
        for j in range(C):
            x = spend_pr[sel, :, j]
            pos = x[x > 0]
            if pos.size >= 20:
                m_ref[s, j] = pos.mean()
    chan_mask = (m_ref > 0).astype(float)
    if not cross_tv:      # owner 02.11: store ads act only on stores, delivery ads only on delivery (no cross channel)
        chan_mask[:, CHANNELS.index(NATIONAL_TV_CROSS)] = 0.0

    mu = (p[p.ad_key.isin(aidx)].groupby('mu_key').agg(ad_key=('ad_key', 'first'), seg_i=('seg_i', 'first'))
          .reset_index())
    mu = mu[mu.mu_key.isin(p[ok].mu_key)].reset_index(drop=True)
    midx = {k: i for i, k in enumerate(mu.mu_key)}
    mu['ad_i'] = mu.ad_key.map(aidx)

    o = p[ok & p.mu_key.isin(midx)].copy().sort_values(['mu_key', 'week_start']).reset_index(drop=True)
    o['m_i'] = o.mu_key.map(midx)
    o['a_i'] = o.ad_key.map(aidx)
    o['tier_i'] = o.size_tier.map({t: i for i, t in enumerate(TIERS)}).fillna(0).astype(int)
    o['y_orders'] = np.log(o.orders_cnt)
    o['y_check'] = np.log(o.turnover_total / o.orders_cnt)
    o['nonworking_share'] = o.nonworking_days / o.n_calendar_days
    o['log1p_precip'] = np.log1p(o.precipitation_mm.fillna(0).clip(lower=0))
    o['log1p_snow'] = np.log1p(o.snow_fall_cm.fillna(0).clip(lower=0))
    o['temp_dev_from_norm_c'] = o.temp_dev_from_norm_c.fillna(0)
    # v6: controls keep only their deviation from the segment-week mean. The common part (national calendar of days
    # off, a cold week everywhere) is owned by holidays, season and the week shock; before, both owned it
    # (pilot v4: R-hat 1.5 on holidays, 1.3 on gamma).
    o[CONTROLS] = o[CONTROLS] - o.groupby(['seg_i', 'w_i'])[CONTROLS].transform('mean')
    X = o[CONTROLS].to_numpy(float)
    cm, cs = X.mean(0), X.std(0) + 1e-9
    o[CONTROLS] = (X - cm) / cs
    prev_pos = o.groupby('m_i').cumcount()
    same = (o.m_i.shift(1) == o.m_i) & (o.w_i.shift(1) == o.w_i - 1)
    o['prev'] = np.where(same, np.arange(len(o)) - 1, -1)
    o['first_in_unit'] = prev_pos.eq(0)
    o['resort'] = o.unit_label.isin(RESORTS).astype(int)

    t = (weeks - weeks[0]).days.to_numpy() / 365.25
    t_c = t - t.mean()
    knots = t[KNOT_EVERY_WEEKS:-1:KNOT_EVERY_WEEKS]          # v6: no knot at the last week (all-zero column)
    basis = np.maximum(0.0, t[:, None] - knots[None, :])
    doy = (weeks + pd.Timedelta(days=3)).dayofyear.to_numpy() / 365.25
    fourier = np.column_stack([np.sin(2 * np.pi * doy), np.cos(2 * np.pi * doy),
                               np.sin(4 * np.pi * doy), np.cos(4 * np.pi * doy)])
    hol, hol_names = _holiday_matrix(weeks)
    # week-level terms are centred over the weeks: they carry no level, the unit level a[k,u] does. Without this
    # the common shift of all unit levels and of the trend is a flat ridge (pilot 02.11: R-hat 6 on level/trend).
    basis = basis - basis.mean(0)
    fourier = fourier - fourier.mean(0)
    hol = hol - hol.mean(0)
    # v6: over 78 weeks the hinges reproduce the yearly Fourier pair almost exactly (R2 0.999; half-year pair 0.98)
    # and contain the straight line: flat ridges between trend, season and slope0 (fast v5: R-hat about 1.5 on
    # fourier, tau_trend, slope0, z_trend). The hinges are made orthogonal to [1, t, Fourier]; same fitted space.
    G = np.column_stack([np.ones_like(t_c), t_c, fourier])
    trend_coef = np.linalg.lstsq(G, basis, rcond=None)[0]
    basis = basis - G @ trend_coef
    return ModelData(weeks=weeks, ad_units=ad, model_units=mu, spend_pr=spend_pr, m_ref=m_ref, chan_mask=chan_mask,
                     obs=o, trend_basis=basis, t_year=t_c, fourier=fourier, holidays=hol, holiday_names=hol_names,
                     controls_mean=cm, controls_sd=cs, trend_coef=trend_coef)


# ---------------------------------------------------------------- model (numpyro / JAX)

def adstock_sat(spend_norm, alpha, lam):
    """spend_norm [A, W, C] (spend per resident / m_ref); alpha, lam [C]. Returns sat [A, W, C] and sat(1) [C]."""
    import jax.numpy as jnp
    A, W, C = spend_norm.shape
    lags = jnp.arange(ADSTOCK_L)
    w = alpha[None, :] ** lags[:, None]               # [L, C]
    w = w / w.sum(0, keepdims=True)
    pad = jnp.concatenate([jnp.zeros((A, ADSTOCK_L - 1, C)), spend_norm], axis=1)
    x = sum(w[l][None, None, :] * pad[:, ADSTOCK_L - 1 - l: ADSTOCK_L - 1 - l + W, :] for l in range(ADSTOCK_L))
    sat = 1.0 - jnp.exp(-x / lam[None, None, :])
    return sat, 1.0 - jnp.exp(-1.0 / lam)


def with_targets(arr: dict, y: np.ndarray) -> dict:
    """Copy of arr whose unit means (ybar) come from targets y [2, N] (real or simulated)."""
    m = arr['m_i']
    cnt = np.bincount(m)
    ybar = np.stack([np.bincount(m, weights=y[k]) / cnt for k in range(2)], 1)[m]
    return arr | {'ybar': ybar}


def _week_projector(t: np.ndarray, *week_terms: np.ndarray) -> np.ndarray:
    """[W, W] projector that removes from a week series the mean, the straight line and every modelled week-level
    term (trend hinges, Fourier, holidays). v2 removed the level and the line; v5 also the other week terms, which
    the shock could copy at no cost (pilot v4: R-hat 1.7 on the week shock, 1.6 on holidays, 1.3 on Fourier)."""
    X = np.column_stack([np.ones_like(t), t] + [np.reshape(m, (len(t), -1)) for m in week_terms])
    return np.eye(len(t)) - X @ np.linalg.pinv(X, rcond=1e-8)


def _week_basis(t: np.ndarray, *week_terms: np.ndarray) -> np.ndarray:
    """[W, R] orthonormal basis of the week series no modelled week term can produce (range of _week_projector).

    v6: the shock is written in these R coordinates. In v5 it was P @ z with z of length W, so W - R directions of z
    never touched the data; they are not along single coordinates, the sampler's per-coordinate scaling cannot
    handle them, and they wandered (fast v5: R-hat 2.1 on z_week). Q z with z ~ N(0, I_R) is the same prior N(0, P).
    """
    vals, vecs = np.linalg.eigh(_week_projector(t, *week_terms))
    return vecs[:, vals > 0.5]


def model_arrays(d: ModelData, city_wave: bool = True) -> dict:
    """Arrays of the model. city_wave=False gives the v6 model exactly (no own yearly wave per unit)."""
    o = d.obs
    ad = d.ad_units
    seg_m = d.model_units.seg_i.to_numpy()
    M = len(d.model_units)
    resort_m = (np.bincount(o.m_i, o.resort, minlength=M) > 0).astype(int)
    # own waves are deviations from the wave of their group (segment x resort): the group's wave is owned by the
    # segment Fourier and the resort Fourier, so the mean of the own waves of a group is not a second owner
    grp_m = seg_m * 2 + resort_m
    G = 2 * len(SEGMENTS)
    return dict(
        city_wave=bool(city_wave),
        wave_grp_m=grp_m, wave_grp_onehot_m=np.eye(G)[grp_m],
        wave_grp_count_m=np.maximum(np.bincount(grp_m, minlength=G), 1).astype(float),
        spend_norm=np.where(d.m_ref[ad.seg_i.to_numpy()][:, None, :] > 0,
                            d.spend_pr / np.where(d.m_ref > 0, d.m_ref, 1.0)[ad.seg_i.to_numpy()][:, None, :], 0.0),
        m_ref_a=d.m_ref[ad.seg_i.to_numpy()],                 # [A, C]
        mask_a=d.chan_mask[ad.seg_i.to_numpy()],              # [A, C]
        tau_a=ad.tau.to_numpy(),
        seg_a=ad.seg_i.to_numpy(), tier_a=ad.tier_i.to_numpy(),
        local_c=np.array([c in LOCAL_UNIT_DEVIATION for c in CHANNELS], float),
        m_i=o.m_i.to_numpy(), a_i=o.a_i.to_numpy(), w_i=o.w_i.to_numpy(), s_i=o.seg_i.to_numpy(),
        tier_i=o.tier_i.to_numpy(), prev=o.prev.to_numpy(), resort=o.resort.to_numpy().astype(float),
        X=o[CONTROLS].to_numpy(float), basis=d.trend_basis, t=d.t_year, F=d.fourier, H=d.holidays,
        seg_m=d.model_units.seg_i.to_numpy(),
        seg_onehot_m=np.eye(len(SEGMENTS))[d.model_units.seg_i.to_numpy()],          # [M, S]
        seg_count_m=np.maximum(np.bincount(d.model_units.seg_i.to_numpy(), minlength=len(SEGMENTS)), 1),
        week_basis=_week_basis(d.t_year, d.trend_basis, d.fourier, d.holidays),              # [W, R]
        # v6: centred shock where a segment has many units (each week's shock is pinned by the data, and the
        # non-centred form makes a curved ridge between sig_week and every coefficient); non-centred otherwise
        wk_centred=(np.bincount(d.model_units.seg_i.to_numpy(), minlength=len(SEGMENTS)) >= WEEK_SHOCK_CENTRED_MIN_UNITS
                    ).astype(float),
        ybar=np.column_stack([o.groupby('m_i').y_orders.transform('mean'), o.groupby('m_i').y_check.transform('mean')]),
    )


def numpyro_model(arr: dict, dims: dict, prior_set: str = 'moderate', y=None):
    import jax.numpy as jnp
    import numpyro
    import numpyro.distributions as dist
    A, M, W, C, S, K, H = (dims[k] for k in 'AMWCSKH')
    N = len(arr['m_i'])
    pri = PRIOR_SETS[prior_set]

    # media: adstock + saturation shared across segments and targets
    a_ab = np.array([ADSTOCK_PRIOR[c] for c in CHANNELS], float)
    alpha = numpyro.sample('alpha', dist.Beta(a_ab[:, 0], a_ab[:, 1]))
    lam = numpyro.sample('lam', dist.LogNormal(0.0, 0.5).expand([C]))
    sat, sat1 = adstock_sat(arr['spend_norm'], alpha, lam)

    mu_r = np.log([pri[c][0] for c in CHANNELS]); sd_r = np.array([pri[c][1] for c in CHANNELS])
    logR = numpyro.sample('logR_orders', dist.Normal(mu_r, sd_r))                          # [C] channel level
    sig_seg = numpyro.sample('sig_seg', dist.HalfNormal(0.4))
    z_seg = numpyro.sample('z_seg', dist.Normal(0, 1).expand([S, C]))
    logR_s = logR[None, :] + sig_seg * z_seg                                             # [S, C]
    sig_tier = numpyro.sample('sig_tier', dist.HalfNormal(0.2))
    z_tier = numpyro.sample('z_tier', dist.Normal(0, 1).expand([3, C]))
    sig_unit = numpyro.sample('sig_unit', dist.HalfNormal(0.3))
    z_unit = numpyro.sample('z_unit', dist.Normal(0, 1).expand([A, C]))
    logR_a = (logR_s[arr['seg_a']] + sig_tier * z_tier[arr['tier_a']]
              + sig_unit * z_unit * arr['local_c'][None, :])
    R_orders_a = jnp.exp(logR_a)                                                         # [A, C]
    R_check_s = numpyro.sample('R_check', dist.Normal(0, CHECK_ROAS_SD).expand([S, C]))
    R_check_a = R_check_s[arr['seg_a']]
    numpyro.deterministic('R_orders_seg', jnp.exp(logR_s))
    conv = arr['m_ref_a'] / (arr['tau_a'][:, None] * sat1[None, :]) * arr['mask_a']    # ROAS -> beta
    beta = jnp.stack([R_orders_a * conv, R_check_a * conv])                              # [2, A, C]
    contrib = jnp.einsum('kac,awc->kaw', beta, sat)                                      # [2, A, W]
    media = contrib[:, arr['a_i'], arr['w_i']]                                           # [2, N]

    # base
    a_m = numpyro.sample('a', dist.Normal(0, 0.3).expand([2, M]))
    sig_slope = numpyro.sample('sig_slope', dist.HalfNormal(0.2).expand([2]))
    z_slope = numpyro.sample('z_slope', dist.Normal(0, 1).expand([2, M]))
    # unit slopes are deviations from the segment slope: centred within each segment
    z_slope = z_slope - (z_slope @ arr['seg_onehot_m'] / arr['seg_count_m'][None, :])[:, arr['seg_m']]
    slope0 = numpyro.sample('slope0', dist.Normal(0, 0.3).expand([2, S]))
    tau_tr = numpyro.sample('tau_trend', dist.HalfNormal(0.5).expand([2]))
    z_tr = numpyro.sample('z_trend', dist.Normal(0, 1).expand([2, S, K]))
    trend = slope0[:, :, None] * arr['t'][None, None, :] + jnp.einsum('wk,jsk->jsw', arr['basis'], tau_tr[:, None, None] * z_tr)
    four = numpyro.sample('fourier', dist.Normal(0, 0.3).expand([2, S, 4]))     # v6: owns the whole yearly wave
    four_res = numpyro.sample('fourier_resort', dist.Normal(0, 0.2).expand([2, 4]))
    hol = numpyro.sample('holidays', dist.Normal(0, 0.2).expand([2, S, H]))
    season = jnp.einsum('wf,jsf->jsw', arr['F'], four) + jnp.einsum('wh,jsh->jsw', arr['H'], hol)
    gam = numpyro.sample('gamma', dist.Normal(0, 0.05).expand([2, S, arr['X'].shape[1]]))
    sig_wk = numpyro.sample('sig_week', dist.HalfNormal(0.03).expand([2, S]))
    c_wk = arr['wk_centred'][None, :, None]                                             # 1 centred, 0 non-centred
    R = arr['week_basis'].shape[1]
    v_wk = numpyro.sample('v_week', dist.Normal(0, sig_wk[:, :, None] ** c_wk).expand([2, S, R]))
    week_shock = jnp.einsum('jsr,wr->jsw', v_wk * sig_wk[:, :, None] ** (1 - c_wk), arr['week_basis'])
    base_sw = trend + season + week_shock                                                # [2, S, W]
    s_i, w_i, m_i = arr['s_i'], arr['w_i'], arr['m_i']
    mu = (arr['ybar'].T + a_m[:, m_i] + (sig_slope[:, None] * z_slope)[:, m_i] * arr['t'][w_i][None, :]
          + base_sw[:, s_i, w_i] + (four_res @ arr['F'][w_i].T) * arr['resort'][None, :]
          + jnp.einsum('jnx,nx->jn', gam[:, s_i, :], arr['X']) + media)
    if arr.get('city_wave', False):
        # v7: own yearly wave of every unit, a shrunk deviation from its group's wave (centred within the group)
        sig_cw = numpyro.sample('sig_city_wave', dist.HalfNormal(CITY_WAVE_SD).expand([2, S]))
        z_cw = numpyro.sample('z_city_wave', dist.Normal(0, 1).expand([2, M, arr['F'].shape[1]]))
        g_mean = jnp.einsum('jmf,mg->jgf', z_cw, arr['wave_grp_onehot_m'] / arr['wave_grp_count_m'][None, :])
        z_cw = z_cw - g_mean[:, arr['wave_grp_m'], :]
        cw = sig_cw[:, arr['seg_m'], None] * z_cw                                       # [2, M, F]
        mu = mu + jnp.einsum('jnf,nf->jn', cw[:, m_i, :], arr['F'][w_i])

    # AR(1) errors per target and segment, check innovation regressed on the orders innovation
    rho = numpyro.sample('rho', dist.Beta(8, 2).expand([2, S]))
    sig = numpyro.sample('sigma', dist.HalfNormal(0.1).expand([2, S, 3]))
    b_oc = numpyro.sample('b_check_on_orders', dist.Normal(0, 0.5).expand([S]))
    nu = 6.0
    if y is None:
        return
    r = y - mu                                                                          # [2, N]
    has_prev = arr['prev'] >= 0
    prev = np.where(has_prev, arr['prev'], 0)
    rho_n = rho[:, s_i]
    e = jnp.where(has_prev[None, :], r - rho_n * r[:, prev], r * jnp.sqrt(1 - rho_n ** 2))
    sc = sig[:, s_i, arr['tier_i']]
    e_c_cond = e[1] - b_oc[s_i] * e[0] * sc[1] / sc[0]
    # first week of a run: stationary scale; Jacobian of r -> e = r*sqrt(1-rho^2)
    numpyro.factor('ar_first_jacobian', 0.5 * jnp.sum(jnp.where(has_prev[None, :], 0.0, jnp.log1p(-rho_n ** 2))))
    numpyro.sample('lik_orders', dist.StudentT(nu, 0.0, sc[0]), obs=e[0])
    numpyro.sample('lik_check', dist.StudentT(nu, 0.0, sc[1]), obs=e_c_cond)


# ---------------------------------------------------------------- start of sampling: mode search from several starts

ROAS_KEYS = ['alpha', 'lam', 'logR_orders', 'sig_seg', 'z_seg', 'sig_tier', 'z_tier', 'sig_unit', 'z_unit', 'R_check']


def multi_start_map(arr: dict, dims: dict, prior_set: str, y, n_starts: int = 8, steps: int = 4000,
                    seed: int = 0, radius: float = 2.0, lr: tuple = (0.03, 0.003)) -> list[dict]:
    """Search the posterior mode from several starts (point estimate + Adam), compiled once.

    Start 0 is the prior median; the others are random points (uniform in [-radius, radius] on the unconstrained
    scale, as NUTS starts by default). Each result: start, loss (= minus log joint at the end, lower is better),
    loss_at_75pct (to see whether it settled), unconstrained point (for NUTS init_params) and the constrained
    values of the ROAS keys. The pilot of 02.11 showed a chain stuck in a false solution: comparing the losses
    of the starts tells a sampler trap (much worse loss) from a solution the data cannot rule out (similar loss).
    """
    import jax
    import jax.numpy as jnp
    import numpyro
    from numpyro.infer import SVI, Trace_ELBO
    from numpyro.infer.autoguide import AutoDelta
    from numpyro.infer.initialization import init_to_median
    from numpyro.infer.svi import SVIState

    guide = AutoDelta(numpyro_model, init_loc_fn=init_to_median(num_samples=15))
    optim = numpyro.optim.Adam(lambda i: lr[0] * (lr[1] / lr[0]) ** (i / steps))
    svi = SVI(numpyro_model, guide, optim, Trace_ELBO())
    state0 = svi.init(jax.random.PRNGKey(seed), arr, dims, prior_set, y=y)

    @jax.jit
    def run(state):
        def body(st, _):
            return svi.update(st, arr, dims, prior_set, y=y)
        return jax.lax.scan(body, state, None, length=steps)

    u0 = svi.optim.get_params(state0.optim_state)
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n_starts):
        if i == 0:
            st = state0
        else:
            u = {k: jnp.asarray(rng.uniform(-radius, radius, np.shape(v)), dtype=jnp.result_type(v)) for k, v in u0.items()}
            st = SVIState(svi.optim.init(u), state0.mutable_state, jax.random.PRNGKey(seed + i))
        st, losses = run(st)
        losses = np.asarray(losses)
        u_end = svi.optim.get_params(st.optim_state)
        c_end = svi.get_params(st)
        suffix = '_auto_loc'
        out.append(dict(start=i, init='prior_median' if i == 0 else f'random_{radius:g}',
                        loss=float(np.mean(losses[-50:])), loss_at_75pct=float(np.mean(losses[int(0.75 * steps) - 50:int(0.75 * steps)])),
                        finite=bool(np.isfinite(losses[-1])),
                        unconstrained={k[:-len(suffix)]: np.asarray(v) for k, v in u_end.items() if k.endswith(suffix)},
                        point={k[:-len(suffix)]: np.asarray(v) for k, v in c_end.items() if k.endswith(suffix)}))
    return out


def multi_start_vi(arr: dict, dims: dict, prior_set: str, y, n_starts: int = 8, steps: int = 15000,
                   seed: int = 0, radius: float = 2.0, lr: tuple = (0.01, 0.001), init_scale: float = 0.05,
                   tail: int = 1000) -> list[dict]:
    """Approximate the posterior from several starts (independent normals on the unconstrained scale), compiled once.

    Version 3 (02.11 after the v2 pilot): on all 621 units the single best point (multi_start_map) is degenerate,
    the city deviations of the local channels fit noise and blow their ROAS up to 12-176 in both simulated worlds,
    while the sampled posterior of the v1 pilot sat at sane values. The approximation counts the volume of the
    posterior, not only its peak, so its centre lies where the posterior mass is. Each result: start, loss
    (= minus ELBO averaged over the last `tail` steps, lower is better), loss_at_75pct, unconstrained centre and
    scale (NUTS chains start at draws from this approximation) and the constrained centre of every latent site.
    """
    import jax
    import jax.numpy as jnp
    import numpyro
    from numpyro.infer import SVI, Trace_ELBO
    from numpyro.infer.autoguide import AutoNormal
    from numpyro.infer.initialization import init_to_median
    from numpyro.infer.svi import SVIState

    guide = AutoNormal(numpyro_model, init_loc_fn=init_to_median(num_samples=15), init_scale=init_scale)
    optim = numpyro.optim.Adam(lambda i: lr[0] * (lr[1] / lr[0]) ** (i / steps))
    svi = SVI(numpyro_model, guide, optim, Trace_ELBO())
    state0 = svi.init(jax.random.PRNGKey(seed), arr, dims, prior_set, y=y)

    @jax.jit
    def run(state):
        def body(st, _):
            return svi.update(st, arr, dims, prior_set, y=y)
        return jax.lax.scan(body, state, None, length=steps)

    u0 = svi.optim.get_params(state0.optim_state)
    rng = np.random.default_rng(seed)
    loc_sfx, sc_sfx = '_auto_loc', '_auto_scale'
    out = []
    for i in range(n_starts):
        if i == 0:
            st = state0
        else:
            u = {k: (jnp.asarray(rng.uniform(-radius, radius, np.shape(v)), dtype=jnp.result_type(v))
                     if k.endswith(loc_sfx) else v) for k, v in u0.items()}
            st = SVIState(svi.optim.init(u), state0.mutable_state, jax.random.PRNGKey(seed + i))
        st, losses = run(st)
        losses = np.asarray(losses)
        c_end = svi.get_params(st)
        q = int(0.75 * steps)
        out.append(dict(start=i, init='prior_median' if i == 0 else f'random_{radius:g}',
                        loss=float(np.mean(losses[-tail:])), loss_at_75pct=float(np.mean(losses[max(q - tail, 0):q])),
                        finite=bool(np.all(np.isfinite(losses[-tail:]))),
                        unconstrained={k[:-len(loc_sfx)]: np.asarray(v) for k, v in c_end.items() if k.endswith(loc_sfx)},
                        scale={k[:-len(sc_sfx)]: np.asarray(v) for k, v in c_end.items() if k.endswith(sc_sfx)},
                        point={k: np.asarray(v) for k, v in guide.median(c_end).items()}))
    return out


def init_params_from(start: dict, n_chains: int, jitter: float = 0.05, seed: int = 0) -> dict:
    """NUTS init_params [chains, ...] (unconstrained): draws from the approximation when it has scales (v3),
    otherwise the point with a small jitter per chain (v2)."""
    rng = np.random.default_rng(seed)
    sc = start.get('scale') or {}
    return {k: v[None] + (sc[k][None] if k in sc else jitter) * rng.standard_normal((n_chains,) + v.shape)
            for k, v in start['unconstrained'].items()}


# ---------------------------------------------------------------- ROAS by switching channels off

def media_contrib_draw(arr: dict, draw: dict) -> np.ndarray:
    """Per-channel log contributions [2, A, W, C] for one posterior draw (numpy)."""
    import jax.numpy as jnp
    sat, sat1 = adstock_sat(arr['spend_norm'], jnp.asarray(draw['alpha']), jnp.asarray(draw['lam']))
    logR_s = draw['logR_orders'][None, :] + draw['sig_seg'] * draw['z_seg']
    logR_a = (logR_s[arr['seg_a']] + draw['sig_tier'] * draw['z_tier'][arr['tier_a']]
              + draw['sig_unit'] * draw['z_unit'] * arr['local_c'][None, :])
    conv = arr['m_ref_a'] / (arr['tau_a'][:, None] * np.asarray(sat1)[None, :]) * arr['mask_a']
    beta = np.stack([np.exp(logR_a) * conv, draw['R_check'][arr['seg_a']] * conv])
    return np.asarray(beta)[:, :, None, :] * np.asarray(sat)[None]


def roas_from_contrib(d: ModelData, arr: dict, contrib: np.ndarray, turnover: np.ndarray) -> pd.DataFrame:
    """Turnover ROAS by segment and channel: sum over observed unit-weeks of T*(1-exp(-(cO+cC))) / spend.

    contrib [2, A, W, C]; turnover [N] observed (or simulated) weekly turnover of the fit rows.
    Spend is counted on the same unit-weeks. The orders/check split is proportional to cO and cC.
    """
    a_i, w_i = arr['a_i'], arr['w_i']
    cO = contrib[0][a_i, w_i, :]
    cC = contrib[1][a_i, w_i, :]
    tot = cO + cC
    inc = turnover[:, None] * (1 - np.exp(-tot))
    share_o = np.divide(cO, tot, out=np.full_like(cO, 0.5), where=np.abs(tot) > 1e-12)
    pop = d.ad_units.pop_k.to_numpy()[a_i] * 1000
    spend = d.spend_pr[a_i, w_i, :] * pop[:, None]
    seg = arr['s_i']
    rows = []
    for s, sname in enumerate(SEGMENTS):
        sel = seg == s
        for j, c in enumerate(CHANNELS):
            sp = spend[sel, j].sum()
            if sp <= 0 or d.chan_mask[s, j] == 0:
                continue
            rows.append(dict(segment=sname, channel=c, spend_rub=sp, effect_rub=inc[sel, j].sum(),
                             effect_orders_rub=(inc[sel, j] * share_o[sel, j]).sum(),
                             roas=inc[sel, j].sum() / sp))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- simulated world

def real_city_waves(d: ModelData, arr: dict, min_obs: int = 26) -> np.ndarray:
    """Each model unit's own yearly wave in the real data, [2, M, F]: Fourier part of a fit of the unit's log target
    around its segment's week mean, with the unit's own level and line. Used to put the real trap into a world."""
    o = d.obs
    M, nf = len(d.model_units), d.fourier.shape[1]
    m_i, w_i = arr['m_i'], arr['w_i']
    out = np.zeros((2, M, nf))
    for k, col in enumerate(['y_orders', 'y_check']):
        dm = o[col] - o.groupby('m_i')[col].transform('mean')
        r = (dm - dm.groupby([o.seg_i, o.w_i]).transform('mean')).to_numpy()
        for m in range(M):
            sel = m_i == m
            if sel.sum() < min_obs:
                continue
            Z = np.column_stack([np.ones(sel.sum()), d.t_year[w_i[sel]], d.fourier[w_i[sel]]])
            out[k, m] = np.linalg.lstsq(Z, r[sel], rcond=None)[0][2:]
    return out


def simulate(d: ModelData, arr: dict, truth: dict, seed: int = 0) -> tuple[np.ndarray, dict]:
    """Targets from the model with known parameters, real spend, real units and real baseline shape.

    truth: R_orders {channel: ROAS through orders}, R_check {channel: ROAS through check}, alpha {c}, lam {c},
    unit_sd (log sd of unit ROAS deviation for local channels), rho (orders, check), sigma (orders, check),
    sig_week (orders, check), b_check_on_orders, city_wave (bool: add every unit's own real yearly wave, v7 world C).
    Baseline per segment = real segment-week mean of unit-demeaned log target, smoothed over 5 weeks.
    """
    rng = np.random.default_rng(seed)
    o = d.obs
    C, S, A = len(CHANNELS), len(SEGMENTS), len(d.ad_units)
    draw = dict(alpha=np.array([truth['alpha'][c] for c in CHANNELS]), lam=np.array([truth['lam'][c] for c in CHANNELS]),
                logR_orders=np.log([truth['R_orders'][c] for c in CHANNELS]), sig_seg=0.0, z_seg=np.zeros((S, C)),
                sig_tier=0.0, z_tier=np.zeros((3, C)), sig_unit=truth.get('unit_sd', 0.3),
                z_unit=rng.standard_normal((A, C)),
                R_check=np.tile([truth['R_check'][c] for c in CHANNELS], (S, 1)))
    contrib = media_contrib_draw(arr, draw)                                    # [2, A, W, C]
    media = contrib.sum(-1)[:, arr['a_i'], arr['w_i']]                          # [2, N]
    ys = []
    for k, col in enumerate(['y_orders', 'y_check']):
        dm = o[col] - o.groupby('m_i')[col].transform('mean')
        sw = dm.groupby([o.seg_i, o.w_i]).mean().unstack(0).reindex(range(len(d.weeks))).ffill().bfill()
        smooth = sw.rolling(5, center=True, min_periods=1).mean()
        base = smooth.to_numpy()[arr['w_i'], arr['s_i']]
        shock = rng.normal(0, truth['sig_week'][k], (S, len(d.weeks)))[arr['s_i'], arr['w_i']]
        ys.append(o.groupby('m_i')[col].transform('mean').to_numpy() + base + shock)
    y = np.vstack(ys) + media
    if truth.get('city_wave', False):
        cw = real_city_waves(d, arr)
        y = y + np.einsum('jnf,nf->jn', cw[:, arr['m_i'], :], d.fourier[arr['w_i']])
    # AR(1) noise per model unit, check innovations correlated with orders innovations
    eps = np.zeros_like(y)
    rho, sig, b = truth['rho'], truth['sigma'], truth['b_check_on_orders']
    for n in range(len(o)):
        pv = arr['prev'][n]
        io = rng.standard_t(6) * sig[0]
        ic = b * io * sig[1] / sig[0] + rng.standard_t(6) * sig[1]
        if pv >= 0:
            eps[0, n] = rho[0] * eps[0, pv] + io
            eps[1, n] = rho[1] * eps[1, pv] + ic
        else:
            eps[0, n] = io / np.sqrt(1 - rho[0] ** 2)
            eps[1, n] = ic / np.sqrt(1 - rho[1] ** 2)
    y = y + eps
    turnover = np.exp(y[0] + y[1])
    truth_roas = roas_from_contrib(d, arr, contrib, turnover)
    return y, dict(contrib=contrib, turnover=turnover, roas=truth_roas)
