"""Registry tests use tiny synthetic packages and no real posterior files."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PYMC_CODE_DIR = Path(__file__).resolve().parents[1]
if str(PYMC_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(PYMC_CODE_DIR))

from mmm_core import model_registry as registry  # noqa: E402


class ModelRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.registry_root = self.root / "registry"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _package(
        self,
        name: str,
        *,
        fingerprint: str,
        schema: str = "0.3.0",
        activation: str = "preprod_restricted",
        blockers: list[str] | None = None,
    ) -> tuple[Path, dict]:
        run_dir = self.root / name
        run_dir.mkdir()
        panel = self.root / f"{name}_panel.parquet"
        panel.write_bytes(f"panel-{name}".encode())
        manifest = {
            "package_schema_version": schema,
            "package_stage": "posterior_ready",
            "activation_status": activation,
            "production_blockers": list(blockers or []),
            "package_input_fingerprint": fingerprint,
            "gate_policy_version": "1.1.0",
            "model_run_id": name,
        }
        files = {
            "model_manifest.json": manifest,
            "run_config.json": {"panel_path": str(panel)},
            "posterior_index.json": {
                "posterior_files_n": 1,
                "posterior_by_fit": {
                    "S::T": {
                        "file_name": "posterior_S__T.nc",
                        "sha256": "synthetic",
                    }
                },
            },
            "gate_policy.json": {},
            "fit_design_metadata.json": {},
        }
        for filename, payload in files.items():
            (run_dir / filename).write_text(json.dumps(payload), encoding="utf-8")
        for filename in ["capability_matrix.csv", "risk_registry.csv", "gate_results.csv"]:
            (run_dir / filename).write_text("column\nvalue\n", encoding="utf-8")
        for filename in [
            "fit_design_media_scales.csv",
            "target_denominator_metadata.csv",
            "historical_support_bounds.csv",
            "adstock_warm_start.csv",
        ]:
            (run_dir / filename).write_text("column\nvalue\n", encoding="utf-8")
        (run_dir / "posterior_S__T.nc").write_bytes(f"posterior-{name}".encode())
        if activation == "production_ready":
            (run_dir / "oot_validation.json").write_text(
                json.dumps(
                    {
                        "status": "passed",
                        "activation_eligible": True,
                        "binding": {"package_input_fingerprint": fingerprint},
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "historical_replay_validation.json").write_text(
                json.dumps(
                    {
                        "status": "passed",
                        "binding": {"package_input_fingerprint": fingerprint},
                    }
                ),
                encoding="utf-8",
            )
        return run_dir, manifest

    @staticmethod
    def _package_stub(manifests: dict[Path, dict]):
        def load(run_dir, **_kwargs):
            resolved = Path(run_dir).resolve()
            return SimpleNamespace(manifest=manifests[resolved])

        return load

    def test_registration_is_idempotent_and_tamper_is_detected(self) -> None:
        run_dir, manifest = self._package("preprod", fingerprint="a" * 64)
        manifests = {run_dir.resolve(): manifest}
        with patch.object(registry.ModelPackage, "from_run_dir", side_effect=self._package_stub(manifests)):
            first = registry.register_model(
                run_dir,
                registered_by="owner",
                reason="test",
                registry_root=self.registry_root,
            )
            second = registry.register_model(
                run_dir,
                registered_by="owner2",
                reason="same content",
                registry_root=self.registry_root,
            )
            self.assertEqual(first, second)
            verified = registry.verify_registration(first["package_id"], self.registry_root)
            self.assertEqual(verified["status"], "verified")
            (run_dir / "capability_matrix.csv").write_text("mutated\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "mutated"):
                registry.verify_registration(first["package_id"], self.registry_root)

    def test_serving_bundle_verifies_inventory_without_source_panel(self) -> None:
        run_dir, manifest = self._package("serving", fingerprint="9" * 64)
        panel_path = Path(json.loads((run_dir / "run_config.json").read_text())["panel_path"])
        manifests = {run_dir.resolve(): manifest}
        with patch.object(registry.ModelPackage, "from_run_dir", side_effect=self._package_stub(manifests)):
            registration = registry.register_model(
                run_dir,
                registered_by="owner",
                reason="serving bundle",
                registry_root=self.registry_root,
            )
            panel_path.unlink()
            with self.assertRaisesRegex(FileNotFoundError, "source panel"):
                registry.verify_registration(registration["package_id"], self.registry_root)
            verified = registry.verify_registration(
                registration["package_id"],
                self.registry_root,
                verification_mode="serving_bundle",
            )
            self.assertEqual(verified["source_panel_status"], "provenance_only_not_copied")
            self.assertEqual(verified["panel_sha256"], registration["panel"]["sha256"])

    def test_serving_bundle_rejects_incomplete_runtime_inventory(self) -> None:
        run_dir, manifest = self._package("incomplete", fingerprint="7" * 64)
        (run_dir / "adstock_warm_start.csv").unlink()
        manifests = {run_dir.resolve(): manifest}
        with patch.object(registry.ModelPackage, "from_run_dir", side_effect=self._package_stub(manifests)):
            registration = registry.register_model(
                run_dir,
                registered_by="owner",
                reason="incomplete serving bundle",
                registry_root=self.registry_root,
            )
            with self.assertRaisesRegex(ValueError, "serving-complete"):
                registry.verify_registration(
                    registration["package_id"],
                    self.registry_root,
                    verification_mode="serving_bundle",
                )

    def test_registration_metadata_tamper_is_detected(self) -> None:
        run_dir, manifest = self._package("metadata", fingerprint="8" * 64)
        manifests = {run_dir.resolve(): manifest}
        with patch.object(registry.ModelPackage, "from_run_dir", side_effect=self._package_stub(manifests)):
            registration = registry.register_model(
                run_dir,
                registered_by="owner",
                reason="metadata",
                registry_root=self.registry_root,
            )
            path = self.registry_root / "registrations" / f"{registration['package_id']}.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["run_dir"] = str(self.root / "other")
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "metadata was mutated"):
                registry.verify_registration(
                    registration["package_id"],
                    self.registry_root,
                    verification_mode="serving_bundle",
                )

    def test_legacy_schema_is_rejected(self) -> None:
        run_dir, manifest = self._package("legacy", fingerprint="b" * 64, schema="0.2.0")
        manifests = {run_dir.resolve(): manifest}
        with patch.object(registry.ModelPackage, "from_run_dir", side_effect=self._package_stub(manifests)):
            with self.assertRaisesRegex(ValueError, "Legacy package schema"):
                registry.register_model(
                    run_dir,
                    registered_by="owner",
                    reason="legacy",
                    registry_root=self.registry_root,
                )

    def test_preprod_activation_uses_compare_and_swap(self) -> None:
        run_dir, manifest = self._package("preprod", fingerprint="c" * 64)
        manifests = {run_dir.resolve(): manifest}
        with patch.object(registry.ModelPackage, "from_run_dir", side_effect=self._package_stub(manifests)):
            registration = registry.register_model(
                run_dir,
                registered_by="owner",
                reason="preprod",
                registry_root=self.registry_root,
            )
            event = registry.activate_model(
                registration["package_id"],
                channel="preprod",
                expected_current="none",
                approved_by="owner",
                reason="test preprod",
                registry_root=self.registry_root,
            )
            self.assertEqual(event["action"], "activate")
            resolved = registry.resolve_channel("preprod", registry_root=self.registry_root)
            self.assertEqual(resolved["package_id"], registration["package_id"])
            with self.assertRaisesRegex(ValueError, "compare-and-swap"):
                registry.activate_model(
                    registration["package_id"],
                    channel="preprod",
                    expected_current="none",
                    approved_by="owner",
                    reason="stale CAS",
                    registry_root=self.registry_root,
                )
            with self.assertRaisesRegex(ValueError, "production_ready"):
                registry.activate_model(
                    registration["package_id"],
                    channel="production",
                    expected_current="none",
                    approved_by="owner",
                    reason="must fail",
                    registry_root=self.registry_root,
                )

    def test_production_rollback_requires_previously_active_package(self) -> None:
        run_a, manifest_a = self._package(
            "prod_a",
            fingerprint="d" * 64,
            activation="production_ready",
        )
        run_b, manifest_b = self._package(
            "prod_b",
            fingerprint="e" * 64,
            activation="production_ready",
        )
        manifests = {run_a.resolve(): manifest_a, run_b.resolve(): manifest_b}
        with patch.object(registry.ModelPackage, "from_run_dir", side_effect=self._package_stub(manifests)):
            reg_a = registry.register_model(
                run_a,
                registered_by="owner",
                reason="prod a",
                registry_root=self.registry_root,
            )
            reg_b = registry.register_model(
                run_b,
                registered_by="owner",
                reason="prod b",
                registry_root=self.registry_root,
            )
            registry.activate_model(
                reg_a["package_id"],
                channel="production",
                expected_current="none",
                approved_by="owner",
                reason="first production",
                registry_root=self.registry_root,
            )
            registry.activate_model(
                reg_b["package_id"],
                channel="production",
                expected_current=reg_a["package_id"],
                approved_by="owner",
                reason="second production",
                registry_root=self.registry_root,
            )
            rollback = registry.rollback_model(
                reg_a["package_id"],
                expected_current=reg_b["package_id"],
                approved_by="owner",
                reason="rollback test",
                registry_root=self.registry_root,
            )
            self.assertEqual(rollback["action"], "rollback")
            self.assertEqual(
                registry.resolve_channel("production", registry_root=self.registry_root)["package_id"],
                reg_a["package_id"],
            )


if __name__ == "__main__":
    unittest.main()
