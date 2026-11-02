#!/usr/bin/env python3
"""Run constituent main-effect contrasts against unchanged completed Katie designs."""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
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

import run_katie_randomise as base
import summarize_katie_randomise as summary


def contrasts(names, exposure, moderator):
    rows, definitions = [], []
    for term in (exposure, moderator):
        if names.count(term) != 1:
            raise ValueError("Missing/duplicate constituent main-effect column: " + term)
        for direction, weight in (("positive", 1), ("negative", -1)):
            rows.append([weight if name == term else 0 for name in names])
            definitions.append(dict(index=len(rows), name=term + "_" + direction, term=term, direction=direction))
    text = "".join(f"/ContrastName{r['index']}\t{r['name']}\n" for r in definitions)
    text += f"/NumWaves\t{len(names)}\n/NumContrasts\t4\n/PPheights\t1\t1\t1\t1\n"
    text += "/RequiredEffect\t1\t1\t1\t1\n/Matrix\n"
    text += "".join("\t".join(map(str, row)) + "\n" for row in rows)
    return text, definitions


def specifications(baseline, output):
    files, jobs = {}, []
    for original in baseline["jobs"]:
        exposure, moderator = base.review.MODELS[original["model"]]
        if moderator is None:
            continue  # Standalone exposure contrasts already finished in the original batch.
        if original["residual_dof"] != 87 or original["permutations"] != 10000:
            raise ValueError("Unexpected original interaction design specification")
        names = Path(original["design"]).with_suffix(".tsv").read_text().splitlines()[0].split("\t")
        if names[0] != "subject" or len(names) != 11 or names[-3:] != [exposure, moderator, original["model"]]:
            raise ValueError("Original design columns differ from the approved interaction model")
        relative = Path("contrasts") / original["outcome"] / original["model"]
        text, definitions = contrasts(names[1:], exposure, moderator)
        files[str(relative / "design.con")] = text
        files[str(relative / "contrasts.tsv")] = base.review.tsv(definitions)
        jobs.append(dict(original, contrast=str(output / relative / "design.con"), contrasts=definitions))
    if len(jobs) != 16 or len({j["key"] for j in jobs}) != 16:
        raise ValueError("Expected exactly 16 additional jobs")
    return files, jobs


def build(args):
    if (args.output / "plan.json").exists():
        check(args)
        print("REUSED: additional main-effect plan unchanged", flush=True)
        return
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Unrecognized output directory; refusing overwrite")
    baseline = base.check(SimpleNamespace(output=args.baseline, upstream=args.upstream))
    _, _, verified = summary.summarize(args.baseline)
    files, jobs = specifications(baseline, args.output)
    paths = {Path(r["path"]) for r in baseline["sources"]}
    paths.update(args.baseline / name for name in baseline["outputs"])
    paths.update([args.baseline / "plan.json", args.baseline / "plan.sha256", Path(__file__),
                  Path(summary.__file__), base.ROOT / "code/run_katie_main_effects.sh",
                  base.ROOT / "code/audit_katie_outcome.py"])
    for original in baseline["jobs"]:
        receipt = args.baseline / "jobs" / original["key"] / "success.json"
        paths.add(receipt)
        paths.update(Path(r["path"]) for r in json.loads(receipt.read_text())["outputs"])
    staging = Path(tempfile.mkdtemp(prefix="." + args.output.name + "-build-", dir=args.output.parent))
    staging.chmod(0o777)
    for name, text in files.items():
        path = staging / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    plan = dict(schema_version=1, n=97, baseline=str(args.baseline), jobs=jobs,
                images=baseline["images"], mask=baseline["mask"], randomise=baseline["randomise"],
                sources=[base.fingerprint(p) for p in sorted(paths)],
                outputs={name: base.cohort.digest(staging / name) for name in files},
                baseline_verification=verified,
                interpretation="Conditional constituent effects, other centered predictor at zero; exploratory per-map FWE",
                exclusions_changed=False, original_images_and_designs_changed=False)
    base.write_json(staging / "plan.json", plan)
    (staging / "plan.sha256").write_text(base.cohort.digest(staging / "plan.json") + "\n")
    if base.STOP:
        raise InterruptedError("Stopped; staged plan preserved: " + str(staging))
    staging.rename(args.output)
    check(args)


def check(args):
    plan = base.load_plan(args.output)
    baseline = base.load_plan(args.baseline)
    if (plan["baseline"] != str(args.baseline) or plan["n"] != 97
            or plan["images"] != baseline["images"] or plan["mask"] != baseline["mask"]
            or plan["randomise"] != baseline["randomise"]):
        raise ValueError("Original baseline, images, mask or executable differs")
    files, jobs = specifications(baseline, args.output)
    if jobs != plan["jobs"]:
        raise ValueError("Additional job specification changed")
    for name, text in files.items():
        if (args.output / name).read_text() != text or base.cohort.digest(args.output / name) != plan["outputs"][name]:
            raise ValueError("New contrasts changed: " + name)
    print("CHECK PASSED: same N=97, row order, images, masks and original designs; "
          "16 additional jobs / 64 directional maps; exposure and moderator main effects only.", flush=True)
    return plan


