"""Fail-closed federal media allocation for application campaign plans.

The allocator is deliberately upstream of forecast/model code.  It resolves a
single immutable package context, expands every federal daily source row on its
own, preserves row-level provenance, and aggregates only after all validations
and conservation checks have passed.
"""

from __future__ import annotations

import csv
import hashlib
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .model_package import sha256_file
from .model_package_reader import ModelPackage


POLICY_VERSION = "FEDERAL_GEO_ALLOCATION_V1"
CONSERVATION_TOLERANCE_RUB = 0.01
TURNOVER_TARGET = "turnover_per_user"
SUPPORTED_CHANNELS = frozenset(
    {
        "Digital_Performance",
        "OOH_Total",
        "Indoor",
        "Радио",
        "Нац_ТВ",
        "Рег_ТВ",
    }
)
FEDERAL_GEO_ALIASES = ("РФ", "Россия", "Российская Федерация")
_FEDERAL_GEO_KEYS = frozenset(value.casefold() for value in FEDERAL_GEO_ALIASES)

ERROR_TEXTS: dict[str, str] = {
    "UNKNOWN_GEO_VALUE": (
        "География не распознана. Для федерального размещения укажите ровно: "
        "«РФ», «Россия» или «Российская Федерация»."
    ),
    "MISSING_SOURCE_ROW_ID": (
        "Не удалось определить исходную строку файла. Загрузите файл повторно; "
        "расчет не запущен."
    ),
    "DUPLICATE_SOURCE_ROW_ID": (
        "Внутренний идентификатор исходной строки повторяется. Расчет остановлен, "
        "чтобы не продублировать бюджет."
    ),
    "INVALID_BUSINESS_DIRECTION": (
        "Выбранное бизнес-направление не поддерживается текущей версией модели."
    ),
    "DIRECTION_CHANNEL_NOT_SUPPORTED_BY_PACKAGE": (
        "Выбранный канал недоступен для этого бизнес-направления в текущей версии модели."
    ),
    "EMPTY_SUPPORTED_GEO_SET": (
        "В текущей версии модели не найден список поддерживаемых географий для "
        "выбранного направления."
    ),
    "NO_FORECAST_READY_GEOS": (
        "Для выбранного периода модель не поддерживает расчет ни по одной "
        "географии. Федеральный бюджет не распределен."
    ),
    "SUPPORTED_GEO_NOT_IN_CATALOG": (
        "Список географий модели не согласован с географическим справочником. "
        "Расчет остановлен."
    ),
    "FEDERAL_POPULATION_MISSING_OR_NONPOSITIVE": (
        "Для одной или нескольких географий модели отсутствует корректная "
        "численность населения. Федеральный бюджет не распределен."
    ),
    "INVALID_BUDGET": "Бюджет должен быть конечным неотрицательным числом.",
    "PACKAGE_POINTER_OR_HASH_MISMATCH": (
        "Версия модели или ее справочников изменилась и не прошла проверку "
        "целостности. Расчет остановлен."
    ),
    "BUDGET_CONSERVATION_FAILED": (
        "После распределения сумма бюджета отличается от исходной более чем на "
        "0,01 ₽. Расчет остановлен."
    ),
    "FEDERAL_ROW_REACHED_FORECAST_BOUNDARY": (
        "Федеральная география не была преобразована в географии модели. "
        "Forecast не запущен."
    ),
}

WARNING_TEXTS: dict[str, str] = {
    "FEDERAL_GEO_ALLOCATION_INFO": (
        "Федеральный бюджет будет распределен между географиями, для которых "
        "модель поддерживает расчет на выбранный период, по действующей методике модели."
    ),
    "FEDERAL_AND_LOCAL_GEO_OVERLAP": (
        "В плане одновременно указаны федеральный бюджет и отдельные локальные "
        "бюджеты. Локальные суммы будут добавлены поверх федерального распределения."
    ),
}


