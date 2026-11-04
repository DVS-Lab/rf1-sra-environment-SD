import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import nibabel as nib
import numpy as np
from scipy.stats import norm, t

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
import run_fevs_imaging_adjustments as runner

base = runner.base


class ImagingAdjustments(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "old-live-checkout"
        self.project.mkdir()
        self.release = self.root / "frozen-release"
        shutil.copytree(runner.ROOT / "data", self.release / "data")
        shutil.copytree(runner.ROOT / "config", self.release / "config")
        self.ids, self.values = runner.behavior.inputs(self.release)
        self.source = self.project / "derivatives/fsl/randomise/katie-reward-extension-v1"
        self.source.mkdir(parents=True)
        self.args = SimpleNamespace(project=self.project, jobs=18,
            output=self.source.parent / runner.VERSION)
        _, rows = base.cohort.read_table(self.release / "data/derived/model-review-v1/centered_candidate_terms.tsv")
        nuisance = np.array([[float(r[n]) for n in runner.COMMON] for r in rows])
        self.original = dict(n=97, jobs=[], images={}, masks={}, sources=[], outputs={})
        mask = self.source / "mask.nii.gz"
        nib.save(nib.Nifti1Image(np.ones((2, 2, 2)), np.eye(4)), mask)
        image = self.source / "subjects-image.nii.gz"
        nib.save(nib.Nifti1Image(np.broadcast_to(np.arange(97, dtype=float), (2, 2, 2, 97)), np.eye(4)), image)
        self.fake = self.root / "randomise"
        self.fake.write_text(f'''#!{sys.executable}
import sys
import nibabel as nib
import numpy as np
args=sys.argv
mask=nib.load(args[args.index('-m')+1])
prefix=args[args.index('-o')+1]
count=int(open(args[args.index('-t')+1]).read().split('/NumContrasts')[1].split()[0])
for i in range(1,count+1):
    for suffix,value in ((f'_tstat{{i}}.nii.gz',4. if i%2 else -4.),
                         (f'_clustere_corrp_tstat{{i}}.nii.gz',.96 if i%2 else 0.)):
        nib.save(nib.Nifti1Image(np.full(mask.shape,value),mask.affine),prefix+suffix)
''')
        self.fake.chmod(0o755)
        self.original["randomise"] = str(self.fake)
        for target, family, outcome, model in runner.TARGETS:
            names = runner.COMMON + (["fevs"] if model == "fevs" else ["fevs", "pm25", "fevsxpm25"])
            p = self.values["fevs"] - self.values["fevs"].mean()
            q = self.values["pm25"] - self.values["pm25"].mean()
            x = np.column_stack([nuisance, p] if model == "fevs" else [nuisance, p, q, p*q])
            folder = self.source / "designs" / target
            folder.mkdir(parents=True)
            (folder / "design.mat").write_text(base.vest_matrix(x))
            (folder / "design.tsv").write_text(base.review.tsv(
                [dict(subject=s, **dict(zip(names, row))) for s, row in zip(self.ids, x)]))
            terms = ["fevs"] if model == "fevs" else ["fevs", "pm25", "fevsxpm25"]
            text, definitions = runner.extension.contrast_text(names, terms)
            (folder / "design.con").write_text(text)
            self.original["images"][family + "/" + outcome] = str(image)
            self.original["masks"][family] = str(mask)
            for z in (2.6, 3.1):
                self.original["jobs"].append(dict(key=f"{family}/{outcome}/{model}/z-"+str(z).replace(".", "p"),
                    family=family, outcome=family+"/"+outcome, model=model, z=z,
                    residual_dof=97-len(names), t_cutoff=float(t.isf(norm.sf(z),97-len(names))),
                    permutations=10000, seed=20261101, design=str(folder/"design.mat"),
                    contrast=str(folder/"design.con"), contrasts=definitions))
        (self.source / "subjects.tsv").write_text(base.review.tsv([dict(subject=s) for s in self.ids]))
        legacy = self.project / "derivatives/fsl/randomise/katie-main-effects-v1/plan.json"
        legacy.parent.mkdir(parents=True)
        legacy.write_text('{"synthetic_legacy_receipt": true}\n')
        self.original["sources"] = [dict(path=str(legacy), sha256=base.cohort.digest(legacy))]
        self.original["outputs"] = {str(p.relative_to(self.source)): base.cohort.digest(p)
                                    for p in self.source.rglob("*") if p.is_file()}
        base.write_json(self.source / "plan.json", self.original)
        (self.source / "plan.sha256").write_text(base.cohort.digest(self.source / "plan.json"))
        for job in self.original["jobs"]:
            self.assertEqual(runner.extension.execute(self.original, job,
                self.source / "jobs" / job["key"], base.cohort.digest(self.source/"plan.json")), "COMPLETED")
        self.protected = {str(p): base.cohort.digest(p) for p in self.source.rglob("*") if p.is_file()}
        self.root_patch = patch.object(runner, "ROOT", self.release)
        self.check_patch = patch.object(runner.extension, "check", return_value=self.original)
        self.root_patch.start()
        self.check_patch.start()
        base.STOP = False
        base.LEASE_FD = None

    def tearDown(self):
        self.root_patch.stop()
        self.check_patch.stop()
        self.temp.cleanup()
        base.STOP = False
        base.LEASE_FD = None

    def test_catalog_preserves_base_columns_and_adds_only_centered_adjustments(self):
        files, jobs, baselines = runner.specification(self.args.output, self.original, self.ids, self.values)
        self.assertEqual((len(jobs), len(baselines)), (18, 6))
        self.assertEqual(sum(len(j["contrasts"]) for j in jobs), 36)
        for job in jobs:
            target = next(b["job"] for b in baselines if b["target"] == job["target"] and b["job"]["z"] == job["z"])
            old = runner.extension.audit.matrix(target["design"])
            relative = str(Path(job["design"]).relative_to(self.args.output))
            x = np.loadtxt(io.StringIO(files[relative].split("/Matrix")[1]), ndmin=2)
            np.testing.assert_array_equal(old, x[:, :old.shape[1]])
            added = job["columns"][old.shape[1]:]
            for index, name in enumerate(added, old.shape[1]):
                np.testing.assert_array_equal(x[:, index], self.values[name]-self.values[name].mean())
            self.assertEqual(job["residual_dof"], 97-x.shape[1])
            self.assertAlmostEqual(job["t_cutoff"], t.isf(norm.sf(job["z"]), job["residual_dof"]), places=12)
            relative = str(Path(job["contrast"]).relative_to(self.args.output))
            c = np.loadtxt(io.StringIO(files[relative].split("/Matrix")[1]), ndmin=2)
            self.assertEqual(np.flatnonzero(c[0]).tolist(), [7])
            np.testing.assert_array_equal(c[1], -c[0])

    def test_archived_inputs_not_stale_live_checkout_and_full_native_resume(self):
        self.assertFalse((self.project/"data").exists())
        self.assertFalse((self.project/"config").exists())
        self.args.jobs = 4
        runner.run(self.args)
        plan = runner.check(self.args)
        self.assertEqual(plan["data_root"], str(self.release))
        self.assertTrue(all(set(r)=={"path", "sha256", "size"} for r in plan["sources"]))
        receipts = {str(p): p.stat().st_mtime_ns for p in self.args.output.rglob("success.json")}
        runner.run(self.args)
        self.assertEqual(receipts, {str(p): p.stat().st_mtime_ns for p in self.args.output.rglob("success.json")})
        self.assertEqual(self.protected, {str(p): base.cohort.digest(p) for p in self.source.rglob("*") if p.is_file()})
        report = self.args.output/"report"
        _, maps = base.cohort.read_table(report/"maps.tsv")
        self.assertEqual(len(maps), 48)
        self.assertEqual(sum(r["adjustment"]=="baseline" for r in maps), 12)
        self.assertTrue(json.loads((report/"review_manifest.json").read_text())["provisional_scoring"])
        from publish_katie_review import payload
        self.assertEqual(len(payload(report)), 5)

    def test_wrong_order_duplicates_and_nonfinite_adjustment_stop(self):
        job = self.original["jobs"][0]
        for ids in (self.ids[::-1], [self.ids[0]]*97, self.ids[:-1]):
            with self.assertRaisesRegex(ValueError, "participant order"):
                runner.design(job, ids, self.values, ("adi",))
        bad = dict(self.values, adi=self.values["adi"].copy())
        bad["adi"][0] = np.nan
        with self.assertRaisesRegex(ValueError, "finite, full-rank"):
            runner.design(job, self.ids, bad, ("adi",))

    def test_rank_deficiency_and_unauthorized_interactions_stop(self):
        bad = dict(self.values, adi=self.values["fevs"].copy())
        with self.assertRaisesRegex(ValueError, "full-rank"):
            runner.design(self.original["jobs"][0], self.ids, bad, ("adi",))
        with self.assertRaisesRegex(ValueError, "three requested"):
            runner.design(self.original["jobs"][0], self.ids, self.values, ("fevsxadi",))

    def test_baseline_score_or_conditional_interaction_mismatch_stops(self):
        bad = dict(self.values, fevs=self.values["fevs"]+np.arange(97))
        with self.assertRaisesRegex(ValueError, "approved centered scores"):
            runner.design(self.original["jobs"][0], self.ids, bad, ("adi",))
        job = next(j for j in self.original["jobs"] if j["model"]=="fevsxpm25")
        path = Path(job["design"])
        x = runner.extension.audit.matrix(path)
        x[0,-1] += 1
        path.write_text(base.vest_matrix(x))
        fields, rows = base.cohort.read_table(path.with_suffix(".tsv"))
        rows[0]["fevsxpm25"] = x[0,-1]
        path.with_suffix(".tsv").write_text(base.review.tsv(rows, fields))
        with self.assertRaisesRegex(ValueError, "intercept/interaction"):
            runner.design(job, self.ids, self.values, ("adi",))

    def test_completed_native_command_and_missing_products_stop(self):
        job = self.original["jobs"][0]
        receipt = self.source/"jobs"/job["key"]/"success.json"
        saved = json.loads(receipt.read_text())
        saved["command"][0] = "/wrong/randomise"
        base.write_json(receipt, saved)
        with self.assertRaisesRegex(ValueError, "command, receipt or products"):
            runner.build(self.args)

    def test_changed_input_design_or_mask_refuses_resume(self):
        plan = runner.build(self.args)
        mask = Path(plan["masks"]["activation"])
        nib.save(nib.Nifti1Image(np.zeros((2,2,2)),np.eye(4)),mask)
        with self.assertRaisesRegex(ValueError, "Frozen input changed"):
            runner.check(self.args)

    def test_live_orphan_refuses_duplicate_execution(self):
        plan = runner.build(self.args)
        job = plan["jobs"][0]
        folder = self.args.output/"jobs"/job["key"]
        base.write_json(folder/"running.json", dict(process_group=os.getpgrp()))
        with self.assertRaisesRegex(ValueError, "active/orphan"):
            runner.extension.execute(plan,job,folder,base.cohort.digest(self.args.output/"plan.json"))

    def test_missing_baseline_product_stops_before_any_new_job(self):
        job = self.original["jobs"][0]
        path = self.source/"jobs"/job["key"]/"success.json"
        prefix = Path(json.loads(path.read_text())["attempt"])/"randomise"
        Path(str(prefix)+"_clustere_corrp_tstat1.nii.gz").unlink()
        with self.assertRaises(FileNotFoundError):
            runner.build(self.args)
        self.assertFalse(self.args.output.exists())

    def test_changed_adjustment_design_is_not_replaced(self):
        plan = runner.build(self.args)
        path = Path(plan["jobs"][0]["design"])
        path.write_text(path.read_text()+"\n")
        altered = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "Frozen design"):
            runner.check(self.args)
        self.assertEqual(path.read_bytes(), altered)

    def test_unrecognized_output_is_not_overwritten(self):
        self.args.output.mkdir()
        path = self.args.output/"keep.txt"
        path.write_text("preserve")
        with self.assertRaisesRegex(ValueError, "Unrecognized"):
            runner.build(self.args)
        self.assertEqual(path.read_text(), "preserve")

    def test_optional_size_normalization_keeps_hash_and_rejects_real_changes(self):
        record = self.original["sources"][0]
        normalized = runner.normalize_sources({record["path"]: record})
        self.assertEqual(normalized, [dict(record, path=str(Path(record["path"]).resolve()),
                                           size=Path(record["path"]).stat().st_size)])
        base.verify_sources(normalized)
        Path(record["path"]).write_text("a genuinely changed source\n")
        with self.assertRaisesRegex(ValueError, "fingerprint failure"):
            runner.normalize_sources({record["path"]: record})

    def test_incorrect_recorded_size_is_not_replaced(self):
        record = dict(self.original["sources"][0], size=-1)
        with self.assertRaisesRegex(ValueError, "fingerprint failure"):
            runner.normalize_sources({record["path"]: record})

    def test_failed_v1_plan_is_untouched(self):
        failed = self.source.parent / "katie-fevs-adjustments-provisional-v1"
        failed.mkdir()
        (failed/"plan.json").write_text('{"preserve_failed_plan": true}\n')
        before = (failed/"plan.json").read_bytes()
        plan = runner.build(self.args)
        self.assertIn("provisional-v2", str(self.args.output))
        self.assertEqual((failed/"plan.json").read_bytes(), before)
        self.assertTrue(all("size" in r for r in plan["sources"]))


if __name__ == "__main__":
    unittest.main()
