"""Versioned static geography identities and coordinates for browser projections.

The runtime reads repository data only. It never calls a geocoder, map API or
network service, and it never guesses an unknown or ambiguous geography.
"""

from __future__ import annotations

import csv
import hashlib
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from mmm_core.campaign_plan import normalize_geo_alias_name


WEB_APP_DIR = Path(__file__).resolve().parents[1]
CATALOG_DIR = WEB_APP_DIR / "data" / "geo_catalog"
CATALOG_PATH = CATALOG_DIR / "geo_catalog_v1.csv"
ALIASES_PATH = CATALOG_DIR / "geo_aliases_v1.csv"
GEO_CATALOG_VERSION = "geo_catalog_v1_2026_07_18"
COORDINATES_SOURCE = "GeoNames RU dump (WGS84)"
COORDINATES_SOURCE_DATE = "2026-07-18"
COORDINATES_SOURCE_SNAPSHOT_SHA256 = (
    "e900a407f811b53a1bf51612fe6f1a809af275e43a02b85f63c7bfddd75e4035"
)
COORDINATES_REVIEW_STATUS = "reviewed_static"

class GeoCatalogError(ValueError):
    """Raised when static catalog data or a serving-coverage guard is invalid."""


def normalize_geo_name(value: Any) -> str:
    """Apply only deterministic lexical normalization, never fuzzy matching."""

    return normalize_geo_alias_name(value)


