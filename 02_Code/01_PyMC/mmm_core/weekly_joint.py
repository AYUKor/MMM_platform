"""Joint weekly MMM for the fourth pass (panel v3): orders and average check together, turnover = orders x check.

One model for all four segments (ТС5/ТСХ x Онлайн/Оффлайн). For every model unit u (city, or oblast rest per
composition period) and week t, for target k in {orders, check}:

    log y[k,u,t] = a[k,u] + slope[k,u]*t + trend[k,s](t) + season[k,s](t) + holidays + resort summer
                   + gamma[k,s] . controls[u,t] + week_shock[k,s,t]
                   + sum_c beta[k,c,u] * sat_c(adstock_c(spend per resident[c,u,t] / m_ref[s,c])) + e[k,u,t]

    e[k,u,t] = rho[k,s] * e[k,u,t-1] + innovation;  check innovation regressed on the orders innovation.

beta is not sampled directly: it is computed from ROAS at the typical spend m_ref, so the priors are in ROAS
space. R_orders has the owner's moderate log-normal ranges (channel -> segment -> unit for local channels),
R_check is centred at 0. Turnover ROAS = R_orders + R_check at typical spend; the exact number is computed
afterwards by switching each channel off (roas_table).

week_shock is a common, shrunk shock of a segment-week (not a free effect per date): it carries the common
noise that made old intervals 3-5 times too narrow. Adstock (normalized geometric, 8 weeks) and saturation
(1 - exp(-x/lambda)) are shared by both targets and all segments of a channel.

Data: panels/04_2025_2026Q2_fourth_pass/v3_20261102 and the national per-1000 table next to it
(prepared/04_2025_2026Q2_fourth_pass/07_media_units_v3_20261102). July-September 2026 are never read.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

CHANNELS = ['Нац_ТВ', 'Рег_ТВ', 'Радио', 'OOH_Total', 'Digital_Performance', 'Нац_ТВ_офлайн_в_онлайн']
NATIONAL_TV_CROSS = 'Нац_ТВ_офлайн_в_онлайн'   # TV of the offline label of the same network, fed to online
LOCAL_UNIT_DEVIATION = {'Рег_ТВ', 'OOH_Total', 'Digital_Performance'}   # channels with city-level differences
SEGMENTS = ['ТС5/Онлайн', 'ТС5/Оффлайн', 'ТСХ/Онлайн', 'ТСХ/Оффлайн']
TIERS = ['small', 'medium', 'large']
TARGETS = ['orders', 'check']
RESORTS = {'СОЧИ', 'АНАПА', 'ГЕЛЕНДЖИК'}
ADSTOCK_L = 8
KNOT_EVERY_WEEKS = 7
CONTROLS = ['nonworking_share', 'temp_dev_from_norm_c', 'log1p_precip', 'log1p_snow']

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
    trend_basis: np.ndarray         # [W, K]
    t_year: np.ndarray              # [W]
    fourier: np.ndarray             # [W, 4]
    holidays: np.ndarray            # [W, H]
    holiday_names: list
    controls_mean: np.ndarray = field(default_factory=lambda: np.zeros(0))
    controls_sd: np.ndarray = field(default_factory=lambda: np.zeros(0))

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


def prepare(panel_path: str, national_csv: str, fit_window_end: str | None = None) -> ModelData:
    p = pd.read_parquet(panel_path)
    assert p.week_start.max() <= pd.Timestamp('2026-06-22'), 'панель выходит за 28.06.2026'
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
    knots = t[KNOT_EVERY_WEEKS::KNOT_EVERY_WEEKS]
    basis = np.maximum(0.0, t[:, None] - knots[None, :])
    doy = (weeks + pd.Timedelta(days=3)).dayofyear.to_numpy() / 365.25
    fourier = np.column_stack([np.sin(2 * np.pi * doy), np.cos(2 * np.pi * doy),
                               np.sin(4 * np.pi * doy), np.cos(4 * np.pi * doy)])
    hol, hol_names = _holiday_matrix(weeks)
    return ModelData(weeks=weeks, ad_units=ad, model_units=mu, spend_pr=spend_pr, m_ref=m_ref, chan_mask=chan_mask,
                     obs=o, trend_basis=basis, t_year=t_c, fourier=fourier, holidays=hol, holiday_names=hol_names,
                     controls_mean=cm, controls_sd=cs)


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


def model_arrays(d: ModelData) -> dict:
    o = d.obs
    ad = d.ad_units
    return dict(
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
    slope0 = numpyro.sample('slope0', dist.Normal(0, 0.3).expand([2, S]))
    tau_tr = numpyro.sample('tau_trend', dist.HalfNormal(0.5).expand([2]))
    z_tr = numpyro.sample('z_trend', dist.Normal(0, 1).expand([2, S, K]))
    trend = slope0[:, :, None] * arr['t'][None, None, :] + jnp.einsum('wk,jsk->jsw', arr['basis'], tau_tr[:, None, None] * z_tr)
    four = numpyro.sample('fourier', dist.Normal(0, 0.1).expand([2, S, 4]))
    four_res = numpyro.sample('fourier_resort', dist.Normal(0, 0.2).expand([2, 4]))
    hol = numpyro.sample('holidays', dist.Normal(0, 0.2).expand([2, S, H]))
    season = jnp.einsum('wf,jsf->jsw', arr['F'], four) + jnp.einsum('wh,jsh->jsw', arr['H'], hol)
    gam = numpyro.sample('gamma', dist.Normal(0, 0.05).expand([2, S, arr['X'].shape[1]]))
    sig_wk = numpyro.sample('sig_week', dist.HalfNormal(0.03).expand([2, S]))
    z_wk = numpyro.sample('z_week', dist.Normal(0, 1).expand([2, S, W]))
    week_shock = sig_wk[:, :, None] * z_wk
    base_sw = trend + season + week_shock                                                # [2, S, W]
    s_i, w_i, m_i = arr['s_i'], arr['w_i'], arr['m_i']
    mu = (arr['ybar'].T + a_m[:, m_i] + (sig_slope[:, None] * z_slope)[:, m_i] * arr['t'][w_i][None, :]
          + base_sw[:, s_i, w_i] + (four_res @ arr['F'][w_i].T) * arr['resort'][None, :]
          + jnp.einsum('jnx,nx->jn', gam[:, s_i, :], arr['X']) + media)

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
    numpyro.sample('lik_orders', dist.StudentT(nu, 0.0, sc[0]), obs=e[0])
    numpyro.sample('lik_check', dist.StudentT(nu, 0.0, sc[1]), obs=e_c_cond)


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

def simulate(d: ModelData, arr: dict, truth: dict, seed: int = 0) -> tuple[np.ndarray, dict]:
    """Targets from the model with known parameters, real spend, real units and real baseline shape.

    truth: R_orders {channel: ROAS through orders}, R_check {channel: ROAS through check}, alpha {c}, lam {c},
    unit_sd (log sd of unit ROAS deviation for local channels), rho (orders, check), sigma (orders, check),
    sig_week (orders, check), b_check_on_orders.
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
