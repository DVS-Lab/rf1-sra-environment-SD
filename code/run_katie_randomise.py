#!/usr/bin/env python3
"""Build/check isolated Katie inputs and run resumable cluster-extent randomise."""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

import nibabel as nib
import numpy as np
from scipy.stats import norm, t

import freeze_katie_cohort as cohort
import review_katie_models as review

ROOT = Path(__file__).resolve().parents[1]
STOP = False
LEASE_FD = None


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(cohort.json_text(value))
    temporary.replace(path)


def fingerprint(path):
    path = Path(path).resolve()
    return dict(path=str(path), size=path.stat().st_size, sha256=cohort.digest(path))


def verify_sources(records):
    for record in records:
        if fingerprint(record["path"]) != record:
            raise ValueError("Frozen input changed: " + record["path"])


def load_plan(output):
    path = output / "plan.json"
    if cohort.digest(path) != (output / "plan.sha256").read_text().strip():
        raise ValueError("Analysis plan changed")
    plan = json.loads(path.read_text())
    verify_sources(plan["sources"])
    return plan


def grid(reference, image, ndim=3):
    if (len(image.shape) != ndim or reference.shape[:3] != image.shape[:3]
            or not np.allclose(reference.affine, image.affine, atol=1e-5, rtol=0)):
        raise ValueError("Image grid mismatch; no implicit resampling")


def save_image(path, data, reference):
    path.parent.mkdir(parents=True, exist_ok=True)
    header = reference.header.copy()
    header.set_data_dtype(data.dtype)
    header.set_intent("none")
    image = nib.Nifti1Image(data, reference.affine, header)
    if data.ndim == 4:
        image.header.set_xyzt_units(reference.header.get_xyzt_units()[0], "unknown")
        image.header.set_zooms((*reference.header.get_zooms()[:3], 1.0))
        image.header["descrip"] = b"Katie: fourth dimension is participant, not time"
    temporary = path.with_name(path.name.replace(".nii.gz", ".tmp.nii.gz"))
    nib.save(image, temporary)
    temporary.replace(path)


def vest_matrix(x):
    return f"/NumWaves\t{x.shape[1]}\n/NumPoints\t{x.shape[0]}\n/PPheights\t" + \
        "\t".join("1" for _ in range(x.shape[1])) + "\n/Matrix\n" + \
        "".join("\t".join(format(v, ".17g") for v in row) + "\n" for row in x)


def vest_contrasts(names, target):
    positive = np.array([1.0 if n == target else 0.0 for n in names])
    rows = np.stack([positive, -positive])
    return (f"/ContrastName1\t{target}_positive\n/ContrastName2\t{target}_negative\n"
            f"/NumWaves\t{len(names)}\n/NumContrasts\t2\n/PPheights\t1\t1\n"
            "/RequiredEffect\t1\t1\n/Matrix\n" +
            "".join("\t".join(format(v, ".17g") for v in row) + "\n" for row in rows))


def approved_config():
    config = json.loads((ROOT / "config/analysis_decisions.json").read_text())
    inference = config["inference"]
    if (not config["execution_authorized"] or config["cohort"]["n"] != 97
            or config["models"] != list(review.MODELS) or inference["engine"] != "randomise"
            or inference["method"] != "cluster_extent_permutation_FWE"
            or inference["tfce"] or inference["palm_allowed"]
            or inference["cluster_forming_z"] != [2.6, 3.1]
            or inference["permutations"] != 10000):
        raise ValueError("Configuration differs from the approved analysis")
    expected = {"social_specific": "signed_differences", "average": "pair_means"}
    for outcome, mode in expected.items():
        if (config["outcomes"][outcome]["approved_qc_mode"] != mode
                or config["outcomes"][outcome]["approved_qc_terms"] != list(review.QC_OPTIONS[mode])):
            raise ValueError("Approved paired QC specification changed")
    return config


def live_eras(upstream, variables, pairs):
    lookup = {(r["subject"], r["contrast"]): r for r in pairs}
    result, paths = [], []
    for v in variables:
        sub = v["subject"]
        for task in cohort.TASKS:
            path = upstream / f"bids/sub-{sub}/ses-01/func/sub-{sub}_ses-01_task-{task}_run-1_echo-2_part-mag_bold.json"
            metadata = json.loads(path.read_text())
            version = str(metadata.get("SoftwareVersions", "")).upper()
            labels = [era for era in ("E11", "XA30", "XA60") if era in version]
            if len(labels) != 1:
                raise ValueError("Unrecognized live SoftwareVersions: " + str(path))
            pair = lookup[(sub, "4")]
            result.append(dict(subject=sub, session="01", run="1", task=task, software_era=labels[0],
                               tsnr=pair[task + "_tsnr"], fd_mean=pair[task + "_fd_mean"]))
            paths.append(path)
    return result, paths


