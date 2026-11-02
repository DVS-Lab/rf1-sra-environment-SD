import copy
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
import run_katie_randomise as runner

ROOT = Path(__file__).resolve().parents[1]


def image(path, values, affine=None):
    nib.save(nib.Nifti1Image(np.asarray(values, dtype=float), np.eye(4) if affine is None else affine), path)


def tiny_images(root, n=3):
    mask = np.ones((2, 3, 4)); mask[0, 0, 0] = 0
    image(root / "mask.nii.gz", mask)
    pairs = []
    difference = np.zeros(mask.shape + (n,), dtype=np.float32)
    expected_mean = difference.copy()
    for i in range(n):
        sub = str(10001 + i)
        row = dict(subject=sub, contrast="4")
        a, b = np.full(mask.shape, i + 4.), np.full(mask.shape, i + 1.)
        for task, data in (("socialdoors", a), ("doors", b)):
            path = root / f"{sub}_{task}.nii.gz"
            image(path, data)
            row[task + "_cope"] = str(path)
        pairs.append(row)
        difference[..., i][mask > 0] = (a - b)[mask > 0]
        expected_mean[..., i][mask > 0] = ((a + b) / 2)[mask > 0]
    image(root / "difference.nii.gz", difference)
    return pairs, [r["subject"] for r in pairs], expected_mean


