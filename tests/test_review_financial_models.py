import csv
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
import review_financial_models as financial


class FinancialPreviews(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files, cls.catalog = financial.generate()
        _, roster = financial.review.cohort.read_table(financial.ROOT / "data/derived/katie-cohort-v1/subjects.tsv")
        cls.ids = [r["subject"] for r in roster]
        with financial.SCORES.open() as stream:
            cls.rows = list(csv.DictReader(stream))

    def write_scores(self, root, rows):
        path = root / "scores.csv"
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["sub-num", "fevs", "OAFEM"])
            writer.writeheader(); writer.writerows(rows)
        return path

    def test_current_complete_n97_and_zero_scores_preserved(self):
        rows, same = financial.read_scores(financial.SCORES, self.ids)
        self.assertTrue(same)
        self.assertEqual(len(rows), 97)
        self.assertEqual(sum(r["fevs"] == 0 for r in rows), 10)
        self.assertEqual(sum(r["oafem"] == 0 for r in rows), 32)
        self.assertEqual([r["subject"] for r in rows], self.ids)

    def test_reordered_source_is_joined_by_id_not_row_position(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_scores(Path(directory), list(reversed(self.rows)))
            actual, same = financial.read_scores(path, self.ids)
            expected, _ = financial.read_scores(financial.SCORES, self.ids)
            self.assertFalse(same)
            self.assertEqual(actual, expected)

    def test_missing_duplicate_unknown_and_nonfinite_scores_rejected(self):
        for kind in ("missing", "duplicate", "unknown", "nonfinite", "negative"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                rows = [dict(row) for row in self.rows]
                if kind == "missing": rows.pop()
                elif kind == "duplicate": rows[-1] = dict(rows[0])
                elif kind == "unknown": rows[-1]["sub-num"] = "99999"
                elif kind == "nonfinite": rows[0]["fevs"] = "nan"
                elif kind == "negative": rows[0]["OAFEM"] = "-1"
                with self.assertRaises(ValueError):
                    financial.read_scores(self.write_scores(Path(directory), rows), self.ids)

    def test_all_four_models_keep_same_order_score_only_and_approved_qc(self):
        import io
        for name, text in self.files.items():
            if not name.endswith("design.tsv"): continue
            rows = list(csv.DictReader(io.StringIO(text), delimiter="\t"))
            self.assertEqual([r["subject"] for r in rows], self.ids)
            columns = list(rows[0])[1:]
            self.assertEqual(len(columns), 8)
            score = "fevs" if "/fevs/" in name else "oafem"
            self.assertEqual(columns[-1], score)
            self.assertNotIn("adi", columns)
            self.assertNotIn("pm25", columns)
            self.assertNotIn("ecog", columns)
            self.assertNotIn("mspss", columns)
            self.assertEqual(columns[1:3], ["delta_fd", "delta_tsnr"] if "/social_specific/" in name else ["pair_mean_fd", "pair_mean_tsnr"])
            x = np.array([[float(r[c]) for c in columns] for r in rows])
            self.assertEqual(np.linalg.matrix_rank(x), 8)
            np.testing.assert_allclose(x[:, 1:].mean(axis=0), 0, atol=1e-10)

    def test_two_directional_score_contrasts_only_no_interactions_or_launch(self):
        import io
        for name, text in self.files.items():
            if name.endswith("contrasts.tsv"):
                rows = list(csv.DictReader(io.StringIO(text), delimiter="\t"))
                self.assertEqual(len(rows), 2)
                values = np.array([[float(v) for k, v in row.items() if k != "name"] for row in rows])
                np.testing.assert_array_equal(values[0], [0, 0, 0, 0, 0, 0, 0, 1])
                np.testing.assert_array_equal(values[1], -values[0])
        self.assertEqual(self.catalog["status"], "numerical_previews_only_not_launched")
        self.assertEqual(self.catalog["lead_supplemental_score"], "fevs")
        self.assertFalse(self.catalog["exclusions_changed"])
        self.assertFalse(any(name.endswith((".mat", ".con", ".fsf", ".nii.gz")) for name in self.files))

    def test_leverage_is_diagnostic_and_all_97_retained(self):
        import json
        diagnostics = json.loads(self.files["design_diagnostics.json"])
        self.assertEqual(len(diagnostics), 4)
        for row in diagnostics:
            self.assertEqual((row["n"], row["rank"], row["residual_dof"]), (97, 8, 89))
            self.assertTrue(row["leverage_is_not_an_exclusion_rule"])
            self.assertFalse(row["exclusions_made"])

    def test_deterministic_hashes_and_no_absolute_private_paths(self):
        import hashlib
        import json
        again, _ = financial.generate()
        self.assertEqual(again, self.files)
        provenance = json.loads(self.files["provenance.json"])
        for name, digest in provenance["outputs"].items():
            self.assertEqual(hashlib.sha256(self.files[name].encode()).hexdigest(), digest)
        self.assertNotIn("/Users/", self.files["provenance.json"])


if __name__ == "__main__":
    unittest.main()
