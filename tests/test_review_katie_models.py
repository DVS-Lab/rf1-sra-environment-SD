import csv
import io
import json
import os
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
import review_katie_models as review

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UPSTREAM = ROOT.parent / "rf1-sra-linux2-geometry"
if not DEFAULT_UPSTREAM.exists():
    DEFAULT_UPSTREAM = ROOT.parent / "rf1-sra-linux2"
UPSTREAM = Path(os.environ.get("RF1_SRA_UPSTREAM_ROOT", DEFAULT_UPSTREAM))
UG = Path(os.environ.get("RF1_UG_ROOT", ROOT.parent / "rf1-sra-environment-UG"))


class CorrelationTests(unittest.TestCase):
    def test_known_pearson_and_tied_spearman(self):
        r, rho = review.correlations([[1, 4], [2, 3], [2, 3], [4, 1]])
        np.testing.assert_allclose(r, [[1, -1], [-1, 1]])
        np.testing.assert_allclose(rho, [[1, -1], [-1, 1]])

    def test_refuse_missing_or_constant_not_pairwise_drop(self):
        for x in ([[1, 2], [2, np.nan], [3, 4]], [[1, 2], [1, 3], [1, 4]]):
            with self.assertRaisesRegex(ValueError, "complete finite nonconstant"):
                review.correlations(x)


class ModelAdaptation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files, cls.summary = review.generate(UPSTREAM, UG)
        _, variables = review.cohort.read_table(ROOT / "data/derived/katie-cohort-v1/analysis_variables.tsv")
        _, pairs = review.cohort.read_table(ROOT / "data/derived/katie-cohort-v1/selected_pairs.tsv")
        _, era = review.cohort.read_table(UPSTREAM / "qc/scanner_era/run_metrics.tsv")
        cls.ids, cls.raw, cls.terms = review.aligned_terms(variables, pairs, era)
        cls.variables, cls.pairs, cls.era = variables, pairs, era

    def test_six_inherited_models_not_seventh_adi2_or_quadratic(self):
        audit = json.loads(self.files["ug_template_audit.json"])
        self.assertEqual(set(audit["models"]), set(review.MODELS))
        self.assertTrue(audit["adi2_is_byte_identical_duplicate"])
        for name, data in audit["models"].items():
            self.assertEqual(data["columns"][:7], review.BASE_TITLES)
            self.assertEqual(data["rank"], len(data["columns"]))

    def test_inherited_main_effect_hierarchy_and_product(self):
        for mode in review.QC_OPTIONS:
            for model, (exposure, moderator) in review.MODELS.items():
                names, x, contrasts, info = review.model_preview(self.terms, model, mode)
                if moderator:
                    self.assertIn(exposure, names)
                    self.assertIn(moderator, names)
                    np.testing.assert_array_equal(x[:, -1], self.terms[exposure] * self.terms[moderator])
                self.assertEqual(info["rank"], len(names))
                self.assertEqual(info["residual_dof"], 97 - len(names))
                self.assertEqual(contrasts[0][info["scientific_target"]], 1)
                self.assertEqual(contrasts[1][info["scientific_target"]], -1)
                self.assertNotIn("female", names)
                self.assertFalse(info["approved_for_execution"])

    def test_actual_correlations_and_no_missing_rows(self):
        rows = list(csv.DictReader(io.StringIO(self.files["correlations.tsv"]), delimiter="\t"))
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(r["n"] == "97" for r in rows))
        self.assertAlmostEqual(float(rows[0]["pearson_r"]), 0.06195177, places=6)
        self.assertAlmostEqual(float(rows[0]["spearman_rho"]), 0.188459, places=6)
        self.assertTrue(all(abs(float(r["pearson_r"])) < 0.25 for r in rows))

    def test_no_changed_cohort_and_all_design_orders_match(self):
        _, expected = review.cohort.read_table(ROOT / "data/derived/katie-cohort-v1/subjects.tsv")
        ids = [r["subject"] for r in expected]
        for name, contents in self.files.items():
            if name.endswith("design.tsv"):
                actual = list(csv.DictReader(io.StringIO(contents), delimiter="\t"))
                self.assertEqual([r["subject"] for r in actual], ids)
        self.assertEqual(self.summary["new_exclusions"], 0)

    def test_era_counts_and_single_gender_indicator(self):
        self.assertEqual(self.summary["scanner_era_counts"], {"E11": 25, "XA30": 5, "XA60": 67})
        for name in ("age", "gender_code1", "adi", "pm25", "mspss", "ecog", "e11", "xa30", "delta_fd", "pair_mean_fd"):
            self.assertAlmostEqual(float(self.terms[name].mean()), 0, places=10)
        self.assertNotIn("female", self.terms)

    def test_refuse_unknown_or_conflicting_era(self):
        era = [dict(r) for r in self.era]
        row = next(r for r in era if r["subject"] == self.ids[0] and r["task"] == "doors" and r["session"] == "01")
        row["software_era"] = "UNKNOWN"
        with self.assertRaisesRegex(ValueError, "matching scanner era"):
            review.aligned_terms(self.variables, self.pairs, era)

    def test_secondary_mean_is_not_selected_based_on_primary_p(self):
        catalog = json.loads(self.files["model_catalog.json"])
        self.assertEqual(catalog["outcomes"]["primary"], "(Social_win-loss)-(Doors_win-loss)")
        self.assertEqual(catalog["outcomes"]["secondary"], "((Social_win-loss)+(Doors_win-loss))/2")
        self.assertEqual(catalog["secondary_selection"], "run_and_report_as_secondary_not_only_when_primary_is_null")
        self.assertFalse(catalog["randomise_run"])
        self.assertFalse(catalog["qc_option_approved"])
        self.assertFalse(any(name.endswith((".mat", ".con", ".fsf", ".nii.gz")) for name in self.files))

    def test_identical_rebuild_and_hashes(self):
        expected, _ = review.generate(UPSTREAM, UG)
        self.assertEqual(self.files, expected)
        provenance = json.loads(self.files["provenance.json"])
        self.assertNotIn("/Users/", self.files["provenance.json"])
        for name, digest in provenance["outputs"].items():
            self.assertEqual(review.hashlib.sha256(self.files[name].encode()).hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()
