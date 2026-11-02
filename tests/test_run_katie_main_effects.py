import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import nibabel as nib
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
import run_katie_main_effects as followup

base = followup.base
ROOT = base.ROOT


class MainEffectFlow(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.baseline = self.root / "baseline"
        self.baseline.mkdir()
        self.fake = self.root / "fake_randomise"
        self.fake.write_text(f"#!{sys.executable}\n" + """import sys
import nibabel as nib
import numpy as np
args=sys.argv[1:]
prefix=args[args.index('-o')+1]
mask=nib.load(args[args.index('-m')+1])
for i in range(1,5):
    for suffix in (f'_tstat{i}.nii.gz',f'_clustere_corrp_tstat{i}.nii.gz'):
        data=np.ones(mask.shape)*(0.9 if 'corrp' in suffix else i)
        nib.save(nib.Nifti1Image(data,mask.affine),prefix+suffix)
""")
        self.fake.chmod(self.fake.stat().st_mode | stat.S_IXUSR)
        _, raw = base.cohort.read_table(ROOT / "data/derived/model-review-v1/aligned_raw_terms.tsv")
        _, table = base.cohort.read_table(ROOT / "data/derived/model-review-v1/centered_candidate_terms.tsv")
        terms = {name: np.array([float(r[name]) for r in table]) for name in table[0] if name != "subject"}
        files, jobs = base.make_designs(self.baseline, base.approved_config(), [r["subject"] for r in raw], terms)
        for name, text in files.items():
            path = self.baseline / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        shape = (2, 3, 4)
        mask = self.baseline / "mask.nii.gz"
        nib.save(nib.Nifti1Image(np.ones(shape), np.eye(4)), mask)
        images = {}
        for outcome in ("social_specific", "average"):
            path = self.baseline / (outcome + ".nii.gz")
            nib.save(nib.Nifti1Image(np.ones(shape + (97,)), np.eye(4)), path)
            images[outcome] = str(path)
        outputs = {name: base.cohort.digest(self.baseline / name) for name in files}
        outputs.update({path.name: base.cohort.digest(path) for path in [mask, *map(Path, images.values())]})
        self.plan = dict(n=97, jobs=jobs, images=images, mask=str(mask), randomise=str(self.fake),
                         outputs=outputs, sources=[base.fingerprint(self.fake)])
        base.write_json(self.baseline / "plan.json", self.plan)
        plan_hash = base.cohort.digest(self.baseline / "plan.json")
        (self.baseline / "plan.sha256").write_text(plan_hash)
        for job in jobs:
            folder = self.baseline / "jobs" / job["key"]
            folder.mkdir(parents=True)
            prefix = folder / "randomise"
            for i in (1, 2):
                for suffix in (f"_tstat{i}.nii.gz", f"_clustere_corrp_tstat{i}.nii.gz"):
                    nib.save(nib.Nifti1Image(np.zeros(shape), np.eye(4)), str(prefix) + suffix)
            base.write_json(folder / "success.json", dict(job=job, smoke=False, plan_sha256=plan_hash,
                attempt=str(folder), outputs=base.output_images(prefix, str(mask))))
        self.args = SimpleNamespace(baseline=self.baseline, output=self.root / "additional",
                                    upstream=self.root / "upstream", jobs=4, report=self.root / "report")
        base.STOP = False
        base.LEASE_FD = None

    def tearDown(self):
        base.STOP = False
        self.temporary.cleanup()

    def build(self):
        # Baseline arithmetic/order has its own full integration test; the new
        # batch additionally verifies all real synthetic original receipts/maps.
        with patch.object(base, "check", return_value=self.plan):
            followup.build(self.args)
        return followup.check(self.args)

    def test_16_jobs_reuse_exact_original_designs_and_four_target_rows(self):
        files, jobs = followup.specifications(self.plan, self.args.output)
        self.assertEqual(len(jobs), 16)
        self.assertEqual(len(files), 16)
        originals = {r["key"]: r for r in self.plan["jobs"]}
        for job in jobs:
            original = originals[job["key"]]
            for name in ("design", "t_cutoff", "z", "residual_dof", "seed", "permutations"):
                self.assertEqual(job[name], original[name])
            exposure, moderator = base.review.MODELS[job["model"]]
            self.assertEqual([r["term"] for r in job["contrasts"]], [exposure, exposure, moderator, moderator])
            self.assertEqual([r["direction"] for r in job["contrasts"]], ["positive", "negative"] * 2)
            relative = str(Path(job["contrast"]).relative_to(self.args.output))
            matrix = np.array([[int(v) for v in line.split()] for line in files[relative].split("/Matrix\n")[1].splitlines()])
            self.assertEqual(matrix.shape, (4, 10))
            np.testing.assert_array_equal(matrix[:, :7], 0)
            np.testing.assert_array_equal(matrix[:, -1], 0)  # Never retest interaction in this new batch.
            np.testing.assert_array_equal(matrix[0], -matrix[1])
            np.testing.assert_array_equal(matrix[2], -matrix[3])
            self.assertEqual(np.flatnonzero(matrix[0]).tolist(), [7])
            self.assertEqual(np.flatnonzero(matrix[2]).tolist(), [8])

    def test_full_build_16_jobs_64_results_and_resume_preserve_originals(self):
        originals = {str(p): (p.stat().st_mtime_ns, base.cohort.digest(p)) for p in self.baseline.rglob("*") if p.is_file()}
        plan = self.build()
        with patch.dict(os.environ, dict(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")):
            followup.run(self.args)
            status = json.loads((self.args.output / "status.json").read_text())
            self.assertEqual(status["status"], "complete")
            self.assertEqual(len(status["outcomes"]), 16)
            self.assertEqual(len((self.args.report / "maps.tsv").read_text().splitlines()), 65)
            product = next((self.args.output / "jobs").rglob("randomise_tstat4.nii.gz"))
            stamp = product.stat().st_mtime_ns
            report_stamp = (self.args.report / "README.md").stat().st_mtime_ns
            followup.build(self.args)
            followup.run(self.args)
            self.assertEqual(product.stat().st_mtime_ns, stamp)
            self.assertEqual((self.args.report / "README.md").stat().st_mtime_ns, report_stamp)
        self.assertEqual(len(list((self.args.output / "jobs").rglob("success.json"))), 16)
        self.assertEqual(originals, {str(p): (p.stat().st_mtime_ns, base.cohort.digest(p))
                                     for p in self.baseline.rglob("*") if p.is_file()})
        self.assertEqual(plan["images"], self.plan["images"])

    def test_baseline_design_mutation_stops_new_batch(self):
        self.build()
        path = Path(self.plan["jobs"][0]["design"])
        path.write_text("wrong row order")
        with self.assertRaisesRegex(ValueError, "Frozen input changed"):
            followup.check(self.args)

    def test_changed_additional_contrast_rejected(self):
        plan = self.build()
        Path(plan["jobs"][0]["contrast"]).write_text("changed")
        with self.assertRaisesRegex(ValueError, "contrasts changed"):
            followup.check(self.args)

    def test_fourth_output_required_and_corruption_not_overwritten(self):
        plan = self.build()
        job = plan["jobs"][0]
        folder = self.args.output / "jobs" / job["key"]
        digest = base.cohort.digest(self.args.output / "plan.json")
        with patch.dict(os.environ, dict(OPENBLAS_NUM_THREADS="1")):
            self.assertEqual(followup.execute(plan, job, folder, digest), "COMPLETED")
        receipt = json.loads((folder / "success.json").read_text())
        fourth = Path(receipt["attempt"]) / "randomise_clustere_corrp_tstat4.nii.gz"
        fourth.write_bytes(b"corrupt")
        with self.assertRaises(Exception):
            followup.execute(plan, job, folder, digest)
        self.assertEqual(fourth.read_bytes(), b"corrupt")

    def test_missing_fourth_output_is_not_success(self):
        plan = self.build()
        job = plan["jobs"][0]
        folder = self.args.output / "jobs" / job["key"]
        self.fake.write_text(self.fake.read_text().replace("range(1,5)", "range(1,4)"))
        with patch.dict(os.environ, dict(OPENBLAS_NUM_THREADS="1")), self.assertRaises(FileNotFoundError):
            followup.execute(plan, job, folder, "test")
        self.assertFalse((folder / "success.json").exists())
        self.assertTrue((folder / "attempts/attempt-0001/console.log").exists())

    def test_active_group_and_stop_prevent_duplicate(self):
        plan = self.build()
        job = plan["jobs"][0]
        folder = self.args.output / "jobs" / job["key"]
        folder.mkdir(parents=True)
        base.write_json(folder / "running.json", dict(process_group=os.getpgrp()))
        with self.assertRaisesRegex(ValueError, "refusing duplicate"):
            followup.execute(plan, job, folder, "test")
        (folder / "running.json").unlink()
        base.STOP = True
        self.assertEqual(followup.execute(plan, job, folder, "test"), "NOT_STARTED")


if __name__ == "__main__":
    unittest.main()
