"""Request validators for local pilot user create and update operations."""

from __future__ import annotations

from typing import Any, Mapping

from contracts.auth_contract_utils import AuthContractError
from services.auth_admin import ROLE_IDS


def validate_admin_user_create(payload: Mapping[str, Any]) -> dict[str, Any]:
    expected = {"email", "display_name", "password", "role_id"}
    if set(payload) != expected:
        raise AuthContractError("Create-user fields do not match the contract")
    if not all(isinstance(payload[key], str) for key in expected):
        raise AuthContractError("Create-user fields must be text")
    if not 2 <= len(payload["display_name"].strip()) <= 120:
        raise AuthContractError("display_name is invalid")
    if "@" not in payload["email"] or len(payload["email"]) > 254:
        raise AuthContractError("email is invalid")
    if not 12 <= len(payload["password"]) <= 256:
        raise AuthContractError("password is invalid")
    if payload["role_id"] not in ROLE_IDS:
        raise AuthContractError("role_id is invalid")
    return dict(payload)

def validate_admin_user_update(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not payload or set(payload) - {"display_name", "role_id"}:
        raise AuthContractError("Update-user fields do not match the contract")
    if "display_name" in payload and (
        not isinstance(payload["display_name"], str)
        or not 2 <= len(payload["display_name"].strip()) <= 120
    ):
        raise AuthContractError("display_name is invalid")
    if "role_id" in payload and payload["role_id"] not in ROLE_IDS:
        raise AuthContractError("role_id is invalid")
    return dict(payload)
