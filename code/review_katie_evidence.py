#!/usr/bin/env python3
"""Matched brain/scatter panels, explicit task means, and executed-design views."""
import argparse
import fcntl
import json
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np
from scipy.stats import t
import statsmodels.api as sm

import review_fevs_adjustment_maps as mapped
import run_social_win_mean as taskmean

base=mapped.base
ROOT=Path(__file__).resolve().parents[1]


def main_effect_fit(x,y,names,raw):
    index=names.index("fevs")
    if (x.shape!=(97,len(names)) or y.shape!=(97,) or np.linalg.matrix_rank(x)!=len(names)
            or not np.isfinite(x).all() or not np.isfinite(y).all()
            or not np.allclose(x[:,index],raw-raw.mean(),rtol=0,atol=1e-10)):
        raise ValueError("Matched ROI/design or FEVS axis differs; no rows dropped")
    fit=sm.OLS(y,x,hasconst=True).fit()
    robust=fit.get_robustcov_results(cov_type="HC3",use_t=True)
    adjusted=fit.resid+fit.params[0]+fit.params[index]*x[:,index]
    ci=robust.conf_int()[index]
    record=dict(n=97,beta=float(fit.params[index]),hc3_lower=float(ci[0]),hc3_upper=float(ci[1]),
        max_cooks_d=float(fit.get_influence().cooks_distance[0].max()),
        loo_beta_min=float(fit.get_influence().params_not_obsi[:,index].min()),
        loo_beta_max=float(fit.get_influence().params_not_obsi[:,index].max()),
        selection="Original corrected cluster held fixed across every adjustment; same-sample descriptive only",
        inferential_p_reported=False,exclusions_changed=False)
    return adjusted,fit,record


def design_figure(path,job,names,title):
    x=taskmean.adjustments.extension.audit.matrix(job["design"])
    c=taskmean.adjustments.extension.audit.matrix(job["contrast"])
    if x.shape!=(97,len(names)) or c.shape[1]!=len(names) or not np.isfinite(x).all():
        raise ValueError("Executed design/contrast shape differs")
    scale=np.max(np.abs(x),axis=0)
    if np.any(scale==0):raise ValueError("Zero-valued design column")
    fig,axes=plt.subplots(2,1,figsize=(12,8),gridspec_kw=dict(height_ratios=[4,1.6]),layout="constrained")
    im=axes[0].imshow(x/scale,cmap="RdBu_r",vmin=-1,vmax=1,aspect="auto",interpolation="nearest")
    axes[0].set(ylabel="Frozen participant / 4D volume row",title=title+"\nColumn-max scaling for display only; original values unchanged")
    axes[1].imshow(c,cmap="RdBu_r",vmin=-1,vmax=1,aspect="auto",interpolation="nearest")
    definitions=job.get("contrasts",[dict(term="ones",direction=d) for d in ("positive","negative")])
    if len(definitions)!=c.shape[0]:raise ValueError("Contrast labels differ")
    axes[1].set_yticks(range(c.shape[0]),[d["term"]+" "+d["direction"] for d in definitions],fontsize=8)
    for ax in axes:ax.set_xticks(range(len(names)),names,rotation=35,ha="right",fontsize=8)
    fig.colorbar(im,ax=axes,shrink=.6)
    mapped.views.plots.save_figure(fig,path)
    standardized=x.copy();standardized[:,1:]/=np.std(x[:,1:],axis=0,ddof=1)
    return dict(columns=";".join(names),n=97,rank=int(np.linalg.matrix_rank(x)),residual_df=97-len(names),
                scaled_condition_number=float(np.linalg.cond(standardized)),contrasts=c.shape[0],
                ones_contrasted=bool(np.any(c[:,names.index("ones")]!=0)),matrix_source=job["design"],contrast_source=job["contrast"])


