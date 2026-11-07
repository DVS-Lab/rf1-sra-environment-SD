from pathlib import Path
import sys
import unittest
import numpy as np
import statsmodels.api as sm
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
import review_fevs_vs_fixed_roi_support as review


class FixedRegionSupport(unittest.TestCase):
    def fixture(self):
        rng=np.random.default_rng(174)
        x=np.column_stack([np.ones(97),rng.normal(size=(97,9))]);support=rng.uniform(1,7,97)
        adjusted=np.column_stack([x,support-support.mean()])
        names=review.review.previous.COMMON+['fevs','pm25','fevsxpm25']
        y=-.11*x[:,7]+.15*adjusted[:,-1]+rng.normal(size=97)
        return x,adjusted,names,support,y

    def test_identical_region_same_rows_and_only_additive_corrected_support(self):
        x,adjusted,names,support,y=self.fixture()
        review.validate_models(names,x,names+['mspss'],adjusted,support)
        changed=adjusted.copy();changed[0,7]+=.1
        with self.assertRaises(ValueError):review.validate_models(names,x,names+['mspss'],changed,support)
        with self.assertRaises(ValueError):review.validate_models(names,x,names+['mspss'],adjusted,support[::-1])
        with self.assertRaises(ValueError):review.coefficient(x,y[:-1],names,'original')

    def test_reported_hc3_interval_and_standard_error_match_same_ols_fit(self):
        x,adjusted,names,support,y=self.fixture()
        for matrix,columns,df in [(x,names,87),(adjusted,names+['mspss'],86)]:
            result=review.coefficient(matrix,y,columns,'test')
            fit=sm.OLS(y,matrix).fit().get_robustcov_results(cov_type='HC3',use_t=True)
            i=columns.index('fevs')
            self.assertEqual(result['n'],97);self.assertEqual(result['residual_df'],df)
            self.assertAlmostEqual(result['hc3_se'],fit.bse[i])
            np.testing.assert_allclose([result['hc3_lower'],result['hc3_upper']],fit.conf_int()[i])

    def test_shrinkage_and_precision_are_separate_quantities(self):
        old=dict(beta=-.11,hc3_se=.02,hc3_ci_width=.08,hc3_t=-5.5,ols_se=.018)
        new=dict(beta=-.08,hc3_se=.025,hc3_ci_width=.10,hc3_t=-3.2,ols_se=.022)
        result=review.compare(old,new)
        self.assertAlmostEqual(result['magnitude_reduction_percent'],100*(1-.08/.11))
        self.assertAlmostEqual(result['hc3_se_change_percent'],25)
        self.assertAlmostEqual(result['absolute_hc3_t_ratio'],result['beta_magnitude_ratio']/result['hc3_se_ratio'])
        self.assertFalse(result['sign_changed'])


if __name__=='__main__':unittest.main()
