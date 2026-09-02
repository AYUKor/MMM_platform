"""Materialize and preflight one verified Fin transfer as an immutable server release.

The Fin contour intentionally uses a compact transfer layout.  The server runtime
does not: registry package extensions must live below
``package_artifacts/<package_id>/`` and the model package must be restored to the
registered ``run_dir``.  This module treats ``MODEL_CLOSURE.json`` as the signed
mapping between those two layouts and fails closed on any identity, path, hash or
byte mismatch.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.cookies import SimpleCookie
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "1.0.0"
RELEASE_MANIFEST = "manifests/RELEASE_MANIFEST.json"
MODEL_CLOSURE = "manifests/MODEL_CLOSURE.json"
TRANSFER_MANIFEST = "manifests/TRANSFER_MANIFEST.json"
TRANSFER_CHECKSUMS = "manifests/TRANSFER_SHA256SUMS.json"
FRONTEND_MANIFEST = "manifests/FRONTEND_DIST_MANIFEST.json"
REGISTRY_RELATIVE_ROOT = PurePosixPath(
    "03_Outputs/01_PyMC_outputs/00_Model_registry"
)
EXTENSION_SOURCE_ROOT = PurePosixPath("model/package_extensions")
PACKAGE_ID_PATTERN = re.compile(r"pkg_[0-9a-f]{16}_[0-9a-f]{16}\Z")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
MATERIALIZED_ROLES = {
    "MODEL_PACKAGE",
    "MODEL_REGISTRY",
    "PACKAGE_EXTENSIONS",
}
HISTORICAL_EXTENSION_FILES = {
    PurePosixPath("package_artifacts_manifest_v1.json"),
    PurePosixPath("historical_geo_budget_v1/historical_geo_budget_v1.build.json"),
    PurePosixPath("historical_geo_budget_v1/historical_geo_budget_v1.metadata.json"),
    PurePosixPath("historical_geo_budget_v1/historical_geo_budget_v1.parquet"),
    PurePosixPath(
        "historical_geo_budget_v1/historical_model_geo_budget_v1.sample.json"
    ),
}


@dataclass(frozen=True)
class FileMapping:
    """One immutable file mapping from the compact Fin layout to server layout."""

    role: str
    source_relative_path: PurePosixPath
    target_relative_path: PurePosixPath
    sha256: str
    bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "fin_relative_path": self.source_relative_path.as_posix(),
            "server_relative_path": self.target_relative_path.as_posix(),
            "sha256": self.sha256,
            "bytes": self.bytes,
        }


@dataclass(frozen=True)
class FrontendFile:
    relative_path: PurePosixPath
    sha256: str
    bytes: int


@dataclass(frozen=True)
class ReleaseContract:
    fin_root: Path
    release_id: str
    application_commit: str
    application_tree: str
    package_id: str
    model_closure_sha256: str
    model_mappings: tuple[FileMapping, ...]
    frontend_source_root: PurePosixPath
    frontend_files: tuple[FrontendFile, ...]
    application_bundle: Path

    @property
    def package_artifacts_root(self) -> PurePosixPath:
        return REGISTRY_RELATIVE_ROOT / "package_artifacts" / self.package_id


def _normalise_relative(path: Path, root: Path) -> str:
    relative = path.relative_to(root)
    return PurePosixPath(
        *(unicodedata.normalize("NFC", part) for part in relative.parts)
    ).as_posix()


def _safe_relative(value: Any, field: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty relative path")
    value = unicodedata.normalize("NFC", value)
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError(f"{field} must be a safe relative path: {value!r}")
    return relative


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, field: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read {field}: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{field} must contain a JSON object")
    return payload


def _file_index(root: Path) -> dict[str, Path]:
    """Index regular files by NFC-normalised relative path.

    macOS archives can contain canonically decomposed Cyrillic names.  Manifests
    use NFC.  Matching is Unicode-normalisation aware, while the destination is
    always created from the manifest path so Linux runtime lookup is deterministic.
    """

    resolved = root.expanduser().resolve()
    if not resolved.is_dir():
        raise ValueError(f"Directory does not exist: {resolved}")
    result: dict[str, Path] = {}
    for current, dirs, files in os.walk(resolved, followlinks=False):
        current_path = Path(current)
        for name in tuple(dirs):
            directory = current_path / name
            if directory.is_symlink():
                raise ValueError(f"Symlink directory is forbidden: {directory}")
        for name in files:
            path = current_path / name
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"Only regular files are allowed: {path}")
            relative = _normalise_relative(path, resolved)
            if relative in result:
                raise ValueError(f"Unicode-normalised path collision: {relative}")
            result[relative] = path
    return result


def _require_file(index: Mapping[str, Path], relative: str, field: str) -> Path:
    path = index.get(unicodedata.normalize("NFC", relative))
    if path is None:
        raise ValueError(f"Missing {field}: {relative}")
    return path


def _verified_row(row: Mapping[str, Any], field: str) -> tuple[str, int]:
    sha = str(row.get("sha256") or "")
    if not SHA256_PATTERN.fullmatch(sha):
        raise ValueError(f"{field}.sha256 is invalid")
    size = row.get("bytes", row.get("size_bytes"))
    if not isinstance(size, int) or size < 0:
        raise ValueError(f"{field}.bytes is invalid")
    return sha, size


def verify_transfer_inventory(fin_root: Path) -> dict[str, Any]:
    """Verify the complete extracted transfer payload before materialization."""

    root = fin_root.expanduser().resolve()
    index = _file_index(root)
    manifest_path = _require_file(index, TRANSFER_CHECKSUMS, "transfer checksums")
    manifest = _read_json(manifest_path, TRANSFER_CHECKSUMS)
    if manifest.get("status") != "passed":
        raise ValueError("Transfer checksum manifest is not passed")
    rows = manifest.get("files")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Transfer checksum inventory is empty")
    expected: set[str] = set()
    mismatches: list[str] = []
    total_bytes = 0
    for position, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            raise ValueError(f"Transfer checksum row {position} is invalid")
        relative = _safe_relative(
            raw.get("relative_path"), f"transfer.files[{position}].relative_path"
        ).as_posix()
        if relative in expected:
            raise ValueError(f"Duplicate transfer checksum path: {relative}")
        expected.add(relative)
        sha, size = _verified_row(raw, f"transfer.files[{position}]")
        path = index.get(relative)
        if path is None:
            mismatches.append(f"missing:{relative}")
            continue
        actual_size = path.stat().st_size
        actual_sha = _sha256(path)
        total_bytes += actual_size
        if actual_size != size:
            mismatches.append(f"bytes:{relative}")
        if actual_sha != sha:
            mismatches.append(f"sha256:{relative}")
    allowed_unlisted = {TRANSFER_CHECKSUMS, TRANSFER_MANIFEST}
    unexpected = sorted(set(index) - expected - allowed_unlisted)
    if unexpected:
        mismatches.extend(f"unexpected:{path}" for path in unexpected)
    if len(rows) != manifest.get("files_n") or total_bytes != manifest.get("bytes"):
        mismatches.append("inventory_totals")
    if mismatches:
        raise ValueError("Transfer inventory verification failed: " + ", ".join(mismatches[:8]))
    return {
        "status": "passed",
        "files": len(rows),
        "bytes": total_bytes,
        "unexpected": 0,
        "missing": 0,
        "sha_mismatch": 0,
        "bytes_mismatch": 0,
    }


def _identity_values(payloads: Mapping[str, Any], field: str) -> str:
    values = {str(value) for value in payloads.values() if value not in {None, ""}}
    if len(values) != 1:
        details = ", ".join(f"{name}={value!r}" for name, value in payloads.items())
        raise ValueError(f"{field} identity mismatch: {details}")
    return values.pop()


def load_release_contract(fin_root: Path, *, verify_transfer: bool = True) -> ReleaseContract:
    """Load and cross-check release, model, registry and extension identities."""

    root = fin_root.expanduser().resolve()
    if verify_transfer:
        verify_transfer_inventory(root)
    index = _file_index(root)
    release = _read_json(_require_file(index, RELEASE_MANIFEST, "release manifest"), RELEASE_MANIFEST)
    closure = _read_json(_require_file(index, MODEL_CLOSURE, "model closure"), MODEL_CLOSURE)
    transfer = _read_json(_require_file(index, TRANSFER_MANIFEST, "transfer manifest"), TRANSFER_MANIFEST)
    frontend = _read_json(_require_file(index, FRONTEND_MANIFEST, "frontend manifest"), FRONTEND_MANIFEST)
    if release.get("closure_status") != "passed" or closure.get("status") != "passed":
        raise ValueError("Release/model closure is not passed")
    if frontend.get("status") != "passed":
        raise ValueError("Frontend dist manifest is not passed")

    release_id = _identity_values(
        {
            "release": release.get("release_id"),
            "closure": closure.get("release_id"),
            "transfer": transfer.get("release_id"),
            "frontend": frontend.get("release_id"),
        },
        "release_id",
    )
    if root.name != release_id:
        raise ValueError(f"Fin root name must equal release_id: {root.name!r} != {release_id!r}")
    package_id = _identity_values(
        {
            "release": dict(release.get("model") or {}).get("package_id"),
            "closure": closure.get("package_id"),
            "transfer": dict(transfer.get("model") or {}).get("package_id"),
        },
        "package_id",
    )
    if not PACKAGE_ID_PATTERN.fullmatch(package_id):
        raise ValueError(f"Invalid package_id: {package_id!r}")
    application_commit = _identity_values(
        {
            "release": dict(release.get("application") or {}).get("commit"),
            "transfer": dict(transfer.get("application") or {}).get("commit"),
            "frontend": frontend.get("source_commit"),
        },
        "application commit",
    )
    application_tree = _identity_values(
        {
            "release": dict(release.get("application") or {}).get("tree"),
            "transfer": dict(transfer.get("application") or {}).get("tree"),
            "frontend": frontend.get("source_tree"),
        },
        "application tree",
    )
    if not COMMIT_PATTERN.fullmatch(application_commit) or not COMMIT_PATTERN.fullmatch(application_tree):
        raise ValueError("Application commit/tree identity is invalid")
    closure_sha = _identity_values(
        {
            "release": dict(dict(release.get("model") or {}).get("closure") or {}).get("sha256"),
            "closure": closure.get("closure_sha256"),
            "transfer": dict(transfer.get("model") or {}).get("closure_sha256"),
        },
        "model closure SHA-256",
    )
    if not SHA256_PATTERN.fullmatch(closure_sha):
        raise ValueError("Model closure SHA-256 is invalid")

    raw_rows = closure.get("files")
    if not isinstance(raw_rows, list) or not raw_rows:
        raise ValueError("MODEL_CLOSURE files are empty")
    mappings: list[FileMapping] = []
    seen_sources: set[PurePosixPath] = set()
    seen_targets: set[PurePosixPath] = set()
    for position, raw in enumerate(raw_rows):
        if not isinstance(raw, Mapping):
            raise ValueError(f"MODEL_CLOSURE row {position} is invalid")
        role = str(raw.get("role") or "")
        if role not in MATERIALIZED_ROLES:
            raise ValueError(f"Unsupported model closure role: {role!r}")
        source = _safe_relative(
            raw.get("release_relative_path"),
            f"model_closure.files[{position}].release_relative_path",
        )
        target = _safe_relative(
            raw.get("source_relative_path"),
            f"model_closure.files[{position}].source_relative_path",
        )
        sha, size = _verified_row(raw, f"model_closure.files[{position}]")
        if source in seen_sources or target in seen_targets:
            raise ValueError("Model closure source/target mapping is not one-to-one")
        seen_sources.add(source)
        seen_targets.add(target)
        if source.as_posix() not in index:
            raise ValueError(f"Model closure source is missing: {source}")
        source_path = index[source.as_posix()]
        if source_path.stat().st_size != size or _sha256(source_path) != sha:
            raise ValueError(f"Model closure source integrity failed: {source}")
        mappings.append(FileMapping(role, source, target, sha, size))

    expected_files = closure.get("closure_files")
    expected_bytes = closure.get("closure_bytes")
    if len(mappings) != expected_files or sum(row.bytes for row in mappings) != expected_bytes:
        raise ValueError("Model closure count/bytes mismatch")
    extension_mappings = [row for row in mappings if row.role == "PACKAGE_EXTENSIONS"]
    if len(extension_mappings) != 5:
        raise ValueError(f"Expected exactly five package-extension files, got {len(extension_mappings)}")
    package_root = REGISTRY_RELATIVE_ROOT / "package_artifacts" / package_id
    actual_extension_targets = {
        row.target_relative_path.relative_to(package_root)
        for row in extension_mappings
        if row.target_relative_path.is_relative_to(package_root)
    }
    if actual_extension_targets != HISTORICAL_EXTENSION_FILES:
        raise ValueError("Package-extension target mapping does not preserve package_id layout")
    if any(not row.source_relative_path.is_relative_to(EXTENSION_SOURCE_ROOT) for row in extension_mappings):
        raise ValueError("Package-extension source is outside model/package_extensions")

    registration_rel = REGISTRY_RELATIVE_ROOT / "registrations" / f"{package_id}.json"
    registration_mapping = next(
        (row for row in mappings if row.target_relative_path == registration_rel), None
    )
    if registration_mapping is None:
        raise ValueError("Model closure lacks the package registration")
    registration = _read_json(
        index[registration_mapping.source_relative_path.as_posix()], "registry registration"
    )
    channel_mapping = next(
        (
            row
            for row in mappings
            if row.target_relative_path == REGISTRY_RELATIVE_ROOT / "channels/preprod.json"
        ),
        None,
    )
    if channel_mapping is None:
        raise ValueError("Model closure lacks the preprod channel pointer")
    channel = _read_json(index[channel_mapping.source_relative_path.as_posix()], "registry channel")
    extension_manifest_mapping = next(
        (
            row
            for row in extension_mappings
            if row.target_relative_path == package_root / "package_artifacts_manifest_v1.json"
        ),
        None,
    )
    if extension_manifest_mapping is None:
        raise ValueError("Model closure lacks package_artifacts_manifest_v1.json")
    extension_manifest = _read_json(
        index[extension_manifest_mapping.source_relative_path.as_posix()],
        "package artifacts manifest",
    )
    resolved_package_id = _identity_values(
        {
            "release/closure/transfer": package_id,
            "registration": registration.get("package_id"),
            "channel": channel.get("package_id"),
            "package_artifacts": extension_manifest.get("package_id"),
        },
        "verified package_id",
    )
    if resolved_package_id != package_id:
        raise ValueError("Verified package_id differs")
    if extension_manifest.get("registration_content_sha256") != registration.get(
        "registration_content_sha256"
    ):
        raise ValueError("Package-extension registration binding differs")
    if extension_manifest.get("package_input_fingerprint") != registration.get(
        "package_input_fingerprint"
    ):
        raise ValueError("Package-extension fingerprint binding differs")

    frontend_root = _safe_relative(
        frontend.get("dist_relative_path"), "frontend.dist_relative_path"
    )
    raw_frontend_files = frontend.get("files")
    if not isinstance(raw_frontend_files, list) or not raw_frontend_files:
        raise ValueError("Frontend dist inventory is empty")
    frontend_files: list[FrontendFile] = []
    for position, raw in enumerate(raw_frontend_files):
        if not isinstance(raw, Mapping):
            raise ValueError(f"Frontend file row {position} is invalid")
        relative = _safe_relative(raw.get("relative_path"), f"frontend.files[{position}]")
        sha, size = _verified_row(raw, f"frontend.files[{position}]")
        source_path = _require_file(index, (frontend_root / relative).as_posix(), "frontend file")
        if source_path.stat().st_size != size or _sha256(source_path) != sha:
            raise ValueError(f"Frontend dist integrity failed: {relative}")
        frontend_files.append(FrontendFile(relative, sha, size))
    if len(frontend_files) != frontend.get("dist_files_n") or sum(
        row.bytes for row in frontend_files
    ) != frontend.get("dist_bytes"):
        raise ValueError("Frontend dist count/bytes mismatch")

    bundle_candidates = sorted(
        path for relative, path in index.items() if relative.startswith("deployment/") and relative.endswith(".bundle")
    )
    if len(bundle_candidates) != 1:
        raise ValueError(f"Expected one application Git bundle, got {len(bundle_candidates)}")
    return ReleaseContract(
        fin_root=root,
        release_id=release_id,
        application_commit=application_commit,
        application_tree=application_tree,
        package_id=package_id,
        model_closure_sha256=closure_sha,
        model_mappings=tuple(mappings),
        frontend_source_root=frontend_root,
        frontend_files=tuple(frontend_files),
        application_bundle=bundle_candidates[0],
    )


def _run_git(arguments: Sequence[str], *, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        # Ignore workstation-global aliases/trust while preserving an explicitly
        # supplied server GIT_CONFIG_SYSTEM exact safe.directory allowlist.
        env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull},
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise ValueError(f"Git command failed: {detail}")
    return completed.stdout.strip()


def _copy_exclusive(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    current = target.parent
    while current != current.parent:
        if current.is_symlink():
            raise ValueError(f"Destination parent symlink is forbidden: {current}")
        current = current.parent
    try:
        with source.open("rb") as source_handle, target.open("xb") as target_handle:
            shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
        target.chmod(0o644)
    except BaseException:
        if target.exists():
            target.unlink()
        raise


def _verify_file(path: Path, sha: str, size: int, label: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Missing regular {label}: {path}")
    if path.stat().st_size != size:
        raise ValueError(f"Byte mismatch for {label}: {path}")
    if _sha256(path) != sha:
        raise ValueError(f"SHA-256 mismatch for {label}: {path}")


def _verify_extension_semantics(candidate_root: Path, contract: ReleaseContract) -> dict[str, Any]:
    package_root = candidate_root / Path(contract.package_artifacts_root.as_posix())
    actual_index = _file_index(package_root)
    expected = {path.as_posix() for path in HISTORICAL_EXTENSION_FILES}
    actual = set(actual_index)
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing or unexpected:
        raise ValueError(
            f"Package-extension structure differs: missing={missing}, unexpected={unexpected}"
        )
    manifest_path = actual_index["package_artifacts_manifest_v1.json"]
    build_path = actual_index[
        "historical_geo_budget_v1/historical_geo_budget_v1.build.json"
    ]
    metadata_path = actual_index[
        "historical_geo_budget_v1/historical_geo_budget_v1.metadata.json"
    ]
    artifact_path = actual_index[
        "historical_geo_budget_v1/historical_geo_budget_v1.parquet"
    ]
    sample_path = actual_index[
        "historical_geo_budget_v1/historical_model_geo_budget_v1.sample.json"
    ]
    manifest = _read_json(manifest_path, "materialized package artifacts manifest")
    build = _read_json(build_path, "materialized extension build record")
    metadata = _read_json(metadata_path, "materialized extension metadata")
    sample = _read_json(sample_path, "materialized extension response sample")
    registration = _read_json(
        candidate_root
        / Path((REGISTRY_RELATIVE_ROOT / "registrations" / f"{contract.package_id}.json").as_posix()),
        "materialized package registration",
    )
    if _identity_values(
        {
            "contract": contract.package_id,
            "registration": registration.get("package_id"),
            "manifest": manifest.get("package_id"),
            "build": build.get("package_id"),
            "metadata": metadata.get("package_id"),
            "sample": sample.get("package_id"),
        },
        "materialized extension package_id",
    ) != contract.package_id:
        raise ValueError("Materialized extension package_id differs")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 1 or not isinstance(artifacts[0], Mapping):
        raise ValueError("Package artifacts manifest must contain one artifact")
    artifact = dict(artifacts[0])
    expected_artifact_sha = str(artifact.get("sha256") or "")
    expected_artifact_bytes = artifact.get("size_bytes")
    expected_metadata_sha = str(artifact.get("metadata_sha256") or "")
    if artifact.get("relative_path") != "historical_geo_budget_v1/historical_geo_budget_v1.parquet":
        raise ValueError("Historical artifact relative_path differs")
    if artifact.get("metadata_relative_path") != "historical_geo_budget_v1/historical_geo_budget_v1.metadata.json":
        raise ValueError("Historical metadata_relative_path differs")
    _verify_file(artifact_path, expected_artifact_sha, expected_artifact_bytes, "historical artifact")
    _verify_file(metadata_path, expected_metadata_sha, metadata_path.stat().st_size, "historical metadata")
    if any(
        metadata.get(key) != artifact.get(key)
        for key in (
            "artifact_id",
            "artifact_version",
            "period_start",
            "period_end",
            "rows_n",
            "geographies_n",
            "total_budget_rub",
            "source_panel_sha256",
        )
    ):
        raise ValueError("Historical manifest/metadata binding differs")
    if metadata.get("sha256") != expected_artifact_sha or metadata.get("size_bytes") != expected_artifact_bytes:
        raise ValueError("Historical metadata artifact identity differs")
    if (
        build.get("build_status") != "completed"
        or build.get("artifact_sha256") != expected_artifact_sha
        or build.get("artifact_size_bytes") != expected_artifact_bytes
        or build.get("metadata_sha256") != expected_metadata_sha
        or build.get("package_artifacts_manifest_sha256") != _sha256(manifest_path)
    ):
        raise ValueError("Historical extension build record binding differs")
    if (
        sample.get("contract_name") != "historical_model_geo_budget_v1"
        or sample.get("record_origin") != "verified_model_package_artifact"
        or sample.get("status") != "available"
        or sample.get("artifact_id") != artifact.get("artifact_id")
        or sample.get("artifact_version") != artifact.get("artifact_version")
        or sample.get("geographies_n") != metadata.get("geographies_n")
        or sample.get("total_budget_rub") != metadata.get("total_budget_rub")
    ):
        raise ValueError("Historical extension response sample is not an available bound artifact")
    coverage = dict(sample.get("coverage") or {})
    if (
        coverage.get("status") != "available"
        or coverage.get("located_geographies_n") != metadata.get("geographies_n")
        or coverage.get("unlocated_geographies_n") != 0
    ):
        raise ValueError("Historical extension response sample coverage is not complete")
    return {
        "status": "passed",
        "files": 5,
        "unexpected": 0,
        "missing": 0,
        "sha_mismatch": 0,
        "bytes_mismatch": 0,
        "consumers": {
            "package_artifacts_manifest_v1.json": "registry/package identity resolution",
            "historical_geo_budget_v1.build.json": "build-to-manifest identity binding",
            "historical_geo_budget_v1.metadata.json": "runtime metadata/hash resolution",
            "historical_geo_budget_v1.parquet": "runtime artifact hash/bytes resolution",
            "historical_model_geo_budget_v1.sample.json": "available business-state baseline",
        },
        "artifact": {
            "artifact_id": artifact.get("artifact_id"),
            "sha256": expected_artifact_sha,
            "bytes": expected_artifact_bytes,
        },
        "expected_response": sample,
    }


def verify_materialized_candidate(candidate_root: Path, contract: ReleaseContract) -> dict[str, Any]:
    """Verify Git, frontend, model and full package-extension closure in-place."""

    root = candidate_root.expanduser().resolve()
    actual_commit = _run_git(["rev-parse", "HEAD"], cwd=root)
    actual_tree = _run_git(["rev-parse", "HEAD^{tree}"], cwd=root)
    if actual_commit != contract.application_commit or actual_tree != contract.application_tree:
        raise ValueError(
            f"Application identity differs: commit={actual_commit}, tree={actual_tree}"
        )
    tracked_dirty = _run_git(["status", "--porcelain", "--untracked-files=no"], cwd=root)
    if tracked_dirty:
        raise ValueError("Materialized application tracked tree is dirty")
    for row in contract.frontend_files:
        target = root / "04_Web_app/frontend/dist" / Path(row.relative_path.as_posix())
        _verify_file(target, row.sha256, row.bytes, "frontend dist file")
    role_counts = {role: 0 for role in sorted(MATERIALIZED_ROLES)}
    for row in contract.model_mappings:
        target = root / Path(row.target_relative_path.as_posix())
        _verify_file(target, row.sha256, row.bytes, row.role)
        role_counts[row.role] += 1
    extension = _verify_extension_semantics(root, contract)
    return {
        "status": "passed",
        "application": {"commit": actual_commit, "tree": actual_tree},
        "frontend": {
            "files": len(contract.frontend_files),
            "bytes": sum(row.bytes for row in contract.frontend_files),
        },
        "model": {
            "package_id": contract.package_id,
            "closure_sha256": contract.model_closure_sha256,
            "files": len(contract.model_mappings),
            "bytes": sum(row.bytes for row in contract.model_mappings),
            "role_counts": role_counts,
        },
        "extensions": {key: value for key, value in extension.items() if key != "expected_response"},
    }


def materialize_server_release(
    fin_root: Path,
    releases_root: Path,
    candidate_id: str,
) -> dict[str, Any]:
    """Create a new candidate through a verified sibling staging directory."""

    contract = load_release_contract(fin_root, verify_transfer=True)
    expected_candidate = re.compile(re.escape(contract.release_id) + r"__deploy[1-9][0-9]*\Z")
    if not expected_candidate.fullmatch(candidate_id):
        raise ValueError(
            "candidate_id must distinguish the server attempt from the Fin release: "
            f"expected {contract.release_id}__deployN"
        )
    release_parent = releases_root.expanduser().resolve()
    if not release_parent.is_dir():
        raise ValueError(f"Server releases root must already exist: {release_parent}")
    destination = release_parent / candidate_id
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Candidate collision; overwrite is forbidden: {destination}")
    staging = release_parent / f".{candidate_id}.materializing-{secrets.token_hex(8)}"
    if staging.exists() or staging.is_symlink():
        raise FileExistsError(f"Unexpected staging collision: {staging}")
    source_index = _file_index(contract.fin_root)
    try:
        _run_git(
            [
                "clone",
                "--quiet",
                "--no-checkout",
                "--no-local",
                str(contract.application_bundle),
                str(staging),
            ]
        )
        _run_git(["checkout", "--quiet", "--detach", contract.application_commit], cwd=staging)
        clone_tree = _run_git(["rev-parse", "HEAD^{tree}"], cwd=staging)
        if clone_tree != contract.application_tree:
            raise ValueError(f"Application bundle tree differs: {clone_tree}")
        for row in contract.frontend_files:
            source_relative = contract.frontend_source_root / row.relative_path
            source = _require_file(source_index, source_relative.as_posix(), "frontend source")
            target = staging / "04_Web_app/frontend/dist" / Path(row.relative_path.as_posix())
            _copy_exclusive(source, target)
        for row in contract.model_mappings:
            source = _require_file(
                source_index, row.source_relative_path.as_posix(), "model closure source"
            )
            target = staging / Path(row.target_relative_path.as_posix())
            _copy_exclusive(source, target)
        verification = verify_materialized_candidate(staging, contract)
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"Candidate appeared during materialization: {destination}")
        staging.rename(destination)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    extension_mapping = [
        row.to_dict() for row in contract.model_mappings if row.role == "PACKAGE_EXTENSIONS"
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "materialized",
        "fin_release_id": contract.release_id,
        "server_candidate_id": candidate_id,
        "candidate_root": str(destination),
        "package_id_source": "verified release/model/registry/package-artifacts manifests",
        "package_id": contract.package_id,
        "extension_mapping": extension_mapping,
        "verification": verification,
    }


def assert_historical_business_state(
    response: Mapping[str, Any], expected: Mapping[str, Any]
) -> dict[str, Any]:
    """Require the expected business state; HTTP/schema validity alone is insufficient."""

    required_equal = (
        "contract_name",
        "record_origin",
        "status",
        "package_id",
        "artifact_id",
        "artifact_version",
        "geographies_n",
        "total_budget_rub",
    )
    mismatches = [
        key for key in required_equal if response.get(key) != expected.get(key)
    ]
    expected_coverage = dict(expected.get("coverage") or {})
    actual_coverage = dict(response.get("coverage") or {})
    for key in ("status", "located_geographies_n", "unlocated_geographies_n"):
        if actual_coverage.get(key) != expected_coverage.get(key):
            mismatches.append(f"coverage.{key}")
    if expected.get("status") != "available" or expected.get(
        "record_origin"
    ) != "verified_model_package_artifact":
        raise ValueError("Acceptance baseline itself is not available verified artifact state")
    if response.get("status") != "available" or response.get(
        "record_origin"
    ) != "verified_model_package_artifact":
        mismatches.append("business_state")
    if mismatches:
        raise ValueError(
            "Historical geo-budget business-state gate failed: "
            + ", ".join(sorted(set(mismatches)))
        )
    return {
        "status": "passed",
        "contract_name": response.get("contract_name"),
        "record_origin": response.get("record_origin"),
        "business_status": response.get("status"),
        "package_id": response.get("package_id"),
        "geographies_n": response.get("geographies_n"),
        "located_geographies_n": actual_coverage.get("located_geographies_n"),
        "unlocated_geographies_n": actual_coverage.get("unlocated_geographies_n"),
        "total_budget_rub": response.get("total_budget_rub"),
        "coverage": (
            f"{actual_coverage.get('located_geographies_n')}/"
            f"{response.get('geographies_n')}"
        ),
    }


def _http_json(
    method: str,
    url: str,
    *,
    payload: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 5.0,
) -> tuple[int, dict[str, Any], Mapping[str, str]]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json", **dict(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            parsed = json.loads(response.read().decode("utf-8"))
            return response.status, parsed, response.headers
    except urllib.error.HTTPError as exc:
        try:
            parsed = json.loads(exc.read().decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            parsed = {"error": {"code": "INVALID_HTTP_RESPONSE"}}
        return exc.code, parsed, exc.headers


def _choose_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def production_equivalent_preflight(
    candidate_root: Path,
    fin_root: Path,
    work_root: Path,
    *,
    port: int | None = None,
    python_executable: Path | None = None,
) -> dict[str, Any]:
    """Run check-only plus authenticated alternate-port HTTP business gates."""

    contract = load_release_contract(fin_root, verify_transfer=True)
    candidate = candidate_root.expanduser().resolve()
    candidate_verification = verify_materialized_candidate(candidate, contract)
    extension_semantics = _verify_extension_semantics(candidate, contract)
    expected_response = extension_semantics["expected_response"]
    isolated_root = work_root.expanduser().resolve()
    if isolated_root.exists() or isolated_root.is_symlink():
        raise FileExistsError(f"Preflight work_root must not exist: {isolated_root}")
    if isolated_root == candidate or isolated_root in candidate.parents or candidate in isolated_root.parents:
        raise ValueError("Preflight work_root and candidate_root must be disjoint")
    selected_port = port or _choose_port()
    if not 1 <= selected_port <= 65535:
        raise ValueError("Alternate port must be between 1 and 65535")
    selected_python = (python_executable or Path(sys.executable)).expanduser().resolve()
    if not selected_python.is_file():
        raise ValueError(f"Python executable is missing: {selected_python}")
    process: subprocess.Popen[str] | None = None
    log_handle: Any | None = None
    try:
        isolated_root.mkdir(parents=True, mode=0o700)
        current = isolated_root / "current"
        relative_target = os.path.relpath(candidate, isolated_root)
        current.symlink_to(relative_target, target_is_directory=True)
        state = isolated_root / "shared/state"
        runtime = isolated_root / "shared/runtime"
        artifacts = isolated_root / "shared/artifacts"
        auth_db = isolated_root / "shared/auth/auth.sqlite3"
        base_url = f"http://127.0.0.1:{selected_port}"
        public_origin = "https://d1r1-preflight.example.invalid"
        config = _read_json(
            current / "04_Web_app/config/research_backend_v1.example.json",
            "candidate research config",
        )
        config["server"] = {
            **dict(config.get("server") or {}),
            "deployment_profile": "research_pilot",
            "host": "127.0.0.1",
            "port": selected_port,
            "public_base_url": public_origin,
            "allowed_origins": [public_origin, base_url],
        }
        config["paths"] = {
            **dict(config.get("paths") or {}),
            "state_root": str(state),
            "runtime_root": str(runtime),
            "artifact_root": str(artifacts),
            "registry_root": str(
                current / "03_Outputs/01_PyMC_outputs/00_Model_registry"
            ),
            "optimizer_policy_path": str(
                current
                / "02_Code/02_Budget_optimizer/optimizer_decision_policy_v3.yaml"
            ),
            "business_policy_path": str(
                current
                / "02_Code/02_Budget_optimizer/business_threshold_policy_v1.yaml"
            ),
            "federal_population_path": str(
                current
                / "04_Web_app/data/federal_geo_allocation/geo_reference_v2.csv"
            ),
        }
        config["model"] = {
            **dict(config.get("model") or {}),
            "registry_channel": "preprod",
            "expected_package_id": contract.package_id,
            "verification_mode": "serving_bundle",
        }
        config["worker"] = {
            **dict(config.get("worker") or {}),
            "python_executable": str(selected_python),
            "max_workers": 1,
        }
        config["auth"] = {
            **dict(config.get("auth") or {}),
            "mode": "local",
            "database_path": str(auth_db),
            "cookie_secure": True,
        }
        config_path = isolated_root / "research_backend.sanitized.json"
        config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        session_secret = secrets.token_urlsafe(48)
        admin_password = secrets.token_urlsafe(32) + "Aa1!"
        admin_email = "d1r1-preflight@example.invalid"
        environment = {
            **os.environ,
            "MMM_AUTH_SESSION_SECRET": session_secret,
            "MMM_AUTH_BOOTSTRAP_EMAIL": "",
            "MMM_AUTH_BOOTSTRAP_ADMIN_EMAIL": admin_email,
            "MMM_AUTH_BOOTSTRAP_ADMIN_PASSWORD": admin_password,
            "MMM_AUTH_BOOTSTRAP_ADMIN_NAME": "D1R.1 isolated preflight",
        }
        backend = current / "04_Web_app/backend_runtime.py"
        command = [
            str(selected_python),
            "-B",
            str(backend),
            "--config",
            str(config_path),
            "--project-root",
            str(current),
        ]
        check = subprocess.run(
            [*command, "--check-only"],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        if check.returncode:
            raise ValueError(f"Backend check-only failed: {check.stderr.strip()}")
        check_payload = json.loads(check.stdout)
        if (
            check_payload.get("status") != "ready"
            or check_payload.get("git_commit") != contract.application_commit
            or check_payload.get("package_id") != contract.package_id
        ):
            raise ValueError("Backend check-only identity/readiness differs")
        bootstrap = subprocess.run(
            [*command, "--bootstrap-admin"],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        if bootstrap.returncode:
            raise ValueError(f"Isolated bootstrap failed: {bootstrap.stderr.strip()}")
        log_path = isolated_root / "backend.log"
        log_handle = log_path.open("w", encoding="utf-8")
        process = subprocess.Popen(
            command,
            env=environment,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
        deadline = time.monotonic() + 30.0
        health_payload: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                log_handle.flush()
                detail = log_path.read_text(encoding="utf-8", errors="replace")[-8000:]
                raise ValueError(
                    f"Alternate-port backend exited with {process.returncode}: {detail}"
                )
            try:
                status, payload, _ = _http_json("GET", base_url + "/health", timeout=1.0)
                if status == 200 and payload.get("status") == "ok":
                    health_payload = payload
                    break
            except (OSError, urllib.error.URLError, json.JSONDecodeError):
                pass
            time.sleep(0.1)
        if health_payload is None:
            raise TimeoutError("Alternate-port backend did not become healthy")
        ready_status, ready_payload, _ = _http_json("GET", base_url + "/ready")
        if ready_status != 200 or ready_payload.get("status") != "ready":
            raise ValueError("Alternate-port /ready failed")
        login_status, _, login_headers = _http_json(
            "POST",
            base_url + "/api/v1/auth/login",
            payload={"email": admin_email, "password": admin_password},
            headers={"Origin": base_url},
        )
        if login_status != 200:
            raise ValueError(f"Isolated login failed with HTTP {login_status}")
        cookie_header = login_headers.get("Set-Cookie", "")
        cookie = SimpleCookie()
        cookie.load(cookie_header)
        if "mmm_session" not in cookie:
            raise ValueError("Isolated login did not return the session cookie")
        session_cookie = f"mmm_session={cookie['mmm_session'].value}"
        historical_status, historical_payload, _ = _http_json(
            "GET",
            base_url + "/api/v1/model/historical-geo-budget",
            headers={"Cookie": session_cookie, "Origin": base_url},
        )
        if historical_status != 200:
            raise ValueError(
                f"Historical geo-budget endpoint returned HTTP {historical_status}"
            )
        business_gate = assert_historical_business_state(
            historical_payload, expected_response
        )
        result = {
            "schema_version": SCHEMA_VERSION,
            "status": "passed",
            "layout": {
                "current_pointer": "relative",
                "current_target": relative_target,
                "server_style_materialized_root": str(candidate),
                "persistent_paths": "isolated shared state/runtime/artifacts",
                "release_paths": "current-like registry/policy paths",
            },
            "application": {
                "commit": contract.application_commit,
                "tree": contract.application_tree,
            },
            "health": health_payload,
            "ready": ready_payload,
            "historical_geo_budget": {
                **business_gate,
                "http": 200,
                "artifact_identity": extension_semantics["artifact"],
            },
            "extensions": candidate_verification["extensions"],
            "alternate_port": selected_port,
            "production_state_used": False,
        }
        return result
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if log_handle is not None:
            log_handle.close()
        if isolated_root.exists():
            shutil.rmtree(isolated_root)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    verify = subcommands.add_parser("verify-transfer")
    verify.add_argument("--fin-root", required=True, type=Path)
    materialize = subcommands.add_parser("materialize")
    materialize.add_argument("--fin-root", required=True, type=Path)
    materialize.add_argument("--releases-root", required=True, type=Path)
    materialize.add_argument("--candidate-id", required=True)
    verify_candidate = subcommands.add_parser("verify-candidate")
    verify_candidate.add_argument("--fin-root", required=True, type=Path)
    verify_candidate.add_argument("--candidate-root", required=True, type=Path)
    preflight = subcommands.add_parser("preflight")
    preflight.add_argument("--fin-root", required=True, type=Path)
    preflight.add_argument("--candidate-root", required=True, type=Path)
    preflight.add_argument("--work-root", required=True, type=Path)
    preflight.add_argument("--port", type=int)
    preflight.add_argument("--python-executable", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "verify-transfer":
        result = verify_transfer_inventory(args.fin_root)
    elif args.command == "materialize":
        result = materialize_server_release(
            args.fin_root, args.releases_root, args.candidate_id
        )
    elif args.command == "verify-candidate":
        contract = load_release_contract(args.fin_root, verify_transfer=True)
        result = verify_materialized_candidate(args.candidate_root, contract)
    elif args.command == "preflight":
        result = production_equivalent_preflight(
            args.candidate_root,
            args.fin_root,
            args.work_root,
            port=args.port,
            python_executable=args.python_executable,
        )
    else:  # pragma: no cover - argparse guarantees a known command
        raise AssertionError(args.command)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
