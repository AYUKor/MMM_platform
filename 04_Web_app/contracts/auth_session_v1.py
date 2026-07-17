"""Strict semantic validator for ``auth_session_v1``."""

from __future__ import annotations

from typing import Any, Mapping

from contracts.auth_contract_utils import (
    AuthContractError,
    SESSION_ID_RE,
    USER_ID_RE,
    exact_keys,
    required_list,
    required_mapping,
    required_text,
    timestamp,
    validate_contract_header,
)
from services.auth_admin import ROLE_CATALOG


CONTRACT_NAME = "auth_session_v1"


def validate_auth_session(payload: Mapping[str, Any]) -> dict[str, Any]:
    exact_keys(
        payload,
        {"contract_name", "schema_version", "authenticated", "user", "session"},
        CONTRACT_NAME,
    )
    validate_contract_header(payload, CONTRACT_NAME)
    authenticated = payload.get("authenticated")
    if not isinstance(authenticated, bool):
        raise AuthContractError("authenticated must be boolean")
    if not authenticated:
        if payload.get("user") is not None or payload.get("session") is not None:
            raise AuthContractError("Anonymous session must not contain user or session")
        return dict(payload)

    user = required_mapping(payload, "user")
    session = required_mapping(payload, "session")
    exact_keys(
        user,
        {"user_id", "display_name", "email", "role", "permissions", "status"},
        "user",
    )
    user_id = required_text(user, "user_id")
    if not USER_ID_RE.fullmatch(user_id):
        raise AuthContractError("user_id is invalid")
    required_text(user, "display_name", maximum=120)
    email = required_text(user, "email", maximum=254)
    if "@" not in email:
        raise AuthContractError("email is invalid")
    if user.get("status") != "active":
        raise AuthContractError("Authenticated user must be active")
    role = required_mapping(user, "role")
    exact_keys(role, {"role_id", "title"}, "role")
    role_id = required_text(role, "role_id")
    if role_id not in ROLE_CATALOG or role.get("title") != ROLE_CATALOG[role_id]["title"]:
        raise AuthContractError("role does not match the role catalog")
    permissions = required_list(user, "permissions")
    if permissions != ROLE_CATALOG[role_id]["permissions"]:
        raise AuthContractError("permissions do not match the assigned role")

    exact_keys(
        session,
        {
            "session_id",
            "created_at_utc",
            "expires_at_utc",
            "last_seen_at_utc",
            "idle_timeout_seconds",
        },
        "session",
    )
    session_id = required_text(session, "session_id")
    if not SESSION_ID_RE.fullmatch(session_id):
        raise AuthContractError("session_id is invalid")
    created = timestamp(session.get("created_at_utc"), "created_at_utc")
    expires = timestamp(session.get("expires_at_utc"), "expires_at_utc")
    last_seen = timestamp(session.get("last_seen_at_utc"), "last_seen_at_utc")
    if not created <= last_seen <= expires:
        raise AuthContractError("Session timestamps are inconsistent")
    idle = session.get("idle_timeout_seconds")
    if not isinstance(idle, int) or isinstance(idle, bool) or idle < 60:
        raise AuthContractError("idle_timeout_seconds is invalid")
    return dict(payload)
