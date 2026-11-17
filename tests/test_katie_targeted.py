import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"code"))
import review_katie_targeted as r


class Targeted(unittest.TestCase):
    def test_quadratic_preserves_hierarchy_and_97_rows(self):
        _, values = r.values()
        names, x = r.prior.previous.behavior.design(values, "pm25", "mspss")
        cols, q = r.quadratic(names, x)
        self.assertEqual(q.shape, (97,8))
        np.testing.assert_array_equal(q[:, :6], x)
        np.testing.assert_array_equal(q[:,6], x[:,2]**2)
        np.testing.assert_array_equal(q[:,7], x[:,1]*x[:,2]**2)
        v = r.slope_vectors(cols,"pm25","interaction",values["mspss"],[4,6],
                            "pm25_x_mspss_squared")
        beta = np.arange(8.)
        # Verify analytic slope by differentiating predictions numerically.
        for i, level in enumerate((4,6)):
            s = level-values["mspss"].mean()
            def predict(p):
                return np.array([1,p,s,0,0,p*s,s*s,p*s*s]) @ beta
            self.assertAlmostEqual(v[i]@beta, (predict(.00001)-predict(-.00001))/.00002, places=8)

    def test_tail_counts_include_boundary_ties(self):
        _, v = r.values()
        levels, masks = r.support_groups(v["mspss"])
        self.assertTrue(np.all(np.stack(masks).sum(axis=0)==1))
        self.assertTrue(np.all(masks[0][v["mspss"]==levels[0]]))
        self.assertTrue(np.all(masks[2][v["mspss"]==levels[2]]))
        self.assertEqual(sum(row["n"] for row in r.density_rows(v["mspss"],v["pm25"],"PM2.5")),97)

    def test_exact_overlap_and_empty_support(self):
        a=np.array([True,True,False,False])
        b=np.array([False,True,True,True])
        self.assertEqual(r.overlap(a,b),dict(voxels_a=2,voxels_b=3,shared_voxels=1,
                                           fraction_a=.5,fraction_b=1/3,dice=.4))
        self.assertIsNone(r.overlap(a&False,b&False)["dice"])

    def test_fixed_components_use_frozen_order_and_reject_wrong_direction(self):
        ref=r.nib.Nifti1Image(np.ones((2,2,2),dtype=np.float32),np.eye(4))
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            win,doors=folder/"social"/"cope1.nii.gz",folder/"doors"/"cope1.nii.gz"
            for p, v in ((win,3.5),(doors,2.0)):
                p.parent.mkdir()
                r.nib.save(r.nib.Nifti1Image(np.full((2,2,2),v),ref.affine),p)
            rows=[dict(volume=i,subject=str(i),task=task,cope=1,source=str(p),family="activation")
                  for i in range(97) for task,p in (("socialdoors",win),("doors",doors))]
            order=folder/"source_order.tsv"
            order.write_text(r.base.review.tsv(rows))
            records={str(p.resolve()):{} for p in (win,doors,order)}
            roi=np.ones(ref.shape,dtype=bool)
            stack=np.full((8,97),1.5)
            ids=[str(i) for i in range(97)]
            fits=r.components(folder,records,ids,ref,roi,stack)
            np.testing.assert_array_equal(fits["socialdoors"],np.full(97,3.5))
            with self.assertRaisesRegex(ValueError,"contrast direction"):
                r.components(folder,records,ids,ref,roi,-stack)
            with self.assertRaisesRegex(ValueError,"provenance/order"):
                r.components(folder,records,ids[::-1],ref,roi,stack)

    def test_signed_contrast_and_qc_columns_validate(self):
        ids,v=r.values()
        names=["ones","pair_mean_fd","pair_mean_tsnr","e11","xa30","gender_code1","age","adi","ecog","adixecog"]
        _, covariates=r.base.cohort.read_table(r.ROOT/"data/derived/model-review-v1/centered_candidate_terms.tsv")
        x=np.array([[float(row[n]) for n in names] for row in covariates])
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)
            (path/"design.mat").write_text(r.base.vest_matrix(x))
            (path/"design.tsv").write_text(r.base.review.tsv([dict(subject=s,**dict(zip(names,row))) for s,row in zip(ids,x)]))
            (path/"design.con").write_text(r.base.vest_contrasts(names,"adixecog"))
            job=dict(design=path/"design.mat",contrast=path/"design.con",residual_dof=87)
            actual, xx=r.checked_matrix(job,ids,v,"average","adixecog","negative",2)
            self.assertEqual(actual,names)
            np.testing.assert_array_equal(x,xx)
            with self.assertRaisesRegex(ValueError,"signed coefficient"):
                r.checked_matrix(job,ids,v,"average","adixecog","positive",2)
            with self.assertRaisesRegex(ValueError,"design"):
                r.checked_matrix(job,ids,v,"social_specific","adixecog","negative",2)

    def test_behavior_recovers_published_linear_fit_without_subject_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            r.behavior(folder)
            data=json.loads((folder/"behavior.json").read_text())
            self.assertEqual(len(data["fits"]),2)
            self.assertEqual(len(data["anchors"]),6)
            self.assertTrue(all(fit["n"]==97 for fit in data["fits"]))
            self.assertAlmostEqual(data["fits"][0]["beta"],-.98883,places=5)
            for table in folder.glob("*.tsv"):
                self.assertNotIn("subject",table.read_text().splitlines()[0])


if __name__=="__main__":
    unittest.main()
