"""Browser-safe product API contracts for the research MMM application.

The module contains no model or optimizer calculations. It validates compact
API projections assembled from the immutable model package and application
state, and centralizes stable HTTP error codes for frontend behavior.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "1.0.0"
MODEL_PASSPORT_CONTRACT = "model_passport_v1"
JOB_LIST_CONTRACT = "job_list_v1"
HTTP_ERROR_CATALOG_CONTRACT = "http_error_catalog_v1"
CALCULATION_PROFILE_CONTRACT = "calculation_profile_v1"

DEPLOYMENT_PROFILES = {"local_development", "research_pilot"}
OOT_STATUS_CODES = {"passed", "unavailable", "failed"}
REPLAY_STATUS_CODES = {"passed", "unavailable", "failed"}
ALLOWED_USE_CODES = {"primary", "caution", "diagnostic", "unavailable"}
JOB_STATUS_CODES = {
    "queued",
    "running",
    "cancel_requested",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PACKAGE_ID_RE = re.compile(r"^pkg_[0-9a-f]{16}_[0-9a-f]{16}$")
_ABSOLUTE_PATH_RE = re.compile(r"^(?:/|[A-Za-z]:[\\/]|file://)", re.IGNORECASE)


class ProductApiContractError(ValueError):
    """Raised when a Product API v1 payload violates semantic rules."""


HTTP_ERROR_CATALOG: dict[str, dict[str, Any]] = {
    "ADMIN_LAST_ADMIN_PROTECTED": {
        "http_status": 409,
        "retryable": False,
        "display_text": "Нельзя отключить или понизить роль последнего активного администратора.",
        "user_action": "Сначала назначьте другого активного администратора.",
    },
    "ADMIN_QUERY_INVALID": {
        "http_status": 422,
        "retryable": True,
        "display_text": "Параметры просмотра заполнены некорректно.",
        "user_action": "Исправьте фильтры или параметры страницы и повторите запрос.",
    },
    "ADMIN_SERVICE_UNAVAILABLE": {
        "http_status": 503,
        "retryable": True,
        "display_text": "Управление пользователями временно недоступно.",
        "user_action": "Повторите действие позже.",
    },
    "ADMIN_STATE_INCONSISTENT": {
        "http_status": 409,
        "retryable": True,
        "display_text": "Не удалось применить изменение из-за текущего состояния учетных записей.",
        "user_action": "Обновите страницу, проверьте данные и повторите действие.",
    },
    "ADMIN_USER_NOT_FOUND": {
        "http_status": 404,
        "retryable": False,
        "display_text": "Пользователь не найден.",
        "user_action": "Обновите список пользователей.",
    },
    "ARTIFACT_INTEGRITY_FAILED": {
        "http_status": 409,
        "retryable": False,
        "display_text": "Целостность файла результата не подтверждена.",
        "user_action": "Обратитесь к владельцу расчета и не используйте поврежденный файл.",
    },
    "ARTIFACT_NOT_FOUND": {
        "http_status": 404,
        "retryable": False,
        "display_text": "Файл результата не найден или удален по retention policy.",
        "user_action": "Повторите расчет, если файл результата еще нужен.",
    },
    "AUTH_ACCOUNT_DISABLED": {
        "http_status": 401,
        "retryable": False,
        "display_text": "Учетная запись отключена.",
        "user_action": "Обратитесь к администратору.",
    },
    "AUTH_INVALID_CREDENTIALS": {
        "http_status": 401,
        "retryable": True,
        "display_text": "Не удалось войти. Проверьте данные и повторите попытку.",
        "user_action": "Проверьте адрес и пароль.",
    },
    "AUTH_RATE_LIMITED": {
        "http_status": 429,
        "retryable": True,
        "display_text": "Слишком много попыток входа.",
        "user_action": "Повторите попытку немного позже.",
    },
    "AUTH_REQUIRED": {
        "http_status": 401,
        "retryable": True,
        "display_text": "Войдите в систему, чтобы продолжить.",
        "user_action": "Откройте страницу входа.",
    },
    "AUTH_SESSION_EXPIRED": {
        "http_status": 401,
        "retryable": True,
        "display_text": "Сессия завершена.",
        "user_action": "Войдите в систему повторно.",
    },
    "CANCELLATION_NOT_ACCEPTED": {
        "http_status": 409,
        "retryable": False,
        "display_text": "Расчет уже завершен или отмена больше не может быть принята.",
        "user_action": "Обновите статус расчета; завершенный результат остается неизменным.",
    },
    "IDEMPOTENCY_CONFLICT": {
        "http_status": 409,
        "retryable": False,
        "display_text": "Этот ключ запроса уже использован для других данных.",
        "user_action": "Повторите действие с новым Idempotency-Key.",
    },
    "IDEMPOTENCY_KEY_REQUIRED": {
        "http_status": 400,
        "retryable": True,
        "display_text": "Запросу нужен уникальный Idempotency-Key.",
        "user_action": "Frontend должен повторить запрос с корректным ключом.",
    },
    "INVALID_BODY_SIZE": {
        "http_status": 413,
        "retryable": True,
        "display_text": "Размер JSON-запроса недопустим.",
        "user_action": "Уменьшите запрос или исправьте Content-Length.",
    },
    "INVALID_JOB": {
        "http_status": 422,
        "retryable": True,
        "display_text": "Job contract не прошел проверку.",
        "user_action": "Исправьте поля job contract перед повторной отправкой.",
    },
    "INVALID_QUERY": {
        "http_status": 400,
        "retryable": True,
        "display_text": "Параметры запроса не поддерживаются.",
        "user_action": "Исправьте filter, limit или offset.",
    },
    "INVALID_UPLOAD": {
        "http_status": 422,
        "retryable": True,
        "display_text": "Campaign brief не удалось принять.",
        "user_action": "Проверьте формат файла, имя и обязательные колонки.",
    },
    "INVALID_UPLOAD_SIZE": {
        "http_status": 413,
        "retryable": True,
        "display_text": "Файл пустой или превышает допустимый размер.",
        "user_action": "Загрузите непустой файл в пределах установленного лимита.",
    },
    "JOB_CREATION_BLOCKED": {
        "http_status": 409,
        "retryable": True,
        "display_text": "Validation пока не разрешает создать расчет.",
        "user_action": "Исправьте blocking errors и повторите validation.",
    },
    "JOB_NOT_FOUND": {
        "http_status": 404,
        "retryable": False,
        "display_text": "Расчет не найден.",
        "user_action": "Вернитесь в историю расчетов и выберите существующую задачу.",
    },
    "JSON_REQUIRED": {
        "http_status": 415,
        "retryable": True,
        "display_text": "Endpoint ожидает JSON.",
        "user_action": "Укажите Content-Type application/json.",
    },
    "MODEL_PASSPORT_UNAVAILABLE": {
        "http_status": 503,
        "retryable": True,
        "display_text": "Паспорт активной модели временно недоступен.",
        "user_action": (
            "Повторите запрос позже. Если ошибка сохраняется, сообщите "
            "ответственному за сервис."
        ),
    },
    "PRODUCT_NAVIGATION_INCONSISTENT": {
        "http_status": 409,
        "retryable": False,
        "display_text": "Опубликованные сведения не согласованы между собой.",
        "user_action": (
            "Не используйте спорные данные и сообщите ответственному за инструмент."
        ),
    },
    "PRODUCT_NAVIGATION_QUERY_INVALID": {
        "http_status": 422,
        "retryable": True,
        "display_text": "Параметры просмотра заполнены некорректно.",
        "user_action": "Исправьте фильтры или параметры страницы и повторите запрос.",
    },
    "PRODUCT_NAVIGATION_UNAVAILABLE": {
        "http_status": 503,
        "retryable": True,
        "display_text": "Сведения для этой страницы временно недоступны.",
        "user_action": "Обновите страницу позже.",
    },
    "PERMISSION_DENIED": {
        "http_status": 403,
        "retryable": False,
        "display_text": "Недостаточно прав для выполнения этого действия.",
        "user_action": "Обратитесь к администратору, если доступ необходим для работы.",
    },
    "PROGRESS_STATE_INCONSISTENT": {
        "http_status": 409,
        "retryable": True,
        "display_text": "Не удалось согласовать состояние расчета.",
        "user_action": "Обновите страницу. Если проблема сохраняется, сообщите номер расчета ответственному за сервис.",
    },
    "PROGRESS_VIEW_UNAVAILABLE": {
        "http_status": 503,
        "retryable": True,
        "display_text": "Сведения о ходе расчета временно недоступны.",
        "user_action": "Повторите запрос позже.",
    },
    "RESULT_VIEW_INCONSISTENT": {
        "http_status": 409,
        "retryable": False,
        "display_text": "Опубликованные данные результата не согласованы между собой.",
        "user_action": "Не используйте результат и сообщите номер расчета ответственному за сервис.",
    },
    "RESULT_VIEW_UNAVAILABLE": {
        "http_status": 503,
        "retryable": True,
        "display_text": "Представление результата временно недоступно.",
        "user_action": "Повторите запрос позже. Если ошибка сохраняется, сообщите номер расчета ответственному за сервис.",
    },
    "MEDIA_PLAN_QUERY_UNSUPPORTED": {
        "http_status": 422,
        "retryable": True,
        "display_text": "Запрошенный сценарий или фильтр медиаплана недоступен.",
        "user_action": "Выберите доступный сценарий или уберите неподдерживаемый фильтр.",
    },
    "MEDIA_PLAN_VIEW_UNAVAILABLE": {
        "http_status": 503,
        "retryable": True,
        "display_text": "Медиаплан временно недоступен.",
        "user_action": "Повторите запрос позже. Если ошибка сохраняется, сообщите номер расчета ответственному за сервис.",
    },
    "RESOURCE_NOT_READY": {
        "http_status": 404,
        "retryable": True,
        "display_text": "Результат еще не готов.",
        "user_action": "Продолжайте polling статуса job.",
    },
    "ROUTE_NOT_FOUND": {
        "http_status": 404,
        "retryable": False,
        "display_text": "Маршрут не найден.",
        "user_action": "Проверьте адрес и версию запроса.",
    },
    "SCHEMA_NOT_FOUND": {
        "http_status": 404,
        "retryable": False,
        "display_text": "Запрошенная JSON Schema не опубликована.",
        "user_action": "Используйте contract name из OpenAPI v1.",
    },
    "UPLOAD_NOT_FOUND": {
        "http_status": 404,
        "retryable": False,
        "display_text": "Загрузка не найдена.",
        "user_action": "Загрузите campaign brief повторно.",
    },
    "UPLOAD_NOT_READY": {
        "http_status": 409,
        "retryable": True,
        "display_text": "Файл еще не разобран.",
        "user_action": "Дождитесь terminal upload status перед validation.",
    },
    "UPLOAD_SERVICE_DISABLED": {
        "http_status": 503,
        "retryable": True,
        "display_text": "Campaign upload service не настроен.",
        "user_action": (
            "Обратитесь к ответственному за сервис: прием файлов временно "
            "недоступен."
        ),
    },
    "VALIDATION_NOT_FOUND": {
        "http_status": 404,
        "retryable": False,
        "display_text": "Validation не найдена.",
        "user_action": "Запустите новую validation из существующей загрузки.",
    },
}


def _required_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ProductApiContractError(f"{key} must be an object")
    return value


def _required_list(payload: Mapping[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ProductApiContractError(f"{key} must be an array")
    return value


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProductApiContractError(f"{key} is required")
    return value


def _date(value: Any, field_name: str, *, nullable: bool = False) -> date | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise ProductApiContractError(f"{field_name} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ProductApiContractError(f"{field_name} must be an ISO date") from exc


def _reject_paths(value: Any, field_name: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            _reject_paths(nested, f"{field_name}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_paths(nested, f"{field_name}[{index}]")
    elif isinstance(value, str) and _ABSOLUTE_PATH_RE.match(value):
        raise ProductApiContractError(f"{field_name} must not expose an absolute path")


def validate_model_passport(payload: Mapping[str, Any]) -> None:
    if payload.get("contract_name") != MODEL_PASSPORT_CONTRACT:
        raise ProductApiContractError("Unknown model passport contract")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ProductApiContractError("Unsupported model passport schema version")
    if payload.get("record_origin") not in {"verified_model_package", "synthetic_fixture"}:
        raise ProductApiContractError("Unknown model passport record_origin")

    serving = _required_mapping(payload, "serving")
    if serving.get("deployment_profile") not in DEPLOYMENT_PROFILES:
        raise ProductApiContractError("Unknown deployment profile")
    if serving.get("decision_scope") != "forecast_and_allocation_only":
        raise ProductApiContractError("Model passport must remain allocation-only")
    if serving.get("production_claim_allowed") is not False:
        raise ProductApiContractError("Research passport cannot claim production activation")

    package = _required_mapping(payload, "package")
    package_id = _required_text(package, "package_id")
    if not _PACKAGE_ID_RE.fullmatch(package_id):
        raise ProductApiContractError("package.package_id is invalid")
    fingerprint = _required_text(package, "package_fingerprint")
    if not _SHA256_RE.fullmatch(fingerprint):
        raise ProductApiContractError("package.package_fingerprint must be SHA-256")

    data = _required_mapping(payload, "data")
    training = _required_mapping(data, "training_period")
    training_start = _date(training.get("start_date"), "data.training_period.start_date")
    training_end = _date(training.get("end_date"), "data.training_period.end_date")
    if training_start is not None and training_end is not None and training_end < training_start:
        raise ProductApiContractError("data.training_period is reversed")
    shadow = _required_mapping(data, "development_shadow_period")
    shadow_start = _date(
        shadow.get("start_date"),
        "data.development_shadow_period.start_date",
        nullable=True,
    )
    shadow_end = _date(
        shadow.get("end_date"),
        "data.development_shadow_period.end_date",
        nullable=True,
    )
    if (shadow_start is None) != (shadow_end is None):
        raise ProductApiContractError("development shadow period must be complete or absent")
    if shadow_start is not None and shadow_end is not None and shadow_end < shadow_start:
        raise ProductApiContractError("data.development_shadow_period is reversed")

    coverage = _required_mapping(payload, "coverage")
    segments = _required_list(coverage, "segments")
    channels = _required_list(coverage, "channels")
    targets = _required_list(coverage, "targets")
    policies = _required_list(coverage, "channel_policies")
    if any(not isinstance(value, str) or not value for value in (*segments, *channels)):
        raise ProductApiContractError("coverage segments/channels must be non-empty strings")
    counts = _required_mapping(coverage, "allowed_use_counts")
    if set(counts) != ALLOWED_USE_CODES:
        raise ProductApiContractError("coverage.allowed_use_counts must contain every policy code")
    if any(not isinstance(value, int) or value < 0 for value in counts.values()):
        raise ProductApiContractError("coverage.allowed_use_counts must be non-negative integers")
    capability_cells = coverage.get("capability_cells_n")
    if not isinstance(capability_cells, int) or capability_cells < 0:
        raise ProductApiContractError("coverage.capability_cells_n must be non-negative")
    if sum(counts.values()) != capability_cells or len(policies) != capability_cells:
        raise ProductApiContractError("coverage capability counts do not reconcile")
    target_names: set[str] = set()
    for index, entry in enumerate(targets):
        if not isinstance(entry, Mapping):
            raise ProductApiContractError(f"coverage.targets[{index}] must be an object")
        target_name = _required_text(entry, "target")
        if target_name in target_names:
            raise ProductApiContractError(f"Duplicate target summary: {target_name}")
        target_names.add(target_name)
        target_counts = _required_mapping(entry, "allowed_use_counts")
        if set(target_counts) - ALLOWED_USE_CODES or any(
            not isinstance(value, int) or value < 0 for value in target_counts.values()
        ):
            raise ProductApiContractError(f"coverage.targets[{index}] counts are invalid")
        _required_list(entry, "objective_roles")
    policy_keys: set[tuple[str, str, str]] = set()
    policy_counts: dict[str, int] = {code: 0 for code in ALLOWED_USE_CODES}
    for index, entry in enumerate(policies):
        if not isinstance(entry, Mapping):
            raise ProductApiContractError(f"coverage.channel_policies[{index}] must be an object")
        segment = _required_text(entry, "segment")
        channel = _required_text(entry, "channel")
        target = _required_text(entry, "target")
        allowed_use = _required_text(entry, "allowed_use")
        if segment not in segments or channel not in channels or target not in target_names:
            raise ProductApiContractError("Channel policy references unknown coverage")
        if allowed_use not in ALLOWED_USE_CODES:
            raise ProductApiContractError("Channel policy has unknown allowed_use")
        key = (segment, channel, target)
        if key in policy_keys:
            raise ProductApiContractError(f"Duplicate channel policy: {key}")
        policy_keys.add(key)
        policy_counts[allowed_use] += 1
        _required_text(entry, "forecast_action")
        _required_text(entry, "optimizer_action")
        _required_text(entry, "display_text")
    if policy_counts != dict(counts):
        raise ProductApiContractError("Channel policy rows do not match allowed-use counts")

    validation = _required_mapping(payload, "validation")
    replay = _required_mapping(validation, "historical_replay")
    oot = _required_mapping(validation, "sealed_oot")
    if replay.get("status") not in REPLAY_STATUS_CODES:
        raise ProductApiContractError("Unknown historical replay status")
    if oot.get("status") not in OOT_STATUS_CODES:
        raise ProductApiContractError("Unknown OOT status")
    _required_list(payload, "caveats")
    _reject_paths(payload)


def build_error_catalog_payload() -> dict[str, Any]:
    payload = {
        "contract_name": HTTP_ERROR_CATALOG_CONTRACT,
        "schema_version": SCHEMA_VERSION,
        "errors": [
            {"code": code, **details}
            for code, details in sorted(HTTP_ERROR_CATALOG.items())
        ],
    }
    validate_error_catalog(payload)
    return payload


def build_calculation_profile_payload(
    *,
    scenario6_attempt_budget: int,
    profile_label: str,
    model_version_label: str,
) -> dict[str, Any]:
    payload = {
        "contract_name": CALCULATION_PROFILE_CONTRACT,
        "schema_version": SCHEMA_VERSION,
        "scenario6_attempt_budget": scenario6_attempt_budget,
        "profile_label": profile_label,
        "model_version_label": model_version_label,
    }
    validate_calculation_profile(payload)
    return payload


def validate_calculation_profile(payload: Mapping[str, Any]) -> None:
    if payload.get("contract_name") != CALCULATION_PROFILE_CONTRACT:
        raise ProductApiContractError("Unknown calculation profile contract")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ProductApiContractError("Unsupported calculation profile schema version")
    attempt_budget = payload.get("scenario6_attempt_budget")
    if isinstance(attempt_budget, bool) or not isinstance(attempt_budget, int) or attempt_budget <= 0:
        raise ProductApiContractError("scenario6_attempt_budget must be a positive integer")
    _required_text(payload, "profile_label")
    _required_text(payload, "model_version_label")
    _reject_paths(payload)


def validate_error_catalog(payload: Mapping[str, Any]) -> None:
    if payload.get("contract_name") != HTTP_ERROR_CATALOG_CONTRACT:
        raise ProductApiContractError("Unknown HTTP error catalog contract")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ProductApiContractError("Unsupported HTTP error catalog schema version")
    errors = _required_list(payload, "errors")
    codes: set[str] = set()
    for index, entry in enumerate(errors):
        if not isinstance(entry, Mapping):
            raise ProductApiContractError(f"errors[{index}] must be an object")
        code = _required_text(entry, "code")
        if code in codes:
            raise ProductApiContractError(f"Duplicate HTTP error code: {code}")
        codes.add(code)
        status = entry.get("http_status")
        if not isinstance(status, int) or not 400 <= status <= 599:
            raise ProductApiContractError(f"errors[{index}].http_status is invalid")
        if not isinstance(entry.get("retryable"), bool):
            raise ProductApiContractError(f"errors[{index}].retryable must be boolean")
        _required_text(entry, "display_text")
        _required_text(entry, "user_action")
    _reject_paths(payload)


def build_job_list_payload(
    items: list[dict[str, Any]],
    *,
    total: int,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    next_offset = offset + len(items) if offset + len(items) < total else None
    payload = {
        "contract_name": JOB_LIST_CONTRACT,
        "schema_version": SCHEMA_VERSION,
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "next_offset": next_offset,
    }
    validate_job_list(payload)
    return payload


def validate_job_list(payload: Mapping[str, Any]) -> None:
    if payload.get("contract_name") != JOB_LIST_CONTRACT:
        raise ProductApiContractError("Unknown job list contract")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ProductApiContractError("Unsupported job list schema version")
    items = _required_list(payload, "items")
    total = payload.get("total")
    limit = payload.get("limit")
    offset = payload.get("offset")
    next_offset = payload.get("next_offset")
    if not isinstance(total, int) or total < len(items):
        raise ProductApiContractError("job_list.total is inconsistent")
    if not isinstance(limit, int) or not 1 <= limit <= 200:
        raise ProductApiContractError("job_list.limit must be between 1 and 200")
    if not isinstance(offset, int) or offset < 0:
        raise ProductApiContractError("job_list.offset must be non-negative")
    if next_offset is not None and (not isinstance(next_offset, int) or next_offset <= offset):
        raise ProductApiContractError("job_list.next_offset is invalid")
    if next_offset is not None and next_offset != offset + len(items):
        raise ProductApiContractError("job_list.next_offset must follow the returned page")
    if next_offset is None and offset + len(items) < total:
        raise ProductApiContractError("job_list.next_offset is required when more items exist")
    for entry in items:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("job"), Mapping):
            raise ProductApiContractError("job_list items must contain job objects")
        status = _required_mapping(entry["job"], "status").get("code")
        if status not in JOB_STATUS_CODES:
            raise ProductApiContractError(f"Unknown job status: {status}")
    _reject_paths(payload)


def load_product_api_schema() -> dict[str, Any]:
    return json.loads(
        (Path(__file__).with_name("product_api_v1.schema.json")).read_text(encoding="utf-8")
    )


def load_openapi_document() -> dict[str, Any]:
    return json.loads(
        (Path(__file__).with_name("openapi_v1.json")).read_text(encoding="utf-8")
    )
