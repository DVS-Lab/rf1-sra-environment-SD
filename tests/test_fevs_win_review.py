import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import nibabel as nib
import numpy as np
from PIL import Image

import review_fevs_wins as review
import publish_katie_review as publisher
import test_reward_extension as fixtures

base=review.extension.base


class Atlas(unittest.TestCase):
    def test_xml_zero_based_label_indices_unlabeled_and_outside(self):
        with tempfile.TemporaryDirectory() as temp:
            xml=Path(temp)/"atlas.xml"
            xml.write_text('<atlas><data><label index="0">First region</label><label index="1">Second region</label></data></atlas>')
            values=np.zeros((3,3,3),dtype=np.int16);values[1,1,1]=1;values[2,2,2]=2
            image=nib.Nifti1Image(values,np.eye(4))
            result=review.atlas_annotation(image,xml,np.array([[1,1,1],[2,2,2],[0,0,0],[10,10,10]]))
            counts={r["label"]:r["voxels"] for r in result}
            self.assertEqual(counts,{"Unlabeled":2,"First region":1,"Second region":1})


class TargetedReport(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.Extension(methodName="test_numeric_designs_contrasts_and_conditional_main_effects")
        self.fixture.setUp();self.root=self.fixture.root
        self.plan=self.fixture.write_plan();self.folder=self.fixture.output
        shape=(32,40,32);affine=np.diag([4.,4.,4.,1.]);affine[:3,3]=[-64,-100,-64]
        grid=np.indices(shape);r=((grid[0]-16)/13)**2+((grid[1]-21)/16)**2+((grid[2]-16)/14)**2
        self.anatomy=self.root/"synthetic-anatomy.nii.gz"
        nib.save(nib.Nifti1Image((np.exp(-r)*800*(r<1)).astype(np.float32),affine),self.anatomy)
        mask=self.root/"target-mask.nii.gz"
        nib.save(nib.Nifti1Image((r<1).astype(np.uint8),affine),mask)
        _,roster=base.cohort.read_table(review.ROOT/"data/derived/katie-cohort-v1/subjects.tsv")
        ids=[v["subject"] for v in roster];scores,_=review.financial.read_scores(review.financial.SCORES,ids)
        predictor=np.array([v["fevs"] for v in scores]);predictor-=predictor.mean()
        rng=np.random.default_rng(12)
        data=rng.normal(scale=.4,size=shape+(97,)).astype(np.float32)+predictor.astype(np.float32)*.2
        stack=self.root/"target-stack.nii.gz";nib.save(nib.Nifti1Image(data,affine),stack)
        self.plan["masks"]["activation"]=str(mask);self.plan["images"]["activation/win_only"]=str(stack)
        self.plan["sources"] += [base.fingerprint(p) for p in (mask,stack)]
        base.write_json(self.folder/"plan.json",self.plan)
        self.digest=base.cohort.digest(self.folder/"plan.json");(self.folder/"plan.sha256").write_text(self.digest)
        self.selected=[]
        for index,model in enumerate(review.TARGETS):
            job=next(j for j in self.plan["jobs"] if j["key"]==f"activation/win_only/{model}/z-3p1")
            destination=self.folder/"jobs"/job["key"]
            self.fixture.success(self.plan,job,destination,self.digest)
            prefix=destination/"attempts/attempt-0001/randomise"
            corrected=np.zeros(shape);corrected[14+index:18+index,24:28,15:18]=.97+index*.01
            statistic=np.zeros(shape);statistic[corrected>0]=4.5
            for suffix,values in (("_tstat1.nii.gz",statistic),("_clustere_corrp_tstat1.nii.gz",corrected)):
                nib.save(nib.Nifti1Image(values,affine),str(prefix)+suffix)
            receipt=destination/"success.json";saved=json.loads(receipt.read_text())
            saved["outputs"]=review.extension.products(prefix,mask,job["contrasts"]);base.write_json(receipt,saved)
            self.selected.append((job,receipt))
        self.args=SimpleNamespace(project=self.root,report=self.root/"work/target/report",atlas_root=self.root/"no-atlases")

    def tearDown(self):self.fixture.tearDown()

    def build(self):
        with patch.object(review.background,"select",return_value=dict(path=str(self.anatomy))):review.build(self.args)

    def test_two_main_effect_reports_n97_overlap_and_safe_reuse(self):
        self.build();report=self.args.report
        result=json.loads((report/"summary.json").read_text())
        self.assertEqual(result["n"],97);self.assertFalse(result["exclusions_changed"])
        self.assertEqual([r["voxels"] for r in result["clusters"]],[48,48])
        self.assertAlmostEqual(result["overlap"]["dice"],.75)
        self.assertIn("NOT the interaction",result["clusters"][1]["context"])
        self.assertTrue(all(r["term"]=="fevs" and r["n"]==97 for r in result["region_fits"]))
        files=publisher.payload(report)
        self.assertFalse(any("private" in name or "diagnostics" in name for name in files))
        self.assertEqual(len(list((report.parent/"participant-diagnostics").glob("*.tsv"))),2)
        for path in report.glob("*.png"):
            pixels=np.asarray(Image.open(path).convert("RGB"))
            self.assertGreater(pixels.std(),20)
            if path.name.endswith("-brain.png"):
                red=(pixels[...,0].astype(float)-pixels[...,2]>40)&(pixels[...,0].astype(float)-pixels[...,1]>40)
                self.assertGreater(red.sum(),30)
            if os.environ.get("KATIE_PREVIEW_DIR"):
                target=Path(os.environ["KATIE_PREVIEW_DIR"]);target.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(path,target/("target-synthetic-"+path.name))
        before={str(p):p.stat().st_mtime_ns for p in report.iterdir()}
        self.build();self.assertEqual(before,{str(p):p.stat().st_mtime_ns for p in report.iterdir()})
        source=Path(self.plan["images"]["activation/win_only"]);source.write_bytes(b"changed")
        with self.assertRaises(ValueError):review.verify(report,report.parent/"inputs-private.json")

    def test_unfinished_and_wrong_contrast_receipts_rejected_before_rendering(self):
        _,receipt=self.selected[0];saved=json.loads(receipt.read_text());receipt.unlink()
        with self.assertRaisesRegex(ValueError,"not finished"):self.build()
        saved["smoke"]=True;base.write_json(receipt,saved)
        with self.assertRaisesRegex(ValueError,"command/receipt"):self.build()
        self.assertFalse(self.args.report.exists())

    def test_corrupted_native_pixels_rejected_before_rendering(self):
        _,receipt=self.selected[1];saved=json.loads(receipt.read_text())
        target=Path(saved["attempt"])/"randomise_tstat1.nii.gz";target.write_bytes(b"corrupt")
        with self.assertRaises(Exception):self.build()
        self.assertFalse(self.args.report.exists())

    def test_reversed_design_rows_and_nonmain_contrast_are_rejected(self):
        job,_=self.selected[0];design=Path(job["design"]).with_suffix(".tsv")
        original=base.cohort.read_table
        def reversed_rows(path):
            fields,rows=original(path)
            return (fields,list(reversed(rows))) if Path(path)==design else (fields,rows)
        with patch.object(base.cohort,"read_table",side_effect=reversed_rows),self.assertRaisesRegex(ValueError,"participant order"):
            self.build()
        # No rendering occurred; preserve the empty directory for the second guard.
        matrix=review.audit.matrix
        def wrong_contrast(path):
            value=matrix(path)
            if Path(path)==Path(job["contrast"]):value[0]*=-1
            return value
        with patch.object(review.audit,"matrix",side_effect=wrong_contrast),self.assertRaisesRegex(ValueError,"main-effect contrast"):
            self.build()


class Publisher(unittest.TestCase):
    def test_versioned_publication_preserves_original_and_dirty_checkout(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);project=root/"project";project.mkdir();(project/"work").mkdir()
            def git(*args,cwd=project):
                return subprocess.run(["git",*args],cwd=cwd,check=True,text=True,capture_output=True).stdout
            git("init","--initial-branch=main");git("config","user.name","Test User");git("config","user.email","test@example.invalid")
            original=project/publisher.DESTINATION;original.mkdir(parents=True);(original/"README.md").write_text("Original retained\n")
            git("add",".");git("commit","-m","Original")
            remote=root/"remote.git";git("clone","--bare",str(project),str(remote))
            (project/"keep.txt").write_text("staged work\n");git("add","keep.txt")
            before=(git("rev-parse","HEAD"),base.cohort.digest(project/".git/index"),git("status","--porcelain"))
            report=root/"report";report.mkdir();(report/"README.md").write_text("New aggregate review\n")
            (report/"review_manifest.json").write_text(json.dumps(dict(outputs={"README.md":base.cohort.digest(report/"README.md")})))
            target=Path("results/review/fevs-win-v1")
            with patch.object(publisher,"REMOTE",str(remote)):
                publisher.publish(project,report,target);head=git("--git-dir",str(remote),"rev-parse","main")
                publisher.publish(project,report,target)
                self.assertEqual(head,git("--git-dir",str(remote),"rev-parse","main"))
            self.assertEqual(git("--git-dir",str(remote),"show","main:"+str(publisher.DESTINATION/"README.md")),"Original retained\n")
            self.assertEqual(git("--git-dir",str(remote),"show","main:"+str(target/"README.md")),"New aggregate review\n")
            self.assertEqual(before,(git("rev-parse","HEAD"),base.cohort.digest(project/".git/index"),git("status","--porcelain")))
            for invalid in ("../other","/tmp/report","results/review/../../x","results/other/x"):
                with self.assertRaises(ValueError):publisher.publish(project,report,invalid)

    def test_shell_is_readonly_detached_https_and_no_pull(self):
        script=base.ROOT/"code/launch_fevs_win_review.sh"
        subprocess.run(["bash","-n",str(script)],check=True)
        text=script.read_text()
        for required in ("umask 0000","nohup setsid","publish_run_logs.py","snapshot_reward_extension.py","git archive","--destination results/review/fevs-win-v1"):
            self.assertIn(required,text)
        for forbidden in ("git pull","kill -","run_reward_extension.py run","randomise -","rsync","scp "):
            self.assertNotIn(forbidden,text)


if __name__=="__main__":unittest.main()
