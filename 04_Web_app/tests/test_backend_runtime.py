from __future__ import annotations

import sys
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch


WEB_APP_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = WEB_APP_DIR.parent
if str(WEB_APP_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_APP_DIR))

from backend_runtime import (  # noqa: E402
    _config_sha256,
    _single_instance_lock,
    apply_environment_overrides,
    build_settings,
    preflight,
)


PACKAGE_ID = "pkg_807d3ddbae57a52a_9aacd3beb350725b"
PASSPORT_FIXTURE = (
    WEB_APP_DIR / "tests" / "fixtures" / "model_passport_v1_synthetic.json"
)


class BackendRuntimeTest(unittest.TestCase):
    def _config(self, root: Path) -> dict:
        return {
            "schema_version": "1.1.0",
            "server": {
                "deployment_profile": "local_development",
                "host": "127.0.0.1",
                "port": 8765,
                "public_base_url": None,
                "access_control_mode": "local_only",
                "allowed_origins": ["http://localhost:5173"],
            },
            "paths": {
                "state_root": str(root / "state"),
                "runtime_root": str(root / "runtime"),
                "artifact_root": str(root / "artifacts"),
                "registry_root": str(root / "registry"),
                "optimizer_policy_path": "02_Code/02_Budget_optimizer/optimizer_decision_policy_v2.yaml",
                "business_policy_path": "02_Code/02_Budget_optimizer/business_threshold_policy_v1.yaml",
            },
            "model": {
                "registry_channel": "preprod",
                "expected_package_id": PACKAGE_ID,
            },
            "worker": {
                "python_executable": sys.executable,
                "timeout_seconds": 60,
                "max_workers": 1,
                "max_upload_mb": 5,
            },
            "retention": {"days": 30},
        }

    def test_build_and_preflight_pin_registry_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = self._config(Path(temporary))
            settings, host, port = build_settings(config, project_root=PROJECT_ROOT)
            self.assertEqual(host, "127.0.0.1")
            self.assertEqual(port, 8765)
            resolved = {
                "package_id": PACKAGE_ID,
                "registration": {"package_input_fingerprint": "f" * 64},
                "verified": {"inventory_files_n": 55},
            }
            passport = json.loads(PASSPORT_FIXTURE.read_text(encoding="utf-8"))
            with patch("backend_runtime.resolve_channel", autospec=True, return_value=resolved), patch(
                "backend_runtime.build_model_passport",
                autospec=True,
                return_value=passport,
            ):
                result = preflight(settings, config_sha256=_config_sha256(config))
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["package_id"], PACKAGE_ID)
            self.assertEqual(result["inventory_files_n"], 55)
            self.assertEqual(result["model_passport"]["contract_name"], "model_passport_v1")

    def test_preflight_rejects_channel_package_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = self._config(Path(temporary))
            settings, _, _ = build_settings(config, project_root=PROJECT_ROOT)
            resolved = {
                "package_id": "pkg_ffffffffffffffff_ffffffffffffffff",
                "registration": {"package_input_fingerprint": "f" * 64},
                "verified": {"inventory_files_n": 55},
            }
            with patch(
                "backend_runtime.resolve_channel",
                autospec=True,
                return_value=resolved,
            ):
                with self.assertRaisesRegex(ValueError, "mismatch"):
                    preflight(settings, config_sha256=_config_sha256(config))

    def test_research_profile_requires_https_proxy_and_explicit_origin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = self._config(Path(temporary))
            config["server"].update(
                {
                    "deployment_profile": "research_pilot",
                    "public_base_url": "https://mmm.example.test",
                    "access_control_mode": "reverse_proxy_basic_auth",
                    "allowed_origins": ["https://mmm.example.test"],
                }
            )
            settings, host, _ = build_settings(config, project_root=PROJECT_ROOT)
            self.assertEqual(settings.deployment_profile, "research_pilot")
            self.assertEqual(host, "127.0.0.1")
            config["server"]["public_base_url"] = "http://mmm.example.test"
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                build_settings(config, project_root=PROJECT_ROOT)

    def test_environment_overrides_are_part_of_effective_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = self._config(Path(temporary))
            effective = apply_environment_overrides(
                config,
                {
                    "MMM_BACKEND_PORT": "9876",
                    "MMM_BACKEND_RETENTION_DAYS": "14",
                    "MMM_BACKEND_ALLOWED_ORIGINS": "http://localhost:4173,http://127.0.0.1:4173",
                },
            )
            settings, _, port = build_settings(effective, project_root=PROJECT_ROOT)
            self.assertEqual(port, 9876)
            self.assertEqual(settings.retention_days, 14)
            self.assertEqual(len(settings.allowed_origins), 2)
            self.assertNotEqual(_config_sha256(config), _config_sha256(effective))

    def test_single_instance_lock_blocks_second_backend(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock_path = Path(temporary) / "backend.lock"
            with _single_instance_lock(lock_path):
                with self.assertRaisesRegex(RuntimeError, "already owns"):
                    with _single_instance_lock(lock_path):
                        self.fail("Second backend acquired the same lock")


if __name__ == "__main__":
    unittest.main()
