"""Strict semantic validator for ``admin_user_list_v1``."""

from __future__ import annotations

from typing import Any, Mapping

from contracts.admin_user_detail_v1 import validate_admin_user_item
from contracts.auth_contract_utils import (
    AuthContractError,
    exact_keys,
    required_list,
    required_mapping,
    validate_contract_header,
)
from services.auth_admin import ROLE_IDS, USER_STATUSES


CONTRACT_NAME = "admin_user_list_v1"


def validate_admin_user_list(payload: Mapping[str, Any]) -> dict[str, Any]:
    exact_keys(
        payload,
        {"contract_name", "schema_version", "items", "pagination", "applied_filters"},
        CONTRACT_NAME,
    )
    validate_contract_header(payload, CONTRACT_NAME)
    items = required_list(payload, "items")
    user_ids: set[str] = set()
    for item in items:
        if not isinstance(item, Mapping):
            raise AuthContractError("items must contain objects")
        validate_admin_user_item(item)
        if item["user_id"] in user_ids:
            raise AuthContractError("items contain duplicate users")
        user_ids.add(str(item["user_id"]))
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
    exact_keys(filters, {"search", "role", "status", "sort"}, "applied_filters")
    if filters.get("role") is not None and filters["role"] not in ROLE_IDS:
        raise AuthContractError("role filter is invalid")
    if filters.get("status") is not None and filters["status"] not in USER_STATUSES:
        raise AuthContractError("status filter is invalid")
    if filters.get("sort") not in {
        "created_desc",
        "created_asc",
        "name_asc",
        "email_asc",
        "last_login_desc",
    }:
        raise AuthContractError("sort filter is invalid")
    return dict(payload)
