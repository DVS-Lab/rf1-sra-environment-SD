import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import nibabel as nib
import numpy as np
from PIL import Image

import publish_katie_review as publisher
import review_fevs_vs as review
import test_reward_extension as fixtures

base=review.base


class VSReview(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.Extension(methodName="test_numeric_designs_contrasts_and_conditional_main_effects")
        self.fixture.setUp();self.root=self.fixture.root;self.folder=self.fixture.output
        self.plan=self.fixture.write_plan();self.job,self.definition=review.select_job(self.plan)
        _,rows=base.cohort.read_table(review.ROOT/"data/derived/katie-cohort-v1/subjects.tsv")
        self.ids=[row["subject"] for row in rows]
        self.raw=review.common.plots.raw_terms(self.ids)
        names,self.x=review.followup.check_design(self.job,self.definition,self.ids,self.raw)
        shape=(32,40,32);self.affine=np.diag([4.,4.,4.,1.]);self.affine[:3,3]=[-64,-100,-64]
        grid=np.indices(shape);radius=((grid[0]-16)/13)**2+((grid[1]-21)/16)**2+((grid[2]-16)/14)**2
        self.anatomy=self.root/"phantom.nii.gz";mask=self.root/"vs-mask.nii.gz"
        nib.save(nib.Nifti1Image((np.exp(-radius)*800*(radius<1)).astype(np.float32),self.affine),self.anatomy)
        nib.save(nib.Nifti1Image((radius<1).astype(np.uint8),self.affine),mask)
        self.region=np.zeros(shape,dtype=bool);self.region[13:17,23:27,14:17]=True
        self.region[13,23,14:17]=False;self.region[13,24,14]=False
        rng=np.random.default_rng(44)
        self.y=2-3*self.x[:,names.index("fevs")]+self.x[:,names.index("pm25")]+.15*self.x[:,-1]+rng.normal(scale=.5,size=97)
        data=rng.normal(scale=.2,size=shape+(97,)).astype(np.float32);data[self.region,:]=self.y
        self.stack=self.root/"vs-domain-valence.nii.gz";nib.save(nib.Nifti1Image(data,self.affine),self.stack)
        # Deliberately incompatible signals/support make activation fallback detectable.
        wrong=self.root/"activation-not-ppi.nii.gz";wrong_mask=self.root/"activation-empty-mask.nii.gz"
        nib.save(nib.Nifti1Image(-data,self.affine),wrong)
        nib.save(nib.Nifti1Image(np.zeros(shape,dtype=np.uint8),self.affine),wrong_mask)
        self.plan["masks"]["connectivity"]=str(mask);self.plan["images"]["connectivity/social_specific"]=str(self.stack)
        self.plan["masks"]["activation"]=str(wrong_mask);self.plan["images"]["activation/social_specific"]=str(wrong)
        self.plan["sources"] += [base.fingerprint(path) for path in (mask,self.stack,wrong,wrong_mask)]
        base.write_json(self.folder/"plan.json",self.plan)
        self.digest=base.cohort.digest(self.folder/"plan.json");(self.folder/"plan.sha256").write_text(self.digest)
        self.destination=self.folder/"jobs"/review.KEY
        self.fixture.success(self.plan,self.job,self.destination,self.digest)
        self.prefix=self.destination/"attempts/attempt-0001/randomise";index=self.definition["index"]
        for suffix,values in ((f"_tstat{index}.nii.gz",np.where(self.region,4.8,0.)),
                              (f"_tstat{index-1}.nii.gz",np.where(self.region,-4.8,0.)),
                              (f"_clustere_corrp_tstat{index}.nii.gz",np.where(self.region,.97,0.))):
            nib.save(nib.Nifti1Image(values,self.affine),str(self.prefix)+suffix)
        self.receipt=self.destination/"success.json";self.refresh()
        self.args=SimpleNamespace(project=self.root,report=self.root/"work/vs-review/report",atlas_root=self.root/"missing-atlases")

    def tearDown(self):self.fixture.tearDown()

    def refresh(self):
        saved=json.loads(self.receipt.read_text())
        saved["outputs"]=review.common.extension.products(self.prefix,self.plan["masks"]["connectivity"],self.job["contrasts"])
        base.write_json(self.receipt,saved)

    def build(self):
        with patch.object(review.common.background,"select",return_value=dict(path=str(self.anatomy))):review.build(self.args)

    def test_connectivity_not_activation_n97_negative_main_effect_and_reuse(self):
        before={str(path):base.cohort.digest(path) for path in self.folder.rglob("*") if path.is_file()}
        self.build();report=self.args.report;result=json.loads((report/"summary.json").read_text())
        self.assertEqual((result["n"],result["family"],result["outcome"],result["term"]),(97,"connectivity","social_specific","fevs"))
        self.assertFalse(result["exclusions_changed"]);self.assertIn("NOT an interaction or win-only",result["context"])
        self.assertEqual(result["outcome_formula"],review.OUTCOME)
        self.assertEqual(result["clusters"][0]["voxels"],44)
        self.assertLess(result["clusters"][0]["peak_coefficient_t"],0)
        fit=result["region_fits"][0];self.assertEqual(fit["n"],97);self.assertLess(fit["estimate"],0)
        self.assertNotIn("ols_jn_roots",fit)
        _,details=base.cohort.read_table(report.parent/"participant-diagnostics/fevs-vs-cluster-1.tsv")
        self.assertEqual([row["subject"] for row in details],self.ids)
        np.testing.assert_allclose([float(row["region_estimate"]) for row in details],self.y,rtol=0,atol=2e-6)
        self.assertEqual(before,{str(path):base.cohort.digest(path) for path in self.folder.rglob("*") if path.is_file()})
        files=publisher.payload(report)
        self.assertEqual(sum(name.endswith(".png") for name in files),2)
        self.assertFalse(any("private" in name or "diagnostics" in name for name in files))
        for path in report.glob("*.png"):
            pixels=np.asarray(Image.open(path).convert("RGB"));self.assertGreater(pixels.std(),20)
            if path.name.endswith("-brain.png"):
                blue=(pixels[...,2].astype(float)-pixels[...,0]>40)&(pixels[...,2].astype(float)-pixels[...,1]>20)
                self.assertGreater(blue.sum(),30)
            if os.environ.get("KATIE_PREVIEW_DIR"):
                folder=Path(os.environ["KATIE_PREVIEW_DIR"]);folder.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(path,folder/("synthetic-vs-"+path.name))
        stamps={str(path):path.stat().st_mtime_ns for path in report.iterdir()};self.build()
        self.assertEqual(stamps,{str(path):path.stat().st_mtime_ns for path in report.iterdir()})
        self.stack.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError,"fingerprint failure"):review.verify(report)

    def test_wrong_family_outcome_or_interaction_is_not_substituted(self):
        for update in (dict(family="activation"),dict(outcome="connectivity/win_only"),dict(model="oafemxecog")):
            plan=dict(self.plan,jobs=[dict(self.job,**update)])
            with self.assertRaisesRegex(ValueError,"documented VS"):review.select_job(plan)
        contrasts=[dict(row,term="fevsxpm25") if row["term"]=="fevs" else row for row in self.job["contrasts"]]
        with self.assertRaisesRegex(ValueError,"main-effect contrast"):
            review.select_job(dict(self.plan,jobs=[dict(self.job,contrasts=contrasts)]))
        with self.assertRaisesRegex(ValueError,"subject order"):
            review.followup.check_design(self.job,self.definition,list(reversed(self.ids)),self.raw)

    def test_unfinished_and_wrong_native_mask_receipts_rejected(self):
        saved=json.loads(self.receipt.read_text());self.receipt.unlink()
        with self.assertRaisesRegex(ValueError,"unfinished"):self.build()
        saved["command"][saved["command"].index("-m")+1]=self.plan["masks"]["activation"]
        base.write_json(self.receipt,saved)
        with self.assertRaisesRegex(ValueError,"command/receipt differs"):self.build()
        self.assertFalse(self.args.report.exists())

    def test_null_target_does_not_invent_cluster_or_scatter(self):
        path=Path(str(self.prefix)+f"_clustere_corrp_tstat{self.definition['index']}.nii.gz")
        nib.save(nib.Nifti1Image(np.zeros(self.region.shape),self.affine),path);self.refresh()
        self.build();report=self.args.report;result=json.loads((report/"summary.json").read_text())
        self.assertEqual(result["clusters"],[]);self.assertEqual(result["region_fits"],[])
        self.assertEqual([path.name for path in report.glob("*.png")],["fevs-vs-no-cluster.png"])
        self.assertFalse((report.parent/"participant-diagnostics").exists())


class Launcher(unittest.TestCase):
    def test_detached_readonly_auto_publish_and_separate_lock(self):
        path=base.ROOT/"code/launch_fevs_vs_review.sh"
        subprocess.run(["bash","-n",str(path)],check=True);text=path.read_text()
        for required in ("umask 0000","nohup setsid","snapshot_reward_extension.py","git archive","publish_run_logs.py",
                         'ROOT="$PROJECT/work/fevs-vs-review-v1"',"--destination results/review/fevs-vs-v1"):
            self.assertIn(required,text)
        for forbidden in ("git pull","kill -","run_reward_extension.py run","randomise -","scp ","rsync"):
            self.assertNotIn(forbidden,text)


if __name__=="__main__":unittest.main()
