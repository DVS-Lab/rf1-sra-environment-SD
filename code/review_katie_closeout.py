#!/usr/bin/env python3
"""Bounded descriptive closeout: corrected ADI/support, VS components and behavioral slopes."""
from __future__ import annotations
import argparse
import csv
import io
import json
import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np
from scipy.ndimage import label
from scipy.stats import t
import statsmodels.api as sm
import run_katie_support_sensitivity as sensitivity
import select_katie_background as background

base=sensitivity.base
extension=sensitivity.extension
previous=sensitivity.previous
correction=sensitivity.correction
ROOT=Path(__file__).resolve().parents[1]
NAME='katie-results-ready-v1'
CAUTION='Same-sample selected cluster: descriptive only; no participant exclusions'
plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'savefig.facecolor':'white'})


def read(path):
    with Path(path).open(newline='') as f:return list(csv.DictReader(f,delimiter='\t'))


def key(r):
    return (r['family'],r['outcome'].split('/')[-1],r['model'],r['term'],r['direction'],float(r['z']))


def fit_summary(x,y,names,term):
    if x.shape[0]!=97 or y.shape!=(97,) or not np.isfinite(x).all() or not np.isfinite(y).all() or np.linalg.matrix_rank(x)!=x.shape[1]:
        raise ValueError('Finite full-rank N=97 required; no row dropping')
    ordinary=sm.OLS(y,x).fit();robust=ordinary.get_robustcov_results(cov_type='HC3',use_t=True)
    index=names.index(term);ci=robust.conf_int()[index];influence=ordinary.get_influence()
    loo=np.array([sm.OLS(np.delete(y,i),np.delete(x,i,axis=0)).fit().params[index] for i in range(97)])
    info=dict(n=97,term=term,beta=float(robust.params[index]),hc3_lower=float(ci[0]),hc3_upper=float(ci[1]),
        residual_df=int(ordinary.df_resid),max_cooks_d=float(influence.cooks_distance[0].max()),
        max_leverage=float(influence.hat_matrix_diag.max()),n_cooks_above_4_over_n=int((influence.cooks_distance[0]>4/97).sum()),
        loo_beta_min=float(loo.min()),loo_beta_max=float(loo.max()),exclusions_changed=False,selected_cluster_descriptive=True)
    return ordinary,robust,info,loo


def conditional(robust,names,predictor,interaction,moderator):
    moderator=np.asarray(moderator)
    # Nearest empirical percentile guarantees reported levels are observed scores.
    levels=np.quantile(moderator,[.16,.50,.84],method='nearest')
    rows=[]
    for percentile,value in zip((16,50,84),levels):
        vector=np.zeros(len(names));vector[names.index(predictor)]=1;vector[names.index(interaction)]=value-moderator.mean()
        estimate=float(vector@robust.params);se=float(np.sqrt(vector@robust.cov_params()@vector));half=float(t.ppf(.975,robust.df_resid)*se)
        rows.append(dict(percentile=percentile,moderator=float(value),slope=estimate,hc3_lower=estimate-half,hc3_upper=estimate+half,n=97))
    grid=np.linspace(moderator.min(),moderator.max(),201);vectors=np.zeros((len(grid),len(names)))
    vectors[:,names.index(predictor)]=1;vectors[:,names.index(interaction)]=grid-moderator.mean()
    slope=vectors@robust.params;half=t.ppf(.975,robust.df_resid)*np.sqrt(np.einsum('ij,jk,ik->i',vectors,robust.cov_params(),vectors))
    return rows,grid,slope,slope-half,slope+half


