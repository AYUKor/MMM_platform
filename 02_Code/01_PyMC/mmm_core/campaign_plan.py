"""Campaign-plan parsing, flighting and model-package validation.

This module owns the input side of campaign forecast and budget optimization:
raw Excel/CSV briefs from business are normalized, converted to daily flighting,
and validated against the selected fitted MMM model package.

It deliberately does not compute media response. Forecast and optimizer will use
these prepared artifacts as their clean input.
"""

from __future__ import annotations

import csv
import hashlib
import math
import re
from bisect import bisect_left
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .io import ensure_dir, project_root, resolve_path, write_json
from .model_package_reader import ModelPackage


class CampaignPlanError(ValueError):
    """Raised when a future campaign brief cannot be prepared safely."""


CAMPAIGN_ROOT = Path("00_Data/00_Future_Campaigns")
VALIDATED_DIR = CAMPAIGN_ROOT / "02_Validated"
FLIGHTING_DIR = CAMPAIGN_ROOT / "03_Flighting"

X5_AGENCY_CHANNEL_MAP = {
    "нац тв": "Нац_ТВ",
    "национальное тв": "Нац_ТВ",
    "рег тв": "Рег_ТВ",
    "региональное тв": "Рег_ТВ",
    "оон": "OOH_Total",
    "ooh": "OOH_Total",
    "радио": "Радио",
    "indoor": "Indoor",
    "indoor (метро)": "Indoor",
    "азс": "Indoor",
    "электрички": "Indoor",
}

COLUMN_ALIASES = {
    "campaign_name": [
        "campaign_name", "campaign", "campaign id", "campaign_id", "название кампании",
        "кампания", "рк", "rk", "name",
    ],
    "creative_name": [
        "creative_name", "creative", "creative id", "creative_id", "креатив", "название креатива",
    ],
    "segment": [
        "segment", "direction", "target_segment", "target direction", "target_direction",
        "направление", "сегмент", "направление рекламы", "рекламируемое направление",
    ],
    "geo": ["geo", "geo_unit", "region", "city", "гео", "регион", "город", "субъект"],
    "channel": [
        "channel", "media_channel", "channel_type", "source", "канал", "канал рекламы",
        "тип канала", "медиа канал", "медиа", "инструмент",
    ],
    "date": ["date", "day", "дата", "день", "дата размещения"],
    "start_date": [
        "start_date", "date_start", "campaign_start", "campaign_data_start", "дата начала",
        "начало", "старт", "начало кампании", "период с",
    ],
    "end_date": [
        "end_date", "date_end", "campaign_end", "campaign_data_end", "дата окончания",
        "конец", "окончание", "финиш", "конец кампании", "период по",
    ],
    "budget_rub": [
        "budget_rub", "budget", "budget (шт)", "spend", "spend_rub", "media_budget",
        "media_budget_rub", "бюджет", "бюджет руб", "бюджет, руб", "бюджет р.",
        "медиа бюджет", "сумма", "стоимость",
    ],
}


def _normalize_name(value: Any) -> str:
    text = str(value or "").strip().lower().replace("ё", "е")
    text = re.sub(r"[\u00a0\s]+", " ", text)
    text = re.sub(r"[^0-9a-zа-я_ ()/.,-]+", "", text)
    return text.strip()