def matched_panel(path,target,group,models,y,raw,anatomy):
    from nilearn import plotting
    fig=plt.figure(figsize=(17,12.8));fig.suptitle(mapped.adjustment.LABELS[target]+"\nOriginal cluster held fixed for descriptive scatters",fontsize=13,y=.99)
    original=group["rows"][0]["selected"];reference=group["reference"]
    vmax=max(5.,max(float(np.max(np.abs(r["signed_t"]))) for r in group["rows"]))
    fits=[]
    for i,(row,(names,x)) in enumerate(zip(group["rows"],models)):
        bottom=.735-i*.22
        fig.text(.02,bottom+.183,f"{row['adjustment']} | whole-brain cluster-FWE p={row['p']:.4f}; corrected voxels={row['location']['voxels']}",fontsize=10)
        axis=fig.add_axes([.01,bottom,.65,.175])
        display=plotting.plot_stat_map(nib.Nifti1Image(row["signed_t"].astype(np.float32),reference.affine),bg_img=anatomy,
            display_mode="ortho",cut_coords=group["cut_coords"],axes=axis,figure=fig,cmap="RdBu_r",threshold=2.,
            vmax=vmax,symmetric_cbar=True,colorbar=True,draw_cross=True)
        display.add_contours(nib.Nifti1Image(original.astype(np.uint8),reference.affine),levels=[.5],colors=["cyan"],linewidths=1.3)
        if i and row["selected"].any():
            display.add_contours(nib.Nifti1Image(row["selected"].astype(np.uint8),reference.affine),levels=[.5],colors=["gold"],linewidths=1.)
        adjusted,fit,record=main_effect_fit(x,y,names,raw)
        record.update(target=target,adjustment=row["adjustment"]);fits.append(record)
        ax=fig.add_axes([.735,bottom+.025,.235,.13])
        ax.scatter(raw,adjusted,s=13,color="#126A70",alpha=.7,edgecolors="none")
        xx=np.linspace(raw.min(),raw.max(),101)
        ax.plot(xx,fit.params[0]+fit.params[names.index("fevs") ]*(xx-raw.mean()),color="#183B56",lw=1.5)
        ax.set(xlabel="FEVS (exported score)",ylabel="Adjusted original-ROI COPE")
        ax.set_title(f"Same model, fixed ROI | b={record['beta']:.3g}\nHC3 interval [{record['hc3_lower']:.3g}, {record['hc3_upper']:.3g}] (descriptive)",fontsize=8)
        ax.tick_params(labelsize=8);ax.xaxis.label.set_size(8);ax.yaxis.label.set_size(8)
        ax.spines[["top","right"]].set_visible(False)
    fig.text(.5,.025,"N=97; all participants retained; scoring provisional. Cyan: original corrected cluster; gold: adjusted corrected cluster.\n"
        "Brain shading |t|>=2 is display-only. Contours: saved cluster-FWE p<.05 at CDT 3.1. ROI plots are NOT independent confirmation.\n"
        "FEVS main coefficients are not interactions: scatters, not JN plots, are appropriate. PM2.5 models retain the original interaction term.",ha="center",fontsize=9)
    mapped.views.plots.save_figure(fig,path)
    return fits


def group_rows(plan,folder,outcome):
    rows=[];evidence=[]
    for job in [j for j in plan["jobs"] if j["outcome"]==outcome]:
        prefix,records=taskmean.completed(plan,job,folder);evidence.extend(records)
        evidence.append(base.fingerprint(folder/"jobs"/job["key"]/"success.json"))
        for index,direction in ((1,"positive"),(2,"negative")):
            rows.append(dict(mask=plan["mask"],z=job["z"],direction=direction,job=job,
                tstat=str(prefix)+f"_tstat{index}.nii.gz",corrp=str(prefix)+f"_clustere_corrp_tstat{index}.nii.gz"))
    if len(rows)!=4:raise ValueError("Task-mean outcome must have both CDTs and both signs")
    return rows,evidence