def conditional_figure(path,robust,names,predictor,interaction,support,title,selected=False):
    rows,grid,slope,lower,upper=conditional(robust,names,predictor,interaction,support)
    fig,ax=plt.subplots(figsize=(8.8,4.5),layout='constrained')
    ax.fill_between(grid,lower,upper,color='#126a70',alpha=.18,label='HC3 pointwise 95% interval')
    ax.plot(grid,slope,color='#126a70',lw=2,label='Estimated conditional slope');ax.axhline(0,color='#4c565b',lw=.9)
    ax.plot(support,np.full(97,.025),'|',color='#555',alpha=.45,transform=ax.get_xaxis_transform(),label='Observed MSPSS scores')
    for row in rows:ax.plot(row['moderator'],row['slope'],'o',color='#126a70',ms=4)
    ax.set(xlabel='Corrected Island screener MSPSS mean',ylabel=('Selected-cluster activation' if selected else 'FEVS points')+' per '+('ADI unit' if predictor=='adi' else 'PM2.5 unit'),title=title)
    ax.legend(frameon=False,fontsize=8,loc='best')
    fig.supxlabel(CAUTION if selected else 'N=97; age/gender adjusted; financial scoring provisional; intervals are not simultaneous',fontsize=8)
    fig.savefig(path,dpi=220);plt.close(fig)
    return rows


def add(records,path):
    r=base.fingerprint(Path(path));extension.audit.add_record(records,r['path'],r['sha256'],r['size'])


def plan_and_receipts(folder,records,all_jobs=True):
    plan=json.loads((folder/'plan.json').read_text());digest=base.cohort.digest(folder/'plan.json')
    if (folder/'plan.sha256').read_text().strip()!=digest or plan['n']!=97:raise ValueError('Frozen plan seal/N differs')
    add(records,folder/'plan.json');add(records,folder/'plan.sha256')
    for r in plan['sources']:extension.audit.add_record(records,r['path'],r['sha256'],r.get('size'))
    for name,sha in plan['outputs'].items():extension.audit.add_record(records,folder/name,sha)
    if all_jobs:
        for job in plan['jobs']:
            receipt=folder/'jobs'/job['key']/'success.json';saved=json.loads(receipt.read_text());attempt=Path(saved['attempt'])
            if (not attempt.resolve().is_relative_to((receipt.parent/'attempts').resolve()) or saved['job']!=job
                    or saved['plan_sha256']!=digest or saved['smoke'] is not False
                    or saved['command']!=base.command(dict(plan,mask=plan['masks'][job['family']]),job,attempt/'randomise')):
                raise ValueError('Completed job identity/command differs')
            add(records,receipt)
            for r in saved['outputs']:extension.audit.add_record(records,r['path'],r['sha256'],r['size'])
    return plan


def scientific_catalog(project,report,records):
    original=project/'derivatives/fsl/randomise/katie-reward-extension-v1'
    corrected=project/'derivatives/fsl/randomise/katie-mspss-corrected-v1'
    plan=plan_and_receipts(original,records);corrected_plan=plan_and_receipts(corrected,records)
    if len(plan['jobs'])!=220 or len(plan['coverage'])!=1328 or len(corrected_plan['jobs'])!=64:raise ValueError('Completed scope differs')
    old=read(original/'maps.tsv');new=read(corrected/'report/maps.tsv')
    if len(old)!=1328 or len(new)!=384 or len({key(r) for r in old})!=1328 or len({key(r) for r in new})!=384:
        raise ValueError('Incomplete/duplicate scientific catalog')
    replacements={key(r):r for r in new};old_support=[r for r in old if 'mspss' in r['model']]
    if {key(r) for r in old_support}!=set(replacements):raise ValueError('Corrected support maps do not exactly replace original coverage')
    rows=[]
    for row in old:
        replaced=key(row) in replacements;source=replacements[key(row)] if replaced else row
        rows.append({**{k:source[k] for k in ('family','outcome','model','term','direction','z','n','min_cluster_fwe_p','significant_voxels','significant_clusters')},
                     'outcome':source['outcome'].split('/')[-1],'source_status':'corrected_MSPSS' if replaced else 'retained_non_MSPSS'})
    if sum(int(r['significant_clusters'])>0 for r in rows)!=71:raise ValueError('Expected 69 historical maps minus 7 superseded plus 9 corrected maps')
    (report/'scientific_inventory.tsv').write_text(base.review.tsv(rows))
    old_clusters=read(original/'clusters.tsv');new_clusters=read(corrected/'report/clusters.tsv')
    cluster_fields=['family','outcome','model','term','direction','z','n','component','voxels','volume_mm3','cluster_fwe_p_min','peak_contrast_t','peak_x_mm','peak_y_mm','peak_z_mm']
    clusters=[dict(r,source_status='retained_non_MSPSS') for r in old_clusters if 'mspss' not in r['model']]
    clusters += [dict(r,source_status='corrected_MSPSS') for r in new_clusters]
    safe=[{**{k:r[k] for k in cluster_fields},'outcome':r['outcome'].split('/')[-1],'source_status':r['source_status']} for r in clusters]
    for row in rows:
        if sum(key(c)==key(row) for c in safe)!=int(row['significant_clusters']):raise ValueError('Cluster table does not reconcile with catalog')
    (report/'scientific_clusters.tsv').write_text(base.review.tsv(safe))
    for path in (original/'maps.tsv',original/'clusters.tsv',original/'validation.json',corrected/'report/maps.tsv',corrected/'report/clusters.tsv'):
        add(records,path)
    return plan,corrected_plan,rows


