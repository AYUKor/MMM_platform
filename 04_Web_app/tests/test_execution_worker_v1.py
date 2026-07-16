from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any


WEB_APP_DIR = Path(__file__).resolve().parents[1]
if str(WEB_APP_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_APP_DIR))

from worker import (  # noqa: E402
    ExecutionWorker,
    ExecutionWorkerSettings,
    LocalArtifactStore,
    VerifiedModel,
)
from services.job_progress_view import build_job_progress_view  # noqa: E402


FIXTURE_PATH = (
    WEB_APP_DIR / "tests" / "fixtures" / "application_lifecycle_v1_happy_path_synthetic.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _SyntheticResult:
    def __init__(self, job: dict[str, Any]) -> None:
        self.result_id = "result_999999999999"
        self.job = SimpleNamespace(
            job_id=job["job_id"],
            workflow_config_sha256=job["workflow_config"]["sha256"],
            input_flighting_sha256=job["daily_flighting"]["sha256"],
        )
        self.model = SimpleNamespace(
            package_id=job["model_selector"]["package_id"],
            package_fingerprint=job["model_selector"]["expected_package_fingerprint"],
        )
        self.policies = SimpleNamespace(
            optimizer_policy_sha256=job["policies"]["optimizer_policy_sha256"],
            business_policy_sha256=job["policies"]["business_policy_sha256"],
        )

    def validate(self) -> None:
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture_origin": "synthetic_worker_test_not_production_evidence",
            "result_id": self.result_id,
            "job_id": self.job.job_id,
        }


