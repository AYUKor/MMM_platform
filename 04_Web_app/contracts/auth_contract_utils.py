"""Shared strict validation helpers for Phase E browser-safe contracts."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Mapping


SCHEMA_VERSION = "1.0.0"
USER_ID_RE = re.compile(r"^usr_[0-9a-f]{24}$")
SESSION_ID_RE = re.compile(r"^ses_[0-9a-f]{24}$")
EVENT_ID_RE = re.compile(r"^evt_[0-9a-f]{24}$")
REQUEST_ID_RE = re.compile(r"^req_[0-9a-f]{24}$")
ABSOLUTE_PATH_RE = re.compile(r"^(?:/|[A-Za-z]:[\\/]|file://)", re.IGNORECASE)


class AuthContractError(ValueError):
    """Raised when an auth/admin payload violates its versioned contract."""


def exact_keys(payload: Mapping[str, Any], expected: set[str], field: str) -> None:
    if set(payload) != expected:
        raise AuthContractError(f"{field} keys do not match the contract")


def required_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise AuthContractError(f"{key} must be an object")
    return value


def required_list(payload: Mapping[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise AuthContractError(f"{key} must be an array")
    return value


def required_text(payload: Mapping[str, Any], key: str, *, maximum: int = 500) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise AuthContractError(f"{key} must be non-empty text")
    reject_unsafe_text(value, key)
    return value


def optional_text(payload: Mapping[str, Any], key: str, *, maximum: int = 500) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise AuthContractError(f"{key} must be null or non-empty text")
    reject_unsafe_text(value, key)
    return value


def timestamp(value: Any, field: str, *, nullable: bool = False) -> datetime | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise AuthContractError(f"{field} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise AuthContractError(f"{field} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise AuthContractError(f"{field} must include a timezone")
    return parsed


def reject_unsafe_text(value: str, field: str) -> None:
    lowered = value.casefold()
    if ABSOLUTE_PATH_RE.match(value):
        raise AuthContractError(f"{field} must not expose an absolute path")
    for marker in ("password_hash", "session_secret", "set-cookie", "traceback"):
        if marker in lowered:
            raise AuthContractError(f"{field} contains sensitive technical text")


def validate_contract_header(payload: Mapping[str, Any], contract_name: str) -> None:
    if payload.get("contract_name") != contract_name:
        raise AuthContractError("contract_name is invalid")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise AuthContractError("schema_version is invalid")