def checked_design(job,ids,values):
    fields,rows=base.cohort.read_table(Path(job['design']).with_suffix('.tsv'));names=fields[1:]
    x=extension.audit.matrix(job['design']);contrasts=extension.audit.matrix(job['contrast'])
    if ([r['subject'] for r in rows]!=ids or x.shape!=(97,len(names)) or not np.array_equal(x[:,0],np.ones(97))
            or not np.allclose(x,[[float(r[n]) for n in names] for r in rows],rtol=0,atol=1e-12)
            or np.linalg.matrix_rank(x)!=len(names) or names[:7]!=previous.COMMON
            or job['residual_dof']!=97-len(names)):
        raise ValueError('Original design/covariates/order differ')
    for n in names[7:]:
        if n in values and not np.allclose(x[:,names.index(n)],values[n]-values[n].mean(),rtol=0,atol=1e-10):
            raise ValueError('Centered score mismatch: '+n)
    for n in ('fevsxpm25','adixmspss'):
        if n in names:
            a,b=n.split('x')
            if not np.allclose(x[:,names.index(n)],x[:,names.index(a)]*x[:,names.index(b)],rtol=0,atol=1e-10):raise ValueError('Interaction mismatch')
    if contrasts.shape!=(len(job['contrasts']),len(names)):raise ValueError('Contrast count differs')
    for d in job['contrasts']:
        expected=np.zeros(len(names));expected[names.index(d['term'])]=1 if d['direction']=='positive' else -1
        if not np.array_equal(contrasts[d['index']-1],expected):raise ValueError('Named coefficient differs from executed contrast')
    return names,x


def selection(plan,folder,job,term,direction,records):
    prefix,evidence=previous.completed(plan,job,folder)
    for r in evidence:extension.audit.add_record(records,r['path'],r['sha256'],r['size'])
    d=next(d for d in job['contrasts'] if d['term']==term and d['direction']==direction)
    ref=nib.load(plan['masks'][job['family']]);support=ref.get_fdata()>0
    stat=nib.load(str(prefix)+f"_tstat{d['index']}.nii.gz");prob=nib.load(str(prefix)+f"_clustere_corrp_tstat{d['index']}.nii.gz")
    base.grid(ref,stat);base.grid(ref,prob);data=stat.get_fdata();p=prob.get_fdata();selected=support&(p>.95)
    if np.any(data[selected]<job['t_cutoff']-1e-5):raise ValueError('Corrected cluster below actual CDT')
    return ref,data,p,selected


