from pathlib import Path
import tempfile
import unittest

import nibabel as nib
import numpy as np

import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"code"))
import select_katie_background as background


class BackgroundSelection(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.valid=self.root/"FSL-MNI-T1.nii.gz"
        nib.save(nib.Nifti1Image(np.arange(125,dtype=float).reshape(5,5,5),np.eye(4)),self.valid)

    def tearDown(self):self.temp.cleanup()

    def test_zero_byte_placeholder_falls_back_without_modifying_either_file(self):
        empty=self.root/"templateflow-placeholder.nii.gz";empty.touch()
        saved=self.valid.read_bytes()
        result=background.select([empty,self.valid])
        self.assertEqual(result["path"],str(self.valid.resolve()))
        self.assertEqual(len(result["rejected_candidates"]),1)
        self.assertEqual(empty.stat().st_size,0);self.assertEqual(self.valid.read_bytes(),saved)
        self.assertFalse(result["downloaded"])

    def test_corrupt_constant_and_four_dimensional_candidates_are_rejected(self):
        corrupt=self.root/"corrupt.nii.gz";corrupt.write_bytes(b"not a NIfTI")
        constant=self.root/"constant.nii.gz";nib.save(nib.Nifti1Image(np.ones((4,4,4)),np.eye(4)),constant)
        four=self.root/"four.nii.gz";nib.save(nib.Nifti1Image(np.ones((4,4,4,2)),np.eye(4)),four)
        result=background.select([corrupt,constant,four,self.valid])
        self.assertEqual(len(result["rejected_candidates"]),3)

    def test_valid_preferred_background_is_kept(self):
        result=background.select([self.valid,self.root/"absent.nii.gz"])
        self.assertEqual(result["rejected_candidates"],[])
        self.assertEqual(result["shape"],[5,5,5])

    def test_no_valid_background_stops_without_creating_or_downloading_anything(self):
        missing=self.root/"absent.nii.gz"
        with self.assertRaisesRegex(ValueError,"No readable nonempty"):
            background.select([missing])
        self.assertFalse(missing.exists())

    def test_renderer_does_not_change_so_completed_receipts_remain_compatible(self):
        self.assertEqual(background.base.cohort.digest(background.base.ROOT/"code/plot_katie_results.py"),
            "8b465e88e920966650c8f914758c99bfeed678e9187344c3ad7f6a5ff47ceef3")


if __name__=="__main__":unittest.main()
