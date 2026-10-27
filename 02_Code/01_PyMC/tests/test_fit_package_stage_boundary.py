"""Fit -> package boundary: a completed fit stops at fit_complete; package/export is a separate stage."""

from __future__ import annotations

import contextlib
import importlib.util
import io
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

from mmm_core import model  # noqa: E402

FIT_KEYS = ["N1/C1::turnover_per_user", "N1/C1::orders_per_user"]
IDENTITY_SHA = "identity-sha"
PACKAGE_SEQUENCE = ["build", "write", "export", "build", "write", "validate"]


class PackageSpies:
    """Stand-ins for the package/export functions that record the order in which they are called."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def patch(self):
        return mock.patch.multiple(
            model,
            build_package=self._build,
            write_package_artifacts=self._write,
            export_fit_design_metadata=self._export,
            validate_existing_model_run=self._validate,
        )

    def _build(self, run_dir, output_dir):
        self.calls.append("build")
        return ("built",)

    def _write(self, output_dir, built):
        self.calls.append("write")
        return {"model_manifest": str(Path(output_dir) / "model_manifest.json")}

    def _export(self, run_dir):
        self.calls.append("export")
        return {"status": "exported"}

    def _validate(self, run_dir, panel_override=None):
        self.calls.append("validate")
        return {"status": "validated"}


@contextlib.contextmanager
def fake_guarded_fit(status: str):
    """Replace mmm_core.fit (and its arviz import) with a stub that returns a card with the given status."""
    calls: list[dict] = []

    def run_guarded_fit(config, **kwargs):
        calls.append({"config": config, **kwargs})
        return {"status": status, "run_identity_sha256": IDENTITY_SHA, "posterior_files_n": len(FIT_KEYS)}

    module = types.ModuleType("mmm_core.fit")
    module.run_guarded_fit = run_guarded_fit
    with mock.patch.dict(sys.modules, {"mmm_core.fit": module}):
        yield calls


def write_identity(run_dir: Path) -> None:
    identity = {"expected_fit_keys": FIT_KEYS, "run_identity_sha256": IDENTITY_SHA}
    (run_dir / "run_identity.json").write_text(json.dumps(identity), encoding="utf-8")


def write_posterior(run_dir: Path, fit_key: str, payload: bytes = b"posterior") -> None:
    safe = model._safe_fit_key(fit_key)
    posterior = run_dir / f"posterior_{safe}.nc"
    posterior.write_bytes(payload)
    state = {"status": "complete", "fit_key": fit_key, "posterior_sha256": model.sha256_file(posterior)}
    (run_dir / f"fit_state_{safe}.json").write_text(json.dumps(state), encoding="utf-8")


def make_completed_run(run_dir: Path, *, card_status: str = "fit_complete", card_identity: str = IDENTITY_SHA) -> None:
    write_identity(run_dir)
    for fit_key in FIT_KEYS:
        write_posterior(run_dir, fit_key)
    card = {"status": card_status, "run_identity_sha256": card_identity, "posterior_files_n": len(FIT_KEYS)}
    (run_dir / "fit_execution_card.json").write_text(json.dumps(card), encoding="utf-8")
    for name in model.REQUIRED_REPLAY_EVIDENCE:
        (run_dir / name).write_text("evidence", encoding="utf-8")


class FitStageBoundaryTests(unittest.TestCase):
    def test_default_policy_is_the_safe_one(self) -> None:
        self.assertEqual(model.DEFAULT_PACKAGE_POLICY, "skip")
        self.assertEqual(model.PACKAGE_POLICIES, ("skip", "auto"))

    def test_fit_stops_at_fit_complete_by_default(self) -> None:
        spies = PackageSpies()
        with tempfile.TemporaryDirectory() as tmp, spies.patch(), fake_guarded_fit("fit_complete") as fit_calls:
            card = model.run_model_refresh(tmp, mode="fit", fit_config="fit.json")
            self.assertEqual(len(fit_calls), 1)
            self.assertEqual(spies.calls, [])
            self.assertEqual(card["status"], "fit_complete")
            self.assertIs(card["package_created"], False)
            self.assertEqual(card["package_policy"], "skip")
            self.assertIn("--mode package", card["next_stage"])
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_auto_policy_keeps_the_single_shot_sequence_and_card(self) -> None:
        spies = PackageSpies()
        with tempfile.TemporaryDirectory() as tmp, spies.patch(), fake_guarded_fit("fit_complete"):
            card = model.run_model_refresh(tmp, mode="fit", fit_config="fit.json", package="auto")
            self.assertEqual(spies.calls, PACKAGE_SEQUENCE)
            self.assertIs(card["package_created"], True)
            self.assertEqual(card["package_policy"], "auto")
            self.assertEqual(card["validated_package"], {"status": "validated"})
            written = json.loads((Path(tmp) / "model_fit_card.json").read_text(encoding="utf-8"))
            self.assertEqual(written, card)

    def test_incomplete_fit_never_packages(self) -> None:
        for status in ("prepared", "fit_partial"):
            for policy in model.PACKAGE_POLICIES:
                spies = PackageSpies()
                with tempfile.TemporaryDirectory() as tmp, spies.patch(), fake_guarded_fit(status):
                    card = model.run_model_refresh(tmp, mode="fit", fit_config="fit.json", package=policy)
                    self.assertEqual(card["status"], status)
                    self.assertNotIn("package_created", card)
                    self.assertEqual(spies.calls, [])
                    self.assertFalse((Path(tmp) / "model_fit_card.json").exists())

    def test_unknown_policy_fails_before_any_fit_work(self) -> None:
        with fake_guarded_fit("fit_complete") as fit_calls:
            with self.assertRaisesRegex(ValueError, "package policy"):
                model.run_model_refresh("run", mode="fit", fit_config="fit.json", package="always")
        self.assertEqual(fit_calls, [])


class PackageStageTests(unittest.TestCase):
    def test_builds_the_first_package_of_a_completed_fit(self) -> None:
        spies = PackageSpies()
        with tempfile.TemporaryDirectory() as tmp, spies.patch():
            run_dir = Path(tmp)
            make_completed_run(run_dir)
            card = model.run_model_refresh(run_dir, mode="package")
            self.assertEqual(spies.calls, PACKAGE_SEQUENCE)
            self.assertEqual(card["status"], "fit_complete")
            self.assertIs(card["package_created"], True)
            self.assertEqual(card["package_policy"], "stage")
            written = json.loads((run_dir / "model_fit_card.json").read_text(encoding="utf-8"))
            self.assertEqual(written, card)

    def test_check_only_writes_nothing(self) -> None:
        spies = PackageSpies()
        with tempfile.TemporaryDirectory() as tmp, spies.patch():
            run_dir = Path(tmp)
            make_completed_run(run_dir)
            card = model.run_model_refresh(run_dir, mode="package", write=False)
            self.assertEqual(card["status"], "package_preconditions_ok")
            self.assertIs(card["package_created"], False)
            self.assertEqual(spies.calls, [])
            self.assertFalse((run_dir / "model_fit_card.json").exists())

    def refuse(self, run_dir: Path, exception: type[Exception], pattern: str) -> None:
        spies = PackageSpies()
        with spies.patch(), self.assertRaisesRegex(exception, pattern):
            model.package_completed_fit(run_dir)
        self.assertEqual(spies.calls, [])
        self.assertFalse((run_dir / "model_fit_card.json").exists())

    def test_refuses_a_directory_that_is_not_a_guarded_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.refuse(Path(tmp), ValueError, "expected_fit_keys")

    def test_refuses_an_incomplete_or_foreign_fit_card(self) -> None:
        for status in ("prepared", "fit_partial"):
            with tempfile.TemporaryDirectory() as tmp:
                make_completed_run(Path(tmp), card_status=status)
                self.refuse(Path(tmp), ValueError, "not complete")
        with tempfile.TemporaryDirectory() as tmp:
            make_completed_run(Path(tmp), card_identity="another-identity")
            self.refuse(Path(tmp), ValueError, "different run identity")

    def test_refuses_missing_incomplete_or_tampered_posteriors(self) -> None:
        safe = model._safe_fit_key(FIT_KEYS[0])
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            make_completed_run(run_dir)
            (run_dir / f"posterior_{safe}.nc").unlink()
            (run_dir / f"fit_state_{safe}.json").unlink()
            self.refuse(run_dir, ValueError, "Posterior is missing")
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            make_completed_run(run_dir)
            (run_dir / f"posterior_{safe}.nc").unlink()
            self.refuse(run_dir, ValueError, "Incomplete cached fit state")
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            make_completed_run(run_dir)
            (run_dir / f"posterior_{safe}.nc").write_bytes(b"tampered")
            self.refuse(run_dir, ValueError, "hash mismatch")

    def test_refuses_missing_post_fit_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            make_completed_run(run_dir)
            (run_dir / "diagnostics_summary.csv").unlink()
            self.refuse(run_dir, ValueError, "evidence is missing")

    def test_never_overwrites_an_existing_package(self) -> None:
        for name in ("model_manifest.json", "model_fit_card.json"):
            spies = PackageSpies()
            with tempfile.TemporaryDirectory() as tmp, spies.patch():
                run_dir = Path(tmp)
                make_completed_run(run_dir)
                (run_dir / name).write_text("existing", encoding="utf-8")
                with self.assertRaisesRegex(FileExistsError, "never overwrites"):
                    model.package_completed_fit(run_dir)
                self.assertEqual((run_dir / name).read_text(encoding="utf-8"), "existing")
                self.assertEqual(spies.calls, [])


def fake_jobs(final_effects):
    """Patch the fit subprocess: each job stores its posterior; the last one also writes the cards the CLI would."""
    commands: list[list[str]] = []

    class FakeJob:
        def __init__(self, command, **kwargs):
            commands.append(list(command))
            run_dir = Path(command[command.index("--run-dir") + 1])
            fit_key = command[command.index("--only-fit") + 1]
            write_posterior(run_dir, fit_key)
            if fit_key == FIT_KEYS[-1]:
                final_effects(run_dir)
            self.pid = 4242

        def poll(self):
            return 0

    @contextlib.contextmanager
    def patched():
        with mock.patch.object(model.subprocess, "Popen", FakeJob):
            yield commands

    return patched()


def final_cards(status: str = "fit_complete", *, model_card: bool = False):
    def effects(run_dir: Path) -> None:
        card = {"status": status, "run_identity_sha256": IDENTITY_SHA}
        (run_dir / "fit_execution_card.json").write_text(json.dumps(card), encoding="utf-8")
        if model_card:
            (run_dir / "model_fit_card.json").write_text(json.dumps({**card, "package_created": True}), encoding="utf-8")

    return effects


def orchestrate(run_dir: Path, **kwargs):
    return model.orchestrate_guarded_fit(run_dir, fit_config=run_dir / "fit.json", poll_seconds=0.01, **kwargs)


class OrchestratorBoundaryTests(unittest.TestCase):
    def test_default_skip_accepts_a_fit_complete_card_as_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, fake_jobs(final_cards()) as commands:
            run_dir = Path(tmp)
            write_identity(run_dir)
            status = orchestrate(run_dir)
            persisted = json.loads((run_dir / "fit_orchestrator_status.json").read_text(encoding="utf-8"))
        self.assertEqual(status["status"], "complete")
        self.assertEqual((status["package_policy"], status["package_created"]), ("skip", False))
        self.assertEqual((persisted["package_policy"], persisted["package_created"]), ("skip", False))
        self.assertEqual(len(commands), len(FIT_KEYS))
        for command in commands:
            self.assertEqual(command[command.index("--package") + 1], "skip")

    def test_skip_refuses_a_card_that_is_not_fit_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, fake_jobs(final_cards("fit_partial")):
            run_dir = Path(tmp)
            write_identity(run_dir)
            with self.assertRaisesRegex(RuntimeError, "not fit_complete"):
                orchestrate(run_dir)
            persisted = json.loads((run_dir / "fit_orchestrator_status.json").read_text(encoding="utf-8"))
        self.assertEqual(persisted["status"], "failed")

    def test_auto_requires_the_model_fit_card(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, fake_jobs(final_cards()):
            run_dir = Path(tmp)
            write_identity(run_dir)
            with self.assertRaisesRegex(RuntimeError, "final model package card is missing"):
                orchestrate(run_dir, package="auto")
        with tempfile.TemporaryDirectory() as tmp, fake_jobs(final_cards(model_card=True)) as commands:
            run_dir = Path(tmp)
            write_identity(run_dir)
            status = orchestrate(run_dir, package="auto")
        self.assertEqual((status["package_policy"], status["package_created"]), ("auto", True))
        for command in commands:
            self.assertEqual(command[command.index("--package") + 1], "auto")

    def test_unknown_policy_fails_before_any_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, fake_jobs(final_cards()) as commands:
            run_dir = Path(tmp)
            write_identity(run_dir)
            with self.assertRaisesRegex(ValueError, "package policy"):
                orchestrate(run_dir, package="always")
            self.assertFalse((run_dir / "job_logs").exists())
        self.assertEqual(commands, [])


def run_cli(*argv: str) -> dict[str, tuple[tuple, dict]]:
    spec = importlib.util.spec_from_file_location("pymc_model_cli_under_test", PYMC_CODE_DIR / "02_pymc_model.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    calls: dict[str, tuple[tuple, dict]] = {}

    def recorder(name: str):
        def call(*args, **kwargs):
            calls[name] = (args, kwargs)
            return {"status": "stub"}

        return call

    with (
        mock.patch.object(cli, "run_model_refresh", recorder("refresh")),
        mock.patch.object(cli, "orchestrate_guarded_fit", recorder("orchestrate")),
        mock.patch.object(sys, "argv", ["02_pymc_model.py", *argv]),
        contextlib.redirect_stdout(io.StringIO()),
    ):
        cli.main()
    return calls


class CliBoundaryTests(unittest.TestCase):
    FIT = ("--mode", "fit", "--run-dir", "/tmp/mmm_stage_boundary_run", "--fit-config", "/tmp/mmm_stage_boundary.json")

    def test_fit_defaults_to_skip_and_forwards_an_explicit_policy(self) -> None:
        self.assertEqual(run_cli(*self.FIT)["refresh"][1]["package"], "skip")
        self.assertEqual(run_cli(*self.FIT, "--package", "auto")["refresh"][1]["package"], "auto")
        self.assertEqual(run_cli(*self.FIT, "--package", "skip")["refresh"][1]["package"], "skip")

    def test_orchestrate_forwards_the_policy(self) -> None:
        self.assertEqual(run_cli(*self.FIT, "--orchestrate")["orchestrate"][1]["package"], "skip")
        self.assertEqual(run_cli(*self.FIT, "--orchestrate", "--package", "auto")["orchestrate"][1]["package"], "auto")

    def test_package_flag_is_rejected_outside_fit_mode(self) -> None:
        for mode in ("validate", "replay", "package"):
            with self.assertRaisesRegex(ValueError, "applies to --mode fit only"):
                run_cli("--mode", mode, "--run-dir", "/tmp/mmm_stage_boundary_run", "--package", "auto")

    def test_package_mode_needs_an_explicit_run_dir(self) -> None:
        with self.assertRaisesRegex(ValueError, "--run-dir is required"):
            run_cli("--mode", "package")

    def test_package_mode_dispatches_to_the_package_stage(self) -> None:
        calls = run_cli("--mode", "package", "--run-dir", "/tmp/mmm_stage_boundary_run", "--no-write")
        args, kwargs = calls["refresh"]
        self.assertEqual(kwargs["mode"], "package")
        self.assertIs(kwargs["write"], False)
        self.assertEqual(Path(args[0]), Path("/tmp/mmm_stage_boundary_run"))


if __name__ == "__main__":
    unittest.main()
