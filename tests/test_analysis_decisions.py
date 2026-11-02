import csv
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ApprovedChoices(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = json.loads((ROOT / "config/analysis_decisions.json").read_text())

    def test_cohort_is_the_same_frozen_97(self):
        path = ROOT / self.plan["cohort"]["path"]
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), self.plan["cohort"]["sha256"])
        with path.open() as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual(len(rows), self.plan["cohort"]["n"])
        self.assertEqual(len(rows), 97)
        self.assertEqual(self.plan["cohort"]["settled_exclusions"], "unchanged")

    def test_each_outcome_uses_the_user_approved_qc_preview(self):
        expected = {"social_specific": ("signed_differences", ["delta_fd", "delta_tsnr"]),
                    "average": ("pair_means", ["pair_mean_fd", "pair_mean_tsnr"])}
        for outcome, (mode, terms) in expected.items():
            config = self.plan["outcomes"][outcome]
            self.assertEqual(config["approved_qc_mode"], mode)
            self.assertEqual(config["approved_qc_terms"], terms)
            for model in self.plan["models"]:
                path = ROOT / f"data/derived/model-review-v1/previews/{mode}/{model}/design.tsv"
                with path.open() as handle:
                    reader = csv.DictReader(handle, delimiter="\t")
                    self.assertTrue(all(t in reader.fieldnames for t in terms))
                    self.assertEqual(len(list(reader)), 97)

    def test_approved_inference_is_not_a_claim_that_execution_started(self):
        self.assertEqual(len(self.plan["models"]), 6)
        self.assertEqual(len(self.plan["outcomes"]), 2)
        self.assertEqual(self.plan["inference"]["focal_model_outcome_questions"], 12)
        self.assertEqual(self.plan["inference"]["one_sided_focal_maps_per_cdt"], 24)
        self.assertEqual(self.plan["inference"]["engine"], "randomise")
        self.assertEqual(self.plan["inference"]["method"], "cluster_extent_permutation_FWE")
        self.assertFalse(self.plan["inference"]["palm_allowed"])
        self.assertFalse(self.plan["inference"]["tfce"])
        self.assertTrue(self.plan["execution_authorized"])
        self.assertEqual(self.plan["runtime_status"], "derivatives/fsl/randomise/katie-v1/status.json")

    def test_cluster_thresholds_match_current_design_dof_not_raw_Z(self):
        info = json.loads((ROOT / "data/derived/model-review-v1/preview_diagnostics.json").read_text())
        self.assertEqual({r["residual_dof"] for r in info}, {87, 89})
        inference = self.plan["inference"]
        self.assertEqual(inference["cluster_forming_z"], [2.6, 3.1])
        self.assertEqual(inference["randomise_threshold_argument"], "-c")
        self.assertEqual(inference["randomise_threshold_units"], "t_not_Z")
        reference = {"89": {"2.6": 2.65785388280732, "3.1": 3.194965066415},
                     "87": {"2.6": 2.65921204869935, "3.1": 3.19721001565352}}
        self.assertEqual(inference["verified_t_thresholds"], reference)
        for thresholds in inference["verified_t_thresholds"].values():
            for z, t in thresholds.items():
                self.assertGreater(t, float(z))

    def test_correction_scope_is_honest_and_no_new_exclusions(self):
        inference = self.plan["inference"]
        self.assertEqual(inference["within_map_cluster_fwe_alpha"], 0.05)
        self.assertEqual(inference["correction_across_models_outcomes_directions_cdts"], "none_exploratory")
        self.assertFalse(inference["paper_wide_or_joint_two_sided_FWER_claim"])
        self.assertTrue(inference["cluster_forming_thresholds_reported_together"])


if __name__ == "__main__":
    unittest.main()
