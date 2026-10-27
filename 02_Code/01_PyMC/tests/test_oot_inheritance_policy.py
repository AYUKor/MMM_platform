"""OOT inheritance policy v1: synthetic run folders, no sampling, no real data."""
from __future__ import annotations

import copy
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE))
from mmm_core import model_registry
from mmm_core.model_package import (
    ADMISSION_DECISION_SCHEMA,
    OOT_BASIS_INHERITED,
    OOT_INHERITANCE_POLICY,
    build_package,
    evaluate_oot_inheritance,
    index_rows,
    inheritance_source_snapshot,
    inheritance_spec_identity,
    inherited_oot_issues,
    inherited_oot_issues_for_run_dir,
    sha256_file,
    sha256_json,
    write_package_artifacts,
)
from mmm_core.validation import run_inherited_oot_validation

SEGMENTS = ["ТС5/Онлайн", "ТС5/Оффлайн", "ТСХ/Онлайн", "ТСХ/Оффлайн"]
TARGETS = ["turnover_per_user", "orders_per_user", "avg_basket"]
FIT_KEYS = sorted(f"{segment}::{target}" for segment in SEGMENTS for target in TARGETS)
SLOW_FIT = "ТС5/Оффлайн::turnover_per_user"
SPEND = ["spend_Indoor", "spend_OOH", "spend_Нац_ТВ", "spend_Радио"]


