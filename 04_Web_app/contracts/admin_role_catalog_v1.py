"""Strict semantic validator for ``admin_role_catalog_v1``."""

from __future__ import annotations

from typing import Any, Mapping

from contracts.auth_contract_utils import (
    AuthContractError,
    exact_keys,
    required_list,
    required_text,
    validate_contract_header,
)
from services.auth_admin import PERMISSION_CATALOG, PERMISSION_CATALOG_VERSION, ROLE_CATALOG


CONTRACT_NAME = "admin_role_catalog_v1"


def validate_admin_role_catalog(payload: Mapping[str, Any]) -> dict[str, Any]:
    exact_keys(
        payload,
        {"contract_name", "schema_version", "catalog_version", "permissions", "roles"},
        CONTRACT_NAME,
    )
    validate_contract_header(payload, CONTRACT_NAME)
    if payload.get("catalog_version") != PERMISSION_CATALOG_VERSION:
        raise AuthContractError("catalog_version is invalid")
    permissions = required_list(payload, "permissions")
    if permissions != [dict(item) for item in PERMISSION_CATALOG]:
        raise AuthContractError("permission catalog does not match the server catalog")
    roles = required_list(payload, "roles")
    expected = [ROLE_CATALOG[role_id] for role_id in ("viewer", "analyst", "admin")]
    if roles != expected:
        raise AuthContractError("role catalog does not match the server catalog")
    for role in roles:
        if not isinstance(role, Mapping):
            raise AuthContractError("roles must contain objects")
        exact_keys(role, {"role_id", "title", "description", "permissions"}, "role")
        required_text(role, "title", maximum=120)
        required_text(role, "description", maximum=500)
    return dict(payload)
