from types import SimpleNamespace
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from worker.execution_worker import ExecutionWorker

class OptimizerScoringEventsTest(unittest.TestCase):
    def test_scoring_is_translated_to_final_check_without_invented_percent(self):
        emitted=[]
        worker=SimpleNamespace(_campaign_positions={},_last_percent=55.0,
                               _emit_progress=lambda *args,**kwargs:emitted.append(kwargs))
        job=SimpleNamespace(job_id="job_111111111111")
        ExecutionWorker._translate_progress_line(worker,job,json.dumps({
            "event":"optimizer_progress","phase":"posterior_scoring",
            "scoring_pass":"optimizer_finalists","blocks_completed":20,"blocks_total":175,
        }))
        self.assertEqual(len(emitted),1)
        event=emitted[0]
        self.assertEqual(event["stage"],"final_scoring")
        self.assertEqual(event["percent"],55.0)
        self.assertEqual(event["counters"][0].name,"scoring_blocks")
        self.assertEqual(event["counters"][0].current,20)
        self.assertEqual(event["counters"][0].total,175)