def image_arrays(pairs, ids, difference_path, mask_path):
    reference = nib.load(mask_path)
    mask_data = reference.get_fdata()
    if not np.isin(mask_data, (0, 1)).all() or not mask_data.any():
        raise ValueError("Invalid analysis mask")
    mask = mask_data.astype(bool)
    difference = nib.load(difference_path)
    grid(reference, difference, 4)
    if difference.shape[3] != len(ids):
        raise ValueError("Difference stack has wrong participant count")
    lookup = {(r["subject"], r["contrast"]): r for r in pairs}
    average = np.zeros(difference.shape, dtype=np.float32)
    for index, sub in enumerate(ids):
        row = lookup[(sub, "4")]
        values = {}
        for task in cohort.TASKS:
            image = nib.load(row[task + "_cope"])
            grid(reference, image)
            values[task] = image.get_fdata()[mask]
        a, b = values["socialdoors"], values["doors"]
        actual = np.asarray(difference.dataobj[..., index], dtype=np.float32)
        if (not np.array_equal(actual[mask], (a - b).astype(np.float32))
                or not np.isfinite(actual).all() or np.any(actual[~mask] != 0)):
            raise ValueError("Difference direction, volume order or masked pixels differ")
        average[..., index][mask] = (a + b) / 2
    if not np.isfinite(average).all():
        raise ValueError("Nonfinite average effect")
    return reference, average


def make_designs(output, config, ids, terms):
    files, jobs, diagnostics = {}, [], []
    for outcome in ("social_specific", "average"):
        settings = config["outcomes"][outcome]
        for model in config["models"]:
            names, x, contrasts, info = review.model_preview(terms, model, settings["approved_qc_mode"])
            folder = Path("designs") / outcome / model
            files[str(folder / "design.mat")] = vest_matrix(x)
            files[str(folder / "design.con")] = vest_contrasts(names, info["scientific_target"])
            files[str(folder / "design.tsv")] = review.tsv([dict(subject=s, **dict(zip(names, row))) for s, row in zip(ids, x)])
            diagnostics.append(dict(outcome=outcome, **info))
            for z in config["inference"]["cluster_forming_z"]:
                dof = len(ids) - int(np.linalg.matrix_rank(x))
                cutoff = float(t.isf(norm.sf(z), dof))
                pinned = config["inference"]["verified_t_thresholds"][str(dof)][str(z)]
                if not np.isclose(cutoff, pinned, rtol=0, atol=1e-10):
                    raise ValueError("Actual model degrees of freedom/threshold differs from approved plan")
                key = outcome + "/" + model + "/z-" + str(z).replace(".", "p")
                jobs.append(dict(key=key, outcome=outcome, model=model, z=z, t_cutoff=cutoff, residual_dof=dof,
                                 design=str(output / folder / "design.mat"), contrast=str(output / folder / "design.con"),
                                 permutations=config["inference"]["permutations"], seed=20261101))
    files["design_diagnostics.json"] = cohort.json_text(diagnostics)
    return files, jobs


