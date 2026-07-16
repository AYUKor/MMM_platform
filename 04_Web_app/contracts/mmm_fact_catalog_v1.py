"""Reviewed static facts for the optional progress-screen education block."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


CONTRACT_NAME = "mmm_fact_catalog_v1"
SCHEMA_VERSION = "1.0.0"
_FACT_ID_RE = re.compile(r"^fact_[a-z0-9_]{3,64}$")
_CATEGORIES = {
    "adstock",
    "saturation",
    "forecast",
    "uncertainty",
    "support",
    "scenarios",
    "quality",
    "decision",
}


class MmmFactCatalogError(ValueError):
    """Raised when the static fact catalog violates its public contract."""


def validate_mmm_fact_catalog(payload: Mapping[str, Any]) -> None:
    if payload.get("contract_name") != CONTRACT_NAME:
        raise MmmFactCatalogError("Unknown MMM fact catalog contract")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise MmmFactCatalogError("Unsupported MMM fact catalog version")
    facts = payload.get("facts")
    if not isinstance(facts, list) or len(facts) < 20:
        raise MmmFactCatalogError("At least 20 reviewed facts are required")
    fact_ids: set[str] = set()
    for index, fact in enumerate(facts):
        if not isinstance(fact, Mapping):
            raise MmmFactCatalogError(f"facts[{index}] must be an object")
        fact_id = fact.get("fact_id")
        category = fact.get("category")
        text = fact.get("text")
        source_label = fact.get("source_label")
        if not isinstance(fact_id, str) or not _FACT_ID_RE.fullmatch(fact_id):
            raise MmmFactCatalogError(f"facts[{index}].fact_id is invalid")
        if fact_id in fact_ids:
            raise MmmFactCatalogError(f"Duplicate fact_id: {fact_id}")
        fact_ids.add(fact_id)
        if category not in _CATEGORIES:
            raise MmmFactCatalogError(f"facts[{index}].category is invalid")
        if not isinstance(text, str) or not text.strip() or len(text) > 280:
            raise MmmFactCatalogError(f"facts[{index}].text is invalid")
        if text.count(".") > 2:
            raise MmmFactCatalogError(f"facts[{index}].text is longer than two sentences")
        if not isinstance(source_label, str) or not source_label.strip():
            raise MmmFactCatalogError(f"facts[{index}].source_label is required")


def build_mmm_fact_catalog() -> dict[str, Any]:
    source = "Внутренняя методология MMM"
    facts = [
        ("fact_adstock_001", "adstock", "Эффект рекламы может сохраняться после дня показа."),
        ("fact_adstock_002", "adstock", "Разные каналы могут иметь разную длительность остаточного эффекта."),
        ("fact_saturation_001", "saturation", "Дополнительный рубль рекламы не обязан давать тот же эффект, что и предыдущий."),
        ("fact_saturation_002", "saturation", "При высокой интенсивности размещения отдача может расти медленнее бюджета."),
        ("fact_forecast_001", "forecast", "Прогноз показывает дополнительный медиаэффект относительно варианта без кампании."),
        ("fact_forecast_002", "forecast", "Прогноз не является полным прогнозом всего оборота бизнеса."),
        ("fact_uncertainty_001", "uncertainty", "P50 — центральная оценка, а P10 и P90 показывают диапазон неопределенности."),
        ("fact_uncertainty_002", "uncertainty", "Широкий диапазон P10–P90 означает, что результат сильнее зависит от неопределенности модели."),
        ("fact_support_001", "support", "Надежнее оценивать бюджеты, похожие на те, которые модель видела в истории."),
        ("fact_support_002", "support", "Выход за историческую зону не запрещает кампанию, но требует осторожной интерпретации."),
        ("fact_scenarios_001", "scenarios", "S1 сохраняет исходное распределение бюджета без изменений."),
        ("fact_scenarios_002", "scenarios", "S2 поровну делит бюджет между исходными связками географии и канала."),
        ("fact_scenarios_003", "scenarios", "S3 сохраняет бюджеты каналов и выравнивает географии внутри каждого канала."),
        ("fact_scenarios_004", "scenarios", "S4 сохраняет бюджеты географий и выравнивает каналы внутри каждой географии."),
        ("fact_scenarios_005", "scenarios", "S5 ищет более устойчивое распределение в знакомой для модели исторической зоне."),
        ("fact_scenarios_006", "scenarios", "S6 перебирает перераспределения только между разрешенными связками исходного плана."),
        ("fact_quality_001", "quality", "Диагностические показатели помогают понять результат, но не управляют оптимизацией бюджета."),
        ("fact_quality_002", "quality", "Каналы с ограниченными данными получают предупреждения или ограничения на рост бюджета."),
        ("fact_decision_001", "decision", "Лучший математический вариант не становится рекомендацией, если он нарушает ограничения надежности."),
        ("fact_decision_002", "decision", "Рекомендация относится к распределению бюджета, а не заменяет решение о запуске кампании."),
    ]
    payload = {
        "contract_name": CONTRACT_NAME,
        "schema_version": SCHEMA_VERSION,
        "facts": [
            {
                "fact_id": fact_id,
                "category": category,
                "text": text,
                "source_label": source,
            }
            for fact_id, category, text in facts
        ],
    }
    validate_mmm_fact_catalog(payload)
    return payload
