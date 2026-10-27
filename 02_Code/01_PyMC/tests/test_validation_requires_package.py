"""Validation verdicts bind to the model package: without one, validation refuses instead of binding to None."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

PYMC_CODE_DIR = Path(__file__).resolve().parents[1]
if str(PYMC_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(PYMC_CODE_DIR))

import mmm_core  # noqa: E402,F401
from mmm_core.model_package_reader import ModelPackageError  # noqa: E402

FINGERPRINT = "package-fingerprint-1"


def load_validation():
    """Import mmm_core/validation.py privately, with arviz and mmm_core.fit stubbed: the package guard needs neither."""
    fit_stub = types.ModuleType("mmm_core.fit")
    fit_stub._make_geo_lagged_tensor_np = lambda *args, **kwargs: None
    fit_stub._safe_fit_key = lambda fit_key: fit_key.replace("/", "_").replace("::", "__")
    stubs = {"arviz": types.ModuleType("arviz"), "mmm_core.fit": fit_stub}
    saved = {name: sys.modules.get(name) for name in stubs}
    sys.modules.update(stubs)
    try:
        spec = importlib.util.spec_from_file_location(
            "mmm_core._validation_under_test", PYMC_CODE_DIR / "mmm_core" / "validation.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module  # dataclasses resolves annotations through sys.modules
        spec.loader.exec_module(module)
    finally:
        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
    return module


def write_run_config(run_dir: Path) -> None:
    (run_dir / "run_config.json").write_text(json.dumps({"fit_code_sha256": "code-sha"}), encoding="utf-8")


def write_package(run_dir: Path, fingerprint: str | None = FINGERPRINT) -> None:
    manifest = {} if fingerprint is None else {"package_input_fingerprint": fingerprint}
    (run_dir / "model_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


class RequirePackageFingerprintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validation = load_validation()

    def test_missing_manifest_is_refused_and_names_the_next_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ModelPackageError, "--mode package"):
                self.validation.require_package_fingerprint(tmp)

    def test_manifest_without_a_fingerprint_is_refused(self) -> None:
        for fingerprint in (None, ""):
            with tempfile.TemporaryDirectory() as tmp:
                write_package(Path(tmp), fingerprint)
                with self.assertRaises(ModelPackageError):
                    self.validation.require_package_fingerprint(tmp)

    def test_fingerprint_of_the_package_is_returned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_package(Path(tmp))
            self.assertEqual(self.validation.require_package_fingerprint(tmp), FINGERPRINT)


class BindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validation = load_validation()

    def test_binding_is_refused_without_a_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            write_run_config(run_dir)
            with self.assertRaises(ModelPackageError):
                self.validation.build_validation_binding(run_dir, [])

    def test_binding_records_the_package_and_keeps_its_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            write_run_config(run_dir)
            write_package(run_dir)
            extra = run_dir / "extra.csv"
            extra.write_text("a\n1\n", encoding="utf-8")
            binding = self.validation.build_validation_binding(run_dir, [extra])
            manifest_sha = hashlib.sha256((run_dir / "model_manifest.json").read_bytes()).hexdigest()
        self.assertEqual(binding["package_input_fingerprint"], FINGERPRINT)
        self.assertEqual(binding["model_manifest_sha256"], manifest_sha)
        self.assertEqual(list(binding["files_sha256"]), [str(extra)])
        self.assertEqual(
            set(binding),
            {
                "run_dir", "package_input_fingerprint", "model_manifest_sha256", "run_config_sha256", "panel_sha256",
                "fit_code_sha256", "files_sha256", "binding_sha256",
            },
        )


class VerdictWritersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validation = load_validation()

    def split(self):
        return self.validation.OOTSplit(train_end="2026-04-30", oot_start="2026-05-01", oot_end="2026-05-31")

    def test_oot_write_is_refused_before_any_other_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            with self.assertRaisesRegex(ModelPackageError, "bind to the model package"):
                self.validation.run_predictive_oot(
                    run_dir, run_dir / "panel.parquet", run_dir / "coverage.json", self.split(), write=True
                )
            self.assertEqual(list(run_dir.iterdir()), [])

    def test_oot_without_write_is_not_stopped_by_the_package_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            with self.assertRaisesRegex(ValueError, "exactly 12 fit contracts"):
                self.validation.run_predictive_oot(
                    run_dir, run_dir / "panel.parquet", run_dir / "coverage.json", self.split(), write=False
                )

    def test_independent_replay_is_refused_before_any_other_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            with self.assertRaisesRegex(ModelPackageError, "bind to the model package"):
                self.validation.run_independent_historical_response_replay(run_dir)
            self.assertEqual(list(run_dir.iterdir()), [])

    def test_prebuilt_replay_verdict_needs_the_package_and_carries_its_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            write_run_config(run_dir)
            reference, replayed = run_dir / "reference.csv", run_dir / "replayed.csv"
            reference.write_text("a\n1\n", encoding="utf-8")
            replayed.write_text("a\n1\n", encoding="utf-8")
            evaluated = mock.patch.object(
                self.validation, "evaluate_historical_response_replay", return_value={"status": "passed"}
            )
            with evaluated:
                with self.assertRaises(ModelPackageError):
                    self.validation.run_historical_response_replay_validation(run_dir, reference, replayed, write=True)
                self.assertFalse((run_dir / "historical_replay_validation.json").exists())
                write_package(run_dir)
                verdict = self.validation.run_historical_response_replay_validation(run_dir, reference, replayed, write=True)
            written = json.loads((run_dir / "historical_replay_validation.json").read_text(encoding="utf-8"))
        self.assertEqual(verdict["package_input_fingerprint"], FINGERPRINT)
        self.assertEqual(written["package_input_fingerprint"], FINGERPRINT)
        self.assertEqual(written["binding"]["package_input_fingerprint"], FINGERPRINT)


if __name__ == "__main__":
    unittest.main()