def build(args):
    if (args.output / "plan.json").exists():
        check(args)
        print("REUSED: validated inputs/designs unchanged", flush=True)
        return
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Unrecognized nonempty output directory; refusing overwrite")
    config = approved_config()
    expected, _ = cohort.generate(ROOT, args.upstream)
    cohort.verify(ROOT / "data/derived/katie-cohort-v1", expected)
    roster = ROOT / config["cohort"]["path"]
    if cohort.digest(roster) != config["cohort"]["sha256"]:
        raise ValueError("Frozen roster hash differs")
    subset = args.upstream / "work/randomise-katie-final-v1"
    builder = args.upstream / "code/build_socialdoors_randomise.py"
    for command in (("check",) if (subset / "plan.json").exists() else ("build", "check")):
        call = [sys.executable, str(builder), command, "--output", str(subset)]
        if command == "build":
            call += ["--cohort", str(roster)]
        print("STAGE subset " + command, flush=True)
        subprocess.run(call, check=True, cwd=args.upstream)
    _, order = cohort.read_table(subset / "subjects.tsv")
    ids = [r["subject"] for r in order]
    _, frozen_order = cohort.read_table(roster)
    if ids != [r["subject"] for r in frozen_order]:
        raise ValueError("Subset order differs from frozen cohort")
    _, variables = cohort.read_table(ROOT / "data/derived/katie-cohort-v1/analysis_variables.tsv")
    _, pairs = cohort.read_table(ROOT / "data/derived/katie-cohort-v1/selected_pairs.tsv")
    era, sidecars = live_eras(args.upstream, variables, pairs)
    aligned_ids, raw, terms = review.aligned_terms(variables, pairs, era)
    if aligned_ids != ids:
        raise ValueError("Live covariate order differs")
    preview = ROOT / "data/derived/model-review-v1/aligned_raw_terms.tsv"
    if review.tsv(raw) != preview.read_text():
        raise ValueError("Live scanner eras/terms differ from reviewed 97-person table")
    difference, mask = subset / "cope-4/difference_4d.nii.gz", subset / "cope-4/mask.nii.gz"
    reference, average = image_arrays(pairs, ids, difference, mask)
    staging = Path(tempfile.mkdtemp(prefix="." + args.output.name + "-build-", dir=args.output.parent))
    # mkdtemp uses 0700 regardless of umask; this lab's new outputs must be shared.
    staging.chmod(0o777)
    save_image(staging / "inputs/average.nii.gz", average, reference)
    files, jobs = make_designs(args.output, config, ids, terms)
    files.update({"subjects.tsv": roster.read_text(), "raw_covariates.tsv": review.tsv(raw)})
    for name, text in files.items():
        path = staging / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    paths = set(sidecars + [roster, ROOT / "config/analysis_decisions.json", preview,
                            ROOT / "code/freeze_katie_cohort.py", ROOT / "code/review_katie_models.py", Path(__file__),
                            ROOT / "data/derived/katie-cohort-v1/provenance.json", difference, mask,
                            subset / "plan.json", subset / "artifacts.json", Path(args.randomise)])
    for row in pairs:
        if row["contrast"] == "4":
            paths.update(Path(row[task + "_" + f]) for task in cohort.TASKS for f in ("cope", "varcope", "mask", "dof"))
    # Preserve the authenticated original-input lineage from the subset as well.
    subset_plan = json.loads((subset / "plan.json").read_text())
    paths.update(Path(record["path"]) for record in subset_plan["sources"])
    outputs = {name: cohort.digest(staging / name) for name in files}
    outputs["inputs/average.nii.gz"] = cohort.digest(staging / "inputs/average.nii.gz")
    version_file = Path(os.environ.get("FSLDIR", "/usr/local/fsl")) / "etc/fslversion"
    plan = dict(schema_version=1, config=config, upstream=str(args.upstream), n=97, jobs=jobs,
                images=dict(social_specific=str(difference), average=str(args.output / "inputs/average.nii.gz")),
                mask=str(mask), sources=[fingerprint(p) for p in sorted(paths)], outputs=outputs,
                randomise=os.path.abspath(args.randomise),
                fsl_version=version_file.read_text().strip() if version_file.exists() else "unknown_executable_hash_recorded",
                code_commit=cohort.git_source(ROOT, Path("code/run_katie_randomise.py")))
    write_json(staging / "plan.json", plan)
    (staging / "plan.sha256").write_text(cohort.digest(staging / "plan.json") + "\n")
    if STOP:
        raise InterruptedError("Stopped during build; staging preserved: " + str(staging))
    staging.rename(args.output)
    check(args)


