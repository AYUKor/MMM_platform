"""Strict semantic validator for ``admin_system_status_v1``."""

from __future__ import annotations

from typing import Any, Mapping

from contracts.auth_contract_utils import (
    AuthContractError,
    exact_keys,
    required_mapping,
    required_text,
    timestamp,
    validate_contract_header,
)


CONTRACT_NAME = "admin_system_status_v1"
STATUS_CODES = {"healthy", "degraded", "unavailable"}
SUBSYSTEMS = {"application", "storage", "queue", "model", "reports", "auth_storage"}


def validate_admin_system_status(payload: Mapping[str, Any]) -> dict[str, Any]:
    exact_keys(
        payload,
        {
            "contract_name",
            "schema_version",
            "overall_status",
            "checked_at_utc",
            "subsystems",
            "build",
        },
        CONTRACT_NAME,
    )
    validate_contract_header(payload, CONTRACT_NAME)
    if payload.get("overall_status") not in STATUS_CODES:
        raise AuthContractError("overall_status is invalid")
    timestamp(payload.get("checked_at_utc"), "checked_at_utc")
    subsystems = required_mapping(payload, "subsystems")
    exact_keys(subsystems, SUBSYSTEMS, "subsystems")
    statuses: list[str] = []
    for subsystem_id, subsystem in subsystems.items():
        if not isinstance(subsystem, Mapping):
            raise AuthContractError(f"{subsystem_id} must be an object")
        exact_keys(subsystem, {"status", "display_text", "facts"}, subsystem_id)
        status = subsystem.get("status")
        if status not in STATUS_CODES:
            raise AuthContractError(f"{subsystem_id}.status is invalid")
        statuses.append(str(status))
        required_text(subsystem, "display_text", maximum=500)
        facts = required_mapping(subsystem, "facts")
        for key, value in facts.items():
            if not isinstance(key, str) or not isinstance(value, (str, int, float, bool, type(None))):
                raise AuthContractError(f"{subsystem_id}.facts is invalid")
            if isinstance(value, str):
                required_text({"value": value}, "value", maximum=500)
    expected_overall = (
        "unavailable"
        if subsystems["application"]["status"] == "unavailable"
        or subsystems["auth_storage"]["status"] == "unavailable"
        else "degraded"
        if any(status != "healthy" for status in statuses)
        else "healthy"
    )
    if payload["overall_status"] != expected_overall:
        raise AuthContractError("overall_status does not match subsystem status")
    build = required_mapping(payload, "build")
    exact_keys(
        build,
        {"application_version", "api_version", "config_schema_version", "source_revision"},
        "build",
    )
    for key in ("application_version", "api_version", "config_schema_version"):
        required_text(build, key, maximum=100)
    source_revision = build.get("source_revision")
    if source_revision is not None and (
        not isinstance(source_revision, str) or not re_full_sha(source_revision)
    ):
        raise AuthContractError("source_revision is invalid")
    return dict(payload)


def re_full_sha(value: str) -> bool:
    return len(value) == 40 and all(character in "0123456789abcdef" for character in value)
