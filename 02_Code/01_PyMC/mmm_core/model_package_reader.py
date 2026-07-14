"""Read model-package artifacts generated from an X5 MMM run folder.

The model run folder is the source of truth for downstream planning layers.
Forecast and optimizer code should use this reader instead of hard-coding
segments, targets, channels, beta structures, or warning policy.
"""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .io import read_json, resolve_path
from .model_package import (
    build_package_input_fingerprint,
    list_posteriors,
    load_gate_policy,
    sha256_file,
)


class ModelPackageError(RuntimeError):
    """Raised when a model package is missing or inconsistent."""


class StaleModelPackageError(ModelPackageError):
    """Raised when run_config.json changed after package generation."""


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _normalize_values(values: Iterable[str] | None) -> set[str] | None:
    if values is None:
        return None
    out = {str(v) for v in values if v is not None and str(v) != ""}
    return out or None


@dataclass(frozen=True)
class CapabilitySelection:
    """Capabilities split into optimization objective and side metrics."""

    objective_rows: list[dict[str, str]]
    side_metric_rows: list[dict[str, str]]
    excluded_rows: list[dict[str, str]]
    policy: str

    def summary(self) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "objective_rows_n": len(self.objective_rows),
            "side_metric_rows_n": len(self.side_metric_rows),
            "excluded_rows_n": len(self.excluded_rows),
            "objective_allowed_use": dict(Counter(row.get("allowed_use", "") for row in self.objective_rows)),
            "side_allowed_use": dict(Counter(row.get("allowed_use", "") for row in self.side_metric_rows)),
        }


@dataclass(frozen=True)
class PlanValidationResult:
    """Validation result for requested segment/target/channel rows."""

    supported_rows: list[dict[str, Any]]
    unsupported_rows: list[dict[str, Any]]
    risky_supported_rows: list[dict[str, Any]]

    def summary(self) -> dict[str, Any]:
        return {
            "supported_rows_n": len(self.supported_rows),
            "unsupported_rows_n": len(self.unsupported_rows),
            "risky_supported_rows_n": len(self.risky_supported_rows),
        }


