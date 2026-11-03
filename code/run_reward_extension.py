#!/usr/bin/env python3
"""Complete reward-component/model coverage without replacing previous analyses."""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

import nibabel as nib
import numpy as np
from scipy.stats import norm, t

import audit_katie_results as audit
import run_pm25_components as components
import run_katie_remaining as remaining
import run_katie_randomise as base
import summarize_katie_randomise as summary

ROOT = Path(__file__).resolve().parents[1]
CORE_MODELS = ("adi", "pm25", "adixmspss", "pm25xmspss", "adixecog", "pm25xecog",
               "fevs", "oafem", *[s+"x"+m for s in ("fevs", "oafem") for m in ("mspss", "adi", "pm25", "ecog")])
OLD_OUTCOMES = ("social_specific", "average")
NEW_OUTCOMES = ("win_only", "loss_only")
FAMILIES = ("activation", "connectivity")


def definitions(terms):
    return [dict(index=2*i+j+1, term=term, direction=direction)
            for i, term in enumerate(terms) for j, direction in enumerate(("positive", "negative"))]


def contrast_text(names, terms):
    if len(set(terms)) != len(terms) or any(names.count(term) != 1 for term in terms):
        raise ValueError("Scientific contrast terms are missing or duplicated")
    rows = definitions(terms)
    text = "".join(f"/ContrastName{r['index']}\t{r['term']}_{r['direction']}\n" for r in rows)
    text += f"/NumWaves\t{len(names)}\n/NumContrasts\t{len(rows)}\n"
    text += "/PPheights\t"+"\t".join("1" for _ in rows)+"\n/RequiredEffect\t"+"\t".join("1" for _ in rows)+"\n/Matrix\n"
    for row in rows:
        weight = 1 if row["direction"] == "positive" else -1
        text += "\t".join(str(weight if n == row["term"] else 0) for n in names)+"\n"
    return text, rows


def scientific_terms(model, names):
    if model not in CORE_MODELS or names[:1] != ["ones"] or len(names) not in (8, 10):
        raise ValueError("Unexpected previous scientific model")
    terms = names[7:]
    expected = [model] if "x" not in model else [*model.split("x"), model]
    if terms != expected:
        raise ValueError("Scientific columns do not match the model label")
    return terms