def atlas_annotations(reference,selected,peak,records):
    root=Path(os.environ.get('FSLDIR','/usr/local/fsl'))/'data/atlases';xyz=nib.affines.apply_affine(reference.affine,np.argwhere(selected));out=[]
    for kind,filename in [('cort','HarvardOxford-Cortical.xml'),('sub','HarvardOxford-Subcortical.xml')]:
        path=root/f'HarvardOxford/HarvardOxford-{kind}-maxprob-thr25-2mm.nii.gz';xml=root/filename
        if not path.is_file() or not xml.is_file():continue
        add(records,path);add(records,xml);image=nib.load(path);data=np.asarray(image.dataobj)
        names={int(n.attrib['index'])+1:(n.text or '').strip() for n in ET.parse(xml).findall('.//label')}
        def sample(points):
            indices=np.rint(nib.affines.apply_affine(np.linalg.inv(image.affine),points)).astype(int)
            valid=np.all((indices>=0)&(indices<np.array(image.shape)),axis=1);labels=np.zeros(len(points),dtype=int)
            labels[valid]=data[tuple(indices[valid].T)].astype(int);return labels
        labels=sample(xyz);unique,counts=np.unique(labels,return_counts=True)
        out.append(dict(atlas='HarvardOxford-'+kind,peak_label=names.get(int(sample(np.array([peak]))[0]),'Unlabeled'),
            overlap=sorted([dict(label=names.get(int(v),'Unlabeled'),voxels=int(n),fraction=float(n/len(xyz))) for v,n in zip(unique,counts)],key=lambda r:r['voxels'],reverse=True)))
    if not out:raise FileNotFoundError('HarvardOxford atlas and XML unavailable; no anatomical label substituted')
    return out


def brain(path,reference,statistic,region,anatomy,peak,title,positive):
    from nilearn import plotting
    values=np.where(region,statistic if positive else -statistic,0).astype(np.float32)
    fig=plt.figure(figsize=(10,4.3));fig.suptitle(title,fontsize=12)
    ax=fig.add_axes([.02,.18,.95,.68]);vmax=max(4.5,float(abs(values).max()))
    if region.any():
        plotting.plot_stat_map(nib.Nifti1Image(values,reference.affine),bg_img=anatomy,display_mode='ortho',cut_coords=peak,
            axes=ax,figure=fig,cmap='RdBu_r',threshold=1e-8,vmin=-vmax,vmax=vmax,symmetric_cbar=True,colorbar=True,draw_cross=True)
    else:plotting.plot_anat(anatomy,display_mode='ortho',cut_coords=peak,axes=ax,figure=fig,colorbar=False)
    fig.text(.5,.035,'N=97; cluster-FWE p<.05 per map only; positive=red, negative=blue.\n'+CAUTION,ha='center',fontsize=8)
    fig.savefig(path,dpi=220);plt.close(fig)


def region_description(ref,stat,p,selected,records):
    labels,n=label(selected,structure=np.ones((3,3,3),dtype=bool));clusters=[]
    for i in range(1,n+1):
        region=labels==i;ijk=np.argwhere(region);peakijk=ijk[np.argmax(stat[region])];peak=nib.affines.apply_affine(ref.affine,peakijk)
        clusters.append(dict(component=i,voxels=int(region.sum()),peak_mni=[float(v) for v in peak],
            peak_directional_t=float(stat[tuple(peakijk)]),cluster_fwe_p=float(1-p[region].max()),
            atlas=atlas_annotations(ref,region,peak,records),tissue_note='Atlas labels are approximate; not native tissue segmentation'))
    return clusters,labels


