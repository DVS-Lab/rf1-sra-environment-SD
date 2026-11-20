import csv
import tempfile
import unittest
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import nibabel as nib
import numpy as np

KIT=Path(__file__).resolve().parents[1]/"publication/figures-v1"
sys.path.insert(0,str(KIT))
import render
import export_linux2 as native


class FigureKit(unittest.TestCase):
    def test_sealed_sources_and_products(self):
        with (KIT/"sources/provenance.tsv").open() as f:
            for row in csv.DictReader(f,delimiter="\t"):
                self.assertEqual(native.sha(KIT/row["asset"]),row["sha256"])
                self.assertEqual(native.sha(native.ROOT/row["sealed_repository_source"]),row["sha256"])
        figures=list((KIT/"figures").glob("*.svg"))
        self.assertEqual(len(figures),4)
        for path in figures:
            root=ET.parse(path)
            self.assertTrue(root.findall(".//{*}text"))
            self.assertEqual(path.with_suffix(".pdf").read_bytes()[:5],b"%PDF-")

    def test_filter_rejects_wrong_peak_or_p(self):
        ref=nib.Nifti1Image(np.zeros((3,4,5),dtype=np.uint8),np.diag([2,2,2,1]))
        stat=np.zeros(ref.shape); stat[1,2,3]=4.5
        labs=(stat>0).astype(int); prob=labs*.98
        row=dict(component=1,voxels=1,peak_x_mm=2,peak_y_mm=4,peak_z_mm=6,cluster_fwe_p_min=.02)
        region=native.subset(labs,stat,prob,ref,row)
        with self.assertRaises(ValueError):
            native.subset(labs,stat,prob,ref,dict(row,peak_y_mm=0))
        with self.assertRaises(ValueError):
            native.subset(labs,stat,prob,ref,dict(row,cluster_fwe_p_min=.04))
        with tempfile.TemporaryDirectory() as d:
            for name,values in [("mask",region.astype("uint8")),("signed_t",(-stat).astype("float32"))]:
                path=Path(d)/(name+".nii.gz"); native.export_image(path,ref,values)
                out=nib.load(path)
                np.testing.assert_array_equal(out.get_fdata(),values)
                np.testing.assert_allclose(out.affine,ref.affine)
                self.assertFalse(out.header.extensions)

    def test_overlap_uses_cluster_not_union(self):
        fig=render.overlap()
        try:
            matrix=np.asarray(fig.axes[0].collections[0].get_array()).reshape(10,10)
            np.testing.assert_array_equal(matrix,matrix.T)
            self.assertAlmostEqual(matrix[4,8],2*46/(169+188))
            self.assertEqual(matrix[8,9],0)
        finally:
            render.plt.close(fig)
