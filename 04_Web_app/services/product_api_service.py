"""Product API projections and safe local-retention operations.

This service reads verified package/application artifacts and produces compact
browser contracts. It never recalculates MMM effects or optimizer decisions.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


WEB_APP_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = WEB_APP_DIR.parent
PYMC_CODE_DIR = PROJECT_ROOT / "02_Code" / "01_PyMC"

for entry in (WEB_APP_DIR, PYMC_CODE_DIR):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from contracts.product_api_v1 import (  # noqa: E402
    MODEL_PASSPORT_CONTRACT,
    SCHEMA_VERSION,
    build_job_list_payload,
    validate_model_passport,
)
from mmm_core.model_package_reader import ModelPackage  # noqa: E402


TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled", "timed_out"}
TERMINAL_UPLOAD_STATUSES = {"parsed", "rejected"}
TERMINAL_VALIDATION_STATUSES = {"valid", "invalid"}
ALLOWED_USE_CODES = ("primary", "caution", "diagnostic", "unavailable")
_RESOURCE_ID_RE = re.compile(
    r"^(?:job|validation|upload)_[0-9a-f]{12,64}$"
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path.name}")
    return value


def _recorded_package_dir(resolved: Mapping[str, Any], project_root: Path) -> Path:
    registration = resolved.get("registration")
    if not isinstance(registration, Mapping):
        raise ValueError("Resolved registry record has no registration")
    raw = registration.get("run_dir")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("Registry registration has no run_dir")
    path = Path(raw).expanduser()
    return (path if path.is_absolute() else project_root / path).resolve()


def _evidence_status(package_dir: Path, manifest: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    replay_path = package_dir / "historical_replay_validation.json"
    replay = _read_json(replay_path) if replay_path.is_file() else {}
    replay_status = str(replay.get("status") or "unavailable")
    if replay_status not in {"passed", "failed"}:
        replay_status = "unavailable"
    replay_payload = {
        "status": replay_status,
        "generated_at_utc": replay.get("generated_at_utc"),
        "reason_code": (
            None
            if replay_status == "passed"
            else (
                "HISTORICAL_REPLAY_FAILED"
                if replay_status == "failed"
                else "HISTORICAL_REPLAY_UNAVAILABLE"
            )
        ),
        "display_text": (
            "Независимый historical replay пройден."
            if replay_status == "passed"
            else "Независимый historical replay недоступен или не пройден."
        ),
    }

    artifacts = manifest.get("artifact_status") or {}
    blockers = [str(value) for value in manifest.get("production_blockers") or []]
    oot_path = package_dir / "oot_validation.json"
    oot_evidence = _read_json(oot_path) if oot_path.is_file() else {}
    oot_passed = bool(artifacts.get("oot_validation_passed"))
    recorded_oot_status = str(oot_evidence.get("status") or "")
    oot_status = (
        "passed"
        if oot_passed
        else "failed"
        if recorded_oot_status in {"failed", "rejected"}
        else "unavailable"
    )
    oot_reason = (
        None
        if oot_status == "passed"
        else "SEALED_OOT_FAILED"
        if oot_status == "failed"
        else (
            "MISSING_OR_FAILED_OOT_VALIDATION"
            if "MISSING_OR_FAILED_OOT_VALIDATION" in blockers
            else "SEALED_OOT_UNAVAILABLE"
        )
    )
    oot_payload = {
        "status": oot_status,
        "generated_at_utc": oot_evidence.get("generated_at_utc"),
        "reason_code": oot_reason,
        "display_text": (
            "Независимая OOT-валидация пройдена."
            if oot_status == "passed"
            else "Sealed OOT выполнен, но не прошел обязательные проверки."
            if oot_status == "failed"
            else "Новые полные данные для sealed OOT пока недоступны; это не блокирует research-pilot расчеты."
        ),
    }
    return replay_payload, oot_payload


def _target_summaries(rows: Iterable[Mapping[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("target") or "")].append(row)
    output = []
    for target, target_rows in sorted(grouped.items()):
        counts = Counter(str(row.get("allowed_use") or "unavailable") for row in target_rows)
        for code in ALLOWED_USE_CODES:
            counts.setdefault(code, 0)
        output.append(
            {
                "target": target,
                "allowed_use_counts": dict(sorted(counts.items())),
                "objective_roles": sorted(
                    {str(row.get("objective_role") or "forbidden") for row in target_rows}
                ),
            }
        )
    return output


def _channel_policies(rows: Iterable[Mapping[str, str]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in sorted(
        rows,
        key=lambda value: (
            str(value.get("segment") or ""),
            str(value.get("channel") or ""),
            str(value.get("target") or ""),
        ),
    ):
        allowed_use = str(row.get("allowed_use") or "unavailable")
        message = str(
            row.get("marketer_message") or row.get("allowed_use_reason") or ""
        ).strip()
        default_text = {
            "primary": "Канал можно использовать для прогноза и разрешенной оптимизации.",
            "caution": "Канал можно прогнозировать, но автоматическое увеличение бюджета ограничено.",
            "diagnostic": "Канал показывается только как диагностика и не может получать дополнительный бюджет.",
            "unavailable": "Канал недоступен для автоматического прогноза или оптимизации.",
        }[allowed_use]
        output.append(
            {
                "segment": str(row.get("segment") or ""),
                "channel": str(row.get("channel") or ""),
                "target": str(row.get("target") or ""),
                "allowed_use": allowed_use,
                "forecast_action": str(row.get("forecast_use") or "blocked"),
                "optimizer_action": str(row.get("optimizer_use") or "blocked"),
                "display_text": message or default_text,
            }
        )
    return output


def build_model_passport(
    resolved: Mapping[str, Any],
    *,
    project_root: Path,
    deployment_profile: str,
) -> dict[str, Any]:
    """Build one path-safe passport from a registry-verified package."""

    package_dir = _recorded_package_dir(resolved, project_root.expanduser().resolve())
    package = ModelPackage.from_run_dir(
        package_dir,
        require_posterior_ready=True,
        validate_hash=False,
    )
    manifest = package.manifest
    registration = resolved["registration"]
    fingerprint = str(registration.get("package_input_fingerprint") or "")
    if fingerprint != str(manifest.get("package_input_fingerprint") or ""):
        raise ValueError("Registry and model manifest fingerprints differ")

    allowed_use_counts = Counter(
        str(row.get("allowed_use") or "unavailable") for row in package.capability_rows
    )
    for code in ALLOWED_USE_CODES:
        allowed_use_counts.setdefault(code, 0)
    geographies = {
        str(row.get("geo_label") or "")
        for row in package.support_rows
        if str(row.get("scope") or "") == "geo" and str(row.get("geo_label") or "")
    }
    channels = sorted(
        {str(row.get("channel") or "") for row in package.capability_rows if row.get("channel")}
    )
    replay, oot = _evidence_status(package_dir, manifest)
    blocker_text = {
        "MISSING_OR_FAILED_OOT_VALIDATION": (
            "Sealed OOT пока недоступен из-за отсутствия нового полного периода данных."
        )
    }
    blockers = [
        {
            "code": str(code),
            "display_text": blocker_text.get(
                str(code),
                "Ограничение качества активной модели требует проверки.",
            ),
        }
        for code in manifest.get("production_blockers") or []
    ]
    payload = {
        "contract_name": MODEL_PASSPORT_CONTRACT,
        "schema_version": SCHEMA_VERSION,
        "record_origin": "verified_model_package",
        "serving": {
            "deployment_profile": deployment_profile,
            "display_name": "Исследовательская MMM-модель",
            "calculation_allowed": package.package_stage == "posterior_ready",
            "decision_scope": "forecast_and_allocation_only",
            "production_claim_allowed": False,
        },
        "package": {
            "registry_channel": str(resolved.get("channel") or ""),
            "registry_event_id": str(resolved.get("event_id") or ""),
            "package_id": str(resolved.get("package_id") or ""),
            "package_fingerprint": fingerprint,
            "model_run_id": package.model_run_id,
            "package_stage": package.package_stage,
            "activation_status": package.activation_status,
            "package_schema_version": str(manifest.get("package_schema_version") or ""),
            "gate_policy_version": str(manifest.get("gate_policy_version") or ""),
        },
        "data": {
            "grain": "daily",
            "training_period": {
                "start_date": str(manifest.get("train_start") or ""),
                "end_date": str(manifest.get("train_end") or ""),
            },
            "development_shadow_period": {
                "start_date": manifest.get("holdout_start"),
                "end_date": manifest.get("holdout_end"),
                "purpose": "development_shadow_not_sealed_oot",
            },
        },
        "coverage": {
            "segments": sorted(package.segments),
            "channels": channels,
            "targets": _target_summaries(package.capability_rows),
            "geographies_n": len(geographies),
            "capability_cells_n": len(package.capability_rows),
            "allowed_use_counts": {
                code: int(allowed_use_counts[code])
                for code in ALLOWED_USE_CODES
            },
            "channel_policies": _channel_policies(package.capability_rows),
        },
        "validation": {
            "historical_replay": replay,
            "sealed_oot": oot,
            "production_blockers": blockers,
        },
        "caveats": [
            {
                "code": "research_model",
                "display_text": "Результаты предназначены для исследовательского прогнозирования и планирования бюджета.",
            },
            {
                "code": "allocation_only",
                "display_text": "Система рекомендует распределение бюджета, но не принимает решение запускать или отменять кампанию.",
            },
            {
                "code": (
                    "sealed_oot_failed"
                    if oot["status"] == "failed"
                    else "sealed_oot_pending"
                    if oot["status"] == "unavailable"
                    else "sealed_oot_passed"
                ),
                "display_text": oot["display_text"],
            },
        ],
    }
    validate_model_passport(payload)
    return payload


def paginate_jobs(
    records: list[dict[str, Any]],
    *,
    limit: int,
    offset: int,
    status: str | None,
) -> dict[str, Any]:
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    if offset < 0:
        raise ValueError("offset must be non-negative")
    filtered = records
    if status is not None:
        if status not in {
            "queued",
            "running",
            "cancel_requested",
            "succeeded",
            "failed",
            "cancelled",
            "timed_out",
        }:
            raise ValueError("status filter is invalid")
        filtered = [
            record
            for record in records
            if str((record.get("job") or {}).get("status", {}).get("code") or "") == status
        ]
    return build_job_list_payload(
        filtered[offset : offset + limit],
        total=len(filtered),
        limit=limit,
        offset=offset,
    )


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _tree_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if not path.is_dir():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _remove_tree(path: Path) -> None:
    if path.is_symlink():
        raise ValueError(f"Retention refuses symlinked resource directory: {path.name}")
    if path.exists():
        shutil.rmtree(path)


def _safe_resource_id(value: Any, expected_prefix: str) -> str:
    resource_id = str(value or "")
    if (
        not _RESOURCE_ID_RE.fullmatch(resource_id)
        or not resource_id.startswith(f"{expected_prefix}_")
    ):
        raise ValueError(f"Invalid {expected_prefix} resource ID in retention state")
    return resource_id


@dataclass(frozen=True)
class RetentionPlan:
    generated_at_utc: str
    retention_days: int
    cutoff_utc: str
    job_ids: tuple[str, ...]
    validation_ids: tuple[str, ...]
    upload_ids: tuple[str, ...]
    estimated_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RuntimeRetentionManager:
    """Delete only terminal, fully expired local resource families."""

    def __init__(self, state_root: Path, runtime_root: Path, artifact_root: Path) -> None:
        self.state_root = state_root.expanduser().resolve()
        self.runtime_root = runtime_root.expanduser().resolve()
        self.artifact_root = artifact_root.expanduser().resolve()

    @staticmethod
    def _records(root: Path, resource: str, filename: str) -> list[dict[str, Any]]:
        directory = root / resource
        if not directory.is_dir():
            return []
        return [
            _read_json(path)
            for path in sorted(directory.glob(f"*/{filename}"))
            if path.is_file()
        ]

    def plan(self, retention_days: int, *, now: datetime | None = None) -> RetentionPlan:
        if retention_days <= 0:
            raise ValueError("retention_days must be positive")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        cutoff = current - timedelta(days=retention_days)
        jobs = self._records(self.state_root, "jobs", "job.json")
        validations = self._records(self.state_root, "validations", "validation.json")
        uploads = self._records(self.state_root, "uploads", "upload.json")

        expired_jobs: set[str] = set()
        for job in jobs:
            status = str((job.get("status") or {}).get("code") or "")
            finished = _parse_timestamp(job.get("finished_at_utc"))
            if status in TERMINAL_JOB_STATUSES and finished is not None and finished < cutoff:
                expired_jobs.add(_safe_resource_id(job.get("job_id"), "job"))

        jobs_by_validation: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for job in jobs:
            jobs_by_validation[str(job.get("validation_id") or "")].append(job)
        expired_validations: set[str] = set()
        for validation in validations:
            validation_id = _safe_resource_id(validation.get("validation_id"), "validation")
            status = str((validation.get("status") or {}).get("code") or "")
            finished = _parse_timestamp(validation.get("finished_at_utc"))
            related = jobs_by_validation.get(validation_id, [])
            related_expired = all(
                _safe_resource_id(job.get("job_id"), "job") in expired_jobs
                for job in related
            )
            if (
                status in TERMINAL_VALIDATION_STATUSES
                and finished is not None
                and finished < cutoff
                and related_expired
            ):
                expired_validations.add(validation_id)

        validations_by_upload: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for validation in validations:
            validations_by_upload[str(validation.get("upload_id") or "")].append(validation)
        expired_uploads: set[str] = set()
        for upload in uploads:
            upload_id = _safe_resource_id(upload.get("upload_id"), "upload")
            status = str((upload.get("status") or {}).get("code") or "")
            terminal_at = _parse_timestamp(upload.get("parsed_at_utc") or upload.get("rejected_at_utc"))
            related = validations_by_upload.get(upload_id, [])
            related_expired = all(
                _safe_resource_id(validation.get("validation_id"), "validation")
                in expired_validations
                for validation in related
            )
            if (
                status in TERMINAL_UPLOAD_STATUSES
                and terminal_at is not None
                and terminal_at < cutoff
                and related_expired
            ):
                expired_uploads.add(upload_id)

        candidates = []
        for job_id in expired_jobs:
            candidates.extend((self.state_root / "jobs" / job_id, self.runtime_root / job_id))
        for validation_id in expired_validations:
            candidates.extend(
                (
                    self.state_root / "validations" / validation_id,
                    self.runtime_root / "validations" / validation_id,
                    self.artifact_root / "validations" / validation_id,
                )
            )
        for upload_id in expired_uploads:
            candidates.extend(
                (
                    self.state_root / "uploads" / upload_id,
                    self.artifact_root / "uploads" / upload_id,
                )
            )
        return RetentionPlan(
            generated_at_utc=current.isoformat(),
            retention_days=retention_days,
            cutoff_utc=cutoff.isoformat(),
            job_ids=tuple(sorted(expired_jobs)),
            validation_ids=tuple(sorted(expired_validations)),
            upload_ids=tuple(sorted(expired_uploads)),
            estimated_bytes=sum(_tree_size(path) for path in candidates),
        )

    def apply(self, plan: RetentionPlan) -> dict[str, Any]:
        for job_id in plan.job_ids:
            _safe_resource_id(job_id, "job")
            _remove_tree(self.state_root / "jobs" / job_id)
            _remove_tree(self.runtime_root / job_id)
            internal_error = self.runtime_root / "api_internal_errors" / f"{job_id}.log"
            internal_error.unlink(missing_ok=True)
        for validation_id in plan.validation_ids:
            _safe_resource_id(validation_id, "validation")
            _remove_tree(self.state_root / "validations" / validation_id)
            _remove_tree(self.runtime_root / "validations" / validation_id)
            _remove_tree(self.artifact_root / "validations" / validation_id)
        for upload_id in plan.upload_ids:
            _safe_resource_id(upload_id, "upload")
            _remove_tree(self.state_root / "uploads" / upload_id)
            _remove_tree(self.artifact_root / "uploads" / upload_id)
            parse_error = self.runtime_root / "validations" / "upload_parse_errors" / f"{upload_id}.log"
            parse_error.unlink(missing_ok=True)
        self._prune_indices(plan)
        event = {
            **plan.to_dict(),
            "applied_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "applied",
        }
        events = self.state_root / "retention" / "events.jsonl"
        events.parent.mkdir(parents=True, exist_ok=True)
        with events.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        return event

    def _prune_indices(self, plan: RetentionPlan) -> None:
        deleted_prefixes = {
            f"jobs/{value}/" for value in plan.job_ids
        } | {
            f"validations/{value}/" for value in plan.validation_ids
        } | {
            f"uploads/{value}/" for value in plan.upload_ids
        }
        deleted_resource_ids = {*plan.validation_ids, *plan.upload_ids}
        for name in ("idempotency.json", "validation_idempotency.json", "upload_idempotency.json"):
            path = self.state_root / name
            if not path.is_file():
                continue
            index = _read_json(path)
            kept = {
                key: value
                for key, value in index.items()
                if str((value or {}).get("job_id") or "") not in plan.job_ids
                and str((value or {}).get("resource_id") or "")
                not in deleted_resource_ids
                and not any(
                    str((value or {}).get("record_path") or "").startswith(prefix)
                    for prefix in deleted_prefixes
                )
            }
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(kept, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(path)
