"""Isolated model-registry fixtures for HTTP and product-navigation tests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_synthetic_model_registry(
    registry_root: Path,
    model_passport: Mapping[str, Any],
    *,
    pointer_package_id: str | None = None,
) -> Path:
    """Write a minimal registry whose active pointer matches the test passport.

    ``pointer_package_id`` is intentionally overridable so tests can prove that
    the production fail-closed identity check still returns HTTP 409.
    """

    package = model_passport["package"]
    package_id = str(package["package_id"])
    registration = {
        "registry_schema_version": "1.0.0",
        "package_id": package_id,
        "model_run_id": str(package["model_run_id"]),
        "run_dir": "synthetic_outputs/synthetic_model_run",
        "package_input_fingerprint": str(package["package_fingerprint"]),
        "package_schema_version": str(package["package_schema_version"]),
        "gate_policy_version": str(package["gate_policy_version"]),
        "package_stage": str(package["package_stage"]),
        "activation_status_at_registration": str(package["activation_status"]),
        "production_blockers_at_registration": ["MISSING_OR_FAILED_OOT_VALIDATION"],
        "panel": {
            "path": "synthetic_data/panel.parquet",
            "sha256": "9" * 64,
            "size_bytes": 4096,
        },
        "inventory_sha256": {},
        "registered_at_utc": "2026-07-15T10:00:00+00:00",
        "registered_by": "Synthetic test fixture",
        "reason": "Isolated product-navigation identity",
    }
    immutable = dict(registration)
    for key in ("registered_at_utc", "registered_by", "reason"):
        immutable.pop(key)
    registration["registration_content_sha256"] = _canonical_hash(immutable)
    _write_json(
        registry_root / "registrations" / f"{package_id}.json",
        registration,
    )
    _write_json(
        registry_root / "channels" / "preprod.json",
        {
            "package_id": pointer_package_id or package_id,
            "updated_at_utc": "2026-07-15T11:00:00+00:00",
        },
    )
    return registry_root
