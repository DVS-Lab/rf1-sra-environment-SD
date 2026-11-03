import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

import nibabel as nib
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"code"))
import run_pm25_components as components
import test_run_katie_main_effects as fixtures

base = components.base


class Components(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.MainEffectFlow(methodName="test_active_group_and_stop_prevent_duplicate")
        self.fixture.setUp()
        self.root, self.plan, self.args = self.fixture.root, self.fixture.plan, self.fixture.args
        self.args.jobs = 6
        self.data_root = self.root/"release"
        cohort = self.data_root/"data/derived/katie-cohort-v1"; cohort.mkdir(parents=True)
        shutil.copyfile(base.ROOT/"data/derived/katie-cohort-v1/subjects.tsv", cohort/"subjects.tsv")
        _, roster = base.cohort.read_table(cohort/"subjects.tsv")
        self.ids = [r["subject"] for r in roster]
        self.mask = nib.load(self.plan["mask"])
        self.pairs = []
        differences = np.zeros(self.mask.shape+(97,), dtype=np.float32)
        for index, subject in enumerate(self.ids):
            row_tasks = {}
            for task in ("socialdoors", "doors"):
                feat = self.root/"L1"/subject/task; (feat/"stats").mkdir(parents=True)
                (feat/"design.fsf").write_text('set fmri(conname_real.1) "win"\nset fmri(conname_real.2) "loss"\nset fmri(conname_real.4) "win-loss"\n')
                (feat/"design.con").write_text('/Matrix\n1 0 0 0 0\n0 1 0 0 0\n0 0 1 0 0\n1 -1 0 0 0\n')
                win = 2+index/8 if task == "socialdoors" else 1
                loss = .5+index/16 if task == "socialdoors" else .5
                for cope, value in ((1, win), (2, loss), (4, win-loss)):
                    path = feat/f"stats/cope{cope}.nii.gz"
                    nib.save(nib.Nifti1Image(np.full(self.mask.shape, value, dtype=np.float32), self.mask.affine), path)
                row_tasks[task] = feat
            for cope in (1, 2, 4):
                self.pairs.append(dict(subject=subject, contrast=str(cope),
                    **{task+"_feat_dir":str(feat) for task,feat in row_tasks.items()},
                    **{task+"_cope":str(feat/f"stats/cope{cope}.nii.gz") for task,feat in row_tasks.items()}))
            differences[..., index] = 1+index/16
        (cohort/"selected_pairs.tsv").write_text(base.review.tsv(self.pairs))
        path = Path(self.plan["images"]["social_specific"])
        nib.save(nib.Nifti1Image(differences, self.mask.affine), path)
        self.plan["outputs"][path.name] = base.cohort.digest(path)
        base.write_json(self.args.baseline/"plan.json", self.plan)
        (self.args.baseline/"plan.sha256").write_text(base.cohort.digest(self.args.baseline/"plan.json"))
        self.root_patch = patch.object(components, "ROOT", self.data_root); self.root_patch.start()
        base.STOP = False; base.LEASE_FD = None

    def tearDown(self):
        self.root_patch.stop(); self.fixture.tearDown()

    def build(self):
        with patch.object(base, "check", return_value=self.plan), patch.object(components.outcome_audit, "audit",
                return_value=([], dict(n=97, runs=194, failures=0))):
            return components.build(self.args)

    def test_nine_columns_pm_only_contrasts_and_df88(self):
        names, x, _ = components.additive_design(self.plan, self.ids)
        self.assertEqual(names[-2:], ["pm25", "ecog"])
        self.assertEqual(x.shape, (97,9))
        self.assertNotIn("pm25xecog", names)
        files, jobs = components.designs(self.args.output, self.ids, names, x)
        self.assertEqual(len(jobs), 6)
        self.assertEqual({j["outcome"] for j in jobs}, set(components.OUTCOMES))
        import io
        contrasts = np.loadtxt(io.StringIO(files["design.con"].split("/Matrix",1)[1]))
        np.testing.assert_array_equal(contrasts[0], [0,0,0,0,0,0,0,1,0])
        np.testing.assert_array_equal(contrasts[1], -contrasts[0])
        self.assertTrue(all(j["residual_dof"]==88 and j["permutations"]==10000 for j in jobs))

    def test_component_pixels_and_exact_participant_order(self):
        arrays, _, lineage = components.component_arrays(self.pairs, self.ids, self.mask, self.plan["images"]["social_specific"])
        self.assertEqual(len(lineage), 97*2*3)
        np.testing.assert_array_equal(arrays["win_only"][0,0,0], 1+np.arange(97)/8)
        np.testing.assert_array_equal(arrays["loss_only"][0,0,0], np.arange(97)/16)
        with self.assertRaisesRegex(ValueError, "participant order"):
            components.component_arrays(self.pairs, list(reversed(self.ids)), self.mask, self.plan["images"]["social_specific"])

    def test_nuisance_contamination_and_component_substitution_refused(self):
        pair=self.pairs[0]; feat=Path(pair["socialdoors_feat_dir"])
        original=(feat/"design.con").read_text()
        (feat/"design.con").write_text(original.replace("1 0 0 0 0", "1 0 0 0 1"))
        with self.assertRaisesRegex(ValueError,"nuisance weights"):
            components.validate_contrasts(feat)
        (feat/"design.con").write_text(original)
        wrong=[dict(r) for r in self.pairs]
        wrong[0]["socialdoors_cope"]=wrong[1]["socialdoors_cope"]
        with self.assertRaisesRegex(ValueError,"not this participant"):
            components.component_arrays(wrong,self.ids,self.mask,self.plan["images"]["social_specific"])

    def test_missing_component_fails_without_dropping_participant(self):
        Path(self.pairs[0]["doors_cope"]).unlink()
        with self.assertRaises(FileNotFoundError):
            components.component_arrays(self.pairs,self.ids,self.mask,self.plan["images"]["social_specific"])

    def test_swapped_design_labels_refused(self):
        path=Path(next(j["design"] for j in self.plan["jobs"] if j["outcome"]=="social_specific" and j["model"]=="pm25xecog")).with_suffix(".tsv")
        lines=path.read_text().splitlines(); lines[1],lines[2]=lines[2],lines[1]
        path.write_text("\n".join(lines)+"\n")
        with self.assertRaisesRegex(ValueError,"participant order"):
            components.additive_design(self.plan,self.ids)

    def test_complete_resume_and_mutation_preserve_prior_results(self):
        before={str(p):(p.stat().st_mtime_ns,base.cohort.digest(p)) for p in self.args.baseline.rglob("*") if p.is_file()}
        plan=self.build()
        components.run(self.args)
        self.assertEqual(json.loads((self.args.output/"status.json").read_text())["status"],"complete")
        self.assertEqual(len((self.args.output/"maps.tsv").read_text().splitlines()),13)
        image=next((self.args.output/"jobs").rglob("randomise_tstat1.nii.gz")); stamp=image.stat().st_mtime_ns
        components.run(self.args)
        self.assertEqual(image.stat().st_mtime_ns,stamp)
        self.assertEqual(before,{str(p):(p.stat().st_mtime_ns,base.cohort.digest(p)) for p in self.args.baseline.rglob("*") if p.is_file()})
        Path(plan["jobs"][0]["contrast"]).write_text("changed")
        with self.assertRaisesRegex(ValueError,"contrast"):
            components.check(self.args)

    def test_shell_and_no_automatic_image_publication(self):
        path=Path(__file__).resolve().parents[1]/"code/launch_pm25_components.sh"
        subprocess.run(["bash","-n",str(path)],check=True)
        text=path.read_text()
        self.assertIn("umask 0000",text)
        self.assertIn("publish_run_logs.py",text)
        self.assertIn("nohup setsid",text)
        self.assertNotIn("git push",text)


if __name__ == "__main__":
    unittest.main()