def l1_artifacts(pairs,ids,report):
    import shutil
    items=[];evidence=[]
    for task in ("socialdoors","doors"):
        pair=next(r for r in pairs if r["subject"]==ids[0] and r["contrast"]=="4")
        feat=Path(pair[task+"_feat_dir"])
        mapped.adjustment.extension.components.validate_contrasts(feat)
        evidence.extend(base.fingerprint(feat/name) for name in ("design.fsf","design.mat","design.con"))
        for name in ("design.png","design_cov.png"):
            path=feat/name;item=dict(task=task,artifact=name,available=path.is_file())
            if path.is_file():
                destination="L1-"+task+"-"+name;shutil.copyfile(path,report/destination)
                item["report_file"]=destination;evidence.append(base.fingerprint(path))
            items.append(item)
    return items,evidence


def verify(report):
    manifest=json.loads((report/"review_manifest.json").read_text())
    if manifest["n"]!=97 or manifest["renderer_sha256"]!=base.cohort.digest(Path(__file__)):raise ValueError("Evidence report identity changed")
    for name,sha in manifest["outputs"].items():
        if Path(name).name!=name or base.cohort.digest(report/name)!=sha:raise ValueError("Evidence artifact changed")
    saved=json.loads((report.parent/"inputs-private.json").read_text())
    mapped.adjustment.extension.audit.verify_records({r["path"]:r for r in saved["sources"]},8)
    print("CHECK PASSED: matched brain/scatter panels, task means and actual design/contrast views; N=97; no exclusions changed.",flush=True)


