import json
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import nibabel as nib
import numpy as np
from PIL import Image

import review_fevs_adjustment_maps as review
import test_fevs_imaging_adjustments as fixtures

base=review.base


class GeometryAndRendering(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        shape=(40,40,40);affine=np.diag([3.,3.,3.,1.]);affine[:3,3]=[-60,-60,-60]
        grid=np.indices(shape);radius=((grid[0]-20)/16)**2+((grid[1]-20)/17)**2+((grid[2]-20)/17)**2
        self.anatomy=self.root/"anatomy.nii.gz"
        nib.save(nib.Nifti1Image((800*np.exp(-radius)*(radius<1)).astype(np.float32),affine),self.anatomy)
        self.reference=nib.Nifti1Image(np.ones(shape),affine)
        self.original=np.zeros(shape,bool);self.original[12:16,25:29,20:24]=True

    def tearDown(self):self.temp.cleanup()

    def test_peak_shift_can_occur_inside_unchanged_original_cluster(self):
        t=np.zeros(self.original.shape);t[self.original]=4;t[15,28,23]=5
        result=review.geometry(self.original,t,self.reference,self.original)
        self.assertEqual(result["dice"],1)
        self.assertTrue(result["peak_in_original"])
        np.testing.assert_array_equal(result["peak_mni"],[-15,24,9])
        empty=review.geometry(np.zeros_like(self.original),t,self.reference,self.original)
        self.assertIsNone(empty["peak_mni"]);self.assertIsNone(empty["peak_in_original"])
        self.assertEqual(empty["voxels"],0)

    def test_fixed_slice_signed_panels_nonblank_and_no_cluster_is_explicit(self):
        for target,sign in (("activation_fevs_pm25",1),("vs_fevs_pm25",-1)):
            rows=[]
            for i,name in enumerate(review.ORDER):
                selected=self.original.copy()
                if i==2:selected[:]=False
                t=np.zeros(self.original.shape);t[self.original]=4.5
                rows.append(dict(adjustment=name,p=.04 if selected.any() else .06,selected=selected,
                    signed_t=sign*t,location=dict(voxels=int(selected.sum()))))
            path=self.root/(target+".png")
            review.render(path,target,dict(rows=rows,reference=self.reference,cut_coords=[-18,21,6]),str(self.anatomy))
            pixels=np.asarray(Image.open(path).convert("RGB"))
            self.assertGreater(pixels.std(),20)
            delta=pixels[...,0].astype(float)-pixels[...,2].astype(float)
            self.assertGreater(np.sum(delta>60) if sign==1 else np.sum(delta< -60),100)
            if os.environ.get("KATIE_PREVIEW_DIR"):
                preview=Path(os.environ["KATIE_PREVIEW_DIR"]);preview.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(path,preview/("synthetic-adjustment-"+target+".png"))


class SavedMapReview(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ImagingAdjustments(methodName="test_catalog_preserves_base_columns_and_adds_only_centered_adjustments")
        self.fixture.setUp()
        self.project=self.fixture.project
        self.fixture.root_patch.stop()
        moved=self.project/"work/frozen-analysis-release";moved.parent.mkdir()
        shutil.move(self.fixture.release,moved);self.fixture.release=moved
        self.fixture.root_patch=patch.object(review.adjustment,"ROOT",moved);self.fixture.root_patch.start()
        # Synthetic negative VS association, positive activation. No study data.
        text=self.fixture.fake.read_text()
        text=text.replace("count=int(","negative='/connectivity/' in prefix or '/vs_fevs_pm25/' in prefix\ncount=int(")
        text=text.replace("4. if i%2 else -4.","(4. if i%2 else -4.)*(-1 if negative else 1)")
        text=text.replace(".96 if i%2 else 0.",".96 if (i%2==0 if negative else i%2==1) else 0.")
        self.fixture.fake.write_text(text)
        for job in self.fixture.original["jobs"]:
            if job["family"]!="connectivity":continue
            path=self.fixture.source/"jobs"/job["key"]/"success.json"
            saved=json.loads(path.read_text());prefix=Path(saved["attempt"])/"randomise"
            for d in job["contrasts"]:
                i=d["index"]
                for suffix,value in ((f"_tstat{i}.nii.gz",-4. if i%2 else 4.),
                                     (f"_clustere_corrp_tstat{i}.nii.gz",0. if i%2 else .96)):
                    nib.save(nib.Nifti1Image(np.full((2,2,2),value),np.eye(4)),str(prefix)+suffix)
            saved["outputs"]=review.adjustment.extension.products(prefix,self.fixture.original["masks"]["connectivity"],job["contrasts"])
            base.write_json(path,saved)
        self.fixture.args.jobs=6
        review.adjustment.run(self.fixture.args)
        self.plan=review.adjustment.check(self.fixture.args)
        self.args=SimpleNamespace(project=self.project,report=self.project/"work/map-review/report",atlas_root=self.project/"no-atlases")
        self.anatomy=self.project/"work/anatomy.nii.gz"
        grid=np.indices((20,20,20));data=np.exp(-sum((g-10)**2 for g in grid)/50)*800
        affine=np.eye(4);affine[:3,3]=-10
        nib.save(nib.Nifti1Image(data,affine),self.anatomy)

    def tearDown(self):self.fixture.tearDown()

    def test_saved_results_match_summary_no_new_inference_and_reuse(self):
        before={str(p):base.cohort.digest(p) for p in self.project.joinpath("derivatives").rglob("*") if p.is_file()}
        def render(path,*args):Image.new("RGB",(100,100),"navy").save(path)
        with patch.object(review.subprocess,"run") as call,patch.object(review.views.background,"select",return_value=dict(path=str(self.anatomy))),patch.object(review,"render",side_effect=render):
            review.build(self.args)
        self.assertEqual(call.call_count,1)
        self.assertEqual(call.call_args.args[0][2],"check")
        self.assertIn(str(self.fixture.release),call.call_args.args[0][1])
        self.assertNotIn("randomise",call.call_args.args[0])
        self.assertEqual(before,{str(p):base.cohort.digest(p) for p in self.project.joinpath("derivatives").rglob("*") if p.is_file()})
        saved=json.loads((self.args.report/"locations.json").read_text())
        self.assertEqual(len(saved["locations"]),12);self.assertFalse(saved["new_inference"])
        self.assertFalse(saved["exclusions_changed"]);self.assertFalse(saved["atlas_available"])
        from publish_katie_review import payload
        self.assertEqual(len(payload(self.args.report)),7)
        stamps={p.name:p.stat().st_mtime_ns for p in self.args.report.iterdir()}
        review.build(self.args)
        self.assertEqual(stamps,{p.name:p.stat().st_mtime_ns for p in self.args.report.iterdir()})

    def test_changed_published_count_stops_and_negative_vs_is_not_activation(self):
        groups,_=review.collect(self.plan,self.fixture.args.output)
        self.assertEqual(groups["vs_fevs_pm25"]["rows"][0]["direction"],"negative")
        self.assertLess(groups["vs_fevs_pm25"]["rows"][0]["signed_t"].min(),0)
        path=self.fixture.args.output/"report/maps.tsv"
        fields,rows=base.cohort.read_table(path)
        row=next(r for r in rows if r["target"]=="activation_fevs" and r["adjustment"]=="baseline" and r["z"]=="3.1" and r["direction"]=="positive")
        row["significant_voxels"]="999"
        path.write_text(base.review.tsv(rows,fields))
        with self.assertRaisesRegex(ValueError,"published summary"):
            review.collect(self.plan,self.fixture.args.output)


if __name__=="__main__":unittest.main()
