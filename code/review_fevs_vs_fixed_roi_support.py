#!/usr/bin/env python3
"""Read-only original frontal ROI: compare original and additive corrected-support fits."""
from __future__ import annotations
import argparse
import fcntl
import json
import os
from pathlib import Path
import tempfile
import nibabel as nib
import numpy as np
import statsmodels.api as sm
import review_katie_closeout as review

ROOT=Path(__file__).resolve().parents[1]
NAME='fevs-vs-fixed-roi-mspss-v1'
base=review.base
extension=review.extension


def validate_models(names,x,adjusted_names,adjusted,support):
    expected=review.previous.COMMON+['fevs','pm25','fevsxpm25']
    if (names!=expected or adjusted_names!=expected+['mspss'] or x.shape!=(97,10) or adjusted.shape!=(97,11)
            or not np.array_equal(x,adjusted[:,:10]) or np.linalg.matrix_rank(x)!=10
            or np.linalg.matrix_rank(adjusted)!=11 or not np.isfinite(support).all()
            or support.shape!=(97,) or np.any((support<1)|(support>7))
            or not np.allclose(adjusted[:,-1],support-support.mean(),rtol=0,atol=1e-10)):
        raise ValueError('Only one centered corrected-MSPSS column may be added; same full-rank N=97 required')


def coefficient(x,y,names,label):
    if x.shape[0]!=97 or y.shape!=(97,) or not np.isfinite(x).all() or not np.isfinite(y).all() or np.linalg.matrix_rank(x)!=x.shape[1]:
        raise ValueError('Finite full-rank N=97 required; no rows dropped')
    ordinary=sm.OLS(y,x).fit();robust=ordinary.get_robustcov_results(cov_type='HC3',use_t=True)
    i=names.index('fevs');ci=robust.conf_int()[i]
    return dict(model=label,n=97,rank=x.shape[1],residual_df=int(ordinary.df_resid),beta=float(ordinary.params[i]),
        hc3_se=float(robust.bse[i]),hc3_lower=float(ci[0]),hc3_upper=float(ci[1]),hc3_ci_width=float(ci[1]-ci[0]),
        hc3_t=float(robust.tvalues[i]),ols_se=float(ordinary.bse[i]),ols_t=float(ordinary.tvalues[i]),
        selected_cluster_descriptive=True,exclusions_changed=False)


def compare(original,adjusted):
    ratio=abs(adjusted['beta'])/abs(original['beta'])
    se_ratio=adjusted['hc3_se']/original['hc3_se']
    return dict(beta_change=adjusted['beta']-original['beta'],beta_magnitude_ratio=ratio,
        magnitude_reduction_percent=100*(1-ratio),hc3_se_ratio=se_ratio,hc3_se_change_percent=100*(se_ratio-1),
        hc3_ci_width_ratio=adjusted['hc3_ci_width']/original['hc3_ci_width'],
        absolute_hc3_t_ratio=abs(adjusted['hc3_t'])/abs(original['hc3_t']),
        ols_se_ratio=adjusted['ols_se']/original['ols_se'],sign_changed=bool(np.sign(original['beta'])!=np.sign(adjusted['beta'])),
        caution='Selected original region; descriptive comparison. Regional coefficient/SE changes do not fully explain voxelwise cluster extent, permutation correction, or whole-brain p changes.')


def check(project):
    root=project/'work'/NAME;report=root/'report';manifest=json.loads((report/'review_manifest.json').read_text())
    if manifest['n']!=97 or manifest['code_sha256']!=base.cohort.digest(Path(__file__)):
        raise ValueError('Frozen extraction code/cohort differs')
    for name,sha in manifest['outputs'].items():
        if Path(name).name!=name or base.cohort.digest(report/name)!=sha:raise ValueError('Sealed report changed')
    private=json.loads((root/'inputs-private.json').read_text())
    extension.audit.verify_records({r['path']:r for r in private['sources']},12)
    print('CHECK PASSED: original 44-voxel region, same N=97/images/order, original columns unchanged; no permutations run.',flush=True)


