"""Build and operate the single-server X5 MMM research-pilot deployment.

The tool deliberately keeps infrastructure concerns outside MMM mathematics.
It packages one registered serving model without its training panel, renders a
loopback Python + Nginx + systemd deployment, verifies health and disk space,
and creates restorable backups of file-backed application state.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Iterable, Mapping
from urllib.parse import urlsplit


MODEL_BUNDLE_SCHEMA_VERSION = "1.0.0"
BACKUP_SCHEMA_VERSION = "1.0.0"
MODEL_BUNDLE_KIND = "x5_mmm_model_serving_bundle"
BACKUP_KIND = "x5_mmm_research_runtime_backup"
MANIFEST_MEMBER = "bundle_manifest.json"
PAYLOAD_PREFIX = "payload"
PACKAGE_ID_RE = re.compile(r"^pkg_[0-9a-f]{16}_[0-9a-f]{16}$")
CHANNEL_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
DOMAIN_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
SERVING_RUNTIME_REQUIRED_FILES = {
    "model_manifest.json",
    "run_config.json",
    "capability_matrix.csv",
    "risk_registry.csv",
    "gate_policy.json",
    "gate_results.csv",
    "posterior_index.json",
    "fit_design_metadata.json",
    "fit_design_media_scales.csv",
    "target_denominator_metadata.csv",
    "historical_support_bounds.csv",
    "adstock_warm_start.csv",
}
TERMINAL_STATUSES = {
    "uploads": {"parsed", "rejected"},
    "validations": {"valid", "invalid"},
    "jobs": {"succeeded", "failed", "cancelled", "timed_out"},
}


@dataclass(frozen=True)
class PayloadFile:
    source: Path
    path: str
    role: str
    sha256: str
    size_bytes: int

    def manifest_row(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "role": self.role,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_stream(handle: BinaryIO) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _sha256_path(path: Path) -> str:
    with path.open("rb") as handle:
        return _sha256_stream(handle)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _atomic_write(path: Path, payload: bytes, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _safe_relative(value: str) -> str:
    if "\\" in value or "\x00" in value:
        raise ValueError(f"Unsafe archive path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"Unsafe archive path: {value!r}")
    return path.as_posix()


def _safe_target(root: Path, relative: str) -> Path:
    relative = _safe_relative(relative)
    resolved_root = root.expanduser().resolve()
    target = resolved_root.joinpath(*PurePosixPath(relative).parts).resolve()
    try:
        target.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"Archive path escapes target root: {relative}") from exc
    return target


def _relative_to(root: Path, path: Path, field_name: str) -> str:
    try:
        return path.expanduser().resolve().relative_to(root.expanduser().resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"{field_name} must stay inside project root") from exc


def _resolved_project_path(project_root: Path, value: str, field_name: str) -> Path:
    candidate = Path(value).expanduser()
    resolved = candidate.resolve() if candidate.is_absolute() else (project_root / candidate).resolve()
    try:
        resolved.relative_to(project_root.resolve())
    except ValueError as exc:
        raise ValueError(f"{field_name} points outside project root") from exc
    return resolved


def _payload_file(source: Path, path: str, role: str, expected_sha256: str | None = None) -> PayloadFile:
    if not source.is_file() or source.is_symlink():
        raise FileNotFoundError(f"Required regular file is missing: {source}")
    relative = _safe_relative(path)
    current_sha = _sha256_path(source)
    if expected_sha256 and current_sha != expected_sha256:
        raise ValueError(f"Registered file hash mismatch: {relative}")
    return PayloadFile(source, relative, role, current_sha, source.stat().st_size)


def _tar_info(name: str, size: int, mode: int = 0o600) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = size
    info.mode = mode
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    return info


def _write_archive(
    output: Path,
    manifest: Mapping[str, Any],
    payload_files: Iterable[PayloadFile],
) -> Path:
    output = output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite archive: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    files = sorted(payload_files, key=lambda item: item.path)
    try:
        with tarfile.open(temporary, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
            manifest_bytes = _json_bytes(manifest)
            archive.addfile(_tar_info(MANIFEST_MEMBER, len(manifest_bytes)), io.BytesIO(manifest_bytes))
            for item in files:
                member_name = f"{PAYLOAD_PREFIX}/{item.path}"
                with item.source.open("rb") as handle:
                    archive.addfile(_tar_info(member_name, item.size_bytes), handle)
        os.replace(temporary, output)
        output.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def verify_archive(path: Path, *, expected_kind: str) -> dict[str, Any]:
    path = path.expanduser().resolve()
    with tarfile.open(path, mode="r:*") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)):
            raise ValueError("Archive contains duplicate member names")
        if MANIFEST_MEMBER not in names:
            raise ValueError("Archive manifest is missing")
        if any(not member.isfile() for member in members):
            raise ValueError("Archive may contain regular files only")
        manifest_handle = archive.extractfile(MANIFEST_MEMBER)
        if manifest_handle is None:
            raise ValueError("Archive manifest cannot be read")
        manifest = json.loads(manifest_handle.read().decode("utf-8"))
        if not isinstance(manifest, dict) or manifest.get("kind") != expected_kind:
            raise ValueError("Unexpected archive kind")
        expected_schema = {
            MODEL_BUNDLE_KIND: MODEL_BUNDLE_SCHEMA_VERSION,
            BACKUP_KIND: BACKUP_SCHEMA_VERSION,
        }.get(expected_kind)
        if expected_schema is None or manifest.get("schema_version") != expected_schema:
            raise ValueError("Unsupported archive schema version")
        files = manifest.get("files")
        if not isinstance(files, list) or not files:
            raise ValueError("Archive manifest has no file inventory")
        expected_members = {MANIFEST_MEMBER}
        seen_paths: set[str] = set()
        for row in files:
            if not isinstance(row, dict):
                raise ValueError("Invalid archive inventory row")
            relative = _safe_relative(str(row.get("path") or ""))
            if relative in seen_paths:
                raise ValueError("Archive inventory contains duplicate paths")
            seen_paths.add(relative)
            member_name = f"{PAYLOAD_PREFIX}/{relative}"
            expected_members.add(member_name)
            try:
                member = archive.getmember(member_name)
            except KeyError as exc:
                raise ValueError(f"Archive member is missing: {relative}") from exc
            if member.size != int(row.get("size_bytes") or -1):
                raise ValueError(f"Archive size mismatch: {relative}")
            handle = archive.extractfile(member)
            if handle is None or _sha256_stream(handle) != row.get("sha256"):
                raise ValueError(f"Archive hash mismatch: {relative}")
        if set(names) != expected_members:
            unexpected = sorted(set(names) ^ expected_members)
            raise ValueError(f"Archive inventory/member mismatch: {unexpected[:5]}")
    return manifest


def verify_model_bundle(path: Path) -> dict[str, Any]:
    manifest = verify_archive(path, expected_kind=MODEL_BUNDLE_KIND)
    package_id = str(manifest.get("package_id") or "")
    if not PACKAGE_ID_RE.fullmatch(package_id):
        raise ValueError("Model bundle has an invalid package ID")
    source_panel = manifest.get("source_panel")
    if not isinstance(source_panel, dict) or source_panel.get("included") is not False:
        raise ValueError("Model serving bundle must exclude the source panel")
    rows = manifest.get("files") or []
    paths = {str(row.get("path") or "") for row in rows if isinstance(row, dict)}
    if any(PurePosixPath(path).parts[0] == "00_Data" for path in paths):
        raise ValueError("Model serving bundle may not contain 00_Data files")
    roles = [str(row.get("role") or "") for row in rows if isinstance(row, dict)]
    for role in ("registry_registration", "registry_event", "registry_channel_pointer"):
        if roles.count(role) != 1:
            raise ValueError(f"Model bundle must contain exactly one {role}")
    model_names = {
        PurePosixPath(str(row["path"])).name
        for row in rows
        if isinstance(row, dict) and row.get("role") == "model_inventory"
    }
    missing = sorted(SERVING_RUNTIME_REQUIRED_FILES - model_names)
    if missing:
        raise ValueError(f"Model bundle is not serving-complete. Missing: {missing}")
    if not any(name.startswith("posterior_") and name.endswith(".nc") for name in model_names):
        raise ValueError("Model bundle is not serving-complete: no posterior NetCDF files")
    return manifest


def _assert_registration_content(registration: Mapping[str, Any]) -> None:
    expected = str(registration.get("registration_content_sha256") or "")
    immutable = dict(registration)
    for key in ("registered_at_utc", "registered_by", "reason", "registration_content_sha256"):
        immutable.pop(key, None)
    if not expected or _canonical_hash(immutable) != expected:
        raise ValueError("Registry registration metadata hash mismatch")


def collect_model_payload(
    project_root: Path,
    registry_root: Path,
    *,
    channel: str,
    expected_package_id: str,
) -> tuple[dict[str, Any], list[PayloadFile]]:
    project_root = project_root.expanduser().resolve()
    registry_root = registry_root.expanduser().resolve()
    if not PACKAGE_ID_RE.fullmatch(expected_package_id):
        raise ValueError("Invalid expected package ID")
    if not CHANNEL_RE.fullmatch(channel):
        raise ValueError("Invalid registry channel")
    registry_relative = _relative_to(project_root, registry_root, "registry_root")
    channel_path = registry_root / "channels" / f"{channel}.json"
    channel_pointer = _read_json(channel_path)
    if channel_pointer.get("channel") != channel:
        raise ValueError("Registry channel pointer has the wrong channel")
    if channel_pointer.get("package_id") != expected_package_id:
        raise ValueError("Registry channel does not point to the expected package")
    registration_path = registry_root / "registrations" / f"{expected_package_id}.json"
    registration = _read_json(registration_path)
    _assert_registration_content(registration)
    if registration.get("package_id") != expected_package_id:
        raise ValueError("Registration package ID mismatch")
    if channel_pointer.get("registration_content_sha256") != registration.get(
        "registration_content_sha256"
    ):
        raise ValueError("Channel pointer and registration hash differ")

    run_dir = _resolved_project_path(project_root, str(registration.get("run_dir") or ""), "run_dir")
    run_relative = _relative_to(project_root, run_dir, "run_dir")
    panel = registration.get("panel") or {}
    panel_path = _resolved_project_path(project_root, str(panel.get("path") or ""), "panel.path")
    if not panel_path.is_file() or _sha256_path(panel_path) != panel.get("sha256"):
        raise ValueError("Source panel is missing or differs from registered provenance")

    inventory = registration.get("inventory_sha256")
    if not isinstance(inventory, dict) or not inventory:
        raise ValueError("Registration has no serving inventory")
    missing = sorted(SERVING_RUNTIME_REQUIRED_FILES - set(inventory))
    if missing:
        raise ValueError(f"Registered package is not serving-complete. Missing: {missing}")
    if not any(name.startswith("posterior_") and name.endswith(".nc") for name in inventory):
        raise ValueError("Registered package is not serving-complete: no posterior NetCDF files")
    payload: list[PayloadFile] = []
    for filename, expected_sha in sorted(inventory.items()):
        safe_name = _safe_relative(str(filename))
        if len(PurePosixPath(safe_name).parts) != 1:
            raise ValueError("Registered inventory names must be package-local files")
        payload.append(
            _payload_file(
                run_dir / safe_name,
                f"{run_relative}/{safe_name}",
                "model_inventory",
                str(expected_sha),
            )
        )
    payload.append(
        _payload_file(
            registration_path,
            f"{registry_relative}/registrations/{expected_package_id}.json",
            "registry_registration",
        )
    )
    event_id = str(channel_pointer.get("event_id") or "")
    event_path = registry_root / "events" / f"{event_id}.json"
    event = _read_json(event_path)
    if (
        event.get("event_id") != event_id
        or event.get("channel") != channel
        or event.get("package_id") != expected_package_id
        or event.get("registration_content_sha256")
        != registration.get("registration_content_sha256")
    ):
        raise ValueError("Registry activation event is inconsistent with the channel pointer")
    payload.append(
        _payload_file(
            event_path,
            f"{registry_relative}/events/{event_id}.json",
            "registry_event",
        )
    )
    payload.append(
        _payload_file(
            channel_path,
            f"{registry_relative}/channels/{channel}.json",
            "registry_channel_pointer",
        )
    )
    if any(PurePosixPath(item.path).parts[0] == "00_Data" for item in payload):
        raise ValueError("A model serving bundle may not include files from 00_Data")

    manifest = {
        "schema_version": MODEL_BUNDLE_SCHEMA_VERSION,
        "kind": MODEL_BUNDLE_KIND,
        "created_at_utc": _utc_now(),
        "package_id": expected_package_id,
        "package_input_fingerprint": registration.get("package_input_fingerprint"),
        "registration_content_sha256": registration.get("registration_content_sha256"),
        "registry_channel": channel,
        "registry_event_id": event_id,
        "model_run_id": registration.get("model_run_id"),
        "source_panel": {
            "included": False,
            "sha256": panel.get("sha256"),
            "size_bytes": panel.get("size_bytes"),
        },
        "files": [item.manifest_row() for item in sorted(payload, key=lambda item: item.path)],
    }
    return manifest, payload


def package_model(
    project_root: Path,
    registry_root: Path,
    output: Path,
    *,
    channel: str,
    expected_package_id: str,
) -> dict[str, Any]:
    manifest, payload = collect_model_payload(
        project_root,
        registry_root,
        channel=channel,
        expected_package_id=expected_package_id,
    )
    archive = _write_archive(output, manifest, payload)
    verified = verify_model_bundle(archive)
    return {
        "status": "created_and_verified",
        "archive": str(archive),
        "archive_sha256": _sha256_path(archive),
        "package_id": verified["package_id"],
        "files_n": len(verified["files"]),
        "payload_size_bytes": sum(int(row["size_bytes"]) for row in verified["files"]),
        "source_panel_included": False,
    }


def install_model_bundle(bundle: Path, project_root: Path) -> dict[str, Any]:
    manifest = verify_model_bundle(bundle)
    project_root = project_root.expanduser().resolve()
    project_root.mkdir(parents=True, exist_ok=True)
    rows = list(manifest["files"])
    priority = {
        "model_inventory": 0,
        "registry_registration": 1,
        "registry_event": 2,
        "registry_channel_pointer": 3,
    }
    rows.sort(key=lambda row: (priority.get(str(row.get("role")), 99), str(row["path"])))
    installed = 0
    unchanged = 0
    with tarfile.open(bundle.expanduser().resolve(), mode="r:*") as archive:
        for row in rows:
            relative = _safe_relative(str(row["path"]))
            target = _safe_target(project_root, relative)
            if target.exists():
                if not target.is_file() or _sha256_path(target) != row["sha256"]:
                    raise FileExistsError(f"Refusing to replace different installed file: {target}")
                unchanged += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            member = archive.getmember(f"{PAYLOAD_PREFIX}/{relative}")
            handle = archive.extractfile(member)
            if handle is None:
                raise ValueError(f"Cannot read bundle member: {relative}")
            temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
            try:
                with temporary.open("xb") as destination:
                    shutil.copyfileobj(handle, destination, length=1024 * 1024)
                if _sha256_path(temporary) != row["sha256"]:
                    raise ValueError(f"Installed file hash mismatch: {relative}")
                temporary.chmod(0o600)
                os.replace(temporary, target)
                installed += 1
            finally:
                temporary.unlink(missing_ok=True)
    return {
        "status": "installed",
        "package_id": manifest["package_id"],
        "installed_files_n": installed,
        "unchanged_files_n": unchanged,
        "source_panel_installed": False,
    }


def _validated_domain(domain: str) -> str:
    if any(char.isspace() for char in domain):
        raise ValueError("Domain may not contain whitespace")
    parsed = urlsplit(f"https://{domain}")
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.port is not None
        or parsed.netloc != parsed.hostname
    ):
        raise ValueError("Domain must be a plain DNS name, without scheme or path")
    labels = parsed.hostname.split(".")
    if (
        len(parsed.hostname) > 253
        or len(labels) < 2
        or any(not DOMAIN_LABEL_RE.fullmatch(label) for label in labels)
    ):
        raise ValueError("Domain must be a valid multi-label DNS name")
    return parsed.hostname.lower()


def _absolute_path(value: Path, field_name: str) -> Path:
    path = value.expanduser()
    if not path.is_absolute() or any(char.isspace() for char in str(path)):
        raise ValueError(f"{field_name} must be one absolute path")
    return path


def render_deployment(
    output_dir: Path,
    *,
    domain: str,
    project_root: Path,
    venv_root: Path,
    data_root: Path,
    backup_root: Path,
    package_id: str,
    channel: str = "preprod",
    service_user: str = "x5mmm",
    backend_port: int = 8765,
    min_free_gb: float = 20.0,
    backup_keep: int = 7,
    auth_file: Path | None = None,
    tls_certificate: Path | None = None,
    tls_certificate_key: Path | None = None,
) -> dict[str, Any]:
    domain = _validated_domain(domain)
    if not PACKAGE_ID_RE.fullmatch(package_id):
        raise ValueError("Invalid package ID")
    if not CHANNEL_RE.fullmatch(channel):
        raise ValueError("Invalid registry channel")
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", service_user):
        raise ValueError("Invalid service user")
    if not 1 <= backend_port <= 65535 or min_free_gb <= 0 or backup_keep <= 0:
        raise ValueError("Invalid port, disk threshold or backup retention")
    project_root = _absolute_path(project_root, "project_root")
    venv_root = _absolute_path(venv_root, "venv_root")
    data_root = _absolute_path(data_root, "data_root")
    backup_root = _absolute_path(backup_root, "backup_root")
    auth_file = _absolute_path(
        auth_file or Path("/etc/nginx/x5-mmm-research.htpasswd"),
        "auth_file",
    )
    tls_certificate = _absolute_path(
        tls_certificate or Path(f"/etc/letsencrypt/live/{domain}/fullchain.pem"),
        "tls_certificate",
    )
    tls_certificate_key = _absolute_path(
        tls_certificate_key or Path(f"/etc/letsencrypt/live/{domain}/privkey.pem"),
        "tls_certificate_key",
    )
    python = venv_root / "bin" / "python"
    deployment_tool = project_root / "04_Web_app" / "deployment" / "research_pilot.py"
    backend_script = project_root / "04_Web_app" / "backend_runtime.py"
    backend_config_path = Path("/etc/x5-mmm/research_backend.json")
    public_origin = f"https://{domain}"
    backend_config = {
        "schema_version": "1.1.0",
        "server": {
            "deployment_profile": "research_pilot",
            "host": "127.0.0.1",
            "port": backend_port,
            "public_base_url": public_origin,
            "access_control_mode": "reverse_proxy_basic_auth",
            "allowed_origins": [public_origin],
        },
        "paths": {
            "state_root": str(data_root / "state"),
            "runtime_root": str(data_root / "runtime"),
            "artifact_root": str(data_root / "artifacts"),
            "registry_root": str(project_root / "03_Outputs/01_PyMC_outputs/00_Model_registry"),
            "optimizer_policy_path": str(
                project_root / "02_Code/02_Budget_optimizer/optimizer_decision_policy_v3.yaml"
            ),
            "business_policy_path": str(
                project_root / "02_Code/02_Budget_optimizer/business_threshold_policy_v1.yaml"
            ),
        },
        "model": {
            "registry_channel": channel,
            "expected_package_id": package_id,
            "verification_mode": "serving_bundle",
        },
        "worker": {
            "python_executable": str(python),
            "timeout_seconds": 7200,
            "max_workers": 1,
            "max_upload_mb": 50,
        },
        "retention": {"days": 30},
    }
    backend_command = (
        f"{python} -B {backend_script} --config {backend_config_path} "
        f"--project-root {project_root}"
    )
    service = f"""[Unit]