def build(args):
    report=args.report
    if (report/"review_manifest.json").exists():verify(report);return
    if report.exists() and any(report.iterdir()):raise ValueError("Unsealed report exists; preserve it and use another version")
    folder=args.project/"derivatives/fsl/randomise"/mapped.adjustment.VERSION
    plan=base.load_plan(folder)
    mapped.check_analysis(args.project,Path(plan["data_root"]))
    groups,evidence=mapped.collect(plan,folder)
    ids,values=mapped.adjustment.behavior.inputs(ROOT)
    _,ordered=base.cohort.read_table(folder/"subjects.tsv")
    if [r["subject"] for r in ordered]!=ids:raise ValueError("Descriptive estimates do not match frozen image order")
    anatomy=mapped.views.background.select([Path(os.environ.get("FSLDIR","/usr/local/fsl"))/"data/standard/MNI152_T1_2mm.nii.gz"])["path"]
    report.mkdir(parents=True,exist_ok=True)
    fits=[];designs=[];cache={};records={r["path"]:r for r in plan["sources"]}
    for target,group in groups.items():
        roi=group["rows"][0]["selected"]
        image_path=plan["images"][next(j["outcome"] for j in plan["jobs"] if j["target"]==target)]
        if image_path not in cache:cache[image_path]=nib.load(image_path).get_fdata(dtype=np.float32)
        if cache[image_path].shape[-1]!=97:raise ValueError("Expected 97 image volumes")
        y=cache[image_path][roi,:].mean(axis=0,dtype=np.float64)
        models=[]
        for row in group["rows"]:
            name=row["adjustment"]
            job=next(b["job"] for b in plan["baselines"] if b["target"]==target and b["job"]["z"]==3.1) if name=="baseline" else next(j for j in plan["jobs"] if j["target"]==target and j["adjustment"]==name and j["z"]==3.1)
            headers,rows=base.cohort.read_table(Path(job["design"]).with_suffix(".tsv"));names=headers[1:]
            if [r["subject"] for r in rows]!=ids:raise ValueError("Scatter model row order differs")
            x=mapped.views.audit.matrix(job["design"])
            if not np.allclose(x,[[float(r[n]) for n in names] for r in rows],rtol=0,atol=1e-12):raise ValueError("Labeled/numeric design differs")
            models.append((names,x))
            if target!="vs_fevs_pm25" and (name=="baseline" or target=="activation_fevs_pm25" and name=="adi_ecog"):
                identifier=target+"-"+name
                designs.append(dict(id=identifier,**design_figure(report/("design-"+identifier+".png"),job,names,identifier)))
        fits.extend(matched_panel(report/(target+"-paired.png"),target,group,models,y,values["fevs"],anatomy))
    old_folder=args.project/"derivatives/fsl/randomise/katie-remaining-v1/activation"
    old=taskmean.saved_plan(old_folder)
    mean_folder=args.project/"derivatives/fsl/randomise"/taskmean.VERSION
    mean=taskmean.saved_plan(mean_folder)
    evidence.extend(taskmean.verify_smoke(mean_folder,mean))
    evidence.extend([base.fingerprint(old_folder/"plan.json"),base.fingerprint(mean_folder/"plan.json"),base.fingerprint(mean_folder/"plan.sha256")])
    for source_plan,root in ((old,old_folder),(mean,mean_folder)):
        for r in source_plan["sources"]:mapped.adjustment.extension.audit.add_record(records,r["path"],r["sha256"],r.get("size"))
        evidence.extend(base.fingerprint(root/name) for name in source_plan["outputs"])
    group_statistics=[]
    for owner,root,outcome,title in ((old,old_folder,"average","Average of social and nonsocial win-minus-loss"),
        (old,old_folder,"social_specific","Double subtraction: social win-minus-loss minus nonsocial win-minus-loss"),
        (mean,mean_folder,"social_win","Social win minus nonsocial win: explicit intercept test")):
        rows,source=group_rows(owner,root,outcome);evidence.extend(source)
        for row in rows:
            statistic,_=taskmean.adjustments.summary.map_summary(row["job"],row["direction"],nib.load(row["tstat"]),
                nib.load(row["corrp"]),nib.load(row["mask"]))
            group_statistics.append(statistic)
        mapped.views.plots.brain_figure(dict(id=outcome,title=title,rows=rows,background=anatomy,
            path=str(report/("group-"+outcome+".png")),relative="group-"+outcome+".png"))
        if outcome=="social_win":
            job=owner["jobs"][0]
            designs.append(dict(id="task-mean-intercept",**design_figure(report/"design-task-mean-intercept.png",job,mean["columns"],title)))
    _,pairs=base.cohort.read_table(ROOT/"data/derived/katie-cohort-v1/selected_pairs.tsv")
    l1,source=l1_artifacts(pairs,ids,report);evidence.extend(source)
    public_designs=[{k:v for k,v in d.items() if k not in ("matrix_source","contrast_source")} for d in designs]
    base.write_json(report/"summary.json",dict(n=97,provisional_scoring=True,new_randomise_jobs=2,new_directional_maps=4,
        descriptive_fits=fits,designs=public_designs,L1_artifacts=l1,group_means=group_statistics,exclusions_changed=False,
        note="Only the missing social-win group intercept is new; other task maps and scientific whole-brain tests reused"))
    (report/"design_checks.tsv").write_text(base.review.tsv(public_designs))
    lines=["# Katie Evidence Panels: Context, Content, Conclusions","","N=97; provisional scoring; no settled exclusions changed.",
        "The column of ones does not test itself: it must be explicitly contrasted. Only two new task-mean jobs were added (social win minus nonsocial win, both CDTs); existing win-loss and double-subtraction jobs were reused.",
        "FEVS main coefficients use scatters, not JN plots. Every scatter uses the exact corresponding model and the original corrected ROI held fixed across adjustments, including null whole-brain fits. These are selected-sample descriptive estimates, not independent inference.",""]
    conclusions=dict(
        activation_fevs="Higher FEVS is associated with a larger social-winning activation contrast in the original/ADI fits, but this is not uniformly robust to Ecog adjustment. The atlas caveat prevents a clean cortical vmPFC/OFC claim.",
        activation_fevs_pm25="The conditional FEVS activation location is stable, but correction is borderline and depends on adjustment. The same-sample scatter is illustrative, not a rescue of a null whole-brain fit. This is not evidence of a winning-related FEVS x PM2.5 interaction.",
        vs_fevs_pm25="Higher FEVS relates to a lower social-by-valence VS-connectivity contrast with the same frontal target across ADI/Ecog adjustments at CDT 3.1. This is not global weaker connectivity or winning-specific coupling.")
    for target,*_ in mapped.adjustment.TARGETS:
        lines += ["## "+mapped.adjustment.LABELS[target],"","**Context:** Does the FEVS association remain after adding ADI/Ecog?",f"![Matched maps and scatters]({target}-paired.png)",
                  "**Content:** Rows are original, ADI, Ecog, and both; brain p-values are whole-brain cluster-FWE at CDT 3.1. Scatter slopes/HC3 intervals are descriptive, selected-ROI estimates.",
                  "**Conclusion:** "+conclusions[target]+" Do not treat ROI intervals as a second successful hypothesis test.",""]
    for outcome in ("social_win","average","social_specific"):
        subset=[r for r in group_statistics if r["outcome"]==outcome]
        found=any(r["significant_voxels"]>0 for r in subset)
        conclusion=("A corrected group-average contrast is present; inspect the sign and CDT table below.") if found else (
            "No corrected group-average contrast was detected at either CDT in either direction. This does not establish equivalence or rule out individual-difference associations.")
        lines += ["## Group task effect: "+outcome,"","**Context:** Is the mean task contrast different from zero across the frozen 97 participants?",
                  f"![Task mean]({ 'group-'+outcome+'.png'})","**Content:** Explicit +/- intercept contrasts, not a financial-score effect.",
                  "| CDT | Direction | Minimum cluster-FWE p | Corrected voxels |","|---|---|---:|---:|"]
        lines += [f"| {r['z']} | {r['direction']} | {r['min_cluster_fwe_p']:.4f} | {r['significant_voxels']} |" for r in subset]
        lines += ["", "**Conclusion:** "+conclusion,""]
    lines += ["## Executed Designs And Contrasts","","Custom heatmaps are drawn from actual executed VEST files, not inferred from a column of ones or reconstructed from a new cohort. Columns are scaled only for display. Full matrices remain unchanged and participant row labels are not published."]
    for d in public_designs:lines += [f"![Executed design]({'design-'+d['id']+'.png'})",""]
    lines += ["Native L1 design.png/design_cov.png are copied unchanged when available; availability is recorded in summary.json. Missing PNGs never trigger a FEAT rerun.",""]
    (report/"README.md").write_text("\n".join(lines))
    paths=[Path(__file__),Path(mapped.__file__),Path(taskmean.__file__),Path(mapped.views.plots.__file__),Path(anatomy),folder/"plan.json"]
    for r in evidence+[base.fingerprint(p) for p in paths]:mapped.adjustment.extension.audit.add_record(records,r["path"],r["sha256"],r["size"])
    mapped.adjustment.extension.audit.verify_records(records,8)
    base.write_json(report.parent/"inputs-private.json",dict(sources=list(records.values())))
    base.write_json(report/"review_manifest.json",dict(n=97,provisional_scoring=True,exclusions_changed=False,
        renderer_sha256=base.cohort.digest(Path(__file__)),outputs={p.name:base.cohort.digest(p) for p in report.iterdir() if p.is_file()}))
    verify(report)


if __name__=="__main__":
    os.umask(0)
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("command",choices=("build","check"))
    parser.add_argument("--project",type=Path,required=True);parser.add_argument("--report",type=Path,required=True)
    args=parser.parse_args();args.project=args.project.resolve();args.report=args.report.resolve()
    args.report.parent.mkdir(parents=True,exist_ok=True)
    with (args.report.parent/".report.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        build(args) if args.command=="build" else verify(args.report)