def behavior(report,values,records):
    names,x=previous.behavior.design(values,'pm25','mspss');ordinary,robust,info,loo=fit_summary(x,values['fevs'],names,'interaction')
    published=read(ROOT/'results/review/behavioral-mspss-corrected-provisional-v1/interactions.tsv')
    target=next(r for r in published if r['model']=='fevs_pm25_mspss')
    for a,b in [('interaction_beta','beta'),('ci_lower','hc3_lower'),('ci_upper','hc3_upper')]:
        if not np.isclose(float(target[a]),info[b],rtol=0,atol=1e-9):raise ValueError('Reproduced behavioral model differs from published corrected coefficients')
    levels=conditional_figure(report/'figure-1-behavior.png',robust,names,'pm25','interaction',values['mspss'],
        'Does social support modify the PM2.5–FEVS association?')
    (report/'behavioral_conditional_slopes.tsv').write_text(base.review.tsv(levels))
    folder=ROOT/'results/review/behavioral-mspss-corrected-provisional-v1'
    manifest=json.loads((folder/'review_manifest.json').read_text())
    for name,sha in manifest['outputs'].items():
        if base.cohort.digest(folder/name)!=sha:raise ValueError('Published corrected behavioral artifact changed')
        add(records,folder/name)
    return dict(**info,conditional_slopes=levels,published_interaction=target,
                reproduction='Existing model reproduced solely to recover HC3 covariance for exact observed-percentile contrasts; no new formula',provisional_financial_scoring=True)


def adi_review(project,report,plan,ids,values,anatomy,records,private):
    job=next(j for j in plan['jobs'] if j['key']=='activation/win_only/adixmspss/z-3p1')
    names,x=checked_design(job,ids,values)
    folder=project/'derivatives/fsl/randomise/katie-mspss-corrected-v1'
    ref,stat,p,selected=selection(plan,folder,job,'adixmspss','positive',records)
    clusters,labels=region_description(ref,stat,p,selected,records)
    if len(clusters)!=1 or clusters[0]['voxels']!=87 or not np.isclose(clusters[0]['cluster_fwe_p'],.0255,atol=1e-6):raise ValueError('Corrected ADI/support target differs from published 87-voxel finding')
    source=Path(plan['images']['activation/win_only']);add(records,source);image=nib.load(source);base.grid(ref,image,4)
    if image.shape[3]!=97:raise ValueError('ADI activation stack does not have 97 ordered volumes')
    y=image.get_fdata(dtype=np.float32)[selected,:].mean(axis=0,dtype=np.float64)
    ordinary,robust,info,loo=fit_summary(x,y,names,'adixmspss')
    peak=clusters[0]['peak_mni'];brain(report/'figure-3-adi-support-brain.png',ref,stat,selected,anatomy,peak,
        'ADI × corrected MSPSS: Social win − nonsocial win activation',True)
    levels=conditional_figure(report/'figure-3-adi-support-conditional.png',robust,names,'adi','adixmspss',values['mspss'],
        'How does the ADI–activation slope vary across corrected support?',selected=True)
    fig,axes=plt.subplots(1,2,figsize=(10,3.5),layout='constrained')
    axes[0].hist(ordinary.get_influence().cooks_distance[0],bins=12,color='#126a70')
    axes[0].axvline(4/97,color='#555',ls='--',lw=.8);axes[0].set(xlabel="Cook's distance (aggregate distribution)",ylabel='Count',title=f"Influence: max Cook's D={info['max_cooks_d']:.3f}")
    axes[1].hist(loo,bins=12,color='#126a70');axes[1].axvline(info['beta'],color='#555',ls='--');axes[1].axvline(0,color='#aaa',lw=.8)
    axes[1].set(xlabel='Leave-one-out interaction coefficient',ylabel='Count',title='All 97 retained; aggregate distribution')
    fig.supxlabel(CAUTION,fontsize=8);fig.savefig(report/'adi-support-influence.png',dpi=200);plt.close(fig)
    diagnostics=[dict(subject=s,region_estimate=float(v),loo_beta=float(l)) for s,v,l in zip(ids,y,loo)]
    (private/'adi-participant-diagnostics.tsv').write_text(base.review.tsv(diagnostics))
    (report/'adi_conditional_slopes.tsv').write_text(base.review.tsv(levels))
    return dict(job=job['key'],contrast='Social win - nonsocial win activation',cluster=clusters[0],fit=info,conditional_slopes=levels,
                pattern='ADI slope increases as corrected support increases. Protective buffering is not established by this interaction or by the value of the activation contrast.',new_permutation_analysis=False)


