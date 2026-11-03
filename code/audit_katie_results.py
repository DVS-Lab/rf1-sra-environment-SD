#!/usr/bin/env python3
"""Audit all completed Katie batches without rerunning inference or changing inputs."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import io
import json
import os
from pathlib import Path
import sys

import nibabel as nib
import numpy as np
from scipy.stats import norm, t

import run_katie_randomise as base
import run_katie_main_effects as conditional
import run_katie_remaining as remaining
import summarize_katie_randomise as summary

BATCHES = {
    "environment_activation": ("katie-v1", 24, 2),
    "conditional_activation": ("katie-main-effects-v1", 16, 4),
    "group_activation": ("katie-remaining-v1/activation", 8, 2),
    "environment_connectivity": ("katie-remaining-v1/connectivity", 24, 2),
    "financial_predictors": ("katie-financial-v1", 16, 2),
    "financial_moderation": ("katie-financial-moderation-v1", 64, 2),
}


def matrix(path):
    return np.loadtxt(io.StringIO(Path(path).read_text().split("/Matrix", 1)[1]), ndmin=2)


def add_record(records, path, digest, size=None):
    path = str(Path(path).resolve())
    item = dict(path=path, sha256=digest)
    if size is not None: item["size"] = size
    if path in records and (records[path]["sha256"] != digest or
            (size is not None and "size" in records[path] and records[path]["size"] != size)):
        raise ValueError("Contradictory saved fingerprints for " + path)
    records[path] = dict(records.get(path, {}), **item)


def verify_records(records, jobs):
    def verify(record):
        path = Path(record["path"])
        if ("size" in record and path.stat().st_size != record["size"]) or base.cohort.digest(path) != record["sha256"]:
            raise ValueError("Frozen source/result changed: " + str(path))
    failures=[]
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        pending = [pool.submit(verify, r) for r in records.values()]
        for number, future in enumerate(as_completed(pending), 1):
            try:future.result()
            except Exception as exc:
                failures.append(str(exc));print("HASH FAILURE "+str(exc),flush=True)
            if number % 100 == 0 or number == len(pending):
                print(f"HASH AUDIT {number}/{len(pending)} unique files", flush=True)
    if failures:raise ValueError(f"{len(failures)} fingerprint failure(s); see full HASH FAILURE lines: "+failures[0])


def design(job, ids, conditional_job=False):
    x, c = matrix(job["design"]), matrix(job["contrast"])
    fields, rows = base.cohort.read_table(Path(job["design"]).with_suffix(".tsv"))
    names = fields[1:]
    expected = np.array([[float(r[n]) for n in names] for r in rows])
    if ([r["subject"] for r in rows] != ids or x.shape[0] != 97 or x.shape[1] != len(names)
            or not np.allclose(expected, x, rtol=0, atol=1e-12) or not np.isfinite(x).all()
            or np.linalg.matrix_rank(x) != x.shape[1] or c.shape[1] != x.shape[1]
            or c.shape[0] != (4 if conditional_job else 2)
            or job["residual_dof"] != 97-x.shape[1] or not np.all(x[:, 0] == 1)):
        raise ValueError("Row order, finite/full-rank matrix, contrast shape or residual df mismatch")
    expected_cutoff = float(t.isf(norm.sf(job["z"]), job["residual_dof"]))
    if job["z"] not in (2.6, 3.1) or not np.isclose(job["t_cutoff"], expected_cutoff, atol=1e-10, rtol=0):
        raise ValueError("Incorrect model-specific Z-to-t CDT")
    if job["permutations"] != 10000 or job["seed"] != 20261101:
        raise ValueError("Permutation count or fixed seed differs")
    definitions = []
    for index, contrast in enumerate(c, 1):
        nonzero = np.flatnonzero(contrast)
        if len(nonzero) != 1 or contrast[nonzero[0]] not in (-1, 1):
            raise ValueError("Expected the documented single-term directional contrast")
        term = names[nonzero[0]]
        direction = "positive" if contrast[nonzero[0]] == 1 else "negative"
        if index % 2 == 0 and not np.array_equal(contrast, -c[index-2]):
            raise ValueError("Directional contrast pair differs")
        if conditional_job:
            saved = job["contrasts"][index-1]
            if (saved["term"], saved["direction"], saved["index"]) != (term, direction, index):
                raise ValueError("Conditional contrast label differs from actual matrix")
        definitions.append(dict(index=index, term=term, direction=direction))
    return names, x, definitions


def inventory(project):
    _, roster = base.cohort.read_table(base.ROOT / "data/derived/katie-cohort-v1/subjects.tsv")
    ids = [r["subject"] for r in roster]
    if len(ids) != 97 or len(set(ids)) != 97: raise ValueError("Frozen N=97 roster differs")
    records, plans, units = {}, {}, []
    for batch, (relative, count, contrasts) in BATCHES.items():
        folder = project / "derivatives/fsl/randomise" / relative
        path = folder / "plan.json"; digest = base.cohort.digest(path)
        if digest != (folder / "plan.sha256").read_text().strip(): raise ValueError("Plan hash mismatch")
        plan = json.loads(path.read_text()); plans[batch] = plan
        if plan["n"] != 97 or len(plan["jobs"]) != count or len({j["key"] for j in plan["jobs"]}) != count:
            raise ValueError("Unexpected completed batch inventory: " + batch)
        add_record(records, path, digest)
        for name, sha in plan["outputs"].items(): add_record(records, folder / name, sha)
        for r in plan["sources"]: add_record(records, r["path"], r["sha256"], r["size"])
        if (folder / "subjects.tsv").exists():
            _, order = base.cohort.read_table(folder / "subjects.tsv")
            if [r["subject"] for r in order] != ids: raise ValueError("Image-family roster differs")
        for job in plan["jobs"]:
            try:names, x, definitions = design(job, ids, contrasts == 4)
            except ValueError as exc:raise ValueError(batch+"/"+job["key"]+": "+str(exc)) from exc
            for path in (Path(job["design"]), Path(job["contrast"]), Path(job["design"]).with_suffix(".tsv")):
                add_record(records, path, base.cohort.digest(path))
            receipt = folder / "jobs" / job["key"] / "success.json"
            saved = json.loads(receipt.read_text())
            if saved["job"] != job or saved["plan_sha256"] != digest or saved["smoke"]:
                raise ValueError("Invalid completed receipt: " + str(receipt))
            prefix = Path(saved["attempt"]) / "randomise"
            if not prefix.parent.resolve().is_relative_to((receipt.parent / "attempts").resolve()):
                raise ValueError("Receipt points outside its job attempts")
            mask = plan.get("mask") or plan["masks"][job["family"]]
            view = dict(plan, mask=mask)
            if saved["command"] != base.command(view, job, prefix):
                raise ValueError("Actual native command differs from frozen specification")
            add_record(records, receipt, base.cohort.digest(receipt))
            for r in saved["outputs"]: add_record(records, r["path"], r["sha256"], r["size"])
            family = job.get("family", "connectivity" if "connectivity" in batch else "activation")
            units.append(dict(batch=batch, family=family, job=job, names=names, definitions=definitions,
                mask=mask, image=plan["images"][job["outcome"]], prefix=str(prefix), receipt=str(receipt)))
        if batch == "group_activation":
            smoke = json.loads((folder / "smoke/success.json").read_text())
            text = (Path(smoke["attempt"]) / "console.log").read_text().lower()
            if (not smoke["smoke"] or smoke["plan_sha256"] != digest or smoke["job"] not in plan["jobs"]
                    or smoke["command"] != base.command(plan,smoke["job"],Path(smoke["attempt"])/"randomise",permutations=2)
                    or not any(v in text for v in ("sign flipping", "sign-flipping"))):
                raise ValueError("Missing native sign-flipping confirmation for group activation")
            add_record(records,folder / "smoke/success.json",base.cohort.digest(folder / "smoke/success.json"))
            add_record(records, Path(smoke["attempt"]) / "console.log", base.cohort.digest(Path(smoke["attempt"]) / "console.log"))
        print(f"INVENTORIED {batch}: {count} jobs / {count*contrasts} directional maps", flush=True)
    for unit in units:
        canonical = plans["environment_connectivity" if unit["family"] == "connectivity" else "group_activation"]
        outcome = unit["job"]["outcome"].split("/")[-1]
        if (Path(unit["image"]).resolve() != Path(canonical["images"][outcome]).resolve()
                or Path(unit["mask"]).resolve() != Path(canonical["mask"]).resolve()):
            raise ValueError("Model refers to a different image stack or mask than its outcome family")
    return ids, records, plans, units


def image_order_audit(project, plans, ids):
    activation = plans["group_activation"]
    connectivity = plans["environment_connectivity"]
    _, pairs = base.cohort.read_table(base.ROOT / "data/derived/katie-cohort-v1/selected_pairs.tsv")
    lookup = base.cohort.unique(pairs, ("subject", "contrast"))
    reference = nib.load(activation["mask"]); mask = reference.get_fdata() > 0
    arrays = {name: np.asarray(nib.load(path).dataobj, dtype=np.float32) for name, path in activation["images"].items()}
    for data in arrays.values():
        if data.shape != reference.shape+(97,) or not np.isfinite(data).all(): raise ValueError("Invalid activation stack")
    timing_rows, evidence = [], set()
    for index, sub in enumerate(ids):
        for task in ("socialdoors", "doors"):
            pair=lookup[(sub,"4")]
            events=Path(plans["environment_activation"]["upstream"])/f"bids/sub-{sub}/ses-01/func/sub-{sub}_ses-01_task-{task}_run-1_events.tsv"
            row,used=remaining.outcome.inspect_run(sub,task,Path(pair[task+"_feat_dir"]),Path(pair[task+"_cope"]),events)
            if row["status"] != "passed":raise ValueError("Outcome-phase L1 audit failed")
            timing_rows.append(row);evidence.update(used);evidence.add(events)
            source = nib.load(lookup[(sub, "4")][task+"_cope"]); base.grid(reference, source)
            if not np.array_equal(arrays[task][..., index][mask], np.asarray(source.dataobj, dtype=np.float32)[mask]):
                raise ValueError(f"Activation participant/source volume mismatch: {sub} {task}")
    if (not np.allclose(arrays["social_specific"][mask], (arrays["socialdoors"]-arrays["doors"])[mask], rtol=1e-5, atol=1e-5)
            or not np.allclose(arrays["average"][mask], ((arrays["socialdoors"]+arrays["doors"])/2)[mask], rtol=1e-5, atol=1e-5)):
        raise ValueError("Activation paired difference/average arithmetic mismatch")
    del arrays
    reference = nib.load(connectivity["mask"]); mask = reference.get_fdata() > 0
    arrays = {name: np.asarray(nib.load(path).dataobj, dtype=np.float32) for name, path in connectivity["images"].items()}
    if any(a.shape != reference.shape+(97,) or not np.isfinite(a).all() for a in arrays.values()):
        raise ValueError("Invalid connectivity stack")
    for index, sub in enumerate(ids):
        values = {}
        for task in ("socialdoors", "doors"):
            receipt = project / f"derivatives/fsl/randomise/katie-remaining-v1/ppi-l1/sub-{sub}_ses-01_task-{task}_run-1/success.json"
            saved = json.loads(receipt.read_text())
            if (saved["job"]["subject"], saved["job"]["task"]) != (sub, task): raise ValueError("PPI identity differs")
            verified=remaining.verify_ppi(Path(saved["feat"]), saved["job"])
            evidence.update(Path(r["path"]) for r in verified);evidence.add(receipt)
            source = nib.load(Path(saved["feat"]) / "stats/cope4.nii.gz"); base.grid(reference, source)
            values[task] = np.asarray(source.dataobj, dtype=np.float32)[mask]
        for name, target in (("social_specific", values["socialdoors"]-values["doors"]),
                             ("average", (values["socialdoors"]+values["doors"])/2)):
            if not np.allclose(arrays[name][..., index][mask], target, rtol=1e-5, atol=1e-5):
                raise ValueError(f"PPI participant/source order or arithmetic differs: {sub} {name}")
    print("CHECK PASSED: 194 activation and 194 compatible VS-PPI source COPEs map to the exact 97-person image order; paired arithmetic verified.", flush=True)
    print("CHECK PASSED: all 194 activation L1 contrasts use feedback win-loss; EV timing agrees with BIDS under the settled formatter rule.",flush=True)
    return timing_rows,[base.fingerprint(p) for p in sorted(evidence)]


def audit(project, report, jobs=24, source_arithmetic=True):
    ids, records, plans, units = inventory(project)
    timing_rows=[]
    if source_arithmetic:
        timing_rows,evidence=image_order_audit(project,plans,ids)
        for r in evidence:add_record(records,r["path"],r["sha256"],r["size"])
    verify_records(records, jobs)
    maps, clusters = [], []
    for number, unit in enumerate(units, 1):
        job = unit["job"]; prefix = unit["prefix"]
        receipt = json.loads(Path(unit["receipt"]).read_text())
        products = conditional.products(Path(prefix), unit["mask"]) if len(unit["definitions"]) == 4 else base.output_images(Path(prefix), unit["mask"])
        if products != receipt["outputs"]: raise ValueError("Native result inventory changed")
        support = nib.load(unit["mask"]); image = nib.load(unit["image"]); base.grid(support, image, 4)
        if image.shape[3] != 97: raise ValueError("Image stack has wrong N")
        for definition in unit["definitions"]:
            index = definition["index"]
            value, found = summary.map_summary(job, definition["direction"], nib.load(prefix+f"_tstat{index}.nii.gz"),
                nib.load(prefix+f"_clustere_corrp_tstat{index}.nii.gz"), support)
            selected = (nib.load(prefix+f"_clustere_corrp_tstat{index}.nii.gz").get_fdata() > .95) & (support.get_fdata() > 0)
            if np.any(nib.load(prefix+f"_tstat{index}.nii.gz").get_fdata()[selected] < job["t_cutoff"]-1e-5):
                raise ValueError("Corrected significant voxels lie below the declared CDT")
            extra = dict(batch=unit["batch"], family=unit["family"], term=definition["term"], contrast_index=index,
                outcome=job["outcome"].split("/")[-1], design=job["design"], image=unit["image"], mask=unit["mask"],
                tstat=prefix+f"_tstat{index}.nii.gz", corrp=prefix+f"_clustere_corrp_tstat{index}.nii.gz")
            maps.append(dict(value, **extra)); clusters.extend(dict(c, **extra) for c in found)
        if number % 16 == 0 or number == len(units): print(f"MAP AUDIT {number}/{len(units)} jobs", flush=True)
    if len(units) != 152 or len(maps) != 336: raise ValueError("Expected all 152 jobs and 336 directional maps")
    provenance = dict(n=97, jobs=152, directional_maps=336, source_arithmetic_verified=source_arithmetic,
        outcome_phase_runs_verified=len(timing_rows),auditor=base.fingerprint(Path(__file__)),
        fingerprint_records=list(records.values()), batches={k:dict(jobs=v[1], maps=v[1]*v[2]) for k,v in BATCHES.items()},
        inference="Existing per-map cluster-FWE; no additional across-model correction", production_changed=False)
    report.mkdir(parents=True, exist_ok=True)
    (report / "audit.json").write_text(base.cohort.json_text(provenance))
    (report / "maps.tsv").write_text(base.review.tsv(maps))
    if timing_rows:(report / "outcome_phase.tsv").write_text(base.review.tsv(timing_rows))
    fields = list(maps[0]) + [k for k in summary.CLUSTER_FIELDS if k not in maps[0]]
    (report / "clusters.tsv").write_text(base.review.tsv(clusters, fields))
    print("CHECK PASSED: all 152 jobs / 336 maps audited; N=97 and settled exclusions unchanged.", flush=True)
    return maps, clusters, provenance


def main():
    os.umask(0)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=24)
    args = parser.parse_args()
    if not 1 <= args.jobs <= 48: parser.error("--jobs must be 1..48")
    audit(args.project.resolve(), args.report.resolve(), args.jobs)


if __name__ == "__main__":
    try: main()
    except Exception as exc:
        print(f"FAILED ({type(exc).__name__}): {exc}", file=sys.stderr, flush=True); sys.exit(1)