class FederalGeoAllocationError(RuntimeError):
    """Stable application error with protected technical detail."""

    def __init__(
        self,
        code: str,
        *,
        technical_details: str = "",
        display_text: str | None = None,
    ) -> None:
        if code not in ERROR_TEXTS:
            raise ValueError(f"Unknown federal allocation error code: {code}")
        self.code = code
        self.display_text = display_text or ERROR_TEXTS[code]
        self.technical_details = technical_details
        super().__init__(f"{code}: {technical_details}" if technical_details else code)


def is_federal_geo(value: Any) -> bool:
    """Recognize only the approved aliases after outer trim and case folding."""

    return str(value or "").strip().casefold() in _FEDERAL_GEO_KEYS


def assert_no_federal_geo(rows: Iterable[Mapping[str, Any]]) -> None:
    """Defense-in-depth guard for the forecast input boundary."""

    if any(is_federal_geo(row.get("geo")) for row in rows):
        raise FederalGeoAllocationError("FEDERAL_ROW_REACHED_FORECAST_BOUNDARY")


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except (OSError, UnicodeError, csv.Error) as exc:
        raise FederalGeoAllocationError(
            "PACKAGE_POINTER_OR_HASH_MISMATCH",
            technical_details=f"Cannot read allocation source {path.name}: {exc}",
        ) from exc


