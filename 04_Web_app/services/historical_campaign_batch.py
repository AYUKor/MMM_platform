"""Offline batch CLI. Physical roots are explicit; GET handlers never import this module."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import time
import uuid
import importlib.metadata

WEB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB))
sys.path.insert(0, str(WEB.parent / '02_Code' / '01_PyMC'))
import numpy as np
import pandas as pd
from mmm_core.historical_campaigns import (HistoricalContext, METHOD_VERSION, assess_campaign,
                                          campaign_state, evaluate_campaign, sha256)
from services.historical_campaign_dataset import DIRECTIONS, REASONS, valid_id
from services.historical_campaign_report import export_report, METHOD_TEXT


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    os.replace(temp, path)


def quantiles(values) -> dict:
    return dict(zip(['p10', 'p50', 'p90'], map(float, np.quantile(values, [.1, .5, .9]))))


def code_identity() -> str:
    paths = [Path(__file__), WEB / 'services/historical_campaign_report.py', WEB / 'services/historical_campaign_dataset.py',
             WEB / 'contracts/historical_campaigns_v1.schema.json', WEB / 'contracts/historical_campaigns_v1.py',
             WEB.parent / '02_Code/01_PyMC/mmm_core/historical_campaigns.py',
             WEB.parent / '02_Code/01_PyMC/mmm_core/forecast_engine.py']
    return hashlib.sha256(''.join(sha256(p) for p in paths).encode()).hexdigest()


def verify_seal(root: Path, seal: dict) -> None:
    for relative, item in seal.items():
        path = root / relative
        if not path.resolve().is_relative_to(root.resolve()) or not path.is_file() or sha256(path) != item['sha256']:
            raise ValueError('Completed artifact missing or changed')


def seal_files(root: Path, paths: list[Path]) -> dict:
    return {p.relative_to(root).as_posix(): {'sha256': sha256(p), 'size_bytes': p.stat().st_size} for p in paths}


def run(args) -> dict:
    started = time.perf_counter()
    spec_path = Path(args.input_manifest)
    spec = json.loads(spec_path.read_text())
    root = Path(args.output_root) / valid_id(args.dataset_id)
    identity = {'input_manifest_sha256': sha256(spec_path), 'code_sha256': code_identity()}
    progress_path = root / 'progress.json'
    if root.exists() and not args.resume:
        raise ValueError('Dataset exists; choose a new ID or resume')
    if (root / 'manifest.json').exists():
        raise ValueError('Published datasets are immutable')
    root.mkdir(parents=True, exist_ok=True)
    if progress_path.exists():
        progress = json.loads(progress_path.read_text())
        if progress['identity'] != identity:
            raise ValueError('Resume identity mismatch')
        for result in progress['completed'].values():
            verify_seal(root, result['files'])
    else:
        progress = {'identity': identity, 'completed': {}, 'attempts': []}
    context = HistoricalContext.load(spec, {'package': Path(args.package_root), 'data': Path(args.data_root),
                                          'source': Path(args.source_root)}, root / 'private/parameters')
    write_json(root / 'private/input_manifest.json', spec)
    load_seconds = time.perf_counter() - started
    rows, assessments = {}, {}
    grouped = {key: value for key, value in context.spend.groupby('campaign_key')}
    for _, row in context.registry.iterrows():
        key, fit = row.campaign_key, row.segment + '::turnover_per_user'
        selected = grouped.get(key, context.spend.iloc[:0])
        a = assess_campaign(row, selected, context.frames[fit], context.transforms[fit])
        state = campaign_state(row, a, context.config)
        card = {'campaign_key': key, 'source_group_id': str(row.campaign_id),
                'business_campaign_id': key if state['identity_status'] == 'confirmed' else None,
                'campaign_name': str(row.campaign_name), 'segment': row.segment,
                'start_date': row.start_date.strftime('%Y-%m-%d'), 'end_date': row.end_date.strftime('%Y-%m-%d'),
                'declared_windows': json.loads(row.source_declared_windows),
                'source_budget_rub': float(row.source_budget_rub), 'allocated_budget_rub': a['allocated_budget_rub'],
                'panel_budget_rub': a['panel_budget_rub'], 'evaluated_budget_rub': a['covered_budget_rub'],
                'has_federal_rows': bool(row.has_federal_rows), 'geographies_count': a['geographies_n'],
                'evaluation_end': a['evaluation_end'], 'tail_days': a['l_max'],
                'historical_geographies': a['geographies'], 'result': None,
                'model_package_id': spec['model_package_id'], 'method_version': METHOD_VERSION, **state}
        card['status_text'] = ('Готово к расчёту' if state['result_status'] == 'pending' else
                               'Нужно уточнить объединение периодов' if state['identity_status'] == 'needs_review' else 'Расчёт недоступен')
        card['reason_texts'] = [REASONS[r] for r in state['identity_reasons'] + state['coverage_reasons']]
        card['limitations'] = METHOD_TEXT
        rows[key], assessments[key] = card, a
    write_json(root / 'private/assessments.json', assessments)
    golden_keys = list(spec.get('goldens', {}))
    eligible = sorted([k for k, v in rows.items() if v['result_status'] == 'pending'],
                      key=lambda k: (golden_keys.index(k) if k in golden_keys else len(golden_keys), k))
    attempted = 0
    for key in eligible:
        if key in progress['completed']:
            rows[key] = progress['completed'][key]['card']
            continue
        if args.max_campaigns and attempted >= args.max_campaigns:
            break
        attempted += 1
        tick = time.perf_counter()
        row = context.registry[context.registry.campaign_key.eq(key)].iloc[0]
        fit = row.segment + '::turnover_per_user'
        private = root / 'private' / key
        serving = root / 'serving' / key
        private.mkdir(parents=True, exist_ok=True)
        serving.mkdir(parents=True, exist_ok=True)
        try:
            daily, dates, geo_channel, during, after, checks = evaluate_campaign(
                row, grouped[key], context.frames[fit], context.transforms[fit], context.draws[fit])
            card = rows[key]
            total = daily.sum(axis=1)
            card['result'] = {'rto': quantiles(total), 'roas': quantiles(total / card['source_budget_rub']),
                              'during': quantiles(during), 'after': quantiles(after), 'draws': len(total)}
            card['result_status'], card['status_text'] = 'calculated', 'Рассчитано'
            golden_diff = {}
            if key in spec.get('goldens', {}):
                for metric, values in spec['goldens'][key].items():
                    tolerance = spec['golden_tolerances'][metric]
                    actual = card['source_budget_rub'] if metric == 'budget' else card['result'][metric]
                    differences = [abs(actual - values)] if metric == 'budget' else [abs(actual[q] - values[q]) for q in values]
                    golden_diff[metric] = max(differences)
                    if max(differences) > tolerance:
                        raise ValueError('Golden numerical acceptance failed')
            np.savez_compressed(private / 'draws.npz', daily=daily, dates=dates.strftime('%Y-%m-%d').to_numpy(dtype=str),
                                pairs=context.draws[fit]['pairs'], during=during, after=after,
                                geo=np.asarray([v[0] for v in geo_channel]), media=np.asarray([v[1] for v in geo_channel]),
                                geo_channel=np.asarray([v[2] for v in geo_channel]))
            daily_rows = [{'date': d.strftime('%Y-%m-%d'), 'period': 'Размещение' if d <= row.end_date else 'После завершения',
                           'rto': quantiles(daily[:, i])} for i, d in enumerate(dates)]
            plan = grouped[key].groupby(['date', 'geo_label', 'media_channel'], as_index=False).spend_rub.sum()
            plan['date'] = plan.date.dt.strftime('%Y-%m-%d')
            media_rows = plan.rename(columns={'geo_label': 'geography'})[['date', 'geography', 'media_channel', 'spend_rub']].to_dict('records')
            geo_summary = [{'geography': g, 'media_channel': m, 'rto': quantiles(v)} for g, m, v in geo_channel]
            geo_totals, channel_totals = [], []
            for label, target, position, field in [('geo', geo_totals, 0, 'geography'), ('channel', channel_totals, 1, 'media_channel')]:
                for value in sorted({cell[position] for cell in geo_channel}):
                    # Aggregate aligned draws first, never sum cell quantiles.
                    effects = np.sum([cell[2] for cell in geo_channel if cell[position] == value], axis=0)
                    column = 'geo_label' if position == 0 else 'media_channel'
                    budget = float(plan.loc[plan[column].eq(value), 'spend_rub'].sum())
                    target.append({field: value, 'spend_rub': budget, 'rto': quantiles(effects)})
            write_json(serving / 'daily.json', {'items': daily_rows})
            write_json(serving / 'media.json', {'plan': media_rows, 'geo_channel_totals': geo_summary, 'geography_totals': geo_totals, 'channel_totals': channel_totals})
            export_report(serving / 'report.xlsx', card, daily_rows, media_rows)
            write_json(private / 'checks.json', {'checks': checks, 'golden_max_abs_differences': golden_diff})
            status = {'card': card, 'seconds': time.perf_counter() - tick,
                      'files': seal_files(root, list(private.iterdir()) + list(serving.iterdir()))}
            progress['completed'][key] = status
            print(json.dumps({'campaign_key': key, 'status': 'calculated', 'seconds': status['seconds'],
                              'golden_max_abs_differences': golden_diff}), flush=True)
        except Exception as exc:
            # Global inputs are checked again before any dataset can be published.
            rows[key]['result'], rows[key]['result_status'], rows[key]['status_text'] = None, 'error', 'Ошибка расчёта'
            rows[key]['reason_texts'] = [REASONS['CALCULATION_FAILED']]
            write_json(private / ('error_' + uuid.uuid4().hex + '.json'), {'exception_type': type(exc).__name__, 'message': str(exc)})
            print(json.dumps({'campaign_key': key, 'status': 'error', 'exception_type': type(exc).__name__}), flush=True)
        write_json(progress_path, progress)
    context.verify()
    if identity != {'input_manifest_sha256': sha256(spec_path), 'code_sha256': code_identity()}:
        raise ValueError('Code or input manifest changed during calculation')
    pending = [k for k in eligible if rows[k]['result_status'] == 'pending']
    counts = {s: {name: sum(predicate(r) for r in rows.values() if r['segment'] == s) for name, predicate in {
        'total': lambda r: True, 'confirmed': lambda r: r['identity_status'] == 'confirmed',
        'needs_review': lambda r: r['identity_status'] == 'needs_review',
        'fully_available': lambda r: r['identity_status'] == 'confirmed' and r['coverage_status'] == 'full',
        'calculated': lambda r: r['result_status'] == 'calculated',
        'unavailable': lambda r: r['identity_status'] == 'confirmed' and r['coverage_status'] != 'full',
        'errors': lambda r: r['result_status'] == 'error'}.items()} for s in DIRECTIONS}
    attempt = {'load_seconds': load_seconds, 'seconds': time.perf_counter() - started, 'counts': counts,
               'pending': len(pending),
               'dataset_bytes': sum(p.stat().st_size for p in root.rglob('*') if p.is_file()),
               'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024)}
    progress['attempts'].append(attempt)
    write_json(progress_path, progress)
    if not pending:
        if any(k not in progress['completed'] for k in golden_keys):
            raise ValueError('Cannot publish dataset without all golden acceptances')
        write_json(root / 'serving/registry.json', list(rows.values()))
        manifest = {'schema_version': '1.0.0', 'dataset_id': args.dataset_id, 'acceptance': 'passed',
                    'model_package_id': spec['model_package_id'], 'package_fingerprint': spec['package_fingerprint'],
                    'panel_sha256': spec['files']['panel']['sha256'], 'method_version': METHOD_VERSION,
                    'run_id': args.dataset_id, 'input_files': spec['files'],
                    'runtime_versions': {name: importlib.metadata.version(name) for name in ['numpy', 'pandas', 'xarray', 'openpyxl']},
                    'private_files': seal_files(root, [p for p in (root / 'private').rglob('*') if p.is_file()]),
                    **identity, 'counts': counts, 'files': seal_files(root, [p for p in (root / 'serving').rglob('*') if p.is_file()])}
        # Validate every public projection before exposing a publication marker.
        from contracts.historical_campaigns_v1 import validate_historical_campaigns
        for key, card in rows.items():
            base = {'schema_version': '1.0.0', 'dataset_id': args.dataset_id,
                    'model_package_id': spec['model_package_id'], 'method_version': METHOD_VERSION,
                    'matches_active_model': None}
            validate_historical_campaigns({**base, 'resource': 'card', 'campaign': card})
            if card['result_status'] == 'calculated':
                for name in ['daily', 'media']:
                    value = json.loads((root / 'serving' / key / (name + '.json')).read_text())
                    validate_historical_campaigns({**base, 'resource': name, 'campaign_key': key, **value})
        write_json(root / 'manifest.json', manifest)
    print(json.dumps(attempt, ensure_ascii=False), flush=True)
    return attempt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['input-manifest', 'package-root', 'data-root', 'source-root', 'output-root', 'dataset-id']:
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--max-campaigns', type=int, default=0, help='Checkpoint after N new campaigns, never reduce posterior draws')
    run(parser.parse_args())


if __name__ == '__main__':
    main()
