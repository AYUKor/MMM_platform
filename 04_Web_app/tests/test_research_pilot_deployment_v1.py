from __future__ import annotations

import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


WEB_APP_DIR = Path(__file__).resolve().parents[1]
DEPLOYMENT_DIR = WEB_APP_DIR / "deployment"
if str(DEPLOYMENT_DIR) not in sys.path:
    sys.path.insert(0, str(DEPLOYMENT_DIR))

import research_pilot as deployment  # noqa: E402


PACKAGE_ID = "pkg_0123456789abcdef_fedcba9876543210"


class ResearchPilotDeploymentTest(unittest.TestCase):
    def _model_tree(self, root: Path) -> tuple[Path, Path]:
        panel = root / "00_Data" / "panel.parquet"
        panel.parent.mkdir(parents=True)
        panel.write_bytes(b"private-training-panel")
        run_dir = root / "03_Outputs" / "01_PyMC_outputs" / "run" / "package"
        run_dir.mkdir(parents=True)
        model_manifest = run_dir / "model_manifest.json"
        model_manifest.write_text(json.dumps({"package_input_fingerprint": "a" * 64}), encoding="utf-8")
        posterior = run_dir / "posterior_test.nc"
        posterior.write_bytes(b"posterior")
        for filename in sorted(deployment.SERVING_RUNTIME_REQUIRED_FILES - {"model_manifest.json"}):
            path = run_dir / filename
            if filename.endswith(".json"):
                path.write_text("{}", encoding="utf-8")
            else:
                path.write_text("column\nvalue\n", encoding="utf-8")
        inventory = {
            path.name: deployment._sha256_path(path)
            for path in sorted(run_dir.iterdir())
            if path.is_file()
        }
        registry = root / "03_Outputs" / "01_PyMC_outputs" / "00_Model_registry"
        for name in ("channels", "events", "registrations"):
            (registry / name).mkdir(parents=True, exist_ok=True)
        registration = {
            "registry_schema_version": "1.0.0",
            "package_id": PACKAGE_ID,
            "model_run_id": "synthetic",
            "run_dir": str(run_dir.relative_to(root)),
            "package_input_fingerprint": "a" * 64,
            "package_schema_version": "0.4.0",
            "gate_policy_version": "1.2.0",
            "package_stage": "posterior_ready",
            "activation_status_at_registration": "preprod_restricted",
            "production_blockers_at_registration": ["MISSING_OR_FAILED_OOT_VALIDATION"],
            "panel": {
                "path": str(panel.relative_to(root)),
                "sha256": deployment._sha256_path(panel),
                "size_bytes": panel.stat().st_size,
            },
            "inventory_sha256": inventory,
            "registered_at_utc": "2026-07-15T00:00:00+00:00",
            "registered_by": "test",
            "reason": "test",
        }
        immutable = dict(registration)
        for key in ("registered_at_utc", "registered_by", "reason"):
            immutable.pop(key)
        registration["registration_content_sha256"] = deployment._canonical_hash(immutable)
        registration_path = registry / "registrations" / f"{PACKAGE_ID}.json"
        registration_path.write_text(json.dumps(registration), encoding="utf-8")
        event_id = "evt_test"
        (registry / "events" / f"{event_id}.json").write_text(
            json.dumps(
                {
                    "event_id": event_id,
                    "channel": "preprod",
                    "package_id": PACKAGE_ID,
                    "registration_content_sha256": registration["registration_content_sha256"],
                }
            ),
            encoding="utf-8",
        )
        (registry / "channels" / "preprod.json").write_text(
            json.dumps(
                {
                    "channel": "preprod",
                    "package_id": PACKAGE_ID,
                    "event_id": event_id,
                    "registration_content_sha256": registration["registration_content_sha256"],
                }
            ),
            encoding="utf-8",
        )
        return registry, panel

    def test_model_bundle_excludes_panel_and_installs_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "source"
            root.mkdir()
            registry, panel = self._model_tree(root)
            bundle = Path(temporary) / "model.tar.gz"
            result = deployment.package_model(
                root,
                registry,
                bundle,
                channel="preprod",
                expected_package_id=PACKAGE_ID,
            )
            self.assertFalse(result["source_panel_included"])
            manifest = deployment.verify_archive(
                bundle,
                expected_kind=deployment.MODEL_BUNDLE_KIND,
            )
            self.assertFalse(manifest["source_panel"]["included"])
            self.assertNotIn(str(panel.relative_to(root)), {row["path"] for row in manifest["files"]})
            target = Path(temporary) / "installed"
            first = deployment.install_model_bundle(bundle, target)
            second = deployment.install_model_bundle(bundle, target)
            self.assertEqual(first["installed_files_n"], len(manifest["files"]))
            self.assertEqual(second["unchanged_files_n"], len(manifest["files"]))
            self.assertFalse((target / panel.relative_to(root)).exists())

    def test_archive_verification_detects_payload_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "value.txt"
            source.write_text("before", encoding="utf-8")
            item = deployment._payload_file(source, "state/value.txt", "runtime_state")
            source.write_text("alter!", encoding="utf-8")
            manifest = {
                "kind": deployment.BACKUP_KIND,
                "schema_version": "1.0.0",
                "files": [item.manifest_row()],
            }
            archive = root / "tampered.tar.gz"
            deployment._write_archive(archive, manifest, [item])
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                deployment.verify_archive(archive, expected_kind=deployment.BACKUP_KIND)

    def test_render_is_loopback_panel_free_and_secret_free(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "render"
            result = deployment.render_deployment(
                output,
                domain="mmm.example.test",
                project_root=Path("/opt/x5-mmm/app"),
                venv_root=Path("/opt/x5-mmm/venv"),
                data_root=Path("/var/lib/x5-mmm"),
                backup_root=Path("/var/backups/x5-mmm"),
                package_id=PACKAGE_ID,
            )
            config = json.loads((output / "research_backend.json").read_text(encoding="utf-8"))
            nginx = (output / "x5-mmm-research.nginx.conf").read_text(encoding="utf-8")
            retention = (output / "x5-mmm-retention.service").read_text(encoding="utf-8")
            install_order = (output / "INSTALL_ORDER.md").read_text(encoding="utf-8")
            self.assertEqual(config["server"]["host"], "127.0.0.1")
            self.assertEqual(config["model"]["verification_mode"], "serving_bundle")
            self.assertNotIn("panel", json.dumps(config).lower())
            self.assertIn("auth_basic", nginx)
            self.assertIn("try_files $uri $uri/ /index.html", nginx)
            self.assertIn("retention --config", retention)
            self.assertIn("root:x5mmm` mode `0640", install_order)
            self.assertIn("Node 22", install_order)
            self.assertFalse(result["secrets_included"])
            with self.assertRaises(ValueError):
                deployment.render_deployment(
                    Path(temporary) / "bad",
                    domain="https://bad.example.test/path",
                    project_root=Path("/opt/x5-mmm/app"),
                    venv_root=Path("/opt/x5-mmm/venv"),
                    data_root=Path("/var/lib/x5-mmm"),
                    backup_root=Path("/var/backups/x5-mmm"),
                    package_id=PACKAGE_ID,
                )
            with self.assertRaises(ValueError):
                deployment.render_deployment(
                    Path(temporary) / "bad-port",
                    domain="mmm.example.test:443",
                    project_root=Path("/opt/x5-mmm/app"),
                    venv_root=Path("/opt/x5-mmm/venv"),
                    data_root=Path("/var/lib/x5-mmm"),
                    backup_root=Path("/var/backups/x5-mmm"),
                    package_id=PACKAGE_ID,
                )

    def test_backup_refuses_active_job_and_round_trips_terminal_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            state = data / "state"
            job_dir = state / "jobs" / "job_0123456789abcdef"
            job_dir.mkdir(parents=True)
            job_path = job_dir / "job.json"
            job_path.write_text(
                json.dumps({"job_id": job_dir.name, "status": {"code": "running"}}),
                encoding="utf-8",
            )
            config = root / "backend.json"
            config.write_text(
                json.dumps(
                    {
                        "paths": {
                            "state_root": str(state),
                            "runtime_root": str(data / "runtime"),
                            "artifact_root": str(data / "artifacts"),
                        },
                        "model": {"expected_package_id": PACKAGE_ID, "registry_channel": "preprod"},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "non-terminal"):
                deployment.create_runtime_backup(config, root / "backups")
            job_path.write_text(
                json.dumps({"job_id": job_dir.name, "status": {"code": "succeeded"}}),
                encoding="utf-8",
            )
            artifact = data / "artifacts" / "uploads" / "file.xlsx"
            artifact.parent.mkdir(parents=True)
            artifact.write_bytes(b"artifact")
            result = deployment.create_runtime_backup(config, root / "backups")
            restored = root / "restored"
            restore_result = deployment.restore_runtime_backup(Path(result["archive"]), restored)
            self.assertGreaterEqual(restore_result["restored_files_n"], 2)
            self.assertEqual((restored / "artifacts/uploads/file.xlsx").read_bytes(), b"artifact")

    def test_health_combines_http_readiness_and_disk_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "backend.json"
            config.write_text(
                json.dumps(
                    {
                        "server": {"host": "127.0.0.1", "port": 8765},
                        "paths": {
                            "state_root": str(root / "state"),
                            "runtime_root": str(root / "runtime"),
                            "artifact_root": str(root / "artifacts"),
                        },
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(
                deployment,
                "_http_json",
                side_effect=[{"status": "ok"}, {"status": "ready"}],
            ), patch.object(
                deployment.shutil,
                "disk_usage",
                return_value=SimpleNamespace(total=100, used=1, free=50 * 1024**3),
            ):
                result = deployment.health_check(config, min_free_gb=20)
            self.assertEqual(result["status"], "healthy")


if __name__ == "__main__":
    unittest.main()
