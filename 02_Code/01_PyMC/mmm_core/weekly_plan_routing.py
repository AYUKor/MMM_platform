"""Media-plan rows -> units of a weekly joint model package (Заноза), by the rules the panel was built with.

The weekly model's units are cities, the rest of an oblast without its cities («... (КРОМЕ ГОРОДОВ)»), a few whole
regions and one district (weekly_geo_routing.csv of the package). A media plan names cities, oblasts and РФ. The
panel v3 routed the agency ledger to the units with these rules (campaign_routing.py), and a plan is routed the same
way so that its money lands where the model learned from:

* a unit of the segment stays as it is;
* physical outdoor (OOH_Total, Indoor) on an oblast -> the rest of that oblast;
* TV, radio, digital on an oblast -> by population over the oblast's units of the segment (its cities and the rest);
* a city that is not a unit of the segment -> the rest of its oblast;
* РФ is left to the federal allocation (federal_geo_allocator.py) that runs after this step.

A row that no rule can place (an oblast without a rest unit for physical outdoor, an oblast or city the panel never
mapped) keeps its label, so the package validation reports it as a geography the model does not support.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Any

from .federal_geo_allocator import is_federal_geo

ROUTING_FILE = 'weekly_geo_routing.csv'
CITY_MAP_FILE = 'weekly_city_oblast_map.csv'
RULES_VERSION = 'panel_v3_plan_routing_v1'


class WeeklyPlanRoutingError(RuntimeError):
    pass


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open('r', encoding='utf-8-sig', newline='') as handle:
        return [dict(row) for row in csv.DictReader(handle)]


class WeeklyPlanRouter:
    """Routing tables of one weekly package."""

    def __init__(self, routing_rows: list[dict[str, str]], city_rows: list[dict[str, str]], *,
                 physical_channels: set[str], channel_aliases: dict[str, str]) -> None:
        self.physical = set(physical_channels)
        self.aliases = dict(channel_aliases)
        self.units: dict[str, set[str]] = defaultdict(set)
        self.rest: dict[tuple[str, str], str] = {}
        self.oblast_units: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
        for row in routing_rows:
            segment, unit, kind = row['segment'], row['unit_label'], row['unit_kind']
            oblast = (row.get('oblast_label') or '').strip()
            population = float(row.get('population_k') or 0.0)
            self.units[segment].add(unit)
            if kind == 'rest_of_oblast':
                if (segment, oblast) in self.rest:
                    raise WeeklyPlanRoutingError(f'two rest units for {oblast} in {segment}')
                self.rest[(segment, oblast)] = unit
            if oblast and kind in {'city', 'rest_of_oblast'} and population > 0:
                self.oblast_units[(segment, oblast)].append((unit, population))
        self.city_oblast = {row['city'].strip(): row['oblast'].strip() for row in city_rows if row.get('city')}

    @classmethod
    def from_package(cls, package: Any) -> 'WeeklyPlanRouter':
        run_dir = Path(package.run_dir)
        manifest = package.manifest
        routing_path, city_path = run_dir / ROUTING_FILE, run_dir / CITY_MAP_FILE
        if not routing_path.exists() or not city_path.exists():
            raise WeeklyPlanRoutingError(
                f'weekly package {run_dir} has no {ROUTING_FILE} / {CITY_MAP_FILE}: rebuild it with schema 0.5.0 or later')
        rules = manifest.get('plan_routing') or {}
        if rules.get('rules_version') != RULES_VERSION or rules.get('agglo'):
            raise WeeklyPlanRoutingError(f'unsupported plan routing rules {rules}')
        return cls(_read_csv(routing_path), _read_csv(city_path), physical_channels=set(rules.get('physical_channels') or []),
                   channel_aliases=dict(manifest.get('channel_aliases') or {}))

    def targets(self, segment: str, geo: str, channel: str) -> tuple[str, list[tuple[str, float]]]:
        """(rule, [(unit, share)]) for one plan cell; an empty list keeps the row as it is."""
        if is_federal_geo(geo):
            return 'federal_allocation_later', []
        if geo in self.units.get(segment, set()):
            return 'model_unit', []
        model_channel = self.aliases.get(channel, channel)
        if (segment, geo) in self.oblast_units or (segment, geo) in self.rest:
            if channel in self.physical or model_channel in self.physical:
                rest = self.rest.get((segment, geo))
                return ('oblast_physical_to_rest', [(rest, 1.0)]) if rest else ('oblast_physical_no_rest_unit', [])
            members = self.oblast_units.get((segment, geo)) or []
            total = sum(p for _, p in members)
            if not members or total <= 0:
                return 'oblast_without_units', []
            return 'oblast_broadcast_by_population', [(unit, p / total) for unit, p in members]
        oblast = self.city_oblast.get(geo)
        if oblast:
            rest = self.rest.get((segment, oblast))
            return ('city_not_in_model_to_oblast_rest', [(rest, 1.0)]) if rest else ('city_not_in_model_no_rest_unit', [])
        return 'not_routed', []

    def route(self, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        """Route normalized plan rows. Returns (rows at model units, provenance, audit); money is kept exactly."""
        routed: list[dict[str, Any]] = []
        provenance: list[dict[str, Any]] = []
        by_rule: dict[str, dict[str, float]] = defaultdict(lambda: {'rows_n': 0, 'budget_rub': 0.0})
        for row in rows:
            budget = float(row['budget_rub'])
            rule, parts = self.targets(str(row['segment']), str(row['geo']), str(row['channel']))
            by_rule[rule]['rows_n'] += 1
            by_rule[rule]['budget_rub'] += budget
            if not parts:
                routed.append(dict(row))
                provenance.append(dict(source_row_id=row.get('source_row_id'), segment=row['segment'],
                                       channel=row['channel'], plan_geo=row['geo'], model_geo=row['geo'], rule=rule,
                                       share=1.0, plan_budget_rub=budget, model_budget_rub=budget))
                continue
            money_left = budget
            for i, (unit, share) in enumerate(parts):
                last = i == len(parts) - 1
                part = money_left if last else budget * share       # the last part takes the rounding remainder
                money_left -= part
                routed.append(dict(row, geo=unit, budget_rub=part, routed_from_geo=row['geo'], routing_rule=rule))
                provenance.append(dict(source_row_id=row.get('source_row_id'), segment=row['segment'],
                                       channel=row['channel'], plan_geo=row['geo'], model_geo=unit, rule=rule,
                                       share=share, plan_budget_rub=budget, model_budget_rub=part))
        total_in = sum(float(r['budget_rub']) for r in rows)
        total_out = sum(float(r['budget_rub']) for r in routed)
        if abs(total_in - total_out) > max(1e-6, abs(total_in) * 1e-12):
            raise WeeklyPlanRoutingError(f'routing changed the plan money: {total_in} -> {total_out}')
        audit = dict(rules_version=RULES_VERSION, rows_in=len(rows), rows_out=len(routed), budget_rub=total_in,
                     by_rule={k: dict(v) for k, v in sorted(by_rule.items())},
                     routed_rows_n=sum(1 for r in routed if r.get('routing_rule')),
                     unplaced_rules=sorted(k for k in by_rule if k in {
                         'oblast_physical_no_rest_unit', 'oblast_without_units', 'city_not_in_model_no_rest_unit',
                         'not_routed'}))
        return routed, provenance, audit
