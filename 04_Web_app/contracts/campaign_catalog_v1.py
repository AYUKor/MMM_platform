"""Semantic validation of the past-campaign catalog served to the browser.

``campaign_catalog_v1`` is the whole catalog of the active model package (list page and Excel download link),
``campaign_card_v1`` is one campaign of it (card page). Both carry the campaign records exactly as the package
extension ``campaign_catalog_v1`` holds them: the portal shows the catalog numbers and never recomputes them.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping


CATALOG_CONTRACT_NAME = "campaign_catalog_v1"
CARD_CONTRACT_NAME = "campaign_card_v1"
SCHEMA_VERSION = "1.1.0"
TITLE = "Прошлые кампании"
DOWNLOAD_PATH = "/api/v1/campaign-catalog/download"
WORKBOOK_SHEETS = ("Тех. информация", "Кампании до 120 дней", "Кампании длиннее 120 дней")
DIRECTIONS = ("ТС5/Онлайн", "ТС5/Оффлайн", "ТСХ/Онлайн", "ТСХ/Оффлайн")
CHANNEL_DISPLAY = {
    "Digital_Performance": "Цифровая реклама",
    "OOH_Total": "Наружная реклама",
    "Indoor": "Indoor",
    "Радио": "Радио",
    "Нац_ТВ": "Национальное ТВ",
    "Рег_ТВ": "Региональное ТВ",
}
CHANNEL_ORDER = {channel_id: index for index, channel_id in enumerate(CHANNEL_DISPLAY)}
LONG_DAYS = 120
CATALOG_KEYS = (
    "contract_name",
    "schema_version",
    "record_origin",
    "status",
    "title",
    "display_text",
    "package_id",
    "model_version",
    "model_display_name",
    "artifact_id",
    "catalog_version",
    "period_start",
    "period_end",
    "roas_level_label",
    "summary",
    "download",
    "notes",
    "campaigns",
    "updated_at_utc",
)
CARD_KEYS = (
    "contract_name",
    "schema_version",
    "record_origin",
    "package_id",
    "model_version",
    "model_display_name",
    "artifact_id",
    "catalog_version",
    "period_start",
    "period_end",
    "roas_level_label",
    "notes",
    "campaign",
    "updated_at_utc",
)
CAMPAIGN_KEYS = (
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
    "explanation",
)
EXPLANATION_KEYS = (
    "rules_version",
    "potential_turnover_rub",
    "kept_share",
    "own_saturation_share",
    "overlap_share",
    "first_ruble_roas",
    "typical_first_ruble_roas",
    "unseen_budget_share",
    "tail_share",
    "own_saturation_cities",
    "overlap_cities",
    "reasons",
)
SUMMARY_KEYS = (
    "campaigns_n",
    "computed_n",
    "reliable_n",
    "up_to_120_days_n",
    "longer_120_days_n",
    "budget_rub",
    "computed_budget_rub",
    "turnover_increment_rub",
    "weighted_roas",
)
CHANNEL_KEYS = ("channel_id", "display_name", "budget_rub", "nationwide")
RANGE_KEYS = ("estimate", "low", "high")
EFFECT_KEYS = ("turnover_increment_rub", "orders_per_1000_buyers", "avg_basket_increment_rub", "roas")
_PACKAGE_ID_RE = re.compile(r"^pkg_[A-Za-z0-9._-]{8,128}$")
_ARTIFACT_ID_RE = re.compile(r"^artifact_[0-9a-f]{24}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_NOTE_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_ABSOLUTE_PATH_RE = re.compile(r"^(?:/(?!api/v1/)|[A-Za-z]:[\\/]|file://)", re.IGNORECASE)


class CampaignCatalogContractError(ValueError):
    """Raised when a catalog or card payload violates its contract."""


def load_campaign_catalog_v1_schema() -> dict[str, Any]:
    return json.loads(Path(__file__).with_name("campaign_catalog_v1.schema.json").read_text(encoding="utf-8"))


def load_campaign_card_v1_schema() -> dict[str, Any]:
    return json.loads(Path(__file__).with_name("campaign_card_v1.schema.json").read_text(encoding="utf-8"))


def _fail(message: str) -> None:
    raise CampaignCatalogContractError(message)


def _exact(value: Any, keys: tuple[str, ...], field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or tuple(value) != keys:
        _fail(f"{field} keys differ from the contract")
    return value


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        _fail(f"{field} must be a finite number")
    return float(value)


def _integer(value: Any, field: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _fail(f"{field} must be an integer >= {minimum}")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{field} must be a non-empty string")
    return value


def _date(value: Any, field: str) -> date:
    if not isinstance(value, str):
        _fail(f"{field} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError:
        _fail(f"{field} is not an ISO date")
    raise AssertionError  # pragma: no cover


def _datetime(value: Any, field: str) -> None:
    if not isinstance(value, str):
        _fail(f"{field} must be an ISO date-time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail(f"{field} is not an ISO date-time")
        return
    if parsed.tzinfo is None:
        _fail(f"{field} must carry a timezone")


def _close(left: float, right: float, absolute: float) -> bool:
    return abs(left - right) <= max(absolute, 1e-9 * max(abs(left), abs(right)))


def _reject_paths(value: Any, field: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            _reject_paths(nested, f"{field}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_paths(nested, f"{field}[{index}]")
    elif isinstance(value, str) and _ABSOLUTE_PATH_RE.match(value):
        _fail(f"Local or absolute path is forbidden at {field}")


def _range(value: Any, field: str) -> Mapping[str, float] | None:
    if value is None:
        return None
    _exact(value, RANGE_KEYS, field)
    low = _number(value["low"], f"{field}.low")
    estimate = _number(value["estimate"], f"{field}.estimate")
    high = _number(value["high"], f"{field}.high")
    tolerance = 1e-9 * max(1.0, abs(low), abs(high))
    if low > estimate + tolerance or estimate > high + tolerance:
        _fail(f"{field} must satisfy low <= estimate <= high")
    return value


def _validate_explanation(value: Any, field: str) -> None:
    """Why the campaign got its number: kept + own saturation + overlap is the whole first-ruble potential."""

    _exact(value, EXPLANATION_KEYS, field)
    _text(value["rules_version"], f"{field}.rules_version")
    for key in ("potential_turnover_rub", "first_ruble_roas", "typical_first_ruble_roas"):
        if _number(value[key], f"{field}.{key}") < 0:
            _fail(f"{field}.{key} must be non-negative")
    for key in ("kept_share", "own_saturation_share", "overlap_share", "unseen_budget_share", "tail_share"):
        if not 0.0 <= _number(value[key], f"{field}.{key}") <= 1.0:
            _fail(f"{field}.{key} must be a share")
    if abs(value["kept_share"] + value["own_saturation_share"] + value["overlap_share"] - 1.0) > 1e-6:
        _fail(f"{field} shares do not add up to the potential")
    for key in ("own_saturation_cities", "overlap_cities"):
        names = value[key]
        if (
            not isinstance(names, list)
            or len(names) > 2
            or any(not isinstance(item, str) or not item.strip() for item in names)
            or len(set(names)) != len(names)
        ):
            _fail(f"{field}.{key} must hold up to two names")
    reasons = value["reasons"]
    if not isinstance(reasons, list) or len(reasons) > 3:
        _fail(f"{field}.reasons must hold zero to three reasons")
    _validate_notes(reasons, f"{field}.reasons")


def validate_campaign_record(record: Any, field: str = "campaign") -> Mapping[str, Any]:
    """One campaign of the catalog: fields, dates, channel budgets, effects and ROAS = turnover / budget."""

    _exact(record, CAMPAIGN_KEYS, field)
    number = _integer(record["number"], f"{field}.number", 1)
    field = f"{field} №{number}"
    _text(record["name"], f"{field}.name")
    directions = record["directions"]
    if (
        not isinstance(directions, list)
        or not directions
        or len(set(directions)) != len(directions)
        or any(item not in DIRECTIONS for item in directions)
    ):
        _fail(f"{field}.directions are invalid")
    start = _date(record["start_date"], f"{field}.start_date")
    end = _date(record["end_date"], f"{field}.end_date")
    days = _integer(record["days_n"], f"{field}.days_n", 1)
    if end < start or days != (end - start).days + 1:
        _fail(f"{field} dates and days differ")
    expected_group = "120_days_and_longer" if days >= LONG_DAYS else "up_to_120_days"
    if record["duration_group"] != expected_group:
        _fail(f"{field}.duration_group differs from days_n")
    budget = _number(record["budget_rub"], f"{field}.budget_rub")
    if budget < 0:
        _fail(f"{field}.budget_rub must be non-negative")
    channels = record["channels"]
    if not isinstance(channels, list) or not channels:
        _fail(f"{field}.channels must be a non-empty list")
    order: list[int] = []
    for index, channel in enumerate(channels):
        _exact(channel, CHANNEL_KEYS, f"{field}.channels[{index}]")
        channel_id = channel["channel_id"]
        if CHANNEL_DISPLAY.get(channel_id) != channel["display_name"]:
            _fail(f"{field}.channels[{index}] channel is unknown")
        if _number(channel["budget_rub"], f"{field}.channels[{index}].budget_rub") < 0:
            _fail(f"{field}.channels[{index}].budget_rub must be non-negative")
        if not isinstance(channel["nationwide"], bool):
            _fail(f"{field}.channels[{index}].nationwide must be boolean")
        order.append(CHANNEL_ORDER[channel_id])
    if order != sorted(set(order)):
        _fail(f"{field}.channels must be unique and in the catalog order")
    if not _close(math.fsum(float(row["budget_rub"]) for row in channels), budget, max(0.01, 1e-9 * budget)):
        _fail(f"{field} channel budgets do not add up to its budget")
    largest = min(channels, key=lambda row: (-float(row["budget_rub"]), CHANNEL_ORDER[row["channel_id"]]))
    if record["main_channel_id"] != largest["channel_id"]:
        _fail(f"{field}.main_channel_id is not its largest channel")
    for list_field in ("cities", "nationwide_channels"):
        values = record[list_field]
        if (
            not isinstance(values, list)
            or any(not isinstance(item, str) or not item.strip() for item in values)
            or len(set(values)) != len(values)
        ):
            _fail(f"{field}.{list_field} must be unique names")
    if record["nationwide_channels"] != [row["display_name"] for row in channels if row["nationwide"]]:
        _fail(f"{field}.nationwide_channels differ from its channels")
    effects = {key: _range(record[key], f"{field}.{key}") for key in EFFECT_KEYS}
    status = record["status"]
    if status == "computed":
        if record["status_display_text"] is not None or effects["turnover_increment_rub"] is None:
            _fail(f"{field} computed campaign must carry its turnover effect")
        if budget > 0:
            if effects["roas"] is None:
                _fail(f"{field} computed campaign must carry ROAS")
            for key in RANGE_KEYS:
                ratio = float(effects["turnover_increment_rub"][key]) / budget
                if not _close(float(effects["roas"][key]), ratio, 1e-9):
                    _fail(f"{field} ROAS differs from turnover / budget")
        elif effects["roas"] is not None:
            _fail(f"{field} ROAS without budget")
    elif status == "not_computed":
        if any(value is not None for value in effects.values()):
            _fail(f"{field} not computed campaign must not carry effects")
        _text(record["status_display_text"], f"{field}.status_display_text")
        if record["reliable"] != 0:
            _fail(f"{field} not computed campaign cannot be reliable")
    else:
        _fail(f"{field}.status is invalid")
    _integer(record["overlaps_n"], f"{field}.overlaps_n")
    if record["reliable"] not in (0, 1) or isinstance(record["reliable"], bool):
        _fail(f"{field}.reliable must be 0 or 1")
    if record["explanation"] is not None:
        if status != "computed":
            _fail(f"{field} not computed campaign cannot carry an explanation")
        _validate_explanation(record["explanation"], f"{field}.explanation")
    return record


def _validate_notes(notes: Any, field: str = "notes") -> None:
    if not isinstance(notes, list):
        _fail(f"{field} must be a list")
    for index, row in enumerate(notes):
        _exact(row, ("code", "display_text"), f"{field}[{index}]")
        if not isinstance(row["code"], str) or not _NOTE_CODE_RE.fullmatch(row["code"]):
            _fail(f"{field}[{index}].code is invalid")
        _text(row["display_text"], f"{field}[{index}].display_text")
    if len({row["code"] for row in notes}) != len(notes):
        _fail(f"{field} repeat a code")


def _validate_summary(summary: Any, campaigns: list[Mapping[str, Any]]) -> None:
    _exact(summary, SUMMARY_KEYS, "summary")
    computed = [row for row in campaigns if row["status"] == "computed"]
    computed_budget = math.fsum(float(row["budget_rub"]) for row in computed)
    turnover = math.fsum(float(row["turnover_increment_rub"]["estimate"]) for row in computed)
    expected_counts = {
        "campaigns_n": len(campaigns),
        "computed_n": len(computed),
        "reliable_n": sum(int(row["reliable"]) for row in campaigns),
        "up_to_120_days_n": sum(row["duration_group"] == "up_to_120_days" for row in campaigns),
        "longer_120_days_n": sum(row["duration_group"] == "120_days_and_longer" for row in campaigns),
    }
    for key, value in expected_counts.items():
        if summary[key] != value:
            _fail(f"summary.{key} differs from the campaigns")
    sums = {
        "budget_rub": math.fsum(float(row["budget_rub"]) for row in campaigns),
        "computed_budget_rub": computed_budget,
        "turnover_increment_rub": turnover,
    }
    for key, value in sums.items():
        if not _close(_number(summary[key], f"summary.{key}"), value, 1e-6):
            _fail(f"summary.{key} differs from the campaigns")
    weighted = summary["weighted_roas"]
    if computed_budget > 0:
        if not _close(_number(weighted, "summary.weighted_roas"), turnover / computed_budget, 1e-12):
            _fail("summary.weighted_roas differs from the campaigns")
    elif weighted is not None:
        _fail("summary.weighted_roas must be null without computed budget")


def _validate_campaign_list(campaigns: Any) -> list[Mapping[str, Any]]:
    if not isinstance(campaigns, list):
        _fail("campaigns must be a list")
    for index, record in enumerate(campaigns):
        validate_campaign_record(record, f"campaigns[{index}]")
    numbers = [row["number"] for row in campaigns]
    if numbers != sorted(set(numbers)):
        _fail("campaign numbers must be unique and ascending")
    return campaigns


def validate_campaign_catalog_v1(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Whole catalog: available (bound package artifact) or an empty unavailable state."""

    _exact(payload, CATALOG_KEYS, "catalog")
    if payload["contract_name"] != CATALOG_CONTRACT_NAME or payload["schema_version"] != SCHEMA_VERSION:
        _fail("Campaign catalog contract mismatch")
    if payload["title"] != TITLE:
        _fail("Campaign catalog title is invalid")
    _text(payload["display_text"], "display_text")
    if not isinstance(payload["package_id"], str) or not _PACKAGE_ID_RE.fullmatch(payload["package_id"]):
        _fail("package_id is invalid")
    origin, status = payload["record_origin"], payload["status"]
    if origin == "model_package_artifact_unavailable":
        if status != "unavailable":
            _fail("Unavailable catalog must have status unavailable")
        for key in (
            "artifact_id",
            "catalog_version",
            "model_display_name",
            "period_start",
            "period_end",
            "roas_level_label",
            "summary",
            "download",
            "updated_at_utc",
        ):
            if payload[key] is not None:
                _fail(f"Unavailable catalog field must be null: {key}")
        if payload["campaigns"] != [] or payload["notes"] != []:
            _fail("Unavailable catalog must not contain campaigns or notes")
        if payload["model_version"] is not None:
            _text(payload["model_version"], "model_version")
        _reject_paths(payload)
        return payload
    if origin != "verified_model_package_artifact" or status != "available":
        _fail("record_origin and status are invalid")
    if not isinstance(payload["artifact_id"], str) or not _ARTIFACT_ID_RE.fullmatch(payload["artifact_id"]):
        _fail("artifact_id is invalid")
    for key in ("model_version", "model_display_name", "catalog_version", "roas_level_label"):
        _text(payload[key], key)
    if _date(payload["period_end"], "period_end") < _date(payload["period_start"], "period_start"):
        _fail("Catalog period is reversed")
    _datetime(payload["updated_at_utc"], "updated_at_utc")
    _validate_notes(payload["notes"])
    campaigns = _validate_campaign_list(payload["campaigns"])
    if not campaigns:
        _fail("Available catalog must contain campaigns")
    _validate_summary(payload["summary"], campaigns)
    download = payload["download"]
    if download is not None:
        _exact(download, ("file_name", "size_bytes", "sha256", "download_path", "sheets"), "download")
        name = _text(download["file_name"], "download.file_name")
        if not name.endswith(".xlsx") or "/" in name or "\\" in name:
            _fail("download.file_name is invalid")
        _integer(download["size_bytes"], "download.size_bytes", 1)
        if not isinstance(download["sha256"], str) or not _SHA256_RE.fullmatch(download["sha256"]):
            _fail("download.sha256 is invalid")
        if download["download_path"] != DOWNLOAD_PATH:
            _fail("download.download_path is invalid")
        if download["sheets"] != list(WORKBOOK_SHEETS):
            _fail("download.sheets differ from the catalog workbook")
    _reject_paths(payload)
    return payload


