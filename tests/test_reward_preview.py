import json
from pathlib import Path
import sys
import unittest

import nibabel as nib
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"code"))
import preview_reward_extension as preview
import test_reward_extension as fixtures
import snapshot_reward_extension as snapshot


class Preview(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.Extension(methodName="test_full_catalog_220_jobs_1328_tests_and_no_old_focal_retests")
        self.fixture.setUp();self.plan=self.fixture.write_plan()
        self.root,self.output=self.fixture.root,self.fixture.output

    def tearDown(self):self.fixture.tearDown()

    def completed(self):
        job=self.plan["jobs"][0]
        self.fixture.success(self.plan,job,self.output/"jobs"/job["key"],
                             preview.extension.base.cohort.digest(self.output/"plan.json"))
        path=self.output/"jobs"/job["key"]/"success.json"
        saved=json.loads(path.read_text());prefix=Path(saved["attempt"])/"randomise"
        image=nib.load(str(prefix)+"_clustere_corrp_tstat1.nii.gz")
        nib.save(nib.Nifti1Image(np.full(image.shape,.99),image.affine),str(prefix)+"_clustere_corrp_tstat1.nii.gz")
        saved["outputs"]=preview.extension.products(prefix,self.plan["masks"][job["family"]],job["contrasts"])
        path.write_text(json.dumps(saved))
        return prefix,job

    def test_only_completed_maps_are_summarized_without_modification(self):
        prefix,job=self.completed()
        base=preview.extension.base
        before={p:base.cohort.digest(p) for p in self.output.rglob("*") if p.is_file()}
        result=preview.preview(self.root)
        self.assertEqual(result["completed_jobs"],1);self.assertEqual(result["pending_jobs"],219)
        self.assertTrue(result["preliminary"])
        self.assertEqual(result["verified_completed_maps"],len(job["contrasts"]))
        self.assertEqual(result["significant_map_count"],1)
        self.assertEqual(result["corrected_findings"][0]["term"],job["contrasts"][0]["term"])
        self.assertEqual(before,{p:base.cohort.digest(p) for p in self.output.rglob("*") if p.is_file()})

    def test_corrupt_completed_result_stops_preview_instead_of_silent_skip(self):
        prefix,_=self.completed()
        Path(str(prefix)+"_tstat1.nii.gz").write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError,"Frozen input changed"):
            preview.preview(self.root)

    def test_wrapper_and_executable_share_one_output_prefix(self):
        lines=["12 bash randomise -i x -o /work/job-1/randomise", "13 randomise -i x -o /work/job-1/randomise",
               "14 randomise -i x -o /work/job-2/randomise"]
        self.assertEqual(len(snapshot.output_prefixes(lines)),2)


if __name__=="__main__":unittest.main()