ALIAS_TO_CANONICAL = {
    _normalize_name(alias): canonical
    for canonical, aliases in COLUMN_ALIASES.items()
    for alias in aliases
}


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def _parse_money(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("\u00a0", " ")
    text = text.replace("₽", "").replace("руб.", "").replace("руб", "")
    text = text.replace(" ", "")
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    text = re.sub(r"[^0-9.\-]", "", text)
    if text in {"", ".", "-"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    # Pandas handles Excel-like timestamps and less common local formats if available.
    try:
        import pandas as pd  # type: ignore

        parsed = pd.to_datetime(text, dayfirst=True, errors="coerce")
        if not pd.isna(parsed):
            return parsed.date()
    except Exception:
        pass
    return None


def _safe_id(value: str) -> str:
    text = _normalize_name(value).replace("/", "_").replace(" ", "_")
    text = re.sub(r"[^0-9a-zа-я_\-]+", "", text)
    return text or "campaign"


def _canonical_x5_agency_channel(value: Any) -> str | None:
    normalized = _normalize_name(value)
    if normalized.startswith("диджитал") or normalized.startswith("digital"):
        return "Digital_Performance"
    return X5_AGENCY_CHANNEL_MAP.get(normalized)


def _parse_agency_period(value: Any, default_year: int) -> tuple[date, date] | None:
    if isinstance(value, datetime):
        return value.date(), value.date()
    if isinstance(value, date):
        return value, value
    text = _clean_text(value)
    if not text:
        return None
    timestamp = _parse_date(text)
    if timestamp is not None and not re.search(r"\s[-–—]\s", text):
        return timestamp, timestamp
    match = re.search(
        r"(?P<sd>\d{1,2})\.(?P<sm>\d{1,2})(?:\.(?P<sy>\d{2,4}))?\s*[-–—]\s*"
        r"(?P<ed>\d{1,2})\.(?P<em>\d{1,2})(?:\.(?P<ey>\d{2,4}))?",
        text,
    )
    if match is None:
        return None

    def _year(raw: str | None, fallback: int) -> int:
        if raw is None:
            return fallback
        value = int(raw)
        return value + 2000 if value < 100 else value

    start_year = _year(match.group("sy"), default_year)
    end_year = _year(match.group("ey"), start_year)
    start = date(start_year, int(match.group("sm")), int(match.group("sd")))
    end = date(end_year, int(match.group("em")), int(match.group("ed")))
    if match.group("ey") is None and end < start:
        end = date(start_year + 1, end.month, end.day)
    if end < start:
        return None
    return start, end


def _top_agency_plan_rows(frame: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Extract the first detailed PLAN block and ignore repeated weekly detail."""
    header_idx: int | None = None
    plan_row_idx: int | None = None
    media_col = geo_col = period_col = budget_col = None
    for idx in range(max(len(frame) - 1, 0)):
        row = [_normalize_name(value) for value in frame.iloc[idx].tolist()]
        next_row = [_normalize_name(value) for value in frame.iloc[idx + 1].tolist()]
        if "медиа" not in row or not any("бюджеты тотал" in value for value in row):
            continue
        if "план" not in next_row:
            continue
        header_idx = idx
        plan_row_idx = idx + 1
        media_col = row.index("медиа")
        geo_col = row.index("гео")
        period_col = row.index("период")
        total_budget_col = next(i for i, value in enumerate(row) if "бюджеты тотал" in value)
        budget_candidates = [
            i for i in range(total_budget_col, len(next_row)) if next_row[i] == "план"
        ]
        if not budget_candidates:
            continue
        budget_col = budget_candidates[0]
        break
    if None in {header_idx, plan_row_idx, media_col, geo_col, period_col, budget_col}:
        raise CampaignPlanError("Agency KPI workbook has no detailed PLAN block with total budget")

    rows: list[dict[str, Any]] = []
    total_row_idx: int | None = None
    for idx in range(int(plan_row_idx) + 1, len(frame)):
        values = frame.iloc[idx].tolist()
        normalized = [_normalize_name(value) for value in values]
        if "итого" in normalized:
            total_row_idx = idx
            break
        source_channel = _clean_text(values[int(media_col)])
        source_geo = _clean_text(values[int(geo_col)])
        period = values[int(period_col)]
        budget = _parse_money(values[int(budget_col)])
        if not source_channel and not source_geo and budget is None:
            continue
        if not source_channel or not source_geo or budget is None or budget < 0:
            raise CampaignPlanError(
                f"Invalid row inside first agency PLAN block at Excel row {idx + 1}: "
                f"channel={source_channel!r}, geo={source_geo!r}, budget={budget!r}"
            )
        rows.append(
            {
                "excel_row": idx + 1,
                "source_channel": source_channel,
                "source_geo": source_geo,
                "period": period,
                "plan_budget_rub": float(budget),
            }
        )
    if total_row_idx is None or not rows:
        raise CampaignPlanError("Agency KPI PLAN block is not terminated by a non-empty total row")
    return rows, {
        "header_excel_row": int(header_idx) + 1,
        "plan_header_excel_row": int(plan_row_idx) + 1,
        "total_excel_row": int(total_row_idx) + 1,
        "plan_budget_column_excel": int(budget_col) + 1,
    }


def _agency_sheet_value(frame: Any, label: str) -> str:
    wanted = _normalize_name(label)
    for idx in range(min(len(frame), 8)):
        values = frame.iloc[idx].tolist()
        for col, value in enumerate(values[:-1]):
            if _normalize_name(value).rstrip(":") == wanted.rstrip(":"):
                return _clean_text(values[col + 1])
    return ""


def _package_population_weights(
    package: ModelPackage,
    segment: str,
    channel: str,
    *,
    target: str = "turnover_per_user",
    denominators: Any | None = None,
    future_start: date | None = None,
    future_end: date | None = None,
    analog_year: int | None = None,
    missing_geo_policy: str = "fail",
    max_nearest_gap_days: int = 7,
) -> tuple[dict[str, float], dict[str, Any]]:
    try:
        import pandas as pd  # type: ignore
    except Exception as exc:  # pragma: no cover - runtime env
        raise CampaignPlanError("X5 agency adapter requires pandas") from exc
    supported = package.supported_geos_for(segment, target, channel)
    if not supported:
        return {}
    path = package.run_dir / "target_denominator_metadata.csv"
    if not path.exists():
        raise CampaignPlanError(f"Model package has no target denominator metadata: {path}")
    if denominators is None:
        denominators = pd.read_csv(
            path,
            usecols=["segment", "geo_label", "date", "population_k"],
        )
    segment_denominators = denominators[denominators["segment"].eq(segment)].copy()
    segment_denominators["population_k"] = pd.to_numeric(
        segment_denominators["population_k"], errors="coerce"
    )
    before_coverage = set(str(geo) for geo in supported)
    after_coverage = set(before_coverage)
    if future_start is not None and future_end is not None:
        after_coverage = _denominator_period_eligible_geos(
            segment_denominators,
            before_coverage,
            future_start=future_start,
            future_end=future_end,
            analog_year=analog_year,
            missing_geo_policy=missing_geo_policy,
            max_nearest_gap_days=max_nearest_gap_days,
        )
    population = segment_denominators.groupby("geo_label", dropna=False)["population_k"].median()
    population = population[population.index.astype(str).isin(supported) & population.gt(0)]
    population = population[population.index.astype(str).isin(after_coverage)]
    if population.empty:
        raise CampaignPlanError(
            f"Model package has no positive population weights for segment={segment!r}, channel={channel!r}"
        )
    total = float(population.sum())
    return (
        {str(geo): float(value / total) for geo, value in population.items()},
        {
            "segment": segment,
            "channel": channel,
            "target": target,
            "future_start": future_start.isoformat() if future_start else "",
            "future_end": future_end.isoformat() if future_end else "",
            "analog_year": analog_year,
            "missing_geo_policy": missing_geo_policy,
            "max_nearest_gap_days": max_nearest_gap_days,
            "model_supported_geos_n": len(before_coverage),
            "denominator_eligible_geos_n": len(after_coverage),
            "excluded_geos_n": len(before_coverage - after_coverage),
            "excluded_geos": sorted(before_coverage - after_coverage),
        },
    )


def _date_in_year(value: date, year: int) -> date:
    try:
        return value.replace(year=year)
    except ValueError:
        return value.replace(year=year, day=28)


def _denominator_period_eligible_geos(
    denominators: Any,
    geos: set[str],
    *,
    future_start: date,
    future_end: date,
    analog_year: int | None,
    missing_geo_policy: str,
    max_nearest_gap_days: int,
) -> set[str]:
    """Return geos whose denominator can be resolved for every future date."""
    try:
        import pandas as pd  # type: ignore
    except Exception as exc:  # pragma: no cover - runtime env
        raise CampaignPlanError("Denominator coverage validation requires pandas") from exc
    frame = denominators[denominators["geo_label"].astype(str).isin(geos)].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.date
    frame = frame.dropna(subset=["date"])
    dates_by_geo_year: dict[tuple[str, int], list[date]] = {}
    for (geo, year), sub in frame.groupby(
        [frame["geo_label"].astype(str), frame["date"].map(lambda value: value.year)],
        dropna=False,
    ):
        dates_by_geo_year[(str(geo), int(year))] = sorted(set(sub["date"]))
    available_years: dict[str, list[int]] = defaultdict(list)
    for geo, year in dates_by_geo_year:
        available_years[geo].append(year)
    future_dates: list[date] = []
    current = future_start
    while current <= future_end:
        future_dates.append(current)
        current += timedelta(days=1)

    def _has_near_date(values: list[date], target_date: date) -> bool:
        position = bisect_left(values, target_date)
        candidates = values[max(position - 1, 0) : position + 1]
        return bool(candidates) and min(abs((value - target_date).days) for value in candidates) <= max_nearest_gap_days

    eligible: set[str] = set()
    for geo in geos:
        years = sorted(set(available_years.get(geo, [])))
        if not years:
            continue
        geo_ok = True
        for future_date in future_dates:
            preferred_year = int(analog_year) if analog_year is not None else future_date.year - 1
            candidate_years = [preferred_year]
            if missing_geo_policy == "nearest_available_year_same_geo":
                candidate_years.extend(
                    year for year in sorted(years, key=lambda value: (abs(value - preferred_year), value))
                    if year != preferred_year
                )
            if not any(
                _has_near_date(
                    dates_by_geo_year.get((geo, candidate_year), []),
                    _date_in_year(future_date, candidate_year),
                )
                for candidate_year in candidate_years
            ):
                geo_ok = False
                break
        if geo_ok:
            eligible.add(geo)
    return eligible


def _package_geo_aliases(package: ModelPackage, config: dict[str, Any]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    path = package.run_dir / "source_geo_aliases.csv"
    if path.exists():
        for row in _read_csv(path):
            source = _normalize_name(row.get("source_geo_norm")).upper()
            target = _clean_text(row.get("model_geo_label"))
            if source and target:
                aliases[source] = target
    for source, target in (config.get("geo_aliases") or {}).items():
        aliases[_normalize_name(source).upper()] = _clean_text(target)
    return aliases


def adapt_x5_agency_kpi_workbook(
    path: Path,
    package: ModelPackage,
    adapter_config: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Convert X5 agency KPI workbooks to the canonical campaign-plan schema.

    The adapter reads only the first detailed PLAN block on each ``*_KPI``
    sheet. Repeated weekly blocks and FACT columns are audit context, not a
    future campaign specification.
    """
    try:
        import pandas as pd  # type: ignore
    except Exception as exc:  # pragma: no cover - runtime env
        raise CampaignPlanError("X5 agency adapter requires pandas/openpyxl") from exc
    config = adapter_config or {}
    default_year = int(config.get("campaign_year") or 2026)
    unsupported_policy = str(config.get("unsupported_source_policy") or "fail")
    if unsupported_policy not in {"fail", "report_and_exclude"}:
        raise CampaignPlanError(
            "campaign_adapter.unsupported_source_policy must be fail or report_and_exclude"
        )
    requested_sheets = [str(value) for value in config.get("sheets") or []]
    future_controls = config.get("future_controls") or {}
    analog_year_raw = future_controls.get("analog_year")
    analog_year = int(analog_year_raw) if analog_year_raw is not None else None
    missing_geo_policy = str(
        future_controls.get("missing_geo_policy") or "fail"
    )
    max_nearest_gap_days = int(
        future_controls.get("max_nearest_gap_days") or 7
    )
    workbook = pd.ExcelFile(path)
    sheet_names = requested_sheets or [name for name in workbook.sheet_names if str(name).upper().endswith("_KPI")]
    if not sheet_names:
        raise CampaignPlanError("X5 agency workbook has no *_KPI sheets")

    capability_keys = {
        (str(row.get("segment")), str(row.get("target")), str(row.get("channel")))
        for row in package.capability_rows
        if row.get("allowed_use") in {"primary", "caution", "diagnostic"}
    }
    package_geo_aliases = _package_geo_aliases(package, config)
    denominator_path = package.run_dir / "target_denominator_metadata.csv"
    denominators = pd.read_csv(
        denominator_path,
        usecols=["segment", "geo_label", "date", "population_k"],
    )
    canonical_rows: list[dict[str, Any]] = []
    excluded_rows: list[dict[str, Any]] = []
    sheet_audits: list[dict[str, Any]] = []
    campaign_audits: list[dict[str, Any]] = []
    denominator_coverage_audits: list[dict[str, Any]] = []
    source_total = 0.0
    included_total = 0.0

    for sheet_name in sheet_names:
        frame = pd.read_excel(path, sheet_name=sheet_name, header=None)
        plan_rows, block_audit = _top_agency_plan_rows(frame)
        brand = _agency_sheet_value(frame, "Бренд")
        source_campaign = _agency_sheet_value(frame, "РК") or path.stem
        sheet_upper = str(sheet_name).upper()
        network = "ТС5" if sheet_upper.startswith("ТС5") else "ТСХ" if sheet_upper.startswith("ТСХ") else ""
        if not network:
            raise CampaignPlanError(f"Cannot infer network from agency sheet name: {sheet_name}")
        format_name = "Онлайн" if "достав" in _normalize_name(brand) else str(config.get("default_format") or "")
        if format_name not in {"Онлайн", "Оффлайн"}:
            raise CampaignPlanError(
                f"Cannot infer online/offline segment from brand={brand!r} in sheet={sheet_name!r}"
            )
        segment = f"{network}/{format_name}"
        campaign_name = f"{source_campaign} | {segment}"
        sheet_source_total = 0.0
        sheet_included_total = 0.0
        source_dates: set[date] = set()
        modeled_dates: set[date] = set()
        source_channels: set[str] = set()
        modeled_channels: set[str] = set()
        sheet_excluded: list[dict[str, Any]] = []
        rf_source_rows_n = 0
        expanded_rows_n = 0

        for source_row in plan_rows:
            budget = float(source_row["plan_budget_rub"])
            source_total += budget
            sheet_source_total += budget
            source_channels.add(str(source_row["source_channel"]))
            period = _parse_agency_period(source_row["period"], default_year)
            if period is not None:
                current = period[0]
                while current <= period[1]:
                    source_dates.add(current)
                    current += timedelta(days=1)
            canonical_channel = _canonical_x5_agency_channel(source_row["source_channel"])
            reason = ""
            if period is None:
                reason = "invalid_or_missing_period"
            elif canonical_channel is None:
                reason = "source_channel_not_mapped"
            elif (segment, "turnover_per_user", canonical_channel) not in capability_keys:
                reason = "segment_channel_not_supported_by_model_package"
            if reason:
                excluded = {
                    "sheet": sheet_name,
                    "campaign_name": campaign_name,
                    "segment": segment,
                    **source_row,
                    "canonical_channel": canonical_channel or "",
                    "reason": reason,
                }
                sheet_excluded.append(excluded)
                excluded_rows.append(excluded)
                if unsupported_policy == "fail":
                    raise CampaignPlanError(f"Unsupported agency source row: {excluded}")
                continue
            start, end = period
            modeled_channels.add(str(canonical_channel))
            source_geo = _normalize_name(source_row["source_geo"]).upper()
            channel_geos = package.supported_geos_for(
                segment,
                "turnover_per_user",
                str(canonical_channel),
            )
            canonical_geo_by_norm = {
                _normalize_name(geo).upper(): geo for geo in channel_geos
            }
            output_geos: list[tuple[str, float]] = []
            if source_geo in {"РФ", "РОССИЯ", "RUSSIA"}:
                rf_source_rows_n += 1
                weights, coverage_audit = _package_population_weights(
                    package,
                    segment,
                    str(canonical_channel),
                    denominators=denominators,
                    future_start=start,
                    future_end=end,
                    analog_year=analog_year,
                    missing_geo_policy=missing_geo_policy,
                    max_nearest_gap_days=max_nearest_gap_days,
                )
                coverage_audit["source_sheet"] = sheet_name
                coverage_audit["source_channel"] = source_row["source_channel"]
                denominator_coverage_audits.append(coverage_audit)
                output_geos = sorted(weights.items())
            else:
                canonical_geo = canonical_geo_by_norm.get(source_geo)
                if canonical_geo is None:
                    alias_target = package_geo_aliases.get(source_geo)
                    if alias_target in channel_geos:
                        canonical_geo = alias_target
                if canonical_geo is None:
                    excluded = {
                        "sheet": sheet_name,
                        "campaign_name": campaign_name,
                        "segment": segment,
                        **source_row,
                        "canonical_channel": canonical_channel,
                        "reason": "source_geo_not_supported_by_model_fit",
                    }
                    sheet_excluded.append(excluded)
                    excluded_rows.append(excluded)
                    if unsupported_policy == "fail":
                        raise CampaignPlanError(f"Unsupported agency source row: {excluded}")
                    continue
                denominator_eligible = _denominator_period_eligible_geos(
                    denominators[denominators["segment"].eq(segment)],
                    {canonical_geo},
                    future_start=start,
                    future_end=end,
                    analog_year=analog_year,
                    missing_geo_policy=missing_geo_policy,
                    max_nearest_gap_days=max_nearest_gap_days,
                )
                if canonical_geo not in denominator_eligible:
                    excluded = {
                        "sheet": sheet_name,
                        "campaign_name": campaign_name,
                        "segment": segment,
                        **source_row,
                        "canonical_channel": canonical_channel,
                        "canonical_geo": canonical_geo,
                        "reason": "denominator_period_not_supported",
                    }
                    sheet_excluded.append(excluded)
                    excluded_rows.append(excluded)
                    if unsupported_policy == "fail":
                        raise CampaignPlanError(f"Unsupported agency source row: {excluded}")
                    continue
                output_geos = [(canonical_geo, 1.0)]

            current = start
            while current <= end:
                modeled_dates.add(current)
                current += timedelta(days=1)

            for geo, weight in output_geos:
                allocated = budget * float(weight)
                canonical_rows.append(
                    {
                        "campaign_name": campaign_name,
                        "creative_name": "Не указан в источнике",
                        "segment": segment,
                        "geo": geo,
                        "channel": canonical_channel,
                        "start_date": start.isoformat(),
                        "end_date": end.isoformat(),
                        "budget_rub": allocated,
                    }
                )
                included_total += allocated
                sheet_included_total += allocated
                expanded_rows_n += 1

        campaign_audits.append(
            {
                "campaign_name": campaign_name,
                "source_campaign_name": source_campaign,
                "segment": segment,
                "brand": brand,
                "source_sheet": sheet_name,
                "campaign_start": min(source_dates).isoformat() if source_dates else "",
                "campaign_end": max(source_dates).isoformat() if source_dates else "",
                "active_dates": len(source_dates),
                "model_input_start": min(modeled_dates).isoformat() if modeled_dates else "",
                "model_input_end": max(modeled_dates).isoformat() if modeled_dates else "",
                "model_input_active_dates": len(modeled_dates),
                "uploaded_budget_rub": round(sheet_source_total, 6),
                "model_input_budget_rub": round(sheet_included_total, 6),
                "unmodeled_budget_rub": round(sheet_source_total - sheet_included_total, 6),
                "source_channels": sorted(source_channels),
                "modeled_channels": sorted(modeled_channels),
                "unmodeled_channels": sorted(
                    {str(row.get("source_channel") or "") for row in sheet_excluded}
                ),
                "source_rows_n": len(plan_rows),
                "model_input_rows_n": expanded_rows_n,
                "excluded_source_rows_n": len(sheet_excluded),
            }
        )
        sheet_audits.append(
            {
                "sheet": sheet_name,
                "brand": brand,
                "source_campaign_name": source_campaign,
                "campaign_name": campaign_name,
                "segment": segment,
                "source_plan_rows_n": len(plan_rows),
                "source_plan_budget_rub": round(sheet_source_total, 6),
                "included_budget_rub": round(sheet_included_total, 6),
                "excluded_budget_rub": round(sheet_source_total - sheet_included_total, 6),
                "rf_source_rows_n": rf_source_rows_n,
                "expanded_model_rows_n": expanded_rows_n,
                "block": block_audit,
            }
        )

    if not canonical_rows:
        raise CampaignPlanError("X5 agency adapter produced no model-supported rows")
    reconciliation = source_total - included_total - sum(float(row["plan_budget_rub"]) for row in excluded_rows)
    if abs(reconciliation) > max(1.0, abs(source_total) * 1e-8):
        raise CampaignPlanError(
            "X5 agency adapter budget reconciliation failed: "
            f"source={source_total:.4f}, included={included_total:.4f}, "
            f"excluded={sum(float(row['plan_budget_rub']) for row in excluded_rows):.4f}"
        )
    audit = {
        "adapter": "x5_agency_kpi_v1",
        "source_file": str(path),
        "campaign_year_assumption": default_year,
        "unsupported_source_policy": unsupported_policy,
        "source_plan_budget_rub": round(source_total, 6),
        "model_input_budget_rub": round(included_total, 6),
        "unmodeled_budget_rub": round(source_total - included_total, 6),
        "source_plan_rows_n": sum(int(row["source_plan_rows_n"]) for row in sheet_audits),
        "model_input_rows_n": len(canonical_rows),
        "excluded_source_rows_n": len(excluded_rows),
        "campaigns": campaign_audits,
        "sheets": sheet_audits,
        "excluded_rows": excluded_rows,
        "budget_reconciliation_abs_diff_rub": round(abs(reconciliation), 6),
        "channel_mapping": {
            "Нац ТВ": "Нац_ТВ",
            "Рег ТВ": "Рег_ТВ",
            "ООН": "OOH_Total",
            "Диджитал (OLV/Banner)": "Digital_Performance",
            "Радио": "Радио",
            "Indoor (Метро), АЗС, Электрички": "Indoor",
        },
        "rf_allocation": "target-eligible model geos weighted by population_k from target_denominator_metadata.csv",
        "geo_alias_source": str(package.run_dir / "source_geo_aliases.csv")
        if (package.run_dir / "source_geo_aliases.csv").exists()
        else "campaign_adapter.geo_aliases",
        "denominator_policy": {
            "analog_year": analog_year,
            "missing_geo_policy": missing_geo_policy,
            "max_nearest_gap_days": max_nearest_gap_days,
            "rf_geo_rule": "population-weighted across model and denominator-period eligible geos",
        },
        "denominator_coverage_audits": denominator_coverage_audits,
    }
    return canonical_rows, audit


def build_source_geo_aliases(
    mapping_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Export reviewed direct source-to-model geo aliases into a model package."""
    try:
        import pandas as pd  # type: ignore
    except Exception as exc:  # pragma: no cover - runtime env
        raise CampaignPlanError("Geo alias export requires pandas") from exc
    mapping = pd.read_csv(mapping_path)
    required = {
        "media_geo_norm",
        "action",
        "final_model_geo_label_or_rule",
        "include_in_model_or_distribution",
    }
    missing = sorted(required - set(mapping.columns))
    if missing:
        raise CampaignPlanError(f"Reviewed geo mapping is missing columns: {missing}")
    direct = mapping[
        mapping["include_in_model_or_distribution"].astype(str).str.lower().eq("yes")
        & mapping["action"].astype(str).isin({"keep_exact_geo", "map_to_target_geo"})
    ].copy()
    direct["source_geo_norm"] = direct["media_geo_norm"].map(
        lambda value: _normalize_name(value).upper()
    )
    direct["model_geo_label"] = direct["final_model_geo_label_or_rule"].map(_clean_text)
    direct = direct[
        direct["source_geo_norm"].ne("") & direct["model_geo_label"].ne("")
    ].drop_duplicates("source_geo_norm")
    source_sha = hashlib.sha256(mapping_path.read_bytes()).hexdigest()
    direct["mapping_action"] = direct["action"].astype(str)
    direct["source_file"] = str(mapping_path)
    direct["source_sha256"] = source_sha
    direct["method_version"] = "reviewed_geo_mapping_v1"
    output = direct[
        [
            "source_geo_norm",
            "model_geo_label",
            "mapping_action",
            "source_file",
            "source_sha256",
            "method_version",
        ]
    ].sort_values("source_geo_norm")
    ensure_dir(output_path.parent)
    output.to_csv(output_path, index=False)
    return {
        "output_path": str(output_path),
        "source_path": str(mapping_path),
        "source_sha256": source_sha,
        "aliases_n": int(len(output)),
    }


def build_historical_campaign_support_bounds(
    episodes_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Build segment-level campaign scale bounds from reviewed episode data."""
    try:
        import pandas as pd  # type: ignore
    except Exception as exc:  # pragma: no cover - runtime env
        raise CampaignPlanError("Campaign support export requires pandas") from exc
    episodes = pd.read_csv(episodes_path)
    required = {"segment", "budget_rub", "active_dates"}
    missing = sorted(required - set(episodes.columns))
    if missing:
        raise CampaignPlanError(f"Campaign episode artifact is missing columns: {missing}")
    episodes["budget_rub"] = pd.to_numeric(episodes["budget_rub"], errors="coerce")
    episodes["active_dates"] = pd.to_numeric(episodes["active_dates"], errors="coerce")
    episodes = episodes[
        episodes["budget_rub"].gt(0) & episodes["active_dates"].gt(0)
    ].copy()
    episodes["daily_intensity_rub"] = episodes["budget_rub"] / episodes["active_dates"]

    def _robust_upper(values: Any) -> float:
        values = pd.to_numeric(values, errors="coerce").dropna()
        if values.empty:
            return 0.0
        p95 = float(values.quantile(0.95))
        p99 = float(values.quantile(0.99))
        observed_max = float(values.max())
        if len(values) < 10:
            return p95
        if len(values) < 30:
            return p99
        return max(p99, min(observed_max, 1.5 * p99))

    rows: list[dict[str, Any]] = []
    source_sha = hashlib.sha256(episodes_path.read_bytes()).hexdigest()
    for segment, sub in episodes.groupby("segment", dropna=False):
        row: dict[str, Any] = {
            "segment": str(segment),
            "episodes_n": int(len(sub)),
            "source_file": str(episodes_path),
            "source_sha256": source_sha,
            "method_version": "contiguous_campaign_episode_v1",
        }
        for prefix, column in [
            ("budget", "budget_rub"),
            ("daily_intensity", "daily_intensity_rub"),
            ("active_dates", "active_dates"),
        ]:
            values = pd.to_numeric(sub[column], errors="coerce").dropna()
            row[f"{prefix}_p50"] = float(values.quantile(0.50))
            row[f"{prefix}_p95"] = float(values.quantile(0.95))
            row[f"{prefix}_p99"] = float(values.quantile(0.99))
            row[f"{prefix}_max"] = float(values.max())
            row[f"{prefix}_robust_upper"] = _robust_upper(values)
        rows.append(row)
    ensure_dir(output_path.parent)
    pd.DataFrame(rows).sort_values("segment").to_csv(output_path, index=False)
    return {
        "output_path": str(output_path),
        "source_path": str(episodes_path),
        "source_sha256": source_sha,
        "segments_n": len(rows),
        "episodes_n": int(len(episodes)),
    }


def _read_csv(path: Path) -> list[dict[str, Any]]:
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter=delimiter))


def _read_excel(path: Path, sheet_name: str | int | None = None) -> list[dict[str, Any]]:
    try:
        import pandas as pd  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on runtime env
        raise CampaignPlanError(
            "Reading .xlsx campaign briefs requires pandas/openpyxl in the runtime. "
            "Install/read through the project Python environment or export the brief to CSV."
        ) from exc
    sheet = 0 if sheet_name in {None, ""} else sheet_name
    df = pd.read_excel(path, sheet_name=sheet)
    if isinstance(df, dict):
        first_key = next(iter(df))
        df = df[first_key]
    df = df.where(pd.notnull(df), None)
    return df.to_dict("records")


def read_campaign_brief(path: Path, sheet_name: str | int | None = None) -> list[dict[str, Any]]:
    """Read a campaign brief from CSV or Excel into row dictionaries."""
    if not path.exists():
        raise CampaignPlanError(f"Campaign file does not exist: {path}")
    suffix = path.suffix.lower()
    if suffix in {".csv", ".tsv"}:
        return _read_csv(path)
    if suffix in {".xlsx", ".xls"}:
        return _read_excel(path, sheet_name=sheet_name)
    raise CampaignPlanError(f"Unsupported campaign file extension: {path.suffix}. Use .xlsx, .xls, .csv or .tsv.")


def _canonicalize_row(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    extras: dict[str, Any] = {}
    for key, value in raw.items():
        canonical = ALIAS_TO_CANONICAL.get(_normalize_name(key))
        if canonical and canonical not in out:
            out[canonical] = value
        else:
            extras[str(key)] = value
    out["_extra_columns"] = extras
    return out


@dataclass(frozen=True)
class CampaignPrepareResult:
    """Paths and summary for prepared campaign inputs."""

    campaign_file: str
    normalized_path: str
    flighting_path: str
    validation_path: str
    issues_path: str | None
    card_path: str
    summary: dict[str, Any]


def normalize_campaign_rows(raw_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Normalize business campaign rows to a standard schema."""
    normalized: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for idx, raw in enumerate(raw_rows, start=1):
        row = _canonicalize_row(raw)
        campaign_name = _clean_text(row.get("campaign_name")) or "unknown_campaign"
        creative_name = _clean_text(row.get("creative_name"))
        segment = _clean_text(row.get("segment"))
        geo = _clean_text(row.get("geo"))
        channel = _clean_text(row.get("channel"))
        budget = _parse_money(row.get("budget_rub"))
        dt = _parse_date(row.get("date"))
        start = _parse_date(row.get("start_date"))
        end = _parse_date(row.get("end_date"))

        row_issues = []
        if not segment:
            row_issues.append("missing_segment")
        if not geo:
            row_issues.append("missing_geo")
        if not channel:
            row_issues.append("missing_channel")
        if budget is None:
            row_issues.append("missing_or_invalid_budget")
        elif budget < 0:
            row_issues.append("negative_budget")
        if dt is None and (start is None or end is None):
            row_issues.append("missing_date_or_start_end")
        if start is not None and end is not None and end < start:
            row_issues.append("end_before_start")

        if row_issues:
            issues.append({
                "source_row_id": idx,
                "issue": "|".join(row_issues),
                "raw_columns": ";".join(str(k) for k in raw.keys()),
            })
            continue

        source_format = "daily" if dt is not None else "interval"
        normalized.append({
            "source_row_id": idx,
            "campaign_name": campaign_name,
            "creative_name": creative_name,
            "segment": segment,
            "geo": geo,
            "channel": channel,
            "date": dt.isoformat() if dt else "",
            "start_date": start.isoformat() if start else "",
            "end_date": end.isoformat() if end else "",
            "budget_rub": float(budget or 0.0),
            "source_format": source_format,
        })
    if not normalized:
        raise CampaignPlanError("Campaign brief has no valid rows after normalization. See parse issues.")
    return normalized, issues


def build_daily_flighting(normalized_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert normalized rows to daily campaign flighting."""
    daily_rows: list[dict[str, Any]] = []
    for row in normalized_rows:
        if row["source_format"] == "daily":
            daily_rows.append({
                **{k: row[k] for k in ["campaign_name", "creative_name", "segment", "geo", "channel"]},
                "date": row["date"],
                "budget_rub": float(row["budget_rub"]),
                "flighting_source": "source_daily",
                "source_row_id": row["source_row_id"],
                "source_start_date": row["date"],
                "source_end_date": row["date"],
            })
            continue
        start = _parse_date(row["start_date"])
        end = _parse_date(row["end_date"])
        if start is None or end is None or end < start:
            raise CampaignPlanError(f"Invalid interval after normalization for source row {row['source_row_id']}")
        n_days = (end - start).days + 1
        daily_budget = float(row["budget_rub"]) / n_days
        current = start
        while current <= end:
            daily_rows.append({
                **{k: row[k] for k in ["campaign_name", "creative_name", "segment", "geo", "channel"]},
                "date": current.isoformat(),
                "budget_rub": daily_budget,
                "flighting_source": "even_split_from_interval",
                "source_row_id": row["source_row_id"],
                "source_start_date": start.isoformat(),
                "source_end_date": end.isoformat(),
            })
            current += timedelta(days=1)
    return daily_rows


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    ensure_dir(path.parent)
    if fieldnames is None:
        keys: list[str] = []
        for row in rows:
            for key in row.keys():
                if key not in keys:
                    keys.append(key)
        fieldnames = keys
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def _campaign_totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "rows_n": len(rows),
        "total_budget_rub": round(sum(float(r.get("budget_rub") or 0.0) for r in rows), 6),
        "segments": sorted({str(r.get("segment", "")) for r in rows if r.get("segment")}),
        "channels": sorted({str(r.get("channel", "")) for r in rows if r.get("channel")}),
        "geos_n": len({str(r.get("geo", "")) for r in rows if r.get("geo")}),
        "min_date": min((r.get("date") or r.get("start_date") for r in rows if r.get("date") or r.get("start_date")), default=""),
        "max_date": max((r.get("date") or r.get("end_date") for r in rows if r.get("date") or r.get("end_date")), default=""),
    }


def _raw_budget_summary(raw_rows: list[dict[str, Any]]) -> dict[str, Any]:
    parsed_values: list[float] = []
    invalid_rows = 0
    for raw in raw_rows:
        canonical = _canonicalize_row(raw)
        budget = _parse_money(canonical.get("budget_rub"))
        if budget is None or budget < 0:
            invalid_rows += 1
            continue
        parsed_values.append(float(budget))
    return {
        "rows_n": len(raw_rows),
        "budget_rows_parsed_n": len(parsed_values),
        "budget_rows_invalid_n": invalid_rows,
        "total_budget_rub": round(sum(parsed_values), 6),
    }


def _targets_from_config(config: dict[str, Any], package: ModelPackage) -> list[str]:
    targets = (
        (config.get("forecast") or {}).get("targets")
        or (config.get("optimizer") or {}).get("targets")
        or (config.get("objective") or {}).get("targets")
        or package.targets
    )
    return [str(t) for t in targets]


def validate_campaign_against_package(
    package: ModelPackage,
    normalized_rows: list[dict[str, Any]],
    targets: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Validate campaign segment/channel/target requests against model capabilities."""
    spend_by_key: dict[tuple[str, str, str, str], float] = defaultdict(float)
    for row in normalized_rows:
        spend_by_key[(row["campaign_name"], row["segment"], row["geo"], row["channel"])] += float(row["budget_rub"])

    capability_by_key = {
        (row.get("segment"), row.get("target"), row.get("channel")): row
        for row in package.capability_rows
        if row.get("allowed_use") in {"primary", "caution", "diagnostic"}
    }

    validation_rows: list[dict[str, Any]] = []
    for (campaign_name, segment, geo, channel), budget in sorted(spend_by_key.items()):
        for target in targets:
            cap = capability_by_key.get((segment, target, channel))
            supported_geos = package.supported_geos_for(segment, target, channel) if cap is not None else set()
            geo_supported = geo in supported_geos
            supported = cap is not None and geo_supported
            if cap is None:
                reason = "segment_target_channel_not_supported_by_selected_model_package"
            elif not supported_geos:
                reason = "historical_geo_support_metadata_missing"
            elif not geo_supported:
                reason = "geo_not_supported_by_selected_model_fit"
            else:
                reason = cap.get("allowed_use_reason") or "supported"
            validation_rows.append({
                "campaign_name": campaign_name,
                "segment": segment,
                "geo": geo,
                "channel": channel,
                "target": target,
                "plan_budget_rub": round(budget, 6),
                "supported_by_model": supported,
                "geo_supported_by_model": geo_supported,
                "allowed_use": cap.get("allowed_use") if cap else "unsupported",
                "risk_level": cap.get("risk_level") if cap else "unavailable",
                "forecast_use": cap.get("forecast_use") if cap else "not_ready",
                "optimizer_use": cap.get("optimizer_use") if cap else "not_ready",
                "objective_role": cap.get("objective_role") if cap else "forbidden",
                "fit_key": cap.get("fit_key") if cap else "",
                "channel_reliability_flags": cap.get("channel_reliability_flags") if cap else "",
                "gate_reason_codes": cap.get("gate_reason_codes") if cap else "UNSUPPORTED_MODEL_CELL",
                "reason": reason,
            })

    counts = Counter(row["allowed_use"] for row in validation_rows)
    summary = {
        "validation_rows_n": len(validation_rows),
        "supported_rows_n": sum(1 for row in validation_rows if row["supported_by_model"]),
        "unsupported_rows_n": sum(1 for row in validation_rows if not row["supported_by_model"]),
        "allowed_use_counts": dict(counts),
        "risky_supported_rows_n": sum(
            1
            for row in validation_rows
            if row["supported_by_model"] and (row["allowed_use"] != "primary" or row["risk_level"] != "low")
        ),
    }
    return validation_rows, summary


def prepare_campaign_from_config(
    config: dict[str, Any],
    config_path: Path,
    package: ModelPackage,
    output_dir: Path,
    *,
    purpose: str,
) -> CampaignPrepareResult:
    """Read, normalize, flight and validate a campaign brief from workflow config."""
    paths = config.get("paths") or {}
    input_dir_value = paths.get("campaign_input_dir")
    campaign_file_value = paths.get("campaign_file")
    campaign_brief_value = paths.get("campaign_brief")
    sheet_name = paths.get("campaign_sheet")

    campaign_path: Path | None = None
    if input_dir_value and campaign_file_value:
        input_dir = resolve_path(input_dir_value, base_dir=config_path.parent)
        campaign_path = input_dir / str(campaign_file_value)
    elif campaign_brief_value:
        campaign_path = resolve_path(campaign_brief_value, base_dir=config_path.parent)
    if campaign_path is None:
        raise CampaignPlanError(
            "Campaign file is required. Set paths.campaign_input_dir + paths.campaign_file "
            "or legacy paths.campaign_brief in the config."
        )

    run_id = str(config.get("run_id") or campaign_path.stem)
    stem = _safe_id(run_id)
    validated_dir = ensure_dir(project_root() / VALIDATED_DIR)
    flighting_dir = ensure_dir(project_root() / FLIGHTING_DIR)
    output_dir = ensure_dir(output_dir)

    adapter_config = dict(config.get("campaign_adapter") or {})
    adapter_config["future_controls"] = dict(config.get("future_controls") or {})
    adapter_name = str(adapter_config.get("name") or "").strip()
    adapter_audit: dict[str, Any] | None = None
    adapter_audit_path: Path | None = None
    if adapter_name:
        if adapter_name != "x5_agency_kpi_v1":
            raise CampaignPlanError(f"Unsupported campaign adapter: {adapter_name}")
        raw_rows, adapter_audit = adapt_x5_agency_kpi_workbook(
            campaign_path,
            package,
            adapter_config,
        )
        adapter_audit_path = output_dir / f"{stem}_source_adapter_audit.json"
        write_json(adapter_audit_path, adapter_audit)
    else:
        raw_rows = read_campaign_brief(campaign_path, sheet_name=sheet_name)
    raw_budget = _raw_budget_summary(raw_rows)
    normalized_rows, issues = normalize_campaign_rows(raw_rows)
    daily_rows = build_daily_flighting(normalized_rows)

    input_total = sum(float(r["budget_rub"]) for r in normalized_rows)
    daily_total = sum(float(r["budget_rub"]) for r in daily_rows)
    strict_cfg = config.get("validation") or {}
    fail_on_parse_issues = bool(strict_cfg.get("fail_on_parse_issues", True))
    fail_on_unsupported = bool(strict_cfg.get("fail_on_unsupported", True))

    normalized_path = validated_dir / f"{stem}_campaign_plan_normalized.csv"
    flighting_path = flighting_dir / f"{stem}_campaign_flighting_daily.csv"
    validation_path = output_dir / f"{stem}_campaign_model_validation.csv"
    issues_path = output_dir / f"{stem}_campaign_parse_issues.csv" if issues else None
    card_path = output_dir / f"{stem}_campaign_prepare_card.json"

    if issues_path is not None:
        _write_csv(issues_path, issues)
    if issues and fail_on_parse_issues:
        raise CampaignPlanError(
            f"Campaign brief contains {len(issues)} invalid row(s); fail-closed validation stopped the run. "
            f"See {issues_path}"
        )

    raw_total = float(raw_budget["total_budget_rub"])
    if abs(raw_total - input_total) > max(1.0, abs(raw_total) * 1e-8):
        raise CampaignPlanError(
            f"Raw-to-normalized budget reconciliation failed: raw={raw_total:.4f}, normalized={input_total:.4f}"
        )
    if abs(input_total - daily_total) > max(1.0, abs(input_total) * 1e-8):
        raise CampaignPlanError(
            f"Budget reconciliation failed: normalized={input_total:.4f}, daily={daily_total:.4f}"
        )

    targets = _targets_from_config(config, package)
    validation_rows, validation_summary = validate_campaign_against_package(package, normalized_rows, targets)

    _write_csv(normalized_path, normalized_rows)
    _write_csv(flighting_path, daily_rows)
    _write_csv(validation_path, validation_rows)

    summary = {
        "purpose": purpose,
        "run_id": run_id,
        "campaign_file": str(campaign_path),
        "campaign_sheet": sheet_name,
        "campaign_adapter": adapter_name or None,
        "source_adapter_audit": adapter_audit,
        "raw_rows_n": len(raw_rows),
        "raw_budget": raw_budget,
        "parse_issues_n": len(issues),
        "normalized": _campaign_totals(normalized_rows),
        "daily_flighting": _campaign_totals(daily_rows),
        "budget_reconciliation_abs_diff": round(abs(input_total - daily_total), 6),
        "raw_to_normalized_budget_abs_diff": round(abs(raw_total - input_total), 6),
        "fail_on_parse_issues": fail_on_parse_issues,
        "fail_on_unsupported": fail_on_unsupported,
        "targets": targets,
        "model_package": package.summary(),
        "validation": validation_summary,
        "outputs": {
            "normalized_path": str(normalized_path),
            "flighting_path": str(flighting_path),
            "validation_path": str(validation_path),
            "issues_path": str(issues_path) if issues_path else None,
            "card_path": str(card_path),
            "source_adapter_audit_path": str(adapter_audit_path) if adapter_audit_path else None,
        },
    }
    write_json(card_path, summary)
    if validation_summary["unsupported_rows_n"] > 0 and fail_on_unsupported:
        raise CampaignPlanError(
            f"Campaign contains {validation_summary['unsupported_rows_n']} unsupported model row(s); "
            f"fail-closed validation stopped the run. See {validation_path}"
        )
    return CampaignPrepareResult(
        campaign_file=str(campaign_path),
        normalized_path=str(normalized_path),
        flighting_path=str(flighting_path),
        validation_path=str(validation_path),
        issues_path=str(issues_path) if issues_path else None,
        card_path=str(card_path),
        summary=summary,
    )
