import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import nibabel as nib
import numpy as np
from PIL import Image
import statsmodels.api as sm

import run_social_win_mean as task
import review_katie_evidence as evidence
import test_fevs_imaging_adjustments as fixtures
import test_fevs_adjustment_maps as map_fixtures

base=task.base


class EvidenceFigures(unittest.TestCase):
    def test_main_effect_partial_residuals_match_exact_full_model(self):
        rng=np.random.default_rng(61);raw=rng.uniform(0,17,97)
        names=["ones","age","fevs","pm25","fevsxpm25","adi","ecog"]
        p=raw-raw.mean();m=rng.normal(size=97)
        x=np.column_stack([np.ones(97),rng.normal(size=97),p,m,p*m,rng.normal(size=(97,2))])
        y=x@np.array([2,.1,.8,.4,.2,.3,.1])+rng.normal(size=97)
        adjusted,fit,info=evidence.main_effect_fit(x,y,names,raw)
        self.assertEqual(info["n"],97);self.assertFalse(info["inferential_p_reported"])
        np.testing.assert_allclose(adjusted,fit.resid+fit.params[0]+fit.params[2]*p)
        self.assertAlmostEqual(info["beta"],sm.OLS(y,x).fit().params[2])
        with self.assertRaisesRegex(ValueError,"Matched ROI/design"):
            evidence.main_effect_fit(x[:-1],y[:-1],names,raw[:-1])

    def test_actual_contrast_heatmap_distinguishes_intercept_from_fevs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);rng=np.random.default_rng(3)
            names=["ones","age","fevs"];x=np.column_stack([np.ones(97),rng.normal(size=(97,2))])
            (root/"design.mat").write_text(base.vest_matrix(x))
            (root/"design.con").write_text(base.vest_contrasts(names,"fevs"))
            job=dict(design=str(root/"design.mat"),contrast=str(root/"design.con"),
                     contrasts=[dict(term="fevs",direction=d) for d in ("positive","negative")])
            path=root/"design.png"
            info=evidence.design_figure(path,job,names,"Executed synthetic design")
            self.assertFalse(info["ones_contrasted"]);self.assertEqual(info["rank"],3)
            self.assertGreater(np.asarray(Image.open(path)).std(),20)
            (root/"design.con").write_text(base.vest_contrasts(names,"ones"))
            job["contrasts"]=[dict(term="ones",direction=d) for d in ("positive","negative")]
            self.assertTrue(evidence.design_figure(path,job,names,"Intercept") ["ones_contrasted"])

    def test_native_l1_pngs_copied_unchanged_and_missing_cov_png_is_not_rebuilt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);report=root/"report";report.mkdir();pair=dict(subject="12345",contrast="4")
            for task_name in ("socialdoors","doors"):
                feat=root/task_name;feat.mkdir();pair[task_name+"_feat_dir"]=str(feat)
                (feat/"design.fsf").write_text('set fmri(conname_real.1) "win"\nset fmri(conname_real.2) "loss"\nset fmri(conname_real.4) "win-loss"\n')
                c=np.array([[1,0,0,0],[0,1,0,0],[0,0,1,0],[1,-1,0,0]],float)
                (feat/"design.con").write_text(base.vest_matrix(c));(feat/"design.mat").write_text(base.vest_matrix(np.ones((97,4))))
                Image.new("RGB",(50,50),"teal").save(feat/"design.png")
            items,_=evidence.l1_artifacts([pair],["12345"],report)
            self.assertEqual(sum(r["available"] for r in items),2)
            for name in ("socialdoors","doors"):
                self.assertEqual((report/("L1-"+name+"-design.png")).read_bytes(),(root/name/"design.png").read_bytes())
                self.assertFalse((root/name/"design_cov.png").exists())

    def test_brain_and_matching_scatter_render_side_by_side_with_null_row(self):
        phantom=map_fixtures.GeometryAndRendering(methodName="test_peak_shift_can_occur_inside_unchanged_original_cluster")
        phantom.setUp()
        try:
            rng=np.random.default_rng(67);raw=rng.uniform(0,17,97);p=raw-raw.mean();q=rng.normal(size=97)
            x=np.column_stack([np.ones(97),rng.normal(size=97),p,q,p*q]);names=["ones","age","fevs","pm25","fevsxpm25"]
            extra=rng.normal(size=(97,2));y=2-.8*p+.2*q+.3*p*q+rng.normal(size=97)
            rows=[];models=[]
            for i,name in enumerate(evidence.mapped.ORDER):
                selected=phantom.original.copy()
                if i==2:selected[:]=False
                statistic=np.zeros(selected.shape);statistic[phantom.original]=4.5
                rows.append(dict(adjustment=name,p=.04 if selected.any() else .06,selected=selected,
                                 signed_t=-statistic,location=dict(voxels=int(selected.sum()))))
                added=[] if i==0 else [0] if i==1 else [1] if i==2 else [0,1]
                models.append((names+[["adi","ecog"][j] for j in added],np.column_stack([x,*[extra[:,j] for j in added]])))
            path=phantom.root/"paired.png"
            fits=evidence.matched_panel(path,"vs_fevs_pm25",dict(rows=rows,reference=phantom.reference,cut_coords=[-18,21,6]),
                                       models,y,raw,str(phantom.anatomy))
            self.assertEqual(len(fits),4);self.assertTrue(all(r["n"]==97 and r["beta"]<0 for r in fits))
            self.assertGreater(np.asarray(Image.open(path)).std(),20)
            if os.environ.get("KATIE_PREVIEW_DIR"):
                import shutil
                destination=Path(os.environ["KATIE_PREVIEW_DIR"]);destination.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(path,destination/"synthetic-evidence-paired.png")
        finally:phantom.tearDown()