def check(args):
    plan = load_plan(args.output)
    if plan["config"] != approved_config() or plan["upstream"] != str(args.upstream):
        raise ValueError("Frozen configuration/upstream changed")
    for name, digest in plan["outputs"].items():
        if cohort.digest(args.output / name) != digest:
            raise ValueError("Built analysis input/design changed: " + name)
    _, variables = cohort.read_table(ROOT / "data/derived/katie-cohort-v1/analysis_variables.tsv")
    _, pairs = cohort.read_table(ROOT / "data/derived/katie-cohort-v1/selected_pairs.tsv")
    era, _ = live_eras(args.upstream, variables, pairs)
    ids, raw, terms = review.aligned_terms(variables, pairs, era)
    files, jobs = make_designs(args.output, plan["config"], ids, terms)
    if jobs != plan["jobs"] or len(jobs) != 24:
        raise ValueError("Job inventory differs")
    for name, text in files.items():
        if (args.output / name).read_text() != text:
            raise ValueError("Recomputed matrix/contrasts differ")
    if (args.output / "subjects.tsv").read_text() != review.tsv([dict(subject=s) for s in ids]):
        raise ValueError("Frozen volume order differs")
    reference, average = image_arrays(pairs, ids, Path(plan["images"]["social_specific"]), Path(plan["mask"]))
    actual = nib.load(plan["images"]["average"])
    grid(reference, actual, 4)
    if actual.shape != average.shape or not np.array_equal(actual.get_fdata(), average):
        raise ValueError("Average stack arithmetic/order differs")
    verify_sources(plan["sources"])
    print("CHECK PASSED: N=97; difference and average images; common mask; live scanner eras; "
          "12 full-rank designs; 24 cluster-extent jobs; both directions; Z-to-t cutoffs. No exclusions changed.", flush=True)
    return plan


def command(plan, job, prefix, permutations=None):
    return [plan["randomise"], "-i", plan["images"][job["outcome"]], "-o", str(prefix),
            "-d", job["design"], "-t", job["contrast"], "-m", plan["mask"],
            "-c", format(job["t_cutoff"], ".15g"), "-n", str(permutations or job["permutations"]),
            "--seed=" + str(job["seed"])]


def output_images(prefix, mask_path):
    mask = nib.load(mask_path)
    paths = [Path(str(prefix) + suffix) for i in (1, 2) for suffix in
             (f"_tstat{i}.nii.gz", f"_clustere_corrp_tstat{i}.nii.gz")]
    for path in paths:
        image = nib.load(path)
        grid(mask, image)
        data = image.get_fdata()
        if not np.isfinite(data).all():
            raise ValueError("Nonfinite randomise result: " + str(path))
        if "corrp" in path.name and (data.min() < 0 or data.max() > 1):
            raise ValueError("Invalid corrected p-value map")
    return [fingerprint(path) for path in sorted(prefix.parent.glob(prefix.name + "*")) if path.is_file()]


def group_alive(pid):
    try:
        os.killpg(int(pid), 0)
        return True
    except ProcessLookupError:
        return False


def execute(plan, job, folder, plan_hash, smoke=False):
    folder.mkdir(parents=True, exist_ok=True)
    receipt = folder / "success.json"
    if receipt.exists():
        saved = json.loads(receipt.read_text())
        if saved["plan_sha256"] != plan_hash or saved["job"] != job or saved["smoke"] != smoke:
            raise ValueError("Completed job receipt differs")
        verify_sources(saved["outputs"])
        return "REUSED"
    running = folder / "running.json"
    if running.exists() and group_alive(json.loads(running.read_text())["process_group"]):
        raise ValueError("Existing orphan/active randomise group; refusing duplicate: " + job["key"])
    if STOP:
        return "NOT_STARTED"
    attempts = folder / "attempts"
    attempts.mkdir(exist_ok=True)
    index = 1
    while (attempts / f"attempt-{index:04d}").exists():
        index += 1
    destination = attempts / f"attempt-{index:04d}"
    destination.mkdir()
    prefix = destination / "randomise"
    call = command(plan, job, prefix, permutations=2 if smoke else None)
    write_json(destination / "command.json", dict(command=call, job=job, smoke=smoke))
    print(("SMOKE " if smoke else "STARTED ") + job["key"], flush=True)
    with (destination / "console.log").open("w") as log:
        process = subprocess.Popen(call, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                                   pass_fds=() if LEASE_FD is None else (LEASE_FD,))
        write_json(running, dict(process_group=process.pid, command=call))
        try:
            while process.poll() is None:
                if STOP:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    raise RuntimeError("Stopped; completed receipts and partial attempts preserved")
                time.sleep(.25)
        finally:
            if process.poll() is not None:
                running.unlink(missing_ok=True)
    if process.returncode:
        ending = "\n".join((destination / "console.log").read_text(errors="replace").splitlines()[-25:])
        raise RuntimeError(f"randomise exited {process.returncode}; {destination}/console.log\n{ending}")
    products = output_images(prefix, plan["mask"])
    write_json(receipt, dict(plan_sha256=plan_hash, job=job, smoke=smoke, outputs=products,
                            attempt=str(destination), command=call, completed=datetime.now(timezone.utc).isoformat()))
    return "COMPLETED"