def products(prefix, mask_path):
    reference = nib.load(mask_path)
    for index in range(1, 5):
        for suffix in (f"_tstat{index}.nii.gz", f"_clustere_corrp_tstat{index}.nii.gz"):
            path = Path(str(prefix) + suffix)
            image = nib.load(path)
            base.grid(reference, image)
            values = image.get_fdata()
            if not np.isfinite(values).all() or ("corrp" in suffix and (values.min() < 0 or values.max() > 1)):
                raise ValueError("Invalid randomise output: " + str(path))
    return [base.fingerprint(p) for p in sorted(prefix.parent.glob(prefix.name + "*")) if p.is_file()]


def execute(plan, job, folder, plan_hash, smoke=False):
    # The original runner is fingerprint-frozen, so its two-contrast executor is
    # not edited. This separate executor requires all four new contrasts.
    folder.mkdir(parents=True, exist_ok=True)
    receipt = folder / "success.json"
    if receipt.exists():
        saved = json.loads(receipt.read_text())
        if saved["job"] != job or saved["plan_sha256"] != plan_hash or saved["smoke"] != smoke:
            raise ValueError("Completed main-effect receipt differs")
        if products(Path(saved["attempt"]) / "randomise", plan["mask"]) != saved["outputs"]:
            raise ValueError("Completed main-effect outputs changed")
        return "REUSED"
    running = folder / "running.json"
    if running.exists() and base.group_alive(json.loads(running.read_text())["process_group"]):
        raise ValueError("Active randomise group; refusing duplicate: " + job["key"])
    if base.STOP:
        return "NOT_STARTED"
    attempts = folder / "attempts"
    attempts.mkdir(exist_ok=True)
    number = 1
    while (attempts / f"attempt-{number:04d}").exists():
        number += 1
    destination = attempts / f"attempt-{number:04d}"
    destination.mkdir()
    prefix = destination / "randomise"
    call = base.command(plan, job, prefix, permutations=2 if smoke else None)
    base.write_json(destination / "command.json", dict(command=call, job=job, smoke=smoke))
    print(("SMOKE " if smoke else "STARTED ") + job["key"], flush=True)
    with (destination / "console.log").open("w") as log:
        process = subprocess.Popen(call, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                                   pass_fds=() if base.LEASE_FD is None else (base.LEASE_FD,))
        base.write_json(running, dict(process_group=process.pid, command=call))
        try:
            while process.poll() is None:
                if base.STOP:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    raise InterruptedError("Stopped; completed results and partial attempt preserved")
                time.sleep(.25)
        finally:
            if process.poll() is not None:
                running.unlink(missing_ok=True)
    if process.returncode:
        ending = "\n".join((destination / "console.log").read_text(errors="replace").splitlines()[-25:])
        raise RuntimeError(f"randomise exited {process.returncode}; {destination}/console.log\n{ending}")
    outputs = products(prefix, plan["mask"])
    base.write_json(receipt, dict(plan_sha256=plan_hash, job=job, smoke=smoke, outputs=outputs,
                                 attempt=str(destination), command=call, completed=datetime.now(timezone.utc).isoformat()))
    return "COMPLETED"


def result_files(args, plan):
    mask = nib.load(plan["mask"])
    digest = base.cohort.digest(args.output / "plan.json")
    maps, clusters, receipts = [], [], []
    for job in plan["jobs"]:
        path = args.output / "jobs" / job["key"] / "success.json"
        receipt = json.loads(path.read_text())
        if receipt["job"] != job or receipt["plan_sha256"] != digest or receipt["smoke"]:
            raise ValueError("Main-effect result receipt differs")
        prefix = Path(receipt["attempt"]) / "randomise"
        if products(prefix, plan["mask"]) != receipt["outputs"]:
            raise ValueError("Main-effect result inventory differs")
        receipts.append(base.fingerprint(path))
        for contrast in job["contrasts"]:
            index = contrast["index"]
            row, found = summary.map_summary(job, contrast["direction"],
                nib.load(str(prefix) + f"_tstat{index}.nii.gz"),
                nib.load(str(prefix) + f"_clustere_corrp_tstat{index}.nii.gz"), mask)
            metadata = dict(term=contrast["term"], contrast_index=index)
            maps.append(dict(row, **metadata))
            clusters.extend(dict(r, **metadata) for r in found)
    if len(maps) != 64:
        raise ValueError("Expected 64 additional directional maps")
    lines = ["# Katie N=97 Conditional Main Effects", "",
             "All 16 additional jobs / 64 maps verified. Original 24 jobs, N=97, images,",
             "design matrices, exclusions and thresholds are unchanged. These effects are",
             "conditional on the other centered predictor being zero, not replacements",
             "for the standalone exposure effects or the original interaction tests.",
             "Per-map cluster-FWE only; exploratory across analyses. All CDTs/directions",
             "are reported. Components describe existing corrected maps (26-connectivity).", "",
             "| Outcome | Model | Term | Direction | CDT Z | Minimum cluster-FWE p | Significant voxels |",
             "|---|---|---|---|---|---|---|"]
    for row in maps:
        lines.append(f"| {row['outcome']} | {row['model']} | {row['term']} | {row['direction']} | "
                     f"{row['z']} | {row['min_cluster_fwe_p']:.4f} | {row['significant_voxels']} |")
    provenance = dict(plan_sha256=digest, receipts=receipts, n=97, jobs=16, maps=64,
                      alpha=.05, rule="corrected_1_minus_p > 0.95 inside unchanged common mask",
                      cross_analysis_correction="none; exploratory", original_results_changed=False)
    files = {"README.md": "\n".join(lines) + "\n", "maps.tsv": base.review.tsv(maps),
             "clusters.tsv": base.review.tsv(clusters, summary.CLUSTER_FIELDS + ["term", "contrast_index"]),
             "provenance.json": base.cohort.json_text(provenance)}
    return files, maps