def vs_components(project,report,original,ids,values,anatomy,records,private):
    job=next(j for j in original['jobs'] if j['key']==sensitivity.BASE_KEY+'z-3p1')
    names,x=checked_design(job,ids,values);folder=project/'derivatives/fsl/randomise/katie-reward-extension-v1'
    ref,stat,p,selected=selection(original,folder,job,'fevs','negative',records)
    clusters,_=region_description(ref,stat,p,selected,records)
    if len(clusters)!=1 or clusters[0]['voxels']!=44 or not np.isclose(clusters[0]['cluster_fwe_p'],.0303,atol=1e-6):raise ValueError('Original fixed VS frontal cluster differs')
    stack=nib.load(original['images']['connectivity/social_specific']);base.grid(ref,stack,4)
    fixed=stack.get_fdata(dtype=np.float32)[selected,:]
    components={task:[] for task in ('socialdoors','doors')}
    for index,subject in enumerate(ids):
        for task in components:
            receipt=project/f'derivatives/fsl/randomise/katie-remaining-v1/ppi-l1/sub-{subject}_ses-01_task-{task}_run-1/success.json'
            saved=json.loads(receipt.read_text());add(records,receipt)
            if (saved['job']['subject'],saved['job']['task'])!=(subject,task):raise ValueError('PPI component identity differs')
            feat=Path(saved['feat']);extension.validate_ppi_components(feat)
            for r in saved['sources']+saved['outputs']:extension.audit.add_record(records,r['path'],r['sha256'],r['size'])
            path=feat/'stats/cope4.nii.gz';image=nib.load(path);base.grid(ref,image);add(records,path)
            components[task].append(image.get_fdata()[selected])
        left,right=components['socialdoors'][-1],components['doors'][-1]
        expected=(left-right).astype(np.float32)
        if not np.array_equal(expected,fixed[:,index]):raise ValueError('Original VS difference stack does not equal these task-specific PPI components in frozen order')
        if (index+1)%25==0 or index==96:print(f'FIXED-ROI COMPONENTS {index+1}/97 pairs verified',flush=True)
    ys={task:np.mean(np.stack(v),axis=1) for task,v in components.items()};ys['difference']=fixed.mean(axis=0,dtype=np.float64)
    fitted={};metadata={};private_rows=[]
    for name,y in ys.items():
        ordinary,robust,info,loo=fit_summary(x,y,names,'fevs');fitted[name]=(ordinary,robust);metadata[name]=info
        for s,v in zip(ids,y):private_rows.append(dict(subject=s,component=name,region_estimate=float(v)))
    if not np.isclose(metadata['socialdoors']['beta']-metadata['doors']['beta'],metadata['difference']['beta'],rtol=0,atol=1e-7):raise ValueError('Component slope decomposition does not reconcile')
    fig,axes=plt.subplots(1,3,figsize=(13,4.3),sharex=True,sharey=True,layout='constrained')
    for ax,name,title in zip(axes,('socialdoors','doors','difference'),('Social win − loss VS PPI','Nonsocial win − loss VS PPI','Social − nonsocial valence PPI')):
        fit,robust=fitted[name];i=names.index('fevs');adjusted=fit.resid+fit.params[0]+fit.params[i]*x[:,i]
        xx=np.linspace(values['fevs'].min(),values['fevs'].max(),101);v=np.zeros((101,len(names)));v[:,0]=1;v[:,i]=xx-values['fevs'].mean()
        estimate=v@robust.params;half=t.ppf(.975,robust.df_resid)*np.sqrt(np.einsum('ij,jk,ik->i',v,robust.cov_params(),v))
        ax.scatter(values['fevs'],adjusted,s=15,alpha=.65,color='#126a70');ax.plot(xx,estimate,color='#126a70');ax.fill_between(xx,estimate-half,estimate+half,color='#126a70',alpha=.15)
        ax.set(title=title,xlabel='FEVS');info=metadata[name];ax.text(.02,.98,f"b={info['beta']:.3f}\nHC3 [{info['hc3_lower']:.3f}, {info['hc3_upper']:.3f}]",transform=ax.transAxes,va='top',fontsize=8)
    axes[0].set_ylabel('Model-adjusted fixed-region estimate (COPE units)');fig.suptitle('Same original 44-voxel frontal region; original FEVS/PM2.5 interaction model',fontsize=11)
    fig.supxlabel(CAUTION+'; pointwise HC3 intervals; common axes',fontsize=8);fig.savefig(report/'figure-2-vs-components.png',dpi=220);plt.close(fig)
    brain(report/'figure-2-vs-original-brain.png',ref,stat,selected,anatomy,clusters[0]['peak_mni'],
          'Original negative FEVS coefficient: domain-by-valence VS PPI',False)
    (private/'vs-components-participant-diagnostics.tsv').write_text(base.review.tsv(private_rows))
    (report/'vs_component_estimates.tsv').write_text(base.review.tsv([dict(component=name,**info) for name,info in metadata.items()]))
    return dict(cluster=clusters[0],fits=metadata,model_columns=names,seed='Original VS; unchanged',
        covariates='Original signed-difference QC, scanner era, age/gender, PM2.5, FEVS x PM2.5 retained for every component',
        caution='Component associations describe a region selected from the difference contrast; no independent confirmation or significance comparison between components',new_permutation_analysis=False)


