#!/usr/bin/env python3
"""Two authorized VS-PPI jobs: add corrected screener MSPSS to FEVS x PM2.5."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import fcntl
import json
import os
from pathlib import Path
import signal
import tempfile
from types import SimpleNamespace
import nibabel as nib
import numpy as np
from scipy.stats import norm, t
import run_fevs_imaging_adjustments as previous
import run_corrected_mspss as correction

extension = previous.extension
base = extension.base
ROOT = Path(__file__).resolve().parents[1]
VERSION = 'katie-vs-fevs-support-sensitivity-v1'
BASE_KEY = 'connectivity/social_specific/fevsxpm25/'
AUTHORIZATION = 'config/katie_results_closeout_v1.json'


def design(source, ids, values, corrected):
    names = previous.COMMON + ['fevs', 'pm25', 'fevsxpm25']
    fields, rows = base.cohort.read_table(Path(source['design']).with_suffix('.tsv'))
    x = extension.audit.matrix(source['design'])
    if (fields != ['subject', *names] or [r['subject'] for r in rows] != ids
            or len(ids) != 97 or len(set(ids)) != 97 or x.shape != (97, 10)
            or not np.allclose(x, [[float(r[n]) for n in names] for r in rows], rtol=0, atol=1e-12)
            or not np.array_equal(x[:, 0], np.ones(97))):
        raise ValueError('Original FEVS/PM2.5 design or frozen order differs')
    for n in ('fevs', 'pm25', 'age', 'gender_code1'):
        if not np.allclose(x[:, names.index(n)], values[n]-values[n].mean(), rtol=0, atol=1e-10):
            raise ValueError('Baseline centered values differ: '+n)
    if not np.allclose(x[:, -1], x[:, 7]*x[:, 8], rtol=0, atol=1e-10):
        raise ValueError('Original FEVS x PM2.5 interaction differs')
    corrected = np.asarray(corrected)
    if corrected.shape != (97,) or not np.isfinite(corrected).all() or np.any((corrected < 1)|(corrected > 7)):
        raise ValueError('Expected corrected support means, 1..7, for all 97')
    adjusted = np.column_stack([x, corrected-corrected.mean()])
    if not np.array_equal(adjusted[:, :10], x) or np.linalg.matrix_rank(adjusted) != 11:
        raise ValueError('Only one additive support column is authorized; full-rank N=97 required')
    return names+['mspss'], adjusted


def specification(output, original, ids, values, corrected):
    files = {'subjects.tsv':base.review.tsv([dict(subject=s) for s in ids])}
    jobs, baselines = [], []
    for z in (2.6, 3.1):
        candidates = [j for j in original['jobs'] if j['key'] == BASE_KEY+'z-'+str(z).replace('.','p')]
        if len(candidates) != 1:
            raise ValueError('Exactly one completed VS domain-by-valence FEVS/PM2.5 baseline required')
        source = candidates[0]
        names, x = design(source, ids, values, corrected)
        definitions = [d for d in source['contrasts'] if d['term']=='fevs']
        if [d['direction'] for d in definitions] != ['positive','negative']:
            raise ValueError('Both baseline FEVS main-coefficient directions required')
        baselines.append(dict(job=source, definitions=definitions))
        files['design.mat'] = base.vest_matrix(x)
        files['design.tsv'] = base.review.tsv([dict(subject=s, **dict(zip(names,r))) for s,r in zip(ids,x)])
        contrast, definitions = extension.contrast_text(names,['fevs'])
        files['design.con'] = contrast
        jobs.append(dict(key='connectivity/social_specific/fevsxpm25_add_mspss/z-'+str(z).replace('.','p'),
            family='connectivity', outcome='connectivity/social_specific', model='fevsxpm25_add_mspss',
            z=z, residual_dof=86, t_cutoff=float(t.isf(norm.sf(z),86)), permutations=10000,
            seed=20261101, design=str(output/'design.mat'), contrast=str(output/'design.con'),
            contrasts=definitions, columns=names))
    if len(jobs)!=2 or any(len(j['contrasts'])!=2 for j in jobs):
        raise ValueError('Only two scientific jobs / four directional maps authorized')
    return files,jobs,baselines


def context(project):
    authorized=json.loads((ROOT/AUTHORIZATION).read_text())
    expected=dict(n=97,new_scientific_jobs=2,new_directional_maps=4,outcome='connectivity/social_specific',tested_coefficient='fevs',retained_model=['fevs','pm25','fevsxpm25'],additive_covariate='corrected_island_screener_mspss',new_interactions=False,permutations=10000,seed=20261101,cluster_forming_z=[2.6,3.1],exclusions_changed=False,financial_score_modifications=False,manuscript_results_drafting=False)
    if any(authorized.get(k)!=v for k,v in expected.items()):raise ValueError('Closeout authorization snapshot differs')
    folder,original = correction.original_plan(project)
    ids,values = previous.behavior.inputs(ROOT)
    corrected = correction.corrected_scores(ROOT,ids,values['mspss'])
    _,order = base.cohort.read_table(folder/'subjects.tsv')
    if [r['subject'] for r in order]!=ids:
        raise ValueError('Frozen source image-volume order differs')
    return folder,original,ids,values,corrected


def build(args):
    if (args.output/'plan.json').exists():
        return check(args)
    if args.output.exists():
        raise ValueError('Unrecognized sensitivity output exists; nothing overwritten')
    folder,original,ids,values,corrected = context(args.project)
    files,jobs,baselines = specification(args.output,original,ids,values,corrected)
    records = {r['path']:r for r in original['sources']}
    paths = [folder/'plan.json',folder/'plan.sha256',folder/'subjects.tsv',Path(__file__),
             Path(previous.__file__),Path(correction.__file__),Path(extension.__file__),Path(base.__file__),
             Path(previous.behavior.__file__),Path(previous.summary.__file__)]
    paths += [ROOT/AUTHORIZATION]
    paths += [ROOT/p for p in (correction.SCORES,correction.PROVENANCE,previous.behavior.ROSTER,
                               previous.behavior.SCORE_FILE,previous.behavior.VARIABLES,
                               previous.behavior.SOURCE_RECEIPT,previous.behavior.POLICY)]
    for item in baselines:
        _,evidence = previous.completed(original,item['job'],folder)
        for r in evidence:extension.audit.add_record(records,r['path'],r['sha256'],r['size'])
        paths += [Path(item['job']['design']),Path(item['job']['design']).with_suffix('.tsv'),Path(item['job']['contrast'])]
    paths += [Path(original['images']['connectivity/social_specific']),Path(original['masks']['connectivity']),Path(original['randomise'])]
    for path in paths:
        r=base.fingerprint(path);extension.audit.add_record(records,r['path'],r['sha256'],r['size'])
    sources = previous.normalize_sources(records)
    stage=Path(tempfile.mkdtemp(prefix='.vs-support-sensitivity-',dir=args.output.parent));stage.chmod(0o777)
    for name,text in files.items():(stage/name).write_text(text)
    plan=dict(n=97,project=str(args.project),data_root=str(ROOT),original=str(folder),jobs=jobs,baselines=baselines,
        images={'connectivity/social_specific':original['images']['connectivity/social_specific']},
        masks={'connectivity':original['masks']['connectivity']},randomise=original['randomise'],sources=sources,
        outputs={name:base.cohort.digest(stage/name) for name in files},code_sha256=base.cohort.digest(Path(__file__)),
        exclusions_changed=False,existing_outputs_changed=False,provisional_financial_scoring=True,
        corrected_administration='island_screener',scope='One additive corrected-MSPSS sensitivity; no new interaction')
    base.write_json(stage/'plan.json',plan);(stage/'plan.sha256').write_text(base.cohort.digest(stage/'plan.json')+'\n')
    stage.rename(args.output)
    return check(args)


def check(args):
    plan=base.load_plan(args.output)
    folder,original,ids,values,corrected=context(args.project)
    files,jobs,baselines=specification(args.output,original,ids,values,corrected)
    if (plan['n']!=97 or plan['data_root']!=str(ROOT) or plan['project']!=str(args.project)
            or plan['jobs']!=jobs or plan['baselines']!=baselines or plan['original']!=str(folder)
            or plan['code_sha256']!=base.cohort.digest(Path(__file__))
            or plan['images']!={'connectivity/social_specific':original['images']['connectivity/social_specific']}
            or plan['masks']!={'connectivity':original['masks']['connectivity']}
            or plan['randomise']!=original['randomise'] or plan['exclusions_changed'] or plan['existing_outputs_changed']):
        raise ValueError('Sensitivity identity changed; resume the original frozen release')
    for name,text in files.items():
        if (args.output/name).read_text()!=text or base.cohort.digest(args.output/name)!=plan['outputs'][name]:
            raise ValueError('Frozen design/contrast/order changed')
    reference=nib.load(plan['masks']['connectivity']);image=nib.load(plan['images']['connectivity/social_specific'])
    base.grid(reference,image,4)
    if image.shape[3]!=97 or not np.any(reference.get_fdata()>0):raise ValueError('Expected original mask and 97-volume stack')
    print('CHECK PASSED: two jobs / four maps; df=86; only centered corrected support added; original columns/images/mask/order unchanged.',flush=True)
    return plan


def results(args,plan):
    folder=Path(plan['original']);original=json.loads((folder/'plan.json').read_text())
    maps,clusters,active,evidence=[],[],{},[]
    units=[('baseline',b['job'],b['definitions'],original,folder) for b in plan['baselines']]
    units += [('add_mspss',j,j['contrasts'],plan,args.output) for j in plan['jobs']]
    for adjustment,job,definitions,owner,source in units:
        prefix,records=previous.completed(owner,job,source);evidence.extend(records)
        mask=nib.load(owner['masks']['connectivity']);support=mask.get_fdata()>0
        pos=None
        for definition in definitions:
            i=definition['index'];stat=nib.load(str(prefix)+f'_tstat{i}.nii.gz');prob=nib.load(str(prefix)+f'_clustere_corrp_tstat{i}.nii.gz')
            data=stat.get_fdata();selected=support&(prob.get_fdata()>.95)
            if np.any(data[selected]<job['t_cutoff']-1e-5):raise ValueError('Selected cluster below actual CDT')
            if definition['direction']=='positive':pos=data
            elif pos is None or not np.allclose(data[support],-pos[support],rtol=1e-5,atol=1e-5):raise ValueError('Directional t maps disagree')
            row,found=previous.summary.map_summary(job,definition['direction'],stat,prob,mask)
            maps.append(dict(row,adjustment=adjustment,family='connectivity',term='fevs'))
            clusters.extend(dict(r,adjustment=adjustment,family='connectivity',term='fevs') for r in found)
            active[(adjustment,job['z'],definition['direction'])]=selected
    for row in maps:
        own=active[(row['adjustment'],row['z'],row['direction'])];ref=active[('baseline',row['z'],row['direction'])]
        row['baseline_overlap_voxels']=int((own&ref).sum());total=int(own.sum()+ref.sum())
        row['baseline_dice']=2*int((own&ref).sum())/total if total else ''
    base.verify_sources(plan['sources']);base.verify_sources(evidence)
    report=args.output/'report';report.mkdir(exist_ok=True)
    texts={'maps.tsv':base.review.tsv(maps),'clusters.tsv':base.review.tsv(clusters,[*previous.summary.CLUSTER_FIELDS,'adjustment','family','term']),
        'README.md':'# Corrected Support Adjustment of FEVS VS Connectivity\n\nTwo new jobs / four maps, plus four reused baseline maps. N=97, original images/mask/order/covariates unchanged. FEVS at mean PM2.5 is tested in both signs; corrected MSPSS is additive, not an interaction. 10,000 permutations, seed 20261101, model-specific CDTs 2.6/3.1; df=86 adjusted. Per-map cluster-FWE only. Financial scoring remains provisional. All maps, including nulls, are in maps.tsv.\n',
        'provenance.json':base.cohort.json_text(dict(n=97,new_jobs=2,new_directional_maps=4,baseline_maps_reused=4,
            corrected_mspss_sha256=base.cohort.digest(ROOT/correction.SCORES),plan_sha256=base.cohort.digest(args.output/'plan.json'),
            exclusions_changed=False,existing_outputs_changed=False,provisional_financial_scoring=True))}
    for name,text in texts.items():
        path=report/name
        if path.exists() and path.read_text()!=text:raise ValueError('Existing report differs; refusing overwrite')
        path.write_text(text)
    base.write_json(report/'review_manifest.json',dict(n=97,outputs={name:base.cohort.digest(report/name) for name in texts}))
    print('CHECK PASSED: 2/2 new sensitivity jobs and all eight baseline/adjusted maps verified.',flush=True)


def main():
    os.umask(0);p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['run','check-results']);p.add_argument('--project',type=Path,required=True)
    args=p.parse_args();args.project=args.project.resolve();args.output=args.project/'derivatives/fsl/randomise'/VERSION
    args.output.parent.mkdir(parents=True,exist_ok=True)
    signal.signal(signal.SIGTERM,base.stop);signal.signal(signal.SIGINT,base.stop)
    with (args.output.parent/('.'+VERSION+'.lock')).open('a') as lease:
        fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB);base.LEASE_FD=lease.fileno()
        plan=build(args)
        if args.command=='run':
            digest=base.cohort.digest(args.output/'plan.json')
            extension.execute(plan,plan['jobs'][0],args.output/'smoke',digest,smoke=True)
            with ThreadPoolExecutor(max_workers=2) as pool:
                pending={pool.submit(extension.execute,plan,j,args.output/'jobs'/j['key'],digest):j for j in plan['jobs']}
                while pending:
                    done,_=wait(pending,timeout=60,return_when=FIRST_COMPLETED)
                    if not done:print(f'HEARTBEAT pending_or_running={len(pending)}/2',flush=True)
                    for future in done:
                        j=pending.pop(future);result=future.result();print(result+' '+j['key'],flush=True)
                        if result not in ('COMPLETED','REUSED'):raise RuntimeError('Incomplete sensitivity; preserved for resume')
            if base.STOP:raise InterruptedError('Stopped; completed attempts preserved')
        results(args,plan)
        base.write_json(args.output/'status.json',dict(status='complete',validated=True,n=97,jobs=2,new_maps=4))


if __name__=='__main__':main()
