from pathlib import Path
import sys
import unittest

import numpy as np
import statsmodels.api as sm

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
import check_fevs_behavioral_adjustments as adjustment


class AdjustmentChecks(unittest.TestCase):
    def test_fixed_family_sample_sizes_and_hc3_interaction_index(self):
        rng = np.random.default_rng(87)
        values = dict(pm25=rng.uniform(6, 10, 97), mspss=rng.uniform(1, 7, 97),
                      age=rng.uniform(55, 89, 97), gender_code1=np.arange(97) % 2,
                      adi=rng.uniform(1, 100, 97), ecog=rng.uniform(1, 3, 97))
        _, x = adjustment.behavior.design(values, "pm25", "mspss")
        values["fevs"] = 5 - .7 * x[:, 5] + .03 * values["adi"] + rng.normal(size=97)
        rows = adjustment.fit(values)
        self.assertEqual([r["adjustment"] for r in rows], ["baseline", "adi", "ecog", "adi+ecog"])
        self.assertEqual([r["residual_df"] for r in rows], [91, 90, 90, 89])
        self.assertTrue(all(r["n"] == 97 for r in rows))
        full = np.column_stack([x, values["adi"] - values["adi"].mean(), values["ecog"] - values["ecog"].mean()])
        check = sm.OLS(values["fevs"], full).fit().get_robustcov_results(cov_type="HC3", use_t=True)
        self.assertAlmostEqual(rows[-1]["interaction_beta"], check.params[5])
        self.assertAlmostEqual(rows[-1]["hc3_p"], check.pvalues[5])


if __name__ == "__main__":
    unittest.main()
