import importlib.util
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
import build_fevs_results_pdf as brief


class ResultsBrief(unittest.TestCase):
    def test_published_evidence_and_fixed_behavioral_result(self):
        target = brief.verify_sources()
        self.assertEqual(int(target["n"]), 97)
        self.assertAlmostEqual(float(target["interaction_beta"]), -.802238003563228)
        self.assertAlmostEqual(float(target["hc3_p"]), .00016818263194417406)

    def test_conditional_curves_are_existing_outputs_not_new_fits(self):
        curves = brief.rows(brief.ROOT / "results/review/behavioral-moderation-provisional-v1/conditional_slopes.tsv")
        rows = [r for r in curves if r["model"] == "fevs_pm25_mspss"]
        self.assertEqual(len(rows), 101)
        self.assertTrue(all(float(r["ci_lower"]) <= float(r["conditional_exposure_slope"]) <= float(r["ci_upper"]) for r in rows))

    @unittest.skipUnless(importlib.util.find_spec("pypdf"), "PDF layout check requires the bundled PDF runtime")
    def test_delivered_pdf_pages_labels_and_no_participant_ids(self):
        from pypdf import PdfReader
        path = brief.ROOT / "output/pdf/FEVS_Main_Results_2026-11-03.pdf"
        reader = PdfReader(path)
        self.assertEqual(len(reader.pages), 4)
        texts = [p.extract_text() for p in reader.pages]
        for text in texts:
            self.assertIn("PRELIMINARY", text)
            self.assertIn("N=97", text)
        self.assertIn("0.000168", texts[0])
        self.assertIn("0.0411", texts[1])
        self.assertIn("0.0303", texts[2])
        self.assertIn("no matching corrected neural", texts[3])
        for subject in ("11120", "11461", "11679", "11853", "11914"):
            self.assertNotIn(subject, "\n".join(texts))


if __name__ == "__main__":
    unittest.main()
