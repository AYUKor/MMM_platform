from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


WEB_APP_DIR = Path(__file__).resolve().parents[1]
if str(WEB_APP_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_APP_DIR))

from contracts.mmm_fact_catalog_v1 import (  # noqa: E402
    build_mmm_fact_catalog,
    validate_mmm_fact_catalog,
)

try:
    import jsonschema
except ImportError:  # pragma: no cover - CI installs schema validation
    jsonschema = None


SCHEMA_PATH = WEB_APP_DIR / "contracts" / "mmm_fact_catalog_v1.schema.json"


class MmmFactCatalogV1Test(unittest.TestCase):
    def test_catalog_contains_reviewed_short_unique_facts(self) -> None:
        payload = build_mmm_fact_catalog()
        validate_mmm_fact_catalog(payload)
        facts = payload["facts"]
        self.assertEqual(len(facts), 20)
        self.assertEqual(len({fact["fact_id"] for fact in facts}), 20)
        self.assertTrue(all(len(fact["text"]) <= 280 for fact in facts))
        self.assertTrue(all(fact["text"].count(".") <= 2 for fact in facts))
        serialized = json.dumps(payload, ensure_ascii=False).lower()
        for forbidden in (
            "http://",
            "https://",
            "/users/",
            "file://",
            "openai",
            "backend",
            "model package",
            "worker",
            "posterior filename",
        ):
            self.assertNotIn(forbidden, serialized)

    @unittest.skipIf(jsonschema is None, "jsonschema is unavailable")
    def test_catalog_matches_json_schema(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(schema)
        self.assertEqual(list(validator.iter_errors(build_mmm_fact_catalog())), [])


if __name__ == "__main__":
    unittest.main()
