#!/usr/bin/env python3
"""Isolated N=97 additive PM2.5/Ecog tests of social-minus-nonsocial components."""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import fcntl
import io
import json
import os
from pathlib import Path
import signal
import tempfile
from types import SimpleNamespace

import nibabel as nib
import numpy as np
from scipy.stats import norm, t

import audit_katie_outcome as outcome_audit
import run_katie_randomise as base
import summarize_katie_randomise as summary

ROOT = Path(__file__).resolve().parents[1]
OUTCOMES = ("win_only", "loss_only", "social_specific")
MODEL = "pm25_ecog_additive"


def matrix(path):
    return np.loadtxt(io.StringIO(Path(path).read_text().split("/Matrix", 1)[1]), ndmin=2)


def additive_design(baseline, ids):
    reference = Path(next(j["design"] for j in baseline["jobs"]
                          if j["outcome"] == "social_specific" and j["model"] == "pm25xecog"))
    fields, rows = base.cohort.read_table(reference.with_suffix(".tsv"))
    expected = ["ones", "delta_fd", "delta_tsnr", "e11", "xa30", "gender_code1", "age", "pm25", "ecog", "pm25xecog"]
    original = matrix(reference)
    if (fields != ["subject", *expected] or [r["subject"] for r in rows] != ids
            or original.shape != (97, 10)):
        raise ValueError("Baseline interaction design has unexpected columns or participant order")
    from_table = np.array([[float(r[n]) for n in expected] for r in rows])
    if not np.allclose(original, from_table, rtol=0, atol=1e-12):
        raise ValueError("Baseline numeric matrix disagrees with its labeled rows")
    if not np.allclose(original[:, -1], original[:, 7] * original[:, 8], rtol=0, atol=1e-12):
        raise ValueError("Unexpected original interaction column")
    x = original[:, :9].copy()
    if not np.isfinite(x).all() or np.linalg.matrix_rank(x) != 9:
        raise ValueError("Additive design must be finite and full rank: 97 rows / 9 columns")
    return expected[:9], x, reference


def designs(output, ids, names, x):
    files = {"subjects.tsv": base.review.tsv([dict(subject=s) for s in ids]),
             "design.tsv": base.review.tsv([dict(subject=s, **dict(zip(names, row))) for s, row in zip(ids, x)]),
             "design.mat": base.vest_matrix(x), "design.con": base.vest_contrasts(names, "pm25")}
    dof = len(ids) - int(np.linalg.matrix_rank(x))
    if dof != 88:
        raise ValueError("Unexpected residual degrees of freedom")
    jobs = []
    for name in OUTCOMES:
        for z in (2.6, 3.1):
            jobs.append(dict(key=f"{name}/{MODEL}/z-" + str(z).replace(".", "p"),
                outcome=name, model=MODEL, z=z, t_cutoff=float(t.isf(norm.sf(z), dof)),
                residual_dof=dof, permutations=10000, seed=20261101,
                design=str(output / "design.mat"), contrast=str(output / "design.con")))
    return files, jobs


def validate_contrasts(feat):
    settings = outcome_audit.settings(feat / "design.fsf")
    actual = matrix(feat / "design.con")
    if actual.shape[0] != 4 or actual.shape[1] < 4 or not np.isfinite(actual).all():
        raise ValueError("Unexpected actual L1 contrast matrix")
    for index, name, weights in ((1, "win", [1, 0, 0, 0]), (2, "loss", [0, 1, 0, 0]),
                                  (4, "win-loss", [1, -1, 0, 0])):
        expected = np.zeros(actual.shape[1]); expected[:4] = weights
        if settings.get(f"conname_real.{index}") != name or not np.array_equal(actual[index-1], expected):
            raise ValueError(f"Actual COPE {index} does not represent {name}; nuisance weights must be zero")


def component_arrays(pairs, ids, reference, existing_difference):
    lookup = base.cohort.unique(pairs, ("subject", "contrast"))
    support = reference.get_fdata() > 0
    source_stack = nib.load(existing_difference); base.grid(reference, source_stack, 4)
    if source_stack.shape[3] != 97:
        raise ValueError("Existing valence-difference stack has wrong N")
    result = {name: np.zeros(reference.shape + (97,), dtype=np.float32) for name in OUTCOMES[:2]}
    evidence, lineage = set(), []
    for index, subject in enumerate(ids):
        values = {}
        for task in ("socialdoors", "doors"):
            values[task] = {}
            pair = lookup[(subject, "4")]
            feat = Path(pair[task + "_feat_dir"])
            validate_contrasts(feat)
            evidence.update((feat / "design.fsf", feat / "design.con"))
            for cope in (1, 2, 4):
                row = lookup[(subject, str(cope))]
                path = Path(row[task + "_cope"])
                if path.resolve() != (feat / f"stats/cope{cope}.nii.gz").resolve() or row[task + "_feat_dir"] != str(feat):
                    raise ValueError("Component source is not this participant/task's validated activation L1")
                image = nib.load(path); base.grid(reference, image)
                data = image.get_fdata()[support]
                if not np.isfinite(data).all():
                    raise ValueError("Nonfinite component COPE; no participant may be dropped")
                values[task][cope] = data
                evidence.add(path)
                lineage.append(dict(volume=index, subject=subject, task=task, cope=cope, source=str(path)))
            # Float32 COPE arithmetic can differ by rounding, but not by a task/contrast substitution.
            a, b, c = (values[task][n] for n in (1, 2, 4))
            tolerance = 8*np.finfo(np.float32).eps*(np.abs(a)+np.abs(b)+np.abs(c)+1)
            if np.any(np.abs((a-b)-c) > tolerance):
                raise ValueError("L1 win-minus-loss does not agree with its win/loss components")
        for name, cope in (("win_only", 1), ("loss_only", 2)):
            result[name][..., index][support] = values["socialdoors"][cope] - values["doors"][cope]
        expected = (values["socialdoors"][4] - values["doors"][4]).astype(np.float32)
        actual = np.asarray(source_stack.dataobj[..., index], dtype=np.float32)
        if not np.array_equal(actual[support], expected) or np.any(actual[~support] != 0):
            raise ValueError("Existing difference stack has wrong participant order, direction or pixels")
    return result, evidence, lineage