class TaskMean(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ImagingAdjustments(methodName="test_catalog_preserves_base_columns_and_adds_only_centered_adjustments")
        self.fixture.setUp()
        self.project=self.fixture.project
        text=self.fixture.fake.read_text().replace("import sys\n","import sys\nprint('Using sign-flipping')\n")
        self.fixture.fake.write_text(text)
        prior=task.adjustments.build(self.fixture.args)
        self.folder=self.project/"derivatives/fsl/randomise/katie-remaining-v1/activation"
        self.folder.mkdir(parents=True)
        original=self.fixture.original["jobs"][0]
        x=task.adjustments.extension.audit.matrix(original["design"])[:,:7]
        names=task.adjustments.COMMON
        for name,text in {"design.mat":base.vest_matrix(x),"design.con":base.vest_contrasts(names,"ones"),
            "design.tsv":base.review.tsv([dict(subject=s,**dict(zip(names,row))) for s,row in zip(self.fixture.ids,x)]),
            "subjects.tsv":base.review.tsv([dict(subject=s) for s in self.fixture.ids])}.items():(self.folder/name).write_text(text)
        group=dict(n=97,sources=[],jobs=[dict(outcome="social_specific",z=3.1,design=str(self.folder/"design.mat"))],
            mask=prior["masks"]["activation"],randomise=str(self.fixture.fake),
            outputs={p.name:base.cohort.digest(p) for p in self.folder.iterdir()})
        base.write_json(self.folder/"plan.json",group)
        (self.folder/"plan.sha256").write_text(base.cohort.digest(self.folder/"plan.json"))
        self.args=SimpleNamespace(project=self.project,output=self.project/"derivatives/fsl/randomise"/task.VERSION)
        self.root_patch=patch.object(task,"ROOT",self.fixture.release);self.root_patch.start()

    def tearDown(self):self.root_patch.stop();self.fixture.tearDown()

    def test_two_intercept_jobs_sign_flip_gate_and_safe_resume(self):
        before={str(p):base.cohort.digest(p) for p in self.fixture.source.rglob("*") if p.is_file()}
        task.run(self.args);plan=task.check(self.args)
        self.assertEqual(len(plan["jobs"]),2)
        c=task.adjustments.extension.audit.matrix(self.args.output/"design.con")
        np.testing.assert_array_equal(c[:,0],[1,-1]);self.assertFalse(c[:,1:].any())
        self.assertEqual(plan["images"]["social_win"],self.fixture.original["images"]["activation/win_only"])
        stamps={str(p):p.stat().st_mtime_ns for p in self.args.output.rglob("success.json")}
        task.run(self.args)
        self.assertEqual(stamps,{str(p):p.stat().st_mtime_ns for p in self.args.output.rglob("success.json")})
        self.assertEqual(before,{str(p):base.cohort.digest(p) for p in self.fixture.source.rglob("*") if p.is_file()})

    def test_missing_sign_flip_confirmation_never_launches_full_jobs(self):
        plan=task.build(self.args)
        def smoke(*args,**kwargs):
            folder=self.args.output/"smoke";attempt=folder/"attempts/a";attempt.mkdir(parents=True)
            (attempt/"console.log").write_text("ordinary permutation only")
            base.write_json(folder/"success.json",dict(attempt=str(attempt)))
            return "COMPLETED"
        with patch.object(base,"execute",side_effect=smoke) as execute:
            with self.assertRaisesRegex(ValueError,"No native sign-flip"):
                task.run(self.args)
        self.assertEqual(execute.call_count,1);self.assertFalse((self.args.output/"jobs").exists())

    def test_noncentered_or_reordered_original_group_is_rejected(self):
        group=json.loads((self.folder/"plan.json").read_text())
        with self.assertRaisesRegex(ValueError,"centered group design"):
            task.task_design(group,self.fixture.ids[::-1])
        x=task.adjustments.extension.audit.matrix(self.folder/"design.mat");x[:,1]+=2
        (self.folder/"design.mat").write_text(base.vest_matrix(x))
        with self.assertRaisesRegex(ValueError,"centered group design"):
            task.task_design(group,self.fixture.ids)


class EvidenceIntegration(unittest.TestCase):
    def test_native_to_report_flow_no_old_results_modified(self):
        f=map_fixtures.SavedMapReview(methodName="test_saved_results_match_summary_no_new_inference_and_reuse")
        f.setUp()
        try:
            project=f.project;group=project/"derivatives/fsl/randomise/katie-remaining-v1/activation";group.mkdir(parents=True)
            original=f.fixture.original["jobs"][0]
            x=task.adjustments.extension.audit.matrix(original["design"])[:,:7];names=task.adjustments.COMMON
            for filename,text in {"design.mat":base.vest_matrix(x),"design.con":base.vest_contrasts(names,"ones"),
                "design.tsv":base.review.tsv([dict(subject=s,**dict(zip(names,row))) for s,row in zip(f.fixture.ids,x)]),
                "subjects.tsv":base.review.tsv([dict(subject=s) for s in f.fixture.ids])}.items():(group/filename).write_text(text)
            jobs=[dict(key=f"{outcome}/group_mean/z-"+str(z).replace(".","p"),outcome=outcome,model="group_mean",z=z,
                t_cutoff=3.2,residual_dof=90,permutations=10000,seed=20261101,design=str(group/"design.mat"),contrast=str(group/"design.con"))
                for outcome in ("socialdoors","doors","average","social_specific") for z in (2.6,3.1)]
            old=dict(n=97,jobs=jobs,sources=[],mask=f.plan["masks"]["activation"],randomise=str(f.fixture.fake),
                images={outcome:f.plan["images"]["activation/win_only"] for outcome in ("socialdoors","doors","average","social_specific")},
                outputs={p.name:base.cohort.digest(p) for p in group.iterdir()})
            base.write_json(group/"plan.json",old);(group/"plan.sha256").write_text(base.cohort.digest(group/"plan.json"))
            for job in jobs:base.execute(old,job,group/"jobs"/job["key"],base.cohort.digest(group/"plan.json"))
            args=SimpleNamespace(project=project,output=project/"derivatives/fsl/randomise"/task.VERSION)
            execute=base.execute
            def smoke(*args,**kwargs):
                result=execute(*args,**kwargs)
                if kwargs.get("smoke"):
                    path=Path(args[2]);saved=json.loads((path/"success.json").read_text())
                    log=Path(saved["attempt"])/"console.log";log.write_text(log.read_text()+"\nUsing sign-flipping\n")
                return result
            with patch.object(task,"ROOT",f.fixture.release),patch.object(base,"execute",side_effect=smoke):task.run(args)
            before={str(p):base.cohort.digest(p) for p in (project/"derivatives").rglob("*") if p.is_file()}
            report=project/"work/evidence-test/report"
            def paired(path,target,group,models,y,raw,anatomy):
                Image.new("RGB",(100,100),"navy").save(path)
                return [dict(target=target,adjustment=row["adjustment"],**evidence.main_effect_fit(x,y,names,raw)[2]) for row,(names,x) in zip(group["rows"],models)]
            def brain(task):Image.new("RGB",(100,100),"navy").save(task["path"])
            with patch.object(evidence,"ROOT",f.fixture.release),patch.object(evidence.mapped,"check_analysis"), \
                 patch.object(evidence.mapped.views.background,"select",return_value=dict(path=str(f.anatomy))), \
                 patch.object(evidence,"l1_artifacts",return_value=([],[])),patch.object(evidence,"matched_panel",side_effect=paired), \
                 patch.object(evidence.mapped.views.plots,"brain_figure",side_effect=brain):
                evidence.build(SimpleNamespace(project=project,report=report))
            self.assertEqual(before,{str(p):base.cohort.digest(p) for p in (project/"derivatives").rglob("*") if p.is_file()})
            summary=json.loads((report/"summary.json").read_text())
            self.assertEqual(len(summary["descriptive_fits"]),12);self.assertEqual(len(summary["group_means"]),12)
            self.assertEqual(len(summary["designs"]),4);self.assertEqual(sum(d["ones_contrasted"] for d in summary["designs"]),1)
            self.assertEqual(summary["new_randomise_jobs"],2);self.assertEqual(summary["new_directional_maps"],4)
            self.assertFalse(summary["exclusions_changed"])
            from publish_katie_review import payload
            self.assertGreaterEqual(len(payload(report)),14)
        finally:f.tearDown()


if __name__=="__main__":unittest.main()