Description=X5 MMM research-pilot backend
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={service_user}
Group={service_user}
WorkingDirectory={project_root}
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-/etc/x5-mmm/backend.env
ExecStartPre={backend_command} --check-only
ExecStart={backend_command}
Restart=on-failure
RestartSec=5
TimeoutStopSec=45
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths={data_root}

[Install]
WantedBy=multi-user.target
"""
    retention_service = f"""[Unit]
Description=X5 MMM terminal-resource retention
After=x5-mmm-backend.service

[Service]
Type=oneshot
WorkingDirectory={project_root}
ExecStart={python} -B {deployment_tool} retention --config {backend_config_path} --project-root {project_root} --service-name x5-mmm-backend --run-as-user {service_user}
UMask=0077
"""
    retention_timer = """[Unit]
Description=Run X5 MMM retention daily

[Timer]
OnCalendar=*-*-* 03:15:00
Persistent=true
RandomizedDelaySec=600

[Install]
WantedBy=timers.target
"""
    health_service = f"""[Unit]
Description=X5 MMM research-pilot health and disk check
After=x5-mmm-backend.service

[Service]
Type=oneshot
User={service_user}
Group={service_user}
WorkingDirectory={project_root}
ExecStart={python} -B {deployment_tool} health --config {backend_config_path} --min-free-gb {min_free_gb:g}
NoNewPrivileges=true
ProtectHome=true
ProtectSystem=strict
"""
    health_timer = """[Unit]
