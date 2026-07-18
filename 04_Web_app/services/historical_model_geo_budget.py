"""Serve package-bound historical model spend without reading the source panel."""

from __future__ import annotations

import hashlib
import json
import math
import sys
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


WEB_APP_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = WEB_APP_DIR.parent
PYMC_CODE_DIR = PROJECT_ROOT / "02_Code" / "01_PyMC"
if str(PYMC_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(PYMC_CODE_DIR))

from contracts.historical_model_geo_budget_v1 import (  # noqa: E402
    CONTRACT_NAME,
    SCHEMA_VERSION,
    TITLE,
    validate_historical_model_geo_budget_v1,
)
from mmm_core.historical_geo_budget import (  # noqa: E402
    ARTIFACT_VERSION,
    METADATA_FILENAME,
    PACKAGE_ARTIFACTS_MANIFEST_FILENAME,
    PARQUET_FILENAME,
    HistoricalGeoBudgetError,
    load_registry_package_identity,
    load_spend_columns_policy,
    sha256_file,
)
from services.geo_catalog import (  # noqa: E402
    GEO_CATALOG_VERSION,
    CanonicalGeoCatalog,
    coverage_summary,
    load_canonical_geo_catalog,
)


SPEND_POLICY_PATH = (
    PYMC_CODE_DIR / "configs" / "historical_geo_budget_spend_columns_v1.json"
)


class HistoricalModelGeoBudgetError(ValueError):
    """Raised when package-bound historical spend evidence is inconsistent."""


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise HistoricalModelGeoBudgetError(f"{path.name} must contain an object")
    return payload


