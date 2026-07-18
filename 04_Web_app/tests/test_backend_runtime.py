from __future__ import annotations

import sys
import tempfile
import unittest
import json
from pathlib import Path
from types import SimpleNamespace
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
TEST_AUTH_SECRET = "backend-runtime-test-session-secret"


class BackendRuntimeTest(unittest.TestCase):
    def _config(self, root: Path) -> dict:
        return {
            "schema_version": "1.2.0",
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
            "auth": {
                "mode": "local",
                "database_path": str(root / "auth.sqlite3"),
                "cookie_name": "mmm_session",
                "cookie_secure": False,
                "session_ttl_seconds": 28_800,
                "idle_timeout_seconds": 3_600,
                "login_window_seconds": 900,
                "login_max_attempts": 5,
                "login_cooldown_seconds": 900,
                "argon2_time_cost": 2,
                "argon2_memory_cost_kib": 19_456,
                "argon2_parallelism": 1,
            },
        }

    @staticmethod
    def _build(config: dict):
        return build_settings(
            config,
            project_root=PROJECT_ROOT,
            environ={"MMM_AUTH_SESSION_SECRET": TEST_AUTH_SECRET},
        )

    def test_build_and_preflight_pin_registry_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = self._config(Path(temporary))
            settings, host, port = self._build(config)
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
            ), patch(
                "backend_runtime.ModelPackage.from_run_dir",
                autospec=True,
                return_value=SimpleNamespace(
                    support_rows=[
                        {
                            "scope": "geo",
                            "target": "turnover_per_user",
                            "geo_label": "МОСКВА",
                        }
                    ]
                ),
            ):
                result = preflight(settings, config_sha256=_config_sha256(config))
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["package_id"], PACKAGE_ID)
            self.assertEqual(result["inventory_files_n"], 55)
            self.assertEqual(result["model_passport"]["contract_name"], "model_passport_v1")
            self.assertEqual(result["geo_catalog_coverage"]["status"], "available")

    def test_preflight_rejects_channel_package_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = self._config(Path(temporary))
            settings, _, _ = self._build(config)
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
            config["auth"]["cookie_secure"] = True
            settings, host, _ = self._build(config)
            self.assertEqual(settings.deployment_profile, "research_pilot")
            self.assertEqual(host, "127.0.0.1")
            config["model"]["verification_mode"] = "serving_bundle"
            settings, _, _ = self._build(config)
            self.assertEqual(settings.model_verification_mode, "serving_bundle")
            config["server"]["public_base_url"] = "http://mmm.example.test"
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                self._build(config)

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
            settings, _, port = self._build(effective)
            self.assertEqual(port, 9876)
            self.assertEqual(settings.retention_days, 14)
            self.assertEqual(len(settings.allowed_origins), 2)
            self.assertNotEqual(_config_sha256(config), _config_sha256(effective))

    def test_auth_secret_is_required_but_never_part_of_effective_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = self._config(Path(temporary))
            with self.assertRaisesRegex(ValueError, "MMM_AUTH_SESSION_SECRET"):
                build_settings(config, project_root=PROJECT_ROOT, environ={})
            settings, _, _ = self._build(config)
            self.assertNotIn(TEST_AUTH_SECRET, repr(settings))
            self.assertNotIn(TEST_AUTH_SECRET, json.dumps(config, ensure_ascii=False))
            effective = apply_environment_overrides(
                config,
                {
                    "MMM_AUTH_MODE": "local",
                    "MMM_AUTH_COOKIE_SECURE": "true",
                    "MMM_AUTH_SESSION_SECRET": TEST_AUTH_SECRET,
                },
            )
            self.assertTrue(effective["auth"]["cookie_secure"])
            self.assertNotIn(TEST_AUTH_SECRET, json.dumps(effective, ensure_ascii=False))

    def test_single_instance_lock_blocks_second_backend(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock_path = Path(temporary) / "backend.lock"
            with _single_instance_lock(lock_path):
                with self.assertRaisesRegex(RuntimeError, "already owns"):
                    with _single_instance_lock(lock_path):
                        self.fail("Second backend acquired the same lock")


if __name__ == "__main__":
    unittest.main()
