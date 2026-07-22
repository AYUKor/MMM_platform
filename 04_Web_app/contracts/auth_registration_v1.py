"""Request validator for local pilot self-service registration."""

from __future__ import annotations

from typing import Any, Mapping

from contracts.auth_contract_utils import AuthContractError


def validate_auth_registration(payload: Mapping[str, Any]) -> dict[str, Any]:
    keys = set(payload)
    if not {"email", "password"} <= keys or keys - {"email", "password", "display_name"}:
        raise AuthContractError("Registration fields do not match the contract")
    email = payload["email"]
    password = payload["password"]
    display_name = payload.get("display_name")
    if not isinstance(email, str) or "@" not in email or len(email) > 254:
        raise AuthContractError("email is invalid")
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise AuthContractError("password is invalid")
    if display_name is not None:
        if not isinstance(display_name, str):
            raise AuthContractError("display_name is invalid")
        stripped = display_name.strip()
        if stripped and not 2 <= len(stripped) <= 120:
            raise AuthContractError("display_name is invalid")
    return dict(payload)
