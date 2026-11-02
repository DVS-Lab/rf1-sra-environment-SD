import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import nibabel as nib
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
import run_katie_remaining as remaining
import test_run_katie_main_effects as fixtures

base = remaining.base


def save(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(np.asarray(values, dtype=float), np.eye(4)), path)


class RemainingWork(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.MainEffectFlow(methodName="test_active_group_and_stop_prevent_duplicate")
        self.fixture.setUp()
        self.root, self.baseline, self.plan = self.fixture.root, self.fixture.baseline, self.fixture.plan
        self.output = self.root / "remaining"
        self.output.mkdir()
        self.args = SimpleNamespace(baseline=self.baseline, output=self.output, upstream=self.root / "upstream",
                                    task_project=self.root / "task", report=self.root / "report", jobs=4)
        _, rows = base.cohort.read_table(base.ROOT / "data/derived/model-review-v1/aligned_raw_terms.tsv")
        self.ids = [r["subject"] for r in rows]
        (self.baseline / "subjects.tsv").write_text(base.review.tsv([dict(subject=sub) for sub in self.ids]))
        self.plan["outputs"]["subjects.tsv"] = base.cohort.digest(self.baseline / "subjects.tsv")
        base.write_json(self.baseline / "plan.json", self.plan)
        plan_hash = base.cohort.digest(self.baseline / "plan.json")
        (self.baseline / "plan.sha256").write_text(plan_hash)
        for receipt in (self.baseline / "jobs").rglob("success.json"):
            saved = json.loads(receipt.read_text()); saved["plan_sha256"] = plan_hash; base.write_json(receipt, saved)
        self.pairs = []
        for index, row in enumerate(rows):
            pair = dict(subject=row["subject"], contrast="4")
            for task, value in (("socialdoors", index + 4.), ("doors", index + 1.)):
                path = self.root / "copes" / f"{row['subject']}_{task}.nii.gz"
                save(path, np.full((2, 3, 4), value))
                pair[task + "_cope"] = str(path)
                pair[task + "_fd_mean"] = row["pair_mean_fd"]
                pair[task + "_tsnr"] = row["pair_mean_tsnr"]
            self.pairs.append(pair)

    def tearDown(self):
        self.fixture.tearDown()

    def test_group_stacks_covariate_means_and_actual_thresholds(self):
        original = {p: (p.stat().st_mtime_ns, base.cohort.digest(p)) for p in self.baseline.rglob("*") if p.is_file()}
        plan = remaining.build_group(self.args, self.plan, self.pairs)
        self.assertEqual(len(plan["jobs"]), 8)
        self.assertEqual(plan["images"]["average"], self.plan["images"]["average"])
        self.assertEqual(plan["images"]["social_specific"], self.plan["images"]["social_specific"])
        for job in plan["jobs"]:
            x = remaining.matrix(Path(job["design"]))
            c = remaining.matrix(Path(job["contrast"]))
            self.assertEqual(x.shape, (97, 7))
            np.testing.assert_allclose(x[:, 1:].mean(axis=0), 0, atol=1e-10)
            np.testing.assert_array_equal(c[0], [1, 0, 0, 0, 0, 0, 0])
            np.testing.assert_array_equal(c[1], -c[0])
            self.assertEqual(job["residual_dof"], 90)
            expected = {2.6: 2.6571978972124937, 3.1: 3.1938810245004920}[job["z"]]
            self.assertAlmostEqual(job["t_cutoff"], expected, places=10)
        social = nib.load(plan["images"]["socialdoors"]).get_fdata()
        self.assertEqual(social.shape, (2, 3, 4, 97))
        np.testing.assert_array_equal(social[0, 0, 0], np.arange(97) + 4)
        self.assertEqual(original, {p: (p.stat().st_mtime_ns, base.cohort.digest(p)) for p in self.baseline.rglob("*") if p.is_file()})
        self.assertEqual(remaining.build_group(self.args, self.plan, self.pairs), plan)

    def test_group_bad_image_grid_or_changed_completed_stack_stops(self):
        plan = remaining.build_group(self.args, self.plan, self.pairs)
        Path(plan["images"]["socialdoors"]).write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "generated file changed"):
            remaining.load_checked(self.output / "activation")

    def make_ppi(self, feat, job, source_confounds=None):
        feat.mkdir(parents=True, exist_ok=True)
        rng = np.random.default_rng(1)
        x = rng.normal(size=(40, 10))
        c = np.zeros((5, 10)); c[3, 5:7] = [1, -1]
        (feat / "design.mat").write_text(base.vest_matrix(x))
        (feat / "design.con").write_text("/Matrix\n" + "\n".join(" ".join(map(str, row)) for row in c))
        settings = dict(evs_real="9", shape4="10", custom5=str(self.root / "phys.txt"))
        for i, title in enumerate(("win", "loss", "decision", "miss", "phys", "ppi-win", "ppi-loss", "ppi-dec", "ppi-miss"), 1):
            settings[f"evtitle{i}"] = title
            settings[f"deriv_yn{i}"] = "0"
        for key in ("smooth", "temphp_yn", "templp_yn", "motionevs"):
            settings[key] = job["act_settings"][key]
        for i, psychological in ((6, 1), (7, 2), (8, 3), (9, 4)):
            settings[f"interactions{i}.{psychological}"] = "1"
            settings[f"interactions{i}.5"] = "1"
        for i in range(1, 5): settings[f"custom{i}"] = job["act_settings"][f"custom{i}"]
        text = f'set feat_files(1) "{job["bold"]}"\nset confoundev_files(1) "{source_confounds or job["confounds"]}"\n'
        text += "\n".join(f'set fmri({key}) "{value}"' for key, value in settings.items())
        (feat / "design.fsf").write_text(text)
        for name in ("mask.nii.gz", "stats/cope4.nii.gz", "stats/varcope4.nii.gz"):
            save(feat / name, np.ones((2, 3, 4)))
        (feat / "stats/dof").write_text("30\n")

    def ppi_job(self):
        job = dict(key="sub-10001_ses-01_task-socialdoors_run-1", subject="10001", task="socialdoors",
                   activation=str(self.root / "activation.feat"), bold=str(self.root / "bold.nii.gz"),
                   confounds=str(self.root / "base-confounds.txt"), evroot=str(self.root / "EVfiles"),
                   old=str(self.root / "old.feat"), act_settings={"shape4": "10", "smooth": "5", "temphp_yn": "0", "templp_yn": "0", "motionevs": "0"})
        save(Path(job["bold"]), np.ones((2, 3, 4, 40)))
        Path(job["confounds"]).write_text("1\n" * 40)
        (self.root / "phys.txt").write_text("1\n" * 40)
        for i in range(1, 5):
            path = self.root / f"ev{i}.txt"; path.write_text("1 2 1\n")
            job["act_settings"][f"custom{i}"] = str(path)
        activation = Path(job["activation"]); activation.mkdir()
        (activation / "design.fsf").write_text("source activation")
        files = []
        for name in ("code/L1stats.sh", "code/project_config.sh", "masks/seed-VS.nii.gz",
                     "templates/L1_task-socialdoors_model-1_type-ppi.fsf", "templates/L1_task-doors_model-1_type-ppi.fsf"):
            path = self.args.task_project / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text("frozen source")
            files.append(str(path))
        job["files"] = files
        self.make_ppi(Path(job["old"]), job)
        return job

    def test_ppi_reuse_requires_same_no_tedana_sources_and_actual_contrast(self):
        job = self.ppi_job()
        remaining.verify_ppi(Path(job["old"]), job)
        different = self.root / "tedana-confounds.txt"; different.write_text("extra ICA regressors")
        self.make_ppi(Path(job["old"]), job, str(different))
        with self.assertRaisesRegex(ValueError, "confounds differs"):
            remaining.verify_ppi(Path(job["old"]), job)
        self.make_ppi(Path(job["old"]), job)
        path = Path(job["old"]) / "design.con"
        c = remaining.matrix(path); c[3] = 0; c[3, 4] = 1  # Seed main effect is NOT PPI outcome contrast.
        path.write_text("/Matrix\n" + "\n".join(" ".join(map(str, row)) for row in c))
        with self.assertRaisesRegex(ValueError, "PPI-win"):
            remaining.verify_ppi(Path(job["old"]), job)
        self.make_ppi(Path(job["old"]), job)
        fsf = Path(job["old"]) / "design.fsf"
        fsf.write_text(fsf.read_text().replace('fmri(interactions6.1) "1"', 'fmri(interactions6.1) "0"'))
        with self.assertRaisesRegex(ValueError, "expected task event"):
            remaining.verify_ppi(Path(job["old"]), job)

    def test_ppi_reuse_preserves_original_and_seed_check_is_required(self):
        job = self.ppi_job()
        old = Path(job["old"])
        original = {p: (p.stat().st_mtime_ns, base.cohort.digest(p)) for p in old.rglob("*") if p.is_file()}
        def extraction(call, log, environment=None):
            self.assertEqual(call[0], "fslmeants")
            Path(call[call.index("-o") + 1]).write_text("1\n" * 40)
        with patch.object(remaining, "child", side_effect=extraction):
            self.assertEqual(remaining.ppi_unit(self.args, job), "REUSED_COMPATIBLE_PPI")
        self.assertEqual(remaining.ppi_unit(self.args, job), "REUSED_PPI")
        self.assertEqual(original, {p: (p.stat().st_mtime_ns, base.cohort.digest(p)) for p in old.rglob("*") if p.is_file()})

    def test_incompatible_ppi_builds_isolated_attempt_and_never_overwrites_old(self):
        job = self.ppi_job()
        other = self.root / "tedana.txt"; other.write_text("ICA")
        self.make_ppi(Path(job["old"]), job, str(other))
        original = {p: base.cohort.digest(p) for p in Path(job["old"]).rglob("*") if p.is_file()}
        def feat(call, log, environment=None):
            self.assertEqual(call[0], "bash")
            self.assertNotIn("--overwrite", call)
            target = Path(environment["FSL_DERIVATIVES_ROOT"]) / "sub-10001/ses-01/L1_task-socialdoors_ses-01_model-1_type-ppi_seed-VS_run-1_sm-5.feat"
            self.make_ppi(target, job)
        with patch.object(remaining, "child", side_effect=feat):
            self.assertEqual(remaining.ppi_unit(self.args, job), "COMPLETED_NO_TEDANA_PPI")
        receipt = json.loads((self.output / "ppi-l1" / job["key"] / "success.json").read_text())
        self.assertFalse(receipt["reused_original"])
        self.assertNotEqual(receipt["feat"], job["old"])
        self.assertEqual(original, {p: base.cohort.digest(p) for p in Path(job["old"]).rglob("*") if p.is_file()})

    def test_complete_queue_48_randomise_jobs_and_resume(self):
        fake = self.root / "fake_remaining_randomise"
        fake.write_text(self.fixture.fake.read_text() + '\nprint("One-sample design detected; sign-flipping instead of permuting.")\n')
        fake.chmod(0o777)
        self.plan["randomise"] = str(fake)
        self.plan["sources"].append(base.fingerprint(fake))
        base.write_json(self.baseline / "plan.json", self.plan)
        digest = base.cohort.digest(self.baseline / "plan.json")
        (self.baseline / "plan.sha256").write_text(digest)
        for receipt in (self.baseline / "jobs").rglob("success.json"):
            saved = json.loads(receipt.read_text()); saved["plan_sha256"] = digest; base.write_json(receipt, saved)
        unit_source = self.root / "ppi-code"; unit_source.write_text("fixed source")
        units = [dict(key=f"sub-{sub}_ses-01_task-{task}_run-1", subject=sub, task=task, files=[str(unit_source)])
                 for sub in self.ids for task in ("socialdoors", "doors")]
        fail_first = [True]
        def ppi_unit(args, unit):
            if unit["key"] == units[0]["key"] and fail_first[0]:
                raise RuntimeError("synthetic recoverable PPI preparation failure")
            root = args.output / "ppi-l1" / unit["key"]
            receipt = root / "success.json"
            if receipt.exists(): return "REUSED_PPI"
            root.mkdir(parents=True)
            participant = self.ids.index(unit["subject"])
            for name, value in (("mask.nii.gz", 1), ("stats/cope4.nii.gz", participant + (4 if unit["task"] == "socialdoors" else 1)),
                                ("stats/varcope4.nii.gz", 1)):
                save(root / name, np.full((2, 3, 4), value))
            base.write_json(receipt, dict(job=unit, sources=[], feat=str(root),
                outputs=[base.fingerprint(p) for p in root.rglob("*.nii.gz")]))
            return "COMPLETED_NO_TEDANA_PPI"
        original_read = base.cohort.read_table
        def read(path):
            if Path(path).name == "selected_pairs.tsv": return list(self.pairs[0]), self.pairs
            return original_read(path)
        # Baseline arithmetic and actual FSL PPI lineage have independent tests;
        # this integration exercises the bounded scheduler and all job receipts.
        from concurrent.futures import ThreadPoolExecutor as NativePool
        import threading
        active, peak = [0], [0]
        lock = threading.Lock()
        class CountedPool(NativePool):
            def submit(self, function, *args, **kwargs):
                def wrapped():
                    with lock:
                        active[0] += 1; peak[0] = max(peak[0], active[0])
                    try: return function(*args, **kwargs)
                    finally:
                        with lock: active[0] -= 1
                return super().submit(wrapped)
        self.args.task_project.mkdir()
        original = {p: base.cohort.digest(p) for p in self.baseline.rglob("*") if p.is_file()}
        with patch.object(base, "check", return_value=self.plan), \
                patch.object(base.cohort, "read_table", side_effect=read), \
                patch.object(remaining.outcome, "audit", return_value=([], dict(failures=0))), \
                patch.object(remaining, "ppi_definitions", return_value=units), \
                patch.object(remaining, "ppi_unit", side_effect=ppi_unit), \
                patch.object(remaining, "ThreadPoolExecutor", CountedPool), \
                patch.object(remaining.conditional.base, "ROOT", self.root), \
                patch.dict(os.environ, dict(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")):
            # Keep actual immutable cohort/code resources addressable when ROOT is isolated.
            for name in ("code", "data", "config"):
                (self.root / name).symlink_to(fixtures.ROOT / name, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "Some branches"):
                remaining.run(self.args)
            first = json.loads((self.output / "status.json").read_text())
            self.assertEqual(first["status"], "failed")
            self.assertTrue((self.args.report / "activation/maps.tsv").exists())
            self.assertFalse((self.output / "connectivity/plan.json").exists())
            primary = next((self.output / "activation/jobs").rglob("randomise_tstat1.nii.gz"))
            primary_stamp = primary.stat().st_mtime_ns
            fail_first[0] = False
            remaining.run(self.args)
            self.assertEqual(primary.stat().st_mtime_ns, primary_stamp)
            status = json.loads((self.output / "status.json").read_text())
            self.assertEqual(status["status"], "complete")
            self.assertEqual(len(status["outcomes"]), 242)  # 48 randomise + 194 PPI units.
            average = nib.load(self.output / "connectivity/inputs/average.nii.gz").get_fdata()
            difference = nib.load(self.output / "connectivity/inputs/social_specific.nii.gz").get_fdata()
            np.testing.assert_array_equal(average[0, 0, 0], np.arange(97) + 2.5)
            np.testing.assert_array_equal(difference[0, 0, 0], np.full(97, 3.))
            self.assertLessEqual(peak[0], self.args.jobs)
            product = next((self.output / "activation/jobs").rglob("randomise_tstat1.nii.gz"))
            stamp = product.stat().st_mtime_ns
            remaining.run(self.args)
            self.assertEqual(product.stat().st_mtime_ns, stamp)
        self.assertEqual(original, {p: base.cohort.digest(p) for p in self.baseline.rglob("*") if p.is_file()})


if __name__ == "__main__":
    unittest.main()