def catalog(output, ids, units, additive_baseline):
    refs, completed = {}, {}
    for unit in units:
        if unit["batch"] == "group_activation":
            continue
        family, model = unit["family"], unit["job"]["model"]
        outcome = unit["job"]["outcome"].split("/")[-1]
        names, x = unit["names"], audit.matrix(unit["job"]["design"])
        terms = scientific_terms(model, names)
        key = (family, outcome, model)
        if key in refs and (refs[key][0] != names or not np.array_equal(refs[key][1], x)):
            raise ValueError("Previous batches disagree on a scientific design")
        refs[key] = (names, x)
        mapkey = (*key, unit["job"]["z"])
        present = completed.setdefault(mapkey, {})
        for definition in unit["definitions"]:
            token = (definition["term"], definition["direction"])
            if token in present:
                raise ValueError("Duplicate original scientific test")
            if definition["term"] not in terms:
                raise ValueError("Unexpected original target coefficient")
            present[token] = dict(receipt=unit["receipt"], prefix=unit["prefix"], index=definition["index"],
                                  batch=unit["batch"], source_job=unit["job"], mask=unit["mask"])
    expected = {(f,o,m) for f in FAMILIES for o in OLD_OUTCOMES for m in CORE_MODELS}
    if set(refs) != expected:
        raise ValueError("All 16 previous models must exist for both families and original outcomes")
    for outcome in OLD_OUTCOMES:
        for model in CORE_MODELS:
            left,right=refs[("activation",outcome,model)],refs[("connectivity",outcome,model)]
            if left[0]!=right[0] or not np.array_equal(left[1],right[1]):
                raise ValueError("Scientific/covariate rows differ across image families")
    files, jobs, coverage = {}, [], []

    def add(family, outcome, model, names, x, terms, already):
        if x.shape != (97,len(names)) or np.linalg.matrix_rank(x) != len(names):
            raise ValueError("Full-rank N=97 design required")
        folder = Path("designs")/family/outcome/model
        for z in (2.6,3.1):
            old = already.get(z,{})
            missing = [term for term in terms if (term,"positive") not in old or (term,"negative") not in old]
            if any(((term,"positive") in old) != ((term,"negative") in old) for term in terms):
                raise ValueError("Original directional pair is incomplete")
            job = None
            if missing:
                text, tested = contrast_text(names,missing)
                relative = folder/"design.con"
                files[str(folder/"design.mat")] = base.vest_matrix(x)
                files[str(folder/"design.tsv")] = base.review.tsv([dict(subject=s,**dict(zip(names,row))) for s,row in zip(ids,x)])
                files[str(relative)] = text
                dof = 97-len(names)
                job = dict(key=f"{family}/{outcome}/{model}/z-"+str(z).replace(".","p"),
                    family=family,outcome=family+"/"+outcome,model=model,z=z,residual_dof=dof,
                    t_cutoff=float(t.isf(norm.sf(z),dof)),permutations=10000,seed=20261101,
                    design=str(output/folder/"design.mat"),contrast=str(output/relative),contrasts=tested)
                jobs.append(job)
            for definition in definitions(terms):
                token=(definition["term"],definition["direction"])
                if token in old:
                    source=dict(origin="existing",**old[token])
                else:
                    item=next(r for r in job["contrasts"] if (r["term"],r["direction"])==token)
                    source=dict(origin="extension",job=job["key"],index=item["index"])
                coverage.append(dict(family=family,outcome=outcome,model=model,z=z,term=token[0],direction=token[1],source=source))

    for family in FAMILIES:
        for outcome in (*OLD_OUTCOMES,*NEW_OUTCOMES):
            for model in CORE_MODELS:
                names,x=refs[(family,"social_specific" if outcome in NEW_OUTCOMES else outcome,model)]
                terms=scientific_terms(model,names)
                add(family,outcome,model,names,x,terms,
                    {z:completed.get((family,outcome,model,z),{}) for z in (2.6,3.1)})
    names,x,_=components.additive_design(additive_baseline,ids)
    for family in FAMILIES:
        for outcome in (*NEW_OUTCOMES,"social_specific"):
            # The existing six-job runner owns PM2.5 activation tests. Never duplicate them.
            already={z:{("pm25",d):dict(batch="additive_activation",index=i,
                source_key=f"{outcome}/{components.MODEL}/z-"+str(z).replace(".","p"))
                for i,d in ((1,"positive"),(2,"negative"))} for z in (2.6,3.1)} if family=="activation" else {}
            add(family,outcome,components.MODEL,names,x,["pm25","ecog"],already)
    if len(jobs)!=220 or len(coverage)!=1328 or len({j["key"] for j in jobs})!=220:
        raise ValueError("Unexpected full coverage inventory")
    return files,jobs,coverage


def validate_ppi_components(feat):
    settings=remaining.paths_from_fsf(feat/"design.fsf")
    c,x=remaining.matrix(feat/"design.con"),remaining.matrix(feat/"design.mat")
    if c.shape[0]!=5 or c.shape[1]<9 or x.shape[1]!=c.shape[1] or not np.isfinite(x).all():
        raise ValueError("Invalid PPI contrast/design shape")
    for index,label,weights in ((1,"win",{5:1}),(2,"loss",{6:1}),(4,"win-loss",{5:1,6:-1})):
        expected=np.zeros(c.shape[1])
        for column,weight in weights.items():expected[column]=weight
        if settings.get(f"conname_real.{index}")!=label or not np.array_equal(c[index-1],expected):
            raise ValueError("PPI component must test task x VS interaction, not activation or physiological main effect")
        if not np.allclose(expected@np.linalg.pinv(x)@x,expected,rtol=1e-6,atol=1e-6):
            raise ValueError("PPI component is not estimable")


