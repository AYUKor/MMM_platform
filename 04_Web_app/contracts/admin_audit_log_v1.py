"""Strict semantic validator for ``admin_audit_log_v1``."""

from __future__ import annotations

from typing import Any, Mapping

from contracts.auth_contract_utils import (
    AuthContractError,
    EVENT_ID_RE,
    REQUEST_ID_RE,
    USER_ID_RE,
    exact_keys,
    optional_text,
    required_list,
    required_mapping,
    required_text,
    timestamp,
    validate_contract_header,
)
from services.auth_admin import AUDIT_EVENT_TYPES


CONTRACT_NAME = "admin_audit_log_v1"


def validate_admin_audit_log(payload: Mapping[str, Any]) -> dict[str, Any]:
    exact_keys(
        payload,
        {"contract_name", "schema_version", "items", "pagination", "applied_filters"},
        CONTRACT_NAME,
    )
    validate_contract_header(payload, CONTRACT_NAME)
    items = required_list(payload, "items")
    event_ids: set[str] = set()
    for item in items:
        if not isinstance(item, Mapping):
            raise AuthContractError("items must contain objects")
        exact_keys(
            item,
            {
                "event_id",
                "event_type",
                "occurred_at_utc",
                "actor_user_id",
                "actor_display_name",
                "target_type",
                "target_id",
                "result",
                "browser_safe_summary",
                "request_id",
            },
            "audit event",
        )
        event_id = required_text(item, "event_id")
        if not EVENT_ID_RE.fullmatch(event_id) or event_id in event_ids:
            raise AuthContractError("event_id is invalid or duplicated")
        event_ids.add(event_id)
        if item.get("event_type") not in AUDIT_EVENT_TYPES:
            raise AuthContractError("event_type is invalid")
        timestamp(item.get("occurred_at_utc"), "occurred_at_utc")
        actor_id = optional_text(item, "actor_user_id")
        if actor_id is not None and not USER_ID_RE.fullmatch(actor_id):
            raise AuthContractError("actor_user_id is invalid")
        optional_text(item, "actor_display_name", maximum=120)
        required_text(item, "target_type", maximum=80)
        optional_text(item, "target_id", maximum=120)
        if item.get("result") not in {"succeeded", "denied", "rate_limited", "account_disabled"}:
            raise AuthContractError("result is invalid")
        required_text(item, "browser_safe_summary", maximum=500)
        request_id = required_text(item, "request_id")
        if not REQUEST_ID_RE.fullmatch(request_id):
            raise AuthContractError("request_id is invalid")
    pagination = required_mapping(payload, "pagination")
    exact_keys(pagination, {"page", "page_size", "total_items", "total_pages"}, "pagination")
    for key in ("page", "page_size", "total_items", "total_pages"):
        if not isinstance(pagination.get(key), int) or isinstance(pagination.get(key), bool):
            raise AuthContractError(f"pagination.{key} is invalid")
    if pagination["page"] < 1 or pagination["page_size"] < 1 or pagination["total_items"] < 0:
        raise AuthContractError("pagination values are invalid")
    expected_pages = (pagination["total_items"] + pagination["page_size"] - 1) // pagination["page_size"]
    if pagination["total_pages"] != expected_pages or len(items) > pagination["page_size"]:
        raise AuthContractError("pagination is inconsistent")
    filters = required_mapping(payload, "applied_filters")
    exact_keys(
        filters,
        {"actor_user_id", "event_type", "occurred_from_utc", "occurred_to_utc", "sort"},
        "applied_filters",
    )
    if filters.get("actor_user_id") is not None and not USER_ID_RE.fullmatch(filters["actor_user_id"]):
        raise AuthContractError("actor filter is invalid")
    if filters.get("event_type") is not None and filters["event_type"] not in AUDIT_EVENT_TYPES:
        raise AuthContractError("event filter is invalid")
    occurred_from = timestamp(filters.get("occurred_from_utc"), "occurred_from_utc", nullable=True)
    occurred_to = timestamp(filters.get("occurred_to_utc"), "occurred_to_utc", nullable=True)
    if occurred_from is not None and occurred_to is not None and occurred_to < occurred_from:
        raise AuthContractError("audit date filters are inconsistent")
    if filters.get("sort") not in {"occurred_desc", "occurred_asc"}:
        raise AuthContractError("sort is invalid")
    return dict(payload)