def build(args):
    if (args.output / "plan.json").exists():
        return check(args)
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Preserve unrecognized existing outputs; refusing overwrite")
    baseline = base.check(SimpleNamespace(output=args.baseline, upstream=args.upstream))
    _, timing = outcome_audit.audit(args.baseline)
    if timing["failures"] or timing["n"] != 97 or timing["runs"] != 194:
        raise ValueError("The existing win/loss event-timing audit did not pass for all 194 runs")
    _, roster = base.cohort.read_table(ROOT / "data/derived/katie-cohort-v1/subjects.tsv")
    ids = [r["subject"] for r in roster]
    names, x, reference_design = additive_design(baseline, ids)
    files, jobs = designs(args.output, ids, names, x)
    _, pairs = base.cohort.read_table(ROOT / "data/derived/katie-cohort-v1/selected_pairs.tsv")
    mask = nib.load(baseline["mask"])
    arrays, evidence, lineage = component_arrays(pairs, ids, mask, baseline["images"]["social_specific"])
    staging = Path(tempfile.mkdtemp(prefix=".pm25-components-", dir=args.output.parent)); staging.chmod(0o777)
    for name, text in files.items():
        (staging / name).write_text(text)
    (staging / "source_order.tsv").write_text(base.review.tsv(lineage))
    for name, array in arrays.items():
        base.save_image(staging / f"inputs/{name}.nii.gz", array, mask)
    evidence.update((Path(__file__), Path(base.__file__), Path(outcome_audit.__file__),
        Path(base.review.__file__), Path(base.cohort.__file__), args.baseline / "plan.json", reference_design,
        reference_design.with_suffix(".tsv"), ROOT / "data/derived/katie-cohort-v1/selected_pairs.tsv",
        ROOT / "data/derived/katie-cohort-v1/subjects.tsv"))
    sources = {r["path"]: r for r in baseline["sources"]}
    for path in evidence:
        r = base.fingerprint(path); sources[r["path"]] = r
    for name in baseline["outputs"]:
        r = base.fingerprint(args.baseline / name); sources[r["path"]] = r
    plan = dict(n=97, jobs=jobs, model=MODEL, columns=names, tested_term="pm25", interactions=False,
        mask=baseline["mask"], randomise=baseline["randomise"], baseline=str(args.baseline), upstream=str(args.upstream),
        reference_design=str(reference_design), code_sha256=base.cohort.digest(Path(__file__)),
        images=dict(win_only=str(args.output / "inputs/win_only.nii.gz"),
                    loss_only=str(args.output / "inputs/loss_only.nii.gz"), social_specific=baseline["images"]["social_specific"]),
        sources=list(sources.values()), original_exclusions_changed=False, existing_results_changed=False,
        outputs={str(p.relative_to(staging)): base.cohort.digest(p) for p in staging.rglob("*") if p.is_file()})
    base.write_json(staging / "plan.json", plan)
    (staging / "plan.sha256").write_text(base.cohort.digest(staging / "plan.json")+"\n")
    if base.STOP:
        raise InterruptedError("Stopped; staging and completed analyses preserved")
    staging.rename(args.output)
    return check(args)


