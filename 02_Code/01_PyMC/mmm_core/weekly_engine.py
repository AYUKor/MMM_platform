"""Forecast engine of a weekly joint model package (weekly_package.PACKAGE_TYPE) behind the platform interfaces.

Same input and output as ForecastEngine.forecast_daily_rows: daily flighting rows in (campaign_name, segment, geo,
channel, date, budget_rub), detail rows per campaign x segment x target x channel x geo with the same columns, and the
summary of forecast_engine.summarize_forecast_detail (posterior draws summed first, quantiles after).

The math is that of 07_weekly_joint_plan_forecast.py (the plan forecast of the model):

* daily budgets are summed into Monday weeks;
* spend per resident / m_ref of the segment goes through the model's normalized geometric adstock (8 weeks, zero
  before the plan: the counterfactual is "no campaign", only the campaign's own spend) and 1 - exp(-x / lam);
* log contribution = (R_orders + R_check) * conv * sat, conv = m_ref / (tau * sat(1)), per draw, as in the fit;
* extra turnover in a unit-week = baseline * (1 - exp(-sum over the campaign's channels)), over the plan weeks and
  the adstock_l - 1 carry-over weeks after the last one; the channels of a unit share it in proportion to their log
  contributions (so the cells add up to the campaign total exactly);
* baseline of a week = the unit's observed turnover in the same week 52 weeks earlier (stepping back whole years
  while the week is after the panel), else the unit's median week. No growth is added.

A row of segment s only reaches the units of segment s: store ads act on store sales and delivery ads on delivery.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .forecast_engine import (SUPPORT_ABS_TOL_RUB, SUPPORT_LEVEL_ELEVATED, SUPPORT_LEVEL_OUTSIDE,
                              SUPPORT_LEVEL_STRONG, SUPPORT_LEVEL_WITHIN, SUPPORT_REL_TOL, CandidateFeasibilityError,
                              _robust_support_upper)
from .weekly_package import (PACKAGE_TYPE, ROAS_LEVEL_LABEL_RU, SERVING_TARGET, WeeklyPackageError,
                             verify_weekly_package_files)

DRAW_CHUNK = 64


def _monday(d: pd.Series) -> pd.Series:
    d = pd.to_datetime(d)
    return (d - pd.to_timedelta(d.dt.weekday, unit='D')).dt.normalize()


def adstock_sat_np(spend_norm: np.ndarray, alpha: np.ndarray, lam: np.ndarray, L: int) -> tuple[np.ndarray, np.ndarray]:
    """spend_norm [U, W, C]; alpha, lam [n, C]. Returns sat [n, U, W, C] and sat(1) [n, C] (zero before week 0)."""
    n, C = alpha.shape
    U, W, _ = spend_norm.shape
    w = alpha[:, None, :] ** np.arange(L)[None, :, None]                 # [n, L, C]
    w = w / w.sum(1, keepdims=True)
    x = np.zeros((n, U, W, C))
    for lag in range(L):
        if lag >= W:
            break
        x[:, :, lag:, :] += w[:, lag, None, None, :] * spend_norm[None, :, :W - lag, :]
    sat = 1.0 - np.exp(-x / lam[:, None, None, :])
    return sat, 1.0 - np.exp(-1.0 / lam)


def adstock_np(spend_norm: np.ndarray, alpha: np.ndarray, L: int) -> np.ndarray:
    """Normalized geometric adstock of one weekly series spend_norm [W] for draws alpha [n]: [n, W] (zero before week
    0), the same weights as adstock_sat_np."""
    w = alpha[:, None] ** np.arange(L)[None, :]
    w = w / w.sum(1, keepdims=True)
    W = len(spend_norm)
    x = np.zeros((len(alpha), W))
    for lag in range(min(L, W)):
        x[:, lag:] += w[:, lag, None] * spend_norm[None, :W - lag]
    return x


@dataclass
class WeeklyCellKernel:
    """Turnover response of one segment x geo x channel cell of a campaign to its total budget (the optimizer's
    search kernel; forecast_engine._CellResponseKernel is the daily one). The cell's weekly profile is kept and scaled:

        response(B) = sum_w base_w * (1 - exp(-beta * (1 - exp(-B * a_w / lam)))),  a_w = adstock(profile / (pop m_ref))

    which is the forecast of the cell alone. The channels of one unit are joint in the model (base * (1 - exp(-sum)));
    the search treats them as independent (the difference is second order, under 1% in the parity check), and the
    finalists are rescored with the exact forecast_daily_rows."""

    cell_pos: int
    segment: str
    geo: str
    channel: str
    base_w: np.ndarray            # [W] baseline turnover of the unit over the campaign horizon
    beta: np.ndarray              # [n] (R_orders + R_check) * conv of the cell's model channel
    a_per_rub: np.ndarray         # [n, W] adstocked normalized spend per rub of cell budget, divided by lam
    _draw_cache: dict[float, np.ndarray] = field(default_factory=dict, repr=False)

    def response_draws(self, budget_rub: float) -> np.ndarray:
        budget = max(float(budget_rub), 0.0)
        key = round(budget, 6)
        hit = self._draw_cache.get(key)
        if hit is not None:
            return hit
        sat = -np.expm1(-budget * self.a_per_rub)
        out = (self.base_w[None, :] * -np.expm1(-self.beta[:, None] * sat)).sum(axis=1)
        self._draw_cache[key] = out
        return out


@dataclass
class _Package:
    run_dir: Path
    manifest: dict[str, Any]
    capability_rows: list[dict[str, str]]
    risk_rows: list[dict[str, str]]

    @property
    def activation_status(self) -> str:
        return str(self.manifest.get('activation_status', 'unknown'))

    @property
    def model_run_id(self) -> str:
        return str(self.manifest.get('model_run_id', ''))


@dataclass
class WeeklyJointEngine:
    run_dir: Path
    package: Any
    metadata: dict[str, Any]
    units: pd.DataFrame
    m_ref: pd.DataFrame
    draws: dict[str, np.ndarray]
    base: pd.DataFrame
    history_spend: pd.DataFrame
    support_bounds: pd.DataFrame
    capability: pd.DataFrame
    package_type: str = PACKAGE_TYPE
    _base_mat: np.ndarray = field(init=False, repr=False)
    _weeks: pd.DatetimeIndex = field(init=False, repr=False)

    def __post_init__(self) -> None:
        m = self.package.manifest
        self.channels = list(m['channels'])
        self.segments = list(m['segments'])
        self.L = int(m['adstock_l_weeks'])
        self.roas_scale = str(m.get('roas_scale', 'equal'))
        self.media_geo = str(m.get('media_geo', 'tier'))
        self.n_draws = int(self.draws['alpha'].shape[0])
        mr = self.m_ref
        self.model_channels = list(dict.fromkeys(mr.channel))         # the model's channel order (wj.CHANNELS)
        S, C = len(self.segments), len(self.model_channels)
        seg_pos = {s: i for i, s in enumerate(self.segments)}
        ch_pos = {c: j for j, c in enumerate(self.model_channels)}
        self.m_ref_sc = np.zeros((S, C))
        self.mask_sc = np.zeros((S, C))
        for r in mr.itertuples(index=False):
            self.m_ref_sc[seg_pos[r.segment], ch_pos[r.channel]] = float(r.m_ref)
            self.mask_sc[seg_pos[r.segment], ch_pos[r.channel]] = float(r.mask)
        self.ch_pos = ch_pos
        self.aliases = dict(m.get('channel_aliases') or {})            # plan channel -> model channel (Indoor -> OOH)
        self.plan_channels = self.channels + [a for a in self.aliases if a not in self.channels]
        u = self.units.sort_values('a').reset_index(drop=True)
        if not (u.a.to_numpy() == np.arange(len(u))).all():
            raise WeeklyPackageError('weekly_units.csv ad unit index is not 0..A-1')
        self.units = u
        self.key = {(s, g): int(a) for s, g, a in zip(u.segment, u.unit_label, u.a)}
        self._weeks = pd.DatetimeIndex(pd.to_datetime(m['panel_weeks']))
        if not set(pd.to_datetime(self.base.week_start)) <= set(self._weeks):
            raise WeeklyPackageError('baseline weeks outside the panel weeks of the manifest')
        widx = {w: i for i, w in enumerate(self._weeks)}
        bm = np.full((len(u), len(self._weeks)), np.nan)
        b = self.base
        cols = [widx[w] for w in pd.to_datetime(b.week_start)]
        bm[b.a.to_numpy(), cols] = b.turnover_rub.to_numpy(float)
        on = np.zeros((len(u), len(self._weeks)))
        on[b.a.to_numpy(), cols] = b.obs_n.to_numpy(float) if 'obs_n' in b else 1.0
        self._base_mat = bm
        self._obs_n = on                       # fit rows per unit-week (the fit counts spend once per row)
        self._base_median = np.nanmedian(np.where(np.isfinite(bm), bm, np.nan), axis=1)
        self._widx = widx
        sb = self.support_bounds
        self._support_idx = {(r.segment, r.geo_label, r.channel): r for r in sb.itertuples(index=False)}
        self._cap = {(r['segment'], r['target'], r['channel']): r for r in self.package.capability_rows}
        if self.media_geo != 'tier' and 'z_unit' not in self.draws:
            raise WeeklyPackageError('media_geo unit needs z_unit draws')

    # ------------------------------------------------------------------ loading
    @classmethod
    def from_run_dir(cls, run_dir: str | Path, *, validate_package_lineage: bool = True, package: Any = None,
                     **_: Any) -> 'WeeklyJointEngine':
        run_dir = Path(run_dir).expanduser().resolve()
        manifest = json.loads((run_dir / 'model_manifest.json').read_text(encoding='utf-8'))
        if manifest.get('package_type') != PACKAGE_TYPE:
            raise WeeklyPackageError(f'{run_dir} is not a {PACKAGE_TYPE} package')
        if validate_package_lineage:
            verify_weekly_package_files(run_dir, manifest)
        if package is None:
            try:
                from .model_package_reader import ModelPackage
                package = ModelPackage.from_run_dir(run_dir, require_posterior_ready=True,
                                                    validate_hash=validate_package_lineage)
            except ImportError:                                       # standalone use (checks on the Mac)
                package = _Package(run_dir, manifest, pd.read_csv(run_dir / 'capability_matrix.csv').to_dict('records'),
                                   pd.read_csv(run_dir / 'risk_registry.csv').to_dict('records'))
        npz = np.load(run_dir / 'weekly_media_draws.npz')
        draws = {k: np.asarray(npz[k], dtype=float) for k in npz.files}
        return cls(run_dir=run_dir, package=package,
                   metadata=json.loads((run_dir / 'fit_design_metadata.json').read_text(encoding='utf-8')),
                   units=pd.read_csv(run_dir / 'weekly_units.csv'),
                   m_ref=pd.read_csv(run_dir / 'weekly_m_ref.csv'),
                   draws=draws,
                   base=pd.read_csv(run_dir / 'weekly_baseline_turnover.csv'),
                   history_spend=pd.read_csv(run_dir / 'weekly_history_spend.csv'),
                   support_bounds=pd.read_csv(run_dir / 'historical_support_bounds.csv'),
                   capability=pd.DataFrame(package.capability_rows))

    def _capability_row(self, segment: str, target: str, channel: str) -> dict[str, Any]:
        return dict(self._cap.get((segment, target, channel)) or {})

    # ------------------------------------------------------------------ model math
    def draw_index(self, n_samples: int) -> np.ndarray:
        """Evenly spaced draws over all chains, as 05 (roas table) and 07 (plan forecast) take them."""
        return np.linspace(0, self.n_draws - 1, min(int(n_samples), self.n_draws)).astype(int)

    def beta_total(self, idx: np.ndarray, a_sel: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(R_orders + R_check) * conv for the draws idx and ad units a_sel: [n, U, C]; and sat(1) inputs lam [n, C]."""
        D = self.draws
        u = self.units.iloc[a_sel]
        seg_a = u.seg_i.to_numpy()
        tier_a = u.tier_i.to_numpy()
        logR_s = D['logR_orders'][idx][:, None, :] + D['sig_seg'][idx][:, None, None] * D['z_seg'][idx]   # [n,S,C]
        logR_a = logR_s[:, seg_a, :] + D['sig_tier'][idx][:, None, None] * D['z_tier'][idx][:, tier_a, :]
        if self.media_geo == 'unit':
            local = np.array([c in ('Рег_ТВ', 'OOH_Total', 'Digital_Performance') for c in self.model_channels], float)
            logR_a = logR_a + D['sig_unit'][idx][:, None, None] * D['z_unit'][idx][:, a_sel, :] * local[None, None, :]
        lam = D['lam'][idx]
        sat1 = 1.0 - np.exp(-1.0 / lam)
        if self.roas_scale == 'gamma':
            geo = u.geo_ratio.to_numpy(float)[None, :] ** D['gamma_geo'][idx][:, None]
        elif self.roas_scale == 'turnover':
            geo = np.broadcast_to(u.geo_ratio.to_numpy(float)[None, :], (len(idx), len(u)))
        else:
            geo = np.ones((len(idx), len(u)))
        m_ref_a = self.m_ref_sc[seg_a]                                                     # [U, C]
        conv = (m_ref_a[None] / (u.tau.to_numpy(float)[None, :, None] * sat1[:, None, :])
                * self.mask_sc[seg_a][None] * geo[:, :, None])
        R_check_a = D['R_check'][idx][:, seg_a, :]
        return (np.exp(logR_a) + R_check_a) * conv, lam

    def contributions(self, spend_rub: np.ndarray, a_sel: np.ndarray, idx: np.ndarray) -> np.ndarray:
        """Log contributions [n, U, W, C] of weekly spend [U, W, C] (rub, model channel order) of the units a_sel."""
        u = self.units.iloc[a_sel]
        pop = u.pop_k.to_numpy(float) * 1000.0
        m_ref_a = self.m_ref_sc[u.seg_i.to_numpy()]
        spr = spend_rub / pop[:, None, None]
        sn = np.where(m_ref_a[:, None, :] > 0, spr / np.where(m_ref_a > 0, m_ref_a, 1.0)[:, None, :], 0.0)
        out = []
        for k in range(0, len(idx), DRAW_CHUNK):
            sub = idx[k:k + DRAW_CHUNK]
            beta, lam = self.beta_total(sub, a_sel)
            sat, _ = adstock_sat_np(sn, self.draws['alpha'][sub], lam, self.L)
            out.append(beta[:, :, None, :] * sat)
        return np.concatenate(out, axis=0)

    def baseline(self, a_sel: np.ndarray, weeks: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Baseline turnover [U, W]: same week 52*k weeks earlier (smallest k >= 1 inside the panel), else median."""
        base = np.zeros((len(a_sel), len(weeks)))
        years = np.zeros((len(a_sel), len(weeks)), int)
        last = self._weeks[-1]
        for j, w in enumerate(weeks):
            k = 1
            while w - pd.Timedelta(weeks=52 * k) > last:
                k += 1
            src = w - pd.Timedelta(weeks=52 * k)
            col = self._widx.get(src)
            for i, a in enumerate(a_sel):
                v = self._base_mat[a, col] if col is not None else np.nan
                if np.isfinite(v):
                    base[i, j], years[i, j] = v, k
                else:
                    base[i, j], years[i, j] = self._base_median[a], -1
        return base, years, (years > 0)

    # ------------------------------------------------------------------ support
    def _support_limits(self, segment: str, geo: str, channel: str) -> dict[str, float] | None:
        """Daily-equivalent spend bounds of a cell (weekly history / 7) and the platform's robust upper boundary
        (forecast_engine._robust_support_upper on active days = 7 x active weeks)."""
        r = self._support_idx.get((segment, geo, self.aliases.get(channel, channel)))
        if r is None:
            return None
        nonneg = lambda v: float(v) if np.isfinite(float(v)) and float(v) > 0 else 0.0
        p95 = nonneg(r.daily_spend_p95_rub)
        p99 = max(nonneg(r.daily_spend_p99_rub), p95)
        mx = max(nonneg(r.daily_spend_max_rub), p99)
        days = int(nonneg(r.active_days))
        return dict(p95=p95, p99=p99, mx=mx, upper=_robust_support_upper(p95, p99, mx, days), active_days=days)

    def _support_check(self, segment: str, geo: str, channel: str, weekly: np.ndarray) -> dict[str, Any]:
        """ForecastEngine._support_assessment on weekly spend: the plan's largest week / 7 against the bounds."""
        lim = self._support_limits(segment, geo, channel)
        future = float(np.max(weekly) / 7.0) if len(weekly) else 0.0
        if lim is None:
            return dict(level=SUPPORT_LEVEL_OUTSIDE if future > 0 else SUPPORT_LEVEL_WITHIN,
                        flags='NO_HISTORICAL_SUPPORT_ROW', p95=0.0, p99=0.0, mx=0.0, upper=0.0, future=future)
        p95, p99, upper = lim['p95'], lim['p99'], lim['upper']
        tol = lambda v: max(SUPPORT_ABS_TOL_RUB, abs(v) * SUPPORT_REL_TOL)
        flags = []
        if lim['active_days'] < 10:
            flags.append('SPARSE_HISTORICAL_ACTIVE_DAYS_LT_10')
        if p95 <= 0 and future > 0:
            flags.append('NO_POSITIVE_HISTORICAL_SPEND_FOR_CELL')
            level = SUPPORT_LEVEL_OUTSIDE
        elif future <= p95 + tol(p95):
            level = SUPPORT_LEVEL_WITHIN
        elif future <= p99 + tol(p99):
            level = SUPPORT_LEVEL_ELEVATED
            flags.append('FUTURE_DAILY_SPEND_P95_TO_P99')
        elif future <= upper + tol(upper):
            level = SUPPORT_LEVEL_STRONG
            flags.append('FUTURE_DAILY_SPEND_P99_TO_ROBUST_UPPER')
        else:
            level = SUPPORT_LEVEL_OUTSIDE
            flags.append('FUTURE_DAILY_SPEND_GT_ROBUST_HIST_UPPER')
        return dict(level=level, flags=';'.join(flags) if flags else 'OK', p95=p95, p99=p99, mx=lim['mx'],
                    upper=upper, future=future)

    # ------------------------------------------------------------------ optimizer interface
    def _source_cell_rows(self, plan: pd.DataFrame, cell: pd.Series) -> pd.DataFrame:
        """Rows of one campaign x segment x geo x channel cell in a flighting (as ForecastEngine._source_cell_rows)."""
        cols = ['campaign_name', 'segment', 'geo', 'channel']
        cache = self.__dict__.setdefault('_src_cache', {})
        if cache.get('plan') is not plan:
            cache.clear()
            cache.update(plan=plan, index=plan.groupby(cols, sort=False, observed=True).indices)
        pos = cache['index'].get(tuple(cell[c] for c in cols))
        return plan.iloc[pos] if pos is not None else plan.iloc[:0]

    def _metadata_rows(self, name: str, columns: tuple[str, ...], values: tuple[str, ...]) -> pd.DataFrame:
        """Rows of a package table by key (as ForecastEngine._metadata_rows); support_bounds is the one the
        optimizer reads."""
        frame = getattr(self, name)
        key = tuple(values)
        m = np.ones(len(frame), bool)
        for c, v in zip(columns, key):
            m &= frame[c].astype(str).to_numpy() == str(v)
        return frame[m]

    def support_cap_rub(self, cell: pd.Series, source_plan: pd.DataFrame, *, limit: str = 'p95') -> float:
        """Largest total budget of a cell whose peak week stays within the support limit (weekly analogue of
        forecast_engine._support_cap_rub_for_cell: the support check compares the plan's largest week / 7)."""
        lim = self._support_limits(str(cell['segment']), str(cell['geo']), str(cell['channel']))
        if lim is None:
            return 0.0
        key = {'p95': 'p95', 'p99': 'p99', 'robust_upper': 'upper'}
        if limit not in key:
            raise ValueError(f'Unknown support limit: {limit}')
        weekly_limit = 7.0 * lim[key[limit]]
        if weekly_limit <= 0:
            return 0.0
        base = self._source_cell_rows(source_plan, cell)
        if base.empty:
            return weekly_limit
        by_week = base.groupby(_monday(pd.Series(pd.to_datetime(base['date']).to_numpy())).to_numpy()).budget_rub.sum()
        total = float(by_week.sum())
        if total <= 0:
            return weekly_limit * max(len(by_week), 1)
        return weekly_limit / max(float(by_week.max()) / total, 1e-12)

    def serving_inventory(self, *, validate: bool = False) -> dict[str, Any]:
        """Serving inventory of the package: one joint model serving the four segments (the daily packages have
        12 research fits and 4 serving ones; serving_semantics.validate_serving_model_inventory checks that)."""
        from .serving_semantics import SERVING_SEGMENTS_N
        segs = [str(s) for s in self.segments]
        inv = dict(research_models_in_package_n=1, active_serving_models_n=len(segs), serving_segments=sorted(segs),
                   duplicate_serving_segments=sorted({s for s in segs if segs.count(s) > 1}),
                   missing_serving_segment_labels_n=sum(not s for s in segs), model_time_step='week',
                   model_package_type=self.package_type)
        if validate and (len(set(segs)) != SERVING_SEGMENTS_N or inv['duplicate_serving_segments']
                         or inv['missing_serving_segment_labels_n']):
            raise WeeklyPackageError(f'Weekly package does not serve the {SERVING_SEGMENTS_N} segments: {inv}')
        return inv

    def optimizer_plan(self, plan: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
        """The flighting the optimizer works on.

        * Directions stay apart: a campaign with rows in several segments is optimized as one campaign per segment
          ("<campaign> | <segment>"), so no money moves between store and delivery directions or between networks.
        * Plan channels the model merged go to the model channel (Indoor -> OOH_Total): the model has one response
          for both, so the optimizer cannot split money between them."""
        out = plan.copy()
        merged = {a: t for a, t in self.aliases.items() if (out['channel'] == a).any()}
        if merged:
            out['channel'] = out['channel'].map(lambda c: self.aliases.get(c, c))
        seg_n = out.groupby('campaign_name')['segment'].nunique()
        split = sorted(str(c) for c in seg_n[seg_n > 1].index)
        if split:
            many = out['campaign_name'].isin(split)
            out.loc[many, 'campaign_name'] = out.loc[many, 'campaign_name'].astype(str) + ' | ' + out.loc[many, 'segment'].astype(str)
        keys = [c for c in out.columns if c not in ('budget_rub',)]
        out = out.groupby(keys, as_index=False, sort=False, dropna=False)['budget_rub'].sum()
        notes = dict(directions_separate=True, campaigns_split_by_segment=split, channel_aliases_merged=merged,
                     budget_rub_in=float(plan['budget_rub'].sum()), budget_rub_out=float(out['budget_rub'].sum()))
        if abs(notes['budget_rub_in'] - notes['budget_rub_out']) > max(1.0, 1e-9 * abs(notes['budget_rub_in'])):
            raise WeeklyPackageError('optimizer flighting does not keep the plan budget')
        return out, notes

    def turnover_response_kernels(self, plan: pd.DataFrame, cells: pd.DataFrame, campaign_name: str, *,
                                  n_samples: int, **_: Any) -> list[WeeklyCellKernel]:
        """Search kernels of the campaign's cells (cells: segment, geo, channel rows of the campaign, in order)."""
        cells = cells.reset_index(drop=True)
        camp = plan[plan['campaign_name'] == campaign_name].copy()
        if camp.empty:
            raise CandidateFeasibilityError(f'No source flighting rows for {campaign_name}')
        camp['week_start'] = _monday(pd.Series(pd.to_datetime(camp['date']).to_numpy())).to_numpy()
        weeks = pd.date_range(camp.week_start.min(), camp.week_start.max() + pd.Timedelta(weeks=self.L - 1), freq='7D')
        widx = {w: i for i, w in enumerate(weeks)}
        idx = self.draw_index(n_samples)
        kernels: list[WeeklyCellKernel] = []
        unit_cache: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        for pos, cell in cells.iterrows():
            segment, geo, ch = str(cell['segment']), str(cell['geo']), str(cell['channel'])
            a = self.key.get((segment, geo))
            mch = self.aliases.get(ch, ch)
            if a is None or mch not in self.ch_pos:
                raise CandidateFeasibilityError(f'Optimizer cell is not in the weekly model: {segment}/{geo}/{ch}')
            j = self.ch_pos[mch]
            src = camp[(camp.segment == segment) & (camp.geo == geo) & (camp.channel == ch)]
            prof = np.zeros(len(weeks))
            for w, v in src.groupby('week_start').budget_rub.sum().items():
                prof[widx[pd.Timestamp(w)]] += float(v)
            total = float(prof.sum())
            if total <= 0:
                raise CandidateFeasibilityError(f'Optimizer needs a positive source profile for {segment}/{geo}/{ch}')
            if a not in unit_cache:
                beta, lam = self.beta_total(idx, np.array([a]))
                base, _, _ = self.baseline(np.array([a]), weeks)
                unit_cache[a] = (beta[:, 0, :], lam, base[0])
            beta, lam, base = unit_cache[a]
            u = self.units.iloc[a]
            m_ref = float(self.m_ref_sc[int(u.seg_i), j])
            if m_ref <= 0 or self.mask_sc[int(u.seg_i), j] == 0:
                raise CandidateFeasibilityError(f'Channel {ch} has no effect in segment {segment} of the weekly model')
            shape = prof / total / (float(u.pop_k) * 1000.0 * m_ref)                 # normalized spend per rub
            x = adstock_np(shape, self.draws['alpha'][idx][:, j], self.L)              # [n, W]
            kernels.append(WeeklyCellKernel(cell_pos=int(pos), segment=segment, geo=geo, channel=ch, base_w=base,
                                            beta=beta[:, j], a_per_rub=x / lam[:, j][:, None]))
        return kernels

    # ------------------------------------------------------------------ platform entry point
    def forecast_daily_rows(self, daily_rows: list[dict[str, Any]], *, n_samples: int = 300, seed: int = 42,
                            include_carryover_days: bool = True, progress_context: str | None = None,
                            analog_year: int | None = None, analog_missing_geo_policy: str = 'fail',
                            independent_scenarios: bool = False, return_campaign_draws: bool = False,
                            targets: Iterable[str] | None = None):
        from .forecast_engine import (_assert_modeled_spend_reconciles, _assert_no_cross_campaign_overlap,
                                      _campaign_total_draw_rows, summarize_forecast_detail)
        plan = pd.DataFrame(daily_rows).copy()
        if plan.empty:
            raise ValueError('No daily rows to forecast')
        need = {'campaign_name', 'segment', 'geo', 'channel', 'date', 'budget_rub'}
        if need - set(plan.columns):
            raise ValueError(f'Daily flighting is missing required columns: {sorted(need - set(plan.columns))}')
        plan['budget_rub'] = pd.to_numeric(plan['budget_rub'], errors='coerce')
        if plan.budget_rub.isna().any() or (~np.isfinite(plan.budget_rub)).any() or (plan.budget_rub < 0).any():
            raise ValueError('Daily flighting contains invalid budget values')
        plan['date'] = pd.to_datetime(plan['date']).dt.date
        if not independent_scenarios:
            _assert_no_cross_campaign_overlap(plan)
        if targets is not None and SERVING_TARGET not in {str(t) for t in targets}:
            empty = pd.DataFrame()
            return (empty, empty, empty) if return_campaign_draws else (empty, empty)
        unknown_ch = sorted(set(plan.channel) - set(self.plan_channels))
        unknown_geo = sorted({(s, g) for s, g in zip(plan.segment, plan.geo) if (s, g) not in self.key})
        if unknown_ch or unknown_geo:
            raise ValueError(f'Weekly model {self.package.model_run_id}: channels not served {unknown_ch}; '
                             f'segment x geo not in the model {unknown_geo[:20]}')
        plan['week_start'] = _monday(pd.Series(pd.to_datetime(plan['date'])))
        idx = self.draw_index(n_samples)
        rows: list[dict[str, Any]] = []
        for campaign_name, camp in plan.groupby('campaign_name', sort=True):
            if progress_context and progress_context not in {'optimizer_search', 'optimizer_finalists'}:
                print(json.dumps(dict(event='forecast_progress', context=progress_context, phase='weekly_scoring',
                                      campaign=str(campaign_name)), ensure_ascii=False), flush=True)
            rows += self._campaign_rows(str(campaign_name), camp, idx, include_carryover_days)
        detail_internal = pd.DataFrame(rows)
        summary = summarize_forecast_detail(detail_internal)
        detail = detail_internal.drop(columns=['_total_effect_draws', '_effect_unit_draws', '_effect_unit_weight'],
                                      errors='ignore')
        _assert_modeled_spend_reconciles(plan, detail)
        if return_campaign_draws:
            return detail, summary, _campaign_total_draw_rows(detail_internal)
        return detail, summary

    def _campaign_rows(self, campaign_name: str, camp: pd.DataFrame, idx: np.ndarray,
                       carryover: bool) -> list[dict[str, Any]]:
        start, end = min(camp.date), max(camp.date)
        w0, w1 = camp.week_start.min(), camp.week_start.max()
        n_tail = self.L - 1 if carryover else 0
        weeks = pd.date_range(w0, w1 + pd.Timedelta(weeks=n_tail), freq='7D')
        widx = {w: i for i, w in enumerate(weeks)}
        cells = camp.groupby(['segment', 'geo'], sort=True)
        a_sel = np.array([self.key[k] for k, _ in cells])
        C = len(self.model_channels)
        spend = np.zeros((len(a_sel), len(weeks), C))
        active_days: dict[tuple[int, str], int] = Counter()
        plan_spend: dict[tuple[int, str], float] = Counter()            # by plan channel (Indoor apart from OOH)
        for i, (_, g) in enumerate(cells):
            agg = g.groupby(['week_start', 'channel']).budget_rub.sum()
            for (w, ch), v in agg.items():
                spend[i, widx[w], self.ch_pos[self.aliases.get(ch, ch)]] += float(v)
                plan_spend[(i, ch)] += float(v)
            for ch, n in g[g.budget_rub > 0].groupby('channel').date.nunique().items():
                active_days[(i, ch)] = int(n)
        contrib = self.contributions(spend, a_sel, idx)                              # [n, U, W, C]
        base, years, used = self.baseline(a_sel, weeks)
        tot = contrib.sum(-1)                                                        # [n, U, W]
        joint = base[None] * (1.0 - np.exp(-tot))                                    # [n, U, W]
        share = np.divide(contrib, tot[..., None], out=np.zeros_like(contrib), where=np.abs(tot[..., None]) > 1e-15)
        eff = (joint[..., None] * share).sum(2)                                      # [n, U, C]
        units = self.units.iloc[a_sel]
        out = []
        for i, ((segment, geo), _) in enumerate(cells):
            u = units.iloc[i]
            pop = float(u.pop_k) * 1000.0
            for ch in sorted(set(camp.channel[(camp.segment == segment) & (camp.geo == geo)])):
                j = self.ch_pos[self.aliases.get(ch, ch)]
                spend_total = float(plan_spend[(i, ch)])
                if spend_total <= 0:
                    continue
                # a model channel's effect goes to its plan channels by their money (OOH and Indoor share OOH_Total)
                totals = eff[:, i, j] * spend_total / float(spend[i, :, j].sum())
                cap = self._capability_row(segment, SERVING_TARGET, ch)
                sup = self._support_check(segment, geo, ch, spend[i, spend[i, :, j] > 0, j])
                act = spend[i, :, j] > 0
                m_ref = self.m_ref_sc[int(u.seg_i), j]
                inten = float((spend[i, act, j] / pop).mean() / m_ref) if m_ref > 0 else float('nan')
                q = lambda x, p: float(np.percentile(x, p))
                out.append({
                    'campaign_name': campaign_name, 'segment': segment, 'target': SERVING_TARGET, 'channel': ch,
                    'geo': geo, 'market_size_tier': str(u.tier), 'start_date': start.isoformat(),
                    'end_date': end.isoformat(), 'horizon_end_date': (weeks[-1] + pd.Timedelta(days=6)).date().isoformat(),
                    'spend_rub': spend_total, 'active_days': int(active_days.get((i, ch), 0)),
                    'effect_unit': 'rub_per_resident',
                    'effect_p10': q(totals, 10) / pop, 'effect_p50': q(totals, 50) / pop, 'effect_p90': q(totals, 90) / pop,
                    'total_effect_unit': 'incremental_turnover_rub',
                    'total_effect_p10': q(totals, 10), 'total_effect_p50': q(totals, 50), 'total_effect_p90': q(totals, 90),
                    'roas_p10': q(totals, 10) / spend_total, 'roas_p50': q(totals, 50) / spend_total,
                    'roas_p90': q(totals, 90) / spend_total,
                    'allowed_use': cap.get('allowed_use', 'unsupported'), 'optimizer_use': cap.get('optimizer_use', 'not_ready'),
                    'risk_level': cap.get('risk_level', 'unavailable'), 'model_flags': cap.get('channel_reliability_flags', ''),
                    'support_level': sup['level'], 'support_flags': sup['flags'],
                    'future_daily_spend_max_rub': sup['future'], 'historical_daily_spend_p95_rub': sup['p95'],
                    'historical_daily_spend_p99_rub': sup['p99'], 'historical_daily_spend_observed_max_rub': sup['mx'],
                    'historical_daily_spend_robust_upper_rub': sup['upper'],
                    'forecast_semantics': 'incremental_media_effect_vs_no_campaign_counterfactual',
                    'y_scaling': 'log_orders_plus_log_check', 'y_offset': 0.0, 'posterior_samples': int(len(idx)),
                    'warm_start_used': False, 'warm_start_matched_in_counterfactual': True,
                    'denominator_analog_year': 'same_week_52_weeks_earlier',
                    'denominator_fallback_gap_days_max': 0,
                    'denominator_fallback_years_max': int(years[i].max()),
                    'model_name': str(self.package.manifest.get('model_name', '')),
                    'model_time_step': 'week', 'roas_level_label': ROAS_LEVEL_LABEL_RU,
                    'baseline_turnover_horizon_rub': float(base[i].sum()),
                    'analog_weeks_share': float(used[i].mean()),
                    'weekly_spend_vs_typical': inten,
                    '_total_effect_draws': totals, '_effect_unit_draws': totals / pop, '_effect_unit_weight': pop,
                })
        return out

    # ------------------------------------------------------------------ parity with the fit
    def replay_roas_table(self, n_samples: int = 200) -> pd.DataFrame:
        """ROAS by segment x channel over the fit window, recomputed from the package alone: the whole history of
        one channel in a segment as the 'plan', baseline = the observed turnover of the same unit-week, spend and
        effect counted on observed unit-weeks. Equals roas_by_segment_channel of the fit (the same 200 draws)."""
        idx = self.draw_index(n_samples)
        weeks = self._weeks
        widx = self._widx
        hs = self.history_spend
        rows = []
        for s, seg in enumerate(self.segments):
            a_sel = self.units.a[self.units.seg_i == s].to_numpy()
            pos = {a: i for i, a in enumerate(a_sel)}
            sub = hs[hs.a.isin(a_sel)]
            spend = np.zeros((len(a_sel), len(weeks), len(self.model_channels)))
            spend[[pos[a] for a in sub.a], [widx[w] for w in pd.to_datetime(sub.week_start)],
                  [self.ch_pos[c] for c in sub.channel]] = sub.spend_rub.to_numpy(float)
            base = self._base_mat[a_sel]
            obs = np.isfinite(base)
            obs_n = self._obs_n[a_sel]
            for c in self.channels:
                j = self.ch_pos[c]
                if self.mask_sc[s, j] == 0:
                    continue
                sp_c = np.zeros_like(spend)
                sp_c[:, :, j] = spend[:, :, j]
                sp = float((spend[:, :, j] * obs_n).sum())
                if sp <= 0:
                    continue
                eff = np.zeros(len(idx))
                for k in range(0, len(idx), DRAW_CHUNK):
                    part = idx[k:k + DRAW_CHUNK]
                    cc = self.contributions(sp_c, a_sel, part)[..., j]                  # [n, U, W]
                    eff[k:k + len(part)] = np.where(obs[None], np.nan_to_num(base)[None] * (1 - np.exp(-cc)), 0).sum((1, 2))
                r = eff / sp
                rows.append(dict(segment=seg, channel=c, spend_rub=sp, roas_q05=float(np.quantile(r, .05)),
                                 roas_median=float(np.quantile(r, .5)), roas_q95=float(np.quantile(r, .95))))
        return pd.DataFrame(rows)