def sensitivity_review(project,report,ids,values,anatomy,records):
    folder=project/'derivatives/fsl/randomise'/sensitivity.VERSION
    plan=plan_and_receipts(folder,records)
    original=json.loads((Path(plan['original'])/'plan.json').read_text())
    rows=read(folder/'report/maps.tsv');(report/'vs_support_sensitivity_maps.tsv').write_text(base.review.tsv(rows))
    for path in (folder/'report/maps.tsv',folder/'report/clusters.tsv',folder/'report/provenance.json'):add(records,path)
    locations=[]
    for job in plan['jobs']:
        names,x=checked_design(job,ids,values)
        if names!=previous.COMMON+['fevs','pm25','fevsxpm25','mspss'] or x.shape!=(97,11):raise ValueError('Only additive support is authorized')
        for direction in ('positive','negative'):
            ref,stat,p,selected=selection(plan,folder,job,'fevs',direction,records)
            clusters,labels=region_description(ref,stat,p,selected,records)
            for c in clusters:
                locations.append(dict(z=job['z'],direction=direction,**c))
                brain(report/f"vs-support-z{job['z']}-{direction}-cluster{c['component']}.png",ref,stat,labels==c['component'],anatomy,c['peak_mni'],
                      f"FEVS VS PPI + corrected support | CDT {job['z']} | {direction}",direction=='positive')
            if job['z']==3.1 and direction=='negative':
                brain(report/'figure-2-vs-support-brain.png',ref,stat,selected,anatomy,[-20.8,57.6,11.2],
                      'FEVS coefficient with additive corrected MSPSS | original frontal cuts',False)
    return dict(new_jobs=2,new_maps=4,baseline_maps_reused=4,maps=rows,clusters=locations,
                caution='Whole-brain sensitivity uses original images/mask. Original frontal cuts are fixed for visual comparison; all adjusted cluster peaks are separately reported.',provisional_financial_scoring=True)


def verify(root):
    report=root/'report';manifest=json.loads((report/'review_manifest.json').read_text());saved=json.loads((root/'inputs-private.json').read_text())
    if manifest['n']!=97 or manifest['renderer_sha256']!=base.cohort.digest(Path(__file__)):raise ValueError('Closeout renderer changed; preserve existing report')
    for name,sha in manifest['outputs'].items():
        if Path(name).name!=name or base.cohort.digest(report/name)!=sha:raise ValueError('Sealed closeout artifact changed')
    extension.audit.verify_records({r['path']:r for r in saved['sources']},12)
    print('CHECK PASSED: closeout figures/tables and all source/completed-output fingerprints; N=97; exclusions unchanged.',flush=True)


