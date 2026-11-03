import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
import snapshot_financial_results as snapshot
import run_financial_models as predictors
import run_financial_moderation as moderation
import test_run_financial_models as fixtures

base = snapshot.base


class FinancialSnapshot(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.FinancialRunner(methodName="test_connectivity_order_mismatch_is_rejected")
        self.fixture.setUp()
        self.root = self.fixture.root
        self.args = self.fixture.args
        self.args.output = self.root / "derivatives/fsl/randomise/katie-financial-v1"
        self.args.output.parent.mkdir(parents=True)
        with patch.object(base, "check", return_value=self.fixture.plan):
            self.plan = predictors.build(self.args)
            old = self.args.output
            self.args.output = self.args.output.with_name("katie-financial-moderation-v1")
            moderation.build(self.args)
            self.args.output = old
        self.environment = patch.dict(os.environ, dict(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1"))
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.fixture.tearDown()

    def complete(self, index=0):
        job = self.plan["jobs"][index]
        unit = self.args.output / "jobs" / job["key"]
        predictors.execute(self.plan, job, unit, base.cohort.digest(self.args.output / "plan.json"))
        return unit

    def test_completed_live_stale_and_invalid_are_separate_no_partial_map_reads(self):
        self.complete()
        processes = []
        for index, pid in ((1, 200), (2, 201)):
            job = self.plan["jobs"][index]
            unit = self.args.output / "jobs" / job["key"]
            attempt = unit / "attempts/attempt-0001"; attempt.mkdir(parents=True)
            (attempt / "randomise_clustere_corrp_tstat1.nii.gz").write_text("unfinished; must not be read")
            command = ["randomise", "-o", str(attempt / "randomise")]
            base.write_json(unit / "running.json", dict(command=command, process_group=pid))
            if pid == 200: processes.append(dict(pgid="200", args=" ".join(command)))
        job = self.plan["jobs"][3]
        unit = self.args.output / "jobs" / job["key"]; unit.mkdir(parents=True)
        base.write_json(unit / "success.json", dict(job=job, plan_sha256="wrong", smoke=False))
        before = {p: (p.stat().st_mtime_ns, base.cohort.digest(p)) for p in self.args.output.rglob("*") if p.is_file()}
        batches, jobs, maps, _ = snapshot.snapshot(self.root, processes)
        a, b = batches
        self.assertEqual((a["receipt_verified"], a["live"], a["incomplete"], a["invalid"], a["queued"]), (1, 1, 1, 1, 12))
        self.assertEqual(b["queued"], 64)
        self.assertEqual(len(jobs), 80)
        self.assertEqual(len(maps), 2)
        self.assertEqual({r["direction"] for r in maps}, {"positive", "negative"})
        self.assertEqual(before, {p: (p.stat().st_mtime_ns, base.cohort.digest(p)) for p in self.args.output.rglob("*") if p.is_file()})

    def test_corrupted_roster_or_completed_map_is_not_reported_as_valid(self):
        unit = self.complete()
        saved = json.loads((unit / "success.json").read_text())
        path = Path(saved["outputs"][0]["path"]); path.write_text("corrupted")
        batches, _, maps, _ = snapshot.snapshot(self.root, [])
        self.assertEqual(batches[0]["invalid"], 1)
        self.assertEqual(maps, [])
        (self.args.output / "subjects.tsv").write_text("subject\nwrong\n")
        batches, _, maps, _ = snapshot.snapshot(self.root, [])
        self.assertIn("roster differs", batches[0]["errors"][0])
        self.assertEqual(maps, [])

    def test_missing_plan_and_stale_recorded_failure_remain_explicit(self):
        base.write_json(self.args.output / "status.json", dict(failures={self.plan["jobs"][0]["key"]: "old attempt failed", "verification": "old check"}))
        (self.args.output.with_name("katie-financial-moderation-v1") / "plan.json").unlink()
        batches, _, _, _ = snapshot.snapshot(self.root, [])
        self.assertEqual(len(batches[0]["recorded_job_failures"]), 1)
        self.assertEqual(len(batches[0]["recorded_validation_failures"]), 1)
        self.assertFalse(batches[1]["prepared"])

    def test_changed_support_mask_blocks_result_interpretation(self):
        self.complete()
        mask = Path(self.plan["masks"]["activation"])
        mask.write_text("changed mask")
        batches, _, maps, _ = snapshot.snapshot(self.root, [])
        self.assertIn("Frozen input changed", batches[0]["errors"][0])
        self.assertEqual(maps, [])

    def test_ps_filter_excludes_unrelated_jobs_and_snapshot_itself(self):
        output = f"10 1 10 01:00 00:10 16.7 100 R randomise -o {self.root}/derivatives/fsl/randomise/katie-financial-v1/job\n"
        output += f"11 1 11 01:00 00:00 0.0 100 S bash {self.root}/code/run_financial_snapshot.sh\n"
        output += "12 1 12 01:00 00:10 16.7 100 R randomise -o /other/project\n"
        with patch.object(snapshot.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, output, "")):
            rows = snapshot.process_snapshot(self.root)
        self.assertEqual([r["pid"] for r in rows], ["10"])
        self.assertEqual(rows[0]["cpu_percent_lifetime"], "16.7")

    def test_cli_writes_new_report_and_never_overwrites_it(self):
        self.complete()
        report = self.root / "snapshot"
        with patch.object(sys, "argv", ["snapshot", "--project", str(self.root), "--report", str(report), "--sample-seconds", "0"]), \
                patch.object(snapshot, "process_snapshot", return_value=[]):
            snapshot.main()
            with self.assertRaisesRegex(ValueError, "no existing report overwritten"):
                snapshot.main()
        self.assertEqual(len((report / "jobs.tsv").read_text().splitlines()), 81)
        self.assertEqual(len((report / "maps.tsv").read_text().splitlines()), 3)
        self.assertFalse(json.loads((report / "provenance.json").read_text())["source_images_rehashed"])
        result = subprocess.run(["bash", "-n", str(base.ROOT / "code/run_financial_snapshot.sh")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