class ModelPackage:
    """Read-only view of a fitted MMM model package."""

    REQUIRED_FILES = ["model_manifest.json", "capability_matrix.csv", "risk_registry.csv", "posterior_index.json"]

    def __init__(
        self,
        run_dir: Path,
        manifest: dict[str, Any],
        capability_rows: list[dict[str, str]],
        risk_rows: list[dict[str, str]],
        posterior_index: dict[str, Any],
        gate_rows: list[dict[str, str]] | None = None,
        support_rows: list[dict[str, str]] | None = None,
    ) -> None:
        self.run_dir = run_dir
        self.manifest = manifest
        self.capability_rows = capability_rows
        self.risk_rows = risk_rows
        self.posterior_index = posterior_index
        self.gate_rows = gate_rows or []
        self.support_rows = support_rows or []

    @classmethod
    def from_run_dir(
        cls,
        run_dir: str | Path,
        *,
        require_posterior_ready: bool = False,
        validate_hash: bool = True,
    ) -> "ModelPackage":
        resolved = resolve_path(run_dir)
        missing = [name for name in cls.REQUIRED_FILES if not (resolved / name).exists()]
        if missing:
            raise ModelPackageError(
                f"Model package is incomplete in {resolved}. Missing: {', '.join(missing)}. "
                "Run mmm_core/model_package.py --run-dir <run_dir> --write first."
            )

        manifest = read_json(resolved / "model_manifest.json") or {}
        capability_rows = _read_csv(resolved / "capability_matrix.csv")
        risk_rows = _read_csv(resolved / "risk_registry.csv")
        posterior_index = read_json(resolved / "posterior_index.json") or {}
        gate_rows = _read_csv(resolved / "gate_results.csv")
        support_rows = _read_csv(resolved / "historical_support_bounds.csv")
        pkg = cls(resolved, manifest, capability_rows, risk_rows, posterior_index, gate_rows, support_rows)

        schema_version = str(manifest.get("package_schema_version") or "0.0.0")
        if schema_version >= "0.2.0" and not gate_rows:
            raise ModelPackageError(
                f"Model package {resolved} declares schema {schema_version} but gate_results.csv is missing or empty."
            )
        unsafe_diagnostic = [
            row
            for row in capability_rows
            if row.get("allowed_use") == "diagnostic"
            and row.get("objective_role") not in {"side_metric_only", "forbidden"}
        ]
        if unsafe_diagnostic:
            raise ModelPackageError("Diagnostic capability rows cannot be optimizer objective rows.")

        unsafe_actions: list[dict[str, str]] = []
        for row in capability_rows:
            allowed = str(row.get("allowed_use") or "unavailable")
            optimizer_action = str(row.get("optimizer_use") or "blocked")
            forecast_action = str(row.get("forecast_use") or "blocked")
            objective_role = str(row.get("objective_role") or "forbidden")
            valid = True
            if allowed == "diagnostic":
                valid = (
                    optimizer_action in {"fixed_at_plan", "blocked"}
                    and forecast_action in {"diagnostic_only", "blocked"}
                    and objective_role in {"side_metric_only", "forbidden"}
                )
            elif allowed == "caution":
                valid = optimizer_action in {"no_increase", "fixed_at_plan", "blocked"}
            elif allowed not in {"primary"}:
                valid = optimizer_action == "blocked" and objective_role == "forbidden"
            if not valid:
                unsafe_actions.append(row)
        if unsafe_actions:
            raise ModelPackageError(
                "Capability actions violate fail-closed allowed-use invariants. "
                f"Examples: {unsafe_actions[:3]}"
            )

        if validate_hash:
            pkg.assert_artifact_lineage_current()
        if require_posterior_ready and pkg.package_stage != "posterior_ready":
            raise ModelPackageError(
                f"Model package stage is {pkg.package_stage}; posterior_ready is required for this operation."
            )
        return pkg

    @property
    def package_stage(self) -> str:
        return str(self.manifest.get("package_stage", "unknown"))

    @property
    def model_run_id(self) -> str:
        return str(self.manifest.get("model_run_id", ""))

    @property
    def activation_status(self) -> str:
        return str(self.manifest.get("activation_status", "unknown"))

    @property
    def segments(self) -> list[str]:
        return list(self.manifest.get("segments") or [])

    @property
    def targets(self) -> list[str]:
        return list(self.manifest.get("targets") or [])

    def assert_run_config_hash_current(self) -> None:
        """Fail if run_config.json changed after model_manifest.json was generated."""
        run_config_path = self.run_dir / "run_config.json"
        expected = self.manifest.get("run_config_sha256")
        current = sha256_file(run_config_path)
        if not expected or not current:
            raise StaleModelPackageError(
                "Model package lineage is incomplete: run_config.json or its expected hash is missing."
            )
        if expected != current:
            raise StaleModelPackageError(
                "Model package is stale: run_config.json hash differs from model_manifest.json. "
                "Regenerate the package with mmm_core/model_package.py --write."
            )

    def assert_artifact_lineage_current(self) -> None:
        """Fail if config, posterior or gate evidence changed after package generation."""
        self.assert_run_config_hash_current()
        expected = self.manifest.get("package_input_fingerprint")
        if not expected:
            raise StaleModelPackageError(
                "Model package has no package_input_fingerprint; regenerate schema 0.3 package artifacts."
            )
        posterior_index = list_posteriors(self.run_dir)
        gate_policy = load_gate_policy(self.run_dir)
        current, _, _ = build_package_input_fingerprint(self.run_dir, posterior_index, gate_policy)
        if current != expected:
            raise StaleModelPackageError(
                "Model package is stale: posterior or gate evidence hashes differ from model_manifest.json. "
                "Regenerate the package before forecasting or optimization."
            )

    def summary(self) -> dict[str, Any]:
        """Return a compact business-readable package summary."""
        return {
            "model_run_id": self.model_run_id,
            "run_dir": str(self.run_dir),
            "package_stage": self.package_stage,
            "activation_status": self.activation_status,
            "production_blockers": list(self.manifest.get("production_blockers") or []),
            "gate_policy_version": self.manifest.get("gate_policy_version"),
            "mode": self.manifest.get("mode"),
            "run_label": self.manifest.get("run_label"),
            "run_variant": self.manifest.get("run_variant"),
            "segments_n": len(self.segments),
            "targets_n": len(self.targets),
            "capability_rows_n": len(self.capability_rows),
            "risk_rows_n": len(self.risk_rows),
            "posterior_files_n": (self.manifest.get("artifact_status") or {}).get("posterior_files_n", 0),
            "allowed_use_counts": dict(Counter(row.get("allowed_use", "") for row in self.capability_rows)),
            "risk_level_counts": dict(Counter(row.get("risk_level", "") for row in self.capability_rows)),
            "optimizer_use_counts": dict(Counter(row.get("optimizer_use", "") for row in self.capability_rows)),
            "forecast_use_counts": dict(Counter(row.get("forecast_use", "") for row in self.capability_rows)),
            "optimizer_policy_counts": dict(Counter(row.get("optimizer_use", "") for row in self.capability_rows)),
            "run_config_sha256": self.manifest.get("run_config_sha256"),
        }

    def filter_capabilities(
        self,
        *,
        segments: Iterable[str] | None = None,
        targets: Iterable[str] | None = None,
        channels: Iterable[str] | None = None,
        allowed_use: Iterable[str] | None = None,
    ) -> list[dict[str, str]]:
        segment_set = _normalize_values(segments)
        target_set = _normalize_values(targets)
        channel_set = _normalize_values(channels)
        allowed_set = _normalize_values(allowed_use)
        rows = []
        for row in self.capability_rows:
            if segment_set is not None and row.get("segment") not in segment_set:
                continue
            if target_set is not None and row.get("target") not in target_set:
                continue
            if channel_set is not None and row.get("channel") not in channel_set:
                continue
            if allowed_set is not None and row.get("allowed_use") not in allowed_set:
                continue
            rows.append(row)
        return rows

    def channels_for(self, segment: str, target: str, *, include_diagnostic: bool = True) -> list[str]:
        allowed = {"primary", "caution", "diagnostic"} if include_diagnostic else {"primary", "caution"}
        rows = self.filter_capabilities(segments=[segment], targets=[target], allowed_use=allowed)
        return sorted({row["channel"] for row in rows})

    def select_for_optimizer(
        self,
        *,
        policy: str = "balanced",
        segments: Iterable[str] | None = None,
        targets: Iterable[str] | None = None,
        channels: Iterable[str] | None = None,
    ) -> CapabilitySelection:
        """Split rows for optimizer objective vs side metrics.

        Policies:
        - strict: only fully optimizable primary rows enter the objective;
        - balanced: primary plus caution/no-increase rows enter the objective;
        - exploratory: same objective eligibility as balanced. Diagnostic rows
          remain side-only under every policy.
        """
        rows = self.filter_capabilities(segments=segments, targets=targets, channels=channels)
        if policy == "strict":
            objective_allowed = {"primary"}
            side_allowed = {"caution", "diagnostic"}
        elif policy in {"balanced", "exploratory"}:
            objective_allowed = {"primary", "caution"}
            side_allowed = {"diagnostic"}
        else:
            raise ModelPackageError(f"Unknown optimizer policy: {policy}")

        objective = [row for row in rows if row.get("allowed_use") in objective_allowed]
        side = [row for row in rows if row.get("allowed_use") in side_allowed]
        excluded = [row for row in rows if row not in objective and row not in side]
        return CapabilitySelection(objective, side, excluded, policy)

    def select_for_forecast(
        self,
        *,
        segments: Iterable[str] | None = None,
        targets: Iterable[str] | None = None,
        channels: Iterable[str] | None = None,
    ) -> CapabilitySelection:
        """Forecast simulates all available rows, preserving risk flags."""
        rows = self.filter_capabilities(segments=segments, targets=targets, channels=channels)
        objective = [row for row in rows if row.get("allowed_use") in {"primary", "caution", "diagnostic"}]
        excluded = [row for row in rows if row not in objective]
        return CapabilitySelection(objective, [], excluded, "simulate_all_supported")

    def validate_requested_rows(self, requested_rows: Iterable[dict[str, Any]]) -> PlanValidationResult:
        """Check whether requested segment/target/channel rows are supported by the model."""
        supported_index = {
            (row.get("segment"), row.get("target"), row.get("channel")): row
            for row in self.capability_rows
            if row.get("allowed_use") in {"primary", "caution", "diagnostic"}
        }
        supported: list[dict[str, Any]] = []
        unsupported: list[dict[str, Any]] = []
        risky: list[dict[str, Any]] = []
        for requested in requested_rows:
            key = (requested.get("segment"), requested.get("target"), requested.get("channel"))
            capability = supported_index.get(key)
            if capability is None:
                unsupported.append({**requested, "reason": "not_supported_by_selected_model_package"})
                continue
            combined = {**requested, "capability": capability}
            supported.append(combined)
            if capability.get("allowed_use") != "primary" or capability.get("risk_level") != "low":
                risky.append(combined)
        return PlanValidationResult(supported, unsupported, risky)

    def supported_geos_for(self, segment: str, target: str, channel: str) -> set[str]:
        """Return geos with an exported historical-support row for the requested fit."""
        return {
            str(row.get("geo_label"))
            for row in self.support_rows
            if row.get("segment") == segment
            and row.get("target") == target
            and row.get("channel") == channel
            and row.get("geo_label")
        }

    def check_card(self, *, purpose: str, optimizer_policy: str = "balanced") -> dict[str, Any]:
        """Return a small JSON-serializable card for workflow smoke checks."""
        if purpose == "optimizer":
            selection = self.select_for_optimizer(policy=optimizer_policy)
        elif purpose == "forecast":
            selection = self.select_for_forecast()
        else:
            raise ModelPackageError(f"Unknown purpose: {purpose}")
        return {
            "purpose": purpose,
            "package_summary": self.summary(),
            "selection_summary": selection.summary(),
            "risk_registry_rows_n": len(self.risk_rows),
            "top_risks": self.risk_rows[:20],
        }