def validate_campaign_card_v1(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """One campaign of the bound catalog."""

    _exact(payload, CARD_KEYS, "card")
    if payload["contract_name"] != CARD_CONTRACT_NAME or payload["schema_version"] != SCHEMA_VERSION:
        _fail("Campaign card contract mismatch")
    if payload["record_origin"] != "verified_model_package_artifact":
        _fail("Campaign card must come from a verified package artifact")
    if not isinstance(payload["package_id"], str) or not _PACKAGE_ID_RE.fullmatch(payload["package_id"]):
        _fail("package_id is invalid")
    if not isinstance(payload["artifact_id"], str) or not _ARTIFACT_ID_RE.fullmatch(payload["artifact_id"]):
        _fail("artifact_id is invalid")
    for key in ("model_version", "model_display_name", "catalog_version", "roas_level_label"):
        _text(payload[key], key)
    if _date(payload["period_end"], "period_end") < _date(payload["period_start"], "period_start"):
        _fail("Catalog period is reversed")
    _datetime(payload["updated_at_utc"], "updated_at_utc")
    _validate_notes(payload["notes"])
    validate_campaign_record(payload["campaign"])
    _reject_paths(payload)
    return payload


__all__ = [
    "CARD_CONTRACT_NAME",
    "CATALOG_CONTRACT_NAME",
    "CampaignCatalogContractError",
    "DOWNLOAD_PATH",
    "SCHEMA_VERSION",
    "TITLE",
    "WORKBOOK_SHEETS",
    "load_campaign_card_v1_schema",
    "load_campaign_catalog_v1_schema",
    "validate_campaign_card_v1",
    "validate_campaign_catalog_v1",
    "validate_campaign_record",
]