def ppi_arrays(project,ids,plan,records):
    reference=nib.load(plan["mask"]);support=reference.get_fdata()>0
    arrays={o:np.zeros(reference.shape+(97,),dtype=np.float32) for o in NEW_OUTCOMES}
    existing=nib.load(plan["images"]["social_specific"]);base.grid(reference,existing,4)
    if existing.shape[3]!=97:raise ValueError("Wrong original PPI participant count")
    lineage=[]
    for index,subject in enumerate(ids):
        values={}
        for task in ("socialdoors","doors"):
            receipt=project/f"derivatives/fsl/randomise/katie-remaining-v1/ppi-l1/sub-{subject}_ses-01_task-{task}_run-1/success.json"
            saved=json.loads(receipt.read_text())
            if (saved["job"]["subject"],saved["job"]["task"])!=(subject,task):raise ValueError("PPI identity differs")
            for record in saved["sources"]+saved["outputs"]:
                audit.add_record(records,record["path"],record["sha256"],record["size"])
            feat=Path(saved["feat"])
            verified=remaining.verify_ppi(feat,saved["job"])
            for record in verified:audit.add_record(records,record["path"],record["sha256"],record["size"])
            audit.add_record(records,receipt,base.cohort.digest(receipt))
            validate_ppi_components(feat)
            values[task]={}
            for cope in (1,2,4):
                path=feat/f"stats/cope{cope}.nii.gz";image=nib.load(path);base.grid(reference,image)
                data=image.get_fdata()[support]
                if not np.isfinite(data).all():raise ValueError("Invalid PPI component pixels; no participant dropped")
                values[task][cope]=data
                record=base.fingerprint(path);audit.add_record(records,path,record["sha256"],record["size"])
                lineage.append(dict(volume=index,subject=subject,task=task,cope=cope,source=str(path),family="connectivity"))
            a,b,c=(values[task][n] for n in (1,2,4))
            if np.any(np.abs(a-b-c)>8*np.finfo(np.float32).eps*(np.abs(a)+np.abs(b)+np.abs(c)+1)):
                raise ValueError("PPI win/loss components disagree with the validated valence contrast")
        for name,cope in (("win_only",1),("loss_only",2)):
            arrays[name][...,index][support]=values["socialdoors"][cope]-values["doors"][cope]
        if not np.array_equal(np.asarray(existing.dataobj[...,index],dtype=np.float32)[support],
                              (values["socialdoors"][4]-values["doors"][4]).astype(np.float32)):
            raise ValueError("Original PPI image order/difference direction differs")
        if (index+1)%25==0 or index==96:print(f"PPI COMPONENTS {index+1}/97 pairs verified",flush=True)
    return arrays,lineage


def build(args):
    if (args.output/"plan.json").exists():return check(args)
    if args.output.exists() and any(args.output.iterdir()):raise ValueError("Refusing to overwrite unrecognized extension outputs")
    ids,records,plans,units=audit.inventory(args.project)
    # Authenticate the original source/volume order once before adding new contrasts.
    _,evidence=audit.image_order_audit(args.project,plans,ids)
    for r in evidence:audit.add_record(records,r["path"],r["sha256"],r["size"])
    files,jobs,coverage=catalog(args.output,ids,units,plans["environment_activation"])
    _,pairs=base.cohort.read_table(ROOT/"data/derived/katie-cohort-v1/selected_pairs.tsv")
    activation,evidence,lineage=components.component_arrays(pairs,ids,nib.load(plans["group_activation"]["mask"]),
                                                          plans["group_activation"]["images"]["social_specific"])
    for row in lineage:row["family"]="activation"
    for path in evidence:
        r=base.fingerprint(path);audit.add_record(records,path,r["sha256"],r["size"])
    connectivity,ppi_lineage=ppi_arrays(args.project,ids,plans["environment_connectivity"],records)
    lineage+=ppi_lineage
    for path in (Path(__file__),Path(audit.__file__),Path(components.__file__),Path(remaining.__file__),Path(base.__file__),
                 ROOT/"data/derived/katie-cohort-v1/selected_pairs.tsv",ROOT/"data/derived/katie-cohort-v1/subjects.tsv"):
        r=base.fingerprint(path);audit.add_record(records,path,r["sha256"],r["size"])
    audit.verify_records(records,24)
    staging=Path(tempfile.mkdtemp(prefix=".reward-extension-",dir=args.output.parent));staging.chmod(0o777)
    for name,text in files.items():
        path=staging/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
    (staging/"subjects.tsv").write_text(base.review.tsv([dict(subject=s) for s in ids]))
    (staging/"source_order.tsv").write_text(base.review.tsv(lineage))
    masks={f:plans["group_activation" if f=="activation" else "environment_connectivity"]["mask"] for f in FAMILIES}
    images={}
    for family,arrays in (("activation",activation),("connectivity",connectivity)):
        source=plans["group_activation" if family=="activation" else "environment_connectivity"]
        images.update({family+"/"+o:source["images"][o] for o in OLD_OUTCOMES})
        for outcome,array in arrays.items():
            relative=Path("inputs")/family/(outcome+".nii.gz")
            base.save_image(staging/relative,array,nib.load(masks[family]))
            images[family+"/"+outcome]=str(args.output/relative)
    plan=dict(n=97,jobs=jobs,coverage=coverage,images=images,masks=masks,
        randomise=plans["environment_activation"]["randomise"],sources=list(records.values()),
        code_sha256=base.cohort.digest(Path(__file__)),project=str(args.project),
        outputs={str(p.relative_to(staging)):base.cohort.digest(p) for p in staging.rglob("*") if p.is_file()},
        exclusions_changed=False,original_results_changed=False,main_effects="conditional at centered moderator/exposure zero",
        new_seed_analysis=False,all_families="activation and original VS-seeded PPI; no mPFC/vmPFC")
    base.write_json(staging/"plan.json",plan)
    (staging/"plan.sha256").write_text(base.cohort.digest(staging/"plan.json")+"\n")
    if base.STOP:raise InterruptedError("Stopped; staged inputs retained")
    staging.rename(args.output)
    return check(args)


