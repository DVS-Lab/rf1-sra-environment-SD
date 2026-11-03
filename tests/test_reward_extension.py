import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import nibabel as nib
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"code"))
import run_reward_extension as extension
import test_katie_review as fixtures

base=extension.base


class Extension(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.CompleteAudit(methodName="test_all_152_jobs_336_maps_and_reject_corrupted_native_command")
        self.fixture.setUp()
        self.root=self.fixture.root
        self.ids,self.records,self.plans,self.units=extension.audit.inventory(self.root)
        self.output=self.root/"derivatives/fsl/randomise/katie-reward-extension-v1"
        self.args=SimpleNamespace(project=self.root,upstream=self.root/"upstream",output=self.output,jobs=60)
        self.files,self.jobs,self.coverage=extension.catalog(self.output,self.ids,self.units,self.plans["environment_activation"])
        base.STOP=False;base.LEASE_FD=None

    def tearDown(self):
        self.fixture.tearDown();base.STOP=False;base.LEASE_FD=None

    def write_plan(self):
        self.output.mkdir(parents=True)
        for name,text in self.files.items():
            path=self.output/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
        (self.output/"subjects.tsv").write_text(base.review.tsv([dict(subject=s) for s in self.ids]))
        masks={f:self.plans["group_activation" if f=="activation" else "environment_connectivity"]["mask"] for f in extension.FAMILIES}
        images={}
        for family in extension.FAMILIES:
            p=self.plans["group_activation" if family=="activation" else "environment_connectivity"]
            images.update({family+"/"+o:p["images"][o if o in extension.OLD_OUTCOMES else "social_specific"]
                           for o in (*extension.OLD_OUTCOMES,*extension.NEW_OUTCOMES)})
        plan=dict(n=97,jobs=self.jobs,coverage=self.coverage,images=images,masks=masks,
            randomise=self.plans["environment_activation"]["randomise"],sources=list(self.records.values()),
            code_sha256=base.cohort.digest(Path(extension.__file__)),project=str(self.root),
            outputs={str(p.relative_to(self.output)):base.cohort.digest(p) for p in self.output.rglob("*") if p.is_file()})
        base.write_json(self.output/"plan.json",plan)
        (self.output/"plan.sha256").write_text(base.cohort.digest(self.output/"plan.json"))
        return plan

    def success(self,plan,job,folder,digest):
        destination=folder/"attempts/attempt-0001";destination.mkdir(parents=True)
        prefix=destination/"randomise";mask=plan.get("mask") or plan["masks"][job["family"]]
        image=nib.load(mask)
        definitions=job.get("contrasts",[dict(index=1),dict(index=2)])
        for definition in definitions:
            for suffix in (f"_tstat{definition['index']}.nii.gz",f"_clustere_corrp_tstat{definition['index']}.nii.gz"):
                values=np.full(image.shape,.9 if "corrp" in suffix else 4.)
                nib.save(nib.Nifti1Image(values,image.affine),str(prefix)+suffix)
        outputs=extension.products(prefix,mask,definitions)
        base.write_json(folder/"success.json",dict(job=job,smoke=False,plan_sha256=digest,attempt=str(destination),
            command=base.command(dict(plan,mask=mask),job,prefix),outputs=outputs))

    def additive(self,plan):
        folder=extension.additive_args(self.args).output;folder.mkdir(parents=True)
        names,x,_=extension.components.additive_design(self.plans["environment_activation"],self.ids)
        files,jobs=extension.components.designs(folder,self.ids,names,x)
        for name,text in files.items():(folder/name).write_text(text)
        additive=dict(n=97,jobs=jobs,mask=plan["masks"]["activation"],randomise=plan["randomise"],
            images={o:plan["images"]["activation/"+o] for o in (*extension.NEW_OUTCOMES,"social_specific")})
        base.write_json(folder/"plan.json",additive)
        digest=base.cohort.digest(folder/"plan.json")
        for job in jobs:self.success(additive,job,folder/"jobs"/job["key"],digest)
        return additive

    def test_full_catalog_220_jobs_1328_tests_and_no_old_focal_retests(self):
        self.assertEqual(len(self.jobs),220);self.assertEqual(len(self.coverage),1328)
        self.assertEqual(sum(len(j["contrasts"]) for j in self.jobs),996)
        self.assertEqual(sum(r["source"]["origin"]=="existing" for r in self.coverage),332)
        new=[j for j in self.jobs if j["outcome"].split("/")[-1] in extension.NEW_OUTCOMES and j["model"] in extension.CORE_MODELS]
        old=[j for j in self.jobs if j["outcome"].split("/")[-1] in extension.OLD_OUTCOMES and j["model"] in extension.CORE_MODELS]
        self.assertEqual(len(new),128);self.assertEqual(len(old),80)
        for job in old:
            self.assertEqual(len(job["contrasts"]),4)
            self.assertTrue(all(r["term"]!=job["model"] for r in job["contrasts"]))
        for job in new:
            terms=[r["term"] for r in job["contrasts"]][::2]
            expected=[job["model"]] if "x" not in job["model"] else [*job["model"].split("x"),job["model"]]
            self.assertEqual(terms,expected)

    def test_numeric_designs_contrasts_and_conditional_main_effects(self):
        plan=self.write_plan()
        extension.check(self.args)
        for job in self.jobs:
            names,rows=base.cohort.read_table(Path(job["design"]).with_suffix(".tsv"))
            self.assertEqual([r["subject"] for r in rows],self.ids)
            c=extension.audit.matrix(job["contrast"])
            for row,definition in zip(c,job["contrasts"]):
                self.assertEqual(np.flatnonzero(row).tolist(),[names[1:].index(definition["term"])])
            self.assertEqual(job["residual_dof"],97-extension.audit.matrix(job["design"]).shape[1])
        path=Path(plan["jobs"][0]["contrast"]);path.write_text("corrupt")
        with self.assertRaisesRegex(ValueError,"artifact changed"):extension.check(self.args)

    def test_cross_family_covariate_mismatch_is_rejected(self):
        units=[dict(u,job=dict(u["job"])) for u in self.units]
        selected=[u for u in units if u["family"]=="connectivity" and u["job"]["model"]=="adi"
                  and u["job"]["outcome"].split("/")[-1]=="social_specific"]
        x=extension.audit.matrix(selected[0]["job"]["design"]);x[0,1]+=.1
        path=self.root/"wrong-connectivity-design.mat";path.write_text(base.vest_matrix(x))
        for unit in selected:unit["job"]["design"]=str(path)
        with self.assertRaisesRegex(ValueError,"across image families"):
            extension.catalog(self.output,self.ids,units,self.plans["environment_activation"])

    def test_ppi_components_reject_activation_or_seed_main_effect_weights(self):
        feat=self.root/"component-ppi";feat.mkdir()
        rng=np.random.default_rng(9);x=rng.normal(size=(97,9))
        (feat/"design.mat").write_text(base.vest_matrix(x))
        (feat/"design.fsf").write_text('set feat_files(1) "/synthetic/bold.nii.gz"\nset confoundev_files(1) "/synthetic/confounds.tsv"\n'
            'set fmri(conname_real.1) "win"\nset fmri(conname_real.2) "loss"\nset fmri(conname_real.4) "win-loss"\n')
        c=np.zeros((5,9));c[0,5]=1;c[1,6]=1;c[3,5:7]=[1,-1]
        (feat/"design.con").write_text(base.vest_matrix(c))
        extension.validate_ppi_components(feat)
        c[0,5]=0;c[0,0]=1;(feat/"design.con").write_text(base.vest_matrix(c))
        with self.assertRaisesRegex(ValueError,"task x VS"):extension.validate_ppi_components(feat)
        c[0,0]=0;c[0,4]=1;(feat/"design.con").write_text(base.vest_matrix(c))
        with self.assertRaisesRegex(ValueError,"task x VS"):extension.validate_ppi_components(feat)

    def test_ppi_component_pixels_order_and_identity(self):
        plan=self.plans["environment_connectivity"];reference=nib.load(plan["mask"])
        expected=np.zeros(reference.shape+(97,),dtype=np.float32)
        for index,subject in enumerate(self.ids):
            for task in ("socialdoors","doors"):
                feat=self.root/"ppi-components"/subject/task;(feat/"stats").mkdir(parents=True)
                a=2+index/8 if task=="socialdoors" else 1
                b=.5+index/16 if task=="socialdoors" else .5
                for cope,value in ((1,a),(2,b),(4,a-b)):
                    nib.save(nib.Nifti1Image(np.full(reference.shape,value,dtype=np.float32),reference.affine),feat/f"stats/cope{cope}.nii.gz")
                path=self.root/f"derivatives/fsl/randomise/katie-remaining-v1/ppi-l1/sub-{subject}_ses-01_task-{task}_run-1/success.json"
                base.write_json(path,dict(job=dict(subject=subject,task=task),sources=[],outputs=[],feat=str(feat)))
            expected[...,index]=1+index/16
        stack=self.root/"ppi-components-difference.nii.gz"
        nib.save(nib.Nifti1Image(expected,reference.affine),stack)
        plan=dict(plan,images=dict(plan["images"],social_specific=str(stack)))
        with patch.object(extension.remaining,"verify_ppi",return_value=[]),patch.object(extension,"validate_ppi_components"):
            arrays,lineage=extension.ppi_arrays(self.root,self.ids,plan,{})
            np.testing.assert_array_equal(arrays["win_only"][0,0,0],1+np.arange(97)/8)
            np.testing.assert_array_equal(arrays["loss_only"][0,0,0],np.arange(97)/16)
            self.assertEqual(len(lineage),582)
            with self.assertRaisesRegex(ValueError,"image order"):
                extension.ppi_arrays(self.root,list(reversed(self.ids)),plan,{})

    def test_six_contrast_execution_resume_and_missing_sixth_product(self):
        plan=self.write_plan();job=next(j for j in self.jobs if len(j["contrasts"])==6)
        fake=Path(plan["randomise"]);fake.write_text(fake.read_text().replace("range(1,5)","range(1,7)"))
        folder=self.output/"jobs"/job["key"];digest=base.cohort.digest(self.output/"plan.json")
        self.assertEqual(extension.execute(plan,job,folder,digest),"COMPLETED")
        image=next(folder.rglob("randomise_tstat6.nii.gz"));stamp=image.stat().st_mtime_ns
        self.assertEqual(extension.execute(plan,job,folder,digest),"REUSED")
        self.assertEqual(image.stat().st_mtime_ns,stamp)
        image.unlink()
        with self.assertRaises(Exception):extension.execute(plan,job,folder,digest)
        self.assertFalse(image.exists())

    def test_full_final_coverage_reuses_original_maps_without_changes(self):
        before={r["path"]:base.cohort.digest(Path(r["path"])) for r in self.records.values()}
        plan=self.write_plan();digest=base.cohort.digest(self.output/"plan.json")
        for job in self.jobs:self.success(plan,job,self.output/"jobs"/job["key"],digest)
        additive=self.additive(plan)
        with patch.object(extension.components,"check",return_value=additive):
            extension.final_results(self.args,plan)
        self.assertEqual(len((self.output/"maps.tsv").read_text().splitlines()),1329)
        self.assertEqual(json.loads((self.output/"validation.json").read_text())["new_directional_tests"],996)
        self.assertEqual(before,{p:base.cohort.digest(Path(p)) for p in before})
        image=next((self.output/"jobs").rglob("randomise_tstat1.nii.gz"));image.write_bytes(b"corrupt")
        with patch.object(extension.components,"check",return_value=additive),self.assertRaises(Exception):
            extension.final_results(self.args,plan)

    def test_scheduler_60_worker_limit_and_additive_slot_reservation(self):
        plan=self.write_plan();active=0;peak=0;reserved_peak=0;lock=threading.Lock()
        class Child:
            returncode=0
            active=True
            calls=0
            def poll(self):
                self.calls+=1
                if self.calls>3:self.active=False
                return None if self.active else 0
        child=Child()
        def job(*args,**kwargs):
            nonlocal active,peak,reserved_peak
            if kwargs or (len(args)>4 and args[4]):return "REUSED"
            with lock:
                active+=1;peak=max(peak,active)
                if child.active:reserved_peak=max(reserved_peak,active)
            time.sleep(.005)
            with lock:active-=1
            return "COMPLETED"
        with patch.object(extension.subprocess,"Popen",return_value=child),patch.object(extension,"build",return_value=plan), \
                patch.object(extension,"execute",side_effect=job),patch.object(extension,"final_results") as final:
            extension.run(self.args)
        self.assertLessEqual(peak,60);self.assertGreater(peak,1);final.assert_called_once()
        self.assertLessEqual(reserved_peak,54)
        self.assertEqual(json.loads((self.output/"status.json").read_text())["status"],"complete")

    def test_shell_preserves_working_checkout_and_umask(self):
        path=Path(extension.__file__).with_name("launch_reward_extension.sh")
        subprocess.run(["bash","-n",str(path)],check=True)
        text=path.read_text()
        self.assertIn("umask 0000",text);self.assertIn("publish_run_logs.py",text)
        self.assertIn("nohup setsid",text);self.assertIn("JOBS=60",text)
        self.assertNotIn("git pull",text);self.assertNotIn("git push",text)

    def test_additive_helper_waits_without_signalling_old_workers(self):
        calls=[BlockingIOError(),None]
        def acquire(*args):
            result=calls.pop(0)
            if result is not None:raise result
        with patch.object(extension.fcntl,"flock",side_effect=acquire),patch.object(extension.time,"sleep"), \
                patch.object(extension.components,"run") as run,patch.object(extension.os,"killpg") as kill:
            extension.ensure_additive(self.args)
        run.assert_called_once();kill.assert_not_called()
        self.assertEqual(run.call_args.args[0].jobs,6)
        base.STOP=True
        with patch.object(extension.components,"run") as run,self.assertRaises(InterruptedError):
            extension.ensure_additive(self.args)
        run.assert_not_called()

    def test_small_worker_budget_is_also_applied_to_additive_helper(self):
        self.args.jobs=1
        self.assertEqual(extension.additive_args(self.args).jobs,1)
        self.args.jobs=4
        self.assertEqual(extension.additive_args(self.args).jobs,4)

    def test_failed_validation_does_not_leave_running_status(self):
        plan=self.write_plan()
        class Child:
            returncode=0
            def poll(self):return 0
        with patch.object(extension.subprocess,"Popen",return_value=Child()),patch.object(extension,"build",return_value=plan), \
                patch.object(extension,"execute",return_value="REUSED"), \
                patch.object(extension,"final_results",side_effect=ValueError("frozen source changed")):
            with self.assertRaisesRegex(ValueError,"frozen source changed"):extension.run(self.args)
        status=json.loads((self.output/"status.json").read_text())
        self.assertEqual(status["status"],"failed");self.assertFalse(status["validated"])
        self.assertEqual(len(status["outcomes"]),220)


if __name__=="__main__":unittest.main()
