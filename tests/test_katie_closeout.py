from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import statsmodels.api as sm
from scipy.stats import norm,t
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
import run_katie_support_sensitivity as runner
import review_katie_closeout as review


class Closeout(unittest.TestCase):
    def fixture(self,root):
        rng=np.random.default_rng(887);ids=[str(20000+i) for i in range(97)]
        values={name:rng.normal(size=97) for name in ('fevs','pm25','age','gender_code1')}
        values['gender_code1']=(np.arange(97)%2).astype(float)
        names=runner.previous.COMMON+['fevs','pm25','fevsxpm25']
        x=np.column_stack([np.ones(97),rng.normal(size=(97,4)),values['gender_code1']-values['gender_code1'].mean(),values['age']-values['age'].mean(),values['fevs']-values['fevs'].mean(),values['pm25']-values['pm25'].mean(),(values['fevs']-values['fevs'].mean())*(values['pm25']-values['pm25'].mean())])
        path=root/'design.mat';path.write_text(runner.base.vest_matrix(x));path.with_suffix('.tsv').write_text(runner.base.review.tsv([dict(subject=s,**dict(zip(names,row))) for s,row in zip(ids,x)]))
        source=dict(design=str(path),model='fevsxpm25',contrasts=[dict(index=1,term='fevs',direction='positive'),dict(index=2,term='fevs',direction='negative')])
        support=np.linspace(1,7,97)
        return ids,values,names,x,source,support

    def test_only_corrected_additive_support_two_jobs_four_maps(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);ids,values,names,x,source,support=self.fixture(root)
            newnames,newx=runner.design(source,ids,values,support)
            self.assertEqual(newnames,names+['mspss']);np.testing.assert_array_equal(x,newx[:,:10]);np.testing.assert_allclose(newx[:,-1],support-support.mean())
            original={'jobs':[dict(source,key=runner.BASE_KEY+'z-'+str(z).replace('.','p')) for z in (2.6,3.1)]}
            files,jobs,baseline=runner.specification(root/'new',original,ids,values,support)
            self.assertEqual(len(jobs),2);self.assertEqual(sum(len(j['contrasts']) for j in jobs),4)
            self.assertTrue(all(j['residual_dof']==86 and j['permutations']==10000 and j['seed']==20261101 for j in jobs))
            self.assertTrue(all([d['term'] for d in j['contrasts']]==['fevs','fevs'] for j in jobs))
            self.assertAlmostEqual(jobs[1]['t_cutoff'],t.isf(norm.sf(3.1),86))
            with self.assertRaises(ValueError):runner.design(source,ids[::-1],values,support)
            with self.assertRaises(ValueError):runner.design(source,ids,values,np.full(97,5.))

    def test_frozen_corrected_scores_propagate_to_observed_percentiles(self):
        root=Path(review.__file__).resolve().parents[1];ids,values=runner.previous.behavior.inputs(root)
        with patch.object(runner.base.cohort,'digest',runner.previous.behavior.sha):
            corrected=runner.correction.corrected_scores(root,ids,values['mspss'])
        self.assertEqual(np.count_nonzero(abs(corrected-values['mspss'])>1e-7),82)
        values['mspss']=corrected;names,x=runner.previous.behavior.design(values,'pm25','mspss')
        fit=sm.OLS(values['fevs'],x).fit().get_robustcov_results(cov_type='HC3',use_t=True)
        rows,grid,slope,lower,upper=review.conditional(fit,names,'pm25','interaction',corrected)
        self.assertEqual([r['percentile'] for r in rows],[16,50,84]);self.assertTrue(all(r['moderator'] in corrected for r in rows))
        for row in rows:
            v=np.zeros(len(names));v[names.index('pm25')]=1;v[names.index('interaction')]=row['moderator']-corrected.mean()
            expected=fit.t_test(v);self.assertAlmostEqual(row['slope'],float(np.asarray(expected.effect).item()))
            np.testing.assert_allclose([row['hc3_lower'],row['hc3_upper']],expected.conf_int()[0],rtol=0,atol=1e-10)
        self.assertGreaterEqual(grid.min(),1);self.assertLessEqual(grid.max(),7)

    def test_fixed_roi_component_slopes_reconcile_with_same_design(self):
        with tempfile.TemporaryDirectory() as folder:
            ids,values,names,x,source,support=self.fixture(Path(folder))
            rng=np.random.default_rng(61);s=3+.3*x[:,7]+rng.normal(size=97);d=2+.6*x[:,7]+rng.normal(size=97)
            stats=[review.fit_summary(x,y,names,'fevs')[2] for y in (s,d,s-d)]
            self.assertAlmostEqual(stats[0]['beta']-stats[1]['beta'],stats[2]['beta'])
            self.assertTrue(all(r['n']==97 and not r['exclusions_changed'] for r in stats))
            with self.assertRaises(ValueError):review.fit_summary(x,s[:-1],names,'fevs')


if __name__=='__main__':unittest.main()
