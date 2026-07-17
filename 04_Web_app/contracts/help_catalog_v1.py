"""Versioned browser-safe help catalog contract."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


CONTRACT_NAME = "help_catalog_v1"
SCHEMA_VERSION = "1.0.0"
RECORD_ORIGINS = {"versioned_help_catalog", "synthetic_fixture"}
SECTION_IDS = (
    "getting_started",
    "data_preparation",
    "scenarios",
    "result_reading",
    "reliability",
    "media_plan",
    "report",
    "common_errors",
    "limitations",
)
SAFE_ROUTES = {"/", "/calculations", "/calculations/new", "/model", "/help"}
BLOCK_TYPES = {"paragraph", "steps", "note"}
NOTE_TONES = {"info", "warning"}

_ARTICLE_ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,80}$")
_UNSAFE_CONTENT_RE = re.compile(
    r"<[^>]*>|javascript:|data:text/html|on(?:error|load|click)\s*=",
    re.IGNORECASE,
)
_ABSOLUTE_PATH_RE = re.compile(r"^(?:/|[A-Za-z]:[\\/]|file://)", re.IGNORECASE)
_FORBIDDEN_CONTENT_TERMS = (
    "backend",
    "stack trace",
    "worker id",
    "local path",
    "model package",
    "internal registry",
)


class HelpCatalogContractError(ValueError):
    """Raised when help content is unsafe or structurally inconsistent."""


def _mapping(value: Any, field_name: str, keys: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HelpCatalogContractError(f"{field_name} must be an object")
    if set(value) != keys:
        raise HelpCatalogContractError(f"{field_name} keys are invalid")
    return value


def _list(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise HelpCatalogContractError(f"{field_name} must be an array")
    return value


def _text(value: Any, field_name: str, *, max_length: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise HelpCatalogContractError(f"{field_name} is invalid")
    if _UNSAFE_CONTENT_RE.search(value):
        raise HelpCatalogContractError(f"{field_name} contains unsafe markup")
    if any(term in value.casefold() for term in _FORBIDDEN_CONTENT_TERMS):
        raise HelpCatalogContractError(f"{field_name} contains internal terminology")
    return value


def _timestamp(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise HelpCatalogContractError(f"{field_name} must be an ISO-8601 datetime")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HelpCatalogContractError(f"{field_name} must be an ISO-8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HelpCatalogContractError(f"{field_name} must include a timezone")
    return parsed


def _route(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or value not in SAFE_ROUTES:
        raise HelpCatalogContractError(f"{field_name} is not an approved route")
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise HelpCatalogContractError(f"{field_name} is not an approved route")


def _reject_paths(value: Any, field_name: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            _reject_paths(nested, f"{field_name}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_paths(nested, f"{field_name}[{index}]")
    elif isinstance(value, str) and _ABSOLUTE_PATH_RE.match(value):
        if ".related_routes[" in field_name:
            _route(value, field_name)
        else:
            raise HelpCatalogContractError(f"Local path is forbidden at {field_name}")


def validate_help_catalog_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return one JSON-native help catalog."""

    root = _mapping(
        payload,
        "payload",
        {
            "contract_name",
            "schema_version",
            "record_origin",
            "sections",
            "updated_at_utc",
        },
    )
    if root["contract_name"] != CONTRACT_NAME:
        raise HelpCatalogContractError("Unknown help catalog contract")
    if root["schema_version"] != SCHEMA_VERSION:
        raise HelpCatalogContractError("Unsupported help catalog version")
    if root["record_origin"] not in RECORD_ORIGINS:
        raise HelpCatalogContractError("Unknown help catalog record origin")

    sections = _list(root["sections"], "sections")
    if len(sections) != len(SECTION_IDS):
        raise HelpCatalogContractError("Help catalog section set is incomplete")
    article_ids: set[str] = set()
    related_by_article: dict[str, set[str]] = {}
    section_ids: list[str] = []
    for section_index, raw_section in enumerate(sections, start=1):
        field_name = f"sections[{section_index - 1}]"
        section = _mapping(
            raw_section,
            field_name,
            {"section_id", "order", "title", "articles"},
        )
        section_id = _text(section["section_id"], f"{field_name}.section_id", max_length=80)
        section_ids.append(section_id)
        if section["order"] != section_index:
            raise HelpCatalogContractError("Help sections must have deterministic order")
        _text(section["title"], f"{field_name}.title", max_length=120)
        articles = _list(section["articles"], f"{field_name}.articles")
        if not articles:
            raise HelpCatalogContractError(f"{field_name} must contain an article")
        for article_index, raw_article in enumerate(articles):
            article_field = f"{field_name}.articles[{article_index}]"
            article = _mapping(
                raw_article,
                article_field,
                {
                    "article_id",
                    "title",
                    "summary",
                    "body",
                    "related_routes",
                    "related_article_ids",
                    "keywords",
                },
            )
            article_id = _text(
                article["article_id"],
                f"{article_field}.article_id",
                max_length=80,
            )
            if not _ARTICLE_ID_RE.fullmatch(article_id) or article_id in article_ids:
                raise HelpCatalogContractError("Help article IDs must be unique and stable")
            article_ids.add(article_id)
            _text(article["title"], f"{article_field}.title", max_length=160)
            _text(article["summary"], f"{article_field}.summary", max_length=500)
            body = _list(article["body"], f"{article_field}.body")
            if not body:
                raise HelpCatalogContractError(f"{article_field}.body must not be empty")
            for block_index, raw_block in enumerate(body):
                block_field = f"{article_field}.body[{block_index}]"
                if not isinstance(raw_block, Mapping):
                    raise HelpCatalogContractError(f"{block_field} must be an object")
                block_type = raw_block.get("block_type")
                if block_type not in BLOCK_TYPES:
                    raise HelpCatalogContractError(f"{block_field}.block_type is invalid")
                if block_type == "paragraph":
                    block = _mapping(raw_block, block_field, {"block_type", "text"})
                    _text(block["text"], f"{block_field}.text")
                elif block_type == "steps":
                    block = _mapping(raw_block, block_field, {"block_type", "items"})
                    items = _list(block["items"], f"{block_field}.items")
                    if not items:
                        raise HelpCatalogContractError(f"{block_field}.items must not be empty")
                    for item in items:
                        _text(item, f"{block_field}.items", max_length=500)
                else:
                    block = _mapping(
                        raw_block,
                        block_field,
                        {"block_type", "tone", "title", "text"},
                    )
                    if block["tone"] not in NOTE_TONES:
                        raise HelpCatalogContractError(f"{block_field}.tone is invalid")
                    _text(block["title"], f"{block_field}.title", max_length=160)
                    _text(block["text"], f"{block_field}.text")
            routes = _list(article["related_routes"], f"{article_field}.related_routes")
            if len(routes) != len(set(routes)):
                raise HelpCatalogContractError("Related routes must be unique")
            for route in routes:
                _route(route, f"{article_field}.related_routes")
            related = _list(
                article["related_article_ids"],
                f"{article_field}.related_article_ids",
            )
            if len(related) != len(set(related)) or article_id in related:
                raise HelpCatalogContractError("Related help article IDs are invalid")
            for related_id in related:
                _text(related_id, f"{article_field}.related_article_ids", max_length=80)
            related_by_article[article_id] = set(related)
            keywords = _list(article["keywords"], f"{article_field}.keywords")
            normalized_keywords: set[str] = set()
            for keyword in keywords:
                value = _text(keyword, f"{article_field}.keywords", max_length=80)
                normalized_keywords.add(value.casefold())
            if len(normalized_keywords) != len(keywords) or len(keywords) < 2:
                raise HelpCatalogContractError("Help article keywords are invalid")

    if tuple(section_ids) != SECTION_IDS:
        raise HelpCatalogContractError("Help sections do not match the reviewed catalog")
    unknown_related = {
        related_id
        for related_ids in related_by_article.values()
        for related_id in related_ids
        if related_id not in article_ids
    }
    if unknown_related:
        raise HelpCatalogContractError("Help articles reference unknown related IDs")
    _timestamp(root["updated_at_utc"], "updated_at_utc")
    _reject_paths(root)
    return json.loads(json.dumps(root, ensure_ascii=False))


def load_help_catalog_schema() -> dict[str, Any]:
    return json.loads(
        Path(__file__).with_name("help_catalog_v1.schema.json").read_text(encoding="utf-8")
    )