def check(args):
    plan = base.load_plan(args.output)
    if (plan["code_sha256"] != base.cohort.digest(Path(__file__)) or plan["baseline"] != str(args.baseline)
            or plan["upstream"] != str(args.upstream) or plan["n"] != 97 or plan["interactions"]):
        raise ValueError("Frozen component plan differs; resume with its recorded code")
    _, roster = base.cohort.read_table(ROOT / "data/derived/katie-cohort-v1/subjects.tsv")
    ids = [r["subject"] for r in roster]
    baseline = json.loads((args.baseline / "plan.json").read_text())
    names, x, _ = additive_design(baseline, ids)
    files, jobs = designs(args.output, ids, names, x)
    if jobs != plan["jobs"] or names != plan["columns"] or len(jobs) != 6:
        raise ValueError("Frozen design or job inventory differs")
    for name, text in files.items():
        if (args.output / name).read_text() != text:
            raise ValueError("Image/design row labels, matrix or PM contrasts changed")
    for name, digest in plan["outputs"].items():
        if base.cohort.digest(args.output / name) != digest:
            raise ValueError("Frozen component input changed: " + name)
    reference = nib.load(plan["mask"])
    for path in plan["images"].values():
        image = nib.load(path); base.grid(reference, image, 4)
        if image.shape[3] != 97:
            raise ValueError("Wrong participant count")
    print("CHECK PASSED: N=97; exact COPE1/2 source order; social-minus-nonsocial win/loss and original valence difference; "
          "same nine-column additive PM2.5/Ecog design; df=88; six jobs, both directions; no exclusions changed.", flush=True)
    return plan


def results(args, plan):
    digest = base.cohort.digest(args.output / "plan.json")
    maps, clusters = [], []
    for job in plan["jobs"]:
        saved = json.loads((args.output / "jobs" / job["key"] / "success.json").read_text())
        prefix = Path(saved["attempt"]) / "randomise"
        if (saved["plan_sha256"] != digest or saved["job"] != job or saved["smoke"]
                or saved["command"] != base.command(plan, job, prefix)):
            raise ValueError("Completed native randomise command/receipt differs")
        base.verify_sources(saved["outputs"])
        if base.output_images(prefix, plan["mask"]) != saved["outputs"]:
            raise ValueError("Native randomise product inventory differs")
        for index, direction in ((1, "positive"), (2, "negative")):
            row, found = summary.map_summary(job, direction, nib.load(str(prefix)+f"_tstat{index}.nii.gz"),
                nib.load(str(prefix)+f"_clustere_corrp_tstat{index}.nii.gz"), nib.load(plan["mask"]))
            maps.append(row); clusters.extend(found)
            print(f"RESULT {job['outcome']} CDT={job['z']} PM2.5={direction} "
                  f"min_cluster_FWE_p={row['min_cluster_fwe_p']:.6g} voxels={row['significant_voxels']}", flush=True)
    (args.output / "maps.tsv").write_text(base.review.tsv(maps))
    (args.output / "clusters.tsv").write_text(base.review.tsv(clusters, summary.CLUSTER_FIELDS))
    base.verify_sources(plan["sources"])
    print("CHECK PASSED: all six jobs / 12 directional maps complete; original data, prior results and exclusions unchanged. "
          "Per-map cluster-FWE only; components and CDTs are related exploratory tests.", flush=True)


def run(args):
    plan = build(args)
    digest = base.cohort.digest(args.output / "plan.json")
    smoke = base.execute(plan, plan["jobs"][0], args.output / "smoke", digest, smoke=True)
    if smoke == "NOT_STARTED":
        raise InterruptedError("Stopped before native smoke test")
    outcomes = {}
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(base.execute, plan, job, args.output / "jobs" / job["key"], digest): job for job in plan["jobs"]}
        while futures:
            done, _ = wait(futures, timeout=60, return_when=FIRST_COMPLETED)
            if not done:
                print(f"HEARTBEAT finished={len(outcomes)}/6 pending_or_running={len(futures)}", flush=True)
            for future in done:
                job = futures.pop(future)
                try:
                    outcomes[job["key"]] = future.result()
                except Exception as exc:
                    outcomes[job["key"]] = "FAILED: " + str(exc)
                print(outcomes[job["key"]] + " " + job["key"], flush=True)
            base.write_json(args.output / "status.json", dict(status="running", total=6, outcomes=outcomes))
    failed = [k for k, v in outcomes.items() if v not in ("COMPLETED", "REUSED")]
    if failed:
        base.write_json(args.output / "status.json", dict(status="failed", total=6, outcomes=outcomes))
        raise RuntimeError("Incomplete jobs; completed receipts preserved. Resume the same command: " + ", ".join(failed))
    results(args, plan)
    base.write_json(args.output / "status.json", dict(status="complete", validated=True, total=6, outcomes=outcomes))


def main():
    os.umask(0)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "check", "check-results"))
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--upstream", type=Path, default=Path("/ZPOOL/data/projects/rf1-sra-linux2"))
    parser.add_argument("--jobs", type=int, default=6)
    args = parser.parse_args()
    args.project, args.upstream = args.project.resolve(), args.upstream.resolve()
    args.baseline = args.project / "derivatives/fsl/randomise/katie-v1"
    args.output = args.project / "derivatives/fsl/randomise/katie-pm25-components-v1"
    if not 1 <= args.jobs <= 6:
        parser.error("Use --jobs 1..6: this batch has six independent randomise jobs")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGTERM, base.stop); signal.signal(signal.SIGINT, base.stop)
    with (args.output.parent / ".katie-pm25-components-v1.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        base.LEASE_FD = lock.fileno()
        if args.command == "run":
            run(args)
        else:
            plan = check(args)
            if args.command == "check-results":
                results(args, plan)


if __name__ == "__main__":
    main()
