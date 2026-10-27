"""Календарная история расходов отдельно от доступности outcomes."""
from __future__ import annotations

from pathlib import Path
from typing import Any
import hashlib

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

KEYS = ['date', 'geo_label', 'network', 'channel']
LAG_MODE = 'calendar_days_v1'


def bound_media_history(config: dict, panel: pd.DataFrame, start: str, end: str) -> pd.DataFrame | None:
    """В replay/OOT использовать именно источник, связанный с run identity."""
    if config.get('lag_mode') != LAG_MODE:
        return None
    binding = config.get('media_history') or {}
    if not binding.get('path'):
        if 'dataset_split' in panel and panel.date.max() >= pd.Timestamp('2026-06-01'):
            raise ValueError('Q2 calendar validation requires bound complete media history')
        return panel[panel.date.between(start, end)].copy()
    path = Path(binding['path'])
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    if digest.hexdigest() != binding.get('sha256'):
        raise ValueError('Bound media history hash mismatch')
    return load_media_history(path, start, end, config.get('media_grouping_config') or {})


def calendar_lags(
    values: np.ndarray, geo_idx: np.ndarray, dates: Any, l_max: int,
    *, history_values: np.ndarray | None = None,
    history_geo_idx: np.ndarray | None = None, history_dates: Any = None,
) -> np.ndarray:
    """Выбрать x[g, date-lag]; отсутствие outcome не сжимает календарь."""
    values = np.asarray(values, dtype=float)
    dates = pd.DatetimeIndex(pd.to_datetime(dates))
    geo_idx = np.asarray(geo_idx)
    if len(values) != len(dates) or len(values) != len(geo_idx) or l_max < 0:
        raise ValueError('Calendar lag dimensions or horizon are invalid')
    hv = values if history_values is None else np.asarray(history_values, dtype=float)
    hg = geo_idx if history_geo_idx is None else np.asarray(history_geo_idx)
    hd = dates if history_dates is None else pd.DatetimeIndex(pd.to_datetime(history_dates))
    if len(hv) != len(hg) or len(hv) != len(hd) or hv.shape[1:] != values.shape[1:]:
        raise ValueError('Media history dimensions disagree')
    if dates.tz != hd.tz or dates.isna().any() or hd.isna().any() or not dates.equals(dates.normalize()) or not hd.equals(hd.normalize()):
        raise ValueError('Media history requires non-null daily dates')
    index = pd.MultiIndex.from_arrays([hg, hd])
    if index.has_duplicates or not np.isfinite(hv).all():
        raise ValueError('Duplicate or nonfinite media history')
    result = np.zeros((l_max + 1, len(values), values.shape[1]), dtype=float)
    for lag in range(l_max + 1):
        requested = pd.MultiIndex.from_arrays([geo_idx, dates - pd.Timedelta(days=lag)])
        positions = index.get_indexer(requested)
        known = positions >= 0
        result[lag, known] = hv[positions[known]]
    return result


def load_media_history(path: Path, start: str, end: str, grouping: dict) -> pd.DataFrame:
    """Читать уже распределённый ledger без повторного mapping/дедупликации."""
    pieces = []
    for batch in pq.ParquetFile(path).iter_batches(batch_size=60000, columns=KEYS + ['channel_type', 'budget']):
        frame = batch.to_pandas()
        frame['date'] = pd.to_datetime(frame.date)
        frame = frame[frame.date.between(start, end)]
        pieces.append(frame.groupby(KEYS + ['channel_type'], as_index=False).budget.sum())
    ledger = pd.concat(pieces, ignore_index=True)
    if not np.isfinite(ledger.budget).all() or ledger.budget.lt(0).any():
        raise ValueError('Media ledger contains invalid budgets')
    ledger['spend_column'] = ledger.channel_type.map(
        lambda c: 'spend_' + str(c).replace(' ', '_').replace('/', '_').replace('ё', 'е').replace('Ё', 'Е'))
    wide = ledger.pivot_table(index=KEYS, columns='spend_column', values='budget', aggfunc='sum', fill_value=0.0).reset_index()
    wide.columns.name = None
    for segment, groups in grouping.items():
        network, channel = segment.split('/', 1)
        mask = wide.network.eq(network) & wide.channel.eq(channel)
        for group, inputs in groups.items():
            if group not in wide:
                wide[group] = 0.0
            available = [c for c in inputs if c in wide]
            wide.loc[mask, group] = wide.loc[mask, available].sum(axis=1) if available else 0.0
    return wide


def scaled_history_lags(rows: pd.DataFrame, history: pd.DataFrame, spend: list[str],
                        geos: list[str], scales: np.ndarray, l_max: int) -> np.ndarray:
    """Применить frozen per-geo scaling к полной media history, затем выбрать даты outcomes."""
    network, channel = rows[['network', 'channel']].iloc[0]
    source = history[history.network.eq(network) & history.channel.eq(channel) & history.geo_label.isin(geos)].copy()
    if source.duplicated(KEYS).any():
        raise ValueError('Duplicate media history keys')
    population = rows.groupby('geo_label').population_k.median()
    geo_map = {geo: i for i, geo in enumerate(geos)}
    gi = rows.geo_label.map(geo_map).to_numpy(int)
    hi = source.geo_label.map(geo_map).to_numpy(int)
    missing = set(spend) - set(source.columns)
    if missing:
        raise ValueError(f'Media history is missing channels: {sorted(missing)}')
    x = rows[spend].to_numpy(float) / np.maximum(rows.population_k.to_numpy(float)[:, None], 1e-3) / np.maximum(scales[gi], 1e-8)
    hx = source[spend].to_numpy(float) / np.maximum(source.geo_label.map(population).to_numpy(float)[:, None], 1e-3) / np.maximum(scales[hi], 1e-8)
    return calendar_lags(x, gi, rows.date, l_max, history_values=hx, history_geo_idx=hi, history_dates=source.date)
