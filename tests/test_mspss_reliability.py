import csv
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"code"))
import review_mspss_reliability as audit


class Agreement(unittest.TestCase):
    def test_identical_measurements_have_perfect_absolute_agreement(self):
        x = np.linspace(1, 7, 30)
        a, c = audit.icc(np.column_stack((x, x)))
        self.assertAlmostEqual(float(a), 1)
        self.assertAlmostEqual(float(c), 1)

    def test_constant_offset_keeps_correlation_but_not_absolute_agreement(self):
        x = np.linspace(1, 5, 30)
        result = audit.agreement(x, x+2, bootstrap=500)
        self.assertAlmostEqual(result["pearson_r"], 1)
        self.assertAlmostEqual(result["icc_consistency_single"], 1)
        self.assertLess(result["icc_absolute_single"], .6)
        self.assertAlmostEqual(result["mean_difference_prescan_minus_screener"], 2)

    def test_batched_icc_equals_independent_single_sample_calculation(self):
        rng = np.random.default_rng(91)
        samples = rng.normal(size=(40, 20, 2))
        a, c = audit.icc(samples)
        for i, values in enumerate(samples):
            one_a, one_c = audit.icc(values)
            self.assertAlmostEqual(float(a[i]), float(one_a))
            self.assertAlmostEqual(float(c[i]), float(one_c))

    def test_icc_matches_independent_long_form_anova(self):
        import pandas as pd
        import statsmodels.api as sm
        import statsmodels.formula.api as formula

        rng = np.random.default_rng(30)
        x = rng.normal(size=(25, 1)) + rng.normal(size=(25, 2))*.5 + np.array([0, .3])
        data = pd.DataFrame(dict(subject=np.repeat(np.arange(25), 2),
                                 occasion=np.tile([0, 1], 25), value=x.ravel()))
        table = sm.stats.anova_lm(formula.ols("value ~ C(subject) + C(occasion)", data).fit(), typ=1)
        row, column, residual = [table.loc[k, "mean_sq"] for k in ("C(subject)", "C(occasion)", "Residual")]
        expected = (row-residual)/(row+residual+2*(column-residual)/25)
        self.assertAlmostEqual(float(audit.icc(x)[0]), expected)

    def test_frozen_roster_remains_97_in_repository(self):
        with (audit.ROOT/"data/derived/katie-cohort-v1/subjects.tsv").open() as stream:
            rows = list(csv.DictReader(stream, delimiter="\t"))
        self.assertEqual(len(rows), 97)
        self.assertEqual(len({r["subject"] for r in rows}), 97)

    def test_full_export_keeps_reversed_and_same_day_pairs_in_primary_analysis(self):
        rows = []
        for i in range(12):
            row = {"rf1-id": str(10000+i), "screener_date": "1/1/2025", "fs_date": "2/1/2025"}
            for a, b in audit.SCALES.values():
                row[a], row[b] = str(1+i*.4), str(1.2+i*.35)
            rows.append(row)
        rows[0]["screener_date"] = "3/1/2025"
        rows[1]["screener_date"] = "2/1/2025"
        original = [dict(r) for r in rows]
        result = audit.population_review(rows, bootstrap=200)
        self.assertEqual(result["n"], 12)
        self.assertEqual(result["scales"]["total"]["n"], 12)
        self.assertEqual(result["n_scan_before_screener"], 1)
        self.assertEqual(result["n_same_day"], 1)
        self.assertEqual(result["scan_after_screener_sensitivity"]["n"], 10)
        self.assertEqual(rows, original)


if __name__ == "__main__":
    unittest.main()
