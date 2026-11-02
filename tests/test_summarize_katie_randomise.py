import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import nibabel as nib
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
import summarize_katie_randomise as summary


class SummarizeMaps(unittest.TestCase):
    def setUp(self):
        self.job = dict(key="social_specific/adi/z-2p6", outcome="social_specific", model="adi",
                        z=2.6, t_cutoff=2.65785388280732)
        self.affine = np.diag([2., 3., 4., 1.])
        self.mask = nib.Nifti1Image(np.ones((4, 4, 4), dtype=np.uint8), self.affine)

    def image(self, values):
        return nib.Nifti1Image(np.asarray(values, dtype=float), self.affine)

    def test_null_and_exact_boundary_are_not_significant(self):
        p = np.zeros((4, 4, 4))
        p[0, 0, 0] = .95
        row, clusters = summary.map_summary(self.job, "positive", self.image(p), self.image(p), self.mask)
        self.assertEqual(row["significant_voxels"], 0)
        self.assertEqual(clusters, [])
        self.assertAlmostEqual(row["min_cluster_fwe_p"], .05)

    def test_corrected_maps_not_raw_t_drive_significance_and_peak_world(self):
        t = np.zeros((4, 4, 4))
        p = t.copy()
        p[0, 0, 0] = p[1, 1, 1] = .99
        p[3, 3, 3] = .98
        t[1, 1, 1], t[3, 3, 3], t[0, 0, 3] = 7., 4., 100.
        row, clusters = summary.map_summary(self.job, "negative", self.image(t), self.image(p), self.mask)
        self.assertEqual(row["significant_voxels"], 3)
        self.assertEqual(row["significant_clusters"], 2)
        self.assertEqual(clusters[0]["voxels"], 2)
        self.assertAlmostEqual(clusters[0]["volume_mm3"], 48.)
        self.assertEqual([clusters[0][f"peak_{a}_mm"] for a in "xyz"], [2., 3., 4.])
        self.assertEqual(clusters[0]["direction"], "negative")
        self.assertEqual(clusters[0]["peak_contrast_t"], 7.)

    def test_outside_mask_never_included(self):
        mask = np.ones((4, 4, 4), dtype=np.uint8)
        mask[0, 0, 0] = 0
        p = np.zeros(mask.shape)
        p[0, 0, 0] = 1
        row, _ = summary.map_summary(self.job, "positive", self.image(p), self.image(p),
                                     nib.Nifti1Image(mask, self.affine))
        self.assertEqual(row["significant_voxels"], 0)
        self.assertEqual(row["min_cluster_fwe_p"], 1.)

    def test_invalid_probabilities_and_grid_rejected(self):
        values = np.zeros((4, 4, 4))
        values[0, 0, 0] = 1.01
        with self.assertRaisesRegex(ValueError, "Invalid"):
            summary.map_summary(self.job, "positive", self.image(values), self.image(values), self.mask)
        with self.assertRaisesRegex(ValueError, "grid mismatch"):
            summary.map_summary(self.job, "positive", self.image(np.zeros((3, 3, 3))),
                                self.image(np.zeros((3, 3, 3))), self.mask)

    def test_empty_cluster_table_has_headers(self):
        row, clusters = summary.map_summary(self.job, "positive", self.image(np.zeros((4, 4, 4))),
                                             self.image(np.zeros((4, 4, 4))), self.mask)
        files = summary.report_files([row], clusters, {"n": 97})
        self.assertEqual(len(files["clusters.tsv"].splitlines()), 1)
        self.assertIn("peak_x_mm", files["clusters.tsv"])
        self.assertIn("0 | 0", files["README.md"])

    def test_complete_48_map_summary_receipts_and_corruption(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mask_path = root / "mask.nii.gz"
            nib.save(self.mask, mask_path)
            jobs = [dict(self.job, key=f"outcome/model{index}/z-2p6") for index in range(24)]
            plan = dict(n=97, jobs=jobs, outputs={}, sources=[], mask=str(mask_path))
            (root / "plan.json").write_text(json.dumps(plan))
            digest = summary.runner.cohort.digest(root / "plan.json")
            (root / "plan.sha256").write_text(digest)
            image = self.image(np.zeros((4, 4, 4)))
            for job in jobs:
                folder = root / "jobs" / job["key"]
                folder.mkdir(parents=True)
                prefix = folder / "randomise"
                for i in (1, 2):
                    nib.save(image, str(prefix) + f"_tstat{i}.nii.gz")
                    nib.save(image, str(prefix) + f"_clustere_corrp_tstat{i}.nii.gz")
                products = summary.runner.output_images(prefix, str(mask_path))
                (folder / "success.json").write_text(json.dumps(dict(plan_sha256=digest, job=job,
                                                                      smoke=False, outputs=products, attempt=str(folder))))
            maps, clusters, provenance = summary.summarize(root)
            self.assertEqual((len(maps), len(clusters), provenance["n"]), (48, 0, 97))
            self.assertEqual(len(provenance["receipts"]), 24)
            bad = root / "jobs" / jobs[0]["key"] / "randomise_tstat1.nii.gz"
            bad.write_bytes(b"corruption")
            with self.assertRaisesRegex(ValueError, "Frozen input changed"):
                summary.summarize(root)

    def test_existing_report_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            report = folder / "README.md"
            report.write_text("existing report")
            with patch.object(sys, "argv", ["summary", "--report", str(folder)]), \
                    patch.object(summary, "summarize", return_value=([{}], [], {})), \
                    patch.object(summary, "report_files", return_value={"README.md": "changed"}):
                with self.assertRaisesRegex(ValueError, "Existing report differs"):
                    summary.main()
            self.assertEqual(report.read_text(), "existing report")


if __name__ == "__main__":
    unittest.main()
