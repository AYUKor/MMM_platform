"""Validate compact historical campaign response contracts, without calculation imports."""
import json
import math
from functools import lru_cache
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker, ValidationError


@lru_cache(maxsize=1)
def _validator():
    schema = json.loads(Path(__file__).with_suffix('.schema.json').read_text())
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_historical_campaigns(payload: dict) -> None:
    try:
        _validator().validate(payload)
    except ValidationError as exc:
        raise ValueError('Historical response contract failed') from exc
    def check(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError('Nonfinite historical result')
        if isinstance(value, list):
            for item in value:
                check(item)
        if isinstance(value, dict):
            if value.get('result_status') == 'calculated':
                if any(value[k] is None for k in ['source_budget_rub', 'start_date', 'end_date']):
                    raise ValueError('Calculated campaign requires full budget and period')
                if value['identity_status'] != 'confirmed' or value['coverage_status'] != 'full' or value['result'] is None:
                    raise ValueError('Incomplete campaign published as calculated')
            if value.get('result_status') in {'unavailable', 'pending', 'error'} and value['result'] is not None:
                raise ValueError('Unavailable result must be null')
            for item in value.values():
                check(item)
    check(payload)
