"""Data refresh workflow for X5 MMM panel v2.

The workflow intentionally stays compact:
- load corrected 2025-2026 agency media workbook;
- apply explicit media-geo mapping/distribution;
- combine 2025 target history with new 2026 target data;
- assemble model-ready controls and media bundles;
- write a v2 parquet plus lightweight audit files.

This script does not run PyMC. Model runs remain a separate layer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import sys
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYMC_CODE_DIR = PROJECT_ROOT / "02_Code" / "01_PyMC"
if str(PYMC_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(PYMC_CODE_DIR))

from mmm_core.io import project_root


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("data_refresh_v2")


START_DATE = pd.Timestamp("2025-01-01")
END_DATE = pd.Timestamp("2026-05-31")

OFFLINE_MARKER_TO_SEGMENT = {
    "ТС5": {"network": "ТС5", "channel": "Онлайн"},
    "ПЯТЕРОЧКА ОФФЛАЙН": {"network": "ТС5", "channel": "Оффлайн"},
    "ПЕРЕКРЕСТОК ОФФЛАЙН": {"network": "ТСХ", "channel": "Оффлайн"},
    "ТСХ": {"network": "ТСХ", "channel": "Онлайн"},
}

DIGITAL_SHEETS = {
    "ТСХ_доставка": {"network": "ТСХ", "channel": "Онлайн"},
    "ТС5_доставка": {"network": "ТС5", "channel": "Онлайн"},
    "Перек_оффл": {"network": "ТСХ", "channel": "Оффлайн"},
    "5_оффл": {"network": "ТС5", "channel": "Оффлайн"},
}

CHANNEL_TYPE_CANONICAL = {
    "ООН": "OOH",
    "OOH": "OOH",
    "ООН РТБ": "ООН РТБ",
    "ООН_РТБ": "ООН РТБ",
}

SOURCE_TO_CHANNEL = {
    "yandex direct": "Paid Search",
    "yandex geo": "Paid Search",
    "yandex": "Paid Search",
    "яндекс": "Paid Search",
    "vk": "Paid Social",
    "telegram": "Paid Social",
    "tgads": "Paid Social",
    "tg ads": "Paid Social",
    "my target": "Paid Social",
    "ozon": "Marketplace Ads",
    "wildberries": "Marketplace Ads",
    "avito": "Marketplace Ads",
    "авито": "Marketplace Ads",
    "sberseller": "Marketplace Ads",
    "tbank": "Marketplace Ads",
    "buzzoola": "Programmatic",
    "yabbi": "Programmatic",
    "hybrid": "Programmatic",
    "weborama": "Programmatic",
    "mobidriven": "Programmatic",
    "byyd": "Programmatic",
    "bidease": "Programmatic",
    "roxot": "Programmatic",
    "segmento": "Programmatic",
    "everest": "Programmatic",
    "astralab": "Programmatic",
    "mywaymag": "Programmatic",
    "cityworld": "Programmatic",
    "plazkart": "Programmatic",
    "vox": "Programmatic",
    "redllama": "Programmatic",
    "digital_alliance": "Programmatic",
    "digital alliance": "Programmatic",
    "omedia": "Programmatic",
    "genius": "Programmatic",
    "between": "Programmatic",
    "betweenx": "Programmatic",
    "otclick": "Programmatic",
    "adspector": "Programmatic",
    "first data": "Programmatic",
    "unisound": "Programmatic",
    "gnezdo": "Programmatic",
    "soloway": "Programmatic",
    "roden media": "Programmatic",
    "adcamp": "Programmatic",
    "punch media": "Programmatic",
    "hsm": "Programmatic",
    "uplify": "Programmatic",
    "mts": "Telecom Ads",
    "beeline": "Telecom Ads",
    "huawei": "Telecom Ads",
    "koshelek": "App Ads",
    "pim media": "App Ads",
    "ivi": "Video Ads",
    "rutube": "Video Ads",
    "gpm": "Video Ads",
    "ctv-house": "Video Ads",
    "rbc": "Premium Publishers",
}

OFFLINE_MEDIA_SPEND_COLS = [
    "spend_Нац_ТВ",
    "spend_Рег_ТВ",
    "spend_OOH",
    "spend_ООН_РТБ",
    "spend_Радио",
    "spend_Indoor",
]
OOH_TOTAL_GROUP_COL = "spend_OOH_Total"
OOH_TOTAL_INPUT_COLS = ["spend_OOH", "spend_ООН_РТБ"]
DIGITAL_RAW_SPEND_INPUTS = [
    "spend_Programmatic",
    "spend_Paid_Search",
    "spend_Paid_Social",
    "spend_Marketplace_Ads",
    "spend_Telecom_Ads",
    "spend_App_Ads",
    "spend_Video_Ads",
    "spend_Premium_Publishers",
    "spend_Other_Digital",
]
MODEL_READY_MEDIA_GROUP_COLS = ["spend_Digital_Performance", OOH_TOTAL_GROUP_COL]

RAW_TARGET_COLS = ["orders_cnt", "turnover_total", "unique_users"]
MODEL_TARGET_COLS = ["turnover_per_user", "orders_per_user", "avg_basket"]
TARGET_BUNDLE_COLS = RAW_TARGET_COLS + MODEL_TARGET_COLS
COUNT_TARGET_COLS = {"orders_cnt", "unique_users"}

WEATHER_COLS = [
    "temp_avg_c",
    "temp_max_c",
    "temp_min_c",
    "temp_norm_avg_c",
    "temp_dev_from_norm_c",
    "hdd_18",
    "cdd_18",
    "feels_like_min_c",
    "precipitation_mm",
    "snow_depth_cm",
    "snow_fall_cm",
    "wind_speed_max_ms",
    "is_heatwave_d",
    "is_coldwave_d",
    "is_heavy_rain_d",
    "is_snowy_d",
    "is_freezing_d",
    "is_extreme_cold_d",
    "is_hot_d",
    "is_extreme_heat_d",
    "is_rainy_d",
    "weather_drives_indoor_d",
]

COMPET_CHANNEL_RENAME = {"Нац ТВ": "NacTV", "Рег ТВ": "RegTV", "ООН": "OOH", "OOH": "OOH"}
COMPET_OUT_COLS = ["compet_spend_NacTV", "compet_spend_RegTV", "compet_spend_OOH"]
CITY_TO_PARENT_REGION = {
    "БЕРДСК": "НОВОСИБИРСКАЯ ОБЛАСТЬ",
    "НОВОКУЗНЕЦК": "КЕМЕРОВСКАЯ ОБЛАСТЬ",
    "НОВОКУЙБЫШЕВСК": "САМАРСКАЯ ОБЛАСТЬ",
    "НОВОЧЕБОКСАРСК": "РЕСПУБЛИКА ЧУВАШИЯ",
}

# Population and weather controls for v2 are strict upstream artifacts.
# Do not approximate them in the panel assembler: missing geo reference or weather
# coverage must fail loudly and be fixed in the source/reference layer.


@dataclass(frozen=True)
class RefreshPaths:
    root: Path
    run_id: str
    config_path: Path | None
    v2_dir: Path
    raw_v2: Path
    output_dir: Path
    panel_start: pd.Timestamp
    panel_end: pd.Timestamp
    media_xlsx: Path
    mapping_csv: Path
    geo_reference_csv: Path
    target_2026: Path
    target_2025: Path
    old_population_xlsx: Path
    old_weather_parquet: Path
    weather_exact_parquet: Path
    usd_rub_csv: Path
    brent_csv: Path
    ruonia_xlsx: Path
    historical_usd_rub_csv: Path
    historical_brent_csv: Path
    historical_ruonia_xlsx: Path
    ruonia_cbr_cache_csv: Path
    fetch_ruonia_from_cbr: bool
    output_panel: Path
    promoted_panel: Path
    promotion_target_panel: Path
    panel_preflight_summary: Path
    allow_overwrite_candidate: bool


@dataclass(frozen=True)
class TargetImputationPatch:
    row_index: int
    date: str
    geo_label: str
    network: str
    channel: str
    method: str
    window_days: int | None
    peer_rows: int
    column: str
    old_value: float | int | str | None
    new_value: float | int | str | None


def norm_text(value: object) -> str:
    if pd.isna(value):
        return ""
    return " ".join(str(value).strip().upper().replace("Ё", "Е").split())


def safe_date(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, format="%d.%m.%Y", errors="coerce")
    fallback = pd.to_datetime(series, errors="coerce", dayfirst=True)
    return parsed.fillna(fallback)


def parse_float_ru(value: object) -> float:
    if pd.isna(value):
        return np.nan
    text = str(value).strip().replace("\ufeff", "").replace(" ", "")
    if not text:
        return np.nan
    text = text.replace("%", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return np.nan


def spend_col_name(channel: str) -> str:
    clean = str(channel).replace(" ", "_").replace("/", "_").replace("ё", "е").replace("Ё", "Е")
    return f"spend_{clean}"


def resolve_paths(config_path: Path | None) -> RefreshPaths:
    root = project_root()
    default_2025 = root / "00_Data" / "01_2025_first_pass"
    default_v2 = root / "00_Data" / "02_2025_2026Q1_second_pass"
    raw_v2 = default_v2 / "01_Raw_Data_v2"

    cfg = {}
    if config_path and config_path.exists():
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    def configured_path(section: str, key: str, default: Path) -> Path:
        value = (cfg.get(section) or {}).get(key)
        path = Path(value) if value else default
        return path.resolve() if path.is_absolute() else (root / path).resolve()

    v2_dir = configured_path("paths", "v2_dir", default_v2)
    raw_v2 = configured_path("paths", "raw_v2_dir", v2_dir / "01_Raw_Data_v2")
    output_dir = configured_path("paths", "output_dir", v2_dir)
    assembly = cfg.get("assembly") or {}
    controls = cfg.get("control_sources") or {}
    ruonia_control = controls.get("ruonia") or {}
    panel_start = pd.Timestamp(assembly.get("panel_start_date") or START_DATE)
    panel_end = pd.Timestamp(assembly.get("panel_end_date") or END_DATE)
    if panel_end < panel_start:
        raise ValueError("assembly.panel_end_date must be on or after panel_start_date")

    return RefreshPaths(
        root=root,
        run_id=str(cfg.get("run_id") or "data_refresh"),
        config_path=config_path.resolve() if config_path else None,
        v2_dir=v2_dir,
        raw_v2=raw_v2,
        output_dir=output_dir,
        panel_start=panel_start,
        panel_end=panel_end,
        media_xlsx=configured_path("input_files", "media_agency", raw_v2 / "2025-2026_26_06.xlsx"),
        mapping_csv=configured_path("input_files", "geo_mapping", raw_v2 / "geo_mapping_media_to_model_v2.csv"),
        geo_reference_csv=configured_path("input_files", "geo_reference", raw_v2 / "geo_reference_v2.csv"),
        target_2026=configured_path("input_files", "targets_2026", raw_v2 / "daily_metrics_by_region_itog.parquet"),
        target_2025=configured_path(
            "assembly",
            "historical_target",
            default_2025 / "01_Raw_Data" / "target_features_for_MMM.parquet",
        ),
        old_population_xlsx=default_2025 / "01_Raw_Data" / "population_geo_rosstat_for_MMM.xlsx",
        old_weather_parquet=root
        / "00_Data"
        / "01_2025_first_pass"
        / "01_Raw_Data"
        / "weather_features_2024-01-01_to_2026-05-05.parquet",
        weather_exact_parquet=v2_dir / "weather_features_2025-01-01_to_2026-05-31_v2_exact.parquet",
        usd_rub_csv=configured_path("input_files", "usd_rub", raw_v2 / "Прошлые данные - USD_RUB.csv"),
        brent_csv=configured_path("input_files", "brent", raw_v2 / "Прошлые данные - Фьючерс на нефть Brent.csv"),
        ruonia_xlsx=configured_path("input_files", "ruonia", raw_v2 / "RUONIA_01_2026_T31_05_2026.xlsx"),
        historical_usd_rub_csv=configured_path(
            "input_files",
            "usd_rub_history",
            default_2025 / "01_Raw_Data" / "USD_RUB_01-01-2024-05_to_05-05-2026.csv",
        ),
        historical_brent_csv=configured_path(
            "input_files",
            "brent_history",
            default_2025 / "01_Raw_Data" / "Brent_01-01-2024-05_to_05-05-2026.csv",
        ),
        historical_ruonia_xlsx=configured_path(
            "input_files",
            "ruonia_history",
            default_2025 / "01_Raw_Data" / "RUONIA_for_MMM.xlsx",
        ),
        ruonia_cbr_cache_csv=configured_path(
            "input_files",
            "ruonia_cbr_cache",
            raw_v2 / "RUONIA_CBR_2024-12-01_to_2026-05-31.csv",
        ),
        fetch_ruonia_from_cbr=bool(ruonia_control.get("fetch_if_cache_missing", False)),
        output_panel=configured_path(
            "assembly",
            "output_panel_candidate",
            output_dir / "panel_candidate.parquet",
        ),
        promoted_panel=configured_path(
            "assembly",
            "promoted_panel",
            output_dir / "panel_final_v2.parquet",
        ),
        promotion_target_panel=configured_path(
            "promotion",
            "target_panel",
            v2_dir / "panel_final_v3.parquet",
        ),
        panel_preflight_summary=configured_path(
            "promotion",
            "panel_preflight_summary",
            output_dir / "audits" / "panel_priors_input_summary.json",
        ),
        allow_overwrite_candidate=bool(assembly.get("allow_overwrite_candidate", False)),
    )


def load_mapping(mapping_csv: Path) -> pd.DataFrame:
    mapping = pd.read_csv(mapping_csv)
    mapping["media_geo_norm"] = mapping["media_geo_norm"].map(norm_text)
    mapping["final_model_geo_label_or_rule"] = mapping["final_model_geo_label_or_rule"].fillna("")
    return mapping


def load_population(paths: RefreshPaths, mapping: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not paths.geo_reference_csv.exists():
        raise FileNotFoundError(f"Missing strict geo reference: {paths.geo_reference_csv}")

    ref = pd.read_csv(paths.geo_reference_csv)
    ref["geo_label"] = ref["geo_label"].map(norm_text)
    required_cols = {"geo_label", "geo_type", "n_stores", "population_k", "population_source"}
    missing_cols = sorted(required_cols - set(ref.columns))
    if missing_cols:
        raise ValueError(f"geo_reference_v2.csv is missing required columns: {missing_cols}")

    model_rows = mapping[mapping["include_in_model_or_distribution"].eq("yes")].copy()
    needed_geos = sorted(set(model_rows["final_model_geo_label_or_rule"].map(norm_text)))
    ref = ref.drop_duplicates("geo_label", keep="first")
    missing_geos = sorted(set(needed_geos) - set(ref["geo_label"]))
    if missing_geos:
        raise ValueError(f"Missing geos in strict geo_reference_v2.csv: {missing_geos}")

    pop = ref[ref["geo_label"].isin(needed_geos)].copy()
    pop["population_k"] = pd.to_numeric(pop["population_k"], errors="coerce")
    pop["n_stores"] = pd.to_numeric(pop["n_stores"], errors="coerce")

    provenance_cols = [
        c for c in pop.columns
        if "population" in c.lower() or c in {"n_stores_source", "weather_source_policy"}
    ]
    bad_provenance = pop[provenance_cols].astype(str).apply(
        lambda s: s.str.contains("manual|approx|proxy", case=False, regex=True, na=False)
    ).any(axis=1)
    if bad_provenance.any():
        bad = pop.loc[bad_provenance, ["geo_label"] + provenance_cols].to_dict("records")
        raise ValueError(f"Strict geo reference contains manual/approx/proxy provenance: {bad}")

    audit = pop.copy()
    audit["population_missing"] = audit["population_k"].isna()
    audit["n_stores_missing"] = audit["n_stores"].isna()
    audit["geo_reference_file"] = str(paths.geo_reference_csv)

    if audit["population_missing"].any() or audit["n_stores_missing"].any():
        bad = audit.loc[
            audit["population_missing"] | audit["n_stores_missing"],
            ["geo_label", "population_missing", "n_stores_missing", "population_source"],
        ].to_dict("records")
        raise ValueError(f"Strict geo reference has missing population/n_stores: {bad}")

    return pop, audit


def load_targets(paths: RefreshPaths, model_geos: Iterable[str]) -> pd.DataFrame:
    model_geos = set(model_geos)
    t25 = pd.read_parquet(paths.target_2025)
    t26 = pd.read_parquet(paths.target_2026)
    targets = pd.concat([t25, t26], ignore_index=True)
    targets["date"] = pd.to_datetime(targets["txn_date"])
    targets = targets.drop(columns=["txn_date"])
    targets["geo_label"] = targets["geo_label"].map(norm_text)
    targets["region_upper"] = targets["geo_label"]
    targets = targets[(targets["date"] >= paths.panel_start) & (targets["date"] <= paths.panel_end)].copy()
    targets = targets[targets["geo_label"].isin(model_geos)].copy()
    targets = targets.drop_duplicates(["date", "geo_label", "network", "channel"], keep="last")
    return targets


def load_media_long(media_xlsx: Path, *, panel_start: pd.Timestamp, panel_end: pd.Timestamp) -> pd.DataFrame:
    offline = pd.read_excel(media_xlsx, sheet_name="offline")
    offline = offline.copy()
    offline["date"] = safe_date(offline["date"])
    budget_col = "budget"
    offline["budget"] = pd.to_numeric(offline[budget_col], errors="coerce")
    offline["media_geo_norm"] = offline["region"].map(norm_text)
    offline["campaign_marker_norm"] = offline["campaign_marker"].map(norm_text)
    offline["channel_type"] = (
        offline["channel_type"].astype(str).str.strip().replace(CHANNEL_TYPE_CANONICAL)
    )
    offline["network"] = offline["campaign_marker_norm"].map(
        lambda x: OFFLINE_MARKER_TO_SEGMENT.get(x, {}).get("network")
    )
    offline["channel"] = offline["campaign_marker_norm"].map(
        lambda x: OFFLINE_MARKER_TO_SEGMENT.get(x, {}).get("channel")
    )
    offline = offline.dropna(subset=["date", "budget", "network", "channel", "channel_type"])
    offline = offline[offline["budget"] >= 0].copy()
    offline["sheet"] = "offline"
    offline["campaign_id_for_audit"] = offline.get("campaign_id", "")

    digital_parts = []
    legend_pattern = "Легенда|CTR|Режим|Дубликат|Опечатка|Некорр|Пробел|Регион|Clicks|Бюджет|Отриц"
    for sheet_name, meta in DIGITAL_SHEETS.items():
        df = pd.read_excel(media_xlsx, sheet_name=sheet_name)
        if "date" not in df.columns:
            continue
        df = df[~df["date"].astype(str).str.contains(legend_pattern, na=False)].copy()
        df["date"] = safe_date(df["date"])
        df = df.dropna(subset=["date"])
        budget_col = "budget (шт)" if "budget (шт)" in df.columns else "budget"
        df["budget"] = pd.to_numeric(df[budget_col], errors="coerce")
        region_col = "regions" if "regions" in df.columns else "region"
        df["media_geo_norm"] = df[region_col].map(norm_text)
        src = df.get("source", pd.Series(index=df.index, dtype=object)).astype(str).str.strip().str.lower()
        df["source_norm"] = src.str.replace("ё", "е", regex=False)
        df["channel_type"] = df["source_norm"].map(SOURCE_TO_CHANNEL).fillna("Other Digital")
        df["network"] = meta["network"]
        df["channel"] = meta["channel"]
        df["sheet"] = sheet_name
        df["campaign_id_for_audit"] = df.get("campaign_id", "")
        df = df.dropna(subset=["budget"])
        df = df[df["budget"] >= 0].copy()
        digital_parts.append(
            df[["date", "media_geo_norm", "channel_type", "network", "channel", "budget", "sheet", "campaign_id_for_audit"]]
        )

    media = pd.concat(
        [
            offline[
                ["date", "media_geo_norm", "channel_type", "network", "channel", "budget", "sheet", "campaign_id_for_audit"]
            ],
            *digital_parts,
        ],
        ignore_index=True,
    )
    media = media[(media["date"] >= panel_start) & (media["date"] <= panel_end)].copy()
    log.info(
        "Raw media loaded: %d rows | %.3f млрд RUB | %s -> %s",
        len(media),
        media["budget"].sum() / 1e9,
        media["date"].min().date(),
        media["date"].max().date(),
    )
    return media


def apply_geo_mapping(
    media: pd.DataFrame,
    mapping: pd.DataFrame,
    population: pd.DataFrame,
    targets: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    map_cols = [
        "media_geo_norm",
        "action",
        "final_model_geo_label_or_rule",
        "include_in_model_or_distribution",
        "mapping_rule_note",
    ]
    mm = media.merge(mapping[map_cols], on="media_geo_norm", how="left")
    missing_mapping = mm[mm["action"].isna()]
    if not missing_mapping.empty:
        raise ValueError(f"Unmapped media geos: {sorted(missing_mapping['media_geo_norm'].unique())[:20]}")

    weights = population[["geo_label", "population_k"]].copy()
    weights["population_k"] = pd.to_numeric(weights["population_k"], errors="coerce")
    weights = weights.dropna(subset=["population_k"])
    weights = weights[weights["population_k"] > 0].copy()
    weights["weight"] = weights["population_k"] / weights["population_k"].sum()
    weight_dict = dict(zip(weights["geo_label"], weights["weight"]))

    elig = targets[["date", "network", "channel", "geo_label"]].drop_duplicates().merge(
        population[["geo_label", "population_k"]],
        on="geo_label",
        how="left",
    )
    median_pop = float(population["population_k"].dropna().median())
    elig["population_k"] = pd.to_numeric(elig["population_k"], errors="coerce").fillna(median_pop)
    elig["population_k"] = elig["population_k"].clip(lower=1e-6)
    elig["eligible_weight"] = elig["population_k"] / elig.groupby(["date", "network", "channel"])[
        "population_k"
    ].transform("sum")
    elig = elig.rename(columns={"geo_label": "eligible_geo_label"})
    eligible_set = {
        key: set(grp["eligible_geo_label"])
        for key, grp in elig.groupby(["date", "network", "channel"], sort=False)
    }

    direct = mm[mm["include_in_model_or_distribution"].eq("yes")].copy()
    direct["geo_label"] = direct["final_model_geo_label_or_rule"].map(norm_text)
    direct["mapped_budget"] = direct["budget"]
    direct["mapping_expansion"] = "direct_or_user_map"

    split_parts = []
    split = mm[mm["action"].eq("split_to_components")].copy()
    for _, row in split.iterrows():
        components = [norm_text(x) for x in str(row["final_model_geo_label_or_rule"]).split(";") if norm_text(x)]
        if not components:
            continue
        key = (row["date"], row["network"], row["channel"])
        eligible_components = [c for c in components if c in eligible_set.get(key, set())]
        if eligible_components:
            components = eligible_components
        comp_weights = np.array([weight_dict.get(c, np.nan) for c in components], dtype=float)
        if np.isnan(comp_weights).all() or comp_weights.sum() <= 0:
            comp_weights = np.ones(len(components), dtype=float) / len(components)
        else:
            comp_weights = np.nan_to_num(comp_weights, nan=0.0)
            comp_weights = comp_weights / comp_weights.sum()
        for comp, w in zip(components, comp_weights):
            new = row.copy()
            new["geo_label"] = comp
            new["mapped_budget"] = float(row["budget"]) * float(w)
            new["mapping_expansion"] = "split_to_components_population_weighted"
            split_parts.append(new)
    split_df = pd.DataFrame(split_parts) if split_parts else pd.DataFrame(columns=list(mm.columns) + ["geo_label", "mapped_budget", "mapping_expansion"])

    dist = mm[mm["action"].eq("pro_rata_to_eligible_geos")].copy()
    if not dist.empty:
        dist = dist.merge(elig, on=["date", "network", "channel"], how="left")
        no_elig = dist["eligible_geo_label"].isna()
        if no_elig.any():
            fallback = dist.loc[no_elig, [c for c in mm.columns]].drop_duplicates().merge(
                weights[["geo_label", "weight"]], how="cross"
            )
            fallback = fallback.rename(columns={"geo_label": "eligible_geo_label", "weight": "eligible_weight"})
            dist = pd.concat([dist.loc[~no_elig], fallback], ignore_index=True, sort=False)
        dist["geo_label"] = dist["eligible_geo_label"]
        dist["mapped_budget"] = dist["budget"] * dist["eligible_weight"]
        dist["mapping_expansion"] = "pro_rata_target_eligible_population_weighted"
    else:
        dist = pd.DataFrame(columns=list(mm.columns) + ["geo_label", "weight", "mapped_budget", "mapping_expansion"])

    excluded = mm[mm["include_in_model_or_distribution"].eq("no")].copy()
    out = pd.concat([direct, split_df, dist], ignore_index=True, sort=False)
    out = out.rename(columns={"budget": "source_budget"})
    out["budget"] = out["mapped_budget"].astype(float)
    for col in [
        "campaign_id_for_audit",
        "sheet",
        "media_geo_norm",
        "channel_type",
        "network",
        "channel",
        "action",
        "mapping_rule_note",
        "mapping_expansion",
        "geo_label",
    ]:
        if col in out.columns:
            out[col] = out[col].fillna("").astype(str)

    audit = pd.DataFrame(
        [
            {
                "raw_media_budget_rub": float(media["budget"].sum()),
                "excluded_budget_rub": float(excluded["budget"].sum()) if not excluded.empty else 0.0,
                "mapped_budget_rub": float(out["budget"].sum()),
                "budget_delta_after_expected_exclusion_rub": float(
                    out["budget"].sum() - (media["budget"].sum() - (excluded["budget"].sum() if not excluded.empty else 0.0))
                ),
                "raw_media_geos": int(media["media_geo_norm"].nunique()),
                "mapped_model_geos": int(out["geo_label"].nunique()),
                "excluded_geos": ", ".join(sorted(excluded["media_geo_norm"].unique())) if not excluded.empty else "",
            }
        ]
    )
    return out, audit


def media_to_wide(mapped_media: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    agg = (
        mapped_media.groupby(["date", "geo_label", "network", "channel", "channel_type"], as_index=False)["budget"]
        .sum()
    )
    wide = agg.pivot_table(
        index=["date", "geo_label", "network", "channel"],
        columns="channel_type",
        values="budget",
        aggfunc="sum",
        fill_value=0.0,
    ).reset_index()
    wide.columns.name = None
    spend_cols = []
    for col in [c for c in wide.columns if c not in {"date", "geo_label", "network", "channel"}]:
        new = spend_col_name(col)
        wide = wide.rename(columns={col: new})
        spend_cols.append(new)
    return wide, sorted(spend_cols)


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compare_candidate_to_promoted(
    candidate: pd.DataFrame,
    promoted_path: Path,
    audit_path: Path,
) -> dict[str, object]:
    """Write a column-level shadow diff without mutating either panel."""
    promoted = pd.read_parquet(promoted_path)
    key_columns = ["date", "geo_label", "network", "channel"]
    if candidate.columns.tolist() != promoted.columns.tolist():
        raise ValueError("Candidate/promoted column order differs after canonical schema alignment")
    candidate_keys = candidate[key_columns].reset_index(drop=True).astype(str)
    promoted_keys = promoted[key_columns].reset_index(drop=True).astype(str)
    if not candidate_keys.equals(promoted_keys):
        raise ValueError("Candidate/promoted row keys differ; shadow comparison is not valid")
    expected_control_columns = {
        "usd_rub_close",
        "usd_rub_change_pct",
        "usd_rub_log_return",
        "brent_usd_close",
        "brent_usd_change_pct",
        "brent_log_return",
        "ruonia_rate",
        "ruonia_change",
    }
    cleanup_patch_columns = {
        "orders_cnt",
        "turnover_total",
        "unique_users",
        "avg_basket",
        "turnover_per_user",
        "orders_per_user",
        "turnover_per_user_raw",
        "orders_per_user_raw",
    }
    cleanup_patch_columns.update(
        column for column in candidate.columns if column.startswith("spend_") and column.endswith("_pc")
    )
    rows: list[dict[str, object]] = []
    for column in candidate.columns:
        if pd.api.types.is_numeric_dtype(candidate[column]) and pd.api.types.is_numeric_dtype(promoted[column]):
            equal = pd.Series(
                np.isclose(
                    pd.to_numeric(candidate[column], errors="coerce"),
                    pd.to_numeric(promoted[column], errors="coerce"),
                    rtol=1e-12,
                    atol=1e-9,
                    equal_nan=True,
                ),
                index=candidate.index,
            )
        else:
            equal = candidate[column].eq(promoted[column]) | (
                candidate[column].isna() & promoted[column].isna()
            )
        changed = int((~equal).sum())
        if changed == 0:
            continue
        category = "unexpected_difference"
        if column in expected_control_columns:
            category = "expected_control_history_correction"
        elif column in cleanup_patch_columns:
            category = "published_cleanup_patch_not_reapplied"
        max_abs_diff = ""
        if pd.api.types.is_numeric_dtype(candidate[column]) and pd.api.types.is_numeric_dtype(promoted[column]):
            delta = (pd.to_numeric(candidate[column], errors="coerce") - pd.to_numeric(promoted[column], errors="coerce")).abs()
            max_abs_diff = float(delta.max()) if delta.notna().any() else ""
        rows.append(
            {
                "column": column,
                "changed_rows": changed,
                "max_abs_diff": max_abs_diff,
                "difference_category": category,
            }
        )
    audit = pd.DataFrame(rows)
    audit.to_csv(audit_path, index=False)
    unexpected = audit[audit["difference_category"].eq("unexpected_difference")] if not audit.empty else audit
    return {
        "columns_with_differences": int(len(audit)),
        "unexpected_difference_columns": unexpected["column"].tolist() if not unexpected.empty else [],
        "audit_path": str(audit_path),
    }


def _combine_control_sources(
    sources: list[tuple[str, Path, pd.DataFrame]],
    *,
    value_column: str,
    tolerance: float = 1e-8,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    parts: list[pd.DataFrame] = []
    audit_rows: list[dict[str, object]] = []
    for priority, (source_name, path, frame) in enumerate(sources):
        clean = frame[["date", value_column]].dropna().copy()
        clean["date"] = (
            pd.to_datetime(clean["date"])
            .dt.tz_localize(None)
            .dt.normalize()
            .astype("datetime64[ns]")
        )
        clean[value_column] = pd.to_numeric(clean[value_column], errors="coerce")
        clean = clean.dropna().drop_duplicates("date", keep="last")
        clean["source_name"] = source_name
        clean["source_priority"] = priority
        parts.append(clean)
        audit_rows.append(
            {
                "control": value_column,
                "source_name": source_name,
                "path": str(path),
                "sha256": _sha256_path(path),
                "rows": int(len(clean)),
                "date_min": clean["date"].min().date().isoformat() if not clean.empty else "",
                "date_max": clean["date"].max().date().isoformat() if not clean.empty else "",
            }
        )
    combined = pd.concat(parts, ignore_index=True)
    conflicts = (
        combined.groupby("date")[value_column]
        .agg(lambda values: float(np.nanmax(values) - np.nanmin(values)))
        .loc[lambda values: values > tolerance]
    )
    if not conflicts.empty:
        examples = conflicts.head(10).to_dict()
        raise ValueError(f"Conflicting overlapping sources for {value_column}: {examples}")
    overlap_dates = int(combined.duplicated("date", keep=False).groupby(combined["date"]).max().sum())
    for row in audit_rows:
        row["overlap_dates_reconciled"] = overlap_dates
        row["overlap_conflicts"] = 0
    resolved = (
        combined.sort_values(["date", "source_priority"])
        .drop_duplicates("date", keep="last")
        .sort_values("date")
        .reset_index(drop=True)
    )
    return resolved, pd.DataFrame(audit_rows)


def _daily_backward_fill(
    date_index: pd.DataFrame,
    source: pd.DataFrame,
    *,
    value_column: str,
    max_staleness_days: int,
) -> pd.DataFrame:
    calendar = date_index[["date"]].copy().sort_values("date")
    calendar["date"] = pd.to_datetime(calendar["date"]).dt.normalize().astype("datetime64[ns]")
    source = source[["date", value_column, "source_name"]].copy().sort_values("date")
    source = source.rename(columns={"date": "source_date", "source_name": f"{value_column}_source"})
    source["source_date"] = pd.to_datetime(source["source_date"]).astype("datetime64[ns]")
    out = pd.merge_asof(
        calendar,
        source,
        left_on="date",
        right_on="source_date",
        direction="backward",
    )
    if out[value_column].isna().any():
        first_missing = out.loc[out[value_column].isna(), "date"].min()
        raise ValueError(
            f"{value_column} has no source observation on or before panel start; leading backfill is forbidden. "
            f"First missing date: {first_missing.date().isoformat()}"
        )
    out[f"{value_column}_staleness_days"] = (out["date"] - out["source_date"]).dt.days
    stale = out[out[f"{value_column}_staleness_days"].gt(max_staleness_days)]
    if not stale.empty:
        examples = stale[["date", "source_date", f"{value_column}_staleness_days"]].head(10).to_dict("records")
        raise ValueError(f"{value_column} exceeds max forward-fill staleness of {max_staleness_days} days: {examples}")
    return out


def _parse_investing_csv(path: Path, value_name: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["Дата"], format="%d.%m.%Y", errors="coerce")
    df[value_name] = df["Цена"].map(parse_float_ru)
    return df[["date", value_name]].dropna(subset=["date", value_name]).sort_values("date")


def load_macro(paths: RefreshPaths, date_index: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    usd, usd_audit = _combine_control_sources(
        [
            ("historical_full", paths.historical_usd_rub_csv, _parse_investing_csv(paths.historical_usd_rub_csv, "usd_rub_close")),
            ("incremental_tail", paths.usd_rub_csv, _parse_investing_csv(paths.usd_rub_csv, "usd_rub_close")),
        ],
        value_column="usd_rub_close",
    )
    brent, brent_audit = _combine_control_sources(
        [
            ("historical_full", paths.historical_brent_csv, _parse_investing_csv(paths.historical_brent_csv, "brent_usd_close")),
            ("incremental_tail", paths.brent_csv, _parse_investing_csv(paths.brent_csv, "brent_usd_close")),
        ],
        value_column="brent_usd_close",
    )
    usd_daily = _daily_backward_fill(date_index, usd, value_column="usd_rub_close", max_staleness_days=10)
    brent_daily = _daily_backward_fill(date_index, brent, value_column="brent_usd_close", max_staleness_days=10)
    macro = usd_daily.merge(brent_daily, on="date", how="inner")
    macro["usd_rub_change_pct"] = macro["usd_rub_close"].pct_change(fill_method=None).fillna(0.0) * 100.0
    macro["brent_usd_change_pct"] = macro["brent_usd_close"].pct_change(fill_method=None).fillna(0.0) * 100.0
    macro["usd_rub_log_return"] = np.log(macro["usd_rub_close"]).diff().fillna(0.0)
    macro["brent_log_return"] = np.log(macro["brent_usd_close"]).diff().fillna(0.0)
    for column in ["usd_rub_log_return", "brent_log_return"]:
        for year, values in macro.groupby(macro["date"].dt.year)[column]:
            if len(values) > 1 and float(values.std()) <= 1e-12:
                raise ValueError(f"{column} has no variation in panel year {year}; source coverage is invalid")
    return macro, pd.concat([usd_audit, brent_audit], ignore_index=True)


def _fetch_ruonia_cbr(from_date: pd.Timestamp, to_date: pd.Timestamp) -> pd.DataFrame:
    envelope = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body><Ruonia xmlns="http://web.cbr.ru/"><fromDate>{from_date.date().isoformat()}T00:00:00</fromDate><ToDate>{to_date.date().isoformat()}T00:00:00</ToDate></Ruonia></soap:Body>
</soap:Envelope>""".encode("utf-8")
    request = urllib.request.Request(
        "https://www.cbr.ru/DailyInfoWebServ/DailyInfo.asmx",
        data=envelope,
        headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": "http://web.cbr.ru/Ruonia"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = response.read()
    root = ET.fromstring(payload)
    rows: list[dict[str, object]] = []
    for element in root.iter():
        if element.tag.split("}")[-1] != "ro":
            continue
        values = {child.tag.split("}")[-1]: child.text for child in element}
        rows.append({"date": values.get("D0"), "ruonia_rate": values.get("ruo")})
    out = pd.DataFrame(rows)
    if out.empty:
        raise ValueError("CBR RUONIA SOAP returned no observations")
    out["date"] = pd.to_datetime(out["date"], utc=True).dt.tz_convert("Europe/Moscow").dt.tz_localize(None).dt.normalize()
    out["ruonia_rate"] = pd.to_numeric(out["ruonia_rate"], errors="coerce")
    return out.dropna().drop_duplicates("date", keep="last").sort_values("date")


def _read_ruonia_xlsx(path: Path) -> pd.DataFrame:
    ru = pd.read_excel(path, sheet_name="RC").rename(columns={"DT": "date", "ruo": "ruonia_rate"})
    ru["date"] = pd.to_datetime(ru["date"], errors="coerce")
    ru["ruonia_rate"] = pd.to_numeric(ru["ruonia_rate"], errors="coerce")
    return ru[["date", "ruonia_rate"]].dropna().sort_values("date")


def load_ruonia(paths: RefreshPaths, date_index: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not paths.ruonia_cbr_cache_csv.exists():
        if not paths.fetch_ruonia_from_cbr:
            raise FileNotFoundError(
                f"Missing official RUONIA cache {paths.ruonia_cbr_cache_csv}; automatic CBR fetch is disabled"
            )
        official = _fetch_ruonia_cbr(paths.panel_start - pd.Timedelta(days=31), paths.panel_end)
        paths.ruonia_cbr_cache_csv.parent.mkdir(parents=True, exist_ok=True)
        official.assign(source="CBR_DailyInfoWebServ_Ruonia").to_csv(paths.ruonia_cbr_cache_csv, index=False)
    official = pd.read_csv(paths.ruonia_cbr_cache_csv)
    official["date"] = pd.to_datetime(official["date"], errors="coerce")
    official["ruonia_rate"] = pd.to_numeric(official["ruonia_rate"], errors="coerce")
    resolved, audit = _combine_control_sources(
        [
            ("historical_local", paths.historical_ruonia_xlsx, _read_ruonia_xlsx(paths.historical_ruonia_xlsx)),
            ("incremental_local", paths.ruonia_xlsx, _read_ruonia_xlsx(paths.ruonia_xlsx)),
            ("official_cbr", paths.ruonia_cbr_cache_csv, official[["date", "ruonia_rate"]]),
        ],
        value_column="ruonia_rate",
        tolerance=1e-6,
    )
    out = _daily_backward_fill(date_index, resolved, value_column="ruonia_rate", max_staleness_days=14)
    out["ruonia_change"] = out["ruonia_rate"].diff().fillna(0.0)
    return out, audit


def build_calendar(date_index: pd.DataFrame) -> pd.DataFrame:
    out = date_index.copy()
    out["dow"] = out["date"].dt.dayofweek
    out["month"] = out["date"].dt.month
    out["day_of_year"] = out["date"].dt.dayofyear
    for period, label in [(7, 7), (30.4, 30), (91.3, 91), (365.25, 365)]:
        out[f"sin_{label}"] = np.sin(2 * np.pi * out["day_of_year"] / period)
        out[f"cos_{label}"] = np.cos(2 * np.pi * out["day_of_year"] / period)

    official = {
        # 2025 copied from accepted old panel calendar.
        "2025-01-01": "new_year",
        "2025-01-02": "new_year",
        "2025-01-03": "new_year",
        "2025-01-04": "new_year",
        "2025-01-05": "new_year",
        "2025-01-06": "new_year",
        "2025-01-07": "new_year",
        "2025-01-08": "new_year",
        "2025-02-23": "feb23",
        "2025-02-24": "feb23",
        "2025-03-08": "mar8",
        "2025-03-10": "mar8",
        "2025-05-01": "may",
        "2025-05-02": "may",
        "2025-05-09": "may_9",
        "2025-06-12": "jun12",
        "2025-06-13": "jun12",
        "2025-11-03": "nov4",
        "2025-11-04": "nov4",
        "2025-12-31": "nye",
        # 2026 through the current panel horizon.
        "2026-01-01": "new_year",
        "2026-01-02": "new_year",
        "2026-01-03": "new_year",
        "2026-01-04": "new_year",
        "2026-01-05": "new_year",
        "2026-01-06": "new_year",
        "2026-01-07": "new_year",
        "2026-01-08": "new_year",
        "2026-02-23": "feb23",
        "2026-03-08": "mar8",
        "2026-03-09": "mar8",
        "2026-05-01": "may",
        "2026-05-09": "may_9",
        "2026-05-11": "may_9",
    }
    pre = {
        "2025-02-14",
        "2025-02-21",
        "2025-02-22",
        "2025-03-06",
        "2025-03-07",
        "2025-09-01",
        *[f"2025-12-{d:02d}" for d in range(20, 31)],
        "2026-02-20",
        "2026-02-21",
        "2026-03-06",
        "2026-04-30",
        "2026-05-08",
    }
    date_str = out["date"].dt.strftime("%Y-%m-%d")
    out["holiday_group"] = date_str.map(official).fillna("regular_day")
    out["is_official_holiday"] = date_str.isin(official).astype(int)
    out["is_pre_holiday"] = date_str.isin(pre).astype(int)
    out["is_nonworking"] = ((out["dow"] >= 5) | (out["is_official_holiday"] == 1)).astype(int)
    out["is_salary_period"] = out["date"].dt.day.isin([5, 25]).astype(int)
    return out


def build_weather(paths: RefreshPaths, model_geos: Iterable[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not paths.weather_exact_parquet.exists():
        raise FileNotFoundError(f"Missing exact weather artifact: {paths.weather_exact_parquet}")

    weather = pd.read_parquet(paths.weather_exact_parquet)
    weather["date"] = pd.to_datetime(weather["date"])
    weather["geo_unit"] = weather["geo_unit"].map(norm_text)

    required_cols = {"date", "geo_unit", *WEATHER_COLS}
    missing_cols = sorted(required_cols - set(weather.columns))
    if missing_cols:
        raise ValueError(f"Exact weather artifact is missing required columns: {missing_cols}")

    model_geos = sorted(set(model_geos))
    all_dates = pd.date_range(paths.panel_start, paths.panel_end, freq="D")
    weather = weather[weather["geo_unit"].isin(model_geos)].copy()
    weather = weather[(weather["date"] >= paths.panel_start) & (weather["date"] <= paths.panel_end)].copy()

    dupes = weather.duplicated(["date", "geo_unit"])
    if dupes.any():
        examples = weather.loc[dupes, ["date", "geo_unit"]].head(20).to_dict("records")
        raise ValueError(f"Exact weather artifact has duplicate date/geo rows: {examples}")

    coverage = weather.groupby("geo_unit")["date"].nunique()
    missing_geos = sorted(set(model_geos) - set(coverage.index))
    short_geos = coverage[coverage.ne(len(all_dates))].sort_values().to_dict()
    if missing_geos or short_geos:
        raise ValueError(
            "Exact weather artifact does not fully cover model geos/dates: "
            f"missing_geos={missing_geos}, short_geos={short_geos}"
        )

    nulls = {col: int(weather[col].isna().sum()) for col in WEATHER_COLS if int(weather[col].isna().sum()) > 0}
    if nulls:
        raise ValueError(f"Exact weather artifact has null weather values: {nulls}")

    expected = pd.MultiIndex.from_product([all_dates, model_geos], names=["date", "geo_unit"]).to_frame(index=False)
    missing_rows = expected.merge(weather[["date", "geo_unit"]], on=["date", "geo_unit"], how="left", indicator=True)
    missing_rows = missing_rows[missing_rows["_merge"].eq("left_only")]
    if not missing_rows.empty:
        raise ValueError(f"Exact weather artifact is missing date/geo rows: {missing_rows.head(20).to_dict('records')}")

    audit = (
        weather.groupby("geo_unit", as_index=False)
        .agg(rows=("date", "size"), min_date=("date", "min"), max_date=("date", "max"))
        .rename(columns={"geo_unit": "geo_label"})
    )
    audit["expected_days"] = len(all_dates)
    audit["missing_days"] = audit["expected_days"] - audit["rows"]
    audit["weather_source_policy"] = "full_horizon_station_observations_v2_exact_artifact"
    station_cols = [c for c in ["weather_station_city", "weather_station_id"] if c in weather.columns]
    if station_cols:
        station_meta = weather.groupby("geo_unit", as_index=False)[station_cols].first().rename(columns={"geo_unit": "geo_label"})
        audit = audit.merge(station_meta, on="geo_label", how="left")

    out_cols = ["date", "geo_unit"] + WEATHER_COLS
    out = weather[out_cols].rename(columns={"geo_unit": "region_upper"})
    return out, audit


def build_competitors(paths: RefreshPaths, population: pd.DataFrame, date_index: pd.DataFrame) -> pd.DataFrame:
    compet = pd.read_excel(paths.media_xlsx, sheet_name="offline_compet")
    compet["region"] = compet["region"].map(norm_text).replace(CITY_TO_PARENT_REGION)
    compet["channel_type_comp"] = compet["channel_type_comp"].astype(str).str.strip()
    compet["budget_comp"] = pd.to_numeric(compet["budget_comp"], errors="coerce")
    compet["week"] = pd.to_datetime(compet["week"], errors="coerce")
    compet = compet.dropna(subset=["budget_comp", "week", "region", "channel_type_comp"])
    compet["budget_comp"] = compet["budget_comp"] / 7.0
    expanded = []
    for offset in range(7):
        chunk = compet.copy()
        chunk["date"] = chunk["week"] + pd.Timedelta(days=offset)
        expanded.append(chunk)
    daily = pd.concat(expanded, ignore_index=True)
    daily = daily[(daily["date"] >= paths.panel_start) & (daily["date"] <= paths.panel_end)].copy()
    daily["channel_norm"] = daily["channel_type_comp"].map(COMPET_CHANNEL_RENAME)
    daily = daily.dropna(subset=["channel_norm"])
    wide = daily.pivot_table(
        index=["date", "region"],
        columns="channel_norm",
        values="budget_comp",
        aggfunc="sum",
        fill_value=0.0,
    ).reset_index()
    wide.columns.name = None
    wide = wide.rename(columns={ch: f"compet_spend_{ch}" for ch in COMPET_CHANNEL_RENAME.values()})
    for col in COMPET_OUT_COLS:
        if col not in wide.columns:
            wide[col] = 0.0

    rf_mask = wide["region"].eq("РФ")
    if rf_mask.any():
        weights = population[["geo_label", "population_k"]].dropna().copy()
        weights = weights[weights["population_k"] > 0]
        weights["weight"] = weights["population_k"] / weights["population_k"].sum()
        rf = wide.loc[rf_mask, ["date", "compet_spend_NacTV"]]
        rf = rf[rf["compet_spend_NacTV"] > 0]
        if not rf.empty:
            fed = rf.merge(weights[["geo_label", "weight"]], how="cross")
            fed["compet_spend_NacTV"] *= fed["weight"]
            fed = fed.rename(columns={"geo_label": "region"})
            regional = wide.loc[~rf_mask].copy()
            regional = regional.merge(
                fed[["date", "region", "compet_spend_NacTV"]].rename(
                    columns={"compet_spend_NacTV": "compet_spend_NacTV_fed"}
                ),
                on=["date", "region"],
                how="outer",
            )
            regional["compet_spend_NacTV"] = regional["compet_spend_NacTV"].fillna(0) + regional[
                "compet_spend_NacTV_fed"
            ].fillna(0)
            regional = regional.drop(columns=["compet_spend_NacTV_fed"])
            wide = regional

    wide = wide.rename(columns={"region": "region_upper"})
    for col in COMPET_OUT_COLS:
        wide[col] = wide[col].fillna(0.0)
    return wide[["date", "region_upper"] + COMPET_OUT_COLS]


def add_media_groups(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel.copy()
    for col in DIGITAL_RAW_SPEND_INPUTS:
        if col not in out.columns:
            out[col] = 0.0
    out["spend_Digital_Performance"] = out[DIGITAL_RAW_SPEND_INPUTS].sum(axis=1)
    for col in OOH_TOTAL_INPUT_COLS:
        if col not in out.columns:
            out[col] = 0.0
    out[OOH_TOTAL_GROUP_COL] = out[OOH_TOTAL_INPUT_COLS].sum(axis=1)
    return out


def add_per_capita(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel.copy()
    spend_cols = [c for c in out.columns if c.startswith("spend_") and not c.endswith("_pc")]
    denom = out["unique_users"].replace(0, np.nan)
    for sc in spend_cols:
        out[f"{sc}_pc"] = out[sc] / denom
    return out


def winsorize_targets(panel: pd.DataFrame) -> pd.DataFrame:
    cfg = dict(
        L1_window=30,
        L1_z=3.0,
        L1_min_periods=5,
        L2_window=30,
        L2_threshold=3.5,
        L2_min_periods=5,
        L3_iqr_mult=3.0,
        L4_avg_basket_max=10_000.0,
        L4_orders_per_user_max=5.0,
        L4_zero_target_spend_threshold=100_000.0,
        correction_threshold=3,
    )
    out = panel.copy()
    spend_cols = [c for c in out.columns if c.startswith("spend_") and not c.endswith("_pc")]

    def rolling_z(s: pd.Series) -> tuple[pd.Series, pd.Series]:
        rm = s.rolling(cfg["L1_window"], center=True, min_periods=cfg["L1_min_periods"]).median()
        rs = s.rolling(cfg["L1_window"], center=True, min_periods=cfg["L1_min_periods"]).std()
        return (np.abs((s - rm) / (rs + 1e-8)) > cfg["L1_z"]).fillna(False), rm

    def hampel(s: pd.Series) -> pd.Series:
        rm = s.rolling(cfg["L2_window"], center=True, min_periods=cfg["L2_min_periods"]).median()
        mad = s.rolling(cfg["L2_window"], center=True, min_periods=cfg["L2_min_periods"]).apply(
            lambda x: np.median(np.abs(x - np.median(x))),
            raw=True,
        )
        return (np.abs(s - rm) / (1.4826 * mad + 1e-8) > cfg["L2_threshold"]).fillna(False)

    def iqr_mask(s: pd.Series) -> pd.Series:
        if len(s.dropna()) < 10:
            return pd.Series(False, index=s.index)
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = q3 - q1
        return ((s < q1 - cfg["L3_iqr_mult"] * iqr) | (s > q3 + cfg["L3_iqr_mult"] * iqr)).fillna(False)

    def classify(mask: pd.Series) -> tuple[pd.Series, pd.Series]:
        flag = mask.fillna(False).astype(int)
        groups = (flag != flag.shift()).cumsum()
        run_lengths = flag.groupby(groups).transform("sum")
        correctable = (flag == 1) & (run_lengths <= cfg["correction_threshold"])
        systematic = (flag == 1) & (run_lengths > cfg["correction_threshold"])
        return correctable, systematic

    for target in ["turnover_per_user", "orders_per_user", "avg_basket"]:
        out[f"{target}_raw"] = out[target].copy()
        out[f"{target}_anomaly_flag"] = False
        corrected = flagged = 0
        for _, grp in out.groupby(["geo_label", "network", "channel"], sort=False):
            grp = grp.sort_values("date")
            s = grp[target].astype(float)
            m1, rm = rolling_z(s)
            m2 = hampel(s)
            m3 = iqr_mask(s)
            spend_sum = grp[spend_cols].sum(axis=1) if spend_cols else pd.Series(0.0, index=grp.index)
            m4 = pd.Series(False, index=grp.index)
            if target == "avg_basket":
                m4 |= grp[target] > cfg["L4_avg_basket_max"]
            if target == "orders_per_user":
                m4 |= grp[target] > cfg["L4_orders_per_user_max"]
            m4 |= (grp[target] == 0) & (spend_sum > cfg["L4_zero_target_spend_threshold"])
            mask = m1 | m2 | m3 | m4
            if not mask.any():
                continue
            corr, syst = classify(mask)
            corr_idx = grp.index[corr]
            if len(corr_idx):
                repl = rm.loc[corr_idx]
                valid = repl.notna()
                out.loc[corr_idx[valid], target] = repl[valid].values
                corrected += int(valid.sum())
            syst_idx = grp.index[syst]
            if len(syst_idx):
                out.loc[syst_idx, f"{target}_anomaly_flag"] = True
                flagged += len(syst_idx)
        log.info("Winsorize %s: corrected=%d | flagged=%d", target, corrected, flagged)
    return out


def _bad_target_mask(panel: pd.DataFrame) -> pd.Series:
    """Identify rows whose raw target bundle cannot be used by the model."""
    mask = pd.Series(False, index=panel.index)
    for column in RAW_TARGET_COLS:
        mask |= pd.to_numeric(panel[column], errors="coerce").le(0)
    mask |= panel[MODEL_TARGET_COLS].isna().any(axis=1)
    return mask.fillna(False)


def _valid_target_peer_mask(peer: pd.DataFrame) -> pd.Series:
    valid = pd.Series(True, index=peer.index)
    for column in RAW_TARGET_COLS:
        valid &= pd.to_numeric(peer[column], errors="coerce").gt(0)
    valid &= ~peer[MODEL_TARGET_COLS].isna().any(axis=1)
    return valid.fillna(False)


def _target_peer_candidates(
    panel: pd.DataFrame,
    row_index: int,
    row: pd.Series,
) -> tuple[pd.DataFrame, str, int | None]:
    """Choose local peers using the same hierarchy as the reviewed v2 cleanup."""
    for window_days in [14, 30, 60, 120]:
        peer = panel[
            panel["geo_label"].eq(row["geo_label"])
            & panel["network"].eq(row["network"])
            & panel["channel"].eq(row["channel"])
            & panel["date"].between(
                row["date"] - pd.Timedelta(days=window_days),
                row["date"] + pd.Timedelta(days=window_days),
            )
            & (panel.index != row_index)
        ]
        valid = peer.loc[_valid_target_peer_mask(peer)]
        if len(valid) >= 5:
            return valid, "same_geo_segment_centered_window", window_days

    peer = panel[
        panel["network"].eq(row["network"])
        & panel["channel"].eq(row["channel"])
        & panel["date"].eq(row["date"])
        & (panel.index != row_index)
    ]
    valid = peer.loc[_valid_target_peer_mask(peer)]
    if len(valid) >= 5:
        return valid, "same_segment_same_date", None

    peer = panel[
        panel["network"].eq(row["network"])
        & panel["channel"].eq(row["channel"])
        & panel["date"].dt.dayofweek.eq(row["date"].dayofweek)
        & panel["date"].dt.month.eq(row["date"].month)
        & (panel.index != row_index)
    ]
    valid = peer.loc[_valid_target_peer_mask(peer)]
    if len(valid) >= 5:
        return valid, "same_segment_same_dow_month", None

    for window_days in [14, 30, 60, 120]:
        peer = panel[
            panel["network"].eq(row["network"])
            & panel["channel"].eq(row["channel"])
            & panel["date"].between(
                row["date"] - pd.Timedelta(days=window_days),
                row["date"] + pd.Timedelta(days=window_days),
            )
            & (panel.index != row_index)
        ]
        valid = peer.loc[_valid_target_peer_mask(peer)]
        if len(valid) >= 5:
            return valid, "same_segment_centered_window", window_days

    raise ValueError(
        "No valid target-imputation peer set for "
        f"index={row_index}, date={row['date'].date()}, geo={row['geo_label']}, "
        f"segment={row['network']}/{row['channel']}"
    )


def impute_invalid_target_rows(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Replace invalid target bundles with reviewed local-peer arithmetic means."""
    out = panel.copy()
    out["date"] = pd.to_datetime(out["date"])
    patches: list[TargetImputationPatch] = []
    bad_indices = list(
        out.loc[_bad_target_mask(out)]
        .sort_values(["date", "network", "channel", "geo_label"])
        .index
    )

    for row_index in bad_indices:
        row = out.loc[row_index]
        peers, method, window_days = _target_peer_candidates(out, row_index, row)
        means = peers[TARGET_BUNDLE_COLS].apply(pd.to_numeric, errors="coerce").mean()

        for column in TARGET_BUNDLE_COLS:
            old_value = out.at[row_index, column]
            new_value: float | int = float(means[column])
            if column in COUNT_TARGET_COLS:
                new_value = int(max(round(new_value), 1))
            else:
                new_value = float(max(new_value, 1e-9))
            out.at[row_index, column] = new_value
            patches.append(
                TargetImputationPatch(
                    row_index=int(row_index),
                    date=str(row["date"].date()),
                    geo_label=str(row["geo_label"]),
                    network=str(row["network"]),
                    channel=str(row["channel"]),
                    method=method,
                    window_days=window_days,
                    peer_rows=int(len(peers)),
                    column=column,
                    old_value=None if pd.isna(old_value) else old_value,
                    new_value=new_value,
                )
            )

        for raw_column, model_column in [
            ("turnover_per_user_raw", "turnover_per_user"),
            ("orders_per_user_raw", "orders_per_user"),
        ]:
            if raw_column not in out.columns:
                continue
            old_value = out.at[row_index, raw_column]
            new_value = float(out.at[row_index, model_column])
            out.at[row_index, raw_column] = new_value
            patches.append(
                TargetImputationPatch(
                    row_index=int(row_index),
                    date=str(row["date"].date()),
                    geo_label=str(row["geo_label"]),
                    network=str(row["network"]),
                    channel=str(row["channel"]),
                    method=method,
                    window_days=window_days,
                    peer_rows=int(len(peers)),
                    column=raw_column,
                    old_value=None if pd.isna(old_value) else old_value,
                    new_value=new_value,
                )
            )

    for column in COUNT_TARGET_COLS:
        out[column] = pd.to_numeric(out[column], errors="raise").round().astype("int64")

    audit = pd.DataFrame([asdict(patch) for patch in patches])
    return out, audit


def refresh_target_auxiliary(panel: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Refresh fields whose denominator or source target may have been imputed."""
    out = panel.copy()
    summary: dict[str, int] = {}
    if "holiday_group" in out.columns:
        summary["holiday_group_missing_before"] = int(out["holiday_group"].isna().sum())
        out["holiday_group"] = out["holiday_group"].fillna("regular_day")
        summary["holiday_group_missing_after"] = int(out["holiday_group"].isna().sum())

    spend_columns = [column for column in out.columns if column.startswith("spend_") and not column.endswith("_pc")]
    denominator = pd.to_numeric(out["unique_users"], errors="coerce").replace(0, np.nan)
    for column in spend_columns:
        out[f"{column}_pc"] = pd.to_numeric(out[column], errors="coerce").fillna(0.0) / denominator

    spend_pc_columns = [column for column in out.columns if column.startswith("spend_") and column.endswith("_pc")]
    summary["spend_pc_missing_after"] = int(out[spend_pc_columns].isna().sum().sum()) if spend_pc_columns else 0
    for column in ["turnover_per_user_raw", "orders_per_user_raw"]:
        if column in out.columns:
            summary[f"{column}_missing_after"] = int(out[column].isna().sum())
            summary[f"{column}_nonpositive_after"] = int(pd.to_numeric(out[column], errors="coerce").le(0).sum())
    return out, summary


def add_market_size_tiers(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    out = panel.copy()
    geo_size = out.groupby("geo_label", dropna=False)[["population_k", "n_stores"]].median()
    rank_cols = []
    for col in ["population_k", "n_stores"]:
        vals = geo_size[col].astype(float)
        fill = vals.median() if vals.notna().any() else 0.0
        geo_size[f"{col}_rank_pct"] = vals.fillna(fill).rank(pct=True, method="average")
        rank_cols.append(f"{col}_rank_pct")
    geo_size["market_size_score"] = geo_size[rank_cols].mean(axis=1)
    stable_rank = geo_size["market_size_score"].rank(method="first")
    geo_size["market_size_tier"] = pd.qcut(stable_rank, q=3, labels=["small", "medium", "large"])
    tier_order = {"small": 0, "medium": 1, "large": 2}
    geo_size["market_size_tier_rank"] = geo_size["market_size_tier"].astype(str).map(tier_order).astype(int)
    geo_size["market_size_tier_source"] = "population_k+n_stores"
    out["market_size_score"] = out["geo_label"].map(geo_size["market_size_score"])
    out["market_size_tier"] = out["geo_label"].map(geo_size["market_size_tier"].astype(str))
    out["market_size_tier_rank"] = out["geo_label"].map(geo_size["market_size_tier_rank"]).astype(int)
    out["market_size_tier_source"] = out["geo_label"].map(geo_size["market_size_tier_source"])
    return out, geo_size.reset_index()


def assemble_panel(paths: RefreshPaths) -> dict:
    if paths.output_panel.resolve() == paths.promoted_panel.resolve():
        raise ValueError("Candidate output must differ from promoted panel; in-place final mutation is forbidden")
    if paths.output_panel.exists() and not paths.allow_overwrite_candidate:
        raise FileExistsError(
            f"Candidate already exists and assembly.allow_overwrite_candidate=false: {paths.output_panel}"
        )
    paths.output_dir.mkdir(parents=True, exist_ok=True)
    audit_dir = paths.output_dir / "audits"
    audit_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir = paths.output_dir / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)

    mapping = load_mapping(paths.mapping_csv)
    population, population_audit = load_population(paths, mapping)
    population.to_excel(paths.output_dir / "population_geo_rosstat_for_MMM_v2.xlsx", index=False)
    population_audit.to_csv(audit_dir / "population_geo_audit_v2.csv", index=False)
    if population_audit["population_missing"].any():
        missing = population_audit.loc[population_audit["population_missing"], "geo_label"].tolist()
        raise ValueError(f"Missing population for model geos: {missing}")

    model_geos = sorted(population["geo_label"].unique())
    targets = load_targets(paths, model_geos)
    media = load_media_long(
        paths.media_xlsx,
        panel_start=paths.panel_start,
        panel_end=paths.panel_end,
    )
    mapped_media, media_budget_audit = apply_geo_mapping(media, mapping, population, targets)
    mapped_media.to_parquet(audit_dir / "media_long_mapped_v2.parquet", index=False, compression="snappy")
    media_budget_audit.to_csv(audit_dir / "media_budget_conservation_v2.csv", index=False)
    ad_wide, spend_cols = media_to_wide(mapped_media)

    panel = targets.merge(ad_wide, on=["date", "geo_label", "network", "channel"], how="left")
    for sc in spend_cols:
        panel[sc] = panel[sc].fillna(0.0)
    for sc in [c for c in OFFLINE_MEDIA_SPEND_COLS + DIGITAL_RAW_SPEND_INPUTS if c not in panel.columns]:
        panel[sc] = 0.0

    pop_cols = population.rename(columns={"geo_label": "region_upper"})
    panel = panel.merge(
        pop_cols[["region_upper", "geo_type", "population_k", "n_stores", "population_source"]],
        on="region_upper",
        how="left",
    )
    if "geo_type_x" in panel.columns or "geo_type_y" in panel.columns:
        left = panel["geo_type_x"] if "geo_type_x" in panel.columns else pd.Series(np.nan, index=panel.index)
        right = panel["geo_type_y"] if "geo_type_y" in panel.columns else pd.Series(np.nan, index=panel.index)
        panel["geo_type"] = left.fillna(right)
        panel = panel.drop(columns=[c for c in ["geo_type_x", "geo_type_y"] if c in panel.columns])

    date_index = pd.DataFrame({"date": pd.date_range(paths.panel_start, paths.panel_end, freq="D")})
    calendar = build_calendar(date_index)
    macro, macro_source_audit = load_macro(paths, date_index)
    ruonia, ruonia_source_audit = load_ruonia(paths, date_index)
    weather, weather_audit = build_weather(paths, model_geos)
    competitors = build_competitors(paths, population, date_index)

    weather_audit.to_csv(audit_dir / "weather_geo_reference_audit_v2.csv", index=False)
    pd.concat([macro_source_audit, ruonia_source_audit], ignore_index=True).to_csv(
        audit_dir / "control_source_reconciliation_v2.csv",
        index=False,
    )
    calendar.to_csv(audit_dir / "calendar_v2.csv", index=False)
    macro_model_columns = [
        "date",
        "usd_rub_close",
        "usd_rub_change_pct",
        "usd_rub_log_return",
        "brent_usd_close",
        "brent_usd_change_pct",
        "brent_log_return",
    ]
    ruonia_model_columns = ["date", "ruonia_rate", "ruonia_change"]
    macro_model = macro[macro_model_columns].copy()
    ruonia_model = ruonia[ruonia_model_columns].copy()
    macro_model.to_parquet(paths.output_dir / "macro_features_2025-01-01_to_2026-05-31_v2.parquet", index=False)
    weather.to_parquet(paths.output_dir / "weather_features_2025-01-01_to_2026-05-31_v2.parquet", index=False)

    panel = panel.merge(calendar, on="date", how="left")
    panel = panel.merge(macro_model, on="date", how="left")
    panel = panel.merge(ruonia_model, on="date", how="left")
    panel = panel.merge(weather, on=["date", "region_upper"], how="left")
    missing_weather_cols = [col for col in WEATHER_COLS if col not in panel.columns]
    missing_weather_values = {
        col: int(panel[col].isna().sum())
        for col in WEATHER_COLS
        if col in panel.columns and int(panel[col].isna().sum()) > 0
    }
    if missing_weather_cols or missing_weather_values:
        raise ValueError(
            "Weather merge is incomplete; fix weather_features_v2_exact before model build: "
            f"missing_cols={missing_weather_cols}, missing_values={missing_weather_values}"
        )
    for col in WEATHER_COLS:
        if col.startswith("is_") or col == "weather_drives_indoor_d":
            panel[col] = panel[col].astype(int)
    panel = panel.merge(competitors, on=["date", "region_upper"], how="left")
    for col in COMPET_OUT_COLS:
        panel[col] = panel[col].fillna(0.0)

    panel = add_media_groups(panel)
    panel = add_per_capita(panel)
    panel["anomaly_period_jul2025"] = (
        (panel["date"] >= pd.Timestamp("2025-07-01")) & (panel["date"] <= pd.Timestamp("2025-07-31"))
    ).astype(int)
    panel = winsorize_targets(panel)
    target_invalid_before_imputation_count = int(_bad_target_mask(panel).sum())
    panel, target_imputation_audit = impute_invalid_target_rows(panel)
    panel, target_auxiliary_summary = refresh_target_auxiliary(panel)
    target_imputation_audit.to_csv(audit_dir / "target_dq_imputation_v2.csv", index=False)
    target_imputation_summary = {
        "invalid_rows_before": target_invalid_before_imputation_count,
        "imputed_rows": int(target_imputation_audit["row_index"].nunique())
        if not target_imputation_audit.empty
        else 0,
        "patched_cells": int(len(target_imputation_audit)),
        "invalid_rows_after": int(_bad_target_mask(panel).sum()),
        "auxiliary": target_auxiliary_summary,
        "policy": {
            "row_trigger": "any raw target <= 0 or any model target is missing",
            "primary_peers": "same geo_label x network x channel in centered +/-14 day window",
            "minimum_peer_rows": 5,
            "fallbacks": [
                "same geo segment in centered +/-30/60/120 day window",
                "same network x channel on the same date",
                "same network x channel in the same month and day of week",
                "same network x channel in centered +/-14/30/60/120 day window",
            ],
            "replacement": "arithmetic mean for the full target bundle; count targets rounded to positive integers",
        },
    }
    (audit_dir / "target_dq_imputation_summary_v2.json").write_text(
        json.dumps(target_imputation_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    target_missing_mask = panel[MODEL_TARGET_COLS].isna().any(axis=1)
    target_missing_after_imputation_count = int(target_missing_mask.sum())
    target_missing_audit_cols = [
        "date",
        "geo_label",
        "network",
        "channel",
        "orders_cnt",
        "turnover_total",
        "unique_users",
        "avg_basket",
        "turnover_per_user",
        "orders_per_user",
    ]
    target_missing_audit = panel.loc[target_missing_mask, target_missing_audit_cols].copy()
    spend_cols_for_target_audit = [c for c in panel.columns if c.startswith("spend_") and not c.endswith("_pc")]
    if spend_cols_for_target_audit and not target_missing_audit.empty:
        target_missing_audit["spend_row_total"] = panel.loc[target_missing_mask, spend_cols_for_target_audit].sum(axis=1)
    target_missing_audit.to_csv(audit_dir / "target_missing_after_winsorize_v2.csv", index=False)
    panel, market_tiers = add_market_size_tiers(panel)
    market_tiers.to_csv(paths.output_dir / "market_size_tiers_v2.csv", index=False)

    # Stable column order: meta/targets first, then the rest.
    first_cols = [
        "geo_label",
        "geo_type",
        "network",
        "channel",
        "orders_cnt",
        "turnover_total",
        "unique_users",
        "avg_basket",
        "turnover_per_user",
        "orders_per_user",
        "date",
        "region_upper",
    ]
    rest = [c for c in panel.columns if c not in first_cols]
    panel = panel[first_cols + rest].sort_values(["date", "geo_label", "network", "channel"]).reset_index(drop=True)
    if paths.promoted_panel.exists():
        promoted_columns = pq.read_schema(paths.promoted_panel).names
        missing_columns = sorted(set(promoted_columns) - set(panel.columns))
        extra_columns = sorted(set(panel.columns) - set(promoted_columns))
        if missing_columns or extra_columns:
            raise ValueError(
                "Candidate schema differs from promoted panel: "
                f"missing={missing_columns}, extra={extra_columns}"
            )
        panel = panel[promoted_columns]
    panel.to_parquet(paths.output_panel, index=False, compression="snappy")
    shadow_comparison = {
        "columns_with_differences": 0,
        "unexpected_difference_columns": [],
        "audit_path": "",
    }
    if paths.promoted_panel.exists():
        shadow_comparison = compare_candidate_to_promoted(
            panel,
            paths.promoted_panel,
            audit_dir / "candidate_vs_promoted_diff_summary.csv",
        )

    spend_cols_all = [c for c in panel.columns if c.startswith("spend_") and not c.endswith("_pc")]
    media_audit_rows = []
    for (network, channel), seg in panel.groupby(["network", "channel"]):
        for sc in sorted(spend_cols_all):
            total = float(seg[sc].sum())
            if total <= 0:
                continue
            nz = seg[sc] > 0
            media_audit_rows.append(
                {
                    "segment": f"{network}/{channel}",
                    "media": sc.replace("spend_", ""),
                    "spend_total_M": total / 1e6,
                    "active_days": int(seg.loc[nz, "date"].nunique()),
                    "active_geos": int(seg.loc[nz, "geo_label"].nunique()),
                    "active_geo_days": int(nz.sum()),
                    "pct_nonzero_rows": float(nz.mean() * 100),
                }
            )
    media_audit_df = pd.DataFrame(media_audit_rows).sort_values(["segment", "spend_total_M"], ascending=[True, False])
    media_audit_df.to_csv(paths.output_dir / "media_matrix_audit_v2.csv", index=False)

    panel_keys = panel[["date", "geo_label", "network", "channel"]].drop_duplicates().assign(in_panel=True)
    unjoined_media = mapped_media.merge(panel_keys, on=["date", "geo_label", "network", "channel"], how="left")
    unjoined_media = unjoined_media[unjoined_media["in_panel"].isna()].copy()
    unjoined_audit = (
        unjoined_media.groupby(["network", "channel", "channel_type", "media_geo_norm", "geo_label"], as_index=False)[
            "budget"
        ]
        .sum()
        .sort_values("budget", ascending=False)
    )
    unjoined_audit.to_csv(audit_dir / "media_unjoined_to_target_v2.csv", index=False)

    target_coverage = (
        panel.groupby(["network", "channel"])
        .agg(rows=("date", "size"), geos=("geo_label", "nunique"), min_date=("date", "min"), max_date=("date", "max"))
        .reset_index()
    )
    target_coverage.to_csv(audit_dir / "target_coverage_v2.csv", index=False)

    raw_spend_cols_all = [c for c in spend_cols_all if c not in MODEL_READY_MEDIA_GROUP_COLS]
    group_spend_cols_all = [c for c in spend_cols_all if c in MODEL_READY_MEDIA_GROUP_COLS]
    promotion_blockers = []
    if target_imputation_summary["invalid_rows_after"] > 0 or target_missing_after_imputation_count > 0:
        promotion_blockers.append("TARGET_DQ_REMAINS_AFTER_IMPUTATION")
    if shadow_comparison["unexpected_difference_columns"]:
        promotion_blockers.append("UNEXPECTED_CANDIDATE_VS_PROMOTED_DIFFERENCES")
    summary = {
        "output_panel": str(paths.output_panel),
        "shape": list(panel.shape),
        "date_min": panel["date"].min().date().isoformat(),
        "date_max": panel["date"].max().date().isoformat(),
        "geo_n": int(panel["geo_label"].nunique()),
        "segments": {
            f"{nw}/{ch}": int(g["geo_label"].nunique()) for (nw, ch), g in panel.groupby(["network", "channel"])
        },
        "media_raw_budget_rub": float(media["budget"].sum()),
        "media_mapped_budget_rub": float(mapped_media["budget"].sum()),
        "panel_joined_raw_spend_rub": float(panel[raw_spend_cols_all].sum().sum()),
        "panel_joined_group_spend_rub": float(panel[group_spend_cols_all].sum().sum()) if group_spend_cols_all else 0.0,
        "media_unjoined_to_target_rub": float(unjoined_media["budget"].sum()),
        "media_unjoined_to_target_pct": float(unjoined_media["budget"].sum() / max(mapped_media["budget"].sum(), 1.0) * 100),
        "rows_2025": int((panel["date"].dt.year == 2025).sum()),
        "rows_2026": int((panel["date"].dt.year == 2026).sum()),
        "weather_proxy_geos": 0,
        "weather_exact_geos": int(weather_audit["geo_label"].nunique()),
        "manual_population_geos": 0,
        "target_invalid_before_imputation_rows": target_invalid_before_imputation_count,
        "target_imputed_rows": target_imputation_summary["imputed_rows"],
        "target_imputation_patch_cells": target_imputation_summary["patched_cells"],
        "target_invalid_after_imputation_rows": target_imputation_summary["invalid_rows_after"],
        "target_missing_after_winsorize_rows": target_missing_after_imputation_count,
        "target_missing_after_winsorize_file": str(audit_dir / "target_missing_after_winsorize_v2.csv"),
        "target_imputation_audit_file": str(audit_dir / "target_dq_imputation_v2.csv"),
        "target_imputation_summary_file": str(audit_dir / "target_dq_imputation_summary_v2.json"),
        "promotion_status": "blocked" if promotion_blockers else "candidate_ready_for_dq",
        "promotion_blockers": promotion_blockers,
        "shadow_comparison": shadow_comparison,
        "geo_reference_file": str(paths.geo_reference_csv),
        "weather_exact_file": str(paths.weather_exact_parquet),
        "notes": [
            "2025 target comes from old raw DWH target file; 2026 target comes from daily_metrics_by_region_itog.parquet.",
            "Media for both 2025 and 2026 comes from corrected v2 agency workbook.",
            "New 38 geos have no 2025 target history, so they enter the panel from 2026 only.",
            "Population and n_stores come from strict geo_reference_v2.csv; manual/approx/proxy provenance is rejected.",
            "Weather comes from full-horizon station-observation artifact weather_features_2025-01-01_to_2026-05-31_v2_exact.parquet; missing weather is rejected before model build.",
        ],
    }
    summary_path = paths.output_dir / f"{paths.output_panel.stem}_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    input_paths = [
        paths.media_xlsx,
        paths.mapping_csv,
        paths.geo_reference_csv,
        paths.target_2025,
        paths.target_2026,
        paths.historical_usd_rub_csv,
        paths.usd_rub_csv,
        paths.historical_brent_csv,
        paths.brent_csv,
        paths.historical_ruonia_xlsx,
        paths.ruonia_xlsx,
        paths.ruonia_cbr_cache_csv,
        paths.weather_exact_parquet,
    ]
    input_manifest = {
        "run_id": paths.run_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "config_path": str(paths.config_path) if paths.config_path else None,
        "config_sha256": _sha256_path(paths.config_path) if paths.config_path else None,
        "panel_start": paths.panel_start.date().isoformat(),
        "panel_end": paths.panel_end.date().isoformat(),
        "inputs": [
            {
                "path": str(path),
                "sha256": _sha256_path(path),
                "size_bytes": path.stat().st_size,
                "mtime_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            }
            for path in input_paths
        ],
    }
    (manifest_dir / "input_manifest.json").write_text(
        json.dumps(input_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if paths.config_path:
        (manifest_dir / "run_config_snapshot.yaml").write_text(
            paths.config_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    build_manifest = {
        "run_id": paths.run_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "config_sha256": _sha256_path(paths.config_path) if paths.config_path else None,
        "data_pipeline_sha256": _sha256_path(Path(__file__).resolve()),
        "status": "candidate_built_not_promoted",
        "promotion_blockers": promotion_blockers,
        "candidate_panel": str(paths.output_panel),
        "candidate_panel_sha256": _sha256_path(paths.output_panel),
        "promoted_panel": str(paths.promoted_panel),
        "promoted_panel_unchanged": paths.promoted_panel.exists(),
        "baseline_promoted_panel_sha256": _sha256_path(paths.promoted_panel)
        if paths.promoted_panel.exists()
        else None,
        "summary": summary,
    }
    (manifest_dir / "build_manifest.json").write_text(
        json.dumps(build_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("Saved panel: %s | shape=%s", paths.output_panel, panel.shape)
    return summary


def promote_reviewed_candidate(
    *,
    candidate_path: Path,
    baseline_path: Path,
    target_path: Path,
    build_manifest_path: Path,
    preflight_summary_path: Path,
    decision_path: Path,
    reviewed_by: str,
    reason: str,
) -> dict[str, object]:
    """Atomically publish a reviewed candidate as a new immutable panel version."""
    reviewed_by = reviewed_by.strip()
    reason = reason.strip()
    if not reviewed_by or not reason:
        raise ValueError("Reviewed promotion requires non-empty reviewed_by and reason")
    for path, label in [
        (candidate_path, "candidate panel"),
        (baseline_path, "baseline promoted panel"),
        (build_manifest_path, "build manifest"),
        (preflight_summary_path, "panel preflight summary"),
    ]:
        if not path.exists():
            raise FileNotFoundError(f"Missing {label}: {path}")
    if target_path.exists():
        raise FileExistsError(f"Immutable promotion target already exists: {target_path}")
    if decision_path.exists():
        raise FileExistsError(f"Immutable promotion decision already exists: {decision_path}")
    if candidate_path.resolve() in {baseline_path.resolve(), target_path.resolve()}:
        raise ValueError("Candidate, baseline and promotion target must be distinct files")

    build_manifest = json.loads(build_manifest_path.read_text(encoding="utf-8"))
    if build_manifest.get("status") != "candidate_built_not_promoted":
        raise ValueError(f"Unexpected build-manifest status: {build_manifest.get('status')}")
    if build_manifest.get("promotion_blockers"):
        raise ValueError(f"Candidate has promotion blockers: {build_manifest['promotion_blockers']}")
    if Path(build_manifest.get("candidate_panel", "")).resolve() != candidate_path.resolve():
        raise ValueError("Build manifest points to a different candidate panel")

    candidate_sha256 = _sha256_path(candidate_path)
    if build_manifest.get("candidate_panel_sha256") != candidate_sha256:
        raise ValueError("Candidate hash no longer matches build manifest")
    baseline_sha256 = _sha256_path(baseline_path)
    if build_manifest.get("baseline_promoted_panel_sha256") != baseline_sha256:
        raise ValueError("Baseline panel hash no longer matches build manifest")
    summary = build_manifest.get("summary") or {}
    if summary.get("promotion_status") != "candidate_ready_for_dq":
        raise ValueError(f"Candidate is not ready for DQ review: {summary.get('promotion_status')}")
    if summary.get("promotion_blockers"):
        raise ValueError(f"Candidate summary has promotion blockers: {summary['promotion_blockers']}")

    preflight = json.loads(preflight_summary_path.read_text(encoding="utf-8"))
    if preflight.get("preflight_status") != "passed":
        raise ValueError("Panel preflight is absent or did not pass")
    if Path(preflight.get("panel_path", "")).resolve() != candidate_path.resolve():
        raise ValueError("Panel preflight was executed for a different candidate")
    if preflight.get("panel_sha256") != candidate_sha256:
        raise ValueError("Panel preflight hash no longer matches candidate")

    generated_at_utc = datetime.now(timezone.utc).isoformat()
    decision = {
        "schema_version": "1.0.0",
        "status": "reviewed_promoted",
        "generated_at_utc": generated_at_utc,
        "run_id": build_manifest.get("run_id"),
        "reviewed_by": reviewed_by,
        "reason": reason,
        "candidate_panel": str(candidate_path),
        "candidate_panel_sha256": candidate_sha256,
        "baseline_panel": str(baseline_path),
        "baseline_panel_sha256": baseline_sha256,
        "promoted_panel": str(target_path),
        "promoted_panel_sha256": candidate_sha256,
        "build_manifest": str(build_manifest_path),
        "build_manifest_sha256": _sha256_path(build_manifest_path),
        "panel_preflight_summary": str(preflight_summary_path),
        "panel_preflight_summary_sha256": _sha256_path(preflight_summary_path),
        "old_panel_preserved": True,
    }

    target_path.parent.mkdir(parents=True, exist_ok=True)
    decision_path.parent.mkdir(parents=True, exist_ok=True)
    target_tmp = target_path.with_name(f".{target_path.name}.tmp")
    decision_tmp = decision_path.with_name(f".{decision_path.name}.tmp")
    if target_tmp.exists() or decision_tmp.exists():
        raise FileExistsError("Promotion temporary artifact already exists; inspect before retrying")
    try:
        shutil.copyfile(candidate_path, target_tmp)
        if _sha256_path(target_tmp) != candidate_sha256:
            raise RuntimeError("Copied promotion target does not match candidate hash")
        decision_tmp.write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(target_tmp, target_path)
        os.replace(decision_tmp, decision_path)
    finally:
        target_tmp.unlink(missing_ok=True)
        decision_tmp.unlink(missing_ok=True)

    return decision


def promote_panel(paths: RefreshPaths, *, reviewed_by: str, reason: str) -> dict[str, object]:
    audit_dir = paths.promotion_target_panel.parent / "audits"
    decision_path = audit_dir / f"{paths.promotion_target_panel.stem}_promotion_decision.json"
    return promote_reviewed_candidate(
        candidate_path=paths.output_panel,
        baseline_path=paths.promoted_panel,
        target_path=paths.promotion_target_panel,
        build_manifest_path=paths.output_dir / "manifests" / "build_manifest.json",
        preflight_summary_path=paths.panel_preflight_summary,
        decision_path=decision_path,
        reviewed_by=reviewed_by,
        reason=reason,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run X5 MMM data refresh workflow.")
    parser.add_argument("--config", required=False, help="Path to data refresh YAML config.")
    parser.add_argument(
        "--mode",
        default="audit_only",
        choices=["audit_only", "build_panel", "promote_panel", "fast_smoke", "medium", "pilot", "production"],
        help="Refresh mode. Data workflow implements audit_only, build_panel and reviewed promote_panel.",
    )
    parser.add_argument("--reviewed-by", default="", help="Reviewer identity for immutable panel promotion.")
    parser.add_argument("--reason", default="", help="Reviewed promotion decision and rationale.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = Path(args.config).expanduser().resolve() if args.config else None
    paths = resolve_paths(config_path)
    log.info("Project root: %s", paths.root)
    log.info("Mode: %s", args.mode)
    if args.mode == "audit_only":
        mapping = load_mapping(paths.mapping_csv)
        population, population_audit = load_population(paths, mapping)
        media = load_media_long(
            paths.media_xlsx,
            panel_start=paths.panel_start,
            panel_end=paths.panel_end,
        )
        date_index = pd.DataFrame({"date": pd.date_range(paths.panel_start, paths.panel_end, freq="D")})
        macro, macro_audit = load_macro(paths, date_index)
        ruonia, ruonia_audit = load_ruonia(paths, date_index)
        print(
            json.dumps(
                {
                    "media_rows": int(len(media)),
                    "media_geos": int(media["media_geo_norm"].nunique()),
                    "media_budget_rub": float(media["budget"].sum()),
                    "model_geos": int(population["geo_label"].nunique()),
                    "missing_population": population_audit.loc[
                        population_audit["population_missing"], "geo_label"
                    ].tolist(),
                    "panel_start": paths.panel_start.date().isoformat(),
                    "panel_end": paths.panel_end.date().isoformat(),
                    "candidate_output": str(paths.output_panel),
                    "promoted_panel": str(paths.promoted_panel),
                    "macro_source_rows": int(len(macro_audit)),
                    "ruonia_source_rows": int(len(ruonia_audit)),
                    "usd_rub_log_return_std_2025": float(
                        macro.loc[macro["date"].dt.year.eq(2025), "usd_rub_log_return"].std()
                    ),
                    "brent_log_return_std_2025": float(
                        macro.loc[macro["date"].dt.year.eq(2025), "brent_log_return"].std()
                    ),
                    "ruonia_rate_std_2025": float(
                        ruonia.loc[ruonia["date"].dt.year.eq(2025), "ruonia_rate"].std()
                    ),
                    "max_control_staleness_days": {
                        "usd_rub": int(macro["usd_rub_close_staleness_days"].max()),
                        "brent": int(macro["brent_usd_close_staleness_days"].max()),
                        "ruonia": int(ruonia["ruonia_rate_staleness_days"].max()),
                    },
                    "output_dir": str(paths.output_dir),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if args.mode == "build_panel":
        summary = assemble_panel(paths)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.mode == "promote_panel":
        decision = promote_panel(paths, reviewed_by=args.reviewed_by, reason=args.reason)
        print(json.dumps(decision, ensure_ascii=False, indent=2))
        return
    raise NotImplementedError("Model execution modes stay in the model notebook layer for now.")


if __name__ == "__main__":
    main()