def _safe_relative(value: Any, field: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise HistoricalModelGeoBudgetError(f"{field} is required")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
        raise HistoricalModelGeoBudgetError(f"{field} must be a safe relative path")
    return relative


def _safe_target(root: Path, relative: PurePosixPath) -> Path:
    target = root.joinpath(*relative.parts).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise HistoricalModelGeoBudgetError("Package artifact path escapes its root") from exc
    return target


def _format_date(value: str) -> str:
    parsed = date.fromisoformat(value)
    return parsed.strftime("%d.%m.%Y")


def _unavailable_payload(
    *,
    package_id: str,
    model_version: str | None,
    reason_code: str,
) -> dict[str, Any]:
    payload = {
        "contract_name": CONTRACT_NAME,
        "schema_version": SCHEMA_VERSION,
        "record_origin": "model_package_artifact_unavailable",
        "status": "unavailable",
        "title": TITLE,
        "display_text": "Исторические расходы активной модели временно недоступны.",
        "period_display_text": "Период данных временно недоступен.",
        "package_id": package_id,
        "model_version": model_version,
        "artifact_id": None,
        "artifact_version": None,
        "catalog_version": GEO_CATALOG_VERSION,
        "period_start": None,
        "period_end": None,
        "spend_columns_version": None,
        "total_budget_rub": None,
        "geographies_n": 0,
        "coverage": {
            "status": "unavailable",
            "located_geographies_n": 0,
            "unlocated_geographies_n": 0,
            "unlocated_geographies": [],
            "located_budget_rub": 0.0,
            "unlocated_budget_rub": 0.0,
            "unlocated_budget_share": None,
        },
        "rows": [],
        "limitations": [
            {
                "code": reason_code,
                "display_text": "Подтвержденный исторический агрегат для выбранной модели пока не опубликован.",
            }
        ],
        "updated_at_utc": None,
    }
    validate_historical_model_geo_budget_v1(payload)
    return payload


def _artifact_evidence(
    *,
    registry_root: Path,
    package_id: str,
) -> tuple[dict[str, Any], dict[str, Any], Any]:
    registration_path = registry_root / "registrations" / f"{package_id}.json"
    if not registration_path.is_file():
        raise FileNotFoundError("registration")
    try:
        identity = load_registry_package_identity(registry_root, package_id)
    except HistoricalGeoBudgetError as exc:
        raise HistoricalModelGeoBudgetError(str(exc)) from exc
    package_root = registry_root / "package_artifacts" / package_id
    package_manifest_path = package_root / PACKAGE_ARTIFACTS_MANIFEST_FILENAME
    if not package_manifest_path.is_file():
        raise FileNotFoundError("package_artifacts_manifest")
    package_manifest = _read_json(package_manifest_path)
    if package_manifest.get("manifest_schema_version") != "1.0.0":
        raise HistoricalModelGeoBudgetError("Package artifact manifest schema differs")
    expected_identity = {
        "package_id": identity.package_id,
        "package_input_fingerprint": identity.package_input_fingerprint,
        "registration_content_sha256": identity.registration_content_sha256,
        "source_panel_sha256": identity.panel_sha256,
    }
    if any(package_manifest.get(key) != value for key, value in expected_identity.items()):
        raise HistoricalModelGeoBudgetError("Package artifact manifest identity differs")
    candidates = [
        row
        for row in package_manifest.get("artifacts") or []
        if isinstance(row, Mapping) and row.get("artifact_kind") == ARTIFACT_VERSION
    ]
    if len(candidates) != 1:
        raise HistoricalModelGeoBudgetError(
            "Package artifact manifest must contain one historical geo-budget artifact"
        )
    entry = dict(candidates[0])
    metadata_relative = _safe_relative(
        entry.get("metadata_relative_path"),
        "metadata_relative_path",
    )
    metadata_path = _safe_target(package_root, metadata_relative)
    if not metadata_path.is_file():
        raise FileNotFoundError("historical_geo_budget_metadata")
    if sha256_file(metadata_path) != entry.get("metadata_sha256"):
        raise HistoricalModelGeoBudgetError("Historical geo-budget metadata hash differs")
    metadata = _read_json(metadata_path)
    manifest_metadata_fields = (
        "source_panel_sha256",
        "period_start",
        "period_end",
        "spend_columns",
        "spend_columns_version",
        "rows_n",
        "geographies_n",
        "total_budget_rub",
        "generated_at_utc",
    )
    if any(entry.get(key) != metadata.get(key) for key in manifest_metadata_fields):
        raise HistoricalModelGeoBudgetError(
            "Historical geo-budget manifest metadata differs"
        )
    artifact_relative = _safe_relative(entry.get("relative_path"), "relative_path")
    artifact_path = _safe_target(package_root, artifact_relative)
    if not artifact_path.is_file():
        raise FileNotFoundError("historical_geo_budget_artifact")
    if (
        artifact_path.name != PARQUET_FILENAME
        or metadata_path.name != METADATA_FILENAME
        or artifact_path.stat().st_size != entry.get("size_bytes")
        or sha256_file(artifact_path) != entry.get("sha256")
        or metadata.get("sha256") != entry.get("sha256")
    ):
        raise HistoricalModelGeoBudgetError("Historical geo-budget artifact integrity failed")
    if any(metadata.get(key) != value for key, value in expected_identity.items()):
        raise HistoricalModelGeoBudgetError("Historical geo-budget metadata identity differs")
    return package_manifest, metadata, identity


def build_historical_model_geo_budget_v1(
    *,
    registry_root: Path,
    package_id: str,
    catalog: CanonicalGeoCatalog | None = None,
) -> dict[str, Any]:
    selected_catalog = catalog or load_canonical_geo_catalog()
    registry = registry_root.expanduser().resolve()
    try:
        _, metadata, identity = _artifact_evidence(
            registry_root=registry,
            package_id=package_id,
        )
    except FileNotFoundError:
        model_version = None
        try:
            model_version = load_registry_package_identity(
                registry,
                package_id,
            ).model_run_id
        except (HistoricalGeoBudgetError, OSError):
            pass
        return _unavailable_payload(
            package_id=package_id,
            model_version=model_version,
            reason_code="historical_artifact_unavailable",
        )

    policy = load_spend_columns_policy(SPEND_POLICY_PATH)
    if (
        metadata.get("metadata_schema_version") != "1.0.0"
        or metadata.get("artifact_version") != ARTIFACT_VERSION
        or metadata.get("relative_path") != PARQUET_FILENAME
        or metadata.get("spend_columns_version") != policy.spend_columns_version
        or metadata.get("spend_columns_config_sha256") != policy.config_sha256
        or tuple(metadata.get("spend_columns") or ()) != policy.spend_columns
    ):
        raise HistoricalModelGeoBudgetError("Historical geo-budget policy metadata differs")
    source_rows = metadata.get("rows")
    if not isinstance(source_rows, list) or not source_rows:
        raise HistoricalModelGeoBudgetError("Historical geo-budget rows are unavailable")
    if metadata.get("rows_n") != len(source_rows) or metadata.get(
        "geographies_n"
    ) != len(source_rows):
        raise HistoricalModelGeoBudgetError("Historical geo-budget row counts differ")

    rows: list[dict[str, Any]] = []
    resolutions = []
    budgets_by_geo_id: dict[str, float] = {}
    seen_geo_ids: set[str] = set()
    for index, source in enumerate(source_rows):
        if not isinstance(source, Mapping):
            raise HistoricalModelGeoBudgetError(f"Historical row {index} is invalid")
        resolution = selected_catalog.resolve(source.get("geo_model_name"))
        if resolution.geo_id in seen_geo_ids:
            raise HistoricalModelGeoBudgetError(
                "Multiple model geographies resolve to one canonical geography"
            )
        seen_geo_ids.add(resolution.geo_id)
        try:
            budget = float(source["historical_total_budget_rub"])
            share = float(source["budget_share"])
            active_days = int(source["active_days_n"])
            active_rows = int(source["active_rows_n"])
        except (KeyError, TypeError, ValueError) as exc:
            raise HistoricalModelGeoBudgetError(
                "Historical geo-budget row metrics are invalid"
            ) from exc
        if (
            not math.isfinite(budget)
            or budget < 0
            or not math.isfinite(share)
            or not 0 <= share <= 1
            or active_days < 0
            or active_rows < active_days
        ):
            raise HistoricalModelGeoBudgetError(
                "Historical geo-budget row metrics are outside their domain"
            )
        resolutions.append(resolution)
        budgets_by_geo_id[resolution.geo_id] = budget
        rows.append(
            {
                "geo_id": resolution.geo_id,
                "geo_display_name": resolution.geo_display_name,
                "latitude": resolution.latitude,
                "longitude": resolution.longitude,
                "coordinates_status": resolution.coordinates_status,
                "historical_total_budget_rub": budget,
                "budget_share": share,
                "active_days_n": active_days,
                "active_rows_n": active_rows,
            }
        )
    rows.sort(key=lambda row: str(row["geo_display_name"]))
    total_budget = float(metadata.get("total_budget_rub"))
    if not math.isfinite(total_budget) or total_budget < 0:
        raise HistoricalModelGeoBudgetError("Historical total budget is invalid")
    tolerance = max(0.01, total_budget * 1e-12)
    if abs(math.fsum(row["historical_total_budget_rub"] for row in rows) - total_budget) > tolerance:
        raise HistoricalModelGeoBudgetError("Historical total budget does not reconcile")
    if total_budget > 0 and abs(math.fsum(row["budget_share"] for row in rows) - 1.0) > 1e-8:
        raise HistoricalModelGeoBudgetError("Historical budget shares do not reconcile")
    coverage = coverage_summary(
        resolutions,
        budget_by_geo_id=budgets_by_geo_id,
    )
    period_start = str(metadata.get("period_start") or "")
    period_end = str(metadata.get("period_end") or "")
    payload = {
        "contract_name": CONTRACT_NAME,
        "schema_version": SCHEMA_VERSION,
        "record_origin": "verified_model_package_artifact",
        "status": coverage["status"],
        "title": TITLE,
        "display_text": (
            "Исторические расходы доступны для всех географий."
            if coverage["status"] == "available"
            else "Часть исторического бюджета не привязана к утвержденным координатам."
            if coverage["status"] == "partial"
            else "Для исторических расходов пока нет утвержденных координат."
        ),
        "period_display_text": (
            f"Период данных: {_format_date(period_start)} — {_format_date(period_end)}"
        ),
        "package_id": identity.package_id,
        "model_version": identity.model_run_id,
        "artifact_id": str(metadata.get("artifact_id") or ""),
        "artifact_version": ARTIFACT_VERSION,
        "catalog_version": GEO_CATALOG_VERSION,
        "period_start": period_start,
        "period_end": period_end,
        "spend_columns_version": policy.spend_columns_version,
        "total_budget_rub": total_budget,
        "geographies_n": len(rows),
        "coverage": coverage,
        "rows": rows,
        "limitations": [
            {
                "code": "historical_spend_only",
                "display_text": "Показаны фактические рекламные расходы из данных активной модели.",
            },
            {
                "code": "activity_not_launch_count",
                "display_text": "Активные строки и дни отражают наблюдения с расходами, а не число отдельных запусков.",
            },
            {
                "code": "point_coordinates",
                "display_text": "Координаты показывают точки географий, а не их административные границы.",
            },
        ],
        "updated_at_utc": str(metadata.get("generated_at_utc") or ""),
    }
    if coverage["status"] != "available":
        payload["limitations"].append(
            {
                "code": "unlocated_historical_budget",
                "display_text": "Бюджет без утвержденных координат сохранен в результате и показан отдельно.",
            }
        )
    validate_historical_model_geo_budget_v1(payload)
    return payload


__all__ = [
    "HistoricalModelGeoBudgetError",
    "SPEND_POLICY_PATH",
    "build_historical_model_geo_budget_v1",
]
