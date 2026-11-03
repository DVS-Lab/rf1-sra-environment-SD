import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import nibabel as nib
import numpy as np
try:
    import statsmodels.api as sm
    from PIL import Image
    import nilearn
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("Optional review tests require code/requirements-review.txt") from exc

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"code"))
import audit_katie_results as audit
import plot_katie_results as plots
import publish_katie_review as publisher
import run_financial_models as financial
import run_financial_moderation as moderation
import test_run_financial_models as fixtures

base=audit.base


class ReviewStatistics(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        rng=np.random.default_rng(76); p=rng.normal(size=97);m=rng.uniform(-1.8,1.8,97)
        p-=p.mean();m-=m.mean()
        nuisance=rng.normal(size=(97,6));nuisance-=nuisance.mean(axis=0)
        self.x=np.column_stack([np.ones(97),nuisance,p,m,p*m])
        self.y=.4+.25*p+.1*m+1.1*p*m+rng.normal(scale=.6,size=97)
        self.fit=sm.OLS(self.y,self.x).fit()

    def tearDown(self): self.temp.cleanup()

    def task(self,interaction=True):
        names=["ones","fd","tsnr","e11","xa30","gender","age","fevs","ecog","fevsxecog"]
        x=self.x if interaction else self.x[:,:8]
        if not interaction:names=names[:8]
        return dict(id="synthetic",title="Synthetic rendering check; not study results",selection="Synthetic ROI; all 97 retained",
            path=str(self.root/"association.png"),details=str(self.root/"details/influence.tsv"),names=names,x=x.tolist(),y=self.y.tolist(),
            raw=dict(fevs=(self.x[:,7]+5).tolist(),ecog=(self.x[:,8]+2).tolist()),
            term="fevsxecog" if interaction else "fevs",interaction=interaction,ids=[str(i) for i in range(97)])

    def test_jn_curve_and_boundaries_agree_with_statsmodels_contrasts(self):
        for fit in (self.fit,self.fit.get_robustcov_results(cov_type="HC3",use_t=True)):
            result=plots.jn_curve(fit,7,9,self.x[:,8],2.)
            for index in (0,99,200,400):
                contrast=np.zeros(10);contrast[7]=1;contrast[9]=result["raw_grid"][index]-2
                np.testing.assert_allclose(result["ci"][index],fit.t_test(contrast).conf_int()[0],rtol=0,atol=1e-12)
            self.assertTrue(result["roots_raw"])
            for root in result["roots_raw"]:
                contrast=np.zeros(10);contrast[7]=1;contrast[9]=root-2
                self.assertLess(np.abs(fit.t_test(contrast).conf_int()[0]).min(),1e-8)
                self.assertGreaterEqual(root,self.x[:,8].min()+2);self.assertLessEqual(root,self.x[:,8].max()+2)

    def test_association_figures_nonblank_and_resumable_no_row_drops(self):
        task=self.task();result=plots.render_task(plots.roi_figure,task)
        self.assertEqual(result["n"],97);self.assertFalse(result["exclusions_made"])
        stamp=Path(task["path"]).stat().st_mtime_ns
        self.assertEqual(plots.render_task(plots.roi_figure,task),result)
        self.assertEqual(Path(task["path"]).stat().st_mtime_ns,stamp)
        task=self.task(False);task["path"]=str(self.root/"scatter.png")
        result=plots.roi_figure(task);self.assertEqual(result["term"],"fevs")
        self.assertEqual(len(Path(task["details"]).read_text().splitlines()),98)

    def test_axis_misalignment_and_unsafe_publication_refused(self):
        task=self.task();task["raw"]["fevs"][0]+=1
        with self.assertRaisesRegex(ValueError,"axes do not match"):plots.roi_figure(task)
        report=self.root/"report";report.mkdir()
        (report/"review_manifest.json").write_text(json.dumps(dict(outputs={"../secret.tsv":"x"})))
        with self.assertRaisesRegex(ValueError,"Unsafe"):publisher.payload(report)
        (report/"review_manifest.json").write_text(json.dumps(dict(outputs={"brain.nii.gz":"x"})))
        with self.assertRaisesRegex(ValueError,"Only aggregate"):publisher.payload(report)

    def test_real_png_brain_montage_with_null_panel(self):
        shape=(64,64,64);affine=np.diag([3.,3.,3.,1.]);affine[:3,3]=[-96,-126,-72]
        grid=np.indices(shape);radius=((grid[0]-32)/23)**2+((grid[1]-35)/25)**2+((grid[2]-29)/27)**2
        background=np.exp(-radius)*800*(radius<1)
        support=radius<1
        statistic=np.zeros(shape);statistic[30:36,30:37,25:31]=5
        for name,data in (("background",background),("mask",support.astype(float)),("positive",statistic),("negative",-statistic)):
            nib.save(nib.Nifti1Image(data,affine),self.root/(name+".nii.gz"))
        rows=[]
        for z in (2.6,3.1):
            for direction in ("positive","negative"):
                corrected=np.where(statistic>0,.99,0) if z==2.6 and direction=="positive" else np.zeros(shape)
                path=self.root/f"corr-{z}-{direction}.nii.gz";nib.save(nib.Nifti1Image(corrected,affine),path)
                rows.append(dict(direction=direction,z=z,tstat=str(self.root/(direction+".nii.gz")),corrp=str(path),mask=str(self.root/"mask.nii.gz")))
        task=dict(id="brain",title="SYNTHETIC phantom: overlay / null-panel rendering check",rows=rows,background=str(self.root/"background.nii.gz"),
            path=str(self.root/"brain.png"),relative="brain.png")
        result=plots.brain_figure(task);self.assertEqual(result["id"],"brain")
        pixels=np.asarray(Image.open(self.root/"brain.png").convert("RGB"),dtype=float)
        area=pixels[100:650,:int(pixels.shape[1]*.9)]
        self.assertGreater(int(((area[...,0]-area[...,2]>45)&(area[...,0]-area[...,1]>40)).sum()),5)
        if os.environ.get("KATIE_PREVIEW_DIR"):
            target=Path(os.environ["KATIE_PREVIEW_DIR"]);target.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(self.root/"brain.png",target/"synthetic-brain.png")
            self.task_preview(target)

    def task_preview(self,target):
        task=self.task();task["path"]=str(target/"synthetic-JN.png");plots.roi_figure(task)
        task=self.task(False);task["path"]=str(target/"synthetic-scatter.png");plots.roi_figure(task)


class CompleteAudit(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.FinancialRunner(methodName="test_connectivity_order_mismatch_is_rejected");self.fixture.setUp()
        self.root=self.fixture.root;self.parent=self.root/"derivatives/fsl/randomise";self.parent.mkdir(parents=True)
        self.baseline=self.parent/"katie-v1";shutil.copytree(self.fixture.baseline,self.baseline)
        self.original=self.fixture.plan
        # Canonical tiny fixtures retain the real N=97 matrices and frozen roster.
        _,pairs=base.cohort.read_table(base.ROOT/"data/derived/katie-cohort-v1/selected_pairs.tsv")
        group_root=self.parent/"katie-remaining-v1/activation"
        files,jobs=audit.remaining.group_specs(self.original,pairs,group_root)
        images=dict(self.original["images"],socialdoors=self.original["images"]["average"],doors=self.original["images"]["average"])
        self.write_plan(group_root,dict(self.original,jobs=jobs,images=images),files)
        connectivity=self.parent/"katie-remaining-v1/connectivity"
        self.write_plan(connectivity,self.original,{"subjects.tsv":(self.fixture.baseline/"subjects.tsv").read_text()})
        conditional=self.parent/"katie-main-effects-v1"
        files,jobs=audit.conditional.specifications(self.original,conditional)
        self.write_plan(conditional,dict(self.original,jobs=jobs),files)
        args=self.fixture.args;args.baseline=self.baseline;args.connectivity=connectivity;args.output=self.parent/"katie-financial-v1"
        with patch.object(base,"check",return_value=self.original):
            financial.build(args);args.output=self.parent/"katie-financial-moderation-v1";moderation.build(args)
        for _,(relative,_,contrasts) in audit.BATCHES.items():
            folder=self.parent/relative;plan=json.loads((folder/"plan.json").read_text());digest=base.cohort.digest(folder/"plan.json")
            for job in plan["jobs"]:
                unit=folder/"jobs"/job["key"];attempt=unit/"attempts/attempt-0001";attempt.mkdir(parents=True,exist_ok=True)
                prefix=attempt/"randomise";mask=plan.get("mask") or plan["masks"][job["family"]]
                for index in range(1,contrasts+1):
                    for suffix in (f"_tstat{index}.nii.gz",f"_clustere_corrp_tstat{index}.nii.gz"):
                        reference=nib.load(mask);nib.save(nib.Nifti1Image(np.zeros(reference.shape),reference.affine),str(prefix)+suffix)
                products=audit.conditional.products(prefix,mask) if contrasts==4 else base.output_images(prefix,mask)
                base.write_json(unit/"success.json",dict(job=job,plan_sha256=digest,smoke=False,attempt=str(attempt),outputs=products,
                    command=base.command(dict(plan,mask=mask),job,prefix)))
            if relative.endswith("activation"):
                attempt=folder/"smoke/attempts/attempt-0001";attempt.mkdir(parents=True)
                (attempt/"console.log").write_text("Native sign-flipping confirmed")
                smoke_job=next(j for j in plan["jobs"] if j["outcome"]=="average")
                base.write_json(folder/"smoke/success.json",dict(smoke=True,attempt=str(attempt),job=smoke_job,plan_sha256=digest,
                    command=base.command(plan,smoke_job,attempt/"randomise",permutations=2)))

    def write_plan(self,folder,plan,files):
        folder.mkdir(parents=True,exist_ok=True)
        for name,text in files.items():
            path=folder/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
        plan=dict(plan,outputs={name:base.cohort.digest(folder/name) for name in files})
        base.write_json(folder/"plan.json",plan);(folder/"plan.sha256").write_text(base.cohort.digest(folder/"plan.json"))

    def tearDown(self): self.fixture.tearDown()

    def test_all_152_jobs_336_maps_and_reject_corrupted_native_command(self):
        maps,clusters,info=audit.audit(self.root,self.root/"review",4,source_arithmetic=False)
        self.assertEqual((len(maps),len(clusters),info["jobs"]),(336,0,152))
        ids,records,plans,units=audit.inventory(self.root)
        self.assertEqual(len(ids),97);self.assertEqual(len(units),152)
        receipt=Path(units[0]["receipt"]);saved=json.loads(receipt.read_text());saved["command"][saved["command"].index("-n")+1]="999"
        receipt.write_text(json.dumps(saved))
        with self.assertRaisesRegex(ValueError,"native command differs"):audit.inventory(self.root)

    def test_matrix_row_order_and_actual_contrast_validation(self):
        unit=self.original["jobs"][0];_,roster=base.cohort.read_table(base.ROOT/"data/derived/katie-cohort-v1/subjects.tsv")
        ids=[r["subject"] for r in roster]
        audit.design(unit,ids)
        with self.assertRaisesRegex(ValueError,"Row order"):audit.design(unit,list(reversed(ids)))
        original=Path(unit["contrast"]).read_text();Path(unit["contrast"]).write_text(original.replace("/Matrix\n","/Matrix\n0 ",1))
        with self.assertRaises(ValueError):audit.design(unit,ids)

    def test_activation_ppi_source_order_and_pair_arithmetic_reject_reversal(self):
        _,roster=base.cohort.read_table(base.ROOT/"data/derived/katie-cohort-v1/subjects.tsv")
        ids=[r["subject"] for r in roster];mask=self.original["mask"];reference=nib.load(mask)
        folder=self.root/"order";folder.mkdir();pairs=[];a=[];b=[];c=[];d=[]
        upstream=folder/"upstream"
        for index,sub in enumerate(ids):
            pair=dict(subject=sub,contrast="4")
            for task,activation,ppi in (("socialdoors",index+2.,index*.2+1.),("doors",index*.5+1.,index*.3+.5)):
                cope=folder/f"{sub}-{task}.nii.gz";nib.save(nib.Nifti1Image(np.full(reference.shape,activation),reference.affine),cope)
                pair[task+"_cope"]=str(cope);pair[task+"_feat_dir"]=str(folder/f"feat-{sub}-{task}")
                feat=folder/f"ppi-{sub}-{task}";(feat/"stats").mkdir(parents=True)
                nib.save(nib.Nifti1Image(np.full(reference.shape,ppi),reference.affine),feat/"stats/cope4.nii.gz")
                receipt=self.parent/f"katie-remaining-v1/ppi-l1/sub-{sub}_ses-01_task-{task}_run-1/success.json"
                base.write_json(receipt,dict(job=dict(subject=sub,task=task),feat=str(feat)))
                event=upstream/f"bids/sub-{sub}/ses-01/func/sub-{sub}_ses-01_task-{task}_run-1_events.tsv"
                event.parent.mkdir(parents=True,exist_ok=True);event.write_text("onset\tduration\ttrial_type\n")
            pairs.append(pair);a.append(index+2.);b.append(index*.5+1.);c.append(index*.2+1.);d.append(index*.3+.5)
        def stack(name,values):
            path=folder/(name+".nii.gz");data=np.broadcast_to(np.asarray(values,dtype=np.float32),reference.shape+(97,)).copy()
            nib.save(nib.Nifti1Image(data,reference.affine),path);return str(path)
        a,b,c,d=map(np.asarray,(a,b,c,d))
        plans=dict(group_activation=dict(mask=mask,images=dict(socialdoors=stack("social",a),doors=stack("doors",b),
                    average=stack("average",(a+b)/2),social_specific=stack("difference",a-b))),
            environment_connectivity=dict(mask=mask,images=dict(average=stack("ppi-average",(c+d)/2),social_specific=stack("ppi-difference",c-d))),
            environment_activation=dict(upstream=str(upstream)))
        original=base.cohort.read_table
        def table(path):
            return (list(pairs[0]),pairs) if path.name=="selected_pairs.tsv" else original(path)
        with patch.object(base.cohort,"read_table",side_effect=table), \
                patch.object(audit.remaining.outcome,"inspect_run",return_value=(dict(status="passed"),[])), \
                patch.object(audit.remaining,"verify_ppi",return_value=[]):
            timing,_=audit.image_order_audit(self.root,plans,ids);self.assertEqual(len(timing),194)
            path=Path(plans["environment_connectivity"]["images"]["social_specific"])
            image=nib.load(path);nib.save(nib.Nifti1Image(image.get_fdata()[...,::-1].copy(),image.affine),path)
            with self.assertRaisesRegex(ValueError,"PPI participant/source order"):
                audit.image_order_audit(self.root,plans,ids)

    def test_shells_parse_and_no_environment_or_inference_changes(self):
        for name in ("launch_katie_review.sh","run_katie_review.sh"):
            result=subprocess.run(["bash","-n",str(base.ROOT/"code"/name)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
        source=(base.ROOT/"code/run_katie_review.sh").read_text()
        self.assertIn("venv-katie-review-",source);self.assertNotIn("code/run_katie_randomise.py run",source)


class ReviewPublication(unittest.TestCase):
    def test_isolated_publication_keeps_dirty_source_index_and_branch_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);project=root/"project";project.mkdir();(project/"work").mkdir()
            def git(*args,cwd=project):
                return subprocess.run(["git",*args],cwd=cwd,check=True,text=True,capture_output=True).stdout
            git("init","--initial-branch=main");git("config","user.name","Test User");git("config","user.email","test@example.invalid")
            (project/"source.txt").write_text("frozen source\n");git("add","source.txt");git("commit","-m","Initial")
            remote=root/"remote.git";git("clone","--bare",str(project),str(remote))
            (project/"source.txt").write_text("user edits retained\n");(project/"untracked.txt").write_text("retain")
            report=root/"report";report.mkdir();(report/"README.md").write_text("Aggregate review\n")
            (report/"review_manifest.json").write_text(json.dumps(dict(n=97,outputs={"README.md":base.cohort.digest(report/"README.md")})))
            before=(git("rev-parse","HEAD"),base.cohort.digest(project/".git/index"),git("status","--porcelain"))
            original_run=publisher.subprocess.run
            with patch.object(publisher,"REMOTE",str(remote)),patch.object(publisher.subprocess,"run",wraps=original_run) as invoked:
                publisher.publish(project,report)
                head=git("--git-dir",str(remote),"rev-parse","main")
                publisher.publish(project,report)
                self.assertEqual(head,git("--git-dir",str(remote),"rev-parse","main"))
                clone_calls=[call.args[0] for call in invoked.call_args_list if call.args[0][:2]==["git","clone"]]
                self.assertEqual(len(clone_calls),2)
                self.assertTrue(all(str(remote) in call and str(project) not in call and "--shared" not in call for call in clone_calls))
                self.assertFalse(any("safe.directory" in str(call.args) for call in invoked.call_args_list))
            self.assertEqual(before,(git("rev-parse","HEAD"),base.cohort.digest(project/".git/index"),git("status","--porcelain")))
            self.assertEqual(git("--git-dir",str(remote),"show","main:results/review/katie-review-v1/README.md"),"Aggregate review\n")


if __name__=="__main__":unittest.main()
