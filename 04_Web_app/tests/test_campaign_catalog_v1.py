"""Past-campaign catalog in the portal: package binding, contracts and HTTP routes on synthetic data only."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping

WEB_APP_DIR = Path(__file__).resolve().parents[1]
PYMC_CODE_DIR = WEB_APP_DIR.parent / "02_Code" / "01_PyMC"
for _path in (WEB_APP_DIR, PYMC_CODE_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from api.http_smoke import HttpSmokeApplication, HttpSmokeSettings, make_handler  # noqa: E402
from contracts.campaign_catalog_v1 import (  # noqa: E402
    CampaignCatalogContractError,
    load_campaign_card_v1_schema,
    load_campaign_catalog_v1_schema,
    validate_campaign_card_v1,
    validate_campaign_catalog_v1,
)
from mmm_core.campaign_catalog_extension import (  # noqa: E402
    ARTIFACT_VERSION,
    DATA_FILENAME,
    METADATA_FILENAME,
    WORKBOOK_FILENAME,
)
from mmm_core.campaign_catalog_synthetic import write_synthetic_extension  # noqa: E402
from services import campaign_catalog as service  # noqa: E402
from tests.synthetic_model_registry import write_synthetic_model_registry  # noqa: E402

PASSPORT_FIXTURE = WEB_APP_DIR / "tests" / "fixtures" / "model_passport_v1_synthetic.json"
FINGERPRINT = "ab" * 32
PACKAGE_ID = f"pkg_{FINGERPRINT[:16]}_{'2' * 16}"
MODEL_RUN_ID = "synthetic_model_run"
TEST_SECRET = "campaign-catalog-test-session-secret-2026"
ADMIN_PASSWORD = "Catalog-admin-2026"


def _passport() -> dict[str, Any]:
    passport = json.loads(PASSPORT_FIXTURE.read_text(encoding="utf-8"))
    passport["package"]["package_id"] = PACKAGE_ID
    passport["package"]["package_fingerprint"] = FINGERPRINT
    passport["package"]["model_run_id"] = MODEL_RUN_ID
    return passport


def _schema_validator(schema: Mapping[str, Any]):
    try:
        import jsonschema
    except ImportError:  # pragma: no cover - optional in the source runtime
        return None
    return jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())


class CampaignCatalogServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.registry = write_synthetic_model_registry(self.root / "registry", _passport())
        self.extension_dir = self.registry / "package_artifacts" / PACKAGE_ID / ARTIFACT_VERSION
        service._CACHE.clear()

    def tearDown(self) -> None:
        service._CACHE.clear()
        self.temporary.cleanup()

    def _publish(self, **overrides: Any) -> dict[str, Any]:
        identity = {
            "package_id": PACKAGE_ID,
            "package_input_fingerprint": FINGERPRINT,
            "model_run_id": MODEL_RUN_ID,
        }
        identity.update(overrides)
        return write_synthetic_extension(
            self.extension_dir, scratch_dir=self.root / "scratch", **identity
        )

    def test_unpublished_catalog_is_an_empty_state_not_an_error(self) -> None:
        payload = service.build_campaign_catalog_v1(registry_root=self.registry, package_id=PACKAGE_ID)
        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["campaigns"], [])
        self.assertIsNone(payload["download"])
        self.assertEqual(payload["model_version"], MODEL_RUN_ID)
        validator = _schema_validator(load_campaign_catalog_v1_schema())
        if validator is not None:
            validator.validate(payload)
        with self.assertRaises(service.CampaignCatalogUnavailableError):
            service.build_campaign_card_v1(registry_root=self.registry, package_id=PACKAGE_ID, number=1)
        with self.assertRaises(service.CampaignCatalogUnavailableError):
            service.campaign_catalog_workbook(registry_root=self.registry, package_id=PACKAGE_ID)
        unknown = service.build_campaign_catalog_v1(
            registry_root=self.registry, package_id="pkg_unavailable_model"
        )
        self.assertEqual(unknown["status"], "unavailable")
        self.assertIsNone(unknown["model_version"])

    def test_published_catalog_is_served_unchanged(self) -> None:
        metadata = self._publish()
        data = json.loads((self.extension_dir / DATA_FILENAME).read_text(encoding="utf-8"))
        payload = service.build_campaign_catalog_v1(registry_root=self.registry, package_id=PACKAGE_ID)
        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["record_origin"], "verified_model_package_artifact")
        self.assertEqual(payload["campaigns"], data["campaigns"])
        self.assertEqual(payload["summary"], data["summary"])
        self.assertEqual(payload["artifact_id"], metadata["artifact_id"])
        self.assertEqual(payload["roas_level_label"], "уровень ROAS по отрасли")
        self.assertEqual(payload["download"]["sha256"], metadata["workbook"]["sha256"])
        self.assertEqual(payload["download"]["download_path"], "/api/v1/campaign-catalog/download")
        self.assertNotIn(str(self.root), json.dumps(payload, ensure_ascii=False))
        validator = _schema_validator(load_campaign_catalog_v1_schema())
        if validator is not None:
            validator.validate(payload)

        number = data["campaigns"][3]["number"]
        card = service.build_campaign_card_v1(registry_root=self.registry, package_id=PACKAGE_ID, number=number)
        self.assertEqual(card["campaign"], data["campaigns"][3])
        self.assertEqual(card["notes"], data["notes"])
        card_validator = _schema_validator(load_campaign_card_v1_schema())
        if card_validator is not None:
            card_validator.validate(card)
        with self.assertRaises(service.CampaignNotFoundError):
            service.build_campaign_card_v1(registry_root=self.registry, package_id=PACKAGE_ID, number=6)

        body, file_name = service.campaign_catalog_workbook(registry_root=self.registry, package_id=PACKAGE_ID)
        self.assertEqual(hashlib.sha256(body).hexdigest(), metadata["workbook"]["sha256"])
        self.assertEqual(file_name, metadata["workbook"]["download_file_name"])

    def test_catalog_of_another_package_or_run_is_refused(self) -> None:
        self._publish(model_run_id="another_model_run")
        with self.assertRaises(service.CampaignCatalogError):
            service.build_campaign_catalog_v1(registry_root=self.registry, package_id=PACKAGE_ID)

    def test_changed_files_are_refused(self) -> None:
        self._publish()
        service.build_campaign_catalog_v1(registry_root=self.registry, package_id=PACKAGE_ID)
        data_path = self.extension_dir / DATA_FILENAME
        original = data_path.read_bytes()
        data_path.write_bytes(original.replace("Тестовая кампания 1".encode(), "Тестовая кампания X".encode(), 1))
        with self.assertRaises(service.CampaignCatalogError):
            service.build_campaign_catalog_v1(registry_root=self.registry, package_id=PACKAGE_ID)
        data_path.write_bytes(original)
        workbook_path = self.extension_dir / WORKBOOK_FILENAME
        workbook_path.write_bytes(workbook_path.read_bytes() + b"\0")
        with self.assertRaises(service.CampaignCatalogError):
            service.campaign_catalog_workbook(registry_root=self.registry, package_id=PACKAGE_ID)

    def test_failed_publication_checks_are_refused(self) -> None:
        self._publish()
        metadata_path = self.extension_dir / METADATA_FILENAME
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["checks"][-1]["status"] = "failed"
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(service.CampaignCatalogError):
            service.build_campaign_catalog_v1(registry_root=self.registry, package_id=PACKAGE_ID)

    def test_incomplete_publication_is_an_integrity_error(self) -> None:
        self._publish()
        (self.extension_dir / WORKBOOK_FILENAME).unlink()
        with self.assertRaises(service.CampaignCatalogError):
            service.build_campaign_catalog_v1(registry_root=self.registry, package_id=PACKAGE_ID)

    def test_contract_rejects_changed_payloads(self) -> None:
        self._publish()
        payload = service.build_campaign_catalog_v1(registry_root=self.registry, package_id=PACKAGE_ID)
        broken = json.loads(json.dumps(payload, ensure_ascii=False))
        broken["summary"]["computed_n"] += 1
        with self.assertRaises(CampaignCatalogContractError):
            validate_campaign_catalog_v1(broken)
        reversed_rows = json.loads(json.dumps(payload, ensure_ascii=False))
        reversed_rows["campaigns"].reverse()
        with self.assertRaises(CampaignCatalogContractError):
            validate_campaign_catalog_v1(reversed_rows)
        leaking = json.loads(json.dumps(payload, ensure_ascii=False))
        leaking["notes"][0]["display_text"] = "/Users/private/catalog.json"
        with self.assertRaises(CampaignCatalogContractError):
            validate_campaign_catalog_v1(leaking)
        card = service.build_campaign_card_v1(
            registry_root=self.registry, package_id=PACKAGE_ID, number=payload["campaigns"][0]["number"]
        )
        extra = dict(card)
        extra["summary"] = payload["summary"]
        with self.assertRaises(CampaignCatalogContractError):
            validate_campaign_card_v1(extra)


class CampaignCatalogHttpTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.root = root
        passport = _passport()
        self.registry = write_synthetic_model_registry(root / "registry", passport)
        service._CACHE.clear()
        self.application = HttpSmokeApplication(
            HttpSmokeSettings(
                state_root=root / "state",
                runtime_root=root / "runtime",
                artifact_root=root / "artifacts",
                project_root=WEB_APP_DIR.parent,
                registry_root=self.registry,
                auth_database_path=root / "auth.sqlite3",
                auth_session_secret=TEST_SECRET,
                auth_argon2_time_cost=2,
                auth_argon2_memory_cost_kib=19_456,
                auth_argon2_parallelism=1,
            ),
            model_passport=passport,
        )
        provider = self.application.auth.identity_provider
        provider.bootstrap_admin(
            email="admin@example.org",
            password=ADMIN_PASSWORD,
            display_name="Тестовый администратор",
            update_existing=False,
        )
        admin_context, admin_token = provider.authenticate(
            "admin@example.org", ADMIN_PASSWORD, request_id="req_" + "a" * 24, client_key="127.0.0.1"
        )
        self.application.auth.admin.create_user(
            {
                "email": "viewer@example.org",
                "display_name": "Тестовый наблюдатель",
                "password": "Viewer-password-2026",
                "role_id": "viewer",
            },
            actor=admin_context,
        )
        _, viewer_token = provider.authenticate(
            "viewer@example.org", "Viewer-password-2026", request_id="req_" + "b" * 24, client_key="127.0.0.1"
        )
        self.cookies = {"admin": f"mmm_session={admin_token}", "viewer": f"mmm_session={viewer_token}"}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.application))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.application.close()
        service._CACHE.clear()
        self.temporary.cleanup()

    def _request(self, path: str, *, role: str | None = "admin") -> tuple[int, Any, Mapping[str, str]]:
        headers = {"Cookie": self.cookies[role]} if role else {}
        request = urllib.request.Request(self.base_url + path, headers=headers, method="GET")
        try:
            response = urllib.request.urlopen(request, timeout=3)
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read()), dict(exc.headers)
        with response:
            content_type = response.headers.get("Content-Type", "")
            content = response.read()
            parsed = json.loads(content) if content_type.startswith("application/json") else content
            return response.status, parsed, dict(response.headers)

    def _publish(self) -> dict[str, Any]:
        return write_synthetic_extension(
            self.registry / "package_artifacts" / PACKAGE_ID / ARTIFACT_VERSION,
            package_id=PACKAGE_ID,
            package_input_fingerprint=FINGERPRINT,
            model_run_id=MODEL_RUN_ID,
            scratch_dir=self.root / "scratch",
        )

    def test_routes_before_publication(self) -> None:
        status, payload, _ = self._request("/api/v1/campaign-catalog")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "unavailable")
        status, error, _ = self._request("/api/v1/campaign-catalog/1")
        self.assertEqual(status, 404)
        self.assertEqual(error["error"]["code"], "CAMPAIGN_CATALOG_NOT_PUBLISHED")
        status, error, _ = self._request("/api/v1/campaign-catalog/download")
        self.assertEqual(status, 404)
        self.assertEqual(error["error"]["code"], "CAMPAIGN_CATALOG_NOT_PUBLISHED")

    def test_routes_serve_the_published_catalog(self) -> None:
        metadata = self._publish()
        status, catalog, _ = self._request("/api/v1/campaign-catalog", role="viewer")
        self.assertEqual(status, 200)
        self.assertEqual(catalog["contract_name"], "campaign_catalog_v1")
        self.assertEqual(catalog["status"], "available")
        validate_campaign_catalog_v1(catalog)
        number = catalog["campaigns"][-1]["number"]
        status, card, _ = self._request(f"/api/v1/campaign-catalog/{number}", role="viewer")
        self.assertEqual(status, 200)
        self.assertEqual(card["campaign"], catalog["campaigns"][-1])
        status, error, _ = self._request("/api/v1/campaign-catalog/999")
        self.assertEqual(status, 404)
        self.assertEqual(error["error"]["code"], "CAMPAIGN_NOT_FOUND")
        status, error, _ = self._request("/api/v1/campaign-catalog?direction=all")
        self.assertEqual(status, 400)
        self.assertEqual(error["error"]["code"], "INVALID_QUERY")
        status, error, _ = self._request("/api/v1/campaign-catalog/0")
        self.assertEqual(status, 404)

        status, body, headers = self._request("/api/v1/campaign-catalog/download")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith(service.XLSX_MEDIA_TYPE))
        self.assertEqual(hashlib.sha256(body).hexdigest(), metadata["workbook"]["sha256"])
        self.assertIn("filename*=UTF-8''", headers["Content-Disposition"])
        self.assertEqual(headers["Cache-Control"], "no-store")

        status, error, _ = self._request("/api/v1/campaign-catalog/download", role="viewer")
        self.assertEqual(status, 403)
        status, _, _ = self._request("/api/v1/campaign-catalog", role=None)
        self.assertEqual(status, 401)

    def test_integrity_error_is_browser_safe(self) -> None:
        self._publish()
        data_path = self.registry / "package_artifacts" / PACKAGE_ID / ARTIFACT_VERSION / DATA_FILENAME
        data_path.write_bytes(data_path.read_bytes() + b" ")
        status, error, _ = self._request("/api/v1/campaign-catalog")
        self.assertEqual(status, 503)
        self.assertEqual(error["error"]["code"], "CAMPAIGN_CATALOG_UNAVAILABLE")
        self.assertNotIn(str(self.root), json.dumps(error, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
