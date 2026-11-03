#!/usr/bin/env python3
"""Read-only targeted location/scatter review of the two completed FEVS win effects."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np
from nilearn import plotting
from scipy.ndimage import label

import audit_katie_results as audit
import plot_katie_results as plots
import review_financial_models as financial
import run_reward_extension as extension
import select_katie_background as background

ROOT=Path(__file__).resolve().parents[1]
TARGETS=("fevs","fevsxpm25")


def atlas_annotation(atlas_image,xml,world):
    names={int(node.attrib["index"])+1:(node.text or "").strip() for node in ET.parse(xml).findall(".//label")}
    indices=np.rint(nib.affines.apply_affine(np.linalg.inv(atlas_image.affine),world)).astype(int)
    valid=np.all((indices>=0)&(indices<np.asarray(atlas_image.shape)),axis=1)
    values=np.zeros(len(indices),dtype=int)
    data=np.asarray(atlas_image.dataobj)
    values[valid]=data[tuple(indices[valid].T)].astype(int)
    unique,counts=np.unique(values,return_counts=True)
    overlap=sorted([dict(label=names.get(int(v),"Unlabeled" if v==0 else f"Unknown atlas value {v}"),
                         voxels=int(n),fraction=float(n/len(world))) for v,n in zip(unique,counts)],
                   key=lambda r:r["voxels"],reverse=True)
    return overlap


def atlases(root):
    result=[]
    for kind,xml in (("cort","HarvardOxford-Cortical.xml"),("sub","HarvardOxford-Subcortical.xml")):
        image=root/f"HarvardOxford/HarvardOxford-{kind}-maxprob-thr25-2mm.nii.gz"
        labels=root/xml
        if image.is_file() and labels.is_file():
            loaded=nib.load(image)
            if loaded.ndim!=3:raise ValueError("Expected a 3D anatomical atlas")
            result.append((kind,loaded,image,labels))
    return result


def brain(path,statistic,selected,reference,anatomy,peak,title,footer):
    values=np.where(selected,statistic,0)
    fig=plt.figure(figsize=(11,4.5))
    fig.suptitle(title,fontsize=12,y=.98)
    axis=fig.add_axes([.02,.17,.95,.7])
    if selected.any():
        plotting.plot_stat_map(nib.Nifti1Image(values.astype(np.float32),reference.affine),bg_img=anatomy,
            display_mode="ortho",cut_coords=peak,axes=axis,figure=fig,cmap="Reds",threshold=1e-8,
            vmax=max(4.5,float(values.max())),symmetric_cbar=False,colorbar=True,draw_cross=True)
    else:
        plotting.plot_anat(anatomy,display_mode="ortho",cut_coords=[0,50,-5],axes=axis,figure=fig,colorbar=False)
    fig.text(.5,.025,footer,ha="center",fontsize=9)
    plots.save_figure(fig,path)


def verify(report,inputs,jobs=8):
    manifest=json.loads((report/"review_manifest.json").read_text())
    for name,digest in manifest["outputs"].items():
        if extension.base.cohort.digest(report/name)!=digest:raise ValueError("Targeted report artifact changed: "+name)
    audit.verify_records({r["path"]:r for r in json.loads(inputs.read_text())["sources"]},jobs)
    if manifest["renderer_sha256"]!=extension.base.cohort.digest(Path(__file__)):
        raise ValueError("Review implementation changed; preserve the existing version")
    print("CHECK PASSED: targeted report artifacts and recorded input/result hashes unchanged; no exclusions changed.",flush=True)


def build(args):
    base=extension.base;report=args.report;parent=report.parent
    private=parent/"inputs-private.json"
    if (report/"review_manifest.json").exists():
        verify(report,private);print("REUSED: completed targeted figures unchanged",flush=True);return
    if report.exists() and any(report.iterdir()):
        raise ValueError("Unsealed target report exists; preserve it and choose a new version")
    folder=args.project/"derivatives/fsl/randomise/katie-reward-extension-v1"
    plan_path=folder/"plan.json";digest=base.cohort.digest(plan_path)
    if digest!=(folder/"plan.sha256").read_text().strip():raise ValueError("Extension plan checksum differs")
    plan=json.loads(plan_path.read_text())
    if plan["n"]!=97 or len(plan["jobs"])!=220:raise ValueError("Unexpected cohort/analysis inventory")
    records={r["path"]:r for r in plan["sources"]}
    for name,sha in plan["outputs"].items():audit.add_record(records,folder/name,sha)
    chosen={}
    for model in TARGETS:
        job=next(j for j in plan["jobs"] if j["family"]=="activation" and j["outcome"]=="activation/win_only"
                 and j["model"]==model and j["z"]==3.1)
        definition=next(r for r in job["contrasts"] if r["term"]=="fevs" and r["direction"]=="positive")
        path=folder/"jobs"/job["key"]/"success.json"
        if not path.exists():raise ValueError("Target job not finished; no partial attempt used: "+job["key"])
        saved=json.loads(path.read_text());prefix=Path(saved["attempt"])/"randomise"
        if not prefix.parent.resolve().is_relative_to((path.parent/"attempts").resolve()):raise ValueError("Unsafe target attempt path")
        if (saved["job"]!=job or saved["plan_sha256"]!=digest or saved["smoke"]
                or saved["command"]!=base.command(dict(plan,mask=plan["masks"]["activation"]),job,prefix)):
            raise ValueError("Target native command/receipt differs")
        if extension.products(prefix,plan["masks"]["activation"],job["contrasts"])!=saved["outputs"]:
            raise ValueError("Target result inventory differs")
        for r in saved["outputs"]:audit.add_record(records,r["path"],r["sha256"],r["size"])
        audit.add_record(records,path,base.cohort.digest(path))
        chosen[model]=(job,definition,prefix)
    _,roster=base.cohort.read_table(ROOT/"data/derived/katie-cohort-v1/subjects.tsv")
    ids=[r["subject"] for r in roster]
    scores,_=financial.read_scores(financial.SCORES,ids)
    _,raw=base.cohort.read_table(ROOT/"data/derived/model-review-v1/aligned_raw_terms.tsv")
    if len(ids)!=97 or [r["subject"] for r in raw]!=ids:raise ValueError("Raw-score/subject order differs")
    raw_scores=dict(fevs=[r["fevs"] for r in scores],pm25=[float(r["pm25"]) for r in raw])
    anatomy=background.select([
        Path(os.environ.get("TEMPLATEFLOW_HOME",str(Path.home()/".cache/templateflow")))/"tpl-MNI152NLin6Asym/tpl-MNI152NLin6Asym_res-02_T1w.nii.gz",
        Path(os.environ.get("FSLDIR","/usr/local/fsl"))/"data/standard/MNI152_T1_2mm.nii.gz"])["path"]
    atlas_list=atlases(args.atlas_root)
    for path in [Path(__file__),Path(plots.__file__),Path(audit.__file__),Path(extension.__file__),
                 Path(financial.__file__),Path(background.__file__),financial.SCORES,Path(anatomy),plan_path,
                 ROOT/"data/derived/katie-cohort-v1/subjects.tsv",ROOT/"data/derived/model-review-v1/aligned_raw_terms.tsv",
                 *[p for _,_,image,xml in atlas_list for p in (image,xml)]]:
        r=base.fingerprint(path);audit.add_record(records,path,r["sha256"],r["size"])
    audit.verify_records(records,8)
    report.mkdir(parents=True,exist_ok=True);parent.mkdir(parents=True,exist_ok=True)
    reference=nib.load(plan["masks"]["activation"]);support=reference.get_fdata()>0
    image=nib.load(plan["images"]["activation/win_only"]);base.grid(reference,image,4)
    if image.shape[3]!=97:raise ValueError("Win-difference stack has wrong N")
    # Read the gzip-compressed 4D stack once, not once per participant/cluster.
    data=image.get_fdata(dtype=np.float32)
    cluster_rows=[];fits=[];selected_models={};peak_models={};links=[];model_columns={}
    for model,(job,definition,prefix) in chosen.items():
        fields,table=base.cohort.read_table(Path(job["design"]).with_suffix(".tsv"));names=fields[1:]
        model_columns[model]=names
        x=audit.matrix(job["design"]);contrasts=audit.matrix(job["contrast"])
        if ([r["subject"] for r in table]!=ids or x.shape[0]!=97 or np.linalg.matrix_rank(x)!=x.shape[1]
                or not np.allclose(x,np.array([[float(r[n]) for n in names] for r in table]),rtol=0,atol=1e-12)):
            raise ValueError("Target design labels, matrix or participant order differ")
        expected=np.zeros(len(names));expected[names.index("fevs")]=1
        if not np.array_equal(contrasts[definition["index"]-1],expected):raise ValueError("Not the FEVS main-effect contrast")
        index=definition["index"]
        t_image=nib.load(str(prefix)+f"_tstat{index}.nii.gz");p_image=nib.load(str(prefix)+f"_clustere_corrp_tstat{index}.nii.gz")
        base.grid(reference,t_image);base.grid(reference,p_image)
        statistic,corrected=t_image.get_fdata(),p_image.get_fdata()
        if (not np.isfinite(statistic).all() or not np.isfinite(corrected).all()
                or corrected.min()<0 or corrected.max()>1):raise ValueError("Invalid target statistic/probability image")
        selected=support&(corrected>.95)
        if np.any(statistic[selected]<job["t_cutoff"]-1e-5):raise ValueError("Corrected target falls below its native CDT")
        selected_models[model]=selected
        components,count=label(selected,structure=np.ones((3,3,3),dtype=bool))
        context="FEVS main effect, standalone" if model=="fevs" else "FEVS main effect at mean PM2.5; NOT the interaction"
        world_peak=[0,50,-5]
        if selected.any():
            ijk=np.argwhere(selected);peak=ijk[np.argmax(statistic[selected])]
            world_peak=nib.affines.apply_affine(reference.affine,peak).tolist();peak_models[model]=world_peak
        brain_name=model+"-brain.png"
        brain(report/brain_name,statistic,selected,reference,anatomy,world_peak,
              "Social win minus nonsocial win | "+context,
              "N=97; positive FEVS coefficient; cluster-FWE p<.05; CDT Z-equivalent 3.1.\n"
              "Coordinates are MNI mm. Atlas annotations describe location, not independent confirmation.")
        links.append((context,brain_name))
        for component in range(1,count+1):
            mask=components==component;ijk=np.argwhere(mask)
            peak=ijk[np.argmax(statistic[mask])];world=nib.affines.apply_affine(reference.affine,ijk)
            peak_world=nib.affines.apply_affine(reference.affine,peak)
            annotations=[]
            for kind,atlas,_,xml in atlas_list:
                annotations.append(dict(atlas="HarvardOxford-"+kind,
                    peak_label=atlas_annotation(atlas,xml,peak_world[None,:])[0]["label"],
                    cluster_overlap=atlas_annotation(atlas,xml,world)))
            name=f"{model}-cluster-{component}"
            row=dict(model=model,term="fevs",context=context,component=component,voxels=int(mask.sum()),
                volume_mm3=float(mask.sum()*abs(np.linalg.det(reference.affine[:3,:3]))),
                cluster_fwe_p=float(1-corrected[mask].max()),peak_t=float(statistic[tuple(peak)]),
                peak_mni_x=float(peak_world[0]),peak_mni_y=float(peak_world[1]),peak_mni_z=float(peak_world[2]),
                peak_atlas_labels="; ".join(a["atlas"]+": "+a["peak_label"] for a in annotations) or "Atlas files unavailable",
                atlas_annotations=annotations)
            cluster_rows.append(row)
            y=data[mask,:].mean(axis=0,dtype=np.float64)
            if not np.isfinite(y).all():raise ValueError("Nonfinite region estimates; no participant dropped")
            fitted=plots.roi_figure(dict(id=name,title="Social win minus nonsocial win | "+context+f" | cluster {component}",
                selection="SAME-SAMPLE SELECTED CLUSTER: descriptive only",path=str(report/(name+"-scatter.png")),
                details=str(parent/"participant-diagnostics"/(name+".tsv")),names=names,x=x.tolist(),y=y.tolist(),
                raw=raw_scores,term="fevs",interaction=False,ids=ids))
            fits.append(fitted);links.append((name+" raw/adjusted scatter and influence",name+"-scatter.png"))
            print("CLUSTER "+json.dumps({k:v for k,v in row.items() if k!="atlas_annotations"}),flush=True)
    a,b=(selected_models[m] for m in TARGETS);intersection=int((a&b).sum());union=int((a|b).sum())
    overlap=dict(intersection_voxels=intersection,union_voxels=union,
        dice=float(2*intersection/(a.sum()+b.sum())) if a.sum()+b.sum() else None)
    if len(peak_models)==2:
        overlap["peak_distance_mm"]=float(np.linalg.norm(np.asarray(peak_models["fevs"])-np.asarray(peak_models["fevsxpm25"])))
    else:
        overlap["note"]="One or both targets have no corrected cluster"
    metadata=dict(n=97,outcome="Social Doors win minus Doors win",target_z=3.1,term="positive FEVS main effect",
        clusters=cluster_rows,overlap=overlap,region_fits=fits,model_columns=model_columns,atlas_available=bool(atlas_list),
        selection_warning="Cluster-selected scatterplots and analytical confidence intervals are descriptive, not independent inference.",
        exclusions_changed=False,original_results_changed=False,new_inference=False)
    (report/"summary.json").write_text(base.cohort.json_text(metadata))
    table=[{k:v for k,v in r.items() if k!="atlas_annotations"} for r in cluster_rows]
    fields=["model","term","context","component","voxels","volume_mm3","cluster_fwe_p","peak_t","peak_mni_x","peak_mni_y","peak_mni_z","peak_atlas_labels"]
    (report/"clusters.tsv").write_text(base.review.tsv(table,fields))
    lines=["# FEVS: Social Win Minus Nonsocial Win", "", "N=97; settled exclusions unchanged. No inference or preprocessing rerun.",
        "These are the two preselected positive FEVS main effects at CDT Z-equivalent 3.1, cluster-FWE p<.05.",
        "The FEVS x PM2.5 model plot is conditional at mean PM2.5, NOT a moderation/JN plot.",
        "Cluster-selected scatterplots/intervals are descriptive and not independent confirmation.",
        "All 97 participants remain in every scatterplot; influence flags do not create exclusions.",
        "The models share participants and outcome images and are not independent replications.",
        "Both models adjust for age, gender, scanner era, signed FD and tSNR differences. The conditional model also includes PM2.5 and FEVS x PM2.5.",
        "Cluster-FWE applies per map, not across the exploratory models, outcomes, directions and thresholds.",
        "Atlas labels use nearest-neighbor MNI coordinate lookup in local Harvard-Oxford max-probability 25% atlases; labels are approximate anatomical annotations.",
        "No masks/statistical images, subject tables or participant-level influence files are published.", "",
        "| Model | Cluster | Voxels | Cluster-FWE p | Peak MNI x, y, z | Peak Atlas Label |", "|---|---:|---:|---:|---|---|"]
    for r in cluster_rows:lines.append(f"| {r['model']} | {r['component']} | {r['voxels']} | {r['cluster_fwe_p']:.4f} | {r['peak_mni_x']:.1f}, {r['peak_mni_y']:.1f}, {r['peak_mni_z']:.1f} | {r['peak_atlas_labels']} |")
    lines += ["", "Overlap: `"+json.dumps(overlap)+"`", ""]
    for title,name in links:lines += ["## "+title,"",f"![{title}]({name})",""]
    (report/"README.md").write_text("\n".join(lines))
    audit.verify_records(records,8)
    private.write_text(base.cohort.json_text(dict(sources=list(records.values()))))
    outputs={p.name:base.cohort.digest(p) for p in report.iterdir() if p.is_file()}
    (report/"review_manifest.json").write_text(base.cohort.json_text(dict(n=97,outputs=outputs,
        renderer_sha256=base.cohort.digest(Path(__file__)),target_models=list(TARGETS),new_inference=False,exclusions_changed=False)))
    verify(report,private)
    print("OVERLAP "+json.dumps(overlap),flush=True)
    print("REVIEW PASSED: target brain views, atlas locations, N=97 scatters and input/result hashes verified.",flush=True)


if __name__=="__main__":
    os.umask(0)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("build","check"))
    parser.add_argument("--project",type=Path,required=True)
    parser.add_argument("--report",type=Path,required=True)
    parser.add_argument("--atlas-root",type=Path,default=Path(os.environ.get("FSLDIR","/usr/local/fsl"))/"data/atlases")
    args=parser.parse_args();args.project=args.project.resolve();args.report=args.report.resolve()
    if args.command=="build":build(args)
    else:verify(args.report,args.report.parent/"inputs-private.json")