def build(project):
    root=project/'work'/NAME;report=root/'report';root.mkdir(parents=True,exist_ok=True)
    if (report/'review_manifest.json').exists():verify(root);return
    if report.exists():raise ValueError('Unsealed partial reporting directory preserved; choose a new version after diagnosing')
    stage=Path(tempfile.mkdtemp(prefix='.closeout-report-',dir=root));stage.chmod(0o777)
    records={};ids,old=previous.behavior.inputs(ROOT);values={k:v.copy() for k,v in old.items()}
    values['mspss']=correction.corrected_scores(ROOT,ids,old['mspss'])
    for name in (previous.behavior.ROSTER,previous.behavior.SCORE_FILE,previous.behavior.VARIABLES,previous.behavior.POLICY,previous.behavior.SOURCE_RECEIPT,correction.SCORES,correction.PROVENANCE):add(records,ROOT/name)
    for module in (sensitivity,previous,correction,extension,base,previous.behavior):add(records,Path(module.__file__))
    add(records,Path(__file__));add(records,ROOT/sensitivity.AUTHORIZATION)
    original,corrected,catalog=scientific_catalog(project,stage,records)
    anatomy=background.select([Path(os.environ.get('TEMPLATEFLOW_HOME',str(Path.home()/'.cache/templateflow')))/'tpl-MNI152NLin6Asym/tpl-MNI152NLin6Asym_res-02_T1w.nii.gz',Path(os.environ.get('FSLDIR','/usr/local/fsl'))/'data/standard/MNI152_T1_2mm.nii.gz'])['path'];add(records,Path(anatomy));add(records,Path(background.__file__))
    metadata=dict(n=97,behavior=behavior(stage,values,records),adi_support=adi_review(project,stage,corrected,ids,values,anatomy,records,root),
        vs_components=vs_components(project,stage,original,ids,values,anatomy,records,root),
        vs_support_sensitivity=sensitivity_review(project,stage,ids,values,anatomy,records),
        canonical_maps=1328,corrected_maps_with_clusters=71,new_sensitivity_maps=4,
        financial_scoring='Provisional exported totals; versions/scoring rules/timepoint provenance still undocumented in the supplied repository',
        exclusions_changed=False,cohort_changed=False,selected_cluster_plots_descriptive=True)
    (stage/'summary.json').write_text(base.cohort.json_text(metadata))
    (stage/'README.md').write_text('# Katie Results Closeout: Validated Analysis Evidence\n\nN=97 unchanged. Two new additive-MSPSS VS-PPI sensitivity jobs (four maps) only. All other inferential results reused. Corrected behavioral slopes, corrected ADI/support activation location and conditional/influence plots, and fixed-original-region VS components are descriptive follow-ups. Selected-cluster plots are not independent confirmation. Financial scoring remains provisional. Canonical inventory replaces the 384 old support maps with 384 corrected maps; all 1,328 maps including nulls remain enumerated. Additional support sensitivity has four separate maps. Participant diagnostics and input paths stay private outside this payload.\n\nThe Results-ready PDF and three-question evidence summary will be assembled after inspecting this evidence package.\n')
    extension.audit.verify_records(records,12)
    (root/'inputs-private.json').write_text(base.cohort.json_text(dict(sources=list(records.values()))))
    outputs={p.name:base.cohort.digest(p) for p in stage.iterdir() if p.is_file()}
    (stage/'review_manifest.json').write_text(base.cohort.json_text(dict(n=97,outputs=outputs,renderer_sha256=base.cohort.digest(Path(__file__)),new_jobs=2,exclusions_changed=False)))
    stage.rename(report);verify(root)


if __name__=='__main__':
    os.umask(0);p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['build','check']);p.add_argument('--project',type=Path,required=True);a=p.parse_args()
    if a.command=='build':build(a.project.resolve())
    else:verify(a.project.resolve()/'work'/NAME)
