import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import nibabel as nib
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"code"))
import run_corrected_mspss as runner

base = runner.base


class CorrectedMSPSS(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.release = self.root/"release"
        shutil.copytree(runner.ROOT/"data", self.release/"data")
        shutil.copytree(runner.ROOT/"config", self.release/"config")
        self.ids, self.values = runner.adjustments.behavior.inputs(self.release)
        self.corrected = runner.corrected_scores(self.release, self.ids, self.values["mspss"])
        self.project = self.root/"stale-checkout"
        self.source = self.project/"derivatives/fsl/randomise/katie-reward-extension-v1"
        self.source.mkdir(parents=True)
        self.args = SimpleNamespace(project=self.project, output=self.source.parent/runner.VERSION, jobs=8)
        self.original = dict(n=97, project=str(self.project), jobs=[], coverage=[], images={}, masks={},
                             sources=[], outputs={}, exclusions_changed=False, original_results_changed=False)
        mask = self.source/"mask.nii.gz"
        image = self.source/"ordered-4d.nii.gz"
        nib.save(nib.Nifti1Image(np.ones((2, 2, 2)), np.eye(4)), mask)
        nib.save(nib.Nifti1Image(np.broadcast_to(np.arange(97, dtype=float), (2, 2, 2, 97)), np.eye(4)), image)
        fake = self.root/"randomise"
        fake.write_text(f'''#!{sys.executable}
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
        fake.chmod(0o755)
        self.original["randomise"] = str(fake)
        _, covariates = base.cohort.read_table(self.release/"data/derived/model-review-v1/centered_candidate_terms.tsv")
        for family in ("activation", "connectivity"):
            self.original["masks"][family] = str(mask)
            for outcome in runner.OUTCOMES:
                self.original["images"][family+"/"+outcome] = str(image)
                for model in runner.MODELS:
                    first = model.split("x")[0]
                    nuisance = ["ones", *(["pair_mean_fd", "pair_mean_tsnr"] if outcome == "average"
                                else ["delta_fd", "delta_tsnr"]), "e11", "xa30", "gender_code1", "age"]
                    names = nuisance + [first, "mspss", model]
                    p = self.values[first]-self.values[first].mean()
                    q = self.values["mspss"]-self.values["mspss"].mean()
                    x = np.column_stack([np.array([[float(r[n]) for n in nuisance] for r in covariates]), p, q, p*q])
                    folder = self.source/"designs"/family/outcome/model
                    folder.mkdir(parents=True)
                    (folder/"design.mat").write_text(base.vest_matrix(x))
                    (folder/"design.tsv").write_text(base.review.tsv(
                        [dict(subject=s, **dict(zip(names, row))) for s, row in zip(self.ids, x)]))
                    text, definitions = runner.extension.contrast_text(names, names[7:])
                    (folder/"design.con").write_text(text)
                    for z in (2.6, 3.1):
                        job = dict(key=f"{family}/{outcome}/{model}/z-{z}", family=family,
                                   outcome=family+"/"+outcome, model=model, z=z,
                                   design=str(folder/"design.mat"), contrast=str(folder/"design.con"))
                        retained = family == "activation" and outcome in ("social_specific", "average") and first in ("adi", "pm25")
                        if not retained:
                            self.original["jobs"].append(job)
                        for d in definitions:
                            source = dict(origin="existing", source_job=job, index=d["index"]) if retained else dict(
                                origin="extension", job=job["key"], index=d["index"])
                            self.original["coverage"].append(dict(family=family, outcome=outcome, model=model,
                                z=z, term=d["term"], direction=d["direction"], source=source))
        self.original["jobs"] += [dict(key=f"unaffected-{i}") for i in range(220-len(self.original["jobs"]))]
        self.original["coverage"] += [dict(family="activation", outcome="average", model="unaffected")
                                      for _ in range(1328-len(self.original["coverage"]))]
        (self.source/"subjects.tsv").write_text(base.review.tsv([dict(subject=s) for s in self.ids]))
        legacy = self.root/"legacy.json"
        legacy.write_text('{"legacy":true}\n')
        self.original["sources"] = [dict(path=str(legacy), sha256=base.cohort.digest(legacy))]
        self.original["outputs"] = {str(p.relative_to(self.source)): base.cohort.digest(p)
                                    for p in self.source.rglob("*") if p.is_file()}
        base.write_json(self.source/"plan.json", self.original)
        (self.source/"plan.sha256").write_text(base.cohort.digest(self.source/"plan.json")+"\n")
        self.protected = {str(p): base.cohort.digest(p) for p in self.source.rglob("*") if p.is_file()}
        self.root_patch = patch.object(runner, "ROOT", self.release)
        self.root_patch.start()
        base.STOP = False
        base.LEASE_FD = None

    def tearDown(self):
        self.root_patch.stop()
        base.STOP = False
        base.LEASE_FD = None
        self.temp.cleanup()

    def test_exact_scope_retained_models_and_only_mspss_columns_change(self):
        files, jobs, references = runner.specification(self.args.output, self.original, self.ids, self.values, self.corrected)
        self.assertEqual(len(jobs), 64)
        self.assertEqual(sum(len(j["contrasts"]) for j in jobs), 384)
        self.assertEqual({j["model"] for j in jobs}, set(runner.MODELS))
        self.assertEqual(len(references), 96)
        for job in jobs:
            relative = Path(job["design"]).relative_to(self.args.output)
            old = runner.extension.audit.matrix(self.source/relative)
            x = np.loadtxt(io.StringIO(files[str(relative)].split("/Matrix")[1]), ndmin=2)
            np.testing.assert_array_equal(x[:, :8], old[:, :8])
            np.testing.assert_array_equal(x[:, 8], self.corrected-self.corrected.mean())
            np.testing.assert_array_equal(x[:, 9], x[:, 7]*x[:, 8])
            self.assertEqual(job["residual_dof"], 87)
            contrast = files[str(Path(job["contrast"]).relative_to(self.args.output))]
            c = np.loadtxt(io.StringIO(contrast.split("/Matrix")[1]), ndmin=2)
            for i, column in enumerate((7, 8, 9)):
                self.assertEqual(np.flatnonzero(c[2*i]).tolist(), [column])
                np.testing.assert_array_equal(c[2*i+1], -c[2*i])

    def test_native_run_resume_and_frozen_release_not_live_data(self):
        self.assertFalse((self.project/"data").exists())
        runner.run(self.args)
        plan = runner.check(self.args)
        self.assertTrue(all(set(r) == {"path", "sha256", "size"} for r in plan["sources"]))
        receipts = {str(p): p.stat().st_mtime_ns for p in self.args.output.rglob("success.json")}
        self.assertEqual(len(receipts), 66)
        runner.run(self.args)
        self.assertEqual(receipts, {str(p): p.stat().st_mtime_ns for p in self.args.output.rglob("success.json")})
        self.assertEqual(self.protected, {str(p): base.cohort.digest(p) for p in self.source.rglob("*") if p.is_file()})
        _, maps = base.cohort.read_table(self.args.output/"report/maps.tsv")
        self.assertEqual(len(maps), 384)
        self.assertEqual({r["term"] for r in maps}, {"adi", "pm25", "fevs", "oafem", "mspss", *runner.MODELS})
        self.assertTrue(json.loads((self.args.output/"status.json").read_text())["validated"])
        from publish_katie_review import payload
        self.assertEqual(len(payload(self.args.output/"report")), 5)

    def test_source_and_design_tampering_stop_without_overwrite(self):
        plan = runner.build(self.args)
        mat = Path(plan["jobs"][0]["design"])
        mat.write_text(mat.read_text()+"\n")
        with self.assertRaisesRegex(ValueError, "Frozen corrected design"):
            runner.check(self.args)
        self.assertTrue(mat.read_text().endswith("\n\n"))
        self.assertEqual(self.protected, {str(p): base.cohort.digest(p) for p in self.source.rglob("*") if p.is_file()})

    def test_source_provenance_order_range_and_legacy_hash_not_adopted(self):
        with self.assertRaisesRegex(ValueError, "order differ"):
            runner.corrected_scores(self.release, self.ids[::-1], self.values["mspss"])
        with self.assertRaisesRegex(ValueError, "recoding increment"):
            runner.corrected_scores(self.release, self.ids, self.values["mspss"]+10)
        legacy = Path(self.original["sources"][0]["path"])
        legacy.write_text("changed\n")
        with self.assertRaisesRegex(ValueError, "Frozen source/result changed"):
            runner.build(self.args)
        self.assertFalse((self.args.output/"plan.json").exists())

    def test_duplicate_coverage_wrong_matrix_and_row_order_fail(self):
        bad = json.loads(json.dumps(self.original))
        bad["coverage"][1] = dict(bad["coverage"][0])
        with self.assertRaisesRegex(ValueError, "duplicate original"):
            runner.specification(self.args.output, bad, self.ids, self.values, self.corrected)
        job = self.original["jobs"][0]
        with self.assertRaisesRegex(ValueError, "participant order"):
            runner.design(job, self.ids[::-1], self.values, self.corrected, "social_specific", job["model"])
        wrong = dict(self.values, mspss=self.values["mspss"]+np.arange(97))
        with self.assertRaisesRegex(ValueError, "authenticated centered scores"):
            runner.design(job, self.ids, wrong, self.corrected, "social_specific", job["model"])

    def test_changed_original_plan_and_unknown_output_fail_closed(self):
        (self.source/"plan.json").write_text("{}\n")
        with self.assertRaisesRegex(ValueError, "plan seal differs"):
            runner.build(self.args)
        self.args.output.mkdir()
        with self.assertRaisesRegex(ValueError, "Unrecognized existing"):
            runner.build(self.args)

    def test_launcher_bounds_syntax_and_single_thread_configuration(self):
        launcher = Path(runner.__file__).with_name("launch_corrected_mspss.sh")
        subprocess.run(["bash", "-n", str(launcher)], check=True)
        for value in ("0", "81", "oops"):
            result = subprocess.run(["bash", str(launcher), "--jobs", value], cwd=self.project,
                                    text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("LAUNCHED:", result.stdout)
        text = launcher.read_text()
        for required in ("umask 0000", "JOBS=75", "OMP_NUM_THREADS=1", "OPENBLAS_NUM_THREADS=1",
                         "MKL_NUM_THREADS=1", "NUMEXPR_NUM_THREADS=1", "nohup setsid", "publish_run_logs.py",
                         "--sync-checkout", "tar.umask=0000 archive", "chmod 0777"):
            self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
