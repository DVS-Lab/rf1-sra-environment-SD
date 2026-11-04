#!/usr/bin/env python3
"""Add only the missing N=97 social-win-minus-nonsocial-win intercept tests."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
import os
from pathlib import Path
import signal
import tempfile

import nibabel as nib
import numpy as np
from scipy.stats import norm, t

import run_fevs_imaging_adjustments as adjustments

base=adjustments.base
ROOT=Path(__file__).resolve().parents[1]
VERSION="katie-social-win-mean-v1"


def saved_plan(folder):
    path=folder/"plan.json"
    if base.cohort.digest(path)!=(folder/"plan.sha256").read_text().strip():
        raise ValueError("Saved task plan changed")
    plan=json.loads(path.read_text())
    adjustments.extension.audit.verify_records({r["path"]:r for r in plan["sources"]},24)
    for name,sha in plan["outputs"].items():
        if base.cohort.digest(folder/name)!=sha:raise ValueError("Saved task artifact changed")
    return plan


def task_design(group,ids):
    original=next(j for j in group["jobs"] if j["outcome"]=="social_specific" and j["z"]==3.1)
    path=Path(original["design"])
    fields,rows=base.cohort.read_table(path.with_suffix(".tsv"))
    names=fields[1:];x=adjustments.extension.audit.matrix(path)
    if (len(ids)!=97 or len(set(ids))!=97 or [r["subject"] for r in rows]!=ids
            or names!=adjustments.COMMON or x.shape!=(97,7) or not np.isfinite(x).all()
            or np.linalg.matrix_rank(x)!=7 or not np.array_equal(x[:,0],np.ones(97))
            or not np.allclose(x[:,1:].mean(axis=0),0,rtol=0,atol=1e-10)
            or not np.allclose(x,[[float(r[n]) for n in names] for r in rows],rtol=0,atol=1e-12)):
        raise ValueError("Original centered group design or N=97 order differs")
    return names,x,path


def build(args):
    if (args.output/"plan.json").exists():return check(args)
    if args.output.exists() and any(args.output.iterdir()):raise ValueError("Unrecognized outputs; refusing overwrite")
    v2=args.project/"derivatives/fsl/randomise"/adjustments.VERSION
    prior=base.load_plan(v2)
    group_folder=args.project/"derivatives/fsl/randomise/katie-remaining-v1/activation"
    group=saved_plan(group_folder)
    _,roster=base.cohort.read_table(v2/"subjects.tsv");ids=[r["subject"] for r in roster]
    _,ordered=base.cohort.read_table(group_folder/"subjects.tsv")
    _,approved=base.cohort.read_table(ROOT/"data/derived/katie-cohort-v1/subjects.tsv")
    if ordered!=roster or approved!=roster or prior["n"]!=97 or group["n"]!=97:
        raise ValueError("Frozen image order/cohort differs; no participants dropped")
    names,x,source_design=task_design(group,ids)
    reference=nib.load(group["mask"]);other=nib.load(prior["masks"]["activation"])
    base.grid(reference,other)
    if not np.array_equal(reference.get_fdata(),other.get_fdata()):raise ValueError("Original group and component masks differ")
    image=prior["images"]["activation/win_only"]
    loaded=nib.load(image);base.grid(reference,loaded,4)
    if loaded.shape[3]!=97:raise ValueError("Expected exact original 97-volume social-win difference stack")
    jobs=[dict(key="social_win/group_mean/z-"+str(z).replace(".","p"),outcome="social_win",model="group_mean",
        z=z,residual_dof=90,t_cutoff=float(t.isf(norm.sf(z),90)),permutations=10000,seed=20261101,
        design=str(args.output/"design.mat"),contrast=str(args.output/"design.con")) for z in (2.6,3.1)]
    records={r["path"]:r for r in prior["sources"]}
    for r in group["sources"]:adjustments.extension.audit.add_record(records,r["path"],r["sha256"],r.get("size"))
    paths=[Path(__file__),Path(base.__file__),Path(adjustments.__file__),source_design,source_design.with_suffix(".tsv"),
           Path(image),Path(group["mask"]),Path(group["randomise"]),v2/"plan.json",v2/"plan.sha256",
           group_folder/"plan.json",group_folder/"plan.sha256",group_folder/"subjects.tsv"]
    paths += [group_folder/p for p in group["outputs"]]
    for path in paths:
        r=base.fingerprint(path);adjustments.extension.audit.add_record(records,r["path"],r["sha256"],r["size"])
    sources=adjustments.normalize_sources(records)
    stage=Path(tempfile.mkdtemp(prefix=".social-win-mean-",dir=args.output.parent));stage.chmod(0o777)
    for name,text in {"design.mat":base.vest_matrix(x),"design.con":base.vest_contrasts(names,"ones"),
                      "design.tsv":base.review.tsv([dict(subject=s,**dict(zip(names,row))) for s,row in zip(ids,x)]),
                      "subjects.tsv":base.review.tsv([dict(subject=s) for s in ids])}.items():(stage/name).write_text(text)
    plan=dict(n=97,project=str(args.project),data_root=str(ROOT),jobs=jobs,columns=names,mask=group["mask"],
        images=dict(social_win=image),randomise=group["randomise"],sources=sources,sign_flipping_required=True,
        code_sha256=base.cohort.digest(Path(__file__)),exclusions_changed=False,completed_outputs_changed=False,
        outputs={p.name:base.cohort.digest(p) for p in stage.iterdir()})
    base.write_json(stage/"plan.json",plan);(stage/"plan.sha256").write_text(base.cohort.digest(stage/"plan.json"))
    stage.rename(args.output)
    return check(args)


def check(args):
    plan=base.load_plan(args.output)
    if (plan["n"]!=97 or plan["project"]!=str(args.project) or len(plan["jobs"])!=2
            or plan["code_sha256"]!=base.cohort.digest(Path(__file__)) or not plan["sign_flipping_required"]
            or plan["exclusions_changed"] or plan["completed_outputs_changed"]):raise ValueError("Frozen task-mean plan differs")
    names,rows=base.cohort.read_table(args.output/"design.tsv")
    _,roster=base.cohort.read_table(args.output/"subjects.tsv")
    x=adjustments.extension.audit.matrix(args.output/"design.mat")
    contrasts=adjustments.extension.audit.matrix(args.output/"design.con")
    if names!=["subject",*adjustments.COMMON] or [r["subject"] for r in rows]!=[r["subject"] for r in roster]:
        raise ValueError("Task mean design/volume labels differ")
    expected=np.zeros((2,7));expected[0,0]=1;expected[1,0]=-1
    if x.shape!=(97,7) or np.linalg.matrix_rank(x)!=7 or not np.array_equal(contrasts,expected):
        raise ValueError("Task mean must explicitly contrast the intercept in both directions")
    for name,sha in plan["outputs"].items():
        if base.cohort.digest(args.output/name)!=sha:raise ValueError("Frozen task input changed")
    print("CHECK PASSED: N=97; explicit social-win minus nonsocial-win intercept; original seven-column centered design; two CDTs; no old jobs rerun.",flush=True)
    return plan


def completed(plan,job,folder):
    saved=json.loads((folder/"jobs"/job["key"]/"success.json").read_text())
    prefix=Path(saved["attempt"])/"randomise"
    if (not prefix.parent.resolve().is_relative_to((folder/"jobs"/job["key"]/"attempts").resolve())
            or saved["job"]!=job or saved["plan_sha256"]!=base.cohort.digest(folder/"plan.json") or saved["smoke"]
            or saved["command"]!=base.command(plan,job,prefix) or base.output_images(prefix,plan["mask"])!=saved["outputs"]):
        raise ValueError("Completed task-mean receipt or products differ")
    return prefix,saved["outputs"]


def verify_smoke(folder,plan):
    receipt=folder/"smoke/success.json"
    smoke=json.loads(receipt.read_text())
    prefix=Path(smoke["attempt"])/"randomise"
    if (not prefix.parent.resolve().is_relative_to((folder/"smoke/attempts").resolve())
            or smoke["plan_sha256"]!=base.cohort.digest(folder/"plan.json") or smoke["job"]!=plan["jobs"][0]
            or not smoke["smoke"] or smoke["command"]!=base.command(plan,plan["jobs"][0],prefix,permutations=2)
            or base.output_images(prefix,plan["mask"])!=smoke["outputs"]):
        raise ValueError("Native sign-flip smoke receipt or products differ")
    text=(Path(smoke["attempt"])/"console.log").read_text().lower()
    if not ("sign-flipping" in text or "sign flipping" in text):raise ValueError("Native smoke did not confirm sign flipping")
    return [base.fingerprint(receipt),base.fingerprint(Path(smoke["attempt"])/"console.log"),*smoke["outputs"]]


def validate(args,plan):
    verify_smoke(args.output,plan)
    maps=[]
    for job in plan["jobs"]:
        prefix,_=completed(plan,job,args.output)
        for index,direction in ((1,"positive"),(2,"negative")):
            row,_=adjustments.summary.map_summary(job,direction,nib.load(str(prefix)+f"_tstat{index}.nii.gz"),
                nib.load(str(prefix)+f"_clustere_corrp_tstat{index}.nii.gz"),nib.load(plan["mask"]))
            maps.append(row)
    (args.output/"maps.tsv").write_text(base.review.tsv(maps))
    base.verify_sources(plan["sources"])
    print("CHECK PASSED: 2/2 social-win task-mean jobs, four directional maps and native sign-flip gate verified; N=97 and previous results unchanged.",flush=True)


def run(args):
    plan=build(args);sha=base.cohort.digest(args.output/"plan.json")
    base.execute(plan,plan["jobs"][0],args.output/"smoke",sha,smoke=True)
    receipt=json.loads((args.output/"smoke/success.json").read_text())
    text=(Path(receipt["attempt"])/"console.log").read_text().lower()
    if not ("sign-flipping" in text or "sign flipping" in text):raise ValueError("No native sign-flip confirmation; full jobs not launched")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(base.execute,plan,j,args.output/"jobs"/j["key"],sha) for j in plan["jobs"]]
        outcomes=[f.result() for f in futures]
    if any(s not in ("COMPLETED","REUSED") for s in outcomes):raise RuntimeError("Task-mean jobs incomplete; preserve and resume")
    validate(args,plan)


def main():
    os.umask(0)
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("command",choices=("run","check-results"));p.add_argument("--project",type=Path,required=True)
    args=p.parse_args();args.project=args.project.resolve();args.output=args.project/"derivatives/fsl/randomise"/VERSION
    args.output.parent.mkdir(parents=True,exist_ok=True)
    signal.signal(signal.SIGTERM,base.stop);signal.signal(signal.SIGINT,base.stop)
    with (args.output.parent/("."+VERSION+".lock")).open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);base.LEASE_FD=lock.fileno()
        run(args) if args.command=="run" else validate(args,check(args))


if __name__=="__main__":main()
