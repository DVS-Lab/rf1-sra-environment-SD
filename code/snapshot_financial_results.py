#!/usr/bin/env python3
"""Read-only progress and verified completed-result snapshot of the financial batches."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import nibabel as nib

import run_katie_randomise as base
import summarize_katie_randomise as summary

BATCHES = {"predictors": ("katie-financial-v1", 16), "moderation": ("katie-financial-moderation-v1", 64)}
JOB_FIELDS = ["batch", "job", "state", "role", "family", "model", "outcome", "z", "process_group",
              "seconds_since_console_update", "console_tail", "recorded_failure", "finding"]
EXTRA = ["batch", "family", "role"]


def process_snapshot(project):
    call = ["ps", "-ww", "-u", str(os.getuid()), "-o", "pid=,ppid=,pgid=,etime=,time=,pcpu=,rss=,stat=,args="]
    result = subprocess.run(call, capture_output=True, text=True, check=True)
    fields = ["pid", "ppid", "pgid", "elapsed", "cpu_time", "cpu_percent_lifetime", "rss_kib", "state", "args"]
    rows = []
    for line in result.stdout.splitlines():
        values = line.split(None, 8)
        if len(values) != 9:
            continue
        command = values[-1]
        if str(project) in command and ("/katie-financial" in command or
                any(name in command for name in ("run_financial_models.", "run_financial_moderation."))):
            rows.append(dict(zip(fields, values)))
    return rows


def tail(path):
    if not path.exists():
        return "", ""
    modified = path.stat().st_mtime
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size - 8192))
        content = stream.read().decode(errors="replace")
    return max(0, round(time.time() - modified, 1)), "\n".join(content.splitlines()[-8:])


def checked_plan(folder, expected, roster):
    path = folder / "plan.json"
    digest = base.cohort.digest(path)
    if digest != (folder / "plan.sha256").read_text().strip():
        raise ValueError("Frozen plan hash differs")
    plan = json.loads(path.read_text())
    if plan["n"] != 97 or len(plan["jobs"]) != expected or len({j["key"] for j in plan["jobs"]}) != expected:
        raise ValueError("Unexpected frozen financial job inventory")
    if (folder / "subjects.tsv").read_text() != roster:
        raise ValueError("Snapshot roster differs from frozen N=97 order")
    for name, saved in plan["outputs"].items():
        if base.cohort.digest(folder / name) != saved:
            raise ValueError("Frozen design/roster artifact changed: " + name)
    for mask in set(plan["masks"].values()):
        saved = [r for r in plan["sources"] if Path(r["path"]).resolve() == Path(mask).resolve()]
        if not saved:
            raise ValueError("No frozen support-mask fingerprint")
        base.verify_sources(saved)
    return plan, digest


def snapshot(project, processes):
    roster = (base.ROOT / "data/derived/katie-cohort-v1/subjects.tsv").read_text()
    jobs, maps, clusters, batches = [], [], [], []
    for batch, (name, expected) in BATCHES.items():
        folder = project / "derivatives/fsl/randomise" / name
        info = dict(batch=batch, planned=expected, receipt_verified=0, live=0, queued=0,
                    incomplete=0, invalid=0, prepared=False, errors=[], recorded_validation_failures={}, recorded_job_failures={})
        batches.append(info)
        if not (folder / "plan.json").exists():
            info["errors"].append("Plan not present; batch may still be in preflight")
            continue
        try:
            plan, digest = checked_plan(folder, expected, roster)
        except Exception as exc:
            info["errors"].append(str(exc)); continue
        info["prepared"] = True
        info["plan_sha256"] = digest
        # Sources were authenticated by the launch preflight. This quick snapshot
        # rechecks immutable designs/receipts/maps, not every large source image.
        failures = {}
        if (folder / "status.json").exists():
            try:
                failures = json.loads((folder / "status.json").read_text()).get("failures", {})
                info["recorded_validation_failures"] = {k: v for k, v in failures.items() if k not in {j["key"] for j in plan["jobs"]}}
                info["recorded_job_failures"] = {k: v for k, v in failures.items() if k in {j["key"] for j in plan["jobs"]}}
            except (ValueError, OSError) as exc:
                info["errors"].append("Cannot read coordinator status: " + str(exc))
        # Freeze the receipt list before reading maps; never inspect live partial corrp images.
        completed = {j["key"] for j in plan["jobs"] if (folder / "jobs" / j["key"] / "success.json").exists()}
        for job in plan["jobs"]:
            unit = folder / "jobs" / job["key"]
            row = dict(batch=batch, job=job["key"], state="QUEUED", role=job["role"], family=job["family"],
                       model=job["model"], outcome=job["outcome"], z=job["z"], process_group="",
                       seconds_since_console_update="", console_tail="", recorded_failure=failures.get(job["key"], ""), finding="")
            if job["key"] in completed:
                try:
                    saved = json.loads((unit / "success.json").read_text())
                    if saved["job"] != job or saved["plan_sha256"] != digest or saved["smoke"]:
                        raise ValueError("Completed receipt mismatch")
                    prefix = Path(saved["attempt"]) / "randomise"
                    if not prefix.parent.resolve().is_relative_to((unit / "attempts").resolve()):
                        raise ValueError("Receipt points outside this job's attempts")
                    base.verify_sources(saved["outputs"])
                    if base.output_images(prefix, plan["masks"][job["family"]]) != saved["outputs"]:
                        raise ValueError("Completed result inventory differs")
                    found_maps, found_clusters = [], []
                    for index, direction in ((1, "positive"), (2, "negative")):
                        value, found = summary.map_summary(job, direction, nib.load(str(prefix) + f"_tstat{index}.nii.gz"),
                            nib.load(str(prefix) + f"_clustere_corrp_tstat{index}.nii.gz"), nib.load(plan["masks"][job["family"]]))
                        extra = dict(batch=batch, family=job["family"], role=job["role"])
                        found_maps.append(dict(value, **extra)); found_clusters.extend(dict(r, **extra) for r in found)
                    maps.extend(found_maps); clusters.extend(found_clusters)
                    row["state"] = "RECEIPT_VERIFIED"; info["receipt_verified"] += 1
                except Exception as exc:
                    row["state"] = "INVALID_RECEIPT_OR_RESULT"; row["finding"] = str(exc); info["invalid"] += 1
            else:
                marker = unit / "running.json"
                attempts = sorted((unit / "attempts").glob("attempt-*")) if (unit / "attempts").exists() else []
                if attempts:
                    row["seconds_since_console_update"], row["console_tail"] = tail(attempts[-1] / "console.log")
                if marker.exists():
                    try:
                        running = json.loads(marker.read_text())
                        row["process_group"] = running["process_group"]
                        prefix = running["command"][running["command"].index("-o") + 1]
                        alive = any(str(running["process_group"]) == p["pgid"] and prefix in p["args"] for p in processes)
                        row["state"] = "LIVE" if alive else "INCOMPLETE_NO_MATCHING_LIVE_PROCESS"
                    except Exception as exc:
                        row["state"] = "INCOMPLETE_MARKER"; row["finding"] = str(exc)
                elif attempts:
                    row["state"] = "INCOMPLETE_ATTEMPT"
                if row["state"] == "LIVE": info["live"] += 1
                elif row["state"] == "QUEUED": info["queued"] += 1
                else: info["incomplete"] += 1
            jobs.append(row)
    return batches, jobs, maps, clusters


def main():
    os.umask(0)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--sample-seconds", type=float, default=5)
    args = parser.parse_args(); args.project = args.project.resolve()
    if not 0 <= args.sample_seconds <= 30: parser.error("--sample-seconds must be 0..30")
    if args.report.exists(): raise ValueError("Select a new timestamped snapshot; no existing report overwritten")
    started = datetime.now(timezone.utc).isoformat()
    first = process_snapshot(args.project)
    if args.sample_seconds: time.sleep(args.sample_seconds)
    second = process_snapshot(args.project)
    batches, jobs, maps, clusters = snapshot(args.project, second)
    for batch in batches:
        print(f"PROGRESS {batch['batch']}: verified={batch['receipt_verified']}/{batch['planned']} live={batch['live']} "
              f"queued={batch['queued']} incomplete={batch['incomplete']} invalid={batch['invalid']}", flush=True)
        for error in batch["errors"]: print("SNAPSHOT NOTE: " + error, flush=True)
        for key, value in batch["recorded_validation_failures"].items(): print(f"RECORDED VALIDATION FAILURE {key}: {value}", flush=True)
        for key, value in batch["recorded_job_failures"].items(): print(f"RECORDED JOB FAILURE {key}: {value}", flush=True)
    for label, rows in (("FIRST", first), ("SECOND", second)):
        print(f"PROCESS SAMPLE {label}: CPU% is lifetime average, CPU_TIME is cumulative; compare samples.", flush=True)
        for row in rows: print(base.cohort.json_text(row).strip(), flush=True)
    for row in jobs:
        if row["state"] not in ("QUEUED", "RECEIPT_VERIFIED"):
            print("JOB DETAIL " + base.cohort.json_text(row).strip(), flush=True)
    print("COMPLETED-MAP RESULTS ONLY: interim, incomplete family; no result-driven stopping or model changes.", flush=True)
    for row in maps:
        print(f"RESULT {row['batch']} {row['job']} {row['direction']}: min cluster-FWE p={row['min_cluster_fwe_p']:.4f}; "
              f"significant voxels={row['significant_voxels']}", flush=True)
    print("COMPLETED-MAP CLUSTERS (MNI millimetres; descriptive components of existing corrected maps):", flush=True)
    print(base.review.tsv(clusters, summary.CLUSTER_FIELDS + EXTRA), flush=True)
    info = dict(started_utc=started, finished_utc=datetime.now(timezone.utc).isoformat(), batches=batches,
                n=97, source_images_rehashed=False, full_source_lineage_preflight_required=True,
                snapshot_only=True, interim=True, cross_analysis_correction="none; exploratory per-map FWE",
                processes_first=first, processes_second=second)
    files = {"jobs.tsv": base.review.tsv(jobs, JOB_FIELDS),
             "maps.tsv": base.review.tsv(maps, ["job", "outcome", "model", "direction", "z", "t_cutoff", "n",
                "min_cluster_fwe_p", "significant_voxels", "significant_clusters", "max_contrast_t", *EXTRA]),
             "clusters.tsv": base.review.tsv(clusters, summary.CLUSTER_FIELDS + EXTRA),
             "provenance.json": base.cohort.json_text(info),
             "README.md": "# Financial Batches: Read-Only Interim Snapshot\n\n"
                "See provenance.json for job counts and two process samples; jobs.tsv includes every planned job in prepared batches. "
                "maps.tsv includes both directions and nulls only for hash/receipt-verified completed jobs. No live partial maps read. "
                "Some jobs can finish during the snapshot; it is a time window, not an atomic census. "
                "No running code, outputs, exclusions, models or processes changed. Full source-image hashes were checked at launch, "
                "not repeated here. Console silence alone does not establish a stalled native job. "
                "These are interim exploratory per-map FWE results, not correction across the whole model family. "
                "Do not stop or change models based on this peek.\n"}
    args.report.mkdir(parents=True)
    for name, text in files.items(): (args.report / name).write_text(text)
    print("SNAPSHOT SAVED: " + str(args.report), flush=True)
    if any(b["invalid"] or b["errors"] or b["recorded_validation_failures"] or b["recorded_job_failures"] for b in batches):
        raise RuntimeError("Snapshot saved with findings; inspect it without deleting or restarting outputs")
    print("CHECK PASSED: snapshot artifacts written; completed maps verified; no inference restarted or inputs changed.", flush=True)


if __name__ == "__main__":
    try: main()
    except Exception as exc:
        print(f"FAILED ({type(exc).__name__}): {exc}", file=sys.stderr, flush=True); sys.exit(1)
