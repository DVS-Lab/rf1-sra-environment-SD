#!/usr/bin/env python3
"""Read-only location, JN and scatter review of three completed activation effects."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np
from nilearn import plotting
from scipy.ndimage import label
from scipy.stats import norm, t
import statsmodels.api as sm

import review_fevs_wins as common

base=common.extension.base
ROOT=Path(__file__).resolve().parents[1]
TARGETS=(
    dict(id="fevs-pm25-loss",model="fevsxpm25",outcome="loss_only",term="fevsxpm25",z=3.1,
         interaction=True,context="FEVS x PM2.5 interaction",outcome_label="Social loss minus nonsocial loss"),
    dict(id="ecog-pm25-loss",model="pm25xecog",outcome="loss_only",term="ecog",z=2.6,
         interaction=False,context="Ecog main effect at mean PM2.5",outcome_label="Social loss minus nonsocial loss"),
    dict(id="ecog-oafem-win",model="oafemxecog",outcome="win_only",term="ecog",z=3.1,
         interaction=False,context="Ecog main effect at mean OAFEM",outcome_label="Social win minus nonsocial win"),
)


def check_design(job,definition,ids,raw):
    names,rows=base.cohort.read_table(Path(job["design"]).with_suffix(".tsv"));names=names[1:]
    x=common.audit.matrix(job["design"]);contrasts=common.audit.matrix(job["contrast"])
    expected=np.array([[float(row[name]) for name in names] for row in rows])
    if ([row["subject"] for row in rows]!=ids or x.shape!=(97,len(names))
            or not np.isfinite(x).all() or not np.allclose(x,expected,rtol=0,atol=1e-12)
            or not np.all(x[:,0]==1) or np.linalg.matrix_rank(x)!=len(names)
            or job["residual_dof"]!=97-len(names)):
        raise ValueError("Target design/subject order, finite matrix, rank or residual df differs")
    if (job["permutations"]!=10000 or job["seed"]!=20261101
            or not np.isclose(job["t_cutoff"],t.isf(norm.sf(job["z"]),job["residual_dof"]),rtol=0,atol=1e-10)):
        raise ValueError("Target permutation settings or Z-to-t cutoff differs")
    if names[1:3]!=["delta_fd","delta_tsnr"]:
        raise ValueError("Component outcomes require the frozen signed-difference QC terms")
    a,b,interaction=names[-3:]
    if interaction!=a+"x"+b or not np.allclose(x[:,-1],x[:,-3]*x[:,-2],rtol=0,atol=1e-10):
        raise ValueError("Target interaction is not the product of centered main terms")
    for name in (a,b):
        values=np.asarray(raw[name])
        if not np.allclose(x[:,names.index(name)],values-values.mean(),rtol=0,atol=1e-10):
            raise ValueError("Raw predictor axes differ from the frozen centered design")
    expected=np.zeros(len(names));expected[names.index(definition["term"])]=-1
    if (contrasts.shape!=(len(job["contrasts"]),len(names))
            or definition["direction"]!="negative"
            or not np.array_equal(contrasts[definition["index"]-1],expected)):
        raise ValueError("Target contrast is not the documented negative coefficient")
    return names,x


def signed_brain(path,statistic,selected,reference,anatomy,peak,title,z):
    # Native negative-direction t is positive in surviving voxels; display the coefficient's sign.
    values=np.where(selected,-statistic,0).astype(np.float32)
    vmax=max(4.5,float(np.max(np.abs(values))))
    fig=plt.figure(figsize=(11,4.7));fig.suptitle(title,fontsize=11,y=.98)
    axis=fig.add_axes([.02,.20,.95,.67])
    if selected.any():
        plotting.plot_stat_map(nib.Nifti1Image(values,reference.affine),bg_img=anatomy,
            display_mode="ortho",cut_coords=peak,axes=axis,figure=fig,cmap="RdBu_r",threshold=1e-8,
            vmin=-vmax,vmax=vmax,symmetric_cbar=True,colorbar=True,draw_cross=True)
    else:
        plotting.plot_anat(anatomy,display_mode="ortho",cut_coords=[0,50,-5],axes=axis,figure=fig,colorbar=False)
    fig.text(.5,.035,f"N=97; blue = negative coefficient; cluster-FWE p<.05; CDT Z-equivalent {z}.\n"
        +("MNI coordinates; atlas labels are approximate annotations." if selected.any() else "No surviving corrected cluster; no ROI/JN plot generated."),
        ha="center",fontsize=9)
    common.plots.save_figure(fig,path)


def verify(report):
    manifest=json.loads((report/"review_manifest.json").read_text())
    for name,digest in manifest["outputs"].items():
        if Path(name).name!=name or base.cohort.digest(report/name)!=digest:
            raise ValueError("Follow-up report artifact differs: "+name)
    if manifest["renderer_sha256"]!=base.cohort.digest(Path(__file__)):
        raise ValueError("Follow-up renderer changed; preserve this report version")
    common.audit.verify_records({r["path"]:r for r in json.loads((report.parent/"inputs-private.json").read_text())["sources"]},8)
    print("CHECK PASSED: follow-up figures and frozen source/design/result hashes verified; N=97; exclusions unchanged.",flush=True)


def build(args):
    report=args.report
    if (report/"review_manifest.json").exists():
        verify(report);print("REUSED: sealed follow-up figures unchanged",flush=True);return
    if report.exists() and any(report.iterdir()):
        raise ValueError("Unsealed follow-up report exists; preserve it and choose a new version")
    folder=args.project/"derivatives/fsl/randomise/katie-reward-extension-v1"
    path=folder/"plan.json";digest=base.cohort.digest(path)
    if digest!=(folder/"plan.sha256").read_text().strip():raise ValueError("Extension plan checksum differs")
    plan=json.loads(path.read_text())
    if plan["n"]!=97 or len(plan["jobs"])!=220:raise ValueError("Unexpected frozen cohort/job inventory")
    records={r["path"]:r for r in plan["sources"]}
    for name,sha in plan["outputs"].items():common.audit.add_record(records,folder/name,sha)
    _,roster=base.cohort.read_table(ROOT/"data/derived/katie-cohort-v1/subjects.tsv")
    ids=[row["subject"] for row in roster]
    if len(ids)!=97 or len(set(ids))!=97:raise ValueError("Frozen N=97 roster differs")
    _,ordered=base.cohort.read_table(folder/"subjects.tsv")
    if [row["subject"] for row in ordered]!=ids:raise ValueError("Extension image-family roster differs")
    raw=common.plots.raw_terms(ids)
    chosen=[]
    for target in TARGETS:
        candidates=[job for job in plan["jobs"] if job["family"]=="activation" and job["model"]==target["model"]
                    and job["outcome"]=="activation/"+target["outcome"] and job["z"]==target["z"]]
        if len(candidates)!=1:raise ValueError("Target job missing or duplicated: "+target["id"])
        job=candidates[0]
        definition=next(row for row in job["contrasts"] if row["term"]==target["term"] and row["direction"]=="negative")
        names,x=check_design(job,definition,ids,raw)
        receipt=folder/"jobs"/job["key"]/"success.json"
        if not receipt.exists():raise ValueError("Target unfinished; no partial attempt used: "+job["key"])
        saved=json.loads(receipt.read_text());prefix=Path(saved["attempt"])/"randomise"
        if not prefix.parent.resolve().is_relative_to((receipt.parent/"attempts").resolve()):raise ValueError("Unsafe target attempt path")
        if (saved["job"]!=job or saved["plan_sha256"]!=digest or saved["smoke"] is not False
                or saved["command"]!=base.command(dict(plan,mask=plan["masks"]["activation"]),job,prefix)):
            raise ValueError("Target native command/receipt differs")
        if common.extension.products(prefix,plan["masks"]["activation"],job["contrasts"])!=saved["outputs"]:
            raise ValueError("Target completed result inventory differs")
        for record in saved["outputs"]:common.audit.add_record(records,record["path"],record["sha256"],record["size"])
        common.audit.add_record(records,receipt,base.cohort.digest(receipt))
        chosen.append((target,job,definition,prefix,names,x))
    anatomy=common.background.select([
        Path(os.environ.get("TEMPLATEFLOW_HOME",str(Path.home()/".cache/templateflow")))/"tpl-MNI152NLin6Asym/tpl-MNI152NLin6Asym_res-02_T1w.nii.gz",
        Path(os.environ.get("FSLDIR","/usr/local/fsl"))/"data/standard/MNI152_T1_2mm.nii.gz"])["path"]
    atlas_list=common.atlases(args.atlas_root)
    paths=[Path(__file__),Path(common.__file__),Path(common.plots.__file__),Path(common.audit.__file__),
        Path(common.extension.__file__),Path(common.financial.__file__),Path(common.background.__file__),
        common.financial.SCORES,Path(anatomy),path,ROOT/"data/derived/katie-cohort-v1/subjects.tsv",
        ROOT/"data/derived/model-review-v1/aligned_raw_terms.tsv",
        *[p for _,_,image,xml in atlas_list for p in (image,xml)]]
    for path in paths:
        record=base.fingerprint(path);common.audit.add_record(records,path,record["sha256"],record["size"])
    common.audit.verify_records(records,8)
    report.mkdir(parents=True,exist_ok=True)
    reference=nib.load(plan["masks"]["activation"]);support=reference.get_fdata()>0
    clusters=[];fits=[];models=[];links=[]
    # Process one outcome stack at a time and load each gzip-compressed 4D image only once.
    for outcome in dict.fromkeys(target["outcome"] for target in TARGETS):
        image=nib.load(plan["images"]["activation/"+outcome]);base.grid(reference,image,4)
        if image.shape[3]!=97:raise ValueError("Component stack has wrong N")
        data=image.get_fdata(dtype=np.float32)
        for target,job,definition,prefix,names,x in (item for item in chosen if item[0]["outcome"]==outcome):
            index=definition["index"]
            statistic=nib.load(str(prefix)+f"_tstat{index}.nii.gz").get_fdata()
            corrected=nib.load(str(prefix)+f"_clustere_corrp_tstat{index}.nii.gz").get_fdata()
            positive=nib.load(str(prefix)+f"_tstat{index-1}.nii.gz").get_fdata()
            if not np.allclose(statistic[support],-positive[support],rtol=1e-5,atol=1e-5):
                raise ValueError("Positive/negative native coefficient maps disagree")
            selected=support&(corrected>.95)
            if np.any(statistic[selected]<job["t_cutoff"]-1e-5):raise ValueError("Corrected target below its native CDT")
            components,count=label(selected,structure=np.ones((3,3,3),dtype=bool))
            peak=[0,50,-5]
            if selected.any():
                ijk=np.argwhere(selected);peak=nib.affines.apply_affine(reference.affine,ijk[np.argmax(statistic[selected])]).tolist()
            name=target["id"]+"-brain.png";title=target["outcome_label"]+"\n"+target["context"]
            signed_brain(report/name,statistic,selected,reference,anatomy,peak,title,target["z"])
            links.append((target["context"]+" | "+target["outcome_label"],name))
            models.append(dict(**target,columns=names,corrected_clusters=count))
            for component in range(1,count+1):
                region=components==component;ijk=np.argwhere(region);world=nib.affines.apply_affine(reference.affine,ijk)
                peak_ijk=ijk[np.argmax(statistic[region])];peak_world=nib.affines.apply_affine(reference.affine,peak_ijk)
                annotations=[dict(atlas="HarvardOxford-"+kind,
                    peak_label=common.atlas_annotation(atlas,xml,peak_world[None,:])[0]["label"],
                    cluster_overlap=common.atlas_annotation(atlas,xml,world)) for kind,atlas,_,xml in atlas_list]
                row=dict(id=target["id"],outcome=outcome,model=target["model"],term=target["term"],direction="negative",
                    z=target["z"],component=component,voxels=int(region.sum()),
                    volume_mm3=float(region.sum()*abs(np.linalg.det(reference.affine[:3,:3]))),
                    cluster_fwe_p=float(1-corrected[region].max()),peak_coefficient_t=-float(statistic[tuple(peak_ijk)]),
                    peak_mni_x=float(peak_world[0]),peak_mni_y=float(peak_world[1]),peak_mni_z=float(peak_world[2]),
                    peak_atlas_labels="; ".join(a["atlas"]+": "+a["peak_label"] for a in annotations) or "Atlas files unavailable",
                    atlas_annotations=annotations)
                clusters.append(row);identifier=target["id"]+f"-cluster-{component}"
                if count>1:
                    name=identifier+"-brain.png"
                    signed_brain(report/name,statistic,region,reference,anatomy,peak_world.tolist(),title+f" | cluster {component}",target["z"])
                    links.append((identifier+" location",name))
                y=data[region,:].mean(axis=0,dtype=np.float64)
                if not np.isfinite(y).all():raise ValueError("Nonfinite region estimates; no participant dropped")
                suffix="jn" if target["interaction"] else "scatter"
                name=identifier+"-"+suffix+".png"
                fit=common.plots.roi_figure(dict(id=identifier,title=title+f" | cluster {component}",
                    selection="SAME-SAMPLE SELECTED CLUSTER: descriptive only",path=str(report/name),
                    details=str(report.parent/"participant-diagnostics"/(identifier+".tsv")),
                    names=names,x=x.tolist(),y=y.tolist(),raw={k:v.tolist() for k,v in raw.items()},
                    term=target["term"],interaction=target["interaction"],ids=ids))
                fits.append(fit);links.append((identifier+" | "+("JN, conditional slopes and influence" if target["interaction"] else "raw/adjusted scatter and influence"),name))
                if target["interaction"]:
                    fitted=sm.OLS(y,x,hasconst=True).fit();curves=[]
                    for covariance,estimator in (("OLS",fitted),("HC3",fitted.get_robustcov_results(cov_type="HC3",use_t=True))):
                        curve=common.plots.jn_curve(estimator,names.index("fevs"),names.index("fevsxpm25"),x[:,names.index("pm25")],float(raw["pm25"].mean()))
                        curves.extend(dict(covariance=covariance,pm25=float(value),conditional_fevs_slope=float(slope),
                            ci_lower=float(interval[0]),ci_upper=float(interval[1]))
                            for value,slope,interval in zip(curve["raw_grid"],curve["slope"],curve["ci"]))
                    (report/(identifier+"-jn-curves.tsv")).write_text(base.review.tsv(curves))
                print("CLUSTER "+json.dumps({k:v for k,v in row.items() if k!="atlas_annotations"}),flush=True)
        del data
    metadata=dict(n=97,targets=models,clusters=clusters,region_fits=fits,atlas_available=bool(atlas_list),
        exclusions_changed=False,original_results_changed=False,new_inference=False,
        caution="Same-sample selected clusters; descriptive ROI/JN intervals, not independent inference; mapwise FWE only.")
    (report/"summary.json").write_text(base.cohort.json_text(metadata))
    fields=["id","outcome","model","term","direction","z","component","voxels","volume_mm3","cluster_fwe_p",
        "peak_coefficient_t","peak_mni_x","peak_mni_y","peak_mni_z","peak_atlas_labels"]
    (report/"clusters.tsv").write_text(base.review.tsv([{k:v for k,v in r.items() if k!="atlas_annotations"} for r in clusters],fields))
    lines=["# FEVS Loss Moderation and Ecog Follow-Up", "", "N=97; running inference, completed outputs and settled exclusions unchanged.",
        "Three preidentified negative-direction activation findings only; not an exhaustive or final-batch report.",
        "Loss = Social Doors loss minus Doors loss; win = Social Doors win minus Doors win. Neither is the win-minus-loss difference-of-differences.",
        "The loss FEVS x PM2.5 plot tests an interaction; the Ecog plots show main effects at mean PM2.5 or mean OAFEM, NOT interactions.",
        "Full original models retain both main terms and their interaction, age, gender, scanner era and signed FD/tSNR differences.",
        "Blue brain overlays and signed peak t values indicate negative coefficients; the native negative-direction test has positive t in these voxels.",
        "JN plots show conditional FEVS slopes across observed PM2.5 values only, OLS pointwise 95% intervals, HC3 sensitivity and observed-value rugs.",
        "Selected-cluster estimates, JN regions and analytical intervals are descriptive, not independent confirmation. All 97 participants remain; influence flags do not create exclusions.",
        "Cluster-FWE is per map, not across exploratory models, outcomes, directions or CDTs. These CDTs identify the reported findings, not a new optimization.",
        "Anatomy uses validated local MNI background and optional Harvard-Oxford annotations; statistical images are never resampled.",
        "Only aggregate PNGs/tables are published. Participant diagnostics and input fingerprints stay outside this report.","",
        "| Effect | Outcome | CDT Z | Voxels | Cluster-FWE p | Peak MNI | Atlas |", "|---|---|---:|---:|---:|---|---|"]
    for r in clusters:lines.append(f"| {r['term']} in {r['model']} | {r['outcome']} | {r['z']} | {r['voxels']} | {r['cluster_fwe_p']:.4f} | {r['peak_mni_x']:.1f}, {r['peak_mni_y']:.1f}, {r['peak_mni_z']:.1f} | {r['peak_atlas_labels']} |")
    for title,name in links:lines += ["", "## "+title,"",f"![{title}]({name})",""]
    (report/"README.md").write_text("\n".join(lines))
    common.audit.verify_records(records,8)
    (report.parent/"inputs-private.json").write_text(base.cohort.json_text(dict(sources=list(records.values()))))
    outputs={path.name:base.cohort.digest(path) for path in report.iterdir() if path.is_file()}
    (report/"review_manifest.json").write_text(base.cohort.json_text(dict(n=97,outputs=outputs,
        renderer_sha256=base.cohort.digest(Path(__file__)),targets=list(TARGETS),new_inference=False,exclusions_changed=False)))
    verify(report)
    print("REVIEW PASSED: three target effects; signed brain views, atlas locations, descriptive JN/scatters and influence checks complete.",flush=True)


if __name__=="__main__":
    os.umask(0)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("build","check"));parser.add_argument("--project",type=Path,required=True)
    parser.add_argument("--report",type=Path,required=True)
    parser.add_argument("--atlas-root",type=Path,default=Path(os.environ.get("FSLDIR","/usr/local/fsl"))/"data/atlases")
    args=parser.parse_args();args.project=args.project.resolve();args.report=args.report.resolve()
    if args.command=="build":build(args)
    else:verify(args.report)
