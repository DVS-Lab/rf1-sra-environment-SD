#!/usr/bin/env python3
"""Read-only fixed-slice comparison of original and adjusted FEVS maps."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np

import review_fevs_wins as views
import run_fevs_imaging_adjustments as adjustment

base = adjustment.base
ROOT = Path(__file__).resolve().parents[1]
ORDER = ("baseline", "adi", "ecog", "adi_ecog")


def geometry(selected, statistic, reference, original):
    count = int(selected.sum())
    overlap = int((selected & original).sum())
    total = count + int(original.sum())
    result = dict(voxels=count, original_overlap_voxels=overlap,
                  fraction_current_in_original=overlap/count if count else None,
                  dice=2*overlap/total if total else None)
    if not count:
        return dict(result, peak_mni=None, centroid_mni=None, peak_in_original=None)
    indices = np.argwhere(selected)
    peak = indices[np.argmax(statistic[selected])]
    world = nib.affines.apply_affine(reference.affine, indices)
    return dict(result, peak_mni=nib.affines.apply_affine(reference.affine, peak).tolist(),
                centroid_mni=world.mean(axis=0).tolist(), peak_in_original=bool(original[tuple(peak)]))


def collect(plan, output):
    original_folder = Path(plan["original"])
    original_plan = json.loads((original_folder/"plan.json").read_text())
    groups, records = {}, {}
    _, published = base.cohort.read_table(output/"report/maps.tsv")
    for target, family, _, _ in adjustment.TARGETS:
        direction = "positive" if family == "activation" else "negative"
        source = next(b["job"] for b in plan["baselines"] if b["target"]==target and b["job"]["z"]==3.1)
        jobs = [("baseline", source, original_plan, original_folder)]
        jobs += [(name, next(j for j in plan["jobs"] if j["target"]==target and j["adjustment"]==name and j["z"]==3.1),
                  plan, output) for name in ORDER[1:]]
        reference = nib.load(plan["masks"][family])
        support = reference.get_fdata()>0
        rows = []
        for name, job, owner, folder in jobs:
            prefix, evidence = adjustment.completed(owner, job, folder)
            for r in evidence:
                adjustment.extension.audit.add_record(records,r["path"],r["sha256"],r["size"])
            definition = next(d for d in job["contrasts"] if d["term"]=="fevs" and d["direction"]==direction)
            index = definition["index"]
            statistic_image = nib.load(str(prefix)+f"_tstat{index}.nii.gz")
            probability_image = nib.load(str(prefix)+f"_clustere_corrp_tstat{index}.nii.gz")
            base.grid(reference,statistic_image);base.grid(reference,probability_image)
            statistic, probability = statistic_image.get_fdata(), probability_image.get_fdata()
            selected = support & (probability>.95)
            if np.any(statistic[selected]<job["t_cutoff"]-1e-5):
                raise ValueError("Corrected target falls below its native CDT")
            p = float(1-probability[support].max())
            expected = [r for r in published if (r["target"],r["adjustment"],r["z"],r["direction"]) == (target,name,"3.1",direction)]
            if (len(expected)!=1 or int(expected[0]["significant_voxels"])!=int(selected.sum())
                    or not np.isclose(float(expected[0]["min_cluster_fwe_p"]),p,rtol=0,atol=1e-12)):
                raise ValueError("Map differs from the validated published summary")
            rows.append(dict(target=target,adjustment=name,family=family,direction=direction,p=p,
                statistic=statistic,selected=selected,signed_t=statistic if direction=="positive" else -statistic))
        if not rows[0]["selected"].any():
            raise ValueError("Original focal cluster missing; no data-selected alternative target")
        original = rows[0]["selected"]
        for row in rows:
            row["location"] = geometry(row["selected"],row["statistic"],reference,original)
        peak = np.asarray(rows[0]["location"]["peak_mni"])
        for row in rows:
            current = row["location"]["peak_mni"]
            row["location"]["peak_shift_mm"] = float(np.linalg.norm(np.asarray(current)-peak)) if current else None
        groups[target] = dict(reference=reference, rows=rows, cut_coords=peak.tolist())
    return groups, list(records.values())


def render(path, target, group, anatomy):
    from nilearn import plotting
    fig = plt.figure(figsize=(12,14))
    fig.suptitle(adjustment.LABELS[target]+"\nSame original-peak slices and color scale in every row",fontsize=12,y=.985)
    reference = group["reference"]
    original = group["rows"][0]["selected"]
    vmax = max(5.,max(float(np.max(np.abs(r["signed_t"]))) for r in group["rows"]))
    for i,row in enumerate(group["rows"]):
        bottom = .75-i*.225
        axis = fig.add_axes([.025,bottom,.95,.19])
        # |t|=2 is display-only; gold contours carry the saved cluster-FWE inference.
        image = nib.Nifti1Image(row["signed_t"].astype(np.float32),reference.affine)
        display = plotting.plot_stat_map(image,bg_img=anatomy,display_mode="ortho",cut_coords=group["cut_coords"],
            axes=axis,figure=fig,cmap="RdBu_r",threshold=2.,vmax=vmax,symmetric_cbar=True,colorbar=True,draw_cross=True)
        display.add_contours(nib.Nifti1Image(original.astype(np.uint8),reference.affine),levels=[.5],colors=["cyan"],linewidths=1.5)
        if row["selected"].any() and i:
            display.add_contours(nib.Nifti1Image(row["selected"].astype(np.uint8),reference.affine),levels=[.5],colors=["gold"],linewidths=1.)
        fig.text(.03,bottom+.198,f"{row['adjustment']} | cluster-FWE p={row['p']:.4f} | {row['location']['voxels']} corrected voxels",
                 fontsize=11)
    fig.text(.5,.035,"N=97; scoring provisional; CDT Z-equivalent 3.1; cyan = original corrected cluster; gold = adjusted corrected cluster.\n"
             "Red/blue = positive/negative FEVS coefficient. Background t shading at |t|>=2 is descriptive, NOT a new significance threshold.\n"
             "Fixed slices show position, not every voxel; coordinates and atlas overlaps are approximate anatomical descriptions.",
             ha="center",fontsize=9)
    views.plots.save_figure(fig,path)


def verify(args):
    report = args.report
    manifest = json.loads((report/"review_manifest.json").read_text())
    if (manifest["n"]!=97 or not manifest["provisional_scoring"] or manifest["new_inference"]
            or manifest["renderer_sha256"]!=base.cohort.digest(Path(__file__))):
        raise ValueError("Frozen map review identity differs")
    for name,digest in manifest["outputs"].items():
        if Path(name).name!=name or base.cohort.digest(report/name)!=digest:
            raise ValueError("Map review artifact changed")
    saved = json.loads((report.parent/"inputs-private.json").read_text())
    adjustment.extension.audit.verify_records({r["path"]:r for r in saved["sources"]},8)
    print("CHECK PASSED: original/adjusted maps, fixed-slice figures and source hashes verified; N=97; no inference or exclusions changed.",flush=True)


def build(args):
    if (args.report/"review_manifest.json").exists():
        verify(args);return
    if args.report.exists() and any(args.report.iterdir()):
        raise ValueError("Unsealed review exists; preserve it and choose another version")
    output = args.project/"derivatives/fsl/randomise"/adjustment.VERSION
    path = output/"plan.json"
    if base.cohort.digest(path)!=(output/"plan.sha256").read_text().strip():
        raise ValueError("Adjustment plan changed")
    plan = json.loads(path.read_text())
    frozen = Path(plan["data_root"])
    if (plan["n"]!=97 or plan["project"]!=str(args.project) or not plan["provisional_scoring"]
            or not frozen.resolve().is_relative_to((args.project/"work").resolve())):
        raise ValueError("Unexpected cohort, scoring or frozen release identity")
    # The original release verifies its own ROOT and implementation hash; never
    # substitute this newly archived renderer's data directory for the old one.
    subprocess.run([sys.executable,str(frozen/"code/run_fevs_imaging_adjustments.py"),"check", "--project",str(args.project)],check=True)
    groups,evidence = collect(plan,output)
    anatomy = views.background.select([Path(os.environ.get("TEMPLATEFLOW_HOME",str(Path.home()/".cache/templateflow")))/
        "tpl-MNI152NLin6Asym/tpl-MNI152NLin6Asym_res-02_T1w.nii.gz",
        Path(os.environ.get("FSLDIR","/usr/local/fsl"))/"data/standard/MNI152_T1_2mm.nii.gz"])["path"]
    atlases = views.atlases(args.atlas_root)
    records = {r["path"]:r for r in plan["sources"]}
    paths = [path,output/"plan.sha256",output/"report/maps.tsv",Path(__file__),Path(views.__file__),
             Path(adjustment.__file__),Path(views.background.__file__),Path(views.plots.__file__),Path(anatomy)]
    paths += [p for _,_,image,xml in atlases for p in (image,xml)]
    for r in evidence+[base.fingerprint(p) for p in paths]:
        adjustment.extension.audit.add_record(records,r["path"],r["sha256"],r["size"])
    args.report.mkdir(parents=True,exist_ok=True)
    locations,annotation,table = [],[],[]
    for target,group in groups.items():
        render(args.report/(target+".png"),target,group,anatomy)
        for row in group["rows"]:
            location = dict(target=target,adjustment=row["adjustment"],direction=row["direction"],
                            cluster_fwe_p=row["p"],**row["location"])
            locations.append(location)
            labels = []
            if row["selected"].any():
                world = nib.affines.apply_affine(group["reference"].affine,np.argwhere(row["selected"]))
                for kind,image,_,xml in atlases:
                    overlap = views.atlas_annotation(image,xml,world)
                    peak = views.atlas_annotation(image,xml,np.asarray([row["location"]["peak_mni"]]))
                    annotation.append(dict(target=target,adjustment=row["adjustment"],atlas=kind,
                                           peak_label=peak[0]["label"],overlap=overlap))
                    labels.append(kind+": "+peak[0]["label"])
            peak = row["location"]["peak_mni"]
            table.append(dict(target=target,adjustment=row["adjustment"],p=row["p"],voxels=row["location"]["voxels"],
                overlap=row["location"]["original_overlap_voxels"],dice=row["location"]["dice"],
                peak_mni="none" if peak is None else ", ".join(f"{v:.1f}" for v in peak),
                peak_shift_mm=row["location"]["peak_shift_mm"],peak_in_original=row["location"]["peak_in_original"],
                atlas_peak="; ".join(labels)))
    base.write_json(args.report/"locations.json",dict(n=97,provisional_scoring=True,locations=locations,
        atlas_annotations=annotation,atlas_available=bool(atlases),new_inference=False,exclusions_changed=False))
    (args.report/"locations.tsv").write_text(base.review.tsv(table))
    lines = ["# Original And Adjusted FEVS Map Locations", "", "N=97; read-only review; scoring provisional; no new inference or exclusions.",
        "Three predefined original findings, four conditions each. Both CDTs and directions remain in the full adjustment report; this anatomy review focuses on the original directions at CDT 3.1.",
        "Every row uses original-peak slices and a common within-target color scale. Cyan contours: original corrected cluster; gold: adjusted corrected cluster.",
        "The |t|>=2 background shading is descriptive, NOT a significance criterion. An absent gold contour means no corrected cluster, not a proven absent association.",
        "Dice/overlap and atlas nearest-voxel labels describe location, not independent replication or tissue segmentation. A shifted peak can remain inside the same cluster.", ""]
    for target,*_ in adjustment.TARGETS:
        lines += ["## "+adjustment.LABELS[target],"",f"![Original and adjusted maps]({target}.png)","",
                  "| Added | FWE p | Voxels | Overlap | Dice | Peak MNI mm | Shift mm | Peak in original |",
                  "|---|---:|---:|---:|---:|---|---:|---|"]
        for r in table:
            if r["target"]==target:
                dice="n/a" if not r["voxels"] else f"{r['dice']:.3f}"
                shift="n/a" if r["peak_shift_mm"] is None else f"{r['peak_shift_mm']:.1f}"
                lines.append(f"| {r['adjustment']} | {r['p']:.4f} | {r['voxels']} | {r['overlap']} | {dice} | {r['peak_mni']} | {shift} | {r['peak_in_original']} |")
        lines.append("")
    (args.report/"README.md").write_text("\n".join(lines))
    adjustment.extension.audit.verify_records(records,8)
    base.write_json(args.report.parent/"inputs-private.json",dict(sources=list(records.values())))
    names=["README.md","locations.tsv","locations.json",*[target+".png" for target,*_ in adjustment.TARGETS]]
    base.write_json(args.report/"review_manifest.json",dict(n=97,provisional_scoring=True,new_inference=False,
        renderer_sha256=base.cohort.digest(Path(__file__)),outputs={n:base.cohort.digest(args.report/n) for n in names}))
    verify(args)


def main():
    os.umask(0)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("build","check"))
    parser.add_argument("--project",type=Path,required=True)
    parser.add_argument("--report",type=Path,required=True)
    parser.add_argument("--atlas-root",type=Path,default=Path(os.environ.get("FSLDIR","/usr/local/fsl"))/"data/atlases")
    args=parser.parse_args();args.project=args.project.resolve();args.report=args.report.resolve()
    args.report.parent.mkdir(parents=True,exist_ok=True)
    with (args.report.parent/".review.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        build(args) if args.command=="build" else verify(args)


if __name__=="__main__":main()
