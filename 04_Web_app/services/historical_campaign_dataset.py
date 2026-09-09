"""Read-only persistent historical results. No model or calculation imports."""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path

DIRECTIONS = ['ТС5/Онлайн', 'ТСХ/Онлайн', 'ТС5/Оффлайн', 'ТСХ/Оффлайн']
IDENTIFIER = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$')
ERRORS = {
    'QUERY_INVALID': (422, 'Некорректные параметры запроса.'),
    'NOT_FOUND': (404, 'Кампания не найдена.'),
    'VERSION_UNAVAILABLE': (404, 'Версия исторических результатов недоступна.'),
    'DATASET_CORRUPT': (409, 'Целостность исторических результатов не подтверждена.'),
    'RESULT_UNAVAILABLE': (409, 'Для этой кампании расчёт недоступен.'),
}
REASONS = {
    'INVALID_DECLARED_WINDOW': 'Некорректный объявленный период',
    'MULTIPLE_DECLARED_WINDOWS': 'Нужно уточнить объединение периодов',
    'NONPOSITIVE_BUDGET': 'Неположительный бюджет',
    'ALLOCATION_INCOMPLETE': 'Не весь бюджет распределён по историческим географиям',
    'PANEL_BUDGET_INCOMPLETE': 'Не весь бюджет покрыт панелью',
    'MODEL_BUDGET_INCOMPLETE': 'Не весь бюджет покрыт моделью',
    'CHANNEL_NOT_IN_TURNOVER_FIT': 'Медиаканал отсутствует в модели РТО',
    'FROZEN_CALENDAR_INCOMPLETE': 'В историческом календаре есть пропуски',
    'AFTER_TRAINING': 'Кампания после обучающего периода',
    'CROSSES_TRAINING_END': 'Кампания пересекает конец обучающего периода',
    'BEFORE_TRAINING': 'Кампания начинается до обучающего периода',
    'PREHISTORY_UNAVAILABLE': 'Недостаточно предыстории',
    'TAIL_UNAVAILABLE': 'Нет полного периода после завершения',
    'CALCULATION_FAILED': 'Расчёт кампании завершился ошибкой',
}


class HistoricalDatasetError(ValueError):
    def __init__(self, code: str):
        self.code = 'HISTORICAL_' + code
        self.status, self.display_text = ERRORS[code]
        super().__init__(self.display_text)


