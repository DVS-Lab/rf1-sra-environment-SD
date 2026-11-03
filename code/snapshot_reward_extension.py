#!/usr/bin/env python3
"""Fast read-only progress/result snapshot, suitable for a published run record."""
import argparse
from collections import Counter, deque
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess


def load(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        return {"snapshot_read_error": f"{type(exc).__name__}: {exc}"}


def progress(folder, expected):
    plan_path=folder/"plan.json";status=load(folder/"status.json")
    result=dict(folder=str(folder),expected_jobs=expected,recorded_status=status.get("status","not_available"),
                recorded_validated=status.get("validated"),outcome_counts=dict(Counter(status.get("outcomes",{}).values())))
    for key in ("error","snapshot_read_error"):
        if key in status:result[key]=status[key]
    result["recorded_failures"]={k:v for k,v in status.get("outcomes",{}).items() if str(v).startswith("FAILED")}
    if not plan_path.exists():
        result["plan_available"]=False
        return result
    plan=load(plan_path)
    if "snapshot_read_error" in plan:
        result["plan_error"]=plan["snapshot_read_error"]
        return result
    digest=hashlib.sha256(plan_path.read_bytes()).hexdigest()
    checksum=folder/"plan.sha256"
    result.update(plan_available=True,planned_jobs=len(plan.get("jobs",[])),n=plan.get("n"),
                  plan_checksum_matches=checksum.exists() and checksum.read_text().strip()==digest)
    counts=Counter();invalid=[]
    for job in plan.get("jobs",[]):
        receipt=folder/"jobs"/job["key"]/"success.json"
        if not receipt.exists():counts["missing_receipt"]+=1;continue
        saved=load(receipt)
        if (saved.get("job")!=job or saved.get("plan_sha256")!=digest or saved.get("smoke") is not False):
            counts["invalid_receipt_metadata"]+=1;invalid.append(job["key"]);continue
        indices=[r["index"] for r in job.get("contrasts",[{"index":1},{"index":2}])]
        prefix=Path(saved["attempt"])/"randomise"
        products=[Path(str(prefix)+suffix) for i in indices for suffix in
                  (f"_tstat{i}.nii.gz",f"_clustere_corrp_tstat{i}.nii.gz")]
        if not all(p.is_file() and p.stat().st_size>0 for p in products):
            counts["missing_or_empty_products"]+=1;invalid.append(job["key"]);continue
        counts["receipt_metadata_and_product_presence_ok"]+=1
    result["receipt_inventory"]=dict(counts)
    result["invalid_job_keys"]=invalid
    validation=folder/"validation.json"
    if validation.exists():
        v=load(validation)
        result["recorded_final_validation"]={k:v.get(k) for k in
            ("n","new_jobs","directional_tests","new_directional_tests","original_results_changed","exclusions_changed")}
    result["verification_scope"]="Snapshot checks receipt metadata and product presence, not image hashes or live source integrity."
    return result


def results(folder):
    path=folder/"maps.tsv"
    if not path.exists():
        return dict(available=False,note="Final maps.tsv not yet present; no findings inferred from partial files.")
    with path.open() as stream:rows=list(csv.DictReader(stream,delimiter="\t"))
    required={"family","outcome","model","term","direction","z","origin","min_cluster_fwe_p","significant_voxels"}
    if not rows or not required.issubset(rows[0]):
        return dict(available=False,error="Final result table is empty or has unexpected columns")
    if len(rows)!=1328:
        return dict(available=False,error=f"Incomplete/unexpected result table: {len(rows)} rows; expected 1328")
    summaries=[]
    for family in ("activation","connectivity"):
        for outcome in ("win_only","loss_only","social_specific","average"):
            selected=[r for r in rows if r["family"]==family and r["outcome"]==outcome]
            new=[r for r in selected if r["origin"]=="extension"]
            summaries.append(dict(family=family,outcome=outcome,total_maps=len(selected),new_maps=len(new),
                new_maps_with_clusters=sum(int(r["significant_voxels"])>0 for r in new)))
    findings=[{k:r[k] for k in ("family","outcome","model","term","direction","z","min_cluster_fwe_p","significant_voxels")}
              for r in rows if r["origin"]=="extension" and int(r["significant_voxels"])>0]
    findings.sort(key=lambda r:float(r["min_cluster_fwe_p"]))
    return dict(available=True,rows=len(rows),summary=summaries,new_corrected_findings=findings,
        caution="Per-map cluster-FWE only; exploratory across models, outcomes, directions and CDTs. Reading this table is not a new integrity check.")


def processes(pattern):
    try:
        call=subprocess.run(["pgrep","-u",str(os.getuid()),"-af",pattern],capture_output=True,text=True,check=False)
        if call.returncode not in (0,1):return ["Process query unavailable: "+call.stderr.strip()]
        return call.stdout.splitlines()
    except OSError as exc:
        return [f"Process query unavailable: {exc}"]


def snapshot(project):
    print("READ-ONLY SNAPSHOT:",datetime.now(timezone.utc).isoformat(),socket.gethostname(),flush=True)
    print("No jobs started/stopped, no inputs changed, no exclusions changed.",flush=True)
    print("=== Matching coordinators ===",flush=True)
    print("\n".join(processes(r"[p]ython[^ ]* .*run_(reward_extension|pm25_components)[.]py (run|ensure-additive)")) or "NONE",flush=True)
    print("=== Matching extension randomise processes ===",flush=True)
    native=processes(r"[r]andomise .*katie-reward-extension-v1")
    print("Matching process count:",len(native),flush=True)
    for line in native[:5]:print(line,flush=True)
    parent=project/"derivatives/fsl/randomise"
    for name,total in (("katie-pm25-components-v1",6),("katie-reward-extension-v1",220)):
        print("=== "+name+" ===",flush=True)
        print(json.dumps(progress(parent/name,total),indent=2),flush=True)
    print("=== Final result-table summary ===",flush=True)
    print(json.dumps(results(parent/"katie-reward-extension-v1"),indent=2),flush=True)
    logs=list((project/"logs/runs").glob("reward-extension-*.nohup.out"))
    if logs:
        latest=max(logs,key=lambda p:p.stat().st_mtime)
        print("=== Latest launcher log: "+str(latest)+" ===",flush=True)
        with latest.open(errors="replace") as stream:print("".join(deque(stream,maxlen=50)),flush=True)
    else:print("No reward-extension launcher log found.",flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project",type=Path,required=True)
    args=parser.parse_args()
    snapshot(args.project.resolve())