class ExecutionWorkerV1Test(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project_root = self.root / "project"
        self.artifact_root = self.root / "artifact_store"
        self.runtime_root = self.root / "runtime"
        self.policy_dir = self.project_root / "policies"
        self.project_root.mkdir()
        self.artifact_root.mkdir()
        self.policy_dir.mkdir(parents=True)
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.job = copy.deepcopy(fixture["jobs"][0])
        self.job.update(
            {
                "record_origin": "synthetic_fixture",
                "status": {"code": "queued", "display_text": "В очереди"},
                "created_at_utc": "2026-01-01T00:00:00Z",
                "queued_at_utc": "2026-01-01T00:00:01Z",
                "started_at_utc": None,
                "cancel_requested_at_utc": None,
                "finished_at_utc": None,
                "attempt_number": 0,
                "result_id": None,
                "terminal_error_id": None,
                "code_reference": "git:synthetic-test",
            }
        )
        self.optimizer_policy = self.policy_dir / "optimizer_policy.json"
        self.optimizer_policy.write_text(
            json.dumps({"policy_id": self.job["policies"]["optimizer_policy_id"]}),
            encoding="utf-8",
        )
        self.business_policy = self.policy_dir / "business_policy.json"
        self.business_policy.write_text(
            json.dumps(
                {
                    "policy_id": self.job["policies"]["business_policy_id"],
                    "decision": {"mode": self.job["policies"]["business_decision_mode"]},
                }
            ),
            encoding="utf-8",
        )
        self.job["policies"]["optimizer_policy_sha256"] = _sha256(self.optimizer_policy)
        self.job["policies"]["business_policy_sha256"] = _sha256(self.business_policy)
        self.fake_optimizer = self.project_root / "fake_optimizer.py"
        self.fake_optimizer.write_text(self._fake_optimizer_source(), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _fake_optimizer_source(self) -> str:
        return """
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--config', required=True)
args = parser.parse_args()
config = json.loads(Path(args.config).read_text(encoding='utf-8'))
scenario6 = config['optimizer']['scenario_6']
mode = config.get('synthetic_test_mode', 'success')
if mode == 'sleep':
    time.sleep(5)
if mode == 'fail':
    print('synthetic protected failure detail', flush=True)
    raise SystemExit(7)
output = Path(config['paths']['output_dir'])
output.mkdir(parents=True, exist_ok=True)
events = []
for campaign_index, campaign in enumerate(('Synthetic A', 'Synthetic B'), start=1):
    events.extend([
        {'event': 'optimizer_progress', 'phase': 'candidate_generation', 'campaign': campaign, 'campaign_index': campaign_index, 'campaigns_total': 2},
        {'event': 'optimizer_progress', 'phase': 'adaptive_search_complete', 'campaign': campaign, 'search_attempts_evaluated_n': 12, 'search_max_evaluations_n': scenario6['search_candidates']},
        {'event': 'optimizer_progress', 'phase': 'search_scoring', 'campaign': campaign, 'candidates_to_score': 8},
        {'event': 'optimizer_progress', 'phase': 'finalist_scoring_complete', 'campaign': campaign, 'finalists_scored': 3},
    ])
for event in events:
    print(json.dumps(event), flush=True)
context = config['worker_execution']
optimizer_policy = Path(config['decision_policy_file'])
business_policy = Path(config['objective']['business_threshold_policy'])
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
run_id = config['run_id']
run_card = {
    'run_id': run_id,
    'flighting_sha256': context['pinned_daily_flighting_sha256'],
    'search_candidates_per_campaign': scenario6['search_candidates'],
    'search_samples': scenario6['search_posterior_samples'],
    'final_samples': scenario6['final_posterior_samples'],
    'search_seed': scenario6['random_seed'],
    'final_seed': scenario6['final_random_seed'],
    'decision_policy_sha256': sha(optimizer_policy),
    'objective': {'business_threshold_policy_sha256': sha(business_policy)},
}
(output / f'{run_id}_optimizer_run_card.json').write_text(json.dumps(run_card), encoding='utf-8')
(output / 'model_resolution_optimizer.json').write_text(
    json.dumps({
        'package_id': config['model_ref']['expected_package_id'],
        'package_input_fingerprint': context['synthetic_package_fingerprint'],
    }),
    encoding='utf-8',
)
"""

    def _write_artifact(
        self,
        identity: dict[str, Any],
        relative_key: str,
        content: str,
    ) -> Path:
        path = self.artifact_root / relative_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        identity.update(
            {
                "display_name": path.name,
                "storage_key": relative_key,
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
        return path

    def _prepare_job(self, mode: str = "success") -> tuple[dict[str, Any], Path]:
        self._write_artifact(
            self.job["normalized_plan"],
            "validations/validation_333333333333/campaign_plan_normalized.csv",
            "campaign_name,segment,geo,channel,budget_rub\nSynthetic,S,A,C,100\n",
        )
        daily_path = self._write_artifact(
            self.job["daily_flighting"],
            "validations/validation_333333333333/campaign_flighting_daily.csv",
            "campaign_name,segment,geo,channel,date,budget_rub\nSynthetic,S,A,C,2026-08-01,100\n",
        )
        config = {
            "layer": "budget_optimizer",
            "synthetic_test_mode": mode,
            "model_ref": {
                "source": "registry",
                "channel": self.job["model_selector"]["registry_channel"],
                "expected_package_id": self.job["model_selector"]["package_id"],
            },
            "objective": {"primary": "maximize_incremental_turnover_p50"},
            "optimizer": {
                "scenario_6": {
                    "enabled": True,
                    "search_candidates": self.job["sampling"]["scenario6_attempt_budget"],
                    "search_posterior_samples": self.job["sampling"]["search_posterior_draws"],
                    "final_posterior_samples": self.job["sampling"]["final_posterior_draws"],
                    "random_seed": self.job["sampling"]["search_seed"],
                    "final_random_seed": self.job["sampling"]["final_seed"],
                }
            },
        }
        config_path = self._write_artifact(
            self.job["workflow_config"],
            "jobs/job_777777777777/config/decision_job_config.json",
            json.dumps(config),
        )
        self.job["workflow_config"]["media_type"] = "application/json"
        return self.job, daily_path

    def _worker(
        self,
        job: dict[str, Any],
        *,
        timeout: float = 5.0,
        cancel: bool = False,
    ) -> ExecutionWorker:
        fingerprint = job["model_selector"]["expected_package_fingerprint"]

        def verify_model(*_: Any) -> VerifiedModel:
            return VerifiedModel(
                package_id=job["model_selector"]["package_id"],
                package_fingerprint=fingerprint,
                run_dir=self.project_root,
                registry_channel=job["model_selector"]["registry_channel"],
                registry_event_id="evt_synthetic_test",
                gate_policy_version=job["policies"]["gate_policy_version"],
                activation_status="preprod_restricted",
            )

        def result_builder(
            output_dir: Path,
            job_id: str,
            workflow_config_sha256: str,
            storage_prefix: str,
        ) -> _SyntheticResult:
            self.assertTrue(output_dir.is_dir())
            self.assertEqual(job_id, job["job_id"])
            self.assertEqual(workflow_config_sha256, job["workflow_config"]["sha256"])
            self.assertFalse(Path(storage_prefix).is_absolute())
            return _SyntheticResult(job)

        return ExecutionWorker(
            ExecutionWorkerSettings(
                runtime_root=self.runtime_root,
                timeout_seconds=timeout,
                project_root=WEB_APP_DIR.parent,
                python_executable=Path(sys.executable),
                optimizer_cli=self.fake_optimizer,
                policy_dir=self.policy_dir,
                registry_root=self.project_root / "registry",
                poll_seconds=0.01,
                terminate_grace_seconds=0.5,
            ),
            LocalArtifactStore(self.artifact_root),
            model_verifier=verify_model,
            code_verifier=lambda *_: None,
            result_builder=result_builder,
            cancellation_probe=(lambda: cancel),
        )

    def _inject_fingerprint_for_fake_process(self, job: dict[str, Any]) -> None:
        original = self.fake_optimizer.read_text(encoding="utf-8")
        fingerprint = job["model_selector"]["expected_package_fingerprint"]
        original = original.replace(
            "context = config['worker_execution']",
            "context = config['worker_execution']\ncontext['synthetic_package_fingerprint'] = "
            + repr(fingerprint),
        )
        self.fake_optimizer.write_text(original, encoding="utf-8")

    def test_success_runs_isolated_process_and_preserves_one_job_identity(self) -> None:
        job, _ = self._prepare_job()
        self._inject_fingerprint_for_fake_process(job)
        source_config_path = self.artifact_root / job["workflow_config"]["storage_key"]
        source_hash_before = _sha256(source_config_path)

        outcome = self._worker(job).run(job)

        self.assertTrue(outcome.succeeded)
        self.assertEqual(outcome.final_job.job_id, job["job_id"])
        self.assertEqual(outcome.final_job.result_id, "result_999999999999")
        self.assertEqual(
            [event.to_status.code for event in outcome.job_events],
            ["running", "succeeded"],
        )
        stages = [event.stage for event in outcome.progress_events]
        for expected_stage in (
            "prepare",
            "benchmarks",
            "scenario6",
            "forecast",
            "final_scoring",
            "report",
        ):
            self.assertIn(expected_stage, stages)
        first_report_index = stages.index("report")
        last_final_scoring_index = max(
            index for index, stage in enumerate(stages) if stage == "final_scoring"
        )
        self.assertGreater(first_report_index, last_final_scoring_index)
        sequences = [event.sequence for event in outcome.job_events + outcome.progress_events]
        self.assertEqual(len(sequences), len(set(sequences)))
        percentages = [event.percent_complete for event in outcome.progress_events]
        self.assertEqual(percentages, sorted(percentages))
        final_scoring = [
            event.percent_complete
            for event in outcome.progress_events
            if event.stage == "final_scoring"
        ]
        self.assertEqual(final_scoring, [55.0, 90.0])
        scenario6_events = [
            event for event in outcome.progress_events if event.stage == "scenario6"
        ]
        self.assertEqual(len(scenario6_events), 2)
        for event in scenario6_events:
            attempt_counter = next(
                counter for counter in event.counters if counter.name == "attempts"
            )
            self.assertEqual(attempt_counter.current, 12)
            self.assertEqual(
                attempt_counter.total,
                job["sampling"]["scenario6_attempt_budget"],
            )

        running_job = copy.deepcopy(job)
        running_job.update(
            {
                "status": {"code": "running", "display_text": "Выполняется"},
                "started_at_utc": outcome.final_job.started_at_utc,
                "finished_at_utc": None,
                "attempt_number": 1,
                "result_id": None,
            }
        )
        validation = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["validations"][0]
        progress_view = build_job_progress_view(
            job_payload=running_job,
            validation_payload=validation,
            progress_payloads=[event.to_dict() for event in outcome.progress_events],
            error_payloads=[],
            result_payload=None,
            queue_position=None,
            queued_jobs_total=0,
        ).to_dict()
        self.assertEqual(progress_view["current_stage_id"], "P09")
        self.assertEqual(progress_view["scenario6"]["attempts_checked"], 12)
        self.assertIsNone(progress_view["scenario6"]["safe_candidates"])
        self.assertFalse(progress_view["result_available"])
        self.assertEqual(_sha256(source_config_path), source_hash_before)
        execution_config = json.loads(
            (outcome.attempt_root / "config" / "execution_config.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(execution_config["worker_execution"]["job_id"], job["job_id"])
        self.assertEqual(
            execution_config["optimizer"]["scenario_6"]["search_posterior_samples"],
            job["sampling"]["search_posterior_draws"],
        )
        self.assertTrue((outcome.attempt_root / "decision_result_manifest_v1.json").is_file())

    def test_tampered_input_fails_before_optimizer_process(self) -> None:
        job, daily_path = self._prepare_job()
        daily_path.write_text(daily_path.read_text(encoding="utf-8") + "tampered", encoding="utf-8")

        outcome = self._worker(job).run(job)

        self.assertEqual(outcome.final_job.status.code, "failed")
        self.assertIsNone(outcome.process_return_code)
        self.assertEqual(outcome.errors[0].code, "ARTIFACT_HASH_MISMATCH")
        self.assertEqual(outcome.errors[0].category, "artifact_integrity")
        self.assertFalse((outcome.attempt_root / "optimizer_output").exists())

    def test_nonzero_process_is_a_safe_terminal_failure(self) -> None:
        job, _ = self._prepare_job(mode="fail")
        self._inject_fingerprint_for_fake_process(job)

        outcome = self._worker(job).run(job)

        self.assertEqual(outcome.final_job.status.code, "failed")
        self.assertEqual(outcome.process_return_code, 7)
        self.assertEqual(outcome.errors[0].code, "OPTIMIZER_PROCESS_FAILED")
        serialized_error = json.dumps(outcome.errors[0].to_dict(), ensure_ascii=False)
        self.assertNotIn(str(self.root), serialized_error)
        self.assertIn(
            "synthetic protected failure detail",
            (outcome.attempt_root / "protected_execution.log").read_text(encoding="utf-8"),
        )

    def test_timeout_terminates_process_and_creates_retryable_error(self) -> None:
        job, _ = self._prepare_job(mode="sleep")
        self._inject_fingerprint_for_fake_process(job)

        outcome = self._worker(job, timeout=0.05).run(job)

        self.assertEqual(outcome.final_job.status.code, "timed_out")
        self.assertEqual(outcome.errors[0].category, "timeout")
        self.assertTrue(outcome.errors[0].retryable)
        self.assertIsNotNone(outcome.process_return_code)

    def test_cancellation_is_not_misclassified_as_error(self) -> None:
        job, _ = self._prepare_job(mode="sleep")
        self._inject_fingerprint_for_fake_process(job)

        outcome = self._worker(job, cancel=True).run(job)

        self.assertEqual(outcome.final_job.status.code, "cancelled")
        self.assertEqual(outcome.errors, ())
        self.assertEqual(
            [event.to_status.code for event in outcome.job_events],
            ["running", "cancel_requested", "cancelled"],
        )
        outcome.final_job.validate()


if __name__ == "__main__":
    unittest.main()