class ImagesAndDesigns(unittest.TestCase):
    def test_difference_and_mean_arithmetic_common_mask(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pairs, ids, expected = tiny_images(root)
            _, actual = runner.image_arrays(pairs, ids, root / "difference.nii.gz", root / "mask.nii.gz")
            np.testing.assert_array_equal(actual, expected)
            self.assertTrue(np.isfinite(actual).all())
            self.assertTrue((actual[0, 0, 0] == 0).all())

    def test_wrong_direction_and_grid_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pairs, ids, _ = tiny_images(root)
            path = root / "difference.nii.gz"
            values = nib.load(path).get_fdata()
            image(path, -values)
            with self.assertRaisesRegex(ValueError, "direction"):
                runner.image_arrays(pairs, ids, path, root / "mask.nii.gz")
            affine = np.eye(4); affine[0, 3] = 1
            image(path, values, affine)
            with self.assertRaisesRegex(ValueError, "grid mismatch"):
                runner.image_arrays(pairs, ids, path, root / "mask.nii.gz")

    def test_approved_real_97_person_designs_and_t_thresholds(self):
        config = runner.approved_config()
        _, raw = runner.cohort.read_table(ROOT / "data/derived/model-review-v1/aligned_raw_terms.tsv")
        _, table = runner.cohort.read_table(ROOT / "data/derived/model-review-v1/centered_candidate_terms.tsv")
        terms = {name: np.array([float(r[name]) for r in table]) for name in table[0] if name != "subject"}
        files, jobs = runner.make_designs(Path("/analysis"), config, [r["subject"] for r in raw], terms)
        self.assertEqual(len(jobs), 24)
        self.assertEqual(len({j["key"] for j in jobs}), 24)
        for job in jobs:
            expected = config["inference"]["verified_t_thresholds"][str(job["residual_dof"])][str(job["z"])]
            self.assertAlmostEqual(job["t_cutoff"], expected, places=10)
            self.assertEqual(job["permutations"], 10000)
        self.assertIn("delta_fd", files["designs/social_specific/adi/design.tsv"])
        self.assertIn("pair_mean_fd", files["designs/average/adi/design.tsv"])
        for name, text in files.items():
            if name.endswith("design.mat"):
                header, data = text.split("/Matrix\n")
                self.assertIn("/NumPoints\t97", header)
                self.assertEqual(len(data.strip().splitlines()), 97)
            if name.endswith("design.con"):
                rows = text.split("/Matrix\n")[1].strip().splitlines()
                x = np.array([[float(v) for v in row.split()] for row in rows])
                np.testing.assert_array_equal(x[1], -x[0])
                self.assertEqual(np.count_nonzero(x[0]), 1)

    def test_no_tfce_no_unconverted_z_and_smoke_is_separate(self):
        plan = dict(randomise="/fsl/randomise", images={"average": "/inputs/mean.nii.gz"}, mask="/mask.nii.gz")
        job = dict(outcome="average", design="design.mat", contrast="design.con", t_cutoff=3.19721001565352,
                   permutations=10000, seed=20261101)
        command = runner.command(plan, job, Path("/attempt/randomise"))
        self.assertIn("-c", command)
        self.assertNotIn("-T", command)
        self.assertNotIn("-D", command)
        self.assertEqual(command[command.index("-n") + 1], "10000")
        self.assertNotEqual(command[command.index("-c") + 1], "3.1")
        smoke = runner.command(plan, job, Path("/smoke/randomise"), permutations=2)
        self.assertEqual(smoke[smoke.index("-n") + 1], "2")


class ReceiptAndRetry(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.pairs, ids, _ = tiny_images(self.root)
        self.fake = self.root / "fake_randomise"
        self.fake.write_text(f"#!{sys.executable}\n" + """import sys
import nibabel as nib
import numpy as np
args=sys.argv[1:]
prefix=args[args.index('-o')+1]
mask=nib.load(args[args.index('-m')+1])
for i in (1,2):
    for suffix in (f'_tstat{i}.nii.gz',f'_clustere_corrp_tstat{i}.nii.gz'):
        data=np.ones(mask.shape)*(0.9 if 'corrp' in suffix else i)
        nib.save(nib.Nifti1Image(data,mask.affine),prefix+suffix)
""")
        self.fake.chmod(self.fake.stat().st_mode | stat.S_IXUSR)
        self.plan = dict(randomise=str(self.fake), images=dict(social_specific=str(self.root / "difference.nii.gz")),
                         mask=str(self.root / "mask.nii.gz"))
        self.job = dict(key="social_specific/adi/z-2p6", outcome="social_specific", design="design.mat",
                        contrast="design.con", t_cutoff=2.6578538828, permutations=10000, seed=1)
        self.folder = self.root / "job"
        runner.STOP = False

    def tearDown(self):
        self.temporary.cleanup()

    def test_complete_reuse_and_corruption_never_overwritten(self):
        self.assertEqual(runner.execute(self.plan, self.job, self.folder, "plan"), "COMPLETED")
        receipt = json.loads((self.folder / "success.json").read_text())
        product = Path(receipt["outputs"][0]["path"])
        stamp = product.stat().st_mtime_ns
        self.assertEqual(runner.execute(self.plan, self.job, self.folder, "plan"), "REUSED")
        self.assertEqual(stamp, product.stat().st_mtime_ns)
        product.write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "Frozen input changed"):
            runner.execute(self.plan, self.job, self.folder, "plan")
        self.assertEqual(product.read_bytes(), b"corrupt")

    def test_partial_attempt_preserved_and_new_attempt_used(self):
        partial = self.folder / "attempts/attempt-0001"
        partial.mkdir(parents=True)
        (partial / "partial.txt").write_text("preserve me")
        self.assertEqual(runner.execute(self.plan, self.job, self.folder, "plan"), "COMPLETED")
        self.assertEqual((partial / "partial.txt").read_text(), "preserve me")
        receipt = json.loads((self.folder / "success.json").read_text())
        self.assertTrue(receipt["attempt"].endswith("attempt-0002"))

    def test_live_group_blocks_duplicate_and_no_stop_launch(self):
        self.folder.mkdir()
        runner.write_json(self.folder / "running.json", dict(process_group=os.getpgrp()))
        with self.assertRaisesRegex(ValueError, "refusing duplicate"):
            runner.execute(self.plan, self.job, self.folder, "plan")
        (self.folder / "running.json").unlink()
        runner.STOP = True
        try:
            self.assertEqual(runner.execute(self.plan, self.job, self.folder, "plan"), "NOT_STARTED")
            self.assertFalse((self.folder / "attempts").exists())
        finally:
            runner.STOP = False

    def test_bad_exit_is_logged_and_preserved(self):
        self.fake.write_text(f"#!{sys.executable}\nimport sys\nprint('test failure')\nsys.exit(3)\n")
        with self.assertRaisesRegex(RuntimeError, "test failure"):
            runner.execute(self.plan, self.job, self.folder, "plan")
        self.assertFalse((self.folder / "success.json").exists())
        self.assertTrue((self.folder / "attempts/attempt-0001/console.log").exists())

    def test_completed_receipt_cannot_be_reused_for_changed_job(self):
        runner.execute(self.plan, self.job, self.folder, "plan")
        changed = dict(self.job, t_cutoff=3.1)
        with self.assertRaisesRegex(ValueError, "receipt differs"):
            runner.execute(self.plan, changed, self.folder, "plan")


class CompleteSyntheticFlow(unittest.TestCase):
    def test_build_check_all_24_jobs_results_and_resume(self):
        fixture = ReceiptAndRetry(methodName="test_bad_exit_is_logged_and_preserved")
        fixture.setUp()
        try:
            root = fixture.root
            upstream = root / "upstream"
            upstream.mkdir()
            actual_upstream = ROOT.parent / "rf1-sra-linux2-geometry"
            if not actual_upstream.exists():
                actual_upstream = ROOT.parent / "rf1-sra-linux2"
            expected, summary = runner.cohort.generate(ROOT, actual_upstream)
            original_read = runner.cohort.read_table
            fields, original_pairs = original_read(ROOT / "data/derived/katie-cohort-v1/selected_pairs.tsv")
            _, raw = original_read(ROOT / "data/derived/model-review-v1/aligned_raw_terms.tsv")
            eras = {r["subject"]: r["software_era"] for r in raw}
            _, order = original_read(ROOT / "data/derived/katie-cohort-v1/subjects.tsv")
            ids = [r["subject"] for r in order]
            pairs = [dict(r) for r in original_pairs if r["contrast"] == "4"]
            shape = (2, 3, 4)
            mask = np.ones(shape); mask[0, 0, 0] = 0
            difference = np.zeros(shape + (97,), dtype=np.float32)
            for i, row in enumerate(pairs):
                for task in runner.cohort.TASKS:
                    for field in ("cope", "varcope", "mask"):
                        path = root / f"{row['subject']}_{task}_{field}.nii.gz"
                        value = np.full(shape, (i + 4. if task == "socialdoors" else i + 1.) if field == "cope" else 1.)
                        if field == "mask":
                            value = mask
                        image(path, value)
                        row[task + "_" + field] = str(path)
                    dof = root / f"{row['subject']}_{task}_dof"
                    dof.write_text("100\n")
                    row[task + "_dof"] = str(dof)
                    sidecar = upstream / f"bids/sub-{row['subject']}/ses-01/func/sub-{row['subject']}_ses-01_task-{task}_run-1_echo-2_part-mag_bold.json"
                    sidecar.parent.mkdir(parents=True, exist_ok=True)
                    runner.write_json(sidecar, dict(SoftwareVersions="syngo MR " + eras[row["subject"]]))
                difference[..., i][mask > 0] = 3

            def read(path):
                if Path(path) == ROOT / "data/derived/katie-cohort-v1/selected_pairs.tsv":
                    return fields, pairs
                return original_read(path)

            native_run = runner.subprocess.run

            def subset_builder(call, **kwargs):
                if len(call) > 1 and str(call[1]).endswith("build_socialdoors_randomise.py"):
                    subset = upstream / "work/randomise-katie-final-v1"
                    if call[2] == "build":
                        (subset / "cope-4").mkdir(parents=True)
                        image(subset / "cope-4/difference_4d.nii.gz", difference)
                        image(subset / "cope-4/mask.nii.gz", mask)
                        (subset / "subjects.tsv").write_text(runner.review.tsv(order))
                        runner.write_json(subset / "plan.json", dict(sources=[]))
                        runner.write_json(subset / "artifacts.json", {})
                    return runner.subprocess.CompletedProcess(call, 0)
                return native_run(call, **kwargs)

            args = SimpleNamespace(output=root / "analysis", upstream=upstream,
                                   randomise=str(fixture.fake), jobs=4)
            environment = dict(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
            with patch.object(runner.cohort, "generate", return_value=(expected, summary)), \
                    patch.object(runner.cohort, "read_table", side_effect=read), \
                    patch.object(runner.subprocess, "run", side_effect=subset_builder), \
                    patch.dict(os.environ, environment):
                runner.build(args)
                runner.check(args)
                runner.run(args)
                self.assertEqual(json.loads((args.output / "status.json").read_text())["status"], "complete")
                product = next((args.output / "jobs").rglob("randomise_tstat1.nii.gz"))
                stamp = product.stat().st_mtime_ns
                runner.build(args)
                runner.run(args)
                self.assertEqual(product.stat().st_mtime_ns, stamp)
                self.assertEqual(len(list((args.output / "jobs").rglob("success.json"))), 24)
                self.assertEqual((args.output / "subjects.tsv").read_text(), runner.review.tsv(order))
        finally:
            fixture.tearDown()


if __name__ == "__main__":
    unittest.main()
