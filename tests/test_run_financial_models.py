import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
import run_financial_models as financial_run
import test_run_katie_main_effects as fixtures

base = financial_run.base


class FinancialRunner(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.MainEffectFlow(methodName="test_active_group_and_stop_prevent_duplicate")
        self.fixture.setUp()
        self.root, self.baseline, self.plan = self.fixture.root, self.fixture.baseline, self.fixture.plan
        self.connectivity = self.root / "connectivity"; self.connectivity.mkdir()
        roster = (base.ROOT / "data/derived/katie-cohort-v1/subjects.tsv").read_text()
        (self.baseline / "subjects.tsv").write_text(roster)
        self.plan["outputs"]["subjects.tsv"] = base.cohort.digest(self.baseline / "subjects.tsv")
        base.write_json(self.baseline / "plan.json", self.plan)
        (self.baseline / "plan.sha256").write_text(base.cohort.digest(self.baseline / "plan.json"))
        (self.connectivity / "subjects.tsv").write_text(roster)
        ppi = dict(self.plan, outputs={"subjects.tsv": base.cohort.digest(self.connectivity / "subjects.tsv")})
        base.write_json(self.connectivity / "plan.json", ppi)
        (self.connectivity / "plan.sha256").write_text(base.cohort.digest(self.connectivity / "plan.json"))
        self.args = SimpleNamespace(project=self.root, baseline=self.baseline, connectivity=self.connectivity,
                                    output=self.root / "financial", report=self.root / "report", upstream=self.root / "upstream",
                                    families=["activation", "connectivity"], jobs=4, prepare_only=False)
        base.STOP = False; base.LEASE_FD = None

    def tearDown(self):
        self.fixture.tearDown()

    def build(self):
        with patch.object(base, "check", return_value=self.plan):
            return financial_run.build(self.args)

    def test_16_jobs_no_interactions_exact_covariates_and_two_contrasts(self):
        plan = self.build()
        self.assertEqual(len(plan["jobs"]), 16)
        self.assertFalse(plan["interactions"])
        for job in plan["jobs"]:
            with Path(job["design"]).open() as stream:
                data = stream.read().split("/Matrix", 1)[1]
            import io
            x = np.loadtxt(io.StringIO(data), ndmin=2)
            self.assertEqual(x.shape, (97, 8))
            self.assertEqual(np.linalg.matrix_rank(x), 8)
            c = np.loadtxt(io.StringIO(Path(job["contrast"]).read_text().split("/Matrix", 1)[1]), ndmin=2)
            np.testing.assert_array_equal(c[0], [0, 0, 0, 0, 0, 0, 0, 1])
            np.testing.assert_array_equal(c[1], -c[0])
            self.assertEqual(job["residual_dof"], 89)
            self.assertEqual(job["permutations"], 10000)
        self.assertEqual({j["model"] for j in plan["jobs"]}, {"fevs", "oafem"})
        self.assertEqual(plan["images"]["activation/average"], self.plan["images"]["average"])

    def test_connectivity_order_mismatch_is_rejected(self):
        path = self.connectivity / "subjects.tsv"
        lines = path.read_text().splitlines()
        path.write_text("\n".join([lines[0], *reversed(lines[1:])]) + "\n")
        p = json.loads((self.connectivity / "plan.json").read_text())
        p["outputs"]["subjects.tsv"] = base.cohort.digest(path)
        base.write_json(self.connectivity / "plan.json", p)
        (self.connectivity / "plan.sha256").write_text(base.cohort.digest(self.connectivity / "plan.json"))
        with self.assertRaisesRegex(ValueError, "volume order"):
            self.build()

    def test_missing_connectivity_is_not_silently_substituted(self):
        (self.connectivity / "plan.json").unlink()
        with self.assertRaises(FileNotFoundError):
            self.build()

    def test_live_covariate_row_mismatch_is_rejected(self):
        path = Path(self.plan["jobs"][0]["design"])
        text = path.read_text()
        header, matrix = text.split("/Matrix\n", 1)
        rows = matrix.splitlines(); rows[0], rows[1] = rows[1], rows[0]
        path.write_text(header + "/Matrix\n" + "\n".join(rows) + "\n")
        with self.assertRaisesRegex(ValueError, "nuisance covariates differ"):
            self.build()

    def test_execution_authenticates_previews_without_recomputing_platform_diagnostics(self):
        references = {outcome: next(j["design"] for j in self.plan["jobs"] if j["outcome"] == outcome and j["model"] == "adi")
                      for outcome in ("social_specific", "average")}
        with patch.object(financial_run.financial, "generate", side_effect=AssertionError("Do not recompute Mac diagnostics on Linux")):
            designs, jobs, _ = financial_run.specifications(self.args.output, self.args.families, references)
        self.assertEqual(len(jobs), 16)
        self.assertEqual(len([name for name in designs if name.endswith("design.mat")]), 4)

    def test_complete_16_jobs_reports_and_resume_leave_existing_results_unchanged(self):
        before = {p: (p.stat().st_mtime_ns, base.cohort.digest(p)) for p in self.baseline.rglob("*") if p.is_file()}
        with patch.object(base, "check", return_value=self.plan), \
                patch.dict(os.environ, dict(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")):
            financial_run.run(self.args)
            self.assertEqual(json.loads((self.args.output / "status.json").read_text())["status"], "complete")
            self.assertEqual(len((self.args.report / "maps.tsv").read_text().splitlines()), 33)
            path = next((self.args.output / "jobs").rglob("randomise_tstat1.nii.gz"))
            stamp = path.stat().st_mtime_ns
            financial_run.run(self.args)
            self.assertEqual(path.stat().st_mtime_ns, stamp)
        self.assertEqual(before, {p: (p.stat().st_mtime_ns, base.cohort.digest(p)) for p in self.baseline.rglob("*") if p.is_file()})

    def test_waiting_respects_existing_batch_and_never_terminates_it(self):
        path = self.root / "remaining.lock"
        with path.open("a") as owner:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            def release(seconds):
                self.assertEqual(seconds, 15)
                self.assertFalse(owner.closed)
                fcntl.flock(owner, fcntl.LOCK_UN)
            with patch.object(financial_run.time, "sleep", side_effect=release):
                shared = financial_run.wait_shared(path)
            try:
                with path.open("a") as competitor, self.assertRaises(BlockingIOError):
                    fcntl.flock(competitor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                shared.close()

    def test_snapshot_has_no_git_dependency_and_reproduces_financial_previews(self):
        # Match the launcher: use a physical path, not macOS /var -> /private/var aliases.
        release = (self.root / "release").resolve()
        for name in ("code", "data", "config"):
            shutil.copytree(base.ROOT / name, release / name, ignore=shutil.ignore_patterns("__pycache__"))
        environment = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
        result = subprocess.run([sys.executable, str(release / "code/review_financial_models.py"), "check"],
                                cwd=self.root, capture_output=True, text=True, env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((release / ".git").exists())
        help_result = subprocess.run([sys.executable, str(release / "code/run_financial_models.py"), "--help"],
                                     cwd=self.root, capture_output=True, text=True, env=environment)
        self.assertEqual(help_result.returncode, 0, help_result.stderr)


if __name__ == "__main__":
    unittest.main()