Description=Check X5 MMM health every five minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
AccuracySec=30s

[Install]
WantedBy=timers.target
"""
    backup_service = f"""[Unit]
Description=X5 MMM quiesced runtime backup
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory={project_root}
ExecStart={python} -B {deployment_tool} backup --config {backend_config_path} --backup-root {backup_root} --service-name x5-mmm-backend --keep {backup_keep}
UMask=0077
"""
    backup_timer = """[Unit]
Description=Back up X5 MMM runtime state nightly

[Timer]
OnCalendar=*-*-* 02:15:00
Persistent=true
RandomizedDelaySec=600

[Install]
WantedBy=timers.target
"""
    proxy_locations = f"""    location /api/ {{
        proxy_pass http://127.0.0.1:{backend_port};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 7500s;
        proxy_send_timeout 7500s;
        proxy_buffering off;
    }}

    location = /health {{ proxy_pass http://127.0.0.1:{backend_port}; }}
    location = /ready {{ proxy_pass http://127.0.0.1:{backend_port}; }}
"""
    nginx = f"""server {{
    listen 80;
    server_name {domain};
    return 301 https://$host$request_uri;
}}

server {{
    listen 443 ssl http2;
    server_name {domain};

    ssl_certificate {tls_certificate};
    ssl_certificate_key {tls_certificate_key};
    auth_basic "X5 MMM research pilot";
    auth_basic_user_file {auth_file};
    client_max_body_size 50m;

    root {project_root}/04_Web_app/frontend/dist;
    index index.html;

{proxy_locations}
    location / {{
        try_files $uri $uri/ /index.html;
    }}
}}
"""
    install_notes = f"""# Generated Research Pilot Install Order

1. Create the locked Linux user `{service_user}`. Keep `{project_root}` and `{venv_root}` readable/executable by it; own `{data_root}` recursively as `{service_user}:{service_user}` with mode `0700`; keep `{backup_root}` root-owned with mode `0700`.
2. Checkout the approved Git commit into `{project_root}`.
3. Create Python 3.11+ venv at `{venv_root}` and install `requirements-runtime-v1.txt`.
4. Use Node 22, run `npm ci`, and build frontend with `VITE_RESULT_PROVIDER=http` and empty `VITE_API_BASE_URL`.
5. Make `03_Outputs` writable by `{service_user}` and install the separately transferred model bundle as that user with `research_pilot.py install-model`.
6. Create `/etc/x5-mmm` as `root:{service_user}` mode `0750`; copy `research_backend.json` to `{backend_config_path}` as `root:{service_user}` mode `0640` so the unprivileged backend can read it.
7. Create `{auth_file}` with `htpasswd`; credentials are not generated or stored here.
8. Install the Nginx and systemd files, then run daemon-reload and enable the service/timers.
9. Run backend `--check-only`, `research_pilot.py health`, and one real campaign acceptance test.

The Python service remains on `127.0.0.1:{backend_port}`. Only Nginx is internet-facing.
"""
    generated: dict[str, bytes] = {
        "research_backend.json": _json_bytes(backend_config),
        "frontend.env.production": b"VITE_RESULT_PROVIDER=http\nVITE_API_BASE_URL=\n",
        "x5-mmm-backend.service": service.encode(),
        "x5-mmm-retention.service": retention_service.encode(),
        "x5-mmm-retention.timer": retention_timer.encode(),
        "x5-mmm-health.service": health_service.encode(),
        "x5-mmm-health.timer": health_timer.encode(),
        "x5-mmm-backup.service": backup_service.encode(),
        "x5-mmm-backup.timer": backup_timer.encode(),
        "x5-mmm-research.nginx.conf": nginx.encode(),
        "INSTALL_ORDER.md": install_notes.encode(),
    }
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise FileExistsError("Render output directory must be empty")
    for name, payload in generated.items():
        _atomic_write(output_dir / name, payload, mode=0o600)
    render_manifest = {
        "schema_version": "1.0.0",
        "generated_at_utc": _utc_now(),
        "domain": domain,
        "package_id": package_id,
        "model_verification_mode": "serving_bundle",
        "source_panel_required": False,
        "secrets_included": False,
        "files": [
            {
                "path": name,
                "sha256": _sha256_path(output_dir / name),
                "size_bytes": (output_dir / name).stat().st_size,
            }
            for name in sorted(generated)
        ],
    }
    _atomic_write(output_dir / "render_manifest.json", _json_bytes(render_manifest))
    return {"status": "rendered", "output_dir": str(output_dir), **render_manifest}


def _config_runtime_roots(config_path: Path) -> tuple[dict[str, Any], dict[str, Path]]:
    config = _read_json(config_path.expanduser().resolve())
    paths = config.get("paths") or {}
    roots: dict[str, Path] = {}
    for logical, key in (
        ("state", "state_root"),
        ("runtime", "runtime_root"),
        ("artifacts", "artifact_root"),
    ):
        value = Path(str(paths.get(key) or "")).expanduser()
        if not value.is_absolute():
            raise ValueError(f"Deployment backup requires absolute {key}")
        roots[logical] = value.resolve()
    return config, roots


def _status_code(payload: Mapping[str, Any]) -> str:
    status = payload.get("status")
    if isinstance(status, dict):
        return str(status.get("code") or "")
    return str(status or "")


def assert_runtime_idle(state_root: Path) -> dict[str, Any]:
    active: list[dict[str, str]] = []
    patterns = {
        "uploads": ("uploads/*/upload.json", "upload_id"),
        "validations": ("validations/*/validation.json", "validation_id"),
        "jobs": ("jobs/*/job.json", "job_id"),
    }
    for family, (pattern, id_field) in patterns.items():
        for path in sorted(state_root.glob(pattern)):
            payload = _read_json(path)
            code = _status_code(payload)
            if code not in TERMINAL_STATUSES[family]:
                active.append(
                    {
                        "family": family,
                        "resource_id": str(payload.get(id_field) or path.parent.name),
                        "status": code or "unknown",
                    }
                )
    if active:
        raise RuntimeError(f"Runtime backup refused: non-terminal resources exist: {active[:5]}")
    return {"status": "idle", "active_resources_n": 0}


def _collect_tree_payload(roots: Mapping[str, Path]) -> list[PayloadFile]:
    payload: list[PayloadFile] = []
    for logical, root in sorted(roots.items()):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"Backup source may not contain symlinks: {path}")
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            payload.append(_payload_file(path, f"{logical}/{relative}", f"runtime_{logical}"))
    return payload


def create_runtime_backup(
    config_path: Path,
    backup_root: Path,
    *,
    keep: int = 7,
) -> dict[str, Any]:
    if keep <= 0:
        raise ValueError("Backup retention must be positive")
    config, roots = _config_runtime_roots(config_path)
    assert_runtime_idle(roots["state"])
    payload = _collect_tree_payload(roots)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = backup_root.expanduser().resolve()
    backup_root.mkdir(parents=True, exist_ok=True)
    output = backup_root / f"x5-mmm-runtime-{stamp}.tar.gz"
    manifest = {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "kind": BACKUP_KIND,
        "created_at_utc": _utc_now(),
        "package_id": ((config.get("model") or {}).get("expected_package_id")),
        "registry_channel": ((config.get("model") or {}).get("registry_channel")),
        "model_files_included": False,
        "source_data_included": False,
        "files": [item.manifest_row() for item in sorted(payload, key=lambda item: item.path)],
    }
    if not payload:
        # An empty, freshly installed runtime is still a valid backup.
        marker_root = Path(tempfile.mkdtemp(prefix="x5-mmm-empty-backup-"))
        try:
            marker = marker_root / "EMPTY_RUNTIME"
            marker.write_text("No runtime files existed at backup time.\n", encoding="utf-8")
            payload = [_payload_file(marker, "state/EMPTY_RUNTIME", "runtime_state")]
            manifest["files"] = [payload[0].manifest_row()]
            _write_archive(output, manifest, payload)
        finally:
            shutil.rmtree(marker_root)
    else:
        _write_archive(output, manifest, payload)
    verified = verify_archive(output, expected_kind=BACKUP_KIND)
    backups = sorted(backup_root.glob("x5-mmm-runtime-*.tar.gz"), key=lambda path: path.stat().st_mtime)
    removed: list[str] = []
    for stale in backups[:-keep]:
        stale.unlink()
        removed.append(stale.name)
    return {
        "status": "created_and_verified",
        "archive": str(output),
        "archive_sha256": _sha256_path(output),
        "files_n": len(verified["files"]),
        "removed_old_backups": removed,
    }


def backup_with_optional_service_stop(
    config_path: Path,
    backup_root: Path,
    *,
    keep: int,
    service_name: str | None,
) -> dict[str, Any]:
    _, roots = _config_runtime_roots(config_path)
    assert_runtime_idle(roots["state"])
    was_active = False
    if service_name:
        if not re.fullmatch(r"[a-zA-Z0-9_.@-]+", service_name):
            raise ValueError("Invalid systemd service name")
        was_active = subprocess.run(
            ["systemctl", "is-active", "--quiet", service_name],
            check=False,
        ).returncode == 0
        if was_active:
            subprocess.run(["systemctl", "stop", service_name], check=True)
    try:
        assert_runtime_idle(roots["state"])
        result = create_runtime_backup(config_path, backup_root, keep=keep)
        result["service_was_quiesced"] = was_active
        return result
    finally:
        if was_active:
            subprocess.run(["systemctl", "start", service_name], check=True)


def apply_retention_with_service_stop(
    config_path: Path,
    project_root: Path,
    *,
    service_name: str,
    run_as_user: str,
) -> dict[str, Any]:
    if not re.fullmatch(r"[a-zA-Z0-9_.@-]+", service_name):
        raise ValueError("Invalid systemd service name")
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", run_as_user):
        raise ValueError("Invalid retention service user")
    project_root = project_root.expanduser().resolve()
    config_path = config_path.expanduser().resolve()
    _, roots = _config_runtime_roots(config_path)
    assert_runtime_idle(roots["state"])
    was_active = subprocess.run(
        ["systemctl", "is-active", "--quiet", service_name],
        check=False,
    ).returncode == 0
    if was_active:
        subprocess.run(["systemctl", "stop", service_name], check=True)
    try:
        assert_runtime_idle(roots["state"])
        runuser = shutil.which("runuser")
        if not runuser:
            raise RuntimeError("runuser is required for quiesced retention")
        command = [
            runuser,
            "-u",
            run_as_user,
            "--",
            sys.executable,
            "-B",
            str(project_root / "04_Web_app/backend_runtime.py"),
            "--config",
            str(config_path),
            "--project-root",
            str(project_root),
            "--apply-retention",
        ]
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        payload = json.loads(completed.stdout)
        if not isinstance(payload, dict) or payload.get("status") != "applied":
            raise RuntimeError("Retention command returned an unexpected result")
        return {**payload, "service_was_quiesced": was_active}
    finally:
        if was_active:
            subprocess.run(["systemctl", "start", service_name], check=True)


def restore_runtime_backup(backup: Path, target_root: Path) -> dict[str, Any]:
    manifest = verify_archive(backup, expected_kind=BACKUP_KIND)
    target_root = target_root.expanduser().resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    if any(target_root.iterdir()):
        raise FileExistsError("Restore target must be empty")
    restored = 0
    with tarfile.open(backup.expanduser().resolve(), mode="r:*") as archive:
        for row in manifest["files"]:
            relative = _safe_relative(str(row["path"]))
            if relative == "state/EMPTY_RUNTIME":
                continue
            target = _safe_target(target_root, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            handle = archive.extractfile(f"{PAYLOAD_PREFIX}/{relative}")
            if handle is None:
                raise ValueError(f"Cannot read backup member: {relative}")
            with target.open("xb") as destination:
                shutil.copyfileobj(handle, destination, length=1024 * 1024)
            if _sha256_path(target) != row["sha256"]:
                raise ValueError(f"Restored file hash mismatch: {relative}")
            target.chmod(0o600)
            restored += 1
    return {"status": "restored", "target_root": str(target_root), "restored_files_n": restored}


def _http_json(url: str, timeout: float = 10.0) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP health check returned {response.status}")
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Health endpoint returned a non-object payload")
    return payload


def health_check(config_path: Path, *, min_free_gb: float = 20.0) -> dict[str, Any]:
    if min_free_gb <= 0:
        raise ValueError("min_free_gb must be positive")
    config, roots = _config_runtime_roots(config_path)
    server = config.get("server") or {}
    host = str(server.get("host") or "127.0.0.1")
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("Health check refuses a non-loopback Python backend")
    port = int(server.get("port") or 8765)
    base_url = f"http://{host}:{port}"
    health = _http_json(f"{base_url}/health")
    ready = _http_json(f"{base_url}/ready")
    disk: dict[str, Any] = {}
    disk_ok = True
    for logical, root in roots.items():
        candidate = root
        while not candidate.exists() and candidate != candidate.parent:
            candidate = candidate.parent
        usage = shutil.disk_usage(candidate)
        free_gb = usage.free / (1024**3)
        ok = free_gb >= min_free_gb
        disk_ok = disk_ok and ok
        disk[logical] = {"free_gb": round(free_gb, 2), "threshold_gb": min_free_gb, "ok": ok}
    ready_flag = bool(ready.get("ready", ready.get("status") == "ready"))
    health_flag = health.get("status") in {"ok", "healthy", "ready"}
    if not (health_flag and ready_flag and disk_ok):
        raise RuntimeError(
            json.dumps(
                {"health": health, "ready": ready, "disk": disk},
                ensure_ascii=False,
            )
        )
    return {"status": "healthy", "base_url": base_url, "health": health, "ready": ready, "disk": disk}


def _print_result(payload: Mapping[str, Any]) -> None:
    print(json.dumps(dict(payload), ensure_ascii=False, indent=2))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    package = sub.add_parser("package-model", help="Build a panel-free serving-model archive")
    package.add_argument("--project-root", required=True, type=Path)
    package.add_argument("--registry-root", required=True, type=Path)
    package.add_argument("--channel", default="preprod")
    package.add_argument("--expected-package-id", required=True)
    package.add_argument("--output", required=True, type=Path)

    verify_model = sub.add_parser("verify-model-bundle")
    verify_model.add_argument("--bundle", required=True, type=Path)

    install_model = sub.add_parser("install-model")
    install_model.add_argument("--bundle", required=True, type=Path)
    install_model.add_argument("--project-root", required=True, type=Path)

    render = sub.add_parser("render", help="Render Nginx, systemd and backend config")
    render.add_argument("--output-dir", required=True, type=Path)
    render.add_argument("--domain", required=True)
    render.add_argument("--project-root", type=Path, default=Path("/opt/x5-mmm/app"))
    render.add_argument("--venv-root", type=Path, default=Path("/opt/x5-mmm/venv"))
    render.add_argument("--data-root", type=Path, default=Path("/var/lib/x5-mmm"))
    render.add_argument("--backup-root", type=Path, default=Path("/var/backups/x5-mmm"))
    render.add_argument("--package-id", required=True)
    render.add_argument("--channel", default="preprod")
    render.add_argument("--service-user", default="x5mmm")
    render.add_argument("--backend-port", type=int, default=8765)
    render.add_argument("--min-free-gb", type=float, default=20.0)
    render.add_argument("--backup-keep", type=int, default=7)
    render.add_argument("--auth-file", type=Path)
    render.add_argument("--tls-certificate", type=Path)
    render.add_argument("--tls-certificate-key", type=Path)

    health = sub.add_parser("health")
    health.add_argument("--config", required=True, type=Path)
    health.add_argument("--min-free-gb", type=float, default=20.0)

    backup = sub.add_parser("backup")
    backup.add_argument("--config", required=True, type=Path)
    backup.add_argument("--backup-root", required=True, type=Path)
    backup.add_argument("--keep", type=int, default=7)
    backup.add_argument("--service-name", default=None)

    retention = sub.add_parser("retention")
    retention.add_argument("--config", required=True, type=Path)
    retention.add_argument("--project-root", required=True, type=Path)
    retention.add_argument("--service-name", required=True)
    retention.add_argument("--run-as-user", required=True)

    verify_backup = sub.add_parser("verify-backup")
    verify_backup.add_argument("--backup", required=True, type=Path)

    restore = sub.add_parser("restore-backup")
    restore.add_argument("--backup", required=True, type=Path)
    restore.add_argument("--target-root", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "package-model":
            result = package_model(
                args.project_root,
                args.registry_root,
                args.output,
                channel=args.channel,
                expected_package_id=args.expected_package_id,
            )
        elif args.command == "verify-model-bundle":
            manifest = verify_model_bundle(args.bundle)
            result = {
                "status": "verified",
                "package_id": manifest["package_id"],
                "files_n": len(manifest["files"]),
                "source_panel_included": bool(manifest["source_panel"]["included"]),
            }
        elif args.command == "install-model":
            result = install_model_bundle(args.bundle, args.project_root)
        elif args.command == "render":
            result = render_deployment(
                args.output_dir,
                domain=args.domain,
                project_root=args.project_root,
                venv_root=args.venv_root,
                data_root=args.data_root,
                backup_root=args.backup_root,
                package_id=args.package_id,
                channel=args.channel,
                service_user=args.service_user,
                backend_port=args.backend_port,
                min_free_gb=args.min_free_gb,
                backup_keep=args.backup_keep,
                auth_file=args.auth_file,
                tls_certificate=args.tls_certificate,
                tls_certificate_key=args.tls_certificate_key,
            )
        elif args.command == "health":
            result = health_check(args.config, min_free_gb=args.min_free_gb)
        elif args.command == "backup":
            result = backup_with_optional_service_stop(
                args.config,
                args.backup_root,
                keep=args.keep,
                service_name=args.service_name,
            )
        elif args.command == "retention":
            result = apply_retention_with_service_stop(
                args.config,
                args.project_root,
                service_name=args.service_name,
                run_as_user=args.run_as_user,
            )
        elif args.command == "verify-backup":
            manifest = verify_archive(args.backup, expected_kind=BACKUP_KIND)
            result = {"status": "verified", "files_n": len(manifest["files"])}
        elif args.command == "restore-backup":
            result = restore_runtime_backup(args.backup, args.target_root)
        else:  # pragma: no cover - argparse prevents this branch
            raise ValueError(f"Unknown command: {args.command}")
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
        tarfile.TarError,
        urllib.error.URLError,
    ) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    _print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
