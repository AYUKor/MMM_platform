"""Serve the package-bound past-campaign catalog (list, card, Excel) without recomputing anything.

The catalog is a package extension written on the MMM side (``mmm_core.campaign_catalog_extension``):

    <registry>/package_artifacts/<package_id>/campaign_catalog_v1/
        campaign_catalog_v1.json, campaign_catalog_v1.xlsx, campaign_catalog_v1.metadata.json

Before anything is shown, the metadata must be bound to the active package (package_id, fingerprint and model run
of the registry registration), every recorded check must have passed and both files must still have the recorded
size and SHA-256. A missing extension is a normal "not published yet" state; any mismatch is an integrity error.
"""

from __future__ import annotations

import hashlib
import json
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


WEB_APP_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = WEB_APP_DIR.parent
PYMC_CODE_DIR = PROJECT_ROOT / "02_Code" / "01_PyMC"
if str(PYMC_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(PYMC_CODE_DIR))

from contracts.campaign_catalog_v1 import (  # noqa: E402
    CARD_CONTRACT_NAME,
    CATALOG_CONTRACT_NAME,
    DOWNLOAD_PATH,
    SCHEMA_VERSION,
    TITLE,
    WORKBOOK_SHEETS,
    validate_campaign_card_v1,
    validate_campaign_catalog_v1,
)
from mmm_core.campaign_catalog_extension import (  # noqa: E402
    ARTIFACT_VERSION,
    DATA_FILENAME,
    METADATA_FILENAME,
    WORKBOOK_FILENAME,
    CampaignCatalogExtensionError,
    failed_checks,
    sha256_file,
    validate_catalog_data,
    validate_metadata,
)
from mmm_core.historical_geo_budget import (  # noqa: E402
    HistoricalGeoBudgetError,
    load_registry_package_identity,
)


XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class CampaignCatalogError(ValueError):
    """The published catalog is not bound to the active package or its files changed."""


class CampaignCatalogUnavailableError(LookupError):
    """No catalog has been published for the active package."""


class CampaignNotFoundError(LookupError):
    """The requested campaign number is not in the published catalog."""


@dataclass(frozen=True)
class CampaignCatalogEvidence:
    package_id: str
    model_run_id: str
    metadata: Mapping[str, Any]
    data: Mapping[str, Any]
    workbook_path: Path


_CACHE: dict[tuple[Any, ...], CampaignCatalogEvidence] = {}
_CACHE_LOCK = threading.Lock()


