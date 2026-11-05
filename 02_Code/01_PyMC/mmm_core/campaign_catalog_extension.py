"""Package extension ``campaign_catalog_v1``: the past-campaign catalog served by the web portal.

The catalog itself is computed on the MMM side by ``09_weekly_joint_campaign_catalog.py`` (counterfactual per
campaign, leave-one-out, posterior draws). This module only turns its finished output into three immutable files
next to a registered model package, so the portal shows exactly the catalog numbers and never recomputes them:

    package_artifacts/<package_id>/campaign_catalog_v1/
        campaign_catalog_v1.json           every campaign with the fields of the catalog card (portal data)
        campaign_catalog_v1.xlsx           the whole catalog for download: 3 sheets, values only (no formulas)
        campaign_catalog_v1.metadata.json  package binding (package_id + fingerprint), file hashes, checks

The portal reads the metadata, checks that it is bound to the active package and that both files still have the
recorded SHA-256, and only then serves them (``04_Web_app/services/campaign_catalog.py``).

Build (read-only for the catalog and the package folders; the output folder must not exist):

    python -I -m mmm_core.campaign_catalog_extension \\
        --catalog-dir GROUP/catalog_real_production_v13_tier_c15_lam10_tail7an \\
        --package-dir GROUP/package_zanoza_v13_20261105_v3 \\
        --package-id pkg_d1e370330f7b153f_ca7ff4cf62212d8c \\
        --catalog-version tail7an --out-dir OUT/campaign_catalog_v1
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ARTIFACT_VERSION = "campaign_catalog_v1"
DATA_SCHEMA_VERSION = "1.0.0"
METADATA_SCHEMA_VERSION = "1.0.0"
DATA_FILENAME = "campaign_catalog_v1.json"
WORKBOOK_FILENAME = "campaign_catalog_v1.xlsx"
METADATA_FILENAME = "campaign_catalog_v1.metadata.json"
EXTENSION_FILES = (DATA_FILENAME, WORKBOOK_FILENAME, METADATA_FILENAME)
PACKAGE_ID_RE = re.compile(r"^pkg_[0-9a-f]{16}_[0-9a-f]{16}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
LONG_DAYS = 120
DIRECTIONS = ("ТС5/Онлайн", "ТС5/Оффлайн", "ТСХ/Онлайн", "ТСХ/Оффлайн")
# Excel column order of the catalog (decision of 28.10): id, portal name, short name.
CHANNELS = (
    ("Digital_Performance", "Цифровая реклама", "Цифровая"),
    ("OOH_Total", "Наружная реклама", "Наружная"),
    ("Indoor", "Indoor", "Indoor"),
    ("Радио", "Радио", "Радио"),
    ("Нац_ТВ", "Национальное ТВ", "Нац. ТВ"),
    ("Рег_ТВ", "Региональное ТВ", "Рег. ТВ"),
)
CHANNEL_DISPLAY = {channel_id: display for channel_id, display, _ in CHANNELS}
CHANNEL_ORDER = {channel_id: index for index, (channel_id, _, _) in enumerate(CHANNELS)}
SOURCE_CHANNEL_KEYS = {
    "dig": "Digital_Performance",
    "ooh": "OOH_Total",
    "ind": "Indoor",
    "rad": "Радио",
    "ntv": "Нац_ТВ",
    "rtv": "Рег_ТВ",
}
DURATION_SHORT = "up_to_120_days"
DURATION_LONG = "120_days_and_longer"
EFFECT_FIELDS = (
    "turnover_increment_rub",
    "orders_per_1000_buyers",
    "avg_basket_increment_rub",
    "roas",
)
ROAS_LEVEL_LABEL = "уровень ROAS по отрасли"
DA_NANG = timezone(timedelta(hours=7))
NOTES = (
    {
        "code": "roas_industry_level",
        "display_text": (
            "Уровень ROAS по отраслевому ориентиру. Данные сами по себе держат около 10–30% этого уровня. "
            "Разница между городами и неделями из данных."
        ),
    },
    {
        "code": "campaign_effect_leave_one_out",
        "display_text": (
            "Эффект кампании — то, что потеряли бы без неё, если остальные кампании оставить. "
            "Поэтому ROAS кампании ниже ROAS всего канала."
        ),
    },
    {
        "code": "range_p10_p90",
        "display_text": "«от» и «до» — 10-й и 90-й процентили оценки.",
    },
    {
        "code": "reliability_flag",
        "display_text": "Надёжность: 1 — оценке можно доверять, 0 — смотреть с осторожностью.",
    },
    {
        "code": "overlaps",
        "display_text": "Пересечения: сколько других кампаний того же направления шли в те же дни и города.",
    },
)
NOT_COMPUTED_TEXT = "Нет оценки: деньги кампании пришлись на города или недели, которых нет в модели."


class CampaignCatalogExtensionError(ValueError):
    """Raised when the catalog source, the package binding or a written file is inconsistent."""


# ------------------------------------------------------------------------------------------------ small helpers


def sha256_file(path: Path) -> str:
    """SHA-256 of a file, streamed."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CampaignCatalogExtensionError(f"{field} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise CampaignCatalogExtensionError(f"{field} must be finite")
    return parsed


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise CampaignCatalogExtensionError(f"{field} must be a trimmed non-empty string")
    return value


