"""Browser-safe product overview of the active MMM model."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


CONTRACT_NAME = "model_overview_v1"
SCHEMA_VERSION = "1.0.0"
RECORD_ORIGINS = {"application_runtime", "synthetic_fixture"}
ACTIVE_MODEL_STATUSES = {"available", "unavailable"}
CAPABILITY_STATUSES = {"available", "conditional", "unavailable"}
LIMITATION_STATUSES = {"active", "unavailable"}
VERSION_STATUSES = {"active", "registered"}
ARTIFACT_STATUSES = {"available", "unavailable"}
CAPABILITY_IDS = {
    "incremental_effect_forecast",
    "six_scenarios",
    "budget_allocation",
    "safe_recommendation",
    "marketer_report",
}
METHODOLOGY_IDS = {
    "carryover",
    "saturation",
    "uncertainty",
    "counterfactual_forecast",
    "scenario_search",
    "reliability_guardrails",
}

_MODEL_ID_RE = re.compile(r"^pkg_[0-9a-f]{16}_[0-9a-f]{16}$")
_ABSOLUTE_PATH_RE = re.compile(r"^(?:/|[A-Za-z]:[\\/]|file://)", re.IGNORECASE)
_FORBIDDEN_PRESENTATION_TERMS = (
    "backend",
    "api",
    "worker",
    "stack trace",
    "worker id",
    "local path",
    "model package",
    "internal registry",
)


class ModelOverviewContractError(ValueError):
    """Raised when a model-overview payload is unsafe or inconsistent."""


def _mapping(value: Any, field_name: str, keys: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ModelOverviewContractError(f"{field_name} must be an object")
    if set(value) != keys:
        raise ModelOverviewContractError(f"{field_name} keys are invalid")
    return value


def _list(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ModelOverviewContractError(f"{field_name} must be an array")
    return value


def _text(
    value: Any,
    field_name: str,
    *,
    nullable: bool = False,
    presentation: bool = False,
) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ModelOverviewContractError(f"{field_name} is required")
    if presentation:
        lowered = value.casefold()
        if any(term in lowered for term in _FORBIDDEN_PRESENTATION_TERMS):
            raise ModelOverviewContractError(f"{field_name} contains internal terminology")
    return value


def _integer(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ModelOverviewContractError(f"{field_name} must be non-negative")
    return value


def _timestamp(value: Any, field_name: str, *, nullable: bool = False) -> datetime | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise ModelOverviewContractError(f"{field_name} must be an ISO-8601 datetime")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ModelOverviewContractError(f"{field_name} must be an ISO-8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ModelOverviewContractError(f"{field_name} must include a timezone")
    return parsed


def _period(value: Any, field_name: str) -> None:
    period = _mapping(value, field_name, {"start_date", "end_date"})
    try:
        start = date.fromisoformat(str(period["start_date"]))
        end = date.fromisoformat(str(period["end_date"]))
    except ValueError as exc:
        raise ModelOverviewContractError(f"{field_name} must contain ISO dates") from exc
    if end < start:
        raise ModelOverviewContractError(f"{field_name} is reversed")


def _route(value: Any, field_name: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, str) or not value.startswith("/"):
        raise ModelOverviewContractError(f"{field_name} must be an internal route")
    parsed = urlsplit(value)
    if (
        parsed.scheme
        or parsed.netloc
        or "\\" in value
        or ".." in parsed.path.split("/")
        or parsed.path.startswith(("/Users/", "/home/", "/private/", "/tmp/", "/var/"))
    ):
        raise ModelOverviewContractError(f"{field_name} must be an internal route")


def _reject_paths_and_scores(value: Any, field_name: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key.casefold() in {"score", "quality_score", "reliability_score"}:
                raise ModelOverviewContractError("Unapproved model score is forbidden")
            _reject_paths_and_scores(nested, f"{field_name}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_paths_and_scores(nested, f"{field_name}[{index}]")
    elif isinstance(value, str) and _ABSOLUTE_PATH_RE.match(value):
        if field_name.endswith(".path"):
            _route(value, field_name)
        else:
            raise ModelOverviewContractError(f"Local path is forbidden at {field_name}")


def _status(value: Any, field_name: str) -> str:
    status = _mapping(value, field_name, {"code", "display_text"})
    code = _text(status["code"], f"{field_name}.code")
    if code not in ACTIVE_MODEL_STATUSES:
        raise ModelOverviewContractError(f"Unknown {field_name}.code")
    _text(status["display_text"], f"{field_name}.display_text", presentation=True)
    return str(code)


def validate_model_overview_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return one JSON-native model-overview payload."""

    root = _mapping(
        payload,
        "payload",
        {
            "contract_name",
            "schema_version",
            "record_origin",
            "active_model",
            "capabilities",
            "data_requirements",
            "methodology",
            "limitations",
            "versions",
            "artifacts",
            "updated_at_utc",
        },
    )
    if root["contract_name"] != CONTRACT_NAME:
        raise ModelOverviewContractError("Unknown model overview contract")
    if root["schema_version"] != SCHEMA_VERSION:
        raise ModelOverviewContractError("Unsupported model overview version")
    if root["record_origin"] not in RECORD_ORIGINS:
        raise ModelOverviewContractError("Unknown model overview record origin")

    active = _mapping(
        root["active_model"],
        "active_model",
        {
            "status",
            "model_id",
            "display_name",
            "version",
            "published_at_utc",
            "framework",
            "purpose",
            "training_period",
            "supported_scope",
            "description",
        },
    )
    active_status = _status(active["status"], "active_model.status")
    model_id = _text(active["model_id"], "active_model.model_id", nullable=True)
    if model_id is not None and not _MODEL_ID_RE.fullmatch(model_id):
        raise ModelOverviewContractError("active_model.model_id is invalid")
    for key in ("display_name", "version", "framework"):
        _text(active[key], f"active_model.{key}", nullable=True)
    _timestamp(active["published_at_utc"], "active_model.published_at_utc", nullable=True)
    _text(active["purpose"], "active_model.purpose", presentation=True)
    if active["training_period"] is not None:
        _period(active["training_period"], "active_model.training_period")
    if active["supported_scope"] is not None:
        scope = _mapping(
            active["supported_scope"],
            "active_model.supported_scope",
            {
                "segments",
                "channels",
                "targets",
                "geographies_n",
                "capability_cells_n",
                "allowed_use_counts",
            },
        )
        for key in ("segments", "channels", "targets"):
            values = _list(scope[key], f"active_model.supported_scope.{key}")
            if len(values) != len(set(values)):
                raise ModelOverviewContractError(f"active_model.supported_scope.{key} must be unique")
            for item in values:
                _text(item, f"active_model.supported_scope.{key}")
        _integer(scope["geographies_n"], "active_model.supported_scope.geographies_n")
        capability_cells_n = _integer(
            scope["capability_cells_n"],
            "active_model.supported_scope.capability_cells_n",
        )
        counts = _mapping(
            scope["allowed_use_counts"],
            "active_model.supported_scope.allowed_use_counts",
            {"primary", "caution", "diagnostic", "unavailable"},
        )
        if sum(_integer(value, f"allowed_use_counts.{key}") for key, value in counts.items()) != capability_cells_n:
            raise ModelOverviewContractError("Model capability counts do not reconcile")
    _text(active["description"], "active_model.description", presentation=True)
    available_values = (
        active["model_id"],
        active["display_name"],
        active["version"],
        active["framework"],
        active["training_period"],
        active["supported_scope"],
    )
    if active_status == "available" and any(value is None for value in available_values):
        raise ModelOverviewContractError("Available active model is incomplete")
    if active_status == "unavailable" and any(value is not None for value in available_values):
        raise ModelOverviewContractError("Unavailable active model must not expose model facts")

    capabilities = _list(root["capabilities"], "capabilities")
    capability_ids: set[str] = set()
    for index, raw in enumerate(capabilities):
        field_name = f"capabilities[{index}]"
        item = _mapping(raw, field_name, {"capability_id", "title", "status", "description"})
        capability_id = _text(item["capability_id"], f"{field_name}.capability_id")
        if capability_id not in CAPABILITY_IDS or capability_id in capability_ids:
            raise ModelOverviewContractError("Model capabilities are invalid")
        capability_ids.add(str(capability_id))
        _text(item["title"], f"{field_name}.title", presentation=True)
        if item["status"] not in CAPABILITY_STATUSES:
            raise ModelOverviewContractError(f"{field_name}.status is invalid")
        _text(item["description"], f"{field_name}.description", presentation=True)
    if capability_ids != CAPABILITY_IDS:
        raise ModelOverviewContractError("All product capabilities must be explicit")

    requirements = _list(root["data_requirements"], "data_requirements")
    requirement_ids: set[str] = set()
    for index, raw in enumerate(requirements):
        field_name = f"data_requirements[{index}]"
        item = _mapping(
            raw,
            field_name,
            {"requirement_id", "title", "required", "description", "accepted_values"},
        )
        requirement_id = _text(item["requirement_id"], f"{field_name}.requirement_id")
        if requirement_id in requirement_ids:
            raise ModelOverviewContractError("Data requirement IDs must be unique")
        requirement_ids.add(str(requirement_id))
        _text(item["title"], f"{field_name}.title", presentation=True)
        if not isinstance(item["required"], bool):
            raise ModelOverviewContractError(f"{field_name}.required must be boolean")
        _text(item["description"], f"{field_name}.description", presentation=True)
        accepted = _list(item["accepted_values"], f"{field_name}.accepted_values")
        if len(accepted) != len(set(accepted)):
            raise ModelOverviewContractError(f"{field_name}.accepted_values must be unique")
        for value in accepted:
            _text(value, f"{field_name}.accepted_values")

    methodology = _list(root["methodology"], "methodology")
    methodology_ids: set[str] = set()
    for index, raw in enumerate(methodology):
        field_name = f"methodology[{index}]"
        item = _mapping(raw, field_name, {"method_id", "title", "summary"})
        method_id = _text(item["method_id"], f"{field_name}.method_id")
        if method_id not in METHODOLOGY_IDS or method_id in methodology_ids:
            raise ModelOverviewContractError("Methodology entries are invalid")
        methodology_ids.add(str(method_id))
        _text(item["title"], f"{field_name}.title", presentation=True)
        _text(item["summary"], f"{field_name}.summary", presentation=True)
    if methodology_ids != METHODOLOGY_IDS:
        raise ModelOverviewContractError("All reviewed methodology entries are required")

    limitations = _list(root["limitations"], "limitations")
    limitation_codes: set[str] = set()
    for index, raw in enumerate(limitations):
        field_name = f"limitations[{index}]"
        item = _mapping(
            raw,
            field_name,
            {"code", "status", "title", "display_text", "recommended_action"},
        )
        code = _text(item["code"], f"{field_name}.code")
        if code in limitation_codes:
            raise ModelOverviewContractError("Model limitation codes must be unique")
        limitation_codes.add(str(code))
        if item["status"] not in LIMITATION_STATUSES:
            raise ModelOverviewContractError(f"{field_name}.status is invalid")
        _text(item["title"], f"{field_name}.title", presentation=True)
        _text(item["display_text"], f"{field_name}.display_text", presentation=True)
        _text(item["recommended_action"], f"{field_name}.recommended_action", presentation=True)
    if len(limitations) < 4:
        raise ModelOverviewContractError("Known model limitations are incomplete")

    versions = _list(root["versions"], "versions")
    version_ids: set[str] = set()
    active_version_ids: set[str] = set()
    for index, raw in enumerate(versions):
        field_name = f"versions[{index}]"
        item = _mapping(
            raw,
            field_name,
            {
                "model_id",
                "model_run_id",
                "registered_at_utc",
                "package_stage",
                "activation_status",
                "status",
                "source",
            },
        )
        version_id = _text(item["model_id"], f"{field_name}.model_id")
        if not _MODEL_ID_RE.fullmatch(str(version_id)) or version_id in version_ids:
            raise ModelOverviewContractError("Model version IDs are invalid")
        version_ids.add(str(version_id))
        _text(item["model_run_id"], f"{field_name}.model_run_id")
        _timestamp(item["registered_at_utc"], f"{field_name}.registered_at_utc", nullable=True)
        _text(item["package_stage"], f"{field_name}.package_stage")
        _text(item["activation_status"], f"{field_name}.activation_status")
        if item["status"] not in VERSION_STATUSES:
            raise ModelOverviewContractError(f"{field_name}.status is invalid")
        if item["status"] == "active":
            active_version_ids.add(str(version_id))
        if item["source"] not in {"registry_registration", "active_model_passport"}:
            raise ModelOverviewContractError(f"{field_name}.source is invalid")
    if active_status == "available":
        if active_version_ids != {str(model_id)} or str(model_id) not in version_ids:
            raise ModelOverviewContractError("Active model version is not registered")
    elif active_version_ids:
        raise ModelOverviewContractError("Unavailable model cannot have an active version")

    artifacts = _list(root["artifacts"], "artifacts")
    artifact_ids: set[str] = set()
    for index, raw in enumerate(artifacts):
        field_name = f"artifacts[{index}]"
        item = _mapping(raw, field_name, {"artifact_id", "title", "status", "path", "display_text"})
        artifact_id = _text(item["artifact_id"], f"{field_name}.artifact_id")
        if artifact_id in artifact_ids:
            raise ModelOverviewContractError("Model artifact IDs must be unique")
        artifact_ids.add(str(artifact_id))
        _text(item["title"], f"{field_name}.title", presentation=True)
        if item["status"] not in ARTIFACT_STATUSES:
            raise ModelOverviewContractError(f"{field_name}.status is invalid")
        _route(item["path"], f"{field_name}.path", nullable=True)
        if (item["status"] == "available") != (item["path"] is not None):
            raise ModelOverviewContractError(f"{field_name}.path is inconsistent")
        _text(item["display_text"], f"{field_name}.display_text", presentation=True)

    _timestamp(root["updated_at_utc"], "updated_at_utc")
    _reject_paths_and_scores(root)
    return json.loads(json.dumps(root, ensure_ascii=False))


def load_model_overview_schema() -> dict[str, Any]:
    return json.loads(
        Path(__file__).with_name("model_overview_v1.schema.json").read_text(encoding="utf-8")
    )