def run_config(kind: str, panel: Path) -> dict:
    """Source (validated through April) and target (refit through June) differ only where policy v1 allows."""
    target = kind == "target"
    return {
        "expected_fit_keys": FIT_KEYS,
        "fit_runtime_version": "1.2.0",
        "fit_code_sha256": "c" * 64,
        "lag_mode": "calendar_days_v1",
        "media_history": {"lag_mode": "calendar_days_v1", "path": f"/ledger/{kind}.parquet", "sha256": kind,
                          "calendar_code_sha256": "d" * 64},
        "mode": "production" if target else "pilot",
        "run_label": f"run_{kind}",
        "run_variant": f"variant_{kind}",
        "config_path": f"/configs/{kind}.json",
        "config_sha256": kind * 8,
        "panel_path": str(panel),
        "panel_sha256": ("b" if target else "a") * 64,
        "train_start": "2025-01-01",
        "train_end": "2026-06-30" if target else "2026-04-30",
        "holdout_start": "2026-07-01" if target else "2026-05-01",
        "holdout_end": "2026-07-31" if target else "2026-05-31",
        "cfg": {"draws": 2000 if target else 1000, "tune": 2000 if target else 1000, "chains": 4 if target else 2,
                "decay_grid_step": 0.05 if target else 0.1, "l_max": 14, "top_n_geos": None,
                "target_accept": 0.99, "fourier_pairs": 2, "use_jax": True},
        "baseline_structure": "geo",
        "error_structure": "global",
        "media_scaling_mode": "tier_p95_shrunk",
        "spend_active_base": list(reversed(SPEND)) if target else list(SPEND),
        "spend_active_model_universe": list(reversed(SPEND)) if target else list(SPEND),
        "training_audit": {"model_geos": 223 if target else 221, "spend_active_base": list(SPEND)},
    }


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def write_diagnostics(path: Path, *, overrides: dict | None = None, drop: str | None = None) -> None:
    rows = []
    for fit_key in FIT_KEYS:
        if fit_key == drop:
            continue
        row = {"fit_key": fit_key, "rhat_max": "1.003", "ess_bulk_min": "1500", "ess_per_draw": "0.25",
               "n_divergences": "0", "status": "OK"}
        if fit_key == SLOW_FIT:
            row.update({"rhat_max": "1.0134", "ess_bulk_min": "328.5418", "ess_per_draw": "0.041068"})
        row.update((overrides or {}).get(fit_key, {}))
        rows.append(row)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class Fixture:
    """Source and target run folders plus a matching owner decision."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.panel = root / "panel.parquet"
        self.panel.write_bytes(b"synthetic panel bytes")
        self.source, self.target = root / "source", root / "target"
        self.source.mkdir()
        self.target.mkdir()
        write_json(self.source / "run_config.json", run_config("source", self.panel))
        write_json(self.target / "run_config.json", run_config("target", self.panel))
        write_diagnostics(self.target / "diagnostics_summary.csv")
        self.fingerprint = build_package(self.target, self.target)[0]["package_input_fingerprint"]
        write_json(self.target / "model_manifest.json", {"package_input_fingerprint": self.fingerprint})
        write_json(self.target / "historical_replay_validation.json",
                   {"status": "passed", "package_input_fingerprint": self.fingerprint,
                    "binding": {"package_input_fingerprint": self.fingerprint}})
        self.source_oot = {
            "schema_version": "1.0.0", "status": "passed", "activation_eligible": True,
            "turnover_required_pass": True, "full_turnover_geo_coverage": True,
            "quality_counts": {"primary": 7, "caution": 3, "diagnostic": 2},
            "split": {"train_end": "2026-04-30", "oot_start": "2026-05-01", "oot_end": "2026-05-31",
                      "development_seen": False, "evidence_role": "sealed_activation_oot"},
            "binding": {"run_config_sha256": sha256_file(self.source / "run_config.json")},
            "package_input_fingerprint": "3" * 64,
        }
        write_json(self.source / "oot_validation.json", self.source_oot)
        self.decision_path = root / "decision.json"
        self.write_decision()

    def write_decision(self, **changes: object) -> dict:
        decision = {
            "schema": ADMISSION_DECISION_SCHEMA,
            "status": "approved",
            "decided_by": "owner",
            "policy": {"name": OOT_INHERITANCE_POLICY, "version": "1"},
            "owner_messages": [{"id": "msg-1", "text": "approved"}],
            "source": {"oot_validation_sha256": sha256_file(self.source / "oot_validation.json"),
                       "package_input_fingerprint": "3" * 64},
            "target": {"panel_sha256": sha256_file(self.panel),
                       "run_config_sha256": sha256_file(self.target / "run_config.json"),
                       "train_end": "2026-06-30"},
            "conditions": {"no_tuning_after_may_quality_seen": True},
            "accepted_exceptions": [{"fit_key": SLOW_FIT, "metric": "ess_per_draw", "observed": 0.041068,
                                     "threshold": 0.1, "accepted_by": "owner", "message_id": "msg-1"}],
            "monitoring": {"post_release_oot": {"period": "2026-07"}},
        }
        decision.update(changes)
        write_json(self.decision_path, decision)
        return decision

    def diagnostics_rows(self) -> list[dict]:
        with (self.target / "diagnostics_summary.csv").open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    def evaluate(self, decision: dict | None = None, *, config: dict | None = None, diagnostics: dict | None = None,
                 replay: dict | None = None, source: dict | None = None, fit_keys: list[str] | None = None) -> dict:
        target_config = config or json.loads((self.target / "run_config.json").read_text(encoding="utf-8"))
        return evaluate_oot_inheritance(
            decision or json.loads(self.decision_path.read_text(encoding="utf-8")),
            source or inheritance_source_snapshot(
                json.loads((self.source / "oot_validation.json").read_text(encoding="utf-8")),
                sha256_file(self.source / "oot_validation.json"),
                json.loads((self.source / "run_config.json").read_text(encoding="utf-8")),
                self.source,
            ),
            target_config,
            target_panel_sha256=sha256_file(self.panel),
            target_run_config_sha256=sha256_file(self.target / "run_config.json"),
            target_fingerprint=self.fingerprint,
            diagnostics_by_fit=diagnostics if diagnostics is not None else index_rows(self.diagnostics_rows(), "fit_key"),
            expected_fit_keys=fit_keys if fit_keys is not None else list(target_config["expected_fit_keys"]),
            replay_validation=replay if replay is not None else {"status": "passed",
                                                                 "package_input_fingerprint": self.fingerprint},
        )

    def issue(self) -> dict:
        return run_inherited_oot_validation(self.target, self.source, self.decision_path, write=True)


class PolicyConditionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fx = Fixture(Path(self._tmp.name))

    def assertIssue(self, result: dict, code: str) -> None:
        self.assertIn(code, result["issues"], result["checks"])

    def test_all_conditions_hold_with_the_accepted_exception(self) -> None:
        result = self.fx.evaluate()
        self.assertEqual(result["issues"], [], result["checks"])
        self.assertEqual([item["fit_key"] for item in result["accepted_exceptions_applied"]], [SLOW_FIT])

    def test_allowed_differences_are_ignored_and_spend_order_does_not_matter(self) -> None:
        source, target = (json.loads((self.fx.root / name / "run_config.json").read_text(encoding="utf-8"))
                          for name in ("source", "target"))
        self.assertEqual(inheritance_spec_identity(source), inheritance_spec_identity(target))
        self.assertNotEqual(source["spend_active_base"], target["spend_active_base"])

    def test_changed_specification_is_a_blocker(self) -> None:
        for path, value in [(("baseline_structure",), "tier_geo"), (("cfg", "l_max"), 21), (("fit_code_sha256",), "e" * 64),
                            (("lag_mode",), "row_order"), (("spend_active_base",), SPEND + ["spend_New"])]:
            config = json.loads((self.fx.target / "run_config.json").read_text(encoding="utf-8"))
            node = config
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] = value
            result = self.fx.evaluate(config=config)
            self.assertIssue(result, "SAME_SPECIFICATION")

    def test_training_window_must_extend_the_validated_window(self) -> None:
        config = json.loads((self.fx.target / "run_config.json").read_text(encoding="utf-8"))
        config["train_end"] = "2026-04-30"
        self.assertIssue(self.fx.evaluate(config=config), "TRAINING_WINDOW_EXTENDS_SOURCE")

    def test_decision_must_be_an_approved_owner_decision(self) -> None:
        base = json.loads(self.fx.decision_path.read_text(encoding="utf-8"))
        for change in [{"status": "draft"}, {"decided_by": ""}, {"owner_messages": []},
                       {"owner_messages": [{"id": "x", "text": ""}]}, {"schema": "other"}]:
            self.assertIssue(self.fx.evaluate(decision={**base, **change}), "DECISION_APPROVED_BY_OWNER")

    def test_policy_version_is_pinned(self) -> None:
        base = json.loads(self.fx.decision_path.read_text(encoding="utf-8"))
        for policy in [{"name": OOT_INHERITANCE_POLICY, "version": "2"}, {"name": "other", "version": "1"}, {}]:
            self.assertIssue(self.fx.evaluate(decision={**base, "policy": policy}), "DECISION_POLICY_VERSION")

    def test_decision_must_pin_the_exact_source_and_target(self) -> None:
        base = json.loads(self.fx.decision_path.read_text(encoding="utf-8"))
        wrong_source = copy.deepcopy(base)
        wrong_source["source"]["oot_validation_sha256"] = "0" * 64
        self.assertIssue(self.fx.evaluate(decision=wrong_source), "DECISION_PINS_SOURCE_OOT")
        wrong_fp = copy.deepcopy(base)
        wrong_fp["source"]["package_input_fingerprint"] = "0" * 64
        self.assertIssue(self.fx.evaluate(decision=wrong_fp), "DECISION_PINS_SOURCE_OOT")
        for key in ("panel_sha256", "run_config_sha256", "train_end"):
            wrong_target = copy.deepcopy(base)
            wrong_target["target"][key] = "0" * 64 if key.endswith("256") else "2026-05-31"
            self.assertIssue(self.fx.evaluate(decision=wrong_target), "DECISION_PINS_TARGET")

    def test_source_oot_must_be_sealed_passed_and_not_itself_inherited(self) -> None:
        base = copy.deepcopy(self.fx.source_oot)
        mutations = {
            "status": lambda o: o.update(status="shadow_passed_not_activation_evidence"),
            "eligible": lambda o: o.update(activation_eligible=False),
            "development_seen": lambda o: o["split"].update(development_seen=True),
            "role": lambda o: o["split"].update(evidence_role="shadow_development_seen"),
            "turnover": lambda o: o.update(turnover_required_pass=False),
            "coverage": lambda o: o.update(full_turnover_geo_coverage=False),
            "chained": lambda o: o.update(evidence_basis=OOT_BASIS_INHERITED),
        }
        for name, mutate in mutations.items():
            oot = copy.deepcopy(base)
            mutate(oot)
            snapshot = inheritance_source_snapshot(oot, sha256_file(self.fx.source / "oot_validation.json"),
                                                   json.loads((self.fx.source / "run_config.json").read_text(encoding="utf-8")),
                                                   self.fx.source)
            self.assertIssue(self.fx.evaluate(source=snapshot), "SOURCE_OOT_SEALED_AND_PASSED")

    def test_all_twelve_fits_are_required(self) -> None:
        config = json.loads((self.fx.target / "run_config.json").read_text(encoding="utf-8"))
        config["expected_fit_keys"] = FIT_KEYS[:-1]
        self.assertIssue(self.fx.evaluate(config=config), "SAME_TWELVE_FITS")
        write_diagnostics(self.fx.target / "diagnostics_summary.csv", drop=FIT_KEYS[0])
        self.assertIssue(self.fx.evaluate(), "SAME_TWELVE_FITS")

    def test_runtime_violations_need_a_matching_accepted_exception(self) -> None:
        def run(overrides: dict, exceptions: list | None = None) -> dict:
            write_diagnostics(self.fx.target / "diagnostics_summary.csv", overrides=overrides)
            base = json.loads(self.fx.decision_path.read_text(encoding="utf-8"))
            if exceptions is not None:
                base["accepted_exceptions"] = exceptions
            return self.fx.evaluate(decision=base)

        self.assertEqual(run({})["issues"], [])
        self.assertIssue(run({}, exceptions=[]), "RUNTIME_ACCEPTANCE_OR_ACCEPTED_EXCEPTION")
        worse = {SLOW_FIT: {"ess_per_draw": "0.02"}}
        self.assertIssue(run(worse), "RUNTIME_ACCEPTANCE_OR_ACCEPTED_EXCEPTION")  # exception pinned to 0.041068
        other_fit = {FIT_KEYS[0]: {"ess_per_draw": "0.09"}}
        self.assertIssue(run(other_fit), "RUNTIME_ACCEPTANCE_OR_ACCEPTED_EXCEPTION")
        self.assertIssue(run({FIT_KEYS[0]: {"rhat_max": "1.06"}}), "RUNTIME_ACCEPTANCE_OR_ACCEPTED_EXCEPTION")
        self.assertIssue(run({FIT_KEYS[0]: {"n_divergences": "6"}}), "RUNTIME_ACCEPTANCE_OR_ACCEPTED_EXCEPTION")
        self.assertIssue(run({FIT_KEYS[0]: {"rhat_max": ""}}), "RUNTIME_ACCEPTANCE_OR_ACCEPTED_EXCEPTION")
        for incomplete in ({"accepted_by": ""}, {"message_id": ""}, {"threshold": 0.05}, {"metric": "rhat_max"}):
            exception = {"fit_key": SLOW_FIT, "metric": "ess_per_draw", "observed": 0.041068, "threshold": 0.1,
                         "accepted_by": "owner", "message_id": "msg-1", **incomplete}
            self.assertIssue(run({}, exceptions=[exception]), "RUNTIME_ACCEPTANCE_OR_ACCEPTED_EXCEPTION")

    def test_attestation_replay_and_monitoring_are_required(self) -> None:
        base = json.loads(self.fx.decision_path.read_text(encoding="utf-8"))
        self.assertIssue(self.fx.evaluate(decision={**base, "conditions": {}}), "NO_TUNING_AFTER_SOURCE_OOT_ATTESTED")
        self.assertIssue(self.fx.evaluate(decision={**base, "monitoring": {}}), "POST_RELEASE_MONITORING_RECORDED")
        for replay in [{}, {"status": "failed", "package_input_fingerprint": self.fx.fingerprint},
                       {"status": "passed", "package_input_fingerprint": "0" * 64}]:
            self.assertIssue(self.fx.evaluate(replay=replay), "REPLAY_PASSED_AND_BOUND")


class IssuanceAndVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fx = Fixture(Path(self._tmp.name))

    def issued(self) -> dict:
        self.fx.issue()
        return json.loads((self.fx.target / "oot_validation.json").read_text(encoding="utf-8"))

    def issues(self, oot: dict) -> list[str]:
        return inherited_oot_issues_for_run_dir(self.fx.target, oot, self.fx.fingerprint)

    def test_issued_file_is_marked_bound_and_verifies(self) -> None:
        oot = self.issued()
        self.assertEqual((oot["status"], oot["activation_eligible"], oot["evidence_basis"]),
                         ("passed", True, OOT_BASIS_INHERITED))
        self.assertEqual(oot["package_input_fingerprint"], self.fx.fingerprint)
        self.assertEqual(oot["binding"]["package_input_fingerprint"], self.fx.fingerprint)
        self.assertEqual(oot["inheritance"]["decision"]["content_sha256"], sha256_json(oot["inheritance"]["decision"]["content"]))
        self.assertEqual(self.issues(oot), [])

    def test_issuance_never_overwrites_and_refuses_unmet_conditions(self) -> None:
        self.issued()
        with self.assertRaises(FileExistsError):
            self.fx.issue()
        (self.fx.target / "oot_validation.json").unlink()
        self.fx.write_decision(status="draft")
        with self.assertRaisesRegex(ValueError, "DECISION_APPROVED_BY_OWNER"):
            self.fx.issue()
        self.assertFalse((self.fx.target / "oot_validation.json").exists())
        preview = run_inherited_oot_validation(self.fx.target, self.fx.source, self.fx.decision_path, write=False)
        self.assertFalse(preview["activation_eligible"])
        self.assertNotEqual(preview["status"], "passed")

    def test_issuance_needs_a_replay_bound_to_this_package(self) -> None:
        write_json(self.fx.target / "historical_replay_validation.json",
                   {"status": "passed", "package_input_fingerprint": "0" * 64})
        with self.assertRaisesRegex(ValueError, "REPLAY_PASSED_AND_BOUND"):
            self.fx.issue()

    def test_issuance_needs_a_built_package(self) -> None:
        (self.fx.target / "model_manifest.json").unlink()
        with self.assertRaisesRegex(Exception, "Build the package first"):
            self.fx.issue()

    def test_tampering_with_the_issued_file_is_detected(self) -> None:
        oot = self.issued()
        edited = copy.deepcopy(oot)
        edited["inheritance"]["decision"]["content"]["status"] = "draft"
        self.assertEqual(self.issues(edited), ["INHERITANCE_DECISION_HASH_MISMATCH"])
        edited = copy.deepcopy(oot)
        del edited["inheritance"]
        self.assertEqual(self.issues(edited), ["INHERITANCE_RECORD_MISSING"])
        edited = copy.deepcopy(oot)
        edited["inheritance"]["policy"]["version"] = "2"
        self.assertEqual(self.issues(edited), ["INHERITANCE_POLICY_VERSION_MISMATCH"])
        edited = copy.deepcopy(oot)
        edited["inheritance"]["source"]["spec_identity"]["/baseline_structure"] = "other"
        self.assertEqual(self.issues(edited), ["INHERITANCE_SOURCE_SNAPSHOT_INVALID"])
        edited = copy.deepcopy(oot)
        edited["inheritance"]["source"]["development_seen"] = True
        self.assertIn("SOURCE_OOT_SEALED_AND_PASSED", self.issues(edited))
        self.assertIn("INHERITANCE_SOURCE_DIFFERS_FROM_SOURCE_FILES", self.issues(edited))
        edited = copy.deepcopy(oot)
        edited["inheritance"]["source"]["quality_counts"] = {"primary": 12}
        self.assertEqual(self.issues(edited), ["INHERITANCE_SOURCE_DIFFERS_FROM_SOURCE_FILES"])
        edited = copy.deepcopy(oot)
        edited["binding"]["package_input_fingerprint"] = "0" * 64
        self.assertEqual(self.issues(edited), ["INHERITANCE_BINDING_MISMATCH"])
        edited = copy.deepcopy(oot)
        edited["package_input_fingerprint"] = "0" * 64
        self.assertEqual(self.issues(edited), ["INHERITANCE_FINGERPRINT_MISMATCH"])

    def test_changing_the_validated_source_after_issuance_is_detected(self) -> None:
        oot = self.issued()
        changed = {**self.fx.source_oot, "quality_counts": {"primary": 12}}
        write_json(self.fx.source / "oot_validation.json", changed)
        self.assertIn("INHERITANCE_SOURCE_DIFFERS_FROM_SOURCE_FILES", self.issues(oot))

    def test_changing_the_refit_after_issuance_is_detected(self) -> None:
        oot = self.issued()
        write_diagnostics(self.fx.target / "diagnostics_summary.csv", overrides={FIT_KEYS[0]: {"rhat_max": "1.2"}})
        self.assertEqual(self.issues(oot), ["RUNTIME_ACCEPTANCE_OR_ACCEPTED_EXCEPTION"])

    def test_package_builder_accepts_valid_and_blocks_invalid_inherited_evidence(self) -> None:
        oot = self.issued()
        manifest = build_package(self.fx.target, self.fx.target)[0]
        self.assertEqual(manifest["package_input_fingerprint"], self.fx.fingerprint)
        self.assertFalse([code for code in manifest["production_blockers"] if "OOT" in code or "REPLAY" in code])
        self.assertTrue(manifest["artifact_status"]["oot_validation_passed"])
        self.assertEqual(manifest["oot_basis"]["evidence_basis"], OOT_BASIS_INHERITED)
        self.assertEqual(manifest["oot_basis"]["decision_sha256"], oot["inheritance"]["decision"]["content_sha256"])
        self.assertEqual(manifest["oot_basis"]["issues"], [])

        tampered = copy.deepcopy(oot)
        tampered["inheritance"]["decision"]["content"]["decided_by"] = "someone else"
        write_json(self.fx.target / "oot_validation.json", tampered)
        manifest = build_package(self.fx.target, self.fx.target)[0]
        self.assertIn("INVALID_INHERITED_OOT_VALIDATION", manifest["production_blockers"])
        self.assertFalse(manifest["artifact_status"]["oot_validation_passed"])
        self.assertEqual(manifest["oot_basis"]["issues"], ["INHERITANCE_DECISION_HASH_MISMATCH"])

    def test_inherited_file_without_a_record_cannot_pass_the_builder(self) -> None:
        self.issued()
        write_json(self.fx.target / "oot_validation.json",
                   {"status": "passed", "activation_eligible": True, "evidence_basis": OOT_BASIS_INHERITED,
                    "package_input_fingerprint": self.fx.fingerprint})
        manifest = build_package(self.fx.target, self.fx.target)[0]
        self.assertIn("INVALID_INHERITED_OOT_VALIDATION", manifest["production_blockers"])

    def test_registry_rechecks_inherited_evidence_at_production_activation(self) -> None:
        oot = self.issued()
        registration = {
            "activation_status_at_registration": "production_ready",
            "production_blockers_at_registration": [],
            "run_dir": str(self.fx.target),
            "package_input_fingerprint": self.fx.fingerprint,
        }
        model_registry._assert_production_eligible(registration)
        tampered = copy.deepcopy(oot)
        tampered["inheritance"]["policy"]["version"] = "2"
        write_json(self.fx.target / "oot_validation.json", tampered)
        with self.assertRaisesRegex(ValueError, "INHERITANCE_POLICY_VERSION_MISMATCH"):
            model_registry._assert_production_eligible(registration)

    def test_manifest_rebuild_keeps_verdicts_bound_but_a_design_metadata_reexport_does_not(self) -> None:
        """Why the lifecycle refreshes the manifest with model_package.py and not with `--mode replay`.

        `replay` re-exports fit_design_metadata.json (a new generated_at_utc); the file is hashed into the fingerprint of a
        guarded-fit package, so every verdict written for the earlier fingerprint becomes stale.
        """
        target = self.fx.target
        write_json(target / "fit_design_metadata.json", {"generated_at_utc": "2026-10-27T14:48:00+00:00", "fits": {}})
        built = build_package(target, target)
        fingerprint = built[0]["package_input_fingerprint"]
        write_package_artifacts(target, built)
        write_json(target / "historical_replay_validation.json",
                   {"status": "passed", "package_input_fingerprint": fingerprint,
                    "binding": {"package_input_fingerprint": fingerprint}})
        self.fx.issue()

        def verdict_blockers(manifest: dict) -> list[str]:
            return [code for code in manifest["production_blockers"] if "OOT" in code or "REPLAY" in code]

        rebuilt = build_package(target, target)[0]
        self.assertEqual(rebuilt["package_input_fingerprint"], fingerprint)
        self.assertEqual(verdict_blockers(rebuilt), [])
        self.assertEqual(rebuilt["oot_basis"]["evidence_basis"], OOT_BASIS_INHERITED)

        write_json(target / "fit_design_metadata.json", {"generated_at_utc": "2026-10-27T14:59:46+00:00", "fits": {}})
        reexported = build_package(target, target)[0]
        self.assertNotEqual(reexported["package_input_fingerprint"], fingerprint)
        self.assertEqual(sorted(verdict_blockers(reexported)),
                         ["STALE_OR_UNBOUND_HISTORICAL_REPLAY", "STALE_OR_UNBOUND_OOT_VALIDATION"])

    def test_independent_sealed_oot_files_are_unaffected(self) -> None:
        write_json(self.fx.target / "oot_validation.json", {
            "status": "passed", "activation_eligible": True, "package_input_fingerprint": self.fx.fingerprint,
            "binding": {"package_input_fingerprint": self.fx.fingerprint}})
        manifest = build_package(self.fx.target, self.fx.target)[0]
        self.assertFalse([code for code in manifest["production_blockers"] if "OOT" in code])
        self.assertEqual(manifest["oot_basis"], {"evidence_basis": "sealed_oot"})
        registration = {"activation_status_at_registration": "production_ready",
                        "production_blockers_at_registration": [], "run_dir": str(self.fx.target),
                        "package_input_fingerprint": self.fx.fingerprint}
        model_registry._assert_production_eligible(registration)


if __name__ == "__main__":
    unittest.main()