def run(args):
    global STOP
    STOP = False
    plan = check(args)
    plan_hash = cohort.digest(args.output / "plan.json")
    status = args.output / "status.json"
    write_json(status, dict(status="smoke_test", n=97, total=24, outcomes={}))
    smoke = execute(plan, plan["jobs"][0], args.output / "smoke", plan_hash, smoke=True)
    if smoke == "NOT_STARTED":
        raise InterruptedError("Stopped before smoke test")
    print("SMOKE PASSED: actual randomise cluster-extent flags and corrected outputs verified (2 permutations only).", flush=True)
    outcomes = {}
    write_json(status, dict(status="running", n=97, total=24, smoke=smoke, outcomes=outcomes))
    print(f"STAGE RANDOMISE: 24 jobs, {args.jobs} workers; 10000 permutations; no TFCE/PALM", flush=True)
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(execute, plan, job, args.output / "jobs" / job["key"], plan_hash): job for job in plan["jobs"]}
        while futures:
            done, _ = wait(futures, timeout=60, return_when=FIRST_COMPLETED)
            if not done:
                print(f"HEARTBEAT finished={len(outcomes)}/24 pending_or_running={len(futures)}", flush=True)
            for future in done:
                job = futures.pop(future)
                try:
                    result = future.result()
                    outcomes[job["key"]] = result
                    print(f"{result} {job['key']} ({len(outcomes)}/24)", flush=True)
                except Exception as exc:
                    outcomes[job["key"]] = "FAILED: " + str(exc)
                    print(outcomes[job["key"]], flush=True)
            write_json(status, dict(status="running", n=97, total=24, outcomes=outcomes))
    failures = [k for k, value in outcomes.items() if value not in ("COMPLETED", "REUSED")]
    verify_sources(plan["sources"])
    write_json(status, dict(status="failed" if failures else "complete", n=97, total=24, outcomes=outcomes))
    if failures:
        raise RuntimeError(f"{len(failures)} job(s) not complete; preserve outputs and resume the same command")
    check_results(args)


def check_results(args):
    plan = load_plan(args.output)
    digest = cohort.digest(args.output / "plan.json")
    rows = []
    for job in plan["jobs"]:
        folder = args.output / "jobs" / job["key"]
        receipt = json.loads((folder / "success.json").read_text())
        if receipt["job"] != job or receipt["plan_sha256"] != digest or receipt["smoke"]:
            raise ValueError("Final result receipt mismatch")
        verify_sources(receipt["outputs"])
        output_images(Path(receipt["attempt"]) / "randomise", plan["mask"])
        rows.append(dict(job=job["key"], n=97, z=job["z"], t_cutoff=job["t_cutoff"],
                         residual_dof=job["residual_dof"], permutations=job["permutations"],
                         seed=job["seed"], output_prefix=receipt["attempt"] + "/randomise"))
    (args.output / "results.tsv").write_text(review.tsv(rows))
    print("CHECK PASSED: all 24 randomise jobs / 48 directional corrected maps verified; N=97; "
          "per-map cluster-FWE only, exploratory across analyses.", flush=True)


def stop(signum, frame):
    global STOP
    STOP = True


def main():
    global LEASE_FD
    os.umask(0)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "check", "run", "check-results"))
    parser.add_argument("--upstream", type=Path, default=Path("/ZPOOL/data/projects/rf1-sra-linux2"))
    parser.add_argument("--output", type=Path, default=ROOT / "derivatives/fsl/randomise/katie-v1")
    parser.add_argument("--randomise", default=shutil.which("randomise") or "/usr/local/fsl/bin/randomise")
    parser.add_argument("--jobs", type=int, default=24)
    args = parser.parse_args()
    args.output, args.upstream = args.output.resolve(), args.upstream.resolve()
    if not 1 <= args.jobs <= 24:
        parser.error("--jobs must be between 1 and 24")
    if not Path(args.randomise).is_file():
        parser.error("randomise executable not found: " + args.randomise)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with (args.output.parent / ("." + args.output.name + ".lock")).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        LEASE_FD = lock.fileno()
        {"build": build, "check": check, "run": run, "check-results": check_results}[args.command](args)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAILED ({type(exc).__name__}): {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
