"""Build a package-bound historical media-budget aggregate from a model panel.

The source panel is resolved through immutable model-registry metadata. The
builder reads only the date, geography and approved spend columns, never trains
or scores the MMM, and writes a small deterministic Parquet plus a JSON serving
manifest. The manifest repeats the 220 aggregate rows so the web runtime does
not need a Parquet engine or the full source panel.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import resource
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ARTIFACT_VERSION = "historical_geo_budget_v1"
ARTIFACT_SCHEMA_VERSION = "1.0.0"
PARQUET_FILENAME = "historical_geo_budget_v1.parquet"
METADATA_FILENAME = "historical_geo_budget_v1.metadata.json"
BUILD_CARD_FILENAME = "historical_geo_budget_v1.build.json"
PACKAGE_ARTIFACTS_MANIFEST_FILENAME = "package_artifacts_manifest_v1.json"
DEFAULT_BATCH_SIZE = 65_536
PACKAGE_ID_RE = re.compile(r"^pkg_[0-9a-f]{16}_[0-9a-f]{16}$")


class HistoricalGeoBudgetError(ValueError):
    """Raised when source, policy, reconciliation or artifact evidence is invalid."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _registry_canonical_sha256(value: Any) -> str:
    """Match the canonical hash format frozen by mmm_core.model_registry."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HistoricalGeoBudgetError(f"Required JSON artifact is missing: {path.name}") from exc
    if not isinstance(payload, dict):
        raise HistoricalGeoBudgetError(f"JSON artifact must contain an object: {path.name}")
    return payload


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalGeoBudgetError(f"{field} must be a non-empty string")
    return value.strip()


def _registration_content_sha256(registration: Mapping[str, Any]) -> str:
    immutable = dict(registration)
    for key in (
        "registered_at_utc",
        "registered_by",
        "reason",
        "registration_content_sha256",
    ):
        immutable.pop(key, None)
    return _registry_canonical_sha256(immutable)


@dataclass(frozen=True)
class SpendColumnsPolicy:
    schema_version: str
    spend_columns_version: str
    date_column: str
    geo_column: str
    spend_columns: tuple[str, ...]
    forbidden_overlaps: tuple[tuple[str, tuple[str, ...]], ...]
    null_policy: str
    negative_policy: str
    infinite_policy: str
    config_sha256: str

    @property
    def projected_columns(self) -> tuple[str, ...]:
        return (self.date_column, self.geo_column, *self.spend_columns)


def load_spend_columns_policy(path: Path) -> SpendColumnsPolicy:
    payload = _read_json(path)
    if payload.get("schema_version") != "1.0.0":
        raise HistoricalGeoBudgetError("Unsupported spend-columns policy schema")
    raw_columns = payload.get("spend_columns")
    if not isinstance(raw_columns, list) or not raw_columns:
        raise HistoricalGeoBudgetError("spend_columns must be a non-empty array")
    columns = tuple(_required_text(value, "spend_columns[]") for value in raw_columns)
    if len(columns) != len(set(columns)):
        raise HistoricalGeoBudgetError("spend_columns contains duplicates")
    overlaps: list[tuple[str, tuple[str, ...]]] = []
    for index, raw in enumerate(payload.get("forbidden_overlaps") or []):
        if not isinstance(raw, Mapping):
            raise HistoricalGeoBudgetError(f"forbidden_overlaps[{index}] must be an object")
        aggregate = _required_text(
            raw.get("aggregate_column"),
            f"forbidden_overlaps[{index}].aggregate_column",
        )
        components_raw = raw.get("component_columns")
        if not isinstance(components_raw, list) or not components_raw:
            raise HistoricalGeoBudgetError(
                f"forbidden_overlaps[{index}].component_columns must be non-empty"
            )
        components = tuple(
            _required_text(value, f"forbidden_overlaps[{index}].component_columns[]")
            for value in components_raw
        )
        overlaps.append((aggregate, components))
        if aggregate in columns and any(component in columns for component in components):
            raise HistoricalGeoBudgetError(
                f"Aggregate spend column {aggregate} overlaps selected component columns"
            )
    policies = {
        "null_policy": payload.get("null_policy"),
        "negative_policy": payload.get("negative_policy"),
        "infinite_policy": payload.get("infinite_policy"),
    }
    if set(policies.values()) != {"fail_closed"}:
        raise HistoricalGeoBudgetError("Spend null/negative/infinite policies must fail closed")
    return SpendColumnsPolicy(
        schema_version="1.0.0",
        spend_columns_version=_required_text(
            payload.get("spend_columns_version"), "spend_columns_version"
        ),
        date_column=_required_text(payload.get("date_column"), "date_column"),
        geo_column=_required_text(payload.get("geo_column"), "geo_column"),
        spend_columns=columns,
        forbidden_overlaps=tuple(overlaps),
        null_policy="fail_closed",
        negative_policy="fail_closed",
        infinite_policy="fail_closed",
        config_sha256=sha256_file(path),
    )


@dataclass(frozen=True)
class RegistryPackageIdentity:
    package_id: str
    package_input_fingerprint: str
    model_run_id: str
    panel_recorded_path: str
    panel_sha256: str
    panel_size_bytes: int
    registration_content_sha256: str


def load_registry_package_identity(
    registry_root: Path,
    package_id: str,
) -> RegistryPackageIdentity:
    if not PACKAGE_ID_RE.fullmatch(package_id):
        raise HistoricalGeoBudgetError("Package ID is invalid")
    registration = _read_json(
        registry_root.expanduser().resolve()
        / "registrations"
        / f"{package_id}.json"
    )
    if registration.get("package_id") != package_id:
        raise HistoricalGeoBudgetError("Registry package ID does not match the request")
    expected_registration_sha = _required_text(
        registration.get("registration_content_sha256"),
        "registration_content_sha256",
    )
    if _registration_content_sha256(registration) != expected_registration_sha:
        raise HistoricalGeoBudgetError("Registry registration content hash is invalid")
    panel = registration.get("panel")
    if not isinstance(panel, Mapping):
        raise HistoricalGeoBudgetError("Registry registration has no source-panel record")
    panel_size = panel.get("size_bytes")
    if isinstance(panel_size, bool) or not isinstance(panel_size, int) or panel_size <= 0:
        raise HistoricalGeoBudgetError("Registered source-panel size is invalid")
    return RegistryPackageIdentity(
        package_id=package_id,
        package_input_fingerprint=_required_text(
            registration.get("package_input_fingerprint"),
            "package_input_fingerprint",
        ),
        model_run_id=_required_text(registration.get("model_run_id"), "model_run_id"),
        panel_recorded_path=_required_text(panel.get("path"), "panel.path"),
        panel_sha256=_required_text(panel.get("sha256"), "panel.sha256"),
        panel_size_bytes=panel_size,
        registration_content_sha256=expected_registration_sha,
    )


def resolve_registered_panel(
    identity: RegistryPackageIdentity,
    *,
    project_root: Path,
) -> Path:
    raw_path = Path(identity.panel_recorded_path).expanduser()
    panel_path = (
        raw_path if raw_path.is_absolute() else project_root.expanduser().resolve() / raw_path
    ).resolve()
    if not panel_path.is_file():
        raise HistoricalGeoBudgetError("Registered source panel is unavailable")
    if panel_path.stat().st_size != identity.panel_size_bytes:
        raise HistoricalGeoBudgetError("Registered source-panel size has changed")
    if sha256_file(panel_path) != identity.panel_sha256:
        raise HistoricalGeoBudgetError("Registered source-panel hash has changed")
    return panel_path


@dataclass(frozen=True)
class AggregationResult:
    rows: tuple[dict[str, Any], ...]
    source_rows_n: int
    source_columns_n: int
    source_row_groups_n: int
    period_start: str
    period_end: str
    geographies_n: int
    total_budget_rub: float
    selected_column_totals_rub: dict[str, float]
    active_rows_n: int
    zero_spend_rows_n: int


def _as_date(value: Any, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise HistoricalGeoBudgetError(f"{field} contains a non-date value")


def aggregate_panel(
    panel_path: Path,
    policy: SpendColumnsPolicy,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> AggregationResult:
    if batch_size <= 0:
        raise HistoricalGeoBudgetError("batch_size must be positive")
    try:
        import numpy as np
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise HistoricalGeoBudgetError(
            "Historical geo-budget build requires numpy and pyarrow"
        ) from exc

    parquet = pq.ParquetFile(panel_path)
    names = set(parquet.schema_arrow.names)
    missing = sorted(set(policy.projected_columns) - names)
    if missing:
        raise HistoricalGeoBudgetError(f"Source panel is missing required columns: {missing}")
    for column in policy.spend_columns:
        column_type = parquet.schema_arrow.field(column).type
        if not (
            pa.types.is_integer(column_type)
            or pa.types.is_floating(column_type)
            or pa.types.is_decimal(column_type)
        ):
            raise HistoricalGeoBudgetError(f"Spend column is not numeric: {column}")

    geo_budget_parts: dict[str, list[float]] = defaultdict(list)
    geo_source_rows: dict[str, int] = defaultdict(int)
    geo_active_rows: dict[str, int] = defaultdict(int)
    geo_active_dates: dict[str, set[date]] = defaultdict(set)
    column_total_parts: dict[str, list[float]] = defaultdict(list)
    period_start: date | None = None
    period_end: date | None = None
    rows_seen = 0
    active_rows_n = 0
    zero_spend_rows_n = 0

    for batch in parquet.iter_batches(
        batch_size=batch_size,
        columns=list(policy.projected_columns),
        use_threads=False,
    ):
        rows_seen += batch.num_rows
        by_name = {name: batch.column(index) for index, name in enumerate(batch.schema.names)}
        date_values = by_name[policy.date_column].to_pylist()
        geo_values = by_name[policy.geo_column].to_pylist()
        if by_name[policy.date_column].null_count or by_name[policy.geo_column].null_count:
            raise HistoricalGeoBudgetError("Date and geography columns cannot contain nulls")
        spend_arrays = []
        for column in policy.spend_columns:
            values = by_name[column]
            if values.null_count:
                raise HistoricalGeoBudgetError(f"Spend column contains nulls: {column}")
            array = np.asarray(values.to_numpy(zero_copy_only=False), dtype=np.float64)
            if not np.isfinite(array).all():
                raise HistoricalGeoBudgetError(
                    f"Spend column contains NaN or infinite values: {column}"
                )
            if (array < 0).any():
                raise HistoricalGeoBudgetError(f"Spend column contains negative values: {column}")
            spend_arrays.append(array)
            column_total_parts[column].append(math.fsum(array.tolist()))
        matrix = np.column_stack(spend_arrays)
        row_spend = matrix.sum(axis=1, dtype=np.float64)
        if not np.isfinite(row_spend).all() or (row_spend < 0).any():
            raise HistoricalGeoBudgetError("Row media spend is invalid after aggregation")

        batch_geo_parts: dict[str, list[float]] = defaultdict(list)
        for raw_geo, raw_date, raw_spend in zip(geo_values, date_values, row_spend):
            geo = " ".join(str(raw_geo or "").strip().split())
            if not geo:
                raise HistoricalGeoBudgetError("Source panel contains a blank geography")
            observed_date = _as_date(raw_date, policy.date_column)
            period_start = observed_date if period_start is None else min(period_start, observed_date)
            period_end = observed_date if period_end is None else max(period_end, observed_date)
            spend = float(raw_spend)
            geo_source_rows[geo] += 1
            batch_geo_parts[geo].append(spend)
            if spend > 0:
                geo_active_rows[geo] += 1
                geo_active_dates[geo].add(observed_date)
                active_rows_n += 1
            else:
                zero_spend_rows_n += 1
        for geo, values in batch_geo_parts.items():
            geo_budget_parts[geo].append(math.fsum(values))

    if rows_seen != parquet.metadata.num_rows:
        raise HistoricalGeoBudgetError("Projected source-row count does not match Parquet metadata")
    if period_start is None or period_end is None or not geo_source_rows:
        raise HistoricalGeoBudgetError("Source panel is empty")
    geo_totals = {
        geo: math.fsum(parts) for geo, parts in sorted(geo_budget_parts.items())
    }
    total_budget = math.fsum(geo_totals.values())
    column_totals = {
        column: math.fsum(column_total_parts[column])
        for column in policy.spend_columns
    }
    selected_columns_total = math.fsum(column_totals.values())
    tolerance = max(0.01, abs(selected_columns_total) * 1e-12)
    if abs(total_budget - selected_columns_total) > tolerance:
        raise HistoricalGeoBudgetError("Global selected-spend reconciliation failed")

    rows = tuple(
        {
            "geo_model_name": geo,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "historical_total_budget_rub": float(geo_totals[geo]),
            "active_days_n": len(geo_active_dates[geo]),
            "active_rows_n": int(geo_active_rows[geo]),
            "budget_share": (
                float(geo_totals[geo] / total_budget) if total_budget > 0 else 0.0
            ),
            "source_rows_n": int(geo_source_rows[geo]),
            "artifact_version": ARTIFACT_VERSION,
            "source_panel_sha256": "",
            "spend_columns_version": policy.spend_columns_version,
        }
        for geo in sorted(geo_totals)
    )
    share_total = math.fsum(float(row["budget_share"]) for row in rows)
    if total_budget > 0 and abs(share_total - 1.0) > 1e-12:
        raise HistoricalGeoBudgetError("Budget shares do not reconcile to one")
    return AggregationResult(
        rows=rows,
        source_rows_n=rows_seen,
        source_columns_n=parquet.metadata.num_columns,
        source_row_groups_n=parquet.metadata.num_row_groups,
        period_start=period_start.isoformat(),
        period_end=period_end.isoformat(),
        geographies_n=len(rows),
        total_budget_rub=float(total_budget),
        selected_column_totals_rub=column_totals,
        active_rows_n=active_rows_n,
        zero_spend_rows_n=zero_spend_rows_n,
    )


def _parquet_table(rows: Sequence[Mapping[str, Any]], source_panel_sha256: str) -> Any:
    try:
        import pyarrow as pa
    except ImportError as exc:
        raise HistoricalGeoBudgetError("Artifact writing requires pyarrow") from exc
    schema = pa.schema(
        [
            pa.field("geo_model_name", pa.string(), nullable=False),
            pa.field("period_start", pa.date32(), nullable=False),
            pa.field("period_end", pa.date32(), nullable=False),
            pa.field("historical_total_budget_rub", pa.float64(), nullable=False),
            pa.field("active_days_n", pa.int64(), nullable=False),
            pa.field("active_rows_n", pa.int64(), nullable=False),
            pa.field("budget_share", pa.float64(), nullable=False),
            pa.field("source_rows_n", pa.int64(), nullable=False),
            pa.field("artifact_version", pa.string(), nullable=False),
            pa.field("source_panel_sha256", pa.string(), nullable=False),
            pa.field("spend_columns_version", pa.string(), nullable=False),
        ],
        metadata={
            b"artifact_version": ARTIFACT_VERSION.encode("ascii"),
            b"artifact_schema_version": ARTIFACT_SCHEMA_VERSION.encode("ascii"),
            b"source_panel_sha256": source_panel_sha256.encode("ascii"),
        },
    )
    normalized = [
        {
            **dict(row),
            "period_start": date.fromisoformat(str(row["period_start"])),
            "period_end": date.fromisoformat(str(row["period_end"])),
            "source_panel_sha256": source_panel_sha256,
        }
        for row in rows
    ]
    return pa.Table.from_pylist(normalized, schema=schema)


def _install_immutable(temporary: Path, target: Path) -> None:
    if target.exists():
        if not target.is_file() or sha256_file(target) != sha256_file(temporary):
            raise FileExistsError(f"Immutable artifact already exists with different content: {target.name}")
        temporary.unlink()
        return
    os.replace(temporary, target)


def _write_json_immutable(path: Path, payload: Mapping[str, Any]) -> None:
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    if temporary.exists():
        raise FileExistsError(f"Temporary artifact already exists: {temporary.name}")
    temporary.write_bytes(encoded)
    try:
        _install_immutable(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _peak_rss_bytes() -> int:
    raw = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return raw if sys.platform == "darwin" else raw * 1024


def build_historical_geo_budget_artifact(
    *,
    identity: RegistryPackageIdentity,
    panel_path: Path,
    policy: SpendColumnsPolicy,
    output_dir: Path,
    generated_at_utc: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, Any]:
    try:
        generated = datetime.fromisoformat(generated_at_utc.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HistoricalGeoBudgetError("generated_at_utc must be ISO-8601") from exc
    if generated.tzinfo is None:
        raise HistoricalGeoBudgetError("generated_at_utc must include a timezone")
    normalized_generated = generated.astimezone(timezone.utc).isoformat()
    started = time.perf_counter()
    source_sha = sha256_file(panel_path)
    if source_sha != identity.panel_sha256:
        raise HistoricalGeoBudgetError("Source panel differs from registry metadata")
    aggregated = aggregate_panel(panel_path, policy, batch_size=batch_size)
    output = output_dir.expanduser().resolve()
    if output.name != ARTIFACT_VERSION:
        raise HistoricalGeoBudgetError(
            f"Package artifact directory must be named {ARTIFACT_VERSION}"
        )
    output.mkdir(parents=True, exist_ok=True)
    artifact_path = output / PARQUET_FILENAME
    metadata_path = output / METADATA_FILENAME
    temporary = artifact_path.with_name(f".{artifact_path.name}.{os.getpid()}.tmp")
    if temporary.exists():
        raise FileExistsError(f"Temporary artifact already exists: {temporary.name}")
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise HistoricalGeoBudgetError("Artifact writing requires pyarrow") from exc
    table = _parquet_table(aggregated.rows, source_sha)
    pq.write_table(
        table,
        temporary,
        compression="zstd",
        use_dictionary=True,
        write_statistics=True,
        version="2.6",
        data_page_version="2.0",
    )
    try:
        _install_immutable(temporary, artifact_path)
    finally:
        temporary.unlink(missing_ok=True)
    artifact_sha = sha256_file(artifact_path)
    artifact_id = "artifact_" + _canonical_sha256(
        {
            "artifact_version": ARTIFACT_VERSION,
            "package_id": identity.package_id,
            "source_panel_sha256": source_sha,
            "spend_columns_version": policy.spend_columns_version,
            "spend_columns_config_sha256": policy.config_sha256,
        }
    )[:24]
    rows = [
        {**dict(row), "source_panel_sha256": source_sha}
        for row in aggregated.rows
    ]
    metadata = {
        "metadata_schema_version": ARTIFACT_SCHEMA_VERSION,
        "artifact_id": artifact_id,
        "artifact_version": ARTIFACT_VERSION,
        "relative_path": PARQUET_FILENAME,
        "sha256": artifact_sha,
        "size_bytes": artifact_path.stat().st_size,
        "package_id": identity.package_id,
        "package_input_fingerprint": identity.package_input_fingerprint,
        "model_run_id": identity.model_run_id,
        "registration_content_sha256": identity.registration_content_sha256,
        "source_panel_sha256": source_sha,
        "source_panel_size_bytes": identity.panel_size_bytes,
        "source_rows_n": aggregated.source_rows_n,
        "source_columns_n": aggregated.source_columns_n,
        "source_row_groups_n": aggregated.source_row_groups_n,
        "period_start": aggregated.period_start,
        "period_end": aggregated.period_end,
        "spend_columns": list(policy.spend_columns),
        "spend_columns_version": policy.spend_columns_version,
        "spend_columns_config_sha256": policy.config_sha256,
        "selected_column_totals_rub": aggregated.selected_column_totals_rub,
        "rows_n": aggregated.geographies_n,
        "geographies_n": aggregated.geographies_n,
        "total_budget_rub": aggregated.total_budget_rub,
        "active_rows_n": aggregated.active_rows_n,
        "zero_spend_rows_n": aggregated.zero_spend_rows_n,
        "generated_at_utc": normalized_generated,
        "row_sort": "geo_model_name_ascending",
        "null_policy": policy.null_policy,
        "negative_policy": policy.negative_policy,
        "infinite_policy": policy.infinite_policy,
        "rows": rows,
    }
    _write_json_immutable(metadata_path, metadata)
    package_artifacts_manifest = {
        "manifest_schema_version": "1.0.0",
        "package_id": identity.package_id,
        "package_input_fingerprint": identity.package_input_fingerprint,
        "registration_content_sha256": identity.registration_content_sha256,
        "source_panel_sha256": source_sha,
        "artifacts": [
            {
                "artifact_id": artifact_id,
                "artifact_kind": ARTIFACT_VERSION,
                "artifact_version": ARTIFACT_VERSION,
                "relative_path": f"{ARTIFACT_VERSION}/{PARQUET_FILENAME}",
                "sha256": artifact_sha,
                "size_bytes": artifact_path.stat().st_size,
                "metadata_relative_path": f"{ARTIFACT_VERSION}/{METADATA_FILENAME}",
                "metadata_sha256": sha256_file(metadata_path),
                "source_panel_sha256": source_sha,
                "period_start": aggregated.period_start,
                "period_end": aggregated.period_end,
                "spend_columns": list(policy.spend_columns),
                "spend_columns_version": policy.spend_columns_version,
                "rows_n": aggregated.geographies_n,
                "geographies_n": aggregated.geographies_n,
                "total_budget_rub": aggregated.total_budget_rub,
                "generated_at_utc": normalized_generated,
            }
        ],
    }
    package_manifest_path = output.parent / PACKAGE_ARTIFACTS_MANIFEST_FILENAME
    _write_json_immutable(package_manifest_path, package_artifacts_manifest)
    elapsed = time.perf_counter() - started
    build_card = {
        "build_status": "completed",
        "artifact_id": artifact_id,
        "artifact_version": ARTIFACT_VERSION,
        "package_id": identity.package_id,
        "source_panel_sha256": source_sha,
        "build_time_seconds": elapsed,
        "peak_rss_bytes": _peak_rss_bytes(),
        "batch_size": batch_size,
        "artifact_sha256": artifact_sha,
        "artifact_size_bytes": artifact_path.stat().st_size,
        "metadata_sha256": sha256_file(metadata_path),
        "package_artifacts_manifest_sha256": sha256_file(package_manifest_path),
    }
    build_card_path = output / BUILD_CARD_FILENAME
    build_card_path.write_text(
        json.dumps(build_card, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "metadata": metadata,
        "package_artifacts_manifest": package_artifacts_manifest,
        "build": build_card,
    }


def default_artifact_dir(registry_root: Path, package_id: str) -> Path:
    if not PACKAGE_ID_RE.fullmatch(package_id):
        raise HistoricalGeoBudgetError("Package ID is invalid")
    return (
        registry_root.expanduser().resolve()
        / "package_artifacts"
        / package_id
        / ARTIFACT_VERSION
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--registry-root", required=True, type=Path)
    parser.add_argument("--package-id", required=True)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--generated-at-utc", required=True)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    identity = load_registry_package_identity(args.registry_root, args.package_id)
    panel_path = resolve_registered_panel(identity, project_root=args.project_root)
    policy = load_spend_columns_policy(args.config)
    output_dir = args.output_dir or default_artifact_dir(
        args.registry_root,
        identity.package_id,
    )
    result = build_historical_geo_budget_artifact(
        identity=identity,
        panel_path=panel_path,
        policy=policy,
        output_dir=output_dir,
        generated_at_utc=args.generated_at_utc,
        batch_size=args.batch_size,
    )
    metadata = result["metadata"]
    build = result["build"]
    print(
        json.dumps(
            {
                "status": "completed",
                "artifact_id": metadata["artifact_id"],
                "artifact_version": metadata["artifact_version"],
                "package_id": metadata["package_id"],
                "source_rows_n": metadata["source_rows_n"],
                "source_columns_n": metadata["source_columns_n"],
                "geographies_n": metadata["geographies_n"],
                "period_start": metadata["period_start"],
                "period_end": metadata["period_end"],
                "total_budget_rub": metadata["total_budget_rub"],
                "sha256": metadata["sha256"],
                "size_bytes": metadata["size_bytes"],
                "build_time_seconds": build["build_time_seconds"],
                "peak_rss_bytes": build["peak_rss_bytes"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "ARTIFACT_VERSION",
    "BUILD_CARD_FILENAME",
    "DEFAULT_BATCH_SIZE",
    "METADATA_FILENAME",
    "PACKAGE_ARTIFACTS_MANIFEST_FILENAME",
    "PARQUET_FILENAME",
    "AggregationResult",
    "HistoricalGeoBudgetError",
    "RegistryPackageIdentity",
    "SpendColumnsPolicy",
    "aggregate_panel",
    "build_historical_geo_budget_artifact",
    "default_artifact_dir",
    "load_registry_package_identity",
    "load_spend_columns_policy",
    "resolve_registered_panel",
    "sha256_file",
]