def check(args):
    path=args.output/"plan.json"
    if base.cohort.digest(path)!=(args.output/"plan.sha256").read_text().strip():raise ValueError("Extension plan changed")
    plan=json.loads(path.read_text())
    if plan["n"]!=97 or len(plan["jobs"])!=220 or len(plan["coverage"])!=1328 or plan["project"]!=str(args.project):
        raise ValueError("Extension inventory differs")
    if plan["code_sha256"]!=base.cohort.digest(Path(__file__)):raise ValueError("Resume with the recorded extension code")
    for name,digest in plan["outputs"].items():
        if base.cohort.digest(args.output/name)!=digest:raise ValueError("Extension artifact changed: "+name)
    audit.verify_records({r["path"]:r for r in plan["sources"]},24)
    for job in plan["jobs"]:
        x,c=audit.matrix(job["design"]),audit.matrix(job["contrast"])
        if x.shape[0]!=97 or np.linalg.matrix_rank(x)!=x.shape[1] or c.shape!=(len(job["contrasts"]),x.shape[1]):
            raise ValueError("Extension model/contrast shape differs")
        if not np.isclose(job["t_cutoff"],t.isf(norm.sf(job["z"]),97-x.shape[1]),rtol=0,atol=1e-10):
            raise ValueError("Incorrect model-specific cluster threshold")
        names,rows=base.cohort.read_table(Path(job["design"]).with_suffix(".tsv"));names=names[1:]
        _,roster=base.cohort.read_table(args.output/"subjects.tsv")
        if [r["subject"] for r in rows]!=[r["subject"] for r in roster]:raise ValueError("Design/volume row order differs")
        if not np.allclose(x,np.array([[float(r[n]) for n in names] for r in rows]),rtol=0,atol=1e-12):
            raise ValueError("Labeled and numeric design differ")
        for row,definition in zip(c,job["contrasts"]):
            expected=np.array([(1 if definition["direction"]=="positive" else -1) if n==definition["term"] else 0 for n in names])
            if not np.array_equal(row,expected):raise ValueError("Contrast does not test its named coefficient")
    print("CHECK PASSED: N=97; 16 previous models plus additive PM2.5/Ecog; activation and VS-PPI; "
          "explicit main effects/interactions; 220 new jobs; 1328 total directional tests including retained results.",flush=True)
    return plan


def products(prefix,mask,contrasts):
    reference=nib.load(mask)
    for definition in contrasts:
        for suffix in (f"_tstat{definition['index']}.nii.gz",f"_clustere_corrp_tstat{definition['index']}.nii.gz"):
            image=nib.load(str(prefix)+suffix);base.grid(reference,image);data=image.get_fdata()
            if not np.isfinite(data).all() or ("corrp" in suffix and (data.min()<0 or data.max()>1)):
                raise ValueError("Invalid/missing native randomise output")
    return [base.fingerprint(p) for p in sorted(prefix.parent.glob(prefix.name+"*")) if p.is_file()]


