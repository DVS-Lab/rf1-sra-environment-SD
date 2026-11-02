import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
import run_financial_moderation as moderation
import test_run_financial_models as fixtures

base = moderation.base


class ModerationFlow(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.FinancialRunner(methodName="test_connectivity_order_mismatch_is_rejected")
        self.fixture.setUp()
        self.args = self.fixture.args
        self.args.output = self.fixture.root / "moderation"
        self.args.report = self.fixture.root / "moderation-report"

    def tearDown(self):
        self.fixture.tearDown()

    def build(self):
        with patch.object(base, "check", return_value=self.fixture.plan):
            return moderation.build(self.args)

    def test_64_jobs_both_main_effects_exact_product_and_two_sided_interaction(self):
        plan = self.build()
        self.assertEqual(len(plan["jobs"]), 64)
        self.assertEqual(plan["interaction_order"], 2)
        self.assertEqual(sum(j["role"] == "lead_financial_score" for j in plan["jobs"]), 32)
        _, _, ids, scores = moderation.predictor.frozen_previews()
        _, raw = base.cohort.read_table(base.ROOT / "data/derived/model-review-v1/aligned_raw_terms.tsv")
        for job in plan["jobs"]:
            score, moderator = job["model"].split("x")
            x = np.loadtxt(io.StringIO(Path(job["design"]).read_text().split("/Matrix", 1)[1]), ndmin=2)
            self.assertEqual(x.shape, (97, 10))
            self.assertEqual(np.linalg.matrix_rank(x), 10)
            np.testing.assert_allclose(x[:, 7], base.review.center([s[score] for s in scores]), atol=1e-12)
            np.testing.assert_allclose(x[:, 8], base.review.center([float(r[moderator]) for r in raw]), atol=1e-12)
            np.testing.assert_allclose(x[:, 9], x[:, 7] * x[:, 8], atol=1e-12)
            c = np.loadtxt(io.StringIO(Path(job["contrast"]).read_text().split("/Matrix", 1)[1]), ndmin=2)
            np.testing.assert_array_equal(c[0], [0]*9 + [1])
            np.testing.assert_array_equal(c[1], -c[0])
            self.assertEqual(job["residual_dof"], 87)
            self.assertEqual(job["permutations"], 10000)
            _, rows = base.cohort.read_table(Path(job["design"]).with_suffix(".tsv"))
            self.assertEqual([r["subject"] for r in rows], ids)

    def test_64_fake_jobs_128_maps_resume_preserves_all_previous_outputs(self):
        before = {p: (p.stat().st_mtime_ns, base.cohort.digest(p)) for p in self.fixture.baseline.rglob("*") if p.is_file()}
        with patch.object(base, "check", return_value=self.fixture.plan), patch.dict(os.environ,
                dict(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")):
            moderation.run(self.args)
            status = json.loads((self.args.output / "status.json").read_text())
            self.assertEqual(status["status"], "complete")
            self.assertEqual(len(status["outcomes"]), 64)
            self.assertEqual(len((self.args.report / "maps.tsv").read_text().splitlines()), 129)
            products = {p: p.stat().st_mtime_ns for p in (self.args.output / "jobs").rglob("randomise_tstat1.nii.gz")}
            moderation.run(self.args)
            self.assertEqual(products, {p: p.stat().st_mtime_ns for p in products})
        self.assertEqual(before, {p: (p.stat().st_mtime_ns, base.cohort.digest(p)) for p in self.fixture.baseline.rglob("*") if p.is_file()})

    def test_roster_mismatch_and_mutated_design_rejected(self):
        plan = self.build()
        design = Path(plan["jobs"][0]["design"])
        design.write_text(design.read_text().replace("/NumPoints\t97", "/NumPoints\t96"))
        with self.assertRaisesRegex(ValueError, "design changed"):
            moderation.check(self.args)
        path = self.fixture.connectivity / "subjects.tsv"
        path.write_text("subject\nwrong\n")
        with self.assertRaisesRegex(ValueError, "artifact changed"):
            moderation.predictor.checked_image_plan(self.fixture.connectivity)

    def test_launcher_and_wrapper_bash_syntax_no_checkout_mutation(self):
        for name in ("launch_financial_followup.sh", "run_financial_moderation.sh", "run_financial_models.sh"):
            path = base.ROOT / "code" / name
            result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        launcher = (base.ROOT / "code/launch_financial_followup.sh").read_text()
        self.assertNotIn("git pull", launcher)
        self.assertNotIn("kill ", launcher)
        self.assertIn("git archive", launcher)
        self.assertIn("umask 0000", launcher)


if __name__ == "__main__":
    unittest.main()
