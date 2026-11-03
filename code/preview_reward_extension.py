#!/usr/bin/env python3
"""Summarize only hash-verified completed extension jobs; do not modify the batch."""
import argparse
from collections import Counter
import json
from pathlib import Path

import nibabel as nib

import audit_katie_results as audit
import run_reward_extension as extension


def preview(project):
    folder=project/"derivatives/fsl/randomise/katie-reward-extension-v1"
    plan_path=folder/"plan.json"
    if not plan_path.exists():
        return dict(available=False,note="Extension inputs/plan are not yet built; no results inferred.")
    base=extension.base
    if base.cohort.digest(plan_path)!=(folder/"plan.sha256").read_text().strip():
        raise ValueError("Extension plan checksum differs")
    plan=json.loads(plan_path.read_text())
    if plan["n"]!=97 or len(plan["jobs"])!=220:
        raise ValueError("Unexpected cohort or extension inventory")
    records={r["path"]:r for r in plan["sources"]}
    for name,digest in plan["outputs"].items():
        audit.add_record(records,folder/name,digest)
    audit.verify_records(records,24)
    rows=[];pending=[];receipts=[];completed=Counter()
    for job in plan["jobs"]:
        path=folder/"jobs"/job["key"]/"success.json"
        if not path.exists():pending.append(job["key"]);continue
        receipt=json.loads(path.read_text());prefix=Path(receipt["attempt"])/"randomise"
        if not prefix.parent.resolve().is_relative_to((path.parent/"attempts").resolve()):
            raise ValueError("Receipt points outside its job attempts")
        mask=plan["masks"][job["family"]]
        if (receipt["job"]!=job or receipt["plan_sha256"]!=base.cohort.digest(plan_path) or receipt["smoke"]
                or receipt["command"]!=base.command(dict(plan,mask=mask),job,prefix)):
            raise ValueError("Completed native command/receipt differs: "+job["key"])
        base.verify_sources(receipt["outputs"])
        if extension.products(prefix,mask,job["contrasts"])!=receipt["outputs"]:
            raise ValueError("Completed product inventory differs: "+job["key"])
        receipts.append(base.fingerprint(path))
        for definition in job["contrasts"]:
            index=definition["index"]
            row,_=extension.summary.map_summary(job,definition["direction"],nib.load(str(prefix)+f"_tstat{index}.nii.gz"),
                nib.load(str(prefix)+f"_clustere_corrp_tstat{index}.nii.gz"),nib.load(mask))
            rows.append(dict(row,family=job["family"],outcome=job["outcome"].split("/")[-1],term=definition["term"]))
        completed[(job["family"],job["outcome"].split("/")[-1])]+=1
    base.verify_sources(receipts)
    findings=[r for r in rows if r["significant_voxels"]>0]
    findings.sort(key=lambda r:r["min_cluster_fwe_p"])
    return dict(available=True,preliminary=len(pending)>0,n=97,completed_jobs=len(receipts),pending_jobs=len(pending),
        verified_completed_maps=len(rows),completed_by_family_outcome=[dict(family=k[0],outcome=k[1],jobs=v) for k,v in sorted(completed.items())],
        corrected_findings=findings,significant_map_count=len(findings),
        caution="Only completed, hash-verified extension results. Completion order is not a balanced model sample. Per-map cluster-FWE only; no new exclusions or analyses.")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project",type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(preview(args.project.resolve()),indent=2),flush=True)