def execute(plan,job,folder,digest,smoke=False):
    folder.mkdir(parents=True,exist_ok=True)
    receipt=folder/"success.json";mask=plan["masks"][job["family"]]
    view=dict(plan,mask=mask)
    if receipt.exists():
        saved=json.loads(receipt.read_text());prefix=Path(saved["attempt"])/"randomise"
        if (saved["job"]!=job or saved["plan_sha256"]!=digest or saved["smoke"]!=smoke
                or saved["command"]!=base.command(view,job,prefix,permutations=2 if smoke else None)
                or products(prefix,mask,job["contrasts"])!=saved["outputs"]):
            raise ValueError("Completed extension result differs; refusing overwrite")
        return "REUSED"
    running=folder/"running.json"
    if running.exists() and base.group_alive(json.loads(running.read_text())["process_group"]):
        raise ValueError("Existing active/orphan randomise group; no duplicate launched")
    if base.STOP:return "NOT_STARTED"
    attempts=folder/"attempts";attempts.mkdir(exist_ok=True);number=1
    while (attempts/f"attempt-{number:04d}").exists():number+=1
    destination=attempts/f"attempt-{number:04d}";destination.mkdir();prefix=destination/"randomise"
    call=base.command(view,job,prefix,permutations=2 if smoke else None)
    base.write_json(destination/"command.json",dict(command=call,job=job,smoke=smoke))
    print(("SMOKE " if smoke else "STARTED ")+job["key"],flush=True)
    with (destination/"console.log").open("w") as stream:
        process=subprocess.Popen(call,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,
                                 pass_fds=() if base.LEASE_FD is None else (base.LEASE_FD,))
        base.write_json(running,dict(process_group=process.pid,command=call))
        try:
            while process.poll() is None:
                if base.STOP:
                    os.killpg(process.pid,signal.SIGTERM)
                    try:process.wait(timeout=30)
                    except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
                    raise InterruptedError("Stopped; completed receipts and partial attempt preserved")
                time.sleep(.25)
        finally:
            if process.poll() is not None:running.unlink(missing_ok=True)
    if process.returncode:raise RuntimeError(f"randomise exit {process.returncode}: {destination}/console.log")
    base.write_json(receipt,dict(job=job,plan_sha256=digest,smoke=smoke,command=call,attempt=str(destination),
                               outputs=products(prefix,mask,job["contrasts"])))
    return "COMPLETED"


def additive_args(args):
    baseline=args.project/"derivatives/fsl/randomise/katie-v1"
    return SimpleNamespace(project=args.project,upstream=args.upstream,baseline=baseline,
                           output=baseline.parent/"katie-pm25-components-v1",jobs=min(6,args.jobs))


def ensure_additive(args):
    other=additive_args(args);lockpath=other.output.parent/".katie-pm25-components-v1.lock"
    with lockpath.open("a") as lock:
        while not base.STOP:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);break
            except BlockingIOError:
                print("WAITING: existing six-job additive coordinator owns its lock; it is not interrupted or duplicated.",flush=True)
                time.sleep(10)
        if base.STOP:raise InterruptedError("Stopped while waiting; original additive batch untouched")
        base.LEASE_FD=lock.fileno()
        components.run(other)


