#!/usr/bin/env python3
"""Read-only brain/scatter/influence review of the completed FEVS VS-PPI finding."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import nibabel as nib
import numpy as np
from scipy.ndimage import label

import review_reward_followup as followup

common=followup.common
base=followup.base
ROOT=Path(__file__).resolve().parents[1]
KEY="connectivity/social_specific/fevsxpm25/z-3p1"
OUTCOME="[Social VS PPI(win-loss)] - [Nonsocial VS PPI(win-loss)]"


def select_job(plan):
    jobs=[job for job in plan["jobs"] if job["key"]==KEY]
    if len(jobs)!=1:raise ValueError("Completed FEVS VS target missing or duplicated")
    job=jobs[0]
    if (job["family"],job["outcome"],job["model"],job["z"])!=("connectivity","connectivity/social_specific","fevsxpm25",3.1):
        raise ValueError("Target is not the documented VS domain-by-valence job")
    definitions=[row for row in job["contrasts"] if row["term"]=="fevs" and row["direction"]=="negative"]
    if len(definitions)!=1:raise ValueError("Negative FEVS main-effect contrast missing or duplicated")
    return job,definitions[0]


def verify(report):
    manifest=json.loads((report/"review_manifest.json").read_text())
    if manifest["n"]!=97 or manifest["job"]!=KEY:raise ValueError("VS review identity differs")
    for name,digest in manifest["outputs"].items():
        if Path(name).name!=name or base.cohort.digest(report/name)!=digest:
            raise ValueError("VS review artifact differs: "+name)
    if manifest["renderer_sha256"]!=base.cohort.digest(Path(__file__)):
        raise ValueError("VS renderer changed; preserve this report version")
    common.audit.verify_records({r["path"]:r for r in json.loads((report.parent/"inputs-private.json").read_text())["sources"]},8)
    print("CHECK PASSED: FEVS VS report and input/design/result hashes verified; N=97; exclusions unchanged.",flush=True)


def build(args):
    report=args.report
    if (report/"review_manifest.json").exists():
        verify(report);print("REUSED: completed FEVS VS figures unchanged",flush=True);return
    if report.exists() and any(report.iterdir()):raise ValueError("Unsealed VS review exists; preserve it and choose a new version")
    folder=args.project/"derivatives/fsl/randomise/katie-reward-extension-v1"
    path=folder/"plan.json";digest=base.cohort.digest(path)
    if digest!=(folder/"plan.sha256").read_text().strip():raise ValueError("Extension plan checksum differs")
    plan=json.loads(path.read_text())
    if plan["n"]!=97 or len(plan["jobs"])!=220:raise ValueError("Unexpected frozen cohort/job inventory")
    job,definition=select_job(plan)
    records={r["path"]:r for r in plan["sources"]}
    for name,sha in plan["outputs"].items():common.audit.add_record(records,folder/name,sha)
    _,roster=base.cohort.read_table(ROOT/"data/derived/katie-cohort-v1/subjects.tsv")
    ids=[row["subject"] for row in roster]
    _,ordered=base.cohort.read_table(folder/"subjects.tsv")
    if len(ids)!=97 or len(set(ids))!=97 or [row["subject"] for row in ordered]!=ids:
        raise ValueError("VS stack/frozen roster order differs")
    raw=common.plots.raw_terms(ids)
    names,x=followup.check_design(job,definition,ids,raw)
    mask_path=Path(plan["masks"]["connectivity"])
    stack_path=Path(plan["images"]["connectivity/social_specific"])
    receipt=folder/"jobs"/KEY/"success.json"
    if not receipt.exists():raise ValueError("VS target unfinished; no partial attempt used")
    saved=json.loads(receipt.read_text());prefix=Path(saved["attempt"])/"randomise"
    if not prefix.parent.resolve().is_relative_to((receipt.parent/"attempts").resolve()):raise ValueError("Unsafe VS attempt path")
    if (saved["job"]!=job or saved["plan_sha256"]!=digest or saved["smoke"] is not False
            or saved["command"]!=base.command(dict(plan,mask=str(mask_path)),job,prefix)):
        raise ValueError("VS native command/receipt differs")
    if common.extension.products(prefix,str(mask_path),job["contrasts"])!=saved["outputs"]:
        raise ValueError("VS completed result inventory differs")
    for record in saved["outputs"]:common.audit.add_record(records,record["path"],record["sha256"],record["size"])
    anatomy=common.background.select([
        Path(os.environ.get("TEMPLATEFLOW_HOME",str(Path.home()/".cache/templateflow")))/"tpl-MNI152NLin6Asym/tpl-MNI152NLin6Asym_res-02_T1w.nii.gz",
        Path(os.environ.get("FSLDIR","/usr/local/fsl"))/"data/standard/MNI152_T1_2mm.nii.gz"])["path"]
    atlas_list=common.atlases(args.atlas_root)
    paths=[Path(__file__),Path(followup.__file__),Path(common.__file__),Path(common.plots.__file__),
        Path(common.audit.__file__),Path(common.extension.__file__),Path(common.financial.__file__),
        Path(common.background.__file__),common.financial.SCORES,Path(anatomy),path,receipt,mask_path,stack_path,
        ROOT/"data/derived/katie-cohort-v1/subjects.tsv",ROOT/"data/derived/model-review-v1/aligned_raw_terms.tsv",
        *[p for _,_,image,xml in atlas_list for p in (image,xml)]]
    for path in paths:
        record=base.fingerprint(path);common.audit.add_record(records,path,record["sha256"],record["size"])
    common.audit.verify_records(records,8)
    reference=nib.load(mask_path);support=reference.get_fdata()>0
    image=nib.load(stack_path);base.grid(reference,image,4)
    if image.shape[3]!=97:raise ValueError("VS domain-by-valence stack has wrong N")
    index=definition["index"]
    statistic=nib.load(str(prefix)+f"_tstat{index}.nii.gz").get_fdata()
    corrected=nib.load(str(prefix)+f"_clustere_corrp_tstat{index}.nii.gz").get_fdata()
    positive=nib.load(str(prefix)+f"_tstat{index-1}.nii.gz").get_fdata()
    if not np.allclose(statistic[support],-positive[support],rtol=1e-5,atol=1e-5):
        raise ValueError("VS directional coefficient maps disagree")
    selected=support&(corrected>.95)
    if np.any(statistic[selected]<job["t_cutoff"]-1e-5):raise ValueError("Corrected VS target below its native CDT")
    components,count=label(selected,structure=np.ones((3,3,3),dtype=bool))
    report.mkdir(parents=True,exist_ok=True)
    # The original PPI stack is read once; no activation or win-only stack is substituted.
    data=image.get_fdata(dtype=np.float32)
    clusters=[];fits=[];links=[]
    for component in range(1,count+1):
        region=components==component;ijk=np.argwhere(region);world=nib.affines.apply_affine(reference.affine,ijk)
        peak_ijk=ijk[np.argmax(statistic[region])];peak=nib.affines.apply_affine(reference.affine,peak_ijk)
        annotations=[dict(atlas="HarvardOxford-"+kind,
            peak_label=common.atlas_annotation(atlas,xml,peak[None,:])[0]["label"],
            cluster_overlap=common.atlas_annotation(atlas,xml,world)) for kind,atlas,_,xml in atlas_list]
        row=dict(component=component,voxels=int(region.sum()),volume_mm3=float(region.sum()*abs(np.linalg.det(reference.affine[:3,:3]))),
            cluster_fwe_p=float(1-corrected[region].max()),peak_coefficient_t=-float(statistic[tuple(peak_ijk)]),
            peak_mni_x=float(peak[0]),peak_mni_y=float(peak[1]),peak_mni_z=float(peak[2]),
            peak_atlas_labels="; ".join(a["atlas"]+": "+a["peak_label"] for a in annotations) or "Atlas files unavailable",
            atlas_annotations=annotations)
        clusters.append(row);identifier=f"fevs-vs-cluster-{component}"
        title="VS coupling: domain-by-valence contrast\nFEVS main effect at mean PM2.5"
        name=identifier+"-brain.png"
        followup.signed_brain(report/name,statistic,region,reference,anatomy,peak.tolist(),title,3.1)
        links.append((identifier+" location",name))
        y=data[region,:].mean(axis=0,dtype=np.float64)
        if not np.isfinite(y).all():raise ValueError("Nonfinite VS estimates; no participant dropped")
        name=identifier+"-scatter.png"
        fits.append(common.plots.roi_figure(dict(id=identifier,title=title+f" | cluster {component}",
            selection="SAME-SAMPLE SELECTED CLUSTER: descriptive only",path=str(report/name),
            details=str(report.parent/"participant-diagnostics"/(identifier+".tsv")),names=names,x=x.tolist(),y=y.tolist(),
            raw={key:value.tolist() for key,value in raw.items()},term="fevs",interaction=False,ids=ids)))
        links.append((identifier+" raw/adjusted scatter and influence",name))
        print("CLUSTER "+json.dumps({k:v for k,v in row.items() if k!="atlas_annotations"}),flush=True)
    if not count:
        followup.signed_brain(report/"fevs-vs-no-cluster.png",statistic,selected,reference,anatomy,[0,50,-5],"VS FEVS main effect: no corrected cluster",3.1)
        links.append(("No surviving corrected cluster","fevs-vs-no-cluster.png"))
    metadata=dict(n=97,family="connectivity",seed="Original VS PPI seed; unchanged",job=KEY,outcome="social_specific",
        outcome_formula=OUTCOME,term="fevs",direction="negative",context="FEVS main effect at mean PM2.5; NOT an interaction or win-only effect",
        model_columns=names,z=3.1,clusters=clusters,region_fits=fits,exclusions_changed=False,original_results_changed=False,
        new_inference=False,atlas_available=bool(atlas_list),caution="Same-sample selected-cluster descriptions; mapwise cluster-FWE only.")
    (report/"summary.json").write_text(base.cohort.json_text(metadata))
    fields=["component","voxels","volume_mm3","cluster_fwe_p","peak_coefficient_t","peak_mni_x","peak_mni_y","peak_mni_z","peak_atlas_labels"]
    (report/"clusters.tsv").write_text(base.review.tsv([{k:v for k,v in row.items() if k!="atlas_annotations"} for row in clusters],fields))
    lines=["# FEVS and VS Connectivity: Domain-by-Valence Contrast", "", "N=97; settled exclusions, running jobs and completed results unchanged.",
        "Outcome: `"+OUTCOME+"`. This is a difference of task-modulated VS coupling, not activation or win-only connectivity.",
        "Target: negative FEVS main effect at mean PM2.5, from the full FEVS + PM2.5 + FEVS x PM2.5 model. This is NOT the interaction.",
        "Other covariates remain age, gender, scanner era, signed FD and tSNR differences. Blue indicates a negative coefficient.",
        "A negative coefficient means a decreasing social-minus-nonsocial valence-related coupling difference with FEVS; it does not by itself imply globally weaker VS connectivity or isolate winning versus losing.",
        "Cluster-FWE p<.05, CDT Z-equivalent 3.1; mapwise correction only, not across exploratory models/outcomes/CDTs.",
        "Raw and adjusted scatters retain all 97 participants. The adjusted slope is conditional at mean PM2.5, not a JN/moderation plot.",
        "HC3 intervals, Cook's D, leverage and leave-one-out coefficients describe influence; no participant is removed and no voxelwise sensitivity analysis is rerun.",
        "Selected-cluster scatterplots/intervals are descriptive, not independent confirmation. Atlas annotations are approximate MNI labels.",
        "Only aggregate figures/tables are published; input fingerprints and participant diagnostics stay outside this report.", "",
        "| Cluster | Voxels | Cluster-FWE p | Peak MNI x, y, z | Atlas |", "|---|---:|---:|---|---|"]
    for row in clusters:lines.append(f"| {row['component']} | {row['voxels']} | {row['cluster_fwe_p']:.4f} | {row['peak_mni_x']:.1f}, {row['peak_mni_y']:.1f}, {row['peak_mni_z']:.1f} | {row['peak_atlas_labels']} |")
    for title,name in links:lines += ["", "## "+title,"",f"![{title}]({name})",""]
    (report/"README.md").write_text("\n".join(lines))
    common.audit.verify_records(records,8)
    (report.parent/"inputs-private.json").write_text(base.cohort.json_text(dict(sources=list(records.values()))))
    outputs={path.name:base.cohort.digest(path) for path in report.iterdir() if path.is_file()}
    (report/"review_manifest.json").write_text(base.cohort.json_text(dict(n=97,job=KEY,outputs=outputs,
        renderer_sha256=base.cohort.digest(Path(__file__)),new_inference=False,exclusions_changed=False)))
    verify(report)
    print("REVIEW PASSED: FEVS VS cluster location, N=97 scatters and influence diagnostics verified.",flush=True)


if __name__=="__main__":
    os.umask(0)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("build","check"));parser.add_argument("--project",type=Path,required=True)
    parser.add_argument("--report",type=Path,required=True)
    parser.add_argument("--atlas-root",type=Path,default=Path(os.environ.get("FSLDIR","/usr/local/fsl"))/"data/atlases")
    args=parser.parse_args();args.project=args.project.resolve();args.report=args.report.resolve()
    if args.command=="build":build(args)
    else:verify(args.report)
