from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch


WEB_APP_DIR = Path(__file__).resolve().parents[1]
if str(WEB_APP_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_APP_DIR))

from api.http_smoke import (  # noqa: E402
    HttpSmokeApplication,
    HttpSmokeSettings,
    make_handler,
)
from services.product_navigation import (  # noqa: E402
    ProductNavigationStateError,
    ProductNavigationUnavailableError,
)


PASSPORT_FIXTURE = (
    WEB_APP_DIR / "tests" / "fixtures" / "model_passport_v1_synthetic.json"
)


class ProductNavigationHttpTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        passport = json.loads(PASSPORT_FIXTURE.read_text(encoding="utf-8"))
        self.application = HttpSmokeApplication(
            HttpSmokeSettings(
                state_root=root / "state",
                runtime_root=root / "runtime",
                artifact_root=root / "artifacts",
                project_root=root,
                registry_root=root / "registry",
            ),
            model_passport=passport,
        )
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_handler(self.application),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.application.close()
        self.temporary.cleanup()

    def request(self, path: str) -> tuple[int, dict]:
        request = urllib.request.Request(self.base_url + path, method="GET")
        try:
            response = urllib.request.urlopen(request, timeout=3)
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())
        with response:
            return response.status, json.loads(response.read())

    def test_navigation_endpoints_and_contract_discovery_return_200(self) -> None:
        expected = {
            "/api/v1/workspace/home": "workspace_home_v1",
            "/api/v1/calculations/history": "calculation_history_v1",
            "/api/v1/model/overview": "model_overview_v1",
            "/api/v1/help/catalog": "help_catalog_v1",
        }
        for path, contract_name in expected.items():
            with self.subTest(path=path):
                status, payload = self.request(path)
                self.assertEqual(status, 200)
                self.assertEqual(payload["contract_name"], contract_name)

        for name in (
            "workspace-home-v1",
            "calculation-history-v1",
            "model-overview-v1",
            "help-catalog-v1",
        ):
            with self.subTest(schema=name):
                status, payload = self.request(f"/api/v1/contracts/{name}.json")
                self.assertEqual(status, 200)
                self.assertEqual(payload["type"], "object")

    def test_history_query_validation_is_browser_safe(self) -> None:
        cases = {
            "/api/v1/calculations/history?page=0": (
                "Номер страницы и количество строк на странице заполнены некорректно."
            ),
            "/api/v1/calculations/history?unknown=value": (
                "Запрос содержит неподдерживаемые параметры."
            ),
            "/api/v1/calculations/history?status=running&status=failed": (
                "Каждый параметр запроса можно указать только один раз."
            ),
            "/api/v1/calculations/history?created_from=2026-07-20&created_to=2026-07-10": (
                "Диапазон дат заполнен некорректно."
            ),
        }
        for path, display_text in cases.items():
            with self.subTest(path=path):
                status, payload = self.request(path)
                self.assertEqual(status, 422)
                self.assertEqual(payload["error"]["code"], "PRODUCT_NAVIGATION_QUERY_INVALID")
                self.assertEqual(payload["error"]["display_text"], display_text)
                lowered = display_text.casefold()
                self.assertNotIn("query", lowered)
                self.assertNotIn("backend", lowered)

    def test_404_409_and_503_are_stable_and_do_not_leak_exceptions(self) -> None:
        status, payload = self.request("/api/v1/not-a-route")
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "ROUTE_NOT_FOUND")

        with patch.object(
            self.application,
            "model_overview",
            side_effect=ProductNavigationStateError("internal registry key secret"),
        ):
            status, payload = self.request("/api/v1/model/overview")
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"]["code"], "PRODUCT_NAVIGATION_INCONSISTENT")
        self.assertNotIn("registry", payload["error"]["display_text"].casefold())
        self.assertNotIn("secret", payload["error"]["display_text"].casefold())

        with patch.object(
            self.application,
            "help_catalog",
            side_effect=ProductNavigationUnavailableError("/Users/private/help.json"),
        ):
            status, payload = self.request("/api/v1/help/catalog")
        self.assertEqual(status, 503)
        self.assertEqual(payload["error"]["code"], "PRODUCT_NAVIGATION_UNAVAILABLE")
        self.assertNotIn("/Users/", payload["error"]["display_text"])

    def test_missing_active_model_is_an_explicit_200_state(self) -> None:
        self.application.model_passport = None
        status, payload = self.request("/api/v1/model/overview")
        self.assertEqual(status, 200)
        self.assertEqual(payload["active_model"]["status"]["code"], "unavailable")
        self.assertIsNone(payload["active_model"]["model_id"])


if __name__ == "__main__":
    unittest.main()