def _checksum(values: Iterable[str]) -> str:
    payload = "\n".join(sorted(values)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _finite_nonnegative(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise FederalGeoAllocationError("INVALID_BUDGET") from exc
    if not math.isfinite(number) or number < 0:
        raise FederalGeoAllocationError("INVALID_BUDGET")
    return number


@dataclass(frozen=True)
class EligibleGeo:
    geo_id: str
    geo_label: str
    geo_display_name: str
    population_k: float


@dataclass(frozen=True)
class FederalGeoAllocationContext:
    """Pinned, fully loaded and hash-verified policy context for one run."""

    policy_version: str
    package_id: str
    package_pointer_sha256: str
    registration_content_sha256: str
    support_source_sha256: str
    denominator_source_sha256: str
    capability_source_sha256: str
    population_source_sha256: str
    geo_catalog_sha256: str
    eligible_by_direction: Mapping[str, tuple[EligibleGeo, ...]]
    capability_pairs: frozenset[tuple[str, str]]
    geo_by_label: Mapping[str, EligibleGeo]
    eligible_geo_set_checksums: Mapping[str, str]

    @classmethod
    def from_package(
        cls,
        package: ModelPackage,
        *,
        package_id: str,
        package_pointer_sha256: str,
        registration_content_sha256: str,
        registered_inventory_sha256: Mapping[str, Any],
        population_path: Path,
        expected_population_sha256: str,
        geo_catalog_path: Path,
        expected_geo_catalog_sha256: str,
    ) -> "FederalGeoAllocationContext":
        """Load all reference files exactly once and freeze their values in memory."""

        if not package_id or not package_pointer_sha256 or not registration_content_sha256:
            raise FederalGeoAllocationError(
                "PACKAGE_POINTER_OR_HASH_MISMATCH",
                technical_details="Pinned registry identity is incomplete",
            )
        denominator_path = package.run_dir / "target_denominator_metadata.csv"
        support_path = package.run_dir / "historical_support_bounds.csv"
        capability_path = package.run_dir / "capability_matrix.csv"
        paths = {
            "target_denominator_metadata.csv": denominator_path,
            "historical_support_bounds.csv": support_path,
            "capability_matrix.csv": capability_path,
        }
        actual_hashes: dict[str, str] = {}
        for name, path in paths.items():
            expected = str(registered_inventory_sha256.get(name) or "")
            try:
                actual = sha256_file(path)
            except OSError as exc:
                raise FederalGeoAllocationError(
                    "PACKAGE_POINTER_OR_HASH_MISMATCH",
                    technical_details=f"Cannot hash package source {name}: {exc}",
                ) from exc
            if not expected or not actual or actual != expected:
                raise FederalGeoAllocationError(
                    "PACKAGE_POINTER_OR_HASH_MISMATCH",
                    technical_details=f"Registered hash mismatch for {name}",
                )
            actual_hashes[name] = actual

        try:
            population_hash = sha256_file(population_path)
            catalog_hash = sha256_file(geo_catalog_path)
        except OSError as exc:
            raise FederalGeoAllocationError(
                "PACKAGE_POINTER_OR_HASH_MISMATCH",
                technical_details=f"Cannot hash allocation reference: {exc}",
            ) from exc
        if population_hash != expected_population_sha256:
            raise FederalGeoAllocationError(
                "PACKAGE_POINTER_OR_HASH_MISMATCH",
                technical_details="Population source hash mismatch",
            )
        if catalog_hash != expected_geo_catalog_sha256:
            raise FederalGeoAllocationError(
                "PACKAGE_POINTER_OR_HASH_MISMATCH",
                technical_details="Geo catalog hash mismatch",
            )

        denominator_rows = _read_csv(denominator_path)
        support_rows = _read_csv(support_path)
        capability_rows = _read_csv(capability_path)
        population_rows = _read_csv(population_path)
        catalog_rows = _read_csv(geo_catalog_path)

        catalog: dict[str, tuple[str, str]] = {}
        for row in catalog_rows:
            label = str(row.get("geo_normalized_name") or "").strip()
            geo_id = str(row.get("geo_id") or "").strip()
            display = str(row.get("geo_display_name") or "").strip()
            if not label or not geo_id or not display or label in catalog:
                raise FederalGeoAllocationError(
                    "PACKAGE_POINTER_OR_HASH_MISMATCH",
                    technical_details="Geo catalog is empty, incomplete or duplicated",
                )
            catalog[label] = (geo_id, display)

        population: dict[str, float] = {}
        duplicate_population: set[str] = set()
        invalid_population: set[str] = set()
        for row in population_rows:
            label = str(row.get("geo_label") or "").strip()
            if not label:
                continue
            if label in population:
                duplicate_population.add(label)
                continue
            try:
                value = float(row.get("population_k") or "")
            except (TypeError, ValueError):
                value = math.nan
            population[label] = value
            if not math.isfinite(value) or value <= 0:
                invalid_population.add(label)

        denominator_sets: dict[str, set[str]] = defaultdict(set)
        for row in denominator_rows:
            direction = str(row.get("segment") or "").strip()
            label = str(row.get("geo_label") or "").strip()
            if direction and label:
                denominator_sets[direction].add(label)
        support_sets: dict[str, set[str]] = defaultdict(set)
        for row in support_rows:
            if str(row.get("target") or "") != TURNOVER_TARGET:
                continue
            if str(row.get("scope") or "") != "geo":
                continue
            direction = str(row.get("segment") or "").strip()
            label = str(row.get("geo_label") or "").strip()
            if direction and label:
                support_sets[direction].add(label)
        if not denominator_sets:
            raise FederalGeoAllocationError(
                "EMPTY_SUPPORTED_GEO_SET",
                technical_details="Denominator metadata has no direction geography sets",
            )
        if set(denominator_sets) != set(support_sets):
            raise FederalGeoAllocationError(
                "PACKAGE_POINTER_OR_HASH_MISMATCH",
                technical_details="Direction sets differ between denominator and support sources",
            )
        for direction, labels in denominator_sets.items():
            if not labels:
                raise FederalGeoAllocationError("EMPTY_SUPPORTED_GEO_SET")
            if labels != support_sets[direction]:
                raise FederalGeoAllocationError(
                    "PACKAGE_POINTER_OR_HASH_MISMATCH",
                    technical_details=f"Support crosscheck differs for direction {direction}",
                )

        all_supported = set().union(*denominator_sets.values())
        missing_catalog = all_supported - set(catalog)
        if missing_catalog:
            raise FederalGeoAllocationError(
                "SUPPORTED_GEO_NOT_IN_CATALOG",
                technical_details=f"Missing catalog labels: {sorted(missing_catalog)[:5]}",
            )
        invalid_or_missing_population = (
            (all_supported - set(population))
            | (invalid_population & all_supported)
            | (duplicate_population & all_supported)
        )

        geo_by_label = {
            label: EligibleGeo(
                geo_id=catalog[label][0],
                geo_label=label,
                geo_display_name=catalog[label][1],
                population_k=(
                    math.nan
                    if label in invalid_or_missing_population
                    else population[label]
                ),
            )
            for label in all_supported
        }
        eligible_by_direction = {
            direction: tuple(
                sorted(
                    (geo_by_label[label] for label in labels),
                    key=lambda item: item.geo_id,
                )
            )
            for direction, labels in denominator_sets.items()
        }
        capability_pairs = frozenset(
            (
                str(row.get("segment") or "").strip(),
                str(row.get("channel") or "").strip(),
            )
            for row in capability_rows
            if str(row.get("target") or "") == TURNOVER_TARGET
            and str(row.get("allowed_use") or "")
            in {"primary", "caution", "diagnostic"}
            and str(row.get("channel") or "").strip() in SUPPORTED_CHANNELS
        )
        checksums = {
            direction: _checksum(
                f"{geo.geo_id}|{geo.geo_label}" for geo in eligible
            )
            for direction, eligible in eligible_by_direction.items()
        }
        return cls(
            policy_version=POLICY_VERSION,
            package_id=package_id,
            package_pointer_sha256=package_pointer_sha256,
            registration_content_sha256=registration_content_sha256,
            support_source_sha256=actual_hashes["historical_support_bounds.csv"],
            denominator_source_sha256=actual_hashes[
                "target_denominator_metadata.csv"
            ],
            capability_source_sha256=actual_hashes["capability_matrix.csv"],
            population_source_sha256=population_hash,
            geo_catalog_sha256=catalog_hash,
            eligible_by_direction=eligible_by_direction,
            capability_pairs=capability_pairs,
            geo_by_label=geo_by_label,
            eligible_geo_set_checksums=checksums,
        )

    def eligible_geos(
        self,
        direction: str,
        channel: str,
        allowed_labels: Iterable[str] | None = None,
    ) -> tuple[EligibleGeo, ...]:
        if direction not in self.eligible_by_direction:
            raise FederalGeoAllocationError("INVALID_BUSINESS_DIRECTION")
        if (direction, channel) not in self.capability_pairs:
            raise FederalGeoAllocationError(
                "DIRECTION_CHANNEL_NOT_SUPPORTED_BY_PACKAGE"
            )
        declared = self.eligible_by_direction[direction]
        if not declared:
            raise FederalGeoAllocationError("EMPTY_SUPPORTED_GEO_SET")
        if allowed_labels is None:
            eligible = declared
        else:
            allowed = {str(value) for value in allowed_labels}
            unknown = allowed - {geo.geo_label for geo in declared}
            if unknown:
                raise FederalGeoAllocationError(
                    "PACKAGE_POINTER_OR_HASH_MISMATCH",
                    technical_details=(
                        "Forecast-ready geo set is outside declared package support: "
                        f"{sorted(unknown)[:5]}"
                    ),
                )
            eligible = tuple(geo for geo in declared if geo.geo_label in allowed)
        if not eligible:
            raise FederalGeoAllocationError("NO_FORECAST_READY_GEOS")
        invalid_population = [
            geo.geo_label
            for geo in eligible
            if not math.isfinite(geo.population_k) or geo.population_k <= 0
        ]
        if invalid_population:
            raise FederalGeoAllocationError(
                "FEDERAL_POPULATION_MISSING_OR_NONPOSITIVE",
                technical_details=(
                    "Invalid population labels in forecast-ready geo set: "
                    f"{invalid_population[:5]}"
                ),
            )
        return eligible

    def audit_identity(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "package_id": self.package_id,
            "package_pointer_sha256": self.package_pointer_sha256,
            "registration_content_sha256": self.registration_content_sha256,
            "support_source_sha256": self.support_source_sha256,
            "denominator_source_sha256": self.denominator_source_sha256,
            "capability_source_sha256": self.capability_source_sha256,
            "population_source_sha256": self.population_source_sha256,
            "geo_catalog_sha256": self.geo_catalog_sha256,
            "eligible_geo_set_checksums": dict(self.eligible_geo_set_checksums),
        }


@dataclass(frozen=True)
class FederalGeoAllocationResult:
    expanded_rows: tuple[dict[str, Any], ...]
    aggregated_rows: tuple[dict[str, Any], ...]
    warnings: tuple[dict[str, Any], ...]
    audit: dict[str, Any]


class FederalGeoAllocator:
    """Allocate federal daily rows by direction-level population weights."""

    def __init__(self, context: FederalGeoAllocationContext) -> None:
        self.context = context

    def allocate(
        self,
        daily_rows: Iterable[Mapping[str, Any]],
        *,
        eligible_geo_labels_by_source_row_id: Mapping[str, Iterable[str]] | None = None,
        eligibility_audit_by_source_row_id: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> FederalGeoAllocationResult:
        source = [dict(row) for row in daily_rows]
        seen_keys: set[tuple[str, str]] = set()
        federal_groups: set[tuple[str, str, str]] = set()
        local_groups: set[tuple[str, str, str]] = set()

        # Validate the whole input before creating any expanded output.
        for row in source:
            source_id = str(row.get("source_row_id") or "").strip()
            if not source_id:
                raise FederalGeoAllocationError("MISSING_SOURCE_ROW_ID")
            key = (source_id, str(row.get("date") or ""))
            if key in seen_keys:
                raise FederalGeoAllocationError("DUPLICATE_SOURCE_ROW_ID")
            seen_keys.add(key)
            _finite_nonnegative(row.get("budget_rub"))
            direction = str(
                row.get("business_direction") or row.get("segment") or ""
            ).strip()
            channel = str(row.get("channel") or "").strip()
            group = (str(row.get("date") or ""), direction, channel)
            if is_federal_geo(row.get("geo")):
                allowed_labels = None
                if eligible_geo_labels_by_source_row_id is not None:
                    if source_id not in eligible_geo_labels_by_source_row_id:
                        raise FederalGeoAllocationError(
                            "PACKAGE_POINTER_OR_HASH_MISMATCH",
                            technical_details=(
                                "Forecast-ready geo set is missing for federal "
                                f"source_row_id={source_id}"
                            ),
                        )
                    allowed_labels = eligible_geo_labels_by_source_row_id[source_id]
                self.context.eligible_geos(direction, channel, allowed_labels)
                federal_groups.add(group)
            else:
                label = str(row.get("geo") or "").strip()
                if label not in self.context.geo_by_label:
                    raise FederalGeoAllocationError(
                        "UNKNOWN_GEO_VALUE",
                        technical_details=f"Unknown local geo label: {label}",
                    )
                local_groups.add(group)

        expanded: list[dict[str, Any]] = []
        source_reconciliation: list[dict[str, Any]] = []
        federal_source_total = 0.0
        federal_allocated_total = 0.0
        local_source_total = 0.0
        federal_rows_n = 0
        for row in source:
            source_id = str(row["source_row_id"])
            direction = str(
                row.get("business_direction") or row.get("segment") or ""
            ).strip()
            channel = str(row.get("channel") or "").strip()
            spend = _finite_nonnegative(row.get("budget_rub"))
            common = {
                "source_row_id": source_id,
                "campaign_name": str(row.get("campaign_name") or "unknown_campaign"),
                "creative_name": str(row.get("creative_name") or ""),
                "date": str(row.get("date") or ""),
                "business_direction": direction,
                "segment": direction,
                "channel": channel,
                "original_geo": str(row.get("geo") or "").strip(),
                "original_spend_rub": spend,
                "policy_version": self.context.policy_version,
                "package_id": self.context.package_id,
            }
            if is_federal_geo(row.get("geo")):
                federal_rows_n += 1
                federal_source_total += spend
                allowed_labels = (
                    eligible_geo_labels_by_source_row_id.get(source_id)
                    if eligible_geo_labels_by_source_row_id is not None
                    else None
                )
                eligible = self.context.eligible_geos(
                    direction,
                    channel,
                    allowed_labels,
                )
                eligibility_audit = dict(
                    (eligibility_audit_by_source_row_id or {}).get(source_id) or {}
                )
                denominator = math.fsum(geo.population_k for geo in eligible)
                if not math.isfinite(denominator) or denominator <= 0:
                    raise FederalGeoAllocationError(
                        "FEDERAL_POPULATION_MISSING_OR_NONPOSITIVE"
                    )
                row_start = len(expanded)
                for geo in eligible:
                    weight = geo.population_k / denominator
                    expanded.append(
                        {
                            **common,
                            "row_type": "federal_expansion",
                            "geo_id": geo.geo_id,
                            "geo": geo.geo_label,
                            "geo_display_name": geo.geo_display_name,
                            "population_k": geo.population_k,
                            "allocation_weight": weight,
                            "allocated_spend_rub": spend * weight,
                            "allocation_geo_count": len(eligible),
                        }
                    )
                allocated = math.fsum(
                    float(item["allocated_spend_rub"])
                    for item in expanded[row_start:]
                )
                difference = abs(spend - allocated)
                if difference > CONSERVATION_TOLERANCE_RUB:
                    raise FederalGeoAllocationError(
                        "BUDGET_CONSERVATION_FAILED",
                        technical_details=(
                            f"source_row_id={source_id}, difference={difference:.12f}"
                        ),
                    )
                federal_allocated_total += allocated
                source_reconciliation.append(
                    {
                        "source_row_id": source_id,
                        "date": common["date"],
                        "business_direction": direction,
                        "channel": channel,
                        "original_geo": common["original_geo"],
                        "source_budget_rub": spend,
                        "eligible_geo_count": len(eligible),
                        "declared_geo_count": int(
                            eligibility_audit.get("declared_geo_count")
                            or len(self.context.eligible_by_direction[direction])
                        ),
                        "ready_geo_count": int(
                            eligibility_audit.get("ready_geo_count") or len(eligible)
                        ),
                        "excluded_geo_count": int(
                            eligibility_audit.get("excluded_geo_count") or 0
                        ),
                        "required_start": str(
                            eligibility_audit.get("required_start")
                            or row.get("source_start_date")
                            or common["date"]
                        ),
                        "required_end": str(
                            eligibility_audit.get("required_end")
                            or row.get("source_end_date")
                            or common["date"]
                        ),
                        "lmax": eligibility_audit.get("lmax"),
                        "denominator_policy_version": str(
                            eligibility_audit.get("denominator_policy_version") or ""
                        ),
                        "availability_policy_version": str(
                            eligibility_audit.get("availability_policy_version") or ""
                        ),
                        "allocated_total_rub": allocated,
                        "difference_rub": difference,
                        "conservation_pass": True,
                    }
                )
                continue

            local_source_total += spend
            geo = self.context.geo_by_label[str(row.get("geo") or "").strip()]
            expanded.append(
                {
                    **common,
                    "row_type": "local_passthrough",
                    "geo_id": geo.geo_id,
                    "geo": geo.geo_label,
                    "geo_display_name": geo.geo_display_name,
                    "population_k": geo.population_k,
                    "allocation_weight": 1.0,
                    "allocated_spend_rub": spend,
                }
            )

        aggregate: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
        for row in expanded:
            key = (
                str(row["campaign_name"]),
                str(row["date"]),
                str(row["business_direction"]),
                str(row["channel"]),
                str(row["geo_id"]),
            )
            if key not in aggregate:
                aggregate[key] = {
                    "campaign_name": row["campaign_name"],
                    "creative_name": "",
                    "segment": row["business_direction"],
                    "business_direction": row["business_direction"],
                    "geo_id": row["geo_id"],
                    "geo": row["geo"],
                    "geo_display_name": row["geo_display_name"],
                    "channel": row["channel"],
                    "date": row["date"],
                    "budget_rub": 0.0,
                    "flighting_source": "federal_geo_allocation_v1",
                    "source_row_id": "",
                    "source_start_date": row["date"],
                    "source_end_date": row["date"],
                    "policy_version": self.context.policy_version,
                    "package_id": self.context.package_id,
                }
            aggregate[key]["budget_rub"] += float(row["allocated_spend_rub"])
        aggregated = tuple(aggregate[key] for key in sorted(aggregate))
        assert_no_federal_geo(aggregated)

        source_total = federal_source_total + local_source_total
        final_total = math.fsum(float(row["budget_rub"]) for row in aggregated)
        plan_difference = abs(source_total - final_total)
        if plan_difference > CONSERVATION_TOLERANCE_RUB:
            raise FederalGeoAllocationError(
                "BUDGET_CONSERVATION_FAILED",
                technical_details=f"Plan difference={plan_difference:.12f}",
            )

        overlap_groups = sorted(federal_groups & local_groups)
        warnings: list[dict[str, Any]] = []
        if overlap_groups:
            warnings.append(
                {
                    "code": "FEDERAL_AND_LOCAL_GEO_OVERLAP",
                    "display_text": WARNING_TEXTS[
                        "FEDERAL_AND_LOCAL_GEO_OVERLAP"
                    ],
                    "groups": [
                        {
                            "date": date,
                            "business_direction": direction,
                            "channel": channel,
                        }
                        for date, direction, channel in overlap_groups
                    ],
                }
            )
        audit = {
            "schema_version": "1.0.0",
            **self.context.audit_identity(),
            "forecast_geo_availability": {
                "source_rows": [
                    {
                        "source_row_id": source_row_id,
                        **dict(row_audit),
                    }
                    for source_row_id, row_audit in sorted(
                        (eligibility_audit_by_source_row_id or {}).items()
                    )
                ]
            },
            "source_rows_n": len(source),
            "federal_source_rows_n": federal_rows_n,
            "local_source_rows_n": len(source) - federal_rows_n,
            "expanded_rows_before_aggregation_n": len(expanded),
            "aggregated_rows_n": len(aggregated),
            "source_row_reconciliation": source_reconciliation,
            "totals": {
                "federal_source_budget_rub": federal_source_total,
                "federal_allocated_budget_rub": federal_allocated_total,
                "local_source_budget_rub": local_source_total,
                "source_total_budget_rub": source_total,
                "final_plan_budget_rub": final_total,
                "difference_rub": plan_difference,
                "conservation_pass": True,
                "tolerance_rub": CONSERVATION_TOLERANCE_RUB,
            },
            "warnings": warnings,
            "information": [
                {
                    "code": "FEDERAL_GEO_ALLOCATION_INFO",
                    "display_text": WARNING_TEXTS["FEDERAL_GEO_ALLOCATION_INFO"],
                }
            ]
            if federal_rows_n
            else [],
            "errors": [],
        }
        return FederalGeoAllocationResult(
            expanded_rows=tuple(expanded),
            aggregated_rows=aggregated,
            warnings=tuple(warnings),
            audit=audit,
        )
