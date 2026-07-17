"""Strict semantic validator for ``admin_user_detail_v1``."""

from __future__ import annotations

from typing import Any, Mapping

from contracts.auth_contract_utils import (
    AuthContractError,
    USER_ID_RE,
    exact_keys,
    optional_text,
    required_mapping,
    required_text,
    timestamp,
    validate_contract_header,
)
from services.auth_admin import ROLE_CATALOG


CONTRACT_NAME = "admin_user_detail_v1"


def validate_admin_user_item(payload: Mapping[str, Any]) -> dict[str, Any]:
    exact_keys(
        payload,
        {
            "user_id",
            "display_name",
            "email",
            "role",
            "status",
            "created_at_utc",
            "updated_at_utc",
            "last_login_at_utc",
            "created_by_user_id",
            "active_sessions_n",
        },
        "admin user",
    )
    user_id = required_text(payload, "user_id")
    if not USER_ID_RE.fullmatch(user_id):
        raise AuthContractError("user_id is invalid")
    required_text(payload, "display_name", maximum=120)
    email = required_text(payload, "email", maximum=254)
    if "@" not in email:
        raise AuthContractError("email is invalid")
    role = required_mapping(payload, "role")
    exact_keys(role, {"role_id", "title"}, "role")
    role_id = required_text(role, "role_id")
    if role_id not in ROLE_CATALOG or role.get("title") != ROLE_CATALOG[role_id]["title"]:
        raise AuthContractError("role does not match the role catalog")
    if payload.get("status") not in {"active", "disabled"}:
        raise AuthContractError("status is invalid")
    created = timestamp(payload.get("created_at_utc"), "created_at_utc")
    updated = timestamp(payload.get("updated_at_utc"), "updated_at_utc")
    last_login = timestamp(payload.get("last_login_at_utc"), "last_login_at_utc", nullable=True)
    if updated < created or (last_login is not None and last_login < created):
        raise AuthContractError("User timestamps are inconsistent")
    created_by = optional_text(payload, "created_by_user_id")
    if created_by is not None and not USER_ID_RE.fullmatch(created_by):
        raise AuthContractError("created_by_user_id is invalid")
    sessions = payload.get("active_sessions_n")
    if not isinstance(sessions, int) or isinstance(sessions, bool) or sessions < 0:
        raise AuthContractError("active_sessions_n is invalid")
    return dict(payload)

def validate_admin_user_detail(payload: Mapping[str, Any]) -> dict[str, Any]:
    exact_keys(payload, {"contract_name", "schema_version", "user"}, CONTRACT_NAME)
    validate_contract_header(payload, CONTRACT_NAME)
    validate_admin_user_item(required_mapping(payload, "user"))
    return dict(payload)