def stable_geo_id(value: Any) -> str:
    """Return the E.1A-compatible geography identity for a normalized label."""

    normalized = normalize_geo_name(value)
    if not normalized:
        raise GeoCatalogError("Geo name is required")
    return "geo_" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise GeoCatalogError(f"Static geo data is missing: {path.name}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _required(row: Mapping[str, Any], field: str) -> str:
    value = str(row.get(field) or "").strip()
    if not value:
        raise GeoCatalogError(f"Static geo field is required: {field}")
    return value


def _coordinate(row: Mapping[str, Any], field: str, lower: float, upper: float) -> float:
    try:
        value = float(row.get(field))
    except (TypeError, ValueError) as exc:
        raise GeoCatalogError(f"Static geo coordinate is invalid: {field}") from exc
    if not math.isfinite(value) or not lower <= value <= upper:
        raise GeoCatalogError(f"Static geo coordinate is out of range: {field}")
    return value


@dataclass(frozen=True)
class GeoResolution:
    """One canonical, aliased, unknown or ambiguous geography resolution."""

    input_geo_name: str
    geo_id: str
    geo_display_name: str
    canonical_geo_id: str | None
    canonical_geo_display_name: str | None
    normalization_status: str
    normalization_rule: str
    latitude: float | None
    longitude: float | None
    coordinates_status: str
    region_id: str | None
    region_display_name: str | None

    def browser_entry(self) -> dict[str, Any]:
        return {
            "geo_id": self.geo_id,
            "geo_display_name": self.geo_display_name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "coordinates_status": self.coordinates_status,
            "region_id": self.region_id,
            "region_display_name": self.region_display_name,
        }

    def normalization_evidence(self) -> dict[str, Any]:
        return {
            "input_geo_name": self.input_geo_name,
            "canonical_geo_id": self.canonical_geo_id,
            "canonical_geo_display_name": self.canonical_geo_display_name,
            "normalization_status": self.normalization_status,
            "normalization_rule": self.normalization_rule,
        }


class CanonicalGeoCatalog:
    """Validated in-memory view over the versioned static CSV catalogs."""

    def __init__(
        self,
        entries: Sequence[Mapping[str, Any]],
        aliases: Sequence[Mapping[str, Any]],
        *,
        strict_aliases: bool = True,
    ) -> None:
        parsed_entries: list[dict[str, Any]] = []
        ids: set[str] = set()
        names: set[str] = set()
        for source in entries:
            normalized = normalize_geo_name(_required(source, "geo_normalized_name"))
            entry = {
                "geo_id": _required(source, "geo_id"),
                "geo_display_name": _required(source, "geo_display_name"),
                "geo_normalized_name": normalized,
                "geo_type": _required(source, "geo_type"),
                "latitude": _coordinate(source, "latitude", -90.0, 90.0),
                "longitude": _coordinate(source, "longitude", -180.0, 180.0),
                "region_id": _required(source, "region_id"),
                "region_display_name": _required(source, "region_display_name"),
                "federal_district_id": _required(source, "federal_district_id"),
                "federal_district_display_name": _required(
                    source, "federal_district_display_name"
                ),
                "country_code": _required(source, "country_code"),
                "coordinates_source": _required(source, "coordinates_source"),
                "coordinates_source_record_id": _required(
                    source, "coordinates_source_record_id"
                ),
                "coordinates_source_version_or_date": _required(
                    source, "coordinates_source_version_or_date"
                ),
                "coordinates_source_snapshot_sha256": _required(
                    source, "coordinates_source_snapshot_sha256"
                ),
                "coordinates_review_status": _required(
                    source, "coordinates_review_status"
                ),
                "catalog_version": _required(source, "catalog_version"),
            }
            if entry["geo_id"] != stable_geo_id(normalized):
                raise GeoCatalogError(
                    f"Geo ID is incompatible with the E.1A identity: {normalized}"
                )
            if entry["geo_id"] in ids or normalized in names:
                raise GeoCatalogError("Static geo catalog contains duplicate identities")
            if entry["country_code"] != "RU":
                raise GeoCatalogError("Static geo catalog contains a non-Russian entry")
            if (
                entry["coordinates_source"] != COORDINATES_SOURCE
                or entry["coordinates_source_version_or_date"]
                != COORDINATES_SOURCE_DATE
                or entry["coordinates_source_snapshot_sha256"]
                != COORDINATES_SOURCE_SNAPSHOT_SHA256
                or entry["coordinates_review_status"]
                != COORDINATES_REVIEW_STATUS
                or entry["catalog_version"] != GEO_CATALOG_VERSION
            ):
                raise GeoCatalogError("Static geo source/version metadata is inconsistent")
            ids.add(entry["geo_id"])
            names.add(normalized)
            parsed_entries.append(entry)
        if not parsed_entries:
            raise GeoCatalogError("Static geo catalog is empty")

        by_id = {row["geo_id"]: row for row in parsed_entries}
        alias_candidates: dict[str, set[str]] = defaultdict(set)
        alias_rules: dict[tuple[str, str], str] = {}
        seen_aliases: set[tuple[str, str]] = set()
        for source in aliases:
            alias = _required(source, "alias")
            normalized_alias = normalize_geo_name(
                _required(source, "alias_normalized_name")
            )
            if normalized_alias != normalize_geo_name(alias):
                raise GeoCatalogError("Alias normalized name is inconsistent")
            canonical_id = _required(source, "canonical_geo_id")
            alias_identity = (normalized_alias, canonical_id)
            if alias_identity in seen_aliases:
                raise GeoCatalogError("Static geo alias catalog contains duplicates")
            seen_aliases.add(alias_identity)
            entry = by_id.get(canonical_id)
            if entry is None:
                raise GeoCatalogError("Alias references an unknown canonical geo")
            if (
                normalize_geo_name(
                    _required(source, "canonical_geo_normalized_name")
                )
                != entry["geo_normalized_name"]
                or _required(source, "catalog_version") != GEO_CATALOG_VERSION
            ):
                raise GeoCatalogError("Alias canonical metadata is inconsistent")
            alias_candidates[normalized_alias].add(canonical_id)
            alias_rules[(normalized_alias, canonical_id)] = _required(
                source, "normalization_rule"
            )
        for entry in parsed_entries:
            normalized = entry["geo_normalized_name"]
            if (
                alias_candidates.get(normalized) != {entry["geo_id"]}
                or alias_rules.get((normalized, entry["geo_id"]))
                != "canonical_name"
            ):
                raise GeoCatalogError(
                    f"Canonical geo name is absent from alias catalog: {normalized}"
                )
        ambiguous = {
            alias: sorted(candidates)
            for alias, candidates in alias_candidates.items()
            if len(candidates) > 1
        }
        if strict_aliases and ambiguous:
            raise GeoCatalogError(f"Production aliases are ambiguous: {ambiguous}")

        self._entries = tuple(
            sorted(parsed_entries, key=lambda row: row["geo_normalized_name"])
        )
        self._by_id = by_id
        self._alias_candidates = {
            key: tuple(sorted(value)) for key, value in alias_candidates.items()
        }
        self._alias_rules = alias_rules

    @classmethod
    def from_files(
        cls,
        catalog_path: Path = CATALOG_PATH,
        aliases_path: Path = ALIASES_PATH,
    ) -> "CanonicalGeoCatalog":
        return cls(_read_csv(catalog_path), _read_csv(aliases_path))

    @property
    def entries(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(row) for row in self._entries)

    @property
    def geographies_n(self) -> int:
        return len(self._entries)

    def resolve(self, value: Any) -> GeoResolution:
        input_name = " ".join(str(value or "").strip().split())
        normalized = normalize_geo_name(input_name)
        if not normalized:
            raise GeoCatalogError("Geo name is required")
        candidates = self._alias_candidates.get(normalized, ())
        if len(candidates) == 1:
            canonical_id = candidates[0]
            entry = self._by_id[canonical_id]
            rule = self._alias_rules[(normalized, canonical_id)]
            status = "canonical" if rule == "canonical_name" else "alias"
            return GeoResolution(
                input_geo_name=input_name,
                geo_id=canonical_id,
                geo_display_name=entry["geo_display_name"],
                canonical_geo_id=canonical_id,
                canonical_geo_display_name=entry["geo_display_name"],
                normalization_status=status,
                normalization_rule=rule,
                latitude=entry["latitude"],
                longitude=entry["longitude"],
                coordinates_status="canonical",
                region_id=entry["region_id"],
                region_display_name=entry["region_display_name"],
            )
        if len(candidates) > 1:
            status = "ambiguous"
            rule = "registered_alias_has_multiple_candidates"
        else:
            status = "unknown"
            rule = "no_registered_alias"
        return GeoResolution(
            input_geo_name=input_name,
            geo_id=stable_geo_id(normalized),
            geo_display_name=input_name,
            canonical_geo_id=None,
            canonical_geo_display_name=None,
            normalization_status=status,
            normalization_rule=rule,
            latitude=None,
            longitude=None,
            coordinates_status="unavailable",
            region_id=None,
            region_display_name=None,
        )

    def resolve_many(self, values: Iterable[Any]) -> tuple[GeoResolution, ...]:
        by_id: dict[str, GeoResolution] = {}
        for value in values:
            resolution = self.resolve(value)
            by_id.setdefault(resolution.geo_id, resolution)
        return tuple(
            sorted(by_id.values(), key=lambda row: normalize_geo_name(row.geo_display_name))
        )


@lru_cache(maxsize=1)
def load_canonical_geo_catalog() -> CanonicalGeoCatalog:
    """Load and validate the immutable runtime catalog once per process."""

    return CanonicalGeoCatalog.from_files()


def coverage_summary(
    resolutions: Sequence[GeoResolution],
    *,
    budget_by_geo_id: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Describe located/unlocated coverage without dropping unknown money."""

    located = [row for row in resolutions if row.coordinates_status == "canonical"]
    unlocated = [row for row in resolutions if row.coordinates_status == "unavailable"]
    status = (
        "available"
        if resolutions and len(located) == len(resolutions)
        else "partial"
        if located
        else "unavailable"
    )
    payload: dict[str, Any] = {
        "status": status,
        "located_geographies_n": len(located),
        "unlocated_geographies_n": len(unlocated),
        "unlocated_geographies": [
            {"geo_id": row.geo_id, "geo_display_name": row.geo_display_name}
            for row in unlocated
        ],
    }
    if budget_by_geo_id is not None:
        located_budget = sum(
            float(budget_by_geo_id.get(row.geo_id, 0.0)) for row in located
        )
        unlocated_budget = sum(
            float(budget_by_geo_id.get(row.geo_id, 0.0)) for row in unlocated
        )
        total = located_budget + unlocated_budget
        payload.update(
            {
                "located_budget_rub": located_budget,
                "unlocated_budget_rub": unlocated_budget,
                "unlocated_budget_share": (
                    unlocated_budget / total if total > 0 else None
                ),
            }
        )
    return payload


def active_turnover_serving_geographies(
    support_rows: Iterable[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Extract active turnover geo labels from package support evidence."""

    geographies = sorted(
        {
            str(row.get("geo_label") or "").strip()
            for row in support_rows
            if str(row.get("scope") or "") == "geo"
            and str(row.get("target") or "") == "turnover_per_user"
            and str(row.get("geo_label") or "").strip()
        }
    )
    if not geographies:
        raise GeoCatalogError("Active turnover serving geo inventory is empty")
    return tuple(geographies)


def assert_active_serving_geo_coverage(
    active_geographies: Iterable[Any],
    catalog: CanonicalGeoCatalog | None = None,
) -> dict[str, Any]:
    """Fail closed when an active serving geography is absent from the catalog."""

    selected = catalog or load_canonical_geo_catalog()
    resolutions = [selected.resolve(value) for value in active_geographies]
    missing = sorted(
        row.input_geo_name
        for row in resolutions
        if row.normalization_status not in {"canonical", "alias"}
        or row.coordinates_status != "canonical"
    )
    if missing:
        raise GeoCatalogError(
            "Active turnover serving geographies are missing canonical coordinates: "
            f"{missing}"
        )
    return {
        "catalog_version": GEO_CATALOG_VERSION,
        "active_serving_geographies_n": len(resolutions),
        "covered_geographies_n": len(resolutions) - len(missing),
        "status": "available",
    }


__all__ = [
    "ALIASES_PATH",
    "CATALOG_PATH",
    "COORDINATES_REVIEW_STATUS",
    "COORDINATES_SOURCE",
    "COORDINATES_SOURCE_DATE",
    "COORDINATES_SOURCE_SNAPSHOT_SHA256",
    "CanonicalGeoCatalog",
    "GEO_CATALOG_VERSION",
    "GeoCatalogError",
    "GeoResolution",
    "active_turnover_serving_geographies",
    "assert_active_serving_geo_coverage",
    "coverage_summary",
    "load_canonical_geo_catalog",
    "normalize_geo_name",
    "stable_geo_id",
]