def _stat_key(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CampaignCatalogError(f"{path.name} must contain an object")
    return payload


def load_campaign_catalog_evidence(*, registry_root: Path, package_id: str) -> CampaignCatalogEvidence:
    """Verified catalog of one registered package; FileNotFoundError when it was never published."""

    registry = registry_root.expanduser().resolve()
    if not (registry / "registrations" / f"{package_id}.json").is_file():
        raise FileNotFoundError("registration")
    try:
        identity = load_registry_package_identity(registry, package_id)
    except HistoricalGeoBudgetError as exc:
        raise CampaignCatalogError(str(exc)) from exc
    root = registry / "package_artifacts" / package_id / ARTIFACT_VERSION
    metadata_path = root / METADATA_FILENAME
    if not metadata_path.is_file():
        raise FileNotFoundError("campaign_catalog_metadata")
    data_path = root / DATA_FILENAME
    workbook_path = root / WORKBOOK_FILENAME
    if not data_path.is_file() or not workbook_path.is_file():
        raise CampaignCatalogError("Campaign catalog files are incomplete")
    key = (
        str(root),
        package_id,
        identity.package_input_fingerprint,
        identity.model_run_id,
        _stat_key(metadata_path),
        _stat_key(data_path),
        _stat_key(workbook_path),
    )
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
    if cached is not None:
        return cached
    metadata = _read_json(metadata_path)
    try:
        validate_metadata(metadata)
    except CampaignCatalogExtensionError as exc:
        raise CampaignCatalogError(str(exc)) from exc
    expected_identity = {
        "package_id": package_id,
        "package_input_fingerprint": identity.package_input_fingerprint,
        "model_run_id": identity.model_run_id,
    }
    if any(metadata.get(field) != value for field, value in expected_identity.items()):
        raise CampaignCatalogError("Campaign catalog is bound to another package")
    if failed_checks(metadata):
        raise CampaignCatalogError("Campaign catalog checks did not pass")
    for entry_key, path in (("data", data_path), ("workbook", workbook_path)):
        entry = metadata[entry_key]
        if path.stat().st_size != entry["size_bytes"] or sha256_file(path) != entry["sha256"]:
            raise CampaignCatalogError(f"Campaign catalog {entry_key} file changed after publication")
    data = _read_json(data_path)
    try:
        validate_catalog_data(data)
    except CampaignCatalogExtensionError as exc:
        raise CampaignCatalogError(str(exc)) from exc
    if any(data.get(field) != value for field, value in expected_identity.items()) or data.get(
        "catalog_version"
    ) != metadata.get("catalog_version"):
        raise CampaignCatalogError("Campaign catalog data and metadata identities differ")
    summary = data["summary"]
    if (
        summary["campaigns_n"] != metadata["campaigns_n"]
        or summary["computed_n"] != metadata["computed_n"]
    ):
        raise CampaignCatalogError("Campaign catalog counts differ from the metadata")
    evidence = CampaignCatalogEvidence(
        package_id=package_id,
        model_run_id=identity.model_run_id,
        metadata=metadata,
        data=data,
        workbook_path=workbook_path,
    )
    with _CACHE_LOCK:
        _CACHE.clear()
        _CACHE[key] = evidence
    return evidence


def _model_version(registry_root: Path, package_id: str) -> str | None:
    try:
        return load_registry_package_identity(registry_root.expanduser().resolve(), package_id).model_run_id
    except (HistoricalGeoBudgetError, OSError, ValueError):
        return None


def _unavailable_payload(*, package_id: str, model_version: str | None) -> dict[str, Any]:
    payload = {
        "contract_name": CATALOG_CONTRACT_NAME,
        "schema_version": SCHEMA_VERSION,
        "record_origin": "model_package_artifact_unavailable",
        "status": "unavailable",
        "title": TITLE,
        "display_text": "Каталог прошлых кампаний для активной модели пока не опубликован.",
        "package_id": package_id,
        "model_version": model_version,
        "model_display_name": None,
        "artifact_id": None,
        "catalog_version": None,
        "period_start": None,
        "period_end": None,
        "roas_level_label": None,
        "summary": None,
        "download": None,
        "notes": [],
        "campaigns": [],
        "updated_at_utc": None,
    }
    validate_campaign_catalog_v1(payload)
    return payload


def build_campaign_catalog_v1(*, registry_root: Path, package_id: str) -> dict[str, Any]:
    """The whole catalog of the active package, or the empty "not published yet" state."""

    try:
        evidence = load_campaign_catalog_evidence(registry_root=registry_root, package_id=package_id)
    except FileNotFoundError:
        return _unavailable_payload(package_id=package_id, model_version=_model_version(registry_root, package_id))
    data, metadata = evidence.data, evidence.metadata
    summary = data["summary"]
    payload = {
        "contract_name": CATALOG_CONTRACT_NAME,
        "schema_version": SCHEMA_VERSION,
        "record_origin": "verified_model_package_artifact",
        "status": "available",
        "title": TITLE,
        "display_text": (
            f"Каталог прошлых кампаний модели «{data['model_display_name']}»: "
            f"{summary['campaigns_n']} кампаний, оценка есть у {summary['computed_n']}."
        ),
        "package_id": evidence.package_id,
        "model_version": evidence.model_run_id,
        "model_display_name": data["model_display_name"],
        "artifact_id": metadata["artifact_id"],
        "catalog_version": data["catalog_version"],
        "period_start": data["period_start"],
        "period_end": data["period_end"],
        "roas_level_label": data["roas_level_label"],
        "summary": dict(summary),
        "download": {
            "file_name": metadata["workbook"]["download_file_name"],
            "size_bytes": metadata["workbook"]["size_bytes"],
            "sha256": metadata["workbook"]["sha256"],
            "download_path": DOWNLOAD_PATH,
            "sheets": list(WORKBOOK_SHEETS),
        },
        "notes": [dict(row) for row in data["notes"]],
        "campaigns": [dict(row) for row in data["campaigns"]],
        "updated_at_utc": data["generated_at_utc"],
    }
    validate_campaign_catalog_v1(payload)
    return payload


def build_campaign_card_v1(*, registry_root: Path, package_id: str, number: int) -> dict[str, Any]:
    """One campaign of the bound catalog, the same record as in the list."""

    try:
        evidence = load_campaign_catalog_evidence(registry_root=registry_root, package_id=package_id)
    except FileNotFoundError as exc:
        raise CampaignCatalogUnavailableError("campaign catalog is not published") from exc
    data = evidence.data
    matches = [row for row in data["campaigns"] if row["number"] == number]
    if len(matches) != 1:
        raise CampaignNotFoundError(number)
    payload = {
        "contract_name": CARD_CONTRACT_NAME,
        "schema_version": SCHEMA_VERSION,
        "record_origin": "verified_model_package_artifact",
        "package_id": evidence.package_id,
        "model_version": evidence.model_run_id,
        "model_display_name": data["model_display_name"],
        "artifact_id": evidence.metadata["artifact_id"],
        "catalog_version": data["catalog_version"],
        "period_start": data["period_start"],
        "period_end": data["period_end"],
        "roas_level_label": data["roas_level_label"],
        "notes": [dict(row) for row in data["notes"]],
        "campaign": dict(matches[0]),
        "updated_at_utc": data["generated_at_utc"],
    }
    validate_campaign_card_v1(payload)
    return payload


def campaign_catalog_workbook(*, registry_root: Path, package_id: str) -> tuple[bytes, str]:
    """Bytes of the published Excel (hash re-checked on the bytes sent) and its download file name."""

    try:
        evidence = load_campaign_catalog_evidence(registry_root=registry_root, package_id=package_id)
    except FileNotFoundError as exc:
        raise CampaignCatalogUnavailableError("campaign catalog is not published") from exc
    body = evidence.workbook_path.read_bytes()
    if hashlib.sha256(body).hexdigest() != evidence.metadata["workbook"]["sha256"]:
        raise CampaignCatalogError("Campaign catalog workbook changed after publication")
    return body, str(evidence.metadata["workbook"]["download_file_name"])


__all__ = [
    "CampaignCatalogError",
    "CampaignCatalogUnavailableError",
    "CampaignNotFoundError",
    "XLSX_MEDIA_TYPE",
    "build_campaign_card_v1",
    "build_campaign_catalog_v1",
    "campaign_catalog_workbook",
    "load_campaign_catalog_evidence",
]