def final_results(args,plan):
    digest=base.cohort.digest(args.output/"plan.json");resolved={};receipts={}
    for job in plan["jobs"]:
        receipt=args.output/"jobs"/job["key"]/"success.json"
        saved=json.loads(receipt.read_text());prefix=Path(saved["attempt"])/"randomise";mask=plan["masks"][job["family"]]
        if (saved["job"]!=job or saved["plan_sha256"]!=digest or saved["smoke"]
                or saved["command"]!=base.command(dict(plan,mask=mask),job,prefix)
                or products(prefix,mask,job["contrasts"])!=saved["outputs"]):
            raise ValueError("Extension result receipt/products differ")
        receipts[str(receipt)]=base.fingerprint(receipt)
        resolved[job["key"]]=(job,prefix)
    additive=components.check(additive_args(args));additive_hash=base.cohort.digest(additive_args(args).output/"plan.json")
    additive_jobs={j["key"]:j for j in additive["jobs"]}
    maps,clusters=[],[]
    additive_bound=set()
    for expected in plan["coverage"]:
        source=expected["source"];index=source["index"]
        if source["origin"]=="extension":
            job,prefix=resolved[source["job"]]
        elif source["batch"]=="additive_activation":
            job=additive_jobs[source["source_key"]]
            receipt=additive_args(args).output/"jobs"/job["key"]/"success.json"
            saved=json.loads(receipt.read_text());prefix=Path(saved["attempt"])/"randomise"
            if (saved["job"]!=job or saved["plan_sha256"]!=additive_hash or saved["smoke"]
                    or saved["command"]!=base.command(additive,job,prefix)
                    or base.output_images(prefix,additive["mask"])!=saved["outputs"]):
                raise ValueError("Retained additive activation result differs")
            # Bind the externally managed batch to this exact cohort, model and source pixels.
            x=audit.matrix(job["design"])
            own=next(j for j in plan["jobs"] if j["family"]=="activation" and j["model"]==components.MODEL
                     and j["outcome"].split("/")[-1]==expected["outcome"] and j["z"]==expected["z"])
            if not np.array_equal(x,audit.matrix(own["design"])):raise ValueError("Additive designs differ")
            base.grid(nib.load(plan["masks"]["activation"]),nib.load(additive["mask"]))
            if not np.array_equal(nib.load(additive["mask"]).get_fdata(),nib.load(plan["masks"]["activation"]).get_fdata()):
                raise ValueError("Additive activation mask differs")
            if expected["outcome"] not in additive_bound:
                image=nib.load(additive["images"][expected["outcome"]])
                expected_image=nib.load(plan["images"]["activation/"+expected["outcome"]])
                base.grid(expected_image,image,4)
                if image.shape[3]!=97 or not np.array_equal(np.asarray(image.dataobj),np.asarray(expected_image.dataobj)):
                    raise ValueError("Retained additive activation pixels or participant order differ")
                additive_bound.add(expected["outcome"])
            receipts[str(receipt)]=base.fingerprint(receipt)
        else:
            job,prefix=source["source_job"],Path(source["prefix"])
        mask=plan["masks"][expected["family"]]
        row,found=summary.map_summary(job,expected["direction"],nib.load(str(prefix)+f"_tstat{index}.nii.gz"),
            nib.load(str(prefix)+f"_clustere_corrp_tstat{index}.nii.gz"),nib.load(mask))
        meta={k:expected[k] for k in ("family","outcome","model","term","z","direction")}
        maps.append(dict(row,**meta,origin=source["origin"],contrast_index=index,output_prefix=str(prefix)))
        clusters.extend(dict(r,**meta,origin=source["origin"]) for r in found)
    if len(maps)!=1328:raise ValueError("Final scientific coverage is incomplete")
    tokens=[tuple(r[k] for k in ("family","outcome","model","z","term","direction")) for r in maps]
    if len(set(tokens))!=1328:raise ValueError("Duplicate or missing final scientific tests")
    audit.verify_records({r["path"]:r for r in plan["sources"]},24)
    base.verify_sources(list(receipts.values()))
    (args.output/"maps.tsv").write_text(base.review.tsv(maps))
    (args.output/"clusters.tsv").write_text(base.review.tsv(clusters,summary.CLUSTER_FIELDS+["family","term","origin"]))
    base.write_json(args.output/"validation.json",dict(n=97,new_jobs=220,directional_tests=1328,
        new_directional_tests=sum(len(j["contrasts"]) for j in plan["jobs"]),new_receipts=list(receipts.values()),
        original_results_changed=False,exclusions_changed=False,correction="per-map cluster-FWE; exploratory across tests"))
    for family in FAMILIES:
        for outcome in (*OLD_OUTCOMES,*NEW_OUTCOMES):
            rows=[r for r in maps if r["family"]==family and r["outcome"]==outcome]
            print(f"SUMMARY {family} {outcome}: {len(rows)} maps; {sum(r['significant_voxels']>0 for r in rows)} with cluster-FWE p<.05",flush=True)
    print("CHECK PASSED: 220 extension jobs plus retained analyses; complete 1328-map scientific coverage; "
          "N=97 unchanged. Detailed tables remain in ignored derivatives; no bulk Git publication.",flush=True)


