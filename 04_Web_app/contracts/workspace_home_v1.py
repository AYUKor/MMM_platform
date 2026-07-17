"""Browser-safe contract for the marketer workspace home page."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


CONTRACT_NAME = "workspace_home_v1"
SCHEMA_VERSION = "1.0.0"
RECORD_ORIGINS = {"application_runtime", "synthetic_fixture"}
ACTIVE_STATUSES = {"queued", "running", "cancel_requested"}
JOB_STATUSES = ACTIVE_STATUSES | {"succeeded", "failed", "cancelled", "timed_out"}
MODEL_STATUSES = {"available", "unavailable"}
STAGE_STATUSES = {"pending", "active", "completed", "warning", "failed", "skipped"}
ACTION_IDS = {"new_calculation", "calculation_history", "model_overview", "help_catalog"}
WARNING_SEVERITIES = {"info", "warning", "error"}

_OPAQUE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*_[0-9a-f]{12,64}$")
_ABSOLUTE_PATH_RE = re.compile(r"^(?:/|[A-Za-z]:[\\/]|file://)", re.IGNORECASE)
_FORBIDDEN_PRESENTATION_TERMS = (
    "backend",
    "api",
    "worker",
    "stack trace",
    "local path",
    "model package",
    "internal registry",
)


class WorkspaceHomeContractError(ValueError):
    """Raised when a workspace-home projection is not safe or consistent."""


def _mapping(value: Any, field_name: str, keys: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise WorkspaceHomeContractError(f"{field_name} must be an object")
    if set(value) != keys:
        raise WorkspaceHomeContractError(f"{field_name} keys are invalid")
    return value


def _list(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise WorkspaceHomeContractError(f"{field_name} must be an array")
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
        raise WorkspaceHomeContractError(f"{field_name} is required")
    if presentation and any(
        term in value.casefold() for term in _FORBIDDEN_PRESENTATION_TERMS
    ):
        raise WorkspaceHomeContractError(f"{field_name} contains internal terminology")
    return value


def _integer(value: Any, field_name: str, *, nullable: bool = False) -> int | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise WorkspaceHomeContractError(f"{field_name} must be a non-negative integer")
    return value


def _number(value: Any, field_name: str, *, nullable: bool = False) -> float | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise WorkspaceHomeContractError(f"{field_name} must be non-negative")
    return float(value)


def _timestamp(value: Any, field_name: str, *, nullable: bool = False) -> datetime | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise WorkspaceHomeContractError(f"{field_name} must be an ISO-8601 datetime")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkspaceHomeContractError(
            f"{field_name} must be an ISO-8601 datetime"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise WorkspaceHomeContractError(f"{field_name} must include a timezone")
    return parsed


def _period(value: Any, field_name: str) -> None:
    period = _mapping(value, field_name, {"start_date", "end_date"})
    try:
        start = date.fromisoformat(str(period["start_date"]))
        end = date.fromisoformat(str(period["end_date"]))
    except ValueError as exc:
        raise WorkspaceHomeContractError(f"{field_name} must contain ISO dates") from exc
    if end < start:
        raise WorkspaceHomeContractError(f"{field_name} is reversed")


def _opaque_id(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not _OPAQUE_ID_RE.fullmatch(value):
        raise WorkspaceHomeContractError(f"{field_name} must be an opaque ID")


def _route(value: Any, field_name: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, str) or not value.startswith("/"):
        raise WorkspaceHomeContractError(f"{field_name} must be an internal route")
    parsed = urlsplit(value)
    if (
        parsed.scheme
        or parsed.netloc
        or "\\" in value
        or ".." in parsed.path.split("/")
        or parsed.path.startswith(("/Users/", "/home/", "/private/", "/tmp/", "/var/"))
    ):
        raise WorkspaceHomeContractError(f"{field_name} must be an internal route")


def _status(value: Any, field_name: str, allowed: set[str]) -> str:
    status = _mapping(value, field_name, {"code", "display_text"})
    code = _text(status["code"], f"{field_name}.code")
    if code not in allowed:
        raise WorkspaceHomeContractError(f"Unknown {field_name}.code")
    _text(status["display_text"], f"{field_name}.display_text", presentation=True)
    return code


def _reject_paths(value: Any, field_name: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            _reject_paths(nested, f"{field_name}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_paths(nested, f"{field_name}[{index}]")
    elif isinstance(value, str) and _ABSOLUTE_PATH_RE.match(value):
        if field_name.endswith("_path") or field_name.endswith(".path"):
            _route(value, field_name)
        else:
            raise WorkspaceHomeContractError(f"Local path is forbidden at {field_name}")


def validate_workspace_home_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return one JSON-native workspace-home payload."""

    root = _mapping(
        payload,
        "payload",
        {
            "contract_name",
            "schema_version",
            "record_origin",
            "summary",
            "active_calculations",
            "recent_calculations",
            "model",
            "quick_actions",
            "warnings",
            "updated_at_utc",
        },
    )
    if root["contract_name"] != CONTRACT_NAME:
        raise WorkspaceHomeContractError("Unknown workspace home contract")
    if root["schema_version"] != SCHEMA_VERSION:
        raise WorkspaceHomeContractError("Unsupported workspace home version")
    if root["record_origin"] not in RECORD_ORIGINS:
        raise WorkspaceHomeContractError("Unknown workspace home record origin")

    summary = _mapping(
        root["summary"],
        "summary",
        {"running", "queued", "completed_30d", "failed_30d"},
    )
    for key in summary:
        _integer(summary[key], f"summary.{key}")

    active = _list(root["active_calculations"], "active_calculations")
    active_ids: set[str] = set()
    active_counts = {"queued": 0, "running": 0}
    for index, raw in enumerate(active):
        field_name = f"active_calculations[{index}]"
        item = _mapping(
            raw,
            field_name,
            {
                "job_id",
                "campaign_name",
                "status",
                "current_stage",
                "created_at_utc",
                "progress_path",
                "can_cancel",
                "display_text",
            },
        )
        _opaque_id(item["job_id"], f"{field_name}.job_id")
        if item["job_id"] in active_ids:
            raise WorkspaceHomeContractError("Active calculation job IDs must be unique")
        active_ids.add(str(item["job_id"]))
        _text(item["campaign_name"], f"{field_name}.campaign_name")
        status_code = _status(item["status"], f"{field_name}.status", ACTIVE_STATUSES)
        active_counts["queued" if status_code == "queued" else "running"] += 1
        stage = item["current_stage"]
        if stage is not None:
            stage = _mapping(
                stage,
                f"{field_name}.current_stage",
                {"stage_id", "title", "status", "display_text"},
            )
            _text(stage["stage_id"], f"{field_name}.current_stage.stage_id")
            _text(stage["title"], f"{field_name}.current_stage.title", presentation=True)
            if stage["status"] not in STAGE_STATUSES:
                raise WorkspaceHomeContractError("Unknown current stage status")
            _text(stage["display_text"], f"{field_name}.current_stage.display_text", presentation=True)
        _timestamp(item["created_at_utc"], f"{field_name}.created_at_utc")
        _route(item["progress_path"], f"{field_name}.progress_path")
        if not isinstance(item["can_cancel"], bool):
            raise WorkspaceHomeContractError(f"{field_name}.can_cancel must be boolean")
        if item["can_cancel"] != (status_code in {"queued", "running"}):
            raise WorkspaceHomeContractError(f"{field_name}.can_cancel is inconsistent")
        _text(item["display_text"], f"{field_name}.display_text", presentation=True)
    if active_counts["queued"] != summary["queued"] or active_counts["running"] != summary["running"]:
        raise WorkspaceHomeContractError("Home active counts do not reconcile")

    recent = _list(root["recent_calculations"], "recent_calculations")
    recent_ids: set[str] = set()
    for index, raw in enumerate(recent):
        field_name = f"recent_calculations[{index}]"
        item = _mapping(
            raw,
            field_name,
            {
                "job_id",
                "campaign_name",
                "campaign_period",
                "total_budget_rub",
                "created_at_utc",
                "completed_at_utc",
                "status",
                "result_available",
                "report_available",
                "result_path",
                "progress_path",
                "warnings_count",
            },
        )
        _opaque_id(item["job_id"], f"{field_name}.job_id")
        if item["job_id"] in recent_ids or item["job_id"] in active_ids:
            raise WorkspaceHomeContractError("Home calculation job IDs must be unique")
        recent_ids.add(str(item["job_id"]))
        _text(item["campaign_name"], f"{field_name}.campaign_name")
        if item["campaign_period"] is not None:
            _period(item["campaign_period"], f"{field_name}.campaign_period")
        _number(item["total_budget_rub"], f"{field_name}.total_budget_rub", nullable=True)
        created = _timestamp(item["created_at_utc"], f"{field_name}.created_at_utc")
        completed = _timestamp(
            item["completed_at_utc"],
            f"{field_name}.completed_at_utc",
            nullable=True,
        )
        if completed is not None and created is not None and completed < created:
            raise WorkspaceHomeContractError(f"{field_name} timestamps are reversed")
        _status(item["status"], f"{field_name}.status", JOB_STATUSES)
        for key in ("result_available", "report_available"):
            if not isinstance(item[key], bool):
                raise WorkspaceHomeContractError(f"{field_name}.{key} must be boolean")
        if item["report_available"] and not item["result_available"]:
            raise WorkspaceHomeContractError(f"{field_name} report requires a result")
        _route(item["result_path"], f"{field_name}.result_path", nullable=True)
        if item["result_available"] != (item["result_path"] is not None):
            raise WorkspaceHomeContractError(f"{field_name}.result_path is inconsistent")
        _route(item["progress_path"], f"{field_name}.progress_path")
        _integer(item["warnings_count"], f"{field_name}.warnings_count", nullable=True)

    model = _mapping(
        root["model"],
        "model",
        {
            "status",
            "model_id",
            "display_name",
            "version",
            "published_at_utc",
            "training_period",
            "supported_scope",
            "description",
            "details_path",
        },
    )
    model_status = _status(model["status"], "model.status", MODEL_STATUSES)
    for key in ("model_id", "display_name", "version"):
        _text(model[key], f"model.{key}", nullable=True)
    _timestamp(model["published_at_utc"], "model.published_at_utc", nullable=True)
    if model["training_period"] is not None:
        _period(model["training_period"], "model.training_period")
    if model["supported_scope"] is not None:
        scope = _mapping(
            model["supported_scope"],
            "model.supported_scope",
            {"segments", "channels", "targets", "geographies_n"},
        )
        for key in ("segments", "channels", "targets"):
            values = _list(scope[key], f"model.supported_scope.{key}")
            if len(values) != len(set(values)):
                raise WorkspaceHomeContractError(f"model.supported_scope.{key} must be unique")
            for value in values:
                _text(value, f"model.supported_scope.{key}")
        _integer(scope["geographies_n"], "model.supported_scope.geographies_n")
    _text(model["description"], "model.description", presentation=True)
    _route(model["details_path"], "model.details_path")
    nullable_model_values = (
        model["model_id"],
        model["display_name"],
        model["version"],
        model["training_period"],
        model["supported_scope"],
    )
    if model_status == "available" and any(value is None for value in nullable_model_values):
        raise WorkspaceHomeContractError("Available model summary is incomplete")
    if model_status == "unavailable" and any(value is not None for value in nullable_model_values):
        raise WorkspaceHomeContractError("Unavailable model summary must not contain model facts")

    actions = _list(root["quick_actions"], "quick_actions")
    action_ids: set[str] = set()
    for index, raw in enumerate(actions):
        field_name = f"quick_actions[{index}]"
        action = _mapping(raw, field_name, {"action_id", "title", "description", "path"})
        action_id = _text(action["action_id"], f"{field_name}.action_id")
        if action_id not in ACTION_IDS or action_id in action_ids:
            raise WorkspaceHomeContractError("Quick actions are invalid")
        action_ids.add(str(action_id))
        _text(action["title"], f"{field_name}.title", presentation=True)
        _text(action["description"], f"{field_name}.description", presentation=True)
        _route(action["path"], f"{field_name}.path")
    if action_ids != ACTION_IDS:
        raise WorkspaceHomeContractError("Home must publish all real quick actions")

    warnings = _list(root["warnings"], "warnings")
    warning_codes: set[str] = set()
    for index, raw in enumerate(warnings):
        field_name = f"warnings[{index}]"
        warning = _mapping(
            raw,
            field_name,
            {"code", "severity", "title", "display_text", "recommended_action", "path"},
        )
        code = _text(warning["code"], f"{field_name}.code")
        if code in warning_codes:
            raise WorkspaceHomeContractError("Home warning codes must be unique")
        warning_codes.add(str(code))
        if warning["severity"] not in WARNING_SEVERITIES:
            raise WorkspaceHomeContractError(f"{field_name}.severity is invalid")
        _text(warning["title"], f"{field_name}.title", presentation=True)
        _text(warning["display_text"], f"{field_name}.display_text", presentation=True)
        _text(warning["recommended_action"], f"{field_name}.recommended_action", presentation=True)
        _route(warning["path"], f"{field_name}.path", nullable=True)

    _timestamp(root["updated_at_utc"], "updated_at_utc")
    _reject_paths(root)
    return json.loads(json.dumps(root, ensure_ascii=False))


def load_workspace_home_schema() -> dict[str, Any]:
    return json.loads(
        Path(__file__).with_name("workspace_home_v1.schema.json").read_text(encoding="utf-8")
    )
