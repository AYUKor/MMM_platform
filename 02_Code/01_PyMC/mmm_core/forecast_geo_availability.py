"""Shared forecast denominator and temporal geo-availability policy.

The same pure denominator resolver is used by the forecast runtime and by
pre-flight campaign validation.  Validation may therefore reject a geography
before job creation without weakening the runtime fail-closed guard.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .io import read_json
from .model_package_reader import ModelPackage


ANALOG_DENOMINATOR_MAX_NEAREST_GAP_DAYS = 7
DENOMINATOR_RESOLUTION_POLICY_VERSION = "FORECAST_DENOMINATOR_RESOLUTION_V1"
FORECAST_GEO_AVAILABILITY_POLICY_VERSION = "FORECAST_GEO_AVAILABILITY_V1"
SUPPORTED_MISSING_GEO_POLICIES = frozenset(
    {"fail", "nearest_available_year_same_geo"}
)


def analog_date(value: date, year: int) -> date:
    """Move a date to the configured analog year, preserving leap-day semantics."""

    try:
        return value.replace(year=int(year))
    except ValueError:
        if value.month == 2 and value.day == 29:
            return date(int(year), 2, 28)
        raise


class HistoricalDenominatorResolver:
    """Exact pure implementation of the denominator lookup used by forecast."""

    def __init__(self, denominators: pd.DataFrame) -> None:
        frame = denominators.copy()
        required = {
            "segment",
            "geo_label",
            "date",
            "population_k",
            "unique_users",
            "orders_cnt",
        }
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ValueError(f"Denominator metadata is missing columns: {missing}")
        frame["segment"] = frame["segment"].astype(str)
        frame["geo_label"] = frame["geo_label"].astype(str)
        frame["date"] = frame["date"].astype(str)
        for column in ["population_k", "unique_users", "orders_cnt"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if "market_size_tier" not in frame.columns:
            frame["market_size_tier"] = ""

        def records_to_map(
            grouped: pd.DataFrame,
            key_columns: list[str],
        ) -> dict[Any, dict[str, Any]]:
            result: dict[Any, dict[str, Any]] = {}
            columns = [
                *key_columns,
                "population_k",
                "unique_users",
                "orders_cnt",
                "market_size_tier",
            ]
            for values in grouped[columns].itertuples(index=False, name=None):
                key_values = tuple(str(value) for value in values[: len(key_columns)])
                key: Any = key_values[0] if len(key_values) == 1 else key_values
                population_k, unique_users, orders_cnt, market_size_tier = values[
                    len(key_columns) :
                ]
                result[key] = {
                    "population_k": (
                        float(population_k)
                        if pd.notna(population_k)
                        else 1.0
                    ),
                    "unique_users": (
                        float(max(unique_users, 1.0))
                        if pd.notna(unique_users)
                        else 1.0
                    ),
                    "orders_cnt": (
                        float(max(orders_cnt, 1.0))
                        if pd.notna(orders_cnt)
                        else 1.0
                    ),
                    "market_size_tier": str(market_size_tier or ""),
                }
            return result

        def aggregate(key_columns: list[str]) -> pd.DataFrame:
            numeric_columns = ["population_k", "unique_users", "orders_cnt"]
            numeric = (
                frame.groupby(key_columns, dropna=False, sort=False)[numeric_columns]
                .median()
                .reset_index()
            )
            tier_source = frame.dropna(subset=["market_size_tier"])[
                [*key_columns, "market_size_tier"]
            ].copy()
            tier_source["market_size_tier"] = tier_source[
                "market_size_tier"
            ].astype(str)
            if tier_source.empty:
                numeric["market_size_tier"] = math.nan
                return numeric
            tier_counts = (
                tier_source.groupby(
                    [*key_columns, "market_size_tier"],
                    dropna=False,
                    sort=False,
                )
                .size()
                .reset_index(name="_count")
            )
            tier_modes = (
                tier_counts.sort_values(
                    [*key_columns, "_count", "market_size_tier"],
                    ascending=[True] * len(key_columns) + [False, True],
                    kind="mergesort",
                )
                .drop_duplicates(key_columns, keep="first")
                .drop(columns="_count")
            )
            return numeric.merge(
                tier_modes,
                on=key_columns,
                how="left",
                validate="one_to_one",
            )

        exact = aggregate(["segment", "geo_label", "date"])
        by_geo = aggregate(["segment", "geo_label"])
        by_segment = aggregate(["segment"])
        self._exact = records_to_map(exact, ["segment", "geo_label", "date"])
        self._by_geo = records_to_map(by_geo, ["segment", "geo_label"])
        self._by_segment = records_to_map(by_segment, ["segment"])
        self._by_geo_year: dict[
            tuple[str, str, int], list[tuple[date, dict[str, Any]]]
        ] = {}
        for key, value in self._exact.items():
            segment, geo, date_text = key
            parsed = date.fromisoformat(date_text)
            self._by_geo_year.setdefault((segment, geo, parsed.year), []).append(
                (parsed, value)
            )
        for values in self._by_geo_year.values():
            values.sort(key=lambda item: item[0])
        self._available_years: dict[tuple[str, str], tuple[int, ...]] = {}
        for segment, geo, year in self._by_geo_year:
            key = (segment, geo)
            self._available_years[key] = tuple(
                sorted({*self._available_years.get(key, ()), year})
            )
        self._cache: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}

    def resolve(
        self,
        segment: str,
        geo: str,
        future_date: date,
        *,
        analog_year: int | None = None,
        missing_geo_policy: str = "fail",
    ) -> dict[str, Any]:
        """Resolve one denominator with forecast-runtime-equivalent semantics."""

        if missing_geo_policy not in SUPPORTED_MISSING_GEO_POLICIES:
            raise ValueError(
                f"Unsupported missing_geo_policy={missing_geo_policy!r}; "
                f"supported={sorted(SUPPORTED_MISSING_GEO_POLICIES)}"
            )
        cache_key = (
            str(segment),
            str(geo),
            future_date.isoformat(),
            str(analog_year or "previous_year"),
            missing_geo_policy,
        )
        if cache_key in self._cache:
            return dict(self._cache[cache_key])

        preferred_year = int(analog_year or (future_date.year - 1))
        analog = analog_date(future_date, preferred_year)
        exact = self._exact.get((str(segment), str(geo), analog.isoformat()))
        analog_year_used = analog.year
        if analog_year is not None and exact is None:
            available_years = self._available_years.get(
                (str(segment), str(geo)),
                (),
            )
            candidate_years = [int(analog_year)]
            if missing_geo_policy == "nearest_available_year_same_geo":
                candidate_years.extend(
                    year for year in available_years if year != int(analog_year)
                )
            viable: list[tuple[int, int, int, date, dict[str, Any]]] = []
            for candidate_year in candidate_years:
                target_date = analog_date(future_date, candidate_year)
                candidates = self._by_geo_year.get(
                    (str(segment), str(geo), candidate_year)
                ) or []
                if not candidates:
                    continue
                nearest_date, nearest_value = min(
                    candidates,
                    key=lambda item: abs((item[0] - target_date).days),
                )
                gap_days = abs((nearest_date - target_date).days)
                if gap_days <= ANALOG_DENOMINATOR_MAX_NEAREST_GAP_DAYS:
                    viable.append(
                        (
                            abs(candidate_year - int(analog_year)),
                            gap_days,
                            candidate_year,
                            nearest_date,
                            nearest_value,
                        )
                    )
            if viable:
                _, gap_days, analog_year_used, nearest_date, nearest_value = min(
                    viable,
                    key=lambda item: (item[0], item[1], item[2]),
                )
                analog = analog_date(future_date, analog_year_used)
                exact = dict(nearest_value)
                exact["denominator_analog_date_used"] = nearest_date.isoformat()
                exact["denominator_fallback_gap_days"] = gap_days
            if exact is None:
                raise ValueError(
                    "Configured historical analog denominator is missing; fallback would change forecast semantics. "
                    f"segment={segment!r}, geo={geo!r}, future_date={future_date.isoformat()}, "
                    f"analog_date={analog.isoformat()}, "
                    f"max_nearest_gap_days={ANALOG_DENOMINATOR_MAX_NEAREST_GAP_DAYS}"
                )

        value = (
            exact
            or self._by_geo.get((str(segment), str(geo)))
            or self._by_segment.get(str(segment))
        )
        if value is None:
            raise ValueError(
                f"No denominator metadata for segment={segment!r}, geo={geo!r}, "
                f"date={future_date.isoformat()}"
            )
        result = dict(value)
        result.setdefault("denominator_analog_date_used", analog.isoformat())
        result.setdefault("denominator_fallback_gap_days", 0)
        result["denominator_analog_year_used"] = analog_year_used
        result["denominator_fallback_years"] = abs(
            analog_year_used - int(analog_year or analog_year_used)
        )
        self._cache[cache_key] = dict(result)
        return result


@dataclass(frozen=True)
class UnavailableGeo:
    geo: str
    reason: str
    first_unavailable_date: str


@dataclass(frozen=True)
class ForecastGeoAvailability:
    package_id: str
    direction: str
    channel: str
    target: str
    campaign_start: str
    campaign_end: str
    required_start: str
    required_end: str
    lmax: int
    analog_year: int | None
    missing_geo_policy: str
    denominator_policy_version: str
    availability_policy_version: str
    declared_geos: tuple[str, ...]
    ready_geos: tuple[str, ...]
    unavailable_geos: tuple[UnavailableGeo, ...]

    def compact_audit(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "direction": self.direction,
            "channel": self.channel,
            "target": self.target,
            "campaign_start": self.campaign_start,
            "campaign_end": self.campaign_end,
            "required_start": self.required_start,
            "required_end": self.required_end,
            "lmax": self.lmax,
            "analog_year": self.analog_year,
            "missing_geo_policy": self.missing_geo_policy,
            "max_nearest_gap_days": ANALOG_DENOMINATOR_MAX_NEAREST_GAP_DAYS,
            "denominator_policy_version": self.denominator_policy_version,
            "availability_policy_version": self.availability_policy_version,
            "declared_geo_count": len(self.declared_geos),
            "ready_geo_count": len(self.ready_geos),
            "excluded_geo_count": len(self.unavailable_geos),
            "unavailable_geos": [
                {
                    "geo": item.geo,
                    "reason": item.reason,
                    "first_unavailable_date": item.first_unavailable_date,
                }
                for item in self.unavailable_geos
            ],
        }


class ForecastGeoAvailabilityResolver:
    """Resolve the model-declared and actually calculable geo sets for a period."""

    def __init__(
        self,
        package: ModelPackage,
        *,
        package_id: str,
        lmax: int,
        denominator_resolver: HistoricalDenominatorResolver,
    ) -> None:
        if int(lmax) < 0:
            raise ValueError("lmax must be nonnegative")
        self.package = package
        self.package_id = str(package_id)
        self.lmax = int(lmax)
        self.denominator_resolver = denominator_resolver

    @classmethod
    def from_package(
        cls,
        package: ModelPackage,
        *,
        package_id: str,
    ) -> "ForecastGeoAvailabilityResolver":
        metadata_path = Path(package.run_dir) / "fit_design_metadata.json"
        metadata = read_json(metadata_path)
        if not isinstance(metadata, Mapping) or metadata.get("l_max") is None:
            raise ValueError(
                f"Model package has no l_max in fit_design_metadata.json: {metadata_path}"
            )
        denominator_path = Path(package.run_dir) / "target_denominator_metadata.csv"
        if not denominator_path.exists():
            raise ValueError(
                f"Model package has no target denominator metadata: {denominator_path}"
            )
        return cls(
            package,
            package_id=package_id,
            lmax=int(metadata["l_max"]),
            denominator_resolver=HistoricalDenominatorResolver(
                pd.read_csv(denominator_path)
            ),
        )

    def resolve(
        self,
        *,
        direction: str,
        channel: str,
        campaign_start: date,
        campaign_end: date,
        analog_year: int | None,
        missing_geo_policy: str,
        target: str = "turnover_per_user",
    ) -> ForecastGeoAvailability:
        if campaign_end < campaign_start:
            raise ValueError("campaign_end cannot be before campaign_start")
        required_end = campaign_end + timedelta(days=self.lmax)
        declared = tuple(
            sorted(self.package.supported_geos_for(direction, target, channel))
        )
        ready: list[str] = []
        unavailable: list[UnavailableGeo] = []
        for geo in declared:
            current = campaign_start
            first_unavailable: date | None = None
            while current <= required_end:
                try:
                    self.denominator_resolver.resolve(
                        direction,
                        geo,
                        current,
                        analog_year=analog_year,
                        missing_geo_policy=missing_geo_policy,
                    )
                except ValueError:
                    first_unavailable = current
                    break
                current += timedelta(days=1)
            if first_unavailable is None:
                ready.append(geo)
            else:
                unavailable.append(
                    UnavailableGeo(
                        geo=geo,
                        reason="denominator_unavailable_for_required_horizon",
                        first_unavailable_date=first_unavailable.isoformat(),
                    )
                )
        return ForecastGeoAvailability(
            package_id=self.package_id,
            direction=direction,
            channel=channel,
            target=target,
            campaign_start=campaign_start.isoformat(),
            campaign_end=campaign_end.isoformat(),
            required_start=campaign_start.isoformat(),
            required_end=required_end.isoformat(),
            lmax=self.lmax,
            analog_year=analog_year,
            missing_geo_policy=missing_geo_policy,
            denominator_policy_version=DENOMINATOR_RESOLUTION_POLICY_VERSION,
            availability_policy_version=FORECAST_GEO_AVAILABILITY_POLICY_VERSION,
            declared_geos=declared,
            ready_geos=tuple(ready),
            unavailable_geos=tuple(unavailable),
        )
