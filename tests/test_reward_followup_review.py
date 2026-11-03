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
import statsmodels.api as sm

import publish_katie_review as publisher
import review_reward_followup as review
import test_reward_extension as fixtures

base=review.base


class Followup(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.Extension(methodName="test_numeric_designs_contrasts_and_conditional_main_effects")
        self.fixture.setUp();self.root=self.fixture.root;self.folder=self.fixture.output
        self.plan=self.fixture.write_plan()
        _,roster=base.cohort.read_table(review.ROOT/"data/derived/katie-cohort-v1/subjects.tsv")
        self.ids=[row["subject"] for row in roster];self.raw=review.common.plots.raw_terms(self.ids)
        shape=(32,40,32);self.affine=np.diag([4.,4.,4.,1.]);self.affine[:3,3]=[-64,-100,-64]
        grid=np.indices(shape);radius=((grid[0]-16)/13)**2+((grid[1]-21)/16)**2+((grid[2]-16)/14)**2
        self.anatomy=self.root/"phantom.nii.gz";mask=self.root/"followup-mask.nii.gz"
        nib.save(nib.Nifti1Image((np.exp(-radius)*800*(radius<1)).astype(np.float32),self.affine),self.anatomy)
        nib.save(nib.Nifti1Image((radius<1).astype(np.uint8),self.affine),mask)
        self.plan["masks"]["activation"]=str(mask);self.plan["sources"].append(base.fingerprint(mask))
        rng=np.random.default_rng(21)
        stacks={outcome:rng.normal(scale=.2,size=shape+(97,)).astype(np.float32) for outcome in ("loss_only","win_only")}
        self.selected=[];self.regions=[]
        for index,target in enumerate(review.TARGETS):
            job=next(job for job in self.plan["jobs"] if job["key"]==f"activation/{target['outcome']}/{target['model']}/z-"+str(target["z"]).replace(".","p"))
            definition=next(row for row in job["contrasts"] if row["term"]==target["term"] and row["direction"]=="negative")
            x=review.common.audit.matrix(job["design"])
            fields,_=base.cohort.read_table(Path(job["design"]).with_suffix(".tsv"));names=fields[1:]
            region=np.zeros(shape,dtype=bool);region[12+index*3:15+index*3,23:27,14:17]=True
            self.regions.append(region)
            y=1.-3*x[:,names.index(target["term"])]+rng.normal(scale=.12,size=97)
            stacks[target["outcome"]][region,:]=y
            self.selected.append((target,job,definition))
        for outcome,data in stacks.items():
            path=self.root/(outcome+"-followup.nii.gz");nib.save(nib.Nifti1Image(data,self.affine),path)
            self.plan["images"]["activation/"+outcome]=str(path);self.plan["sources"].append(base.fingerprint(path))
        base.write_json(self.folder/"plan.json",self.plan)
        self.digest=base.cohort.digest(self.folder/"plan.json");(self.folder/"plan.sha256").write_text(self.digest)
        for (target,job,definition),region in zip(self.selected,self.regions):
            destination=self.folder/"jobs"/job["key"];self.fixture.success(self.plan,job,destination,self.digest)
            prefix=destination/"attempts/attempt-0001/randomise"
            negative=np.where(region,4.8,0.);corrected=np.where(region,.98,0.)
            for suffix,values in ((f"_tstat{definition['index']}.nii.gz",negative),
                                  (f"_tstat{definition['index']-1}.nii.gz",-negative),
                                  (f"_clustere_corrp_tstat{definition['index']}.nii.gz",corrected)):
                nib.save(nib.Nifti1Image(values,self.affine),str(prefix)+suffix)
            self.refresh_receipt(job)
        self.args=SimpleNamespace(project=self.root,report=self.root/"work/followup/report",atlas_root=self.root/"missing-atlases")

    def tearDown(self):self.fixture.tearDown()

    def refresh_receipt(self,job):
        receipt=self.folder/"jobs"/job["key"]/"success.json";saved=json.loads(receipt.read_text())
        saved["outputs"]=review.common.extension.products(Path(saved["attempt"])/"randomise",self.plan["masks"]["activation"],job["contrasts"])
        base.write_json(receipt,saved)

    def build(self):
        with patch.object(review.common.background,"select",return_value=dict(path=str(self.anatomy))):review.build(self.args)

    def test_three_negative_maps_jn_main_effects_row_order_and_reuse(self):
        original={str(p):base.cohort.digest(p) for p in self.folder.rglob("*") if p.is_file()}
        self.build();report=self.args.report;result=json.loads((report/"summary.json").read_text())
        self.assertEqual(result["n"],97);self.assertFalse(result["exclusions_changed"])
        self.assertEqual(len(result["clusters"]),3);self.assertEqual(len(result["region_fits"]),3)
        self.assertTrue(all(r["peak_coefficient_t"]<0 and r["direction"]=="negative" for r in result["clusters"]))
        self.assertTrue(all(r["n"]==97 and r["estimate"]<0 and not r["exclusions_made"] for r in result["region_fits"]))
        self.assertEqual(sum("ols_jn_regions" in r for r in result["region_fits"]),1)
        self.assertIn("mean OAFEM",(report/"README.md").read_text())
        self.assertEqual(original,{str(p):base.cohort.digest(p) for p in self.folder.rglob("*") if p.is_file()})
        files=publisher.payload(report)
        self.assertEqual(sum(name.endswith(".png") for name in files),6)
        self.assertFalse(any("private" in name or "diagnostics" in name for name in files))
        for path in (report.parent/"participant-diagnostics").glob("*.tsv"):
            self.assertEqual(len(path.read_text().splitlines()),98)
        target,job,_=self.selected[0];x=review.common.audit.matrix(job["design"])
        fields,_=base.cohort.read_table(Path(job["design"]).with_suffix(".tsv"));names=fields[1:]
        _,rows=base.cohort.read_table(report.parent/"participant-diagnostics/fevs-pm25-loss-cluster-1.tsv")
        self.assertEqual([row["subject"] for row in rows],self.ids)
        fitted=sm.OLS([float(row["region_estimate"]) for row in rows],x,hasconst=True).fit()
        _,curves=base.cohort.read_table(report/"fevs-pm25-loss-cluster-1-jn-curves.tsv")
        self.assertEqual(len(curves),802)
        for covariance,estimator in (("OLS",fitted),("HC3",fitted.get_robustcov_results(cov_type="HC3",use_t=True))):
            selected=[row for row in curves if row["covariance"]==covariance]
            for index in (0,200,400):
                row=selected[index];contrast=np.zeros(x.shape[1]);contrast[names.index("fevs")]=1
                contrast[names.index("fevsxpm25")]=float(row["pm25"])-self.raw["pm25"].mean()
                tested=estimator.t_test(contrast)
                np.testing.assert_allclose([float(row["ci_lower"]),float(row["ci_upper"])],tested.conf_int()[0],rtol=0,atol=1e-10)
                self.assertAlmostEqual(float(row["conditional_fevs_slope"]),float(np.asarray(tested.effect).item()))
                self.assertGreaterEqual(float(row["pm25"]),self.raw["pm25"].min()-1e-12)
                self.assertLessEqual(float(row["pm25"]),self.raw["pm25"].max()+1e-12)
        for path in report.glob("*.png"):
            pixels=np.asarray(Image.open(path).convert("RGB"));self.assertGreater(pixels.std(),20)
            if path.name.endswith("-brain.png"):
                blue=(pixels[...,2].astype(float)-pixels[...,0]>40)&(pixels[...,2].astype(float)-pixels[...,1]>20)
                self.assertGreater(blue.sum(),30)
            if os.environ.get("KATIE_PREVIEW_DIR"):
                folder=Path(os.environ["KATIE_PREVIEW_DIR"]);folder.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(path,folder/("synthetic-followup-"+path.name))
        before={str(p):p.stat().st_mtime_ns for p in report.iterdir()};self.build()
        self.assertEqual(before,{str(p):p.stat().st_mtime_ns for p in report.iterdir()})
        (report/"clusters.tsv").write_text("modified")
        with self.assertRaisesRegex(ValueError,"artifact differs"):review.verify(report)

    def test_unfinished_or_smoke_target_is_rejected_without_figures(self):
        _,job,_=self.selected[0];receipt=self.folder/"jobs"/job["key"]/"success.json"
        saved=json.loads(receipt.read_text());receipt.unlink()
        with self.assertRaisesRegex(ValueError,"unfinished"):self.build()
        saved["smoke"]=True;base.write_json(receipt,saved)
        with self.assertRaisesRegex(ValueError,"command/receipt differs"):self.build()
        self.assertFalse(self.args.report.exists())

    def test_design_row_order_axes_products_cutoffs_and_contrast_sign(self):
        _,job,definition=self.selected[0]
        with self.assertRaisesRegex(ValueError,"subject order"):
            review.check_design(job,definition,list(reversed(self.ids)),self.raw)
        raw=dict(self.raw,pm25=self.raw["pm25"]+1)
        # Centering is invariant to a uniform offset; corrupt just one raw observation.
        raw["pm25"]=raw["pm25"].copy();raw["pm25"][0]+=1
        with self.assertRaisesRegex(ValueError,"Raw predictor axes"):
            review.check_design(job,definition,self.ids,raw)
        with self.assertRaisesRegex(ValueError,"Z-to-t"):
            review.check_design(dict(job,t_cutoff=2.),definition,self.ids,self.raw)
        with self.assertRaisesRegex(ValueError,"negative coefficient"):
            review.check_design(job,dict(definition,index=definition["index"]-1),self.ids,self.raw)
        matrix=review.common.audit.matrix
        def invalid_product(path):
            values=matrix(path)
            if Path(path)==Path(job["design"]):values[0,-1]+=.1
            return values
        with patch.object(review.common.audit,"matrix",side_effect=invalid_product),self.assertRaisesRegex(ValueError,"design/subject order"):
            review.check_design(job,definition,self.ids,self.raw)

    def test_disagreeing_native_directional_maps_rejected(self):
        _,job,definition=self.selected[0]
        prefix=self.folder/"jobs"/job["key"]/"attempts/attempt-0001/randomise"
        path=Path(str(prefix)+f"_tstat{definition['index']-1}.nii.gz")
        image=nib.load(path);data=image.get_fdata();data[self.regions[0]]+=1
        nib.save(nib.Nifti1Image(data,image.affine),path);self.refresh_receipt(job)
        with self.assertRaisesRegex(ValueError,"coefficient maps disagree"):self.build()
        self.assertFalse(list(self.args.report.glob("*.png")))

    def test_launcher_is_detached_readonly_and_auto_publishes(self):
        path=base.ROOT/"code/launch_reward_followup_review.sh"
        subprocess.run(["bash","-n",str(path)],check=True);text=path.read_text()
        for required in ("umask 0000","nohup setsid","snapshot_reward_extension.py","git archive","publish_run_logs.py",
                         "--destination results/review/reward-followup-v1"):
            self.assertIn(required,text)
        for forbidden in ("git pull","kill -","run_reward_extension.py run","randomise -","scp ","rsync"):
            self.assertNotIn(forbidden,text)


if __name__=="__main__":unittest.main()