def check_results(args):
    plan = check(args)
    files, maps = result_files(args, plan)
    for name, text in files.items():
        path = args.report / name
        if path.exists() and path.read_text() != text:
            raise ValueError("Existing report differs; preserve it and use a different --report directory")
    args.report.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        path = args.report / name
        if not path.exists():
            path.write_text(text)
    base.verify_sources(plan["sources"])
    print("CHECK PASSED: 16 additional jobs / 64 maps verified; original results and exclusions unchanged.", flush=True)
    for row in maps:
        print(f"{row['job']} {row['term']} {row['direction']}: min cluster-FWE p={row['min_cluster_fwe_p']:.4f}; "
              f"significant voxels={row['significant_voxels']}", flush=True)
    print("REPORT: " + str(args.report), flush=True)


def run(args):
    plan = check(args)
    digest = base.cohort.digest(args.output / "plan.json")
    status = args.output / "status.json"
    base.write_json(status, dict(status="smoke_test", n=97, total=16, outcomes={}))
    if execute(plan, plan["jobs"][0], args.output / "smoke", digest, smoke=True) == "NOT_STARTED":
        raise InterruptedError("Stopped before smoke test")
    print("SMOKE PASSED: all four constituent-effect contrasts verified (2 permutations only).", flush=True)
    outcomes = {}
    print(f"STAGE RANDOMISE MAIN EFFECTS: 16 jobs, {args.jobs} workers; 10000 permutations; no TFCE/PALM", flush=True)
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(execute, plan, job, args.output / "jobs" / job["key"], digest): job for job in plan["jobs"]}
        while futures:
            done, _ = wait(futures, timeout=60, return_when=FIRST_COMPLETED)
            if not done:
                print(f"HEARTBEAT finished={len(outcomes)}/16 pending_or_running={len(futures)}", flush=True)
            for future in done:
                job = futures.pop(future)
                try:
                    outcomes[job["key"]] = future.result()
                except Exception as exc:
                    outcomes[job["key"]] = "FAILED: " + str(exc)
                print(f"{outcomes[job['key']]} {job['key']} ({len(outcomes)}/16)", flush=True)
            base.write_json(status, dict(status="running", n=97, total=16, outcomes=outcomes))
    failed = any(v not in ("COMPLETED", "REUSED") for v in outcomes.values())
    base.write_json(status, dict(status="failed" if failed else "verifying", n=97, total=16, outcomes=outcomes))
    if failed:
        raise RuntimeError("Some jobs incomplete; preserve outputs and resume the same command")
    check_results(args)
    base.write_json(status, dict(status="complete", n=97, total=16, outcomes=outcomes))


def main():
    os.umask(0)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "check", "run", "check-results"))
    parser.add_argument("--baseline", type=Path, default=base.ROOT / "derivatives/fsl/randomise/katie-v1")
    parser.add_argument("--output", type=Path, default=base.ROOT / "derivatives/fsl/randomise/katie-main-effects-v1")
    parser.add_argument("--report", type=Path, default=base.ROOT / "results/randomise/katie-main-effects-v1")
    parser.add_argument("--upstream", type=Path, default=Path("/ZPOOL/data/projects/rf1-sra-linux2"))
    parser.add_argument("--jobs", type=int, default=16)
    args = parser.parse_args()
    for name in ("baseline", "output", "report", "upstream"):
        setattr(args, name, getattr(args, name).resolve())
    if not 1 <= args.jobs <= 16:
        parser.error("--jobs must be between 1 and 16")
    if args.output == args.baseline or args.baseline in args.output.parents:
        parser.error("Additional outputs must be separate from the original analysis")
    if args.output in args.baseline.parents:
        parser.error("Output may not contain the original analysis")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGTERM, base.stop)
    signal.signal(signal.SIGINT, base.stop)
    with (args.output.parent / ("." + args.output.name + ".lock")).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        base.LEASE_FD = lock.fileno()
        {"build": build, "check": check, "run": run, "check-results": check_results}[args.command](args)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAILED ({type(exc).__name__}): {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