def run(args):
    # A separate process can wait for or finish the small batch without blocking the extension.
    child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),"ensure-additive","--project",str(args.project),
        "--upstream",str(args.upstream),"--jobs",str(args.jobs)],pass_fds=() if base.LEASE_FD is None else (base.LEASE_FD,))
    plan=None;outcomes={}
    try:
        plan=build(args);digest=base.cohort.digest(args.output/"plan.json")
        while args.jobs<=6 and child.poll() is None:
            if base.STOP:raise InterruptedError("Stopped waiting for limited-worker additive stage")
            print("WAITING: additive stage finishing before extension to respect the small worker limit.",flush=True)
            time.sleep(10)
        for family in FAMILIES:
            job=max((j for j in plan["jobs"] if j["family"]==family),key=lambda j:len(j["contrasts"]))
            if execute(plan,job,args.output/"smoke"/family,digest,True)=="NOT_STARTED":raise InterruptedError("Stopped before smoke test")
        pending=iter(plan["jobs"]);exhausted=False
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures={}
            while futures or not exhausted:
                limit=max(1,args.jobs-(6 if child.poll() is None else 0))
                while len(futures)<limit and not exhausted and not base.STOP:
                    try:job=next(pending)
                    except StopIteration:exhausted=True;break
                    futures[pool.submit(execute,plan,job,args.output/"jobs"/job["key"],digest)]=job
                if base.STOP:exhausted=True
                if not futures:break
                done,_=wait(futures,timeout=60,return_when=FIRST_COMPLETED)
                if not done:print(f"HEARTBEAT finished={len(outcomes)}/220 active={len(futures)} limit={limit}",flush=True)
                for future in done:
                    job=futures.pop(future)
                    try:outcomes[job["key"]]=future.result()
                    except Exception as exc:outcomes[job["key"]]="FAILED: "+str(exc)
                    print(f"{outcomes[job['key']]} {job['key']} ({len(outcomes)}/220)",flush=True)
                base.write_json(args.output/"status.json",dict(status="running",n=97,total=220,outcomes=outcomes))
        if base.STOP or len(outcomes)!=220 or any(v not in ("COMPLETED","REUSED") for v in outcomes.values()):
            base.write_json(args.output/"status.json",dict(status="incomplete",n=97,total=220,outcomes=outcomes))
            raise RuntimeError("Incomplete extension; completed jobs preserved. Resume the same launcher.")
        while child.poll() is None:
            if base.STOP:raise InterruptedError("Stopped waiting for additive validation")
            print("WAITING: retained six-job additive batch finishing; extension jobs are complete.",flush=True);time.sleep(10)
        if child.returncode:raise RuntimeError("Additive validation failed; extension outputs preserved; inspect its messages")
        final_results(args,plan)
        base.write_json(args.output/"status.json",dict(status="complete",validated=True,n=97,total=220,outcomes=outcomes))
    except BaseException as exc:
        if plan is not None:
            base.write_json(args.output/"status.json",dict(status="stopped" if base.STOP else "failed",validated=False,
                n=97,total=220,outcomes=outcomes,error=f"{type(exc).__name__}: {exc}"))
        raise
    finally:
        if child.poll() is None:
            child.terminate()
            try:child.wait(timeout=45)
            except subprocess.TimeoutExpired:child.kill();child.wait()


def main():
    os.umask(0)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("run","check-results","ensure-additive"))
    parser.add_argument("--project",type=Path,required=True)
    parser.add_argument("--upstream",type=Path,default=Path("/ZPOOL/data/projects/rf1-sra-linux2"))
    parser.add_argument("--jobs",type=int,default=60)
    args=parser.parse_args();args.project=args.project.resolve();args.upstream=args.upstream.resolve()
    args.output=args.project/"derivatives/fsl/randomise/katie-reward-extension-v1"
    if not 1<=args.jobs<=60:parser.error("Use --jobs 1..60")
    args.output.parent.mkdir(parents=True,exist_ok=True)
    signal.signal(signal.SIGTERM,base.stop);signal.signal(signal.SIGINT,base.stop)
    if args.command=="ensure-additive":ensure_additive(args);return
    with (args.output.parent/".katie-reward-extension-v1.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);base.LEASE_FD=lock.fileno()
        if args.command=="run":run(args)
        else:final_results(args,check(args))


if __name__=="__main__":main()