def build(project):
    root=project/'work'/NAME;report=root/'report';root.mkdir(parents=True,exist_ok=True)
    if (report/'review_manifest.json').exists():check(project);return
    if report.exists():raise ValueError('Unsealed report exists; preserve it and diagnose before retrying')
    records={};original_folder=project/'derivatives/fsl/randomise/katie-reward-extension-v1'
    adjusted_folder=project/'derivatives/fsl/randomise'/review.sensitivity.VERSION
    original=review.plan_and_receipts(original_folder,records,all_jobs=False)
    adjusted=review.plan_and_receipts(adjusted_folder,records,all_jobs=False)
    ids,values=review.previous.behavior.inputs(ROOT)
    values['mspss']=review.correction.corrected_scores(ROOT,ids,values['mspss'])
    for folder in (original_folder,adjusted_folder):
        _,roster=base.cohort.read_table(folder/'subjects.tsv')
        if [r['subject'] for r in roster]!=ids:raise ValueError('Frozen cohort/image order differs')
    job=next(j for j in original['jobs'] if j['key']==review.sensitivity.BASE_KEY+'z-3p1')
    adjusted_job=next(j for j in adjusted['jobs'] if float(j['z'])==3.1)
    if (adjusted_job['key']!='connectivity/social_specific/fevsxpm25_add_mspss/z-3p1'
            or adjusted['images']!={'connectivity/social_specific':original['images']['connectivity/social_specific']}
            or adjusted['masks']!={'connectivity':original['masks']['connectivity']}):
        raise ValueError('Completed adjusted outcome/images/mask differ')
    _,evidence=review.previous.completed(adjusted,adjusted_job,adjusted_folder)
    for r in evidence:extension.audit.add_record(records,r['path'],r['sha256'],r['size'])
    names,x=review.checked_design(job,ids,values)
    adjusted_names,adjusted_x=review.checked_design(adjusted_job,ids,values)
    validate_models(names,x,adjusted_names,adjusted_x,values['mspss'])
    ref,stat,p,selected=review.selection(original,original_folder,job,'fevs','negative',records)
    if int(selected.sum())!=44 or not np.isclose(1-p[selected].max(),.0303,atol=1e-6):
        raise ValueError('Original fixed 44-voxel frontal region differs')
    source=Path(original['images']['connectivity/social_specific']);review.add(records,source)
    image=nib.load(source);base.grid(ref,image,4)
    if image.shape[3]!=97:raise ValueError('Expected exactly 97 frozen image volumes')
    y=image.get_fdata(dtype=np.float32)[selected,:].mean(axis=0,dtype=np.float64)
    rows=[coefficient(x,y,names,'original'),coefficient(adjusted_x,y,adjusted_names,'add_corrected_mspss')]
    published=ROOT/'results/review/katie-closeout-analysis-v1'
    manifest=json.loads((published/'review_manifest.json').read_text())
    if base.cohort.digest(published/'summary.json')!=manifest['outputs']['summary.json']:raise ValueError('Published baseline summary changed')
    prior=json.loads((published/'summary.json').read_text())['vs_components']['fits']['difference']
    for name in ('beta','hc3_lower','hc3_upper'):
        if not np.isclose(rows[0][name],prior[name],rtol=0,atol=1e-9):raise ValueError('Original ROI estimate does not reproduce published value')
    for path in [published/'summary.json',published/'review_manifest.json',Path(__file__),
                 ROOT/'code/review_katie_closeout.py',ROOT/'code/run_katie_support_sensitivity.py',
                 ROOT/'code/run_fevs_imaging_adjustments.py',ROOT/'code/run_corrected_mspss.py',
                 ROOT/'code/run_behavioral_moderation.py',ROOT/'code/freeze_katie_cohort.py',
                 ROOT/review.correction.SCORES,ROOT/review.correction.PROVENANCE,
                 *[ROOT/p for p in (review.previous.behavior.ROSTER,review.previous.behavior.SCORE_FILE,
                                    review.previous.behavior.VARIABLES,review.previous.behavior.SOURCE_RECEIPT,review.previous.behavior.POLICY)]]:
        review.add(records,path)
    # Hash against recorded native fingerprints before publishing aggregate estimates.
    extension.audit.verify_records(records,12)
    comparison=compare(*rows)
    stage=Path(tempfile.mkdtemp(prefix='.fixed-roi-support-',dir=root));stage.chmod(0o777)
    (stage/'coefficients.tsv').write_text(base.review.tsv(rows))
    result=dict(n=97,roi_voxels=44,roi_selection='Original negative FEVS cluster, CDT3.1, p=.0303; fixed in both models',
        outcome='[Social VS PPI(win-loss)] - [nonsocial VS PPI(win-loss)]',tested_coefficient='FEVS at mean PM2.5',
        model_columns=dict(original=names,add_corrected_mspss=adjusted_names),fits=rows,comparison=comparison,
        confidence_intervals='HC3, t-based, 95%; descriptive selected-region estimates',new_randomise_jobs=0,
        corrected_mspss_sha256=base.cohort.digest(ROOT/review.correction.SCORES),exclusions_changed=False,
        participant_data_published=False,financial_scoring_provisional=True)
    base.write_json(stage/'summary.json',result)
    (stage/'README.md').write_text('# Fixed original frontal region: additive support adjustment\n\n'+
        'The original 44-voxel cluster, image values, 97-person order and first ten model columns are identical in both fits. Only centered corrected Island screener MSPSS is added. No randomise jobs, new regions, exclusions, or component searches. HC3 95% t intervals and OLS/HC3 standard errors are descriptive; the region was selected from the original same-sample FEVS result. Regional changes cannot fully attribute the change in whole-brain cluster-FWE p. Only aggregate coefficients and changes are published.\n\n'+
        '\n'.join(f"- {r['model']}: b={r['beta']:.6f}; HC3 95% CI [{r['hc3_lower']:.6f}, {r['hc3_upper']:.6f}]; HC3 SE={r['hc3_se']:.6f}" for r in rows)+
        f"\n\nMagnitude reduction: {comparison['magnitude_reduction_percent']:.2f}%; HC3 SE change: {comparison['hc3_se_change_percent']:.2f}%. A negative reduction denotes a larger magnitude. The JSON/TSV retain full precision and OLS SEs.\n")
    base.write_json(root/'inputs-private.json',dict(sources=list(records.values())))
    base.write_json(stage/'review_manifest.json',dict(n=97,code_sha256=base.cohort.digest(Path(__file__)),
        outputs={p.name:base.cohort.digest(p) for p in stage.iterdir() if p.is_file()}))
    stage.rename(report);check(project)
    for r in rows:print(f"{r['model']}: b={r['beta']:.6f}; HC3 CI=[{r['hc3_lower']:.6f}, {r['hc3_upper']:.6f}]; HC3 SE={r['hc3_se']:.6f}",flush=True)
    print(f"Magnitude reduction={comparison['magnitude_reduction_percent']:.2f}%; HC3 SE change={comparison['hc3_se_change_percent']:.2f}%",flush=True)


if __name__=='__main__':
    os.umask(0);parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['build','check'])
    parser.add_argument('--project',required=True,type=Path);args=parser.parse_args();project=args.project.resolve()
    root=project/'work'/NAME;root.mkdir(parents=True,exist_ok=True)
    with (root/'.extraction.lock').open('a') as lease:
        fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if args.command=='build':build(project)
        else:check(project)
