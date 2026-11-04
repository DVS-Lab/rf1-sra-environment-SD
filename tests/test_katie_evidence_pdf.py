import importlib.util
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
import build_katie_evidence_pdf as brief


class EvidenceBrief(unittest.TestCase):
    def test_original_brain_and_scatter_assets_are_verified_together(self):
        sources = brief.verified_inputs()
        for folder, brain, scatter in (
            ("fevs-win-v1", "fevs-brain.png", "fevs-cluster-1-scatter.png"),
            ("fevs-win-v1", "fevsxpm25-brain.png", "fevsxpm25-cluster-1-scatter.png"),
            ("fevs-vs-v1", "fevs-vs-cluster-1-brain.png", "fevs-vs-cluster-1-scatter.png"),
        ):
            self.assertIn(f"results/review/{folder}/{brain}", sources)
            self.assertIn(f"results/review/{folder}/{scatter}", sources)

    @unittest.skipUnless(importlib.util.find_spec("nibabel"), "Scientific runtime required")
    def test_design_matches_executed_matrix_and_contrast_hashes(self):
        import numpy as np
        names, x, c, checks = brief.executed_design()
        self.assertEqual(x.shape, (97, 8))
        self.assertEqual(names[-1], "fevs")
        self.assertTrue(np.all(c[:, 0] == 0))
        self.assertEqual(c[:, -1].tolist(), [1, -1])
        self.assertEqual(checks["mat"], "f86c5c487df2196eef16f2627326f9899db469711f6c3e088ec1210589f06f37")

    @unittest.skipUnless(importlib.util.find_spec("pypdf"), "PDF runtime required")
    def test_twelve_pages_context_content_conclusion_and_completed_evidence(self):
        from pypdf import PdfReader
        reader = PdfReader(brief.OUTPUT)
        self.assertEqual(len(reader.pages), 12)
        texts = [" ".join(p.extract_text().split()) for p in reader.pages]
        for text in texts:
            for label in ("Context", "Content", "Conclusion", "N=97", "PRELIMINARY"):
                self.assertIn(label, text)
        self.assertIn("0.0021", texts[1])
        self.assertIn("0.0011", texts[1])
        self.assertIn("Expected Striatal Activation Is Present", texts[0])
        self.assertIn("11.79", texts[2])
        self.assertIn("11.70", texts[2])
        self.assertIn("66.63 [53.24, 80.02]", texts[2])
        for text in texts[3:9]:
            self.assertIn("exact model-adjusted scatter", text)
            self.assertIn("descriptive only", text)
            self.assertIn("not across the exploratory model family", text)
        self.assertIn("0.0505", texts[6])
        self.assertIn("0.0353", texts[8])
        self.assertIn("scoring-corrected", texts[9])
        self.assertIn("not native FEAT screenshots", texts[10])
        self.assertIn("unmodified native FEAT screenshots", texts[11])
        self.assertNotIn("awaiting evidence publication", " ".join(texts).lower())
        self.assertIn("not demonstrated", " ".join(texts).replace("do not demonstrate", "not demonstrated"))
        for subject in ("11120", "11461", "11679", "11853", "11914"):
            self.assertNotIn(subject, " ".join(texts))

    def test_pdf_provenance_preserves_cohort_and_no_new_analysis(self):
        record = json.loads(brief.OUTPUT.with_suffix(".provenance.json").read_text())
        self.assertEqual(record["n"], 97)
        self.assertFalse(record["exclusions_changed"])
        self.assertFalse(record["new_analysis"])
        self.assertFalse(record["unpublished_evidence_batch"])
        self.assertEqual(record["evidence_publication"], "11ab6e6")
        self.assertEqual(record["pdf_sha256"], brief.old.digest(brief.OUTPUT))
        self.assertEqual(record["builder_sha256"], brief.old.digest(Path(brief.__file__)))

    def test_striatal_response_is_confirmed_separately_in_each_task(self):
        peaks, roi = brief.striatal_task_check()
        self.assertEqual(len(peaks), 6)
        self.assertTrue(all(r["t"] > 7.5 and r["cluster_p"] < .001 for r in peaks))
        for outcome in ("socialdoors", "doors", "average"):
            self.assertGreater(float(roi[outcome]["descriptive_ci_lower"]), 0)
        self.assertLess(float(roi["social_specific"]["descriptive_ci_lower"]), 0)
        self.assertGreater(float(roi["social_specific"]["descriptive_ci_upper"]), 0)


if __name__ == "__main__":
    unittest.main()