def valid_id(value: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise HistoricalDatasetError('QUERY_INVALID')
    return value


class HistoricalDatasetStore:
    """Versions are explicit immutable directories, independently of active models."""
    def __init__(self, root: Path | None, default_id: str | None, active_package: str | None = None):
        self.root, self.default_id, self.active_package = root, default_id, active_package

    def _manifest(self, dataset_id: str | None) -> tuple[Path, dict]:
        name = dataset_id or self.default_id
        if self.root is None or name is None:
            raise HistoricalDatasetError('VERSION_UNAVAILABLE')
        valid_id(name)
        root = self.root.resolve()
        directory = root / name
        if not directory.exists():
            raise HistoricalDatasetError('VERSION_UNAVAILABLE')
        try:
            if directory.is_symlink() or not directory.resolve().is_relative_to(root):
                raise ValueError('Unsafe directory')
            manifest_path = directory / 'manifest.json'
            if manifest_path.is_symlink():
                raise ValueError('Unsafe manifest')
            manifest = json.loads(manifest_path.read_text())
            if manifest['schema_version'] != '1.0.0':
                raise HistoricalDatasetError('VERSION_UNAVAILABLE')
            if manifest['dataset_id'] != name or manifest['acceptance'] != 'passed':
                raise ValueError('Unaccepted version')
            return directory, manifest
        except HistoricalDatasetError:
            raise
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise HistoricalDatasetError('DATASET_CORRUPT') from exc

    def _read(self, directory: Path, manifest: dict, relative: str, binary: bool = False):
        try:
            path = directory / relative
            if not relative.startswith('serving/') or not path.resolve().is_relative_to(directory.resolve()) or path.is_symlink():
                raise ValueError('Unsafe artifact')
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != manifest['files'][relative]['sha256']:
                raise ValueError('Checksum mismatch')
            return data if binary else json.loads(data)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise HistoricalDatasetError('DATASET_CORRUPT') from exc

    def read(self, params: dict[str, list[str]], campaign_key: str | None = None, resource: str = 'registry'):
        allowed = {'dataset_id'} | ({'q', 'sort', 'order', 'offset', 'limit'} if resource == 'registry' else set())
        if set(params) - allowed or any(len(v) != 1 for v in params.values()):
            raise HistoricalDatasetError('QUERY_INVALID')
        query = {k: v[0] for k, v in params.items()}
        directory, manifest = self._manifest(query.get('dataset_id'))
        base = {'schema_version': '1.0.0', 'dataset_id': manifest['dataset_id'],
                'model_package_id': manifest['model_package_id'], 'method_version': manifest['method_version'],
                'matches_active_model': (manifest['model_package_id'] == self.active_package) if self.active_package else None}
        registry = self._read(directory, manifest, 'serving/registry.json')
        try:
            from contracts.historical_campaigns_v1 import validate_historical_campaigns
            if not isinstance(registry, list) or len({r['campaign_key'] for r in registry}) != len(registry):
                raise ValueError('Invalid registry keys')
            validate_historical_campaigns({**base, 'resource': 'registry', 'blocks': [
                {'segment': segment, 'direction_name': segment, 'total': sum(r['segment'] == segment for r in registry),
                 'offset': 0, 'limit': max(1, len(registry)), 'items': [r for r in registry if r['segment'] == segment]}
                for segment in DIRECTIONS]})
            if any(r['segment'] not in DIRECTIONS for r in registry):
                raise ValueError('Unknown direction')
        except (ValueError, KeyError, TypeError) as exc:
            raise HistoricalDatasetError('DATASET_CORRUPT') from exc
        if resource == 'registry':
            sort, order = query.get('sort', 'start_date'), query.get('order', 'desc')
            try:
                offset, limit = int(query.get('offset', '0')), int(query.get('limit', '20'))
                if offset < 0 or not 1 <= limit <= 100 or sort not in {'start_date', 'end_date', 'source_budget_rub', 'campaign_name'} or order not in {'asc', 'desc'}:
                    raise ValueError('Invalid page')
            except ValueError as exc:
                raise HistoricalDatasetError('QUERY_INVALID') from exc
            search = query.get('q', '').strip().casefold()
            if len(search) > 300:
                raise HistoricalDatasetError('QUERY_INVALID')
            blocks = []
            for segment in DIRECTIONS:
                rows = [r for r in registry if r['segment'] == segment and search in r['campaign_name'].casefold()]
                rows.sort(key=lambda r: r['campaign_key'])
                values = [r for r in rows if r[sort] is not None]
                nulls = [r for r in rows if r[sort] is None]
                values.sort(key=lambda r: r[sort].casefold() if sort == 'campaign_name' else r[sort], reverse=order == 'desc')
                ordered = values + nulls
                blocks.append({'segment': segment, 'total': len(rows), 'offset': offset, 'limit': limit,
                               'direction_name': dict(zip(DIRECTIONS, ['Доставка ТС5', 'Доставка ТСХ', 'Магазины ТС5', 'Магазины ТСХ']))[segment],
                               'items': ordered[offset:offset + limit]})
            return {**base, 'resource': 'registry', 'blocks': blocks}
        valid_id(campaign_key)
        rows = [r for r in registry if r['campaign_key'] == campaign_key]
        if not rows:
            raise HistoricalDatasetError('NOT_FOUND')
        if resource == 'card':
            return {**base, 'resource': 'card', 'campaign': rows[0]}
        if resource not in {'daily', 'media', 'report.xlsx'}:
            raise HistoricalDatasetError('QUERY_INVALID')
        if rows[0]['result_status'] != 'calculated':
            raise HistoricalDatasetError('RESULT_UNAVAILABLE')
        name = 'report.xlsx' if resource == 'report.xlsx' else resource + '.json'
        data = self._read(directory, manifest, f'serving/{campaign_key}/{name}', resource == 'report.xlsx')
        if resource == 'report.xlsx':
            return data
        try:
            payload = {**base, 'resource': resource, 'campaign_key': campaign_key, **data}
            validate_historical_campaigns(payload)
            return payload
        except (ValueError, KeyError, TypeError) as exc:
            raise HistoricalDatasetError('DATASET_CORRUPT') from exc


def verify_materialized(root: Path, dataset_id: str) -> dict:
    """Verify actual serving content after copying to an explicit relative layout."""
    from contracts.historical_campaigns_v1 import validate_historical_campaigns
    store = HistoricalDatasetStore(root, dataset_id)
    directory, manifest = store._manifest(dataset_id)
    for relative in manifest['files']:
        store._read(directory, manifest, relative, binary=True)
    registry = store._read(directory, manifest, 'serving/registry.json')
    for card in registry:
        validate_historical_campaigns(store.read({}, card['campaign_key'], 'card'))
        if card['result_status'] == 'calculated':
            for resource_name in ['daily', 'media']:
                validate_historical_campaigns(store.read({}, card['campaign_key'], resource_name))
            store.read({}, card['campaign_key'], 'report.xlsx')
    return {'dataset_id': dataset_id, 'status': 'passed', 'campaigns': len(registry),
            'files': len(manifest['files']), 'model_package_id': manifest['model_package_id']}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Verify materialized historical serving artifacts; never calculate.')
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--dataset-id', required=True)
    args = parser.parse_args()
    print(json.dumps(verify_materialized(args.root, args.dataset_id), ensure_ascii=False))
