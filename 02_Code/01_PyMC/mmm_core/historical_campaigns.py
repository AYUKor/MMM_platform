"""Historical campaign paired response, ported from the accepted A1 method.

Offline calculation only; serving reads separate compact immutable artifacts.
No current-model pointer, research directory or campaign ID is embedded here.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import hashlib
import json
import numpy as np
import pandas as pd

METHOD_VERSION = "historical-paired-media-v1"
ELIGIBILITY_VERSION = "historical-eligibility-v2"
KEYS = ["date", "geo_label", "network", "channel"]

def assert_close(actual: Any, expected: Any, label: str,
                 atol: float = 0.01, rtol: float = 0.0) -> float:
    a, b = np.asarray(actual, float), np.asarray(expected, float)
    if not np.all(np.isfinite(a)) or not np.all(np.isfinite(b)):
        raise ValueError(f"{label}: nonfinite values")
    maximum = float(np.max(np.abs(a - b), initial=0))
    if not np.allclose(a, b, atol=atol, rtol=rtol):
        raise ValueError(f"{label}: max difference {maximum}")
    return maximum

def prepare_panel(panel_path: Path, config: dict) -> pd.DataFrame:
    """Apply frozen grouped channel definitions in memory; raw remains immutable."""
    panel = pd.read_parquet(panel_path)
    panel["date"] = pd.to_datetime(panel["date"])
    if panel.duplicated(KEYS).any():
        raise ValueError("Panel keys are not unique")
    for segment, grouping in config["media_grouping_config"].items():
        network, business_channel = segment.split("/")
        mask = panel.network.eq(network) & panel.channel.eq(business_channel)
        for group, inputs in grouping.items():
            # Both same-valued grouped columns and components may exist. Use each once.
            recalculated = panel.loc[mask, inputs].sum(axis=1)
            assert_close(panel.loc[mask, group], recalculated, f"frozen grouping {segment}/{group}")
            panel.loc[mask, group] = recalculated
    return panel

def fit_frame(panel: pd.DataFrame, row_index: pd.DataFrame, fit_key: str) -> pd.DataFrame:
    """Use recorded training keys/order without new eligibility or date fill rules."""
    index = row_index[row_index.fit_key.eq(fit_key)]
    frame = index.merge(panel, on=KEYS, how="left", validate="one_to_one", indicator=True)
    if not frame._merge.eq("both").all():
        raise ValueError(f"Frozen rows absent from panel: {fit_key}")
    return frame.drop(columns="_merge").sort_values("row_position").reset_index(drop=True)

def load_draws(path: Path, transform: dict, output: Path) -> dict:
    """Use all stored posterior draws, no sampling or observation noise."""
    import xarray as xr
    with xr.open_dataset(path, group="posterior") as ds:
        ds = ds[["alpha", "lam", "beta"]].load()
    channels = list(transform["channels"])
    chains, draws = np.asarray(ds.chain), np.asarray(ds.draw)
    pairs = np.asarray([(int(c), int(d)) for c in chains for d in draws])
    alpha = ds.alpha.sel(channel=channels).transpose("chain", "draw", "channel").values.reshape(-1, len(channels))
    lam = ds.lam.sel(channel=channels).transpose("chain", "draw", "channel").values.reshape(-1, len(channels))
    beta_da = ds.beta.sel(channel=channels)
    if "geo_label" in beta_da.dims:
        kind, labels = "geo_label", list(map(str, ds.geo_label.values))
    elif "market_size_tier" in beta_da.dims:
        kind, labels = "market_size_tier", list(map(str, ds.market_size_tier.values))
    else:
        kind, labels = "pooled", []
    dims = ["chain", "draw", "channel"] + ([] if kind == "pooled" else [kind])
    beta = beta_da.transpose(*dims).values.reshape(len(pairs), len(channels), -1)
    if output.exists():
        with np.load(output) as saved:
            for name, value in [('pairs', pairs), ('alpha', alpha), ('lam', lam), ('beta', beta),
                                ('beta_kind', kind), ('beta_labels', labels), ('channels', channels)]:
                if not np.array_equal(saved[name], np.asarray(value)):
                    raise ValueError('Saved parameter identity mismatch')
    else:
        np.savez_compressed(output, pairs=pairs, alpha=alpha, lam=lam, beta=beta,
                            beta_kind=kind, beta_labels=np.asarray(labels), channels=np.asarray(channels))
    return dict(pairs=pairs, alpha=alpha, lam=lam, beta=beta,
                beta_kind=kind, beta_labels=labels, channels=channels)

def beta_values(draws: dict, transform: dict, geo: str, m: int) -> np.ndarray:
    kind = draws["beta_kind"]
    if kind == "pooled":
        i = 0
    elif kind == "geo_label":
        i = draws["beta_labels"].index(geo)
    else:
        g = transform["geos"].index(geo)
        tier = transform["market_size_tiers"][transform["geo_tier_idx"][g]]
        i = draws["beta_labels"].index(tier)
    return draws["beta"][:, m, i]

def response(x: np.ndarray, alpha: np.ndarray, lam: np.ndarray,
             beta: np.ndarray, users: np.ndarray, y_scale: float, l_max: int) -> np.ndarray:
    """Reuse the proven normalized lag transform, with frozen scaling upstream."""
    from .forecast_engine import _normalized_adstock_draw_matrix
    adstock = _normalized_adstock_draw_matrix(x, alpha, l_max)
    return beta[:, None] * np.tanh(lam[:, None] * adstock / 2.0) * y_scale * users[None, :]

def independent_response(x: np.ndarray, alpha: np.ndarray, lam: np.ndarray,
                         beta: np.ndarray, users: np.ndarray, y_scale: float, l_max: int) -> np.ndarray:
    """Independent scalar draw convolution; no production lag helper is called."""
    effects = []
    for a, l, b in zip(alpha, lam, beta):
        weights = np.asarray([a ** lag for lag in range(l_max + 1)])
        weights /= weights.sum()
        ads = np.convolve(x, weights, mode="full")[:len(x)]
        effects.append(b * np.tanh(l * ads / 2) * y_scale * users)
    return np.asarray(effects)

def assess_campaign(row: pd.Series, spend: pd.DataFrame, frame: pd.DataFrame,
                    transform: dict) -> dict:
    """Full-flight budget and calendar eligibility; never redistribute missing money."""
    start, end = pd.Timestamp(row.start_date), pd.Timestamp(row.end_date)
    lag = int(transform["l_max"])
    pre, tail = start - pd.Timedelta(days=lag), end + pd.Timedelta(days=lag)
    selected = spend[spend.campaign_key.eq(row.campaign_key)].copy()
    selected = selected[selected.spend_rub.ne(0)]
    supported = set(transform["channels"])
    unsupported_budget = float(selected.loc[~selected.media_channel.isin(supported), "spend_rub"].sum())
    matched = selected.merge(frame[KEYS], on=KEYS, how="left", indicator=True, validate="many_to_one")
    missing_budget = float(matched.loc[matched._merge.ne("both"), "spend_rub"].sum())
    covered = float(matched.loc[matched._merge.eq("both") & matched.media_channel.isin(supported), "spend_rub"].sum())
    geos = sorted(selected.geo_label.unique().tolist())
    calendar_gaps = []
    prehistory_gaps = []
    geo_effect_windows = []
    for geo in geos:
        geo_spend = selected[selected.geo_label.eq(geo)]
        first, last = geo_spend.date.min(), geo_spend.date.max()
        local_tail = last + pd.Timedelta(days=lag)
        dates = pd.DatetimeIndex(frame.loc[frame.geo_label.eq(geo), "date"])
        expected = pd.date_range(first, local_tail)
        missing = expected.difference(dates)
        pre_missing = pd.date_range(first - pd.Timedelta(days=lag), first - pd.Timedelta(days=1)).difference(dates)
        if len(pre_missing):
            prehistory_gaps.append({'geo_label': geo, 'missing_dates': pre_missing.strftime('%Y-%m-%d').tolist()})
        geo_effect_windows.append({'geo_label': geo, 'start': str(first.date()), 'end': str(local_tail.date())})
        if len(missing):
            calendar_gaps.append({"geo_label": geo, "missing_dates": missing.strftime("%Y-%m-%d").tolist()})
    source = float(row.source_budget_rub)
    allocated = float(selected.spend_rub.sum())
    panel_budget = float(row.panel_budget_rub)
    reasons = []
    if source <= 0: reasons.append("NONPOSITIVE_BUDGET")
    if abs(source - allocated) > 0.01: reasons.append("ALLOCATION_INCOMPLETE")
    if abs(source - panel_budget) > 0.01: reasons.append("PANEL_BUDGET_INCOMPLETE")
    if abs(source - covered) > 0.01: reasons.append("MODEL_BUDGET_INCOMPLETE")
    if unsupported_budget != 0: reasons.append("PARTIAL_CHANNEL_COVERAGE")
    if calendar_gaps: reasons.append("FROZEN_CALENDAR_INCOMPLETE")
    if any(geo not in transform['geos'] for geo in geos): reasons.append('PARTIAL_GEO_COVERAGE')
    return {"campaign_key": row.campaign_key, "segment": row.segment, "campaign_name": row.campaign_name,
            "eligible": not reasons, "reasons": reasons, "source_budget_rub": source,
            "has_federal_rows": bool(row.has_federal_rows),
            "allocated_budget_rub": allocated, "panel_budget_rub": panel_budget,
            "covered_budget_rub": covered, "unmatched_model_budget_rub": missing_budget,
            "unsupported_channel_budget_rub": unsupported_budget, "geographies_n": len(geos),
            "geographies": geos, "calendar_gaps": calendar_gaps, "prehistory_gaps": prehistory_gaps,
            "geo_effect_windows": geo_effect_windows,
            "prehistory_start": str(pre.date()), "evaluation_start": str(start.date()),
            "placement_end": str(end.date()), "evaluation_end": str(tail.date()), "l_max": lag}

def placement_mask(row: pd.Series, dates: pd.DatetimeIndex) -> np.ndarray:
    """Use actual source placement bounds, retaining declared windows separately."""
    windows = row.get('actual_placement_windows')
    if windows is None:
        declared = json.loads(row.source_declared_windows) if 'source_declared_windows' in row else []
        windows = declared if len(declared) > 1 else [f'{pd.Timestamp(row.start_date).date()} / {pd.Timestamp(row.end_date).date()}']
    mask = np.zeros(len(dates), dtype=bool)
    for window in windows:
        first, last = map(pd.Timestamp, window.split(' / '))
        mask |= (dates >= max(first, pd.Timestamp(row.start_date))) & (dates <= min(last, pd.Timestamp(row.end_date)))
    return mask


def evaluate_campaign(row: pd.Series, selected: pd.DataFrame, frame: pd.DataFrame,
                      transform: dict, draws: dict, chunk_size: int = 512) -> tuple:
    """Compute paired draw differences; all other media/controls/users stay fixed."""
    start, end = pd.Timestamp(row.start_date), pd.Timestamp(row.end_date)
    lag = int(transform["l_max"])
    pre, tail = start - pd.Timedelta(days=lag), end + pd.Timedelta(days=lag)
    dates = pd.date_range(start, tail)
    n = len(draws["pairs"])
    daily = np.zeros((n, len(dates)))
    geo_channel = []
    checks = dict(zero_change_max_abs=0.0, before_start_max_abs=0.0,
                  after_tail_max_abs=0.0, minimum_remainder_rub=0.0,
                  subtraction_recovery_max_abs=0.0, repeat_max_abs=0.0,
                  parallel_remaining_spend_rub=0.0, same_cell_parallel_rows=0,
                  after_tail_observed_geo_channel_days=0)
    # Additional actual day after tail is a zero-response check when present.
    target_end = tail + pd.Timedelta(days=1)
    for geo, media in selected.groupby("geo_label", sort=True):
        history = frame[frame.geo_label.eq(geo)].sort_values("row_position")
        # Retain complete frozen sequence for historical row semantics and warm history.
        # The selected window was checked calendar-contiguous before calculation.
        history = history[history.date.le(target_end)].copy()
        ix = (history.date.ge(start) & history.date.le(tail)).to_numpy()
        output_positions = dates.get_indexer(history.loc[ix, "date"])
        users = history.unique_users.to_numpy(float)
        pop = history.population_k.to_numpy(float)
        if (pop < 1e-3).any() or (users <= 0).any():
            raise ValueError("Historical population/users invalid")
        g = transform["geos"].index(geo)
        for media_channel, campaign_media in media.groupby("media_channel", sort=True):
            m = transform["channels"].index(media_channel)
            column = transform["spend_active"][m]
            total = history[column].to_numpy(float)
            campaign_by_date = campaign_media.groupby("date").spend_rub.sum()
            change = history.date.map(campaign_by_date).fillna(0).to_numpy(float)
            assert_close(change.sum(), campaign_media.spend_rub.sum(), "campaign whole removal")
            if np.any(change < 0) or np.any(total < 0):
                raise ValueError("Negative source or panel spend")
            alternative = total - change
            minimum = float(alternative.min(initial=0))
            checks["minimum_remainder_rub"] = min(checks["minimum_remainder_rub"], minimum)
            # Absolute 1e-7 RUB is only float subtraction tolerance, not budget loss.
            if minimum < -1e-7:
                raise ValueError(f"Campaign exceeds cell: {geo}/{media_channel}/{minimum}")
            alternative[alternative < 0] = 0.0
            recovered = assert_close(total - alternative, change, "only campaign removed", atol=1e-7)
            checks["subtraction_recovery_max_abs"] = max(checks["subtraction_recovery_max_abs"], recovered)
            overlap = (change > 0) & (alternative > 1e-7)
            checks["parallel_remaining_spend_rub"] += float(alternative[overlap].sum())
            checks["same_cell_parallel_rows"] += int(overlap.sum())
            scale = float(transform["x_scale_geo"][g][m])
            if not np.isfinite(scale) or scale <= 0:
                raise ValueError("Invalid frozen scale")
            x = total / np.maximum(pop, 1e-3) / max(scale, 1e-8)
            x_alt = alternative / np.maximum(pop, 1e-3) / max(scale, 1e-8)
            beta = beta_values(draws, transform, geo, m)
            cell_draws = np.zeros(n)
            for lo in range(0, n, chunk_size):
                sl = slice(lo, min(lo + chunk_size, n))
                args = (draws["alpha"][sl, m], draws["lam"][sl, m], beta[sl], users,
                        float(transform["y_scale"]), lag)
                factual = response(x, *args)
                counterfactual = response(x_alt, *args)
                diff = factual - counterfactual
                # Repeat both branches on the exact draws, not quantiles or rounded output.
                repeated = response(x, *args) - response(x_alt, *args)
                checks["repeat_max_abs"] = max(checks["repeat_max_abs"], assert_close(diff, repeated, "repeat", 0))
                checks["zero_change_max_abs"] = max(checks["zero_change_max_abs"], assert_close(factual - response(x, *args), 0, "zero", 0))
                before = history.date.lt(start).to_numpy()
                checks["before_start_max_abs"] = max(checks["before_start_max_abs"], assert_close(diff[:, before], 0, "before start", 1e-8))
                after = history.date.gt(tail).to_numpy()
                if lo == 0: checks["after_tail_observed_geo_channel_days"] += int(after.sum())
                checks["after_tail_max_abs"] = max(checks["after_tail_max_abs"], assert_close(diff[:, after], 0, "after tail", 1e-8))
                daily[sl, output_positions] += diff[:, ix]
                cell_draws[sl] = diff[:, ix].sum(axis=1)
            geo_channel.append((geo, media_channel, cell_draws))
    during_mask = placement_mask(row, dates)
    during, after = daily[:, during_mask].sum(axis=1), daily[:, ~during_mask].sum(axis=1)
    total = daily.sum(axis=1)
    checks["during_plus_after_max_abs"] = assert_close(during + after, total, "during+after=total", 1e-5)
    checks["geo_channel_sum_max_abs"] = assert_close(np.sum([x[2] for x in geo_channel], axis=0), total, "geo/channel sum", 1e-5)
    checks["same_users_and_controls"] = True
    checks["after_tail_observed_check_status"] = "PASS" if checks["after_tail_observed_geo_channel_days"] else "UNAVAILABLE"
    # Boundary control is mathematical, not a fabricated campaign or missing-date fill.
    impulse = np.zeros(lag + 2); impulse[0] = 1.0
    impulse_effect = independent_response(impulse, np.asarray([0.6]), np.asarray([1.0]),
                                          np.asarray([1.0]), np.ones(lag + 2), 1.0, lag)[0]
    if impulse_effect[lag] <= 0 or impulse_effect[lag + 1] != 0:
        raise ValueError("Inclusive lag boundary failed")
    checks["independent_impulse_lag_L_nonzero_Lplus1_zero"] = True
    checks["nonmedia_semantics"] = "Only media vectors copied/subtracted; shared baseline, controls and users are unchanged and cancel analytically."
    return daily, dates, geo_channel, during, after, checks


def sha256(path: Path) -> str:
    """Stream a physical artifact digest without changing the artifact."""
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def safe_id(value: str) -> str:
    return value.replace('/', '_').replace('::', '__')


@dataclass
class HistoricalContext:
    """One immutable, verified input set for the whole offline batch."""
    spec: dict
    paths: dict[str, Path]
    registry: pd.DataFrame
    spend: pd.DataFrame
    frames: dict
    transforms: dict
    draws: dict
    config: dict
    identity_evidence: dict | None = None

    def verify(self) -> None:
        for role, item in self.spec['files'].items():
            path = self.paths[role]
            if not path.is_file() or sha256(path) != item['sha256']:
                raise ValueError(f'Mandatory input missing or changed: {role}')

    @classmethod
    def load(cls, spec: dict, roots: dict[str, Path], private: Path) -> 'HistoricalContext':
        files = spec['files']
        required = {'panel', 'registry', 'spend', 'model_manifest', 'run_config',
                    'fit_design_metadata', 'fit_design_row_index', 'denominators', 'source_manifest'}
        if not required <= files.keys():
            raise ValueError('Missing mandatory input roles')
        paths = {}
        for role, item in files.items():
            root = roots[item['root']].resolve()
            relative = Path(item['path'])
            path = (root / relative).resolve()
            if relative.is_absolute() or not path.is_relative_to(root):
                raise ValueError('Input must be relative to its explicit root')
            paths[role] = path
        ctx = cls(spec, paths, pd.DataFrame(), pd.DataFrame(), {}, {}, {}, {})
        ctx.verify()
        read = lambda role: json.loads(paths[role].read_text())
        manifest, metadata, ctx.config = read('model_manifest'), read('fit_design_metadata'), read('run_config')
        if manifest['package_input_fingerprint'] != spec['package_fingerprint']:
            raise ValueError('Package fingerprint mismatch')
        if ctx.config.get('center_media_response') is not False:
            raise ValueError('Unsupported response centering')
        fits = {k: v for k, v in metadata['fits'].items() if k.endswith('::turnover_per_user')}
        if len(fits) != 4:
            raise ValueError('Four turnover fits required')
        for fit in fits:
            if not {f'transform:{fit}', f'posterior:{fit}'} <= files.keys():
                raise ValueError('Missing mandatory fit artifacts')
        for role, item in files.items():
            if item['root'] == 'package':
                expected = manifest.get('evidence_sha256', {}).get(item['path'])
                if role.startswith('posterior:'):
                    expected = manifest['posterior_sha256'][role.removeprefix('posterior:')]
                if expected and expected != item['sha256']:
                    raise ValueError('Package evidence identity mismatch')
        source = read('source_manifest')
        # Source-code hashes describe historical provenance; every physical data
        # dependency in the accepted allocation cache remains mandatory.
        for role, item in source['input_artifacts'].items():
            if role == 'data_pipeline':
                continue
            physical = files.get('source:' + role)
            if not physical or physical['sha256'] != item['sha256']:
                raise ValueError('Missing or mismatched allocation source dependency')
        for role, name in [('registry', 'A1_CAMPAIGN_REGISTRY.parquet'), ('spend', 'A1_ALLOCATED_CAMPAIGN_SPEND.parquet')]:
            item = source['output_artifacts'][name]
            expected = item['sha256'] if isinstance(item, dict) else item
            if expected != files[role]['sha256']:
                raise ValueError('Cached allocation lineage mismatch')
        panel = prepare_panel(paths['panel'], ctx.config)
        index = pd.read_parquet(paths['fit_design_row_index'])
        index['date'] = pd.to_datetime(index.date)
        denominators = pd.read_csv(paths['denominators'])
        denominators['date'] = pd.to_datetime(denominators.date)
        private.mkdir(parents=True, exist_ok=True)
        for fit, meta in fits.items():
            trans = read(f'transform:{fit}')
            frame = fit_frame(panel, index, fit)
            if trans['channels'] != meta['channels'] or int(trans['l_max']) != int(meta['l_max']):
                raise ValueError('Frozen transform metadata mismatch')
            if frame.row_position.tolist() != list(range(len(frame))):
                raise ValueError('Frozen row order invalid')
            wanted = denominators[denominators.segment.eq(fit.split('::')[0])]
            joined = frame.merge(wanted[['date', 'geo_label', 'population_k', 'unique_users', 'orders_cnt']],
                                 on=['date', 'geo_label'], how='left', validate='one_to_one', suffixes=('', '_saved'))
            for col in ['population_k', 'unique_users', 'orders_cnt']:
                assert_close(joined[col], joined[col + '_saved'], 'daily denominators', 1e-9)
            draws = load_draws(paths[f'posterior:{fit}'], trans, private / f'parameters_{safe_id(fit)}.npz')
            if len(draws['pairs']) != spec['posterior_draws'] or len(np.unique(draws['pairs'], axis=0)) != len(draws['pairs']):
                raise ValueError('Full posterior pair set required')
            for name in ['alpha', 'lam', 'beta']:
                if not np.isfinite(draws[name]).all():
                    raise ValueError('Nonfinite posterior')
            ctx.frames[fit], ctx.transforms[fit], ctx.draws[fit] = frame, trans, draws
        ctx.registry = pd.read_parquet(paths['registry'])
        ctx.spend = pd.read_parquet(paths['spend'])
        ctx.spend['date'] = pd.to_datetime(ctx.spend.date)
        for col in ['start_date', 'end_date']:
            ctx.registry[col] = pd.to_datetime(ctx.registry[col])
        if ctx.registry.campaign_key.duplicated().any() or not set(ctx.spend.campaign_key) <= set(ctx.registry.campaign_key):
            raise ValueError('Invalid source identity keys')
        if ctx.spend.duplicated(['campaign_key', *KEYS, 'media_channel', 'panel_covered']).any():
            raise ValueError('Duplicate allocated spend cells')
        if not np.isfinite(ctx.spend.spend_rub).all() or ctx.spend.spend_rub.lt(0).any():
            raise ValueError('Corrupt allocated spend')
        if 'identity_rows' in paths:
            identity_rows = pd.read_parquet(paths['identity_rows'])
            ctx.identity_evidence = prove_campaign_identity(identity_rows, ctx.registry)
        return ctx


def prove_campaign_identity(source: pd.DataFrame, registry: pd.DataFrame) -> dict:
    """Confirm waves only through a shared, fully populated, exclusive source token.

    UTM placement qualifiers after `|` do not identify a different campaign.
    No fuzzy name matching, gap threshold, or partial-row evidence is accepted.
    """
    data = source.copy()
    data['token'] = data.utm_campaign.fillna('').astype(str).str.split('|', regex=False).str[0].str.strip()
    ownership = data[data.token.ne('')].groupby(['segment', 'token']).campaign_key.nunique()
    proof = {}
    for key, rows in data.groupby('campaign_key'):
        record = registry[registry.campaign_key.eq(key)]
        if len(record) != 1:
            raise ValueError('Identity evidence contains unknown campaign')
        row = record.iloc[0]
        if len(rows) != int(row.source_row_count) or abs(float(rows.budget.sum()) - row.source_budget_rub) > .01:
            raise ValueError('Identity evidence does not cover whole source group')
        if rows.source_file_sha256.nunique() != 1 or rows.source_file_sha256.iloc[0] != row.source_file_sha256:
            raise ValueError('Identity evidence source version differs')
        if rows.segment.nunique() != 1 or rows.segment.iloc[0] != row.segment:
            raise ValueError('Identity evidence crosses direction')
        if rows.campaign_id_for_audit.nunique() != 1 or str(rows.campaign_id_for_audit.iloc[0]) != str(row.campaign_id):
            raise ValueError('Identity evidence crosses source identifier')
        if rows.token.eq('').any() or rows.token.nunique() != 1:
            continue
        token = rows.token.iloc[0]
        if ownership.loc[(row.segment, token)] != 1:
            continue
        if (rows.date.lt(rows.declared_start_date) | rows.date.gt(rows.declared_end_date)).any():
            continue
        windows = sorted({f'{a.date()} / {b.date()}' for a, b in rows[['declared_start_date', 'declared_end_date']].itertuples(index=False, name=None)})
        if windows != sorted(json.loads(row.source_declared_windows)):
            raise ValueError('Identity evidence periods differ')
        actual_windows = sorted({f'{g.date.min().date()} / {g.date.max().date()}'
                                 for _, g in rows.groupby(['declared_start_date', 'declared_end_date'])})
        proof[key] = {'actual_placement_windows': actual_windows, 'kind': 'exclusive_full_source_utm_campaign', 'token': token,
                      'source_sha256': row.source_file_sha256, 'rows': len(rows), 'declared_windows': windows}
    return proof


def campaign_state(row: pd.Series, assessment: dict, config: dict, identity_evidence: dict | None = None) -> dict:
    """Keep business identity independent of model coverage and result readiness."""
    windows = json.loads(row.source_declared_windows)
    confirmed = len(windows) == 1 and int(row.source_declared_window_count) == 1
    identity_reason = 'MULTIPLE_DECLARED_WINDOWS'
    if confirmed:
        try:
            declared_start, declared_end = windows[0].split(' / ')
            if pd.isna(pd.Timestamp(declared_start)) or pd.isna(pd.Timestamp(declared_end)) or pd.Timestamp(declared_start) > pd.Timestamp(declared_end):
                raise ValueError('Invalid declared interval')
        except (ValueError, TypeError, AttributeError):
            confirmed = False
            identity_reason = 'INVALID_DECLARED_WINDOW'
    if not confirmed and identity_evidence and row.campaign_key in identity_evidence:
        confirmed = True
    reasons = list(assessment['reasons'])
    start, end = pd.Timestamp(row.start_date), pd.Timestamp(row.end_date)
    train_start, train_end = pd.Timestamp(config['train_start']), pd.Timestamp(config['train_end'])
    if start > train_end:
        reasons.append('OUT_OF_TRAINING_WINDOW')
    elif end > train_end:
        reasons.append('OUT_OF_TRAINING_WINDOW')
    if start < train_start:
        reasons.append('BEFORE_TRAINING')
    if pd.Timestamp(assessment['evaluation_end']) > train_end:
        reasons.append('TAIL_UNAVAILABLE')
    return {'identity_status': 'confirmed' if confirmed else 'needs_review',
            'coverage_status': 'full' if not reasons else 'unavailable',
            'result_status': 'pending' if confirmed and not reasons else 'unavailable',
            'identity_reasons': [] if confirmed else [identity_reason],
            'coverage_reasons': sorted(set(reasons))}
