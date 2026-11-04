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
    def test_question_driven_sections_begin_with_behavior_and_keep_all_figures(self):
        from pypdf import PdfReader
        reader = PdfReader(brief.OUTPUT)
        self.assertEqual(len(reader.pages), 13)
        texts = [" ".join(p.extract_text().split()) for p in reader.pages]
        for text in texts:
            for label in ("Context", "Content", "Conclusion", "N=97", "PRELIMINARY"):
                self.assertIn(label, text)
        self.assertIn("1. Behavior", texts[0])
        self.assertIn("Does perceived support modify", texts[0])
        self.assertIn("0.001313", texts[0])
        self.assertIn("scoring-corrected", texts[0])
        self.assertIn("NIH EXAMINER/TabCAT", texts[1])
        self.assertIn("0.0021", texts[3])
        self.assertIn("0.0011", texts[3])
        self.assertIn("Do wins elicit the expected striatal response?", texts[2])
        self.assertIn("11.79", texts[2])
        self.assertIn("11.70", texts[2])
        self.assertIn("66.63 [53.24, 80.02]", texts[2])
        for text in texts[5:11]:
            self.assertIn("exact model-adjusted scatter", text)
            self.assertIn("descriptive only", text)
            self.assertIn("not across the exploratory model family", text)
        self.assertIn("0.0505", texts[8])
        self.assertIn("0.0353", texts[10])
        self.assertIn("not native FEAT screenshots", texts[11])
        self.assertIn("unmodified native FEAT screenshots", texts[12])
        self.assertNotIn("awaiting evidence publication", " ".join(texts).lower())
        self.assertIn("not demonstrated", " ".join(texts).replace("do not demonstrate", "not demonstrated"))
        for subject in ("11120", "11461", "11679", "11853", "11914"):
            self.assertNotIn(subject, " ".join(texts))
        record = json.loads(brief.OUTPUT.with_suffix(".provenance.json").read_text())
        self.assertEqual(record["sections"], list(brief.SECTIONS))
        self.assertEqual([r["section"] for r in record["pages"]],
                         [brief.SECTIONS[0]]*2 + [brief.SECTIONS[1]]*3 + [brief.SECTIONS[2]]*4 +
                         [brief.SECTIONS[3]]*2 + [brief.SECTIONS[4]]*2)
        for text, page in zip(texts, record["pages"]):
            self.assertTrue(page["question"].endswith("?"))
            self.assertIn(page["question"], text)
        self.assertEqual(sum(len(page.images) for page in reader.pages[:2]), 2)
        self.assertEqual([item.title for item in reader.outline if not isinstance(item, list)], list(brief.SECTIONS))
        self.assertEqual(sum(len(item) for item in reader.outline if isinstance(item, list)), 13)

    def test_pdf_provenance_preserves_cohort_and_no_new_analysis(self):
        record = json.loads(brief.OUTPUT.with_suffix(".provenance.json").read_text())
        self.assertEqual(record["n"], 97)
        self.assertFalse(record["exclusions_changed"])
        self.assertFalse(record["new_analysis"])
        self.assertFalse(record["unpublished_evidence_batch"])
        self.assertEqual(record["evidence_publication"], "11ab6e6")
        self.assertEqual(record["pdf_sha256"], brief.old.digest(brief.OUTPUT))
        self.assertEqual(record["builder_sha256"], brief.old.digest(Path(brief.__file__)))
        self.assertIn("data/derived/financial-model-review-v1/correlations.tsv", record["inputs"])
        self.assertEqual(len(record["derived_figures"]["correlation_figure_sha256"]), 64)

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
