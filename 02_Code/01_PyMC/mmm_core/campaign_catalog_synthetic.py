"""Synthetic catalog and package folders for tests and local previews of the campaign catalog extension.

Never used by a real build: the names are «Тестовая кампания N» and every number is made up. The files have the same
format as the output of 09_weekly_joint_campaign_catalog.py and a weekly package folder, so the extension builder and
the portal can be exercised end to end without the Mac.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .campaign_catalog_extension import (
    CHANNELS,
    SOURCE_CHANNEL_KEYS,
    PackageIdentity,
    build_extension,
    load_source_catalog,
    sha256_file,
)

CITIES = (
    "Москва", "Санкт-Петербург", "Казань", "Екатеринбург", "Новосибирск", "Нижний Новгород", "Самара",
    "Краснодар", "Ростов-на-Дону", "Воронеж", "Пермь", "Уфа",
)
SEGMENTS = ("ТС5/Онлайн", "ТС5/Оффлайн", "ТСХ/Онлайн", "ТСХ/Оффлайн")
_KEY_BY_ID = {channel_id: key for key, channel_id in SOURCE_CHANNEL_KEYS.items()}
_MODEL_CHANNELS = ("Digital_Performance", "OOH_Total", "Радио", "Нац_ТВ", "Рег_ТВ")


def synthetic_model_roas(segment_index: int, channel_index: int) -> float:
    """Model ROAS of one direction × channel cell; the catalog check file and the package table both use it."""

    return round(1.0 + 0.1 * segment_index + 0.05 * channel_index, 6)


def _unit(seed: int) -> float:
    """Deterministic pseudo-random number in [0, 1)."""

    digest = hashlib.sha256(f"campaign-catalog-synthetic-{seed}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def synthetic_results(campaigns_n: int = 12) -> list[dict[str, Any]]:
    """Rows in the catalog_results.json shape; one campaign is outside the model, two have flag 0."""

    rows: list[dict[str, Any]] = []
    number = 0
    for index in range(campaigns_n):
        number += 2 if index == 5 else 1          # one number is skipped, as after a merge in the real directory
        start = date(2025, 1, 6) + timedelta(days=int(_unit(index) * 480))
        days = 200 if index % 5 == 0 else 7 + int(_unit(index + 100) * 80)
        end = start + timedelta(days=days - 1)
        if end > date(2026, 6, 30):
            end = date(2026, 6, 30)
            days = (end - start).days + 1
        channel_count = 1 + index % 3
        channel_ids = [CHANNELS[(index + step * 2) % len(CHANNELS)][0] for step in range(channel_count)]
        channel_ids = sorted(set(channel_ids), key=[row[0] for row in CHANNELS].index)
        channels = []
        for step, channel_id in enumerate(channel_ids):
            budget = round(1_000_000 * (0.5 + 40 * _unit(index * 10 + step)), 2)
            display = dict((row[0], row[1]) for row in CHANNELS)[channel_id]
            channels.append(
                {"key": _KEY_BY_ID[channel_id], "name": display, "budget": budget, "federal": channel_id == "Нац_ТВ"}
            )
        budget = sum(row["budget"] for row in channels)
        cities_n = 1 + int(_unit(index + 200) * 9)
        has_regional = any(not row["federal"] for row in channels)
        cities = list(CITIES[index % 3: index % 3 + cities_n]) if has_regional else []
        if index == 9 and cities:
            # the real geography lists regions next to cities (money of the region outside its big cities)
            cities += ["Нижегородская область", "Республика Татарстан"]
        directions = sorted({SEGMENTS[index % 4]} | ({SEGMENTS[(index + 1) % 4]} if index % 4 == 3 else set()))
        modeled = index != 4
        roas_mid = 0.25 + 2.4 * _unit(index + 300)
        turnover = (0.7 * roas_mid * budget, roas_mid * budget, 1.4 * roas_mid * budget) if modeled else (0.0, 0.0, 0.0)
        # Magnitudes as in the real catalog of 05.11.2026: orders per 1000 buyers from thousandths to about ten
        # (median 0.06); the average basket moves by fractions of a kopeck with a range around zero, a few
        # campaigns by tens of kopecks.
        orders_mid = 10 ** (-3 + 4 * _unit(index + 400))
        orders = (0.7 * orders_mid, orders_mid, 1.4 * orders_mid)
        basket_mid = 10 ** (-4 + 3.5 * _unit(index + 500))
        basket = (0.4 * basket_mid, basket_mid, 1.8 * basket_mid) if basket_mid > 0.05 else (-2 * basket_mid, basket_mid, 4 * basket_mid)
        rows.append(
            {
                "id": number,
                "name": f"Тестовая кампания {number}",
                "card": {
                    "dirs": directions,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "days": days,
                    "channels": channels,
                    "cities": cities,
                    "federal": [row["name"] for row in channels if row["federal"]],
                    "budget": budget,
                },
                "budget": budget,
                "modeled": modeled,
                "flag": 0 if (not modeled or index in (2, 7)) else 1,
                "turnover": list(turnover),
                "roas": [value / budget for value in turnover],
                "orders1000": list(orders) if modeled else [float("nan")] * 3,
                "basket": list(basket) if modeled else [float("nan")] * 3,
                "seen_rub": budget if modeled else 0.0,
                "ok_rub": budget if modeled else 0.0,
                "unseen_rub": 0.0 if modeled else budget,
                "overlap": int(_unit(index + 600) * 6),
                "by_channel": {},
            }
        )
    return rows


def _numbers_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for x in results:
        card, modeled = x["card"], x["modeled"]
        row: dict[str, Any] = {
            "номер": x["id"], "кампания": x["name"], "направления": ", ".join(card["dirs"]), "старт": card["start"],
            "конец": card["end"], "дней": card["days"], "лист": "длиннее 120 дней" if card["days"] >= 120 else "до 120 дней",
            "бюджет_млн": round(x["budget"] / 1e6, 4),
        }
        for channel in card["channels"]:
            row[f"бюджет_{channel['name']}_млн"] = round(channel["budget"] / 1e6, 4)
        row.update(
            модель_считает=int(modeled),
            оборот_оценка_млн=round(x["turnover"][1] / 1e6, 4) if modeled else "",
            оборот_от_млн=round(x["turnover"][0] / 1e6, 4) if modeled else "",
            оборот_до_млн=round(x["turnover"][2] / 1e6, 4) if modeled else "",
            roas_оценка=round(x["roas"][1], 4) if modeled else "",
            roas_от=round(x["roas"][0], 4) if modeled else "",
            roas_до=round(x["roas"][2], 4) if modeled else "",
            флаг=x["flag"],
            пересечения=x["overlap"],
        )
        rows.append(row)
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in columns})


def write_synthetic_catalog_dir(root: Path, *, campaigns_n: int = 12, npz_sha256: str = "a" * 64) -> Path:
    """Write the five catalog files that the extension builder reads."""

    root.mkdir(parents=True, exist_ok=True)
    results = synthetic_results(campaigns_n)
    meta = {
        "code_version": "campaign_catalog_weekly_joint_v4_synthetic",
        "n_campaigns": len(results),
        "n_draws": 40,
        "calc_seconds": 75,
        "finished_utc": "05.11.2026 03:10",
        "adstock_weeks": 8,
        "tail_weeks": 7,
        "tail_other": "analog",
        "inputs": {
            "npz": {"path": "synthetic/posterior_roas_params_production.npz", "sha256": npz_sha256},
            "ledger": {"path": "synthetic/ledger", "sha256": "b" * 64},
        },
        "code_sha256": {"09_weekly_joint_campaign_catalog.py": "c" * 64},
    }
    checks = {
        "numbers": {},
        "sum_campaigns_le_full": {"violations": 0, "cells": 400, "max_ratio": 0.81},
        "modeled": sum(int(row["modeled"]) for row in results),
        "flag1": sum(int(row["flag"]) for row in results),
    }
    keyed = {str(index): row for index, row in enumerate(results)}
    (root / "catalog_results.json").write_text(
        json.dumps({"results": keyed, "meta": meta, "checks": checks}, ensure_ascii=False), encoding="utf-8"
    )
    (root / "checks.json").write_text(json.dumps({"meta": meta, "checks": checks}, ensure_ascii=False), encoding="utf-8")
    _write_csv(root / "catalog_numbers.csv", _numbers_rows(results))
    _write_csv(
        root / "catalog_by_channel.csv",
        [{"номер": row["id"], "кампания": row["name"], "направление": row["card"]["dirs"][0]} for row in results],
    )
    roas_rows = []
    for s_index, segment in enumerate(SEGMENTS):
        for c_index, channel in enumerate(_MODEL_CHANNELS):
            roas_rows.append(
                {
                    "segment": segment,
                    "channel": channel,
                    "model_roas_fit_rows": synthetic_model_roas(s_index, c_index),
                    "catalog_roas_seen_money": 0.9,
                    "sum_campaign_effect_over_full": 0.7,
                }
            )
    _write_csv(root / "check_catalog_vs_model_roas.csv", roas_rows)
    return root


def write_synthetic_package_dir(
    root: Path,
    *,
    npz_sha256: str = "a" * 64,
    panel_sha256: str = "d" * 64,
    roas_interval: float | None = None,
) -> tuple[Path, str]:
    """Write a minimal weekly package folder (manifest fingerprint over its files); return it and its package_id.

    roas_interval adds roas_q05 / roas_q95 = median * (1 -/+ roas_interval) to the ROAS table, as a real package has.
    """

    root.mkdir(parents=True, exist_ok=True)
    (root / "run_config.json").write_text(json.dumps({"npz_sha256": npz_sha256}), encoding="utf-8")
    roas_rows = []
    for s_index, segment in enumerate(SEGMENTS):
        for c_index, channel in enumerate(_MODEL_CHANNELS):
            median = synthetic_model_roas(s_index, c_index)
            row: dict[str, Any] = {"segment": segment, "channel": channel, "roas_median": median}
            if roas_interval is not None:
                row.update(roas_q05=median * (1 - roas_interval), roas_q95=median * (1 + roas_interval))
            roas_rows.append(row)
    _write_csv(root / "model_roas_table.csv", roas_rows)
    files = {name: sha256_file(root / name) for name in ("run_config.json", "model_roas_table.csv")}
    fingerprint = hashlib.sha256(json.dumps(files, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    manifest = {
        "package_type": "weekly_joint_v1",
        "model_name": "Заноза",
        "model_run_id": "Заноза_synthetic_production",
        "roas_level_label_ru": "уровень ROAS по отрасли",
        "files": files,
        "package_input_fingerprint": fingerprint,
    }
    (root / "model_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return root, f"pkg_{fingerprint[:16]}_{panel_sha256[:16]}"


def write_synthetic_extension(
    out_dir: Path,
    *,
    package_id: str,
    package_input_fingerprint: str,
    model_run_id: str,
    scratch_dir: Path,
    campaigns_n: int = 12,
    model_display_name: str = "Заноза",
    generated_at_utc: str = "2026-11-05T05:00:00+00:00",
    npz_sha256: str = "a" * 64,
) -> dict[str, Any]:
    """Build a synthetic extension bound to a given registry identity (for portal tests); return its metadata."""

    catalog_dir = write_synthetic_catalog_dir(
        scratch_dir / "synthetic_catalog", campaigns_n=campaigns_n, npz_sha256=npz_sha256
    )
    roas_rows = tuple(
        {"segment": segment, "channel": channel, "roas_median": str(synthetic_model_roas(s_index, c_index))}
        for s_index, segment in enumerate(SEGMENTS)
        for c_index, channel in enumerate(_MODEL_CHANNELS)
    )
    identity = PackageIdentity(
        package_id=package_id,
        package_input_fingerprint=package_input_fingerprint,
        model_run_id=model_run_id,
        model_display_name=model_display_name,
        roas_level_label="уровень ROAS по отрасли",
        npz_sha256=npz_sha256,
        model_roas_rows=roas_rows,
        source="synthetic_fixture",
    )
    return build_extension(
        source=load_source_catalog(catalog_dir),
        identity=identity,
        out_dir=out_dir,
        catalog_version="synthetic_catalog_v1",
        generated_at_utc=generated_at_utc,
    )


__all__ = [
    "synthetic_model_roas",
    "synthetic_results",
    "write_synthetic_catalog_dir",
    "write_synthetic_extension",
    "write_synthetic_package_dir",
]