def _iso_date(value: Any, field: str) -> date:
    if not isinstance(value, str):
        raise CampaignCatalogExtensionError(f"{field} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CampaignCatalogExtensionError(f"{field} is not an ISO date") from exc


def _close(left: float, right: float, *, absolute: float, relative: float = 1e-9) -> bool:
    return abs(left - right) <= max(absolute, relative * max(abs(left), abs(right)))


def _quantiles(values: Any, field: str) -> dict[str, float] | None:
    """(p10, p50, p90) of the source -> {estimate, low, high}; None when any value is missing."""

    if values is None:
        return None
    if not isinstance(values, (list, tuple)) or len(values) != 3:
        raise CampaignCatalogExtensionError(f"{field} must hold (p10, p50, p90)")
    parsed: list[float] = []
    for value in values:
        if value is None:
            return None
        number = float(value)
        if math.isnan(number):
            return None
        if not math.isfinite(number):
            raise CampaignCatalogExtensionError(f"{field} must be finite")
        parsed.append(number)
    low, estimate, high = parsed
    return {"estimate": estimate, "low": low, "high": high}


def _write_bytes_new(path: Path, payload: bytes) -> None:
    """Write a new file; never replace an existing one (new versions only)."""

    if path.exists():
        raise FileExistsError(f"Refusing to overwrite an existing file: {path.name}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(payload)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=False, allow_nan=False) + "\n").encode("utf-8")


# ------------------------------------------------------------------------------------------------ source catalog


@dataclass(frozen=True)
class SourceCatalog:
    """Finished output of 09_weekly_joint_campaign_catalog.py (read-only)."""

    catalog_dir: Path
    results: tuple[Mapping[str, Any], ...]
    meta: Mapping[str, Any]
    checks: Mapping[str, Any]
    numbers_rows: tuple[Mapping[str, str], ...]
    roas_check_rows: tuple[Mapping[str, str], ...]
    source_files: tuple[dict[str, Any], ...]


def _read_csv(path: Path) -> tuple[dict[str, str], ...]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return tuple(dict(row) for row in csv.DictReader(handle))


def load_source_catalog(catalog_dir: Path) -> SourceCatalog:
    """Read catalog_results.json (NaN tokens allowed), the numbers CSV and the run checks."""

    root = catalog_dir.expanduser().resolve()
    names = {
        "catalog_results": "catalog_results.json",
        "catalog_numbers": "catalog_numbers.csv",
        "catalog_by_channel": "catalog_by_channel.csv",
        "checks": "checks.json",
        "check_catalog_vs_model_roas": "check_catalog_vs_model_roas.csv",
    }
    missing = [name for name in names.values() if not (root / name).is_file()]
    if missing:
        raise CampaignCatalogExtensionError(f"Catalog folder lacks {missing}")
    raw = json.loads((root / names["catalog_results"]).read_text(encoding="utf-8"))
    results = raw.get("results")
    if not isinstance(results, Mapping) or not results:
        raise CampaignCatalogExtensionError("catalog_results.json has no results")
    run_checks = json.loads((root / names["checks"]).read_text(encoding="utf-8"))
    meta = raw.get("meta") or run_checks.get("meta") or {}
    checks = raw.get("checks") or run_checks.get("checks") or {}
    source_files = tuple(
        {
            "role": role,
            "file_name": file_name,
            "sha256": sha256_file(root / file_name),
            "size_bytes": (root / file_name).stat().st_size,
        }
        for role, file_name in names.items()
    )
    return SourceCatalog(
        catalog_dir=root,
        results=tuple(results[key] for key in sorted(results, key=lambda item: int(item))),
        meta=meta,
        checks=checks,
        numbers_rows=_read_csv(root / names["catalog_numbers"]),
        roas_check_rows=_read_csv(root / names["check_catalog_vs_model_roas"]),
        source_files=source_files,
    )


def _main_channel(channels: Sequence[Mapping[str, Any]]) -> str:
    return min(
        channels,
        key=lambda row: (-float(row["budget_rub"]), CHANNEL_ORDER[str(row["channel_id"])]),
    )["channel_id"]


def normalize_campaign(source: Mapping[str, Any]) -> dict[str, Any]:
    """One catalog_results.json row -> the card record of the portal and the Excel."""

    number = source.get("id")
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise CampaignCatalogExtensionError("Campaign id must be a positive integer")
    field = f"campaign {number}"
    card = source.get("card")
    if not isinstance(card, Mapping):
        raise CampaignCatalogExtensionError(f"{field} has no card")
    start = _iso_date(card.get("start"), f"{field}.start")
    end = _iso_date(card.get("end"), f"{field}.end")
    days = card.get("days")
    if days != (end - start).days + 1:
        raise CampaignCatalogExtensionError(f"{field} days differ from its dates")
    directions = list(card.get("dirs") or [])
    if not directions or any(item not in DIRECTIONS for item in directions):
        raise CampaignCatalogExtensionError(f"{field} has unknown directions {directions}")
    channels: list[dict[str, Any]] = []
    for raw in card.get("channels") or []:
        channel_id = SOURCE_CHANNEL_KEYS.get(str(raw.get("key")))
        if channel_id is None or raw.get("name") != CHANNEL_DISPLAY[channel_id]:
            raise CampaignCatalogExtensionError(f"{field} has an unknown channel {raw!r}")
        channels.append(
            {
                "channel_id": channel_id,
                "display_name": CHANNEL_DISPLAY[channel_id],
                "budget_rub": _finite(raw.get("budget"), f"{field}.channel.budget"),
                "nationwide": bool(raw.get("federal")),
            }
        )
    if not channels:
        raise CampaignCatalogExtensionError(f"{field} has no channels")
    channels.sort(key=lambda row: CHANNEL_ORDER[row["channel_id"]])
    budget = _finite(source.get("budget"), f"{field}.budget")
    if not _close(budget, _finite(card.get("budget"), f"{field}.card.budget"), absolute=0.01):
        raise CampaignCatalogExtensionError(f"{field} budget differs from its card")
    modeled = bool(source.get("modeled"))
    turnover = _quantiles(source.get("turnover"), f"{field}.turnover") if modeled else None
    if modeled and turnover is None:
        raise CampaignCatalogExtensionError(f"{field} is modeled but has no turnover effect")
    roas = _quantiles(source.get("roas"), f"{field}.roas") if modeled else None
    record = {
        "number": number,
        "name": _text(source.get("name"), f"{field}.name"),
        "directions": directions,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "days_n": int(days),
        "duration_group": DURATION_LONG if int(days) >= LONG_DAYS else DURATION_SHORT,
        "budget_rub": budget,
        "channels": channels,
        "main_channel_id": _main_channel(channels),
        "cities": [str(city) for city in card.get("cities") or []],
        "nationwide_channels": [str(name) for name in card.get("federal") or []],
        "status": "computed" if modeled else "not_computed",
        "status_display_text": None if modeled else NOT_COMPUTED_TEXT,
        "turnover_increment_rub": turnover,
        "orders_per_1000_buyers": _quantiles(source.get("orders1000"), f"{field}.orders1000") if modeled else None,
        "avg_basket_increment_rub": _quantiles(source.get("basket"), f"{field}.basket") if modeled else None,
        "roas": roas,
        "overlaps_n": int(source.get("overlap") or 0),
        "reliable": int(source.get("flag") or 0),
    }
    validate_campaign_record(record)
    return record


# ------------------------------------------------------------------------------------------------ data contract


_RECORD_KEYS = (
    "number",
    "name",
    "directions",
    "start_date",
    "end_date",
    "days_n",
    "duration_group",
    "budget_rub",
    "channels",
    "main_channel_id",
    "cities",
    "nationwide_channels",
    "status",
    "status_display_text",
    "turnover_increment_rub",
    "orders_per_1000_buyers",
    "avg_basket_increment_rub",
    "roas",
    "overlaps_n",
    "reliable",
)
_CHANNEL_KEYS = ("channel_id", "display_name", "budget_rub", "nationwide")
_RANGE_KEYS = ("estimate", "low", "high")


def _validate_range(value: Any, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping) or tuple(value) != _RANGE_KEYS:
        raise CampaignCatalogExtensionError(f"{field} must hold estimate, low, high")
    low = _finite(value["low"], f"{field}.low")
    estimate = _finite(value["estimate"], f"{field}.estimate")
    high = _finite(value["high"], f"{field}.high")
    tolerance = 1e-9 * max(1.0, abs(low), abs(high))
    if not (low <= estimate + tolerance and estimate <= high + tolerance):
        raise CampaignCatalogExtensionError(f"{field} must satisfy low <= estimate <= high")


def validate_campaign_record(record: Mapping[str, Any]) -> None:
    """Semantic checks of one card record (shared by the builder and the portal service)."""

    if tuple(record) != _RECORD_KEYS:
        raise CampaignCatalogExtensionError("Campaign record keys differ from campaign_catalog_v1")
    number = record["number"]
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise CampaignCatalogExtensionError("number must be a positive integer")
    field = f"campaign {number}"
    _text(record["name"], f"{field}.name")
    directions = record["directions"]
    if (
        not isinstance(directions, list)
        or not directions
        or len(set(directions)) != len(directions)
        or any(item not in DIRECTIONS for item in directions)
    ):
        raise CampaignCatalogExtensionError(f"{field}.directions are invalid")
    start = _iso_date(record["start_date"], f"{field}.start_date")
    end = _iso_date(record["end_date"], f"{field}.end_date")
    if end < start or record["days_n"] != (end - start).days + 1:
        raise CampaignCatalogExtensionError(f"{field} dates and days differ")
    expected_group = DURATION_LONG if record["days_n"] >= LONG_DAYS else DURATION_SHORT
    if record["duration_group"] != expected_group:
        raise CampaignCatalogExtensionError(f"{field}.duration_group differs from days_n")
    budget = _finite(record["budget_rub"], f"{field}.budget_rub")
    if budget < 0:
        raise CampaignCatalogExtensionError(f"{field}.budget_rub must be non-negative")
    channels = record["channels"]
    if not isinstance(channels, list) or not channels:
        raise CampaignCatalogExtensionError(f"{field}.channels must be a non-empty list")
    seen: set[str] = set()
    for channel in channels:
        if not isinstance(channel, Mapping) or tuple(channel) != _CHANNEL_KEYS:
            raise CampaignCatalogExtensionError(f"{field}.channels row keys differ")
        channel_id = channel["channel_id"]
        if channel_id not in CHANNEL_DISPLAY or channel_id in seen:
            raise CampaignCatalogExtensionError(f"{field} has an unknown or repeated channel")
        seen.add(channel_id)
        if channel["display_name"] != CHANNEL_DISPLAY[channel_id]:
            raise CampaignCatalogExtensionError(f"{field} channel display name differs")
        if _finite(channel["budget_rub"], f"{field}.channel.budget_rub") < 0:
            raise CampaignCatalogExtensionError(f"{field} channel budget must be non-negative")
        if not isinstance(channel["nationwide"], bool):
            raise CampaignCatalogExtensionError(f"{field} channel nationwide must be boolean")
    if [row["channel_id"] for row in channels] != sorted(seen, key=CHANNEL_ORDER.__getitem__):
        raise CampaignCatalogExtensionError(f"{field}.channels must follow the catalog channel order")
    channel_sum = math.fsum(float(row["budget_rub"]) for row in channels)
    if not _close(channel_sum, budget, absolute=max(0.01, 1e-9 * budget)):
        raise CampaignCatalogExtensionError(f"{field} channel budgets do not add up to the budget")
    if record["main_channel_id"] != _main_channel(channels):
        raise CampaignCatalogExtensionError(f"{field}.main_channel_id is not the largest channel")
    for list_field in ("cities", "nationwide_channels"):
        values = record[list_field]
        if not isinstance(values, list) or any(not isinstance(item, str) or not item.strip() for item in values):
            raise CampaignCatalogExtensionError(f"{field}.{list_field} must be a list of names")
        if len(set(values)) != len(values):
            raise CampaignCatalogExtensionError(f"{field}.{list_field} has repeated names")
    expected_nationwide = [row["display_name"] for row in channels if row["nationwide"]]
    if record["nationwide_channels"] != expected_nationwide:
        raise CampaignCatalogExtensionError(f"{field}.nationwide_channels differ from its channels")
    status = record["status"]
    if status not in {"computed", "not_computed"}:
        raise CampaignCatalogExtensionError(f"{field}.status is invalid")
    for effect in EFFECT_FIELDS:
        _validate_range(record[effect], f"{field}.{effect}")
    if status == "computed":
        if record["status_display_text"] is not None or record["turnover_increment_rub"] is None:
            raise CampaignCatalogExtensionError(f"{field} computed campaign must carry its turnover effect")
        turnover, roas = record["turnover_increment_rub"], record["roas"]
        if budget > 0:
            if roas is None:
                raise CampaignCatalogExtensionError(f"{field} computed campaign must carry ROAS")
            for key in _RANGE_KEYS:
                if not _close(float(roas[key]), float(turnover[key]) / budget, absolute=1e-9):
                    raise CampaignCatalogExtensionError(f"{field} ROAS differs from turnover / budget")
        elif roas is not None:
            raise CampaignCatalogExtensionError(f"{field} has ROAS without budget")
    else:
        if any(record[effect] is not None for effect in EFFECT_FIELDS):
            raise CampaignCatalogExtensionError(f"{field} not computed campaign must not carry effects")
        _text(record["status_display_text"], f"{field}.status_display_text")
        if record["reliable"] != 0:
            raise CampaignCatalogExtensionError(f"{field} not computed campaign cannot be reliable")
    overlaps = record["overlaps_n"]
    if isinstance(overlaps, bool) or not isinstance(overlaps, int) or overlaps < 0:
        raise CampaignCatalogExtensionError(f"{field}.overlaps_n must be a non-negative integer")
    if record["reliable"] not in (0, 1) or isinstance(record["reliable"], bool):
        raise CampaignCatalogExtensionError(f"{field}.reliable must be 0 or 1")


def catalog_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Catalog totals; weighted ROAS = sum of turnover estimates / sum of budgets of computed campaigns."""

    computed = [row for row in records if row["status"] == "computed"]
    computed_budget = math.fsum(float(row["budget_rub"]) for row in computed)
    turnover = math.fsum(float(row["turnover_increment_rub"]["estimate"]) for row in computed)
    return {
        "campaigns_n": len(records),
        "computed_n": len(computed),
        "reliable_n": sum(int(row["reliable"]) for row in records),
        "up_to_120_days_n": sum(row["duration_group"] == DURATION_SHORT for row in records),
        "longer_120_days_n": sum(row["duration_group"] == DURATION_LONG for row in records),
        "budget_rub": math.fsum(float(row["budget_rub"]) for row in records),
        "computed_budget_rub": computed_budget,
        "turnover_increment_rub": turnover,
        "weighted_roas": turnover / computed_budget if computed_budget > 0 else None,
    }


_DATA_KEYS = (
    "artifact_version",
    "data_schema_version",
    "package_id",
    "package_input_fingerprint",
    "model_run_id",
    "model_display_name",
    "catalog_version",
    "roas_level_label",
    "period_start",
    "period_end",
    "tail_weeks",
    "generated_at_utc",
    "notes",
    "summary",
    "campaigns",
)


def validate_catalog_data(data: Mapping[str, Any]) -> None:
    """Whole-file checks of campaign_catalog_v1.json (builder before writing, portal before serving)."""

    if tuple(data) != _DATA_KEYS:
        raise CampaignCatalogExtensionError("Catalog data keys differ from campaign_catalog_v1")
    if data["artifact_version"] != ARTIFACT_VERSION or data["data_schema_version"] != DATA_SCHEMA_VERSION:
        raise CampaignCatalogExtensionError("Catalog data version differs")
    if not isinstance(data["package_id"], str) or not PACKAGE_ID_RE.fullmatch(data["package_id"]):
        raise CampaignCatalogExtensionError("Catalog data package_id is invalid")
    if not isinstance(data["package_input_fingerprint"], str) or not SHA256_RE.fullmatch(
        data["package_input_fingerprint"]
    ):
        raise CampaignCatalogExtensionError("Catalog data fingerprint is invalid")
    if not data["package_id"].startswith(f"pkg_{data['package_input_fingerprint'][:16]}_"):
        raise CampaignCatalogExtensionError("Catalog data package_id does not carry its fingerprint")
    for key in ("model_run_id", "model_display_name", "catalog_version", "roas_level_label", "generated_at_utc"):
        _text(data[key], key)
    start = _iso_date(data["period_start"], "period_start")
    end = _iso_date(data["period_end"], "period_end")
    if end < start:
        raise CampaignCatalogExtensionError("Catalog period is reversed")
    tail = data["tail_weeks"]
    if isinstance(tail, bool) or not isinstance(tail, int) or tail < 0:
        raise CampaignCatalogExtensionError("tail_weeks must be a non-negative integer")
    notes = data["notes"]
    if not isinstance(notes, list) or any(
        not isinstance(row, Mapping) or tuple(row) != ("code", "display_text") for row in notes
    ):
        raise CampaignCatalogExtensionError("notes must be code + display_text rows")
    for row in notes:
        _text(row["code"], "notes.code")
        _text(row["display_text"], "notes.display_text")
    campaigns = data["campaigns"]
    if not isinstance(campaigns, list) or not campaigns:
        raise CampaignCatalogExtensionError("Catalog has no campaigns")
    numbers = [row.get("number") for row in campaigns if isinstance(row, Mapping)]
    if len(numbers) != len(campaigns) or numbers != sorted(set(numbers)):
        raise CampaignCatalogExtensionError("Campaign numbers must be unique and ascending")
    for row in campaigns:
        validate_campaign_record(row)
    expected = catalog_summary(campaigns)
    summary = data["summary"]
    if not isinstance(summary, Mapping) or tuple(summary) != tuple(expected):
        raise CampaignCatalogExtensionError("Catalog summary keys differ")
    for key, value in expected.items():
        actual = summary[key]
        if isinstance(value, float):
            if not isinstance(actual, (int, float)) or not _close(float(actual), value, absolute=1e-6):
                raise CampaignCatalogExtensionError(f"Catalog summary {key} differs from its campaigns")
        elif actual != value:
            raise CampaignCatalogExtensionError(f"Catalog summary {key} differs from its campaigns")


# ------------------------------------------------------------------------------------------------ Excel


def _fmt_cities(record: Mapping[str, Any]) -> str:
    text = ", ".join(record["cities"])
    if record["nationwide_channels"]:
        tail = "вся страна (" + ", ".join(record["nationwide_channels"]) + ")"
        text = f"{text} + {tail}" if text else tail
    return text


def write_catalog_workbook(
    path: Path,
    records: Sequence[Mapping[str, Any]],
    tech_rows: Sequence[tuple[str, str]],
) -> dict[str, tuple[int, int]]:
    """Write the download Excel: the layout of 28.10 (3 sheets), every number as a value, no draft marks.

    ``tech_rows`` are (label, value) pairs of «Тех. информация»; a label "§" starts a section. Returns the first and
    the last data row of both campaign sheets."""

    from openpyxl import Workbook
    from openpyxl.formatting.rule import CellIsRule
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.worksheet.properties import PageSetupProperties

    font = "Arial"
    f_body = Font(name=font, size=10)
    f_bold = Font(name=font, size=10, bold=True)
    f_gray = Font(name=font, size=10, color="7F7F7F")
    f_head = Font(name=font, size=10, bold=True, color="FFFFFF")
    f_title = Font(name=font, size=14, bold=True)
    f_note = Font(name=font, size=9, italic=True, color="7F7F7F")
    fill_head = PatternFill("solid", fgColor="262626")
    fill_head2 = PatternFill("solid", fgColor="3A3A3A")
    fill_sect = PatternFill("solid", fgColor="EDEDED")
    side_hair = Side(style="hair", color="BFBFBF")
    side_mid = Side(style="thin", color="8C8C8C")
    mln = "#,##0.0"
    sign = "+0.00;-0.00;0.00"
    widths = {
        "A": 5, "B": 44, "C": 24, "D": 11.5, "E": 11.5, "F": 7, "G": 52, "H": 56,
        "I": 12, "J": 12, "K": 10, "L": 10, "M": 15, "N": 15, "O": 12,
        "P": 11, "Q": 9, "R": 9, "S": 11, "T": 9, "U": 9, "V": 11, "W": 9, "X": 9,
        "Y": 9, "Z": 9, "AA": 9, "AB": 15, "AC": 12,
    }
    channel_columns = dict(zip((channel_id for channel_id, _, _ in CHANNELS), "IJKLMN"))
    group_start = {"I", "P", "S", "V", "Y", "AB", "AC"}

    def campaign_sheet(ws: Any, title: str, rows: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
        ws.sheet_view.showGridLines = False
        ws.sheet_view.zoomScale = 90
        ws["A1"] = title
        ws["A1"].font = f_title
        ws.row_dimensions[1].height = 24
        for column in widths:
            for row_index in (4, 5):
                cell = ws[f"{column}{row_index}"]
                cell.fill = fill_head if row_index == 4 else fill_head2
                cell.font = f_head
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for cell_range, label in (
            ("I4:O4", "Бюджет, млн ₽"),
            ("P4:R4", "Оборот, прирост, млн ₽"),
            ("S4:U4", "Заказы, прирост на 1000 покупателей"),
            ("V4:X4", "Средний чек, прирост, ₽"),
            ("Y4:AA4", "ROAS"),
        ):
            ws.merge_cells(cell_range)
            ws[cell_range.split(":")[0]] = label
        heads = {
            "A": "№", "B": "Кампания", "C": "Направление", "D": "Старт", "E": "Окончание", "F": "Дней",
            "G": "Каналы", "H": "Города", "O": "Всего",
            "P": "оценка", "Q": "от", "R": "до", "S": "оценка", "T": "от", "U": "до",
            "V": "оценка", "W": "от", "X": "до", "Y": "оценка", "Z": "от", "AA": "до",
            "AB": "Пересечения (кампаний)", "AC": "Надёжность",
        }
        for column, (_, display, _) in zip("IJKLMN", CHANNELS):
            heads[column] = display
        for column, text in heads.items():
            ws[f"{column}5"] = text
        ws.row_dimensions[4].height = 30
        ws.row_dimensions[5].height = 32
        for column, width in widths.items():
            ws.column_dimensions[column].width = width
        first = 6
        for offset, record in enumerate(rows):
            r = first + offset
            ws.row_dimensions[r].height = 20
            ws[f"A{r}"] = record["number"]
            ws[f"B{r}"] = record["name"]
            ws[f"C{r}"] = ", ".join(record["directions"])
            ws[f"D{r}"] = date.fromisoformat(record["start_date"])
            ws[f"E{r}"] = date.fromisoformat(record["end_date"])
            ws[f"F{r}"] = record["days_n"]
            ws[f"G{r}"] = ", ".join(row["display_name"] for row in record["channels"])
            ws[f"H{r}"] = _fmt_cities(record)
            for channel in record["channels"]:
                ws[f"{channel_columns[channel['channel_id']]}{r}"] = round(channel["budget_rub"] / 1e6, 6)
            ws[f"O{r}"] = round(record["budget_rub"] / 1e6, 6)
            for start_column, key, scale in (
                ("P", "turnover_increment_rub", 1e6),
                ("S", "orders_per_1000_buyers", 1.0),
                ("V", "avg_basket_increment_rub", 1.0),
                ("Y", "roas", 1.0),
            ):
                values = record[key]
                if values is None:
                    continue
                column = ws[f"{start_column}{r}"].column
                for step, part in enumerate(_RANGE_KEYS):
                    value = values[part] / scale if scale != 1.0 else values[part]
                    ws.cell(row=r, column=column + step, value=round(value, 6) if scale != 1.0 else value)
            ws[f"AB{r}"] = record["overlaps_n"]
            ws[f"AC{r}"] = record["reliable"]
            for column in widths:
                cell = ws[f"{column}{r}"]
                cell.font = f_body
                cell.border = Border(bottom=side_hair, left=side_mid if column in group_start else None)
                cell.alignment = Alignment(vertical="center")
            ws[f"A{r}"].alignment = Alignment(horizontal="center", vertical="center")
            ws[f"B{r}"].font = f_bold
            for column in ("D", "E"):
                ws[f"{column}{r}"].number_format = "DD.MM.YYYY"
                ws[f"{column}{r}"].alignment = Alignment(horizontal="center", vertical="center")
            ws[f"F{r}"].number_format = "0"
            ws[f"F{r}"].alignment = Alignment(horizontal="center", vertical="center")
            for column in "IJKLMNO":
                ws[f"{column}{r}"].number_format = mln
            ws[f"O{r}"].font = f_bold
            for column in ("P", "Q", "R"):
                ws[f"{column}{r}"].number_format = mln
            for column in ("S", "T", "U", "V", "W", "X"):
                ws[f"{column}{r}"].number_format = sign
            for column in ("Y", "Z", "AA"):
                ws[f"{column}{r}"].number_format = "0.00"
            for column in ("P", "S", "V", "Y"):
                ws[f"{column}{r}"].font = f_bold
            for column in ("Q", "R", "T", "U", "W", "X", "Z", "AA"):
                ws[f"{column}{r}"].font = f_gray
            ws[f"AB{r}"].number_format = "0"
            ws[f"AB{r}"].alignment = Alignment(horizontal="center", vertical="center")
            ws[f"AC{r}"].number_format = "0"
            ws[f"AC{r}"].font = f_bold
            ws[f"AC{r}"].alignment = Alignment(horizontal="center", vertical="center")
        last = first + len(rows) - 1
        if rows:
            green = PatternFill("solid", bgColor="E2F0D9", fgColor="E2F0D9")
            amber = PatternFill("solid", bgColor="FCE4D6", fgColor="FCE4D6")
            ws.conditional_formatting.add(
                f"AC{first}:AC{last}",
                CellIsRule(operator="equal", formula=["1"], fill=green, font=Font(name=font, bold=True, color="375623")),
            )
            ws.conditional_formatting.add(
                f"AC{first}:AC{last}",
                CellIsRule(operator="equal", formula=["0"], fill=amber, font=Font(name=font, bold=True, color="843C0C")),
            )
            ws.auto_filter.ref = f"A5:AC{last}"
        ws.freeze_panes = "C6"
        note_row = max(last, 5) + 2
        notes = (
            "Надёжность: 1 — оценке можно доверять (не меньше половины бюджета кампании в каналах, где расчёт модели "
            "сошёлся и данных достаточно); 0 — смотреть с осторожностью.",
            "Пересечения: сколько других кампаний того же направления шли в те же дни и города.",
            "Уровень отдачи каналов задан отраслевыми значениями для каждой сети и направления; данные распределяют его "
            "по городам и неделям. Средний чек модель почти не даёт рекламе менять (так задумано), эффект идёт в "
            "основном через заказы.",
            "Пустые ячейки: деньги кампании пришлись на города или недели, которых нет в модели, оценки нет.",
        )
        for step, text in enumerate(notes):
            ws[f"A{note_row + step}"] = text
            ws[f"A{note_row + step}"].font = f_note
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
        return first, last

    short = [row for row in records if row["duration_group"] == DURATION_SHORT]
    long_rows = [row for row in records if row["duration_group"] == DURATION_LONG]
    workbook = Workbook()
    ws_tech = workbook.active
    ws_tech.title = "Тех. информация"
    ws_short = workbook.create_sheet("Кампании до 120 дней")
    ws_long = workbook.create_sheet("Кампании длиннее 120 дней")
    spans = {
        "short": campaign_sheet(ws_short, "Кампании до 120 дней", short),
        "long": campaign_sheet(ws_long, "Кампании длиннее 120 дней", long_rows),
    }

    ws = ws_tech
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 96
    ws["A1"] = "Тех. информация"
    ws["A1"].font = f_title
    ws.row_dimensions[1].height = 24
    ws["A3"], ws["B3"] = "Параметр", "Значение"
    for column in "AB":
        ws[f"{column}3"].font = f_head
        ws[f"{column}3"].fill = fill_head
        ws[f"{column}3"].alignment = Alignment(vertical="center")
    ws.row_dimensions[3].height = 20
    all_rows = list(tech_rows) + [
        ("§", "Файл"),
        ("Кампаний до 120 дней", str(len(short))),
        ("Кампаний длиннее 120 дней", str(len(long_rows))),
        ("Кампаний всего", str(len(records))),
    ]
    r = 4
    for label, value in all_rows:
        if label == "§":
            ws[f"A{r}"] = value
            ws[f"A{r}"].font = f_bold
            for column in "AB":
                ws[f"{column}{r}"].fill = fill_sect
            ws.row_dimensions[r].height = 18
        else:
            ws[f"A{r}"] = label
            ws[f"B{r}"] = int(value) if label.startswith("Кампаний") else value
            ws[f"A{r}"].font = f_body
            ws[f"B{r}"].font = Font(name=font, size=10, color="000000")
            ws[f"A{r}"].alignment = Alignment(vertical="top")
            ws[f"B{r}"].alignment = Alignment(vertical="top", wrap_text=True, horizontal="left")
            for column in "AB":
                ws[f"{column}{r}"].border = Border(bottom=side_hair)
            if len(str(value)) > 95:
                ws.row_dimensions[r].height = 28 if len(str(value)) < 190 else 42
        r += 1
    ws_tech.sheet_properties.tabColor = "7F7F7F"
    ws_short.sheet_properties.tabColor = "C7FD72"
    ws_long.sheet_properties.tabColor = "D48A20"
    ws_tech.page_setup.orientation = "landscape"
    ws_tech.page_setup.fitToHeight = 0
    ws_tech.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    workbook.active = 1
    for index, sheet in enumerate(workbook.worksheets):
        sheet.sheet_view.tabSelected = index == 1
    workbook.save(path)
    return spans


def verify_catalog_workbook(path: Path, records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Re-open the written Excel and compare every campaign cell with the card records (values, not formulas)."""

    from openpyxl import load_workbook

    workbook = load_workbook(path, data_only=False)
    expected_sheets = ["Тех. информация", "Кампании до 120 дней", "Кампании длиннее 120 дней"]
    if workbook.sheetnames != expected_sheets:
        raise CampaignCatalogExtensionError(f"Excel sheets differ: {workbook.sheetnames}")
    formulas = 0
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    formulas += 1
                if isinstance(cell.value, str) and "ЧЕРНОВИК" in cell.value.upper():
                    raise CampaignCatalogExtensionError("Excel still carries a draft mark")
    if formulas:
        raise CampaignCatalogExtensionError(f"Excel has {formulas} formulas; values only are allowed")
    by_number = {int(row["number"]): row for row in records}
    seen: set[int] = set()
    cells_checked = 0
    channel_columns = dict(zip((channel_id for channel_id, _, _ in CHANNELS), "IJKLMN"))
    for sheet_name, group in (
        ("Кампании до 120 дней", DURATION_SHORT),
        ("Кампании длиннее 120 дней", DURATION_LONG),
    ):
        ws = workbook[sheet_name]
        r = 6
        while isinstance(ws[f"A{r}"].value, int):
            number = int(ws[f"A{r}"].value)
            record = by_number.get(number)
            if record is None or number in seen or record["duration_group"] != group:
                raise CampaignCatalogExtensionError(f"Excel row {sheet_name}!A{r} is not a catalog campaign")
            seen.add(number)
            expected: dict[str, Any] = {
                "B": record["name"],
                "C": ", ".join(record["directions"]),
                "F": record["days_n"],
                "G": ", ".join(row["display_name"] for row in record["channels"]),
                "H": _fmt_cities(record),
                "O": round(record["budget_rub"] / 1e6, 6),
                "AB": record["overlaps_n"],
                "AC": record["reliable"],
            }
            for channel_id, column in channel_columns.items():
                budgets = [row["budget_rub"] for row in record["channels"] if row["channel_id"] == channel_id]
                expected[column] = round(budgets[0] / 1e6, 6) if budgets else None
            for start_column, key, scale in (
                ("P", "turnover_increment_rub", 1e6),
                ("S", "orders_per_1000_buyers", 1.0),
                ("V", "avg_basket_increment_rub", 1.0),
                ("Y", "roas", 1.0),
            ):
                column_index = ws[f"{start_column}{r}"].column
                values = record[key]
                for step, part in enumerate(_RANGE_KEYS):
                    letter = ws.cell(row=r, column=column_index + step).column_letter
                    if values is None:
                        expected[letter] = None
                    else:
                        value = values[part] / scale if scale != 1.0 else values[part]
                        expected[letter] = round(value, 6) if scale != 1.0 else value
            for column, value in expected.items():
                actual = ws[f"{column}{r}"].value
                if isinstance(value, float) and isinstance(actual, (int, float)):
                    if not _close(float(actual), value, absolute=1e-12):
                        raise CampaignCatalogExtensionError(f"Excel {sheet_name}!{column}{r} differs")
                elif actual != value:
                    raise CampaignCatalogExtensionError(f"Excel {sheet_name}!{column}{r} differs")
                cells_checked += 1
            start_cell, end_cell = ws[f"D{r}"].value, ws[f"E{r}"].value
            if (
                not isinstance(start_cell, datetime)
                or start_cell.date().isoformat() != record["start_date"]
                or not isinstance(end_cell, datetime)
                or end_cell.date().isoformat() != record["end_date"]
            ):
                raise CampaignCatalogExtensionError(f"Excel dates of {sheet_name}!A{r} differ")
            cells_checked += 2
            r += 1
    if seen != set(by_number):
        raise CampaignCatalogExtensionError("Excel does not hold every catalog campaign exactly once")
    return {"campaigns": len(seen), "cells_checked": cells_checked, "formulas": 0}


# ------------------------------------------------------------------------------------------------ package identity


@dataclass(frozen=True)
class PackageIdentity:
    package_id: str
    package_input_fingerprint: str
    model_run_id: str
    model_display_name: str
    roas_level_label: str
    npz_sha256: str | None
    model_roas_rows: tuple[Mapping[str, str], ...]
    source: str


def package_identity_from_dir(package_dir: Path, package_id: str) -> PackageIdentity:
    """Identity of a weekly package folder: manifest fingerprint (files re-hashed), run_config npz hash, ROAS table."""

    root = package_dir.expanduser().resolve()
    manifest = json.loads((root / "model_manifest.json").read_text(encoding="utf-8"))
    files = manifest.get("files")
    if not isinstance(files, Mapping) or not files:
        raise CampaignCatalogExtensionError("Package manifest lists no files")
    for name, expected in files.items():
        if sha256_file(root / str(name)) != expected:
            raise CampaignCatalogExtensionError(f"Package file changed after its manifest: {name}")
    fingerprint = hashlib.sha256(json.dumps(dict(files), sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    if fingerprint != manifest.get("package_input_fingerprint"):
        raise CampaignCatalogExtensionError("Package fingerprint differs from its manifest")
    if not PACKAGE_ID_RE.fullmatch(package_id) or not package_id.startswith(f"pkg_{fingerprint[:16]}_"):
        raise CampaignCatalogExtensionError("Package ID does not belong to this package fingerprint")
    run_config = json.loads((root / "run_config.json").read_text(encoding="utf-8"))
    npz = run_config.get("npz_sha256") or (run_config.get("builder") or {}).get("npz_sha256")
    roas_rows = _read_csv(root / "model_roas_table.csv") if (root / "model_roas_table.csv").is_file() else ()
    return PackageIdentity(
        package_id=package_id,
        package_input_fingerprint=fingerprint,
        model_run_id=str(manifest.get("model_run_id") or ""),
        model_display_name=str(manifest.get("model_name") or ""),
        roas_level_label=str(manifest.get("roas_level_label_ru") or ROAS_LEVEL_LABEL),
        npz_sha256=str(npz) if npz else None,
        model_roas_rows=roas_rows,
        source="package_dir",
    )


def _find_npz_sha(value: Any) -> str | None:
    """The npz hash may sit at any depth of run_config (builder arguments); find the one key named npz_sha256."""

    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key == "npz_sha256" and isinstance(nested, str) and SHA256_RE.fullmatch(nested):
                return nested
            found = _find_npz_sha(nested)
            if found:
                return found
    if isinstance(value, list):
        for nested in value:
            found = _find_npz_sha(nested)
            if found:
                return found
    return None


# ------------------------------------------------------------------------------------------------ checks


def _check(check_id: str, passed: bool, display_text: str, value: Any = None) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": "passed" if passed else "failed",
        "value": value,
        "display_text": display_text,
    }


def _rounded(value: float | None, digits: int = 4) -> str:
    if value is None:
        return ""
    return repr(round(float(value), digits))


def compare_with_numbers_csv(
    records: Sequence[Mapping[str, Any]], numbers_rows: Sequence[Mapping[str, str]]
) -> dict[str, Any]:
    """Every catalog row against catalog_numbers.csv of the same run (the CSV rounds to 4 decimals)."""

    by_number = {int(row["номер"]): row for row in numbers_rows}
    mismatches: list[str] = []
    for record in records:
        row = by_number.get(int(record["number"]))
        if row is None:
            mismatches.append(f"№{record['number']} missing in CSV")
            continue
        computed = record["status"] == "computed"
        pairs: list[tuple[str, Any, Any]] = [
            ("кампания", row.get("кампания"), record["name"]),
            ("старт", row.get("старт"), record["start_date"]),
            ("конец", row.get("конец"), record["end_date"]),
            ("дней", int(row.get("дней") or -1), record["days_n"]),
            ("флаг", int(row.get("флаг") or 0), record["reliable"]),
            ("пересечения", int(row.get("пересечения") or 0), record["overlaps_n"]),
            ("модель_считает", int(row.get("модель_считает") or 0), int(computed)),
        ]
        numeric = [
            ("бюджет_млн", record["budget_rub"] / 1e6),
            ("оборот_оценка_млн", record["turnover_increment_rub"]["estimate"] / 1e6 if computed else None),
            ("оборот_от_млн", record["turnover_increment_rub"]["low"] / 1e6 if computed else None),
            ("оборот_до_млн", record["turnover_increment_rub"]["high"] / 1e6 if computed else None),
            ("roas_оценка", record["roas"]["estimate"] if record["roas"] else None),
            ("roas_от", record["roas"]["low"] if record["roas"] else None),
            ("roas_до", record["roas"]["high"] if record["roas"] else None),
        ]
        for key, value in numeric:
            text = row.get(key, "")
            if value is None:
                pairs.append((key, text, ""))
            else:
                pairs.append((key, float(text) if text not in ("", None) else None, round(float(value), 4)))
        for key, left, right in pairs:
            if isinstance(left, float) and isinstance(right, float):
                if abs(left - right) > 1e-9:
                    mismatches.append(f"№{record['number']} {key}: {left} != {right}")
            elif left != right:
                mismatches.append(f"№{record['number']} {key}: {left!r} != {right!r}")
    extra = sorted(set(by_number) - {int(row["number"]) for row in records})
    if extra:
        mismatches.append(f"CSV numbers not in the catalog: {extra[:10]}")
    return {"rows": len(records), "mismatches": mismatches}


def catalog_checks(
    records: Sequence[Mapping[str, Any]],
    source: SourceCatalog,
    identity: PackageIdentity,
) -> list[dict[str, Any]]:
    """Checks recorded in the metadata; the portal serves the catalog only when all of them passed."""

    checks: list[dict[str, Any]] = []
    numbers = [int(row["number"]) for row in records]
    checks.append(
        _check(
            "numbers_unique",
            len(numbers) == len(set(numbers)) == len(source.results),
            "Номера кампаний уникальны, каждая кампания каталога есть ровно один раз.",
            len(numbers),
        )
    )
    csv_report = compare_with_numbers_csv(records, source.numbers_rows)
    checks.append(
        _check(
            "catalog_equals_numbers_csv",
            not csv_report["mismatches"],
            "Поля и числа каталога совпадают с catalog_numbers.csv того же расчёта.",
            {"rows": csv_report["rows"], "mismatches": csv_report["mismatches"][:20]},
        )
    )
    run = dict(source.checks.get("sum_campaigns_le_full") or {})
    ratios = [
        float(row["sum_campaign_effect_over_full"])
        for row in source.roas_check_rows
        if row.get("sum_campaign_effect_over_full") not in (None, "", "nan")
    ]
    max_ratio = max(ratios) if ratios else None
    checks.append(
        _check(
            "sum_campaigns_le_channel_effect",
            run.get("violations") == 0 and max_ratio is not None and max_ratio <= 1.0 + 1e-9,
            "Сумма эффектов кампаний не больше полного эффекта канала (каждый розыгрыш, направление × канал).",
            {"violations": run.get("violations"), "cells": run.get("cells"), "max_median_ratio": max_ratio},
        )
    )
    source_npz = ((source.meta.get("inputs") or {}).get("npz") or {}).get("sha256")
    checks.append(
        _check(
            "catalog_fit_equals_package_fit",
            bool(source_npz) and source_npz == identity.npz_sha256,
            "Каталог посчитан на тех же розыгрышах модели, что и пакет портала.",
            {"catalog_npz_sha256": source_npz, "package_npz_sha256": identity.npz_sha256},
        )
    )
    differences: list[float] = []
    by_cell = {(row.get("segment"), row.get("channel")): row for row in identity.model_roas_rows}
    for row in source.roas_check_rows:
        reference = by_cell.get((row.get("segment"), row.get("channel")))
        value = row.get("model_roas_fit_rows")
        if reference is None or value in (None, "", "nan"):
            continue
        model_roas = float(reference["roas_median"])
        differences.append(abs(float(value) - model_roas) / max(abs(model_roas), 1e-12))
    checks.append(
        _check(
            "catalog_model_roas_equals_package_table",
            bool(differences) and max(differences) <= 0.02,
            "ROAS модели по направлениям и каналам в расчёте каталога совпадает с таблицей пакета (до 2%).",
            {"cells": len(differences), "max_relative_difference": max(differences) if differences else None},
        )
    )
    return checks


# ------------------------------------------------------------------------------------------------ build


def tech_rows_from_source(
    source: SourceCatalog,
    identity: PackageIdentity,
    *,
    catalog_version: str,
    generated_at: datetime,
) -> list[tuple[str, str]]:
    """Rows of «Тех. информация» (same texts as the catalog Excel of 05.11, without draft marks)."""

    meta = source.meta
    inputs = meta.get("inputs") or {}
    adstock_weeks = meta.get("adstock_weeks")
    tail_weeks = int(meta.get("tail_weeks") or 0)
    numbers = source.checks.get("numbers") or {}
    gone = numbers.get("old_not_found") or []
    gone_text = (
        "; "
        + "; ".join(
            f"№{item['id']}" + (f" «{item['name']}»" if item.get("name") else "")
            + " вошла в другую кампанию после исправления дат в журнале 02.11.2026"
            for item in gone
        )
        if gone
        else ""
    )
    seconds = int(meta.get("calc_seconds") or 0)
    code_hash = hashlib.sha256(
        "".join(f"{key}:{value}" for key, value in sorted((meta.get("code_sha256") or {}).items())).encode()
    ).hexdigest()[:12]
    finished = meta.get("finished_utc")
    calc_time = (
        datetime.strptime(finished, "%d.%m.%Y %H:%M").replace(tzinfo=timezone.utc).astimezone(DA_NANG).strftime("%d.%m.%Y %H:%M")
        + " (Дананг, UTC+7)"
        if finished
        else "нет данных"
    )
    data_period = (
        "01.01.2025–30.06.2026 (эффект считается по 28.06.2026, последняя полная неделя)"
        if not tail_weeks
        else (
            f"01.01.2025–30.06.2026; эффект кампаний конца окна досчитан на {tail_weeks} недель после 28.06.2026, "
            "как в прогнозе плана: базовый оборот этих недель — те же недели 2025 года, другие траты в эти недели — "
            + ("как год назад" if meta.get("tail_other") == "analog" else "не учитываются (верхняя оценка)")
        )
    )
    npz = inputs.get("npz") or {}
    return [
        ("§", "Модель и пакет"),
        ("Версия модели", f"«{identity.model_display_name}», запуск {identity.model_run_id}"),
        (
            "Спецификация модели",
            "Одна модель на 4 направления (ТС5 и ТСХ, магазины и доставка): недельные заказы и средний чек, оборот = "
            "заказы × чек; 5 каналов (нац. ТВ, рег. ТВ, радио, наружная реклама вместе с Indoor, цифровая реклама); "
            "реклама магазинов действует только на магазины, доставки только на доставку; в каждом городе реклама "
            "действует по своим расходам на жителя; перенос рекламы "
            f"до {adstock_weeks} недель; обучение 01.01.2025–28.06.2026.",
        ),
        (
            "Уровень отдачи",
            "Уровень ROAS каждого канала привязан к отраслевым значениям для каждой сети и направления (решение от "
            "03.11.2026); данные распределяют его по городам и неделям. Уровень — допущение, а не измерение.",
        ),
        ("Пакет модели", identity.package_id),
        ("Хэш пакета (SHA-256)", identity.package_input_fingerprint),
        ("Розыгрыши модели (SHA-256)", f"{Path(str(npz.get('path') or '')).name} {npz.get('sha256') or ''}".strip()),
        ("§", "Данные"),
        ("Период данных", data_period),
        ("Версия реестра кампаний", "журнал расходов v3 (исправлен 02.11.2026)"),
        ("Хэш реестра кампаний (SHA-256)", str((inputs.get("ledger") or {}).get("sha256") or "")),
        (
            "Версия словаря кампаний",
            "v1: названия, различающиеся регистром, пробелами, знаками и приставкой «РК», считаются одной кампанией; "
            "пауза больше 30 дней — другая кампания; период длиннее года режется по границе года; номера как в "
            "справочнике названий" + gone_text,
        ),
        ("§", "Расчёт"),
        (
            "Метод",
            f"Оценка строится путем создания контрфактуала. Реклама действует с переносом до {adstock_weeks} недель.",
        ),
        (
            "Версия метода",
            "v2: недельная модель; деньги кампании раскладываются по городам модели по тем же правилам, что при обучении",
        ),
        ("Версия каталога", catalog_version),
        ("Версия кода расчёта", f"{meta.get('code_version')}, сборка {code_hash}"),
        ("Дата и время расчёта", calc_time),
        (
            "Длительность расчёта",
            f"{seconds // 60} мин {seconds % 60} с ({meta.get('n_campaigns')} кампаний, {meta.get('n_draws')} "
            "случайных наборов параметров модели)",
        ),
        ("Диапазон «от» – «до»", "от 10-го до 90-го процентиля результата"),
        ("§", "Правила каталога"),
        (
            "Деление на листы",
            "Длительность — от первого до последнего дня кампании. Меньше 120 дней — лист «Кампании до 120 дней», "
            "120 дней и больше — лист «Кампании длиннее 120 дней».",
        ),
        (
            "Пересечения",
            "Другие кампании того же направления, у которых совпал хотя бы один день и один город. Федеральные каналы "
            "считаются как все города.",
        ),
        (
            "Города",
            "Деньги кампании раскладываются по городам модели так же, как при обучении: «РФ» по населению городов, "
            "область по её городам и остатку. Отдача рубля зависит от расходов на жителя: где реклама плотнее "
            "(например, Москва), отдача рубля ниже.",
        ),
        (
            "Единицы",
            "Бюджет и оборот — млн ₽. Заказы — прирост на 1000 покупателей. Средний чек — прирост в рублях. "
            "ROAS = прирост оборота / весь бюджет кампании.",
        ),
        ("§", "Файл"),
        ("Файл сформирован", generated_at.astimezone(DA_NANG).strftime("%d.%m.%Y %H:%M") + " (Дананг)"),
    ]


def build_extension(
    *,
    source: SourceCatalog,
    identity: PackageIdentity,
    out_dir: Path,
    catalog_version: str,
    generated_at_utc: str,
    period_start: str = "2025-01-06",
    period_end: str = "2026-06-28",
    download_file_name: str | None = None,
) -> dict[str, Any]:
    """Write the three extension files into a new folder named campaign_catalog_v1 and return the metadata."""

    generated = datetime.fromisoformat(generated_at_utc.replace("Z", "+00:00"))
    if generated.tzinfo is None:
        raise CampaignCatalogExtensionError("generated_at_utc must carry a timezone")
    generated = generated.astimezone(timezone.utc)
    output = out_dir.expanduser().resolve()
    if output.name != ARTIFACT_VERSION:
        raise CampaignCatalogExtensionError(f"Extension folder must be named {ARTIFACT_VERSION}")
    if output.exists():
        raise FileExistsError(f"Extension folder already exists (new versions only): {output}")
    records = [normalize_campaign(row) for row in source.results]
    records.sort(key=lambda row: row["number"])
    data = {
        "artifact_version": ARTIFACT_VERSION,
        "data_schema_version": DATA_SCHEMA_VERSION,
        "package_id": identity.package_id,
        "package_input_fingerprint": identity.package_input_fingerprint,
        "model_run_id": identity.model_run_id,
        "model_display_name": identity.model_display_name,
        "catalog_version": catalog_version,
        "roas_level_label": identity.roas_level_label,
        "period_start": period_start,
        "period_end": period_end,
        "tail_weeks": int(source.meta.get("tail_weeks") or 0),
        "generated_at_utc": generated.isoformat(),
        "notes": [dict(row) for row in NOTES],
        "summary": catalog_summary(records),
        "campaigns": records,
    }
    validate_catalog_data(data)
    checks = catalog_checks(records, source, identity)
    output.mkdir(parents=True)
    data_path = output / DATA_FILENAME
    workbook_path = output / WORKBOOK_FILENAME
    _write_bytes_new(data_path, _json_bytes(data))
    temporary_workbook = output / f".{WORKBOOK_FILENAME}.{os.getpid()}.tmp.xlsx"
    write_catalog_workbook(
        temporary_workbook,
        records,
        tech_rows_from_source(source, identity, catalog_version=catalog_version, generated_at=generated),
    )
    os.replace(temporary_workbook, workbook_path)
    workbook_report = verify_catalog_workbook(workbook_path, records)
    checks.append(
        _check(
            "workbook_equals_catalog",
            True,
            "Excel для скачивания содержит те же кампании и числа, что и данные портала; формул и пометок «черновик» нет.",
            workbook_report,
        )
    )
    data_sha = sha256_file(data_path)
    workbook_sha = sha256_file(workbook_path)
    artifact_id = "artifact_" + canonical_sha256(
        {
            "artifact_version": ARTIFACT_VERSION,
            "package_id": identity.package_id,
            "data_sha256": data_sha,
            "workbook_sha256": workbook_sha,
        }
    )[:24]
    file_date = generated.astimezone(DA_NANG).strftime("%Y%m%d")
    metadata = {
        "metadata_schema_version": METADATA_SCHEMA_VERSION,
        "artifact_id": artifact_id,
        "artifact_version": ARTIFACT_VERSION,
        "package_id": identity.package_id,
        "package_input_fingerprint": identity.package_input_fingerprint,
        "model_run_id": identity.model_run_id,
        "catalog_version": catalog_version,
        "data": {
            "relative_path": DATA_FILENAME,
            "sha256": data_sha,
            "size_bytes": data_path.stat().st_size,
        },
        "workbook": {
            "relative_path": WORKBOOK_FILENAME,
            "sha256": workbook_sha,
            "size_bytes": workbook_path.stat().st_size,
            "download_file_name": download_file_name
            or f"Каталог_прошлых_кампаний_{identity.model_display_name}_{file_date}.xlsx",
        },
        "campaigns_n": data["summary"]["campaigns_n"],
        "computed_n": data["summary"]["computed_n"],
        "budget_rub": data["summary"]["budget_rub"],
        "turnover_increment_rub": data["summary"]["turnover_increment_rub"],
        "source_files": list(source.source_files),
        "identity_source": identity.source,
        "checks": checks,
        "generated_at_utc": generated.isoformat(),
        "builder": {"module": "mmm_core.campaign_catalog_extension", "version": DATA_SCHEMA_VERSION},
    }
    validate_metadata(metadata)
    _write_bytes_new(output / METADATA_FILENAME, _json_bytes(metadata))
    return metadata


_METADATA_KEYS = (
    "metadata_schema_version",
    "artifact_id",
    "artifact_version",
    "package_id",
    "package_input_fingerprint",
    "model_run_id",
    "catalog_version",
    "data",
    "workbook",
    "campaigns_n",
    "computed_n",
    "budget_rub",
    "turnover_increment_rub",
    "source_files",
    "identity_source",
    "checks",
    "generated_at_utc",
    "builder",
)


def validate_metadata(metadata: Mapping[str, Any]) -> None:
    """Shape and identity checks of campaign_catalog_v1.metadata.json (no file access)."""

    if tuple(metadata) != _METADATA_KEYS:
        raise CampaignCatalogExtensionError("Catalog metadata keys differ")
    if (
        metadata["metadata_schema_version"] != METADATA_SCHEMA_VERSION
        or metadata["artifact_version"] != ARTIFACT_VERSION
    ):
        raise CampaignCatalogExtensionError("Catalog metadata version differs")
    if not re.fullmatch(r"artifact_[0-9a-f]{24}", str(metadata["artifact_id"])):
        raise CampaignCatalogExtensionError("Catalog artifact_id is invalid")
    if not PACKAGE_ID_RE.fullmatch(str(metadata["package_id"])) or not SHA256_RE.fullmatch(
        str(metadata["package_input_fingerprint"])
    ):
        raise CampaignCatalogExtensionError("Catalog metadata package identity is invalid")
    for key, filename in (("data", DATA_FILENAME), ("workbook", WORKBOOK_FILENAME)):
        entry = metadata[key]
        if (
            not isinstance(entry, Mapping)
            or entry.get("relative_path") != filename
            or not SHA256_RE.fullmatch(str(entry.get("sha256")))
            or isinstance(entry.get("size_bytes"), bool)
            or not isinstance(entry.get("size_bytes"), int)
            or entry["size_bytes"] <= 0
        ):
            raise CampaignCatalogExtensionError(f"Catalog metadata {key} entry is invalid")
    name = metadata["workbook"].get("download_file_name")
    if not isinstance(name, str) or not name.endswith(".xlsx") or "/" in name or "\\" in name:
        raise CampaignCatalogExtensionError("Catalog download file name is invalid")
    checks = metadata["checks"]
    if not isinstance(checks, list) or not checks:
        raise CampaignCatalogExtensionError("Catalog metadata has no checks")
    for row in checks:
        if not isinstance(row, Mapping) or row.get("status") not in {"passed", "failed"}:
            raise CampaignCatalogExtensionError("Catalog metadata check rows are invalid")


def failed_checks(metadata: Mapping[str, Any]) -> list[str]:
    return [str(row.get("check_id")) for row in metadata.get("checks") or [] if row.get("status") != "passed"]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--catalog-dir", required=True, type=Path)
    parser.add_argument("--package-dir", required=True, type=Path)
    parser.add_argument("--package-id", required=True)
    parser.add_argument("--catalog-version", required=True)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--generated-at-utc", default=None)
    parser.add_argument("--allow-failed-checks", action="store_true", help="write anyway (the portal will refuse)")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    source = load_source_catalog(args.catalog_dir)
    identity = package_identity_from_dir(args.package_dir, args.package_id)
    run_config = json.loads((args.package_dir / "run_config.json").read_text(encoding="utf-8"))
    if identity.npz_sha256 is None:
        identity = PackageIdentity(**{**identity.__dict__, "npz_sha256": _find_npz_sha(run_config)})
    records = [normalize_campaign(row) for row in source.results]
    precheck = catalog_checks(sorted(records, key=lambda row: row["number"]), source, identity)
    failed = [row for row in precheck if row["status"] != "passed"]
    if failed and not args.allow_failed_checks:
        print(json.dumps({"status": "failed", "checks": failed}, ensure_ascii=False, indent=1, default=str))
        return 2
    metadata = build_extension(
        source=source,
        identity=identity,
        out_dir=args.out_dir,
        catalog_version=args.catalog_version,
        generated_at_utc=args.generated_at_utc or datetime.now(timezone.utc).isoformat(),
    )
    print(json.dumps({key: metadata[key] for key in ("artifact_id", "package_id", "campaigns_n", "computed_n",
                                                      "data", "workbook", "checks")}, ensure_ascii=False, indent=1,
                     default=str))
    return 0 if not failed_checks(metadata) else 3


__all__ = [
    "ARTIFACT_VERSION",
    "CampaignCatalogExtensionError",
    "DATA_FILENAME",
    "EXTENSION_FILES",
    "METADATA_FILENAME",
    "WORKBOOK_FILENAME",
    "build_extension",
    "catalog_summary",
    "failed_checks",
    "load_source_catalog",
    "normalize_campaign",
    "package_identity_from_dir",
    "sha256_file",
    "validate_campaign_record",
    "validate_catalog_data",
    "validate_metadata",
    "verify_catalog_workbook",
    "write_catalog_workbook",
]


if __name__ == "__main__":
    sys.exit(main())
