#!/usr/bin/env python3
"""Run isolated, separate FEVS/OAFEM associations on frozen N=97 image bundles."""
from __future__ import annotations

import argparse
import csv
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import fcntl
import io
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
from types import SimpleNamespace

import nibabel as nib
import numpy as np
from scipy.stats import norm, t

import review_financial_models as financial
import run_katie_randomise as base
import summarize_katie_randomise as summary

ROOT = Path(__file__).resolve().parents[1]


def checked_image_plan(folder):
    plan = base.load_plan(folder)
    for name, digest in plan["outputs"].items():
        if base.cohort.digest(folder / name) != digest:
            raise ValueError("Frozen image-family artifact changed: " + str(folder / name))
    _, roster = base.cohort.read_table(folder / "subjects.tsv")
    _, expected = base.cohort.read_table(ROOT / "data/derived/katie-cohort-v1/subjects.tsv")
    if plan["n"] != 97 or roster != expected:
        raise ValueError("Image-family volume order differs from the frozen 97-person roster")
    mask = nib.load(plan["mask"])
    for outcome in ("social_specific", "average"):
        image = nib.load(plan["images"][outcome])
        base.grid(mask, image, 4)
        if image.shape[3] != 97:
            raise ValueError("Image stack does not contain exactly 97 participants")
    return plan


def frozen_previews():
    folder = ROOT / "data/derived/financial-model-review-v1"
    provenance = json.loads((folder / "provenance.json").read_text())
    files = {}
    for name, digest in provenance["outputs"].items():
        if base.cohort.digest(folder / name) != digest:
            raise ValueError("Frozen financial preview changed: " + name)
        files[name] = (folder / name).read_text()
    for source in provenance["sources"]:
        if base.cohort.digest(ROOT / source["path"]) != source["sha256"]:
            raise ValueError("Frozen financial preview source changed: " + source["path"])
    catalog = json.loads(files["model_catalog.json"])
    _, roster = base.cohort.read_table(ROOT / "data/derived/katie-cohort-v1/subjects.tsv")
    ids = [row["subject"] for row in roster]
    scores, _ = financial.read_scores(financial.SCORES, ids)
    return files, catalog, ids, scores


def specifications(output, families, references):
    # Authenticate the saved review rather than requiring different BLAS builds
    # to reproduce diagnostic VIF/QR decimals byte-for-byte. Independently check
    # execution rows and use the actual baseline nuisance columns.
    files, catalog, ids, scores = frozen_previews()
    designs, jobs = {}, []
    for score in ("fevs", "oafem"):
        for outcome in ("social_specific", "average"):
            relative = Path("designs") / outcome / score
            text = files[f"previews/{outcome}/{score}/design.tsv"]
            rows = list(csv.DictReader(io.StringIO(text), delimiter="\t"))
            names = list(rows[0])[1:]
            x = np.array([[float(row[name]) for name in names] for row in rows])
            expected_names = ["ones", *base.review.QC_OPTIONS["signed_differences" if outcome == "social_specific" else "pair_means"],
                              "e11", "xa30", "gender_code1", "age", score]
            reference = np.loadtxt(io.StringIO(Path(references[outcome]).read_text().split("/Matrix", 1)[1]), ndmin=2)
            centered_score = base.review.center([row[score] for row in scores])
            if ([row["subject"] for row in rows] != ids or names != expected_names or x.shape != (97, 8)
                    or reference.shape[0] != 97 or reference.shape[1] < 7
                    or not np.allclose(x[:, :7], reference[:, :7], rtol=0, atol=1e-12)
                    or not np.allclose(x[:, -1], centered_score, rtol=0, atol=1e-12)):
                raise ValueError("Financial preview rows, source scores or nuisance covariates differ")
            x = np.column_stack([reference[:, :7], centered_score])
            if not np.isfinite(x).all() or np.linalg.matrix_rank(x) != 8:
                raise ValueError("Unexpected financial predictor design")
            designs[str(relative / "design.tsv")] = base.review.tsv([dict(subject=sub, **dict(zip(names, row))) for sub, row in zip(ids, x)])
            designs[str(relative / "design.mat")] = base.vest_matrix(x)
            designs[str(relative / "design.con")] = base.vest_contrasts(names, score)
            for family in families:
                for z in (2.6, 3.1):
                    cutoff = float(t.isf(norm.sf(z), 89))
                    pinned = base.approved_config()["inference"]["verified_t_thresholds"]["89"][str(z)]
                    if not np.isclose(cutoff, pinned, rtol=0, atol=1e-10):
                        raise ValueError("Model-specific CDT conversion changed")
                    jobs.append(dict(key=f"{family}/{outcome}/{score}/z-" + str(z).replace(".", "p"),
                        family=family, outcome=family + "/" + outcome, model=score,
                        role="lead_financial_score" if score == "fevs" else "secondary_financial_score",
                        z=z, t_cutoff=cutoff, residual_dof=89, permutations=10000, seed=20261101,
                        design=str(output / relative / "design.mat"), contrast=str(output / relative / "design.con")))
    return designs, jobs, catalog


def build(args):
    if (args.output / "plan.json").exists():
        return check(args)
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Unrecognized nonempty financial output; refusing overwrite")
    baseline = base.check(SimpleNamespace(output=args.baseline, upstream=args.upstream))
    family_plans = {"activation": baseline}
    if "connectivity" in args.families:
        family_plans["connectivity"] = checked_image_plan(args.connectivity)
    # The image-family row order and first seven columns must match, not just N.
    references = {outcome: next(j["design"] for j in baseline["jobs"] if j["outcome"] == outcome and j["model"] == "adi")
                  for outcome in ("social_specific", "average")}
    designs, jobs, catalog = specifications(args.output, args.families, references)
    for job in jobs:
        source = next(j for j in family_plans[job["family"]]["jobs"]
                      if j["outcome"] == job["outcome"].split("/", 1)[1] and j["model"] == "adi")
        source_x = np.loadtxt(io.StringIO(Path(source["design"]).read_text().split("/Matrix", 1)[1]), ndmin=2)
        new_x = np.loadtxt(io.StringIO(designs[str(Path(job["design"]).relative_to(args.output))].split("/Matrix", 1)[1]), ndmin=2)
        if not np.allclose(source_x[:, :7], new_x[:, :7], rtol=0, atol=1e-12):
            raise ValueError("Live image-family covariate rows differ from the reviewed financial model")
    staging = Path(tempfile.mkdtemp(prefix=".financial-build-", dir=args.output.parent)); staging.chmod(0o777)
    for name, text in designs.items():
        path = staging / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
    (staging / "subjects.tsv").write_text((ROOT / "data/derived/katie-cohort-v1/subjects.tsv").read_text())
    images, masks, sources = {}, {}, []
    for family in args.families:
        folder = args.baseline if family == "activation" else args.connectivity
        plan = family_plans[family]
        sources += plan["sources"] + [base.fingerprint(folder / name) for name in plan["outputs"]]
        sources.append(base.fingerprint(folder / "plan.json"))
        masks[family] = plan["mask"]
        images.update({family + "/" + outcome: plan["images"][outcome] for outcome in ("social_specific", "average")})
    paths = [Path(__file__), Path(financial.__file__), financial.SCORES,
             ROOT / "data/derived/financial-model-review-v1/provenance.json",
             ROOT / "data/derived/katie-cohort-v1/subjects.tsv"]
    sources += [base.fingerprint(path) for path in paths]
    plan = dict(n=97, families=args.families, jobs=jobs, images=images, masks=masks, sources=sources,
                randomise=baseline["randomise"], code_sha256=base.cohort.digest(Path(__file__)),
                release_root=str(ROOT), financial_catalog=catalog, reference_designs=references, interactions=False,
                original_exclusions_changed=False, original_jobs_changed=False,
                outputs={str(path.relative_to(staging)): base.cohort.digest(path) for path in staging.rglob("*") if path.is_file()})
    base.write_json(staging / "plan.json", plan)
    (staging / "plan.sha256").write_text(base.cohort.digest(staging / "plan.json") + "\n")
    if base.STOP: raise InterruptedError("Stopped; financial staging preserved")
    staging.rename(args.output)
    return check(args)


def check(args):
    plan = base.load_plan(args.output)
    if plan["code_sha256"] != base.cohort.digest(Path(__file__)) or plan["families"] != args.families:
        raise ValueError("Frozen financial code/specification changed; use the recorded release to resume")
    designs, jobs, _ = specifications(args.output, args.families, plan["reference_designs"])
    if jobs != plan["jobs"] or plan["n"] != 97 or plan["interactions"]:
        raise ValueError("Frozen financial job inventory changed")
    for name, text in designs.items():
        if (args.output / name).read_text() != text:
            raise ValueError("Financial design/contrast changed")
    for name, digest in plan["outputs"].items():
        if base.cohort.digest(args.output / name) != digest:
            raise ValueError("Financial artifact changed: " + name)
    print(f"CHECK PASSED: N=97; separate FEVS and secondary OAFEM; no interactions; {len(jobs)} jobs; matched image/covariate order.", flush=True)
    return plan


def execute(plan, job, folder, digest, smoke=False):
    view = dict(plan, mask=plan["masks"][job["family"]])
    return base.execute(view, job, folder, digest, smoke=smoke)


def results(args, plan):
    maps, clusters, receipts = [], [], []
    digest = base.cohort.digest(args.output / "plan.json")
    for job in plan["jobs"]:
        path = args.output / "jobs" / job["key"] / "success.json"
        saved = json.loads(path.read_text())
        if saved["job"] != job or saved["plan_sha256"] != digest or saved["smoke"]:
            raise ValueError("Financial result receipt differs")
        base.verify_sources(saved["outputs"])
        prefix = Path(saved["attempt"]) / "randomise"
        if base.output_images(prefix, plan["masks"][job["family"]]) != saved["outputs"]:
            raise ValueError("Financial result inventory changed")
        receipts.append(base.fingerprint(path))
        mask = nib.load(plan["masks"][job["family"]])
        for index, direction in ((1, "positive"), (2, "negative")):
            row, found = summary.map_summary(job, direction, nib.load(str(prefix) + f"_tstat{index}.nii.gz"),
                nib.load(str(prefix) + f"_clustere_corrp_tstat{index}.nii.gz"), mask)
            maps.append(dict(row, family=job["family"], role=job["role"]))
            clusters.extend(dict(r, family=job["family"], role=job["role"]) for r in found)
    files = {"maps.tsv": base.review.tsv(maps), "clusters.tsv": base.review.tsv(clusters, summary.CLUSTER_FIELDS + ["family", "role"]),
             "provenance.json": base.cohort.json_text(dict(n=97, jobs=len(plan["jobs"]), maps=len(maps),
                plan_sha256=digest, receipts=receipts, cross_analysis_correction="none; exploratory per-map FWE",
                interactions=False, original_jobs_or_exclusions_changed=False)),
             "README.md": f"# Katie Financial Associations: N=97\n\n{len(plan['jobs'])} jobs / {len(maps)} maps verified. "
                "Separate FEVS (lead financial score) and OAFEM (secondary) models; no interactions. "
                "Both outcomes, directions and CDTs are reported in maps.tsv, including nulls. "
                "Cluster-FWE p<0.05 per map; no additional correction across the exploratory family. "
                "Original results, cohort and exclusions unchanged.\n"}
    for name, text in files.items():
        path = args.report / name
        if path.exists() and path.read_text() != text:
            raise ValueError("Existing financial report differs; preserve it and choose another --report")
    args.report.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        path = args.report / name
        if not path.exists(): path.write_text(text)
    for row in maps:
        print(f"RESULT {row['job']} {row['direction']}: min cluster-FWE p={row['min_cluster_fwe_p']:.4f}; voxels={row['significant_voxels']}", flush=True)
    print(f"CHECK PASSED: all {len(plan['jobs'])} financial jobs verified; N=97; no interactions or new exclusions.", flush=True)


def run(args):
    plan = build(args)
    if args.prepare_only: return
    digest = base.cohort.digest(args.output / "plan.json")
    for family in args.families:
        job = next(j for j in plan["jobs"] if j["family"] == family and j["model"] == "fevs")
        if execute(plan, job, args.output / "smoke" / family, digest, smoke=True) == "NOT_STARTED":
            raise InterruptedError("Stopped before smoke test")
    print("SMOKE PASSED: FEVS/OAFEM input families; full financial jobs starting.", flush=True)
    outcomes, failures = {}, {}
    with ThreadPoolExecutor(max_workers=min(args.jobs, len(plan["jobs"]))) as pool:
        futures = {pool.submit(execute, plan, job, args.output / "jobs" / job["key"], digest): job for job in plan["jobs"]}
        while futures:
            done, _ = wait(futures, timeout=60, return_when=FIRST_COMPLETED)
            if not done: print(f"HEARTBEAT financial finished={len(outcomes)}/{len(plan['jobs'])}", flush=True)
            for future in done:
                job = futures.pop(future)
                try:
                    result = future.result()
                    if result == "NOT_STARTED": raise InterruptedError("Stopped")
                    outcomes[job["key"]] = result
                except Exception as exc:
                    failures[job["key"]] = str(exc); outcomes[job["key"]] = "FAILED"
                print(f"{outcomes[job['key']]} {job['key']} ({len(outcomes)}/{len(plan['jobs'])})", flush=True)
            base.write_json(args.output / "status.json", dict(status="running", n=97, total=len(plan["jobs"]), outcomes=outcomes, failures=failures))
    if not failures and not base.STOP:
        try: results(args, plan)
        except Exception as exc: failures["verification"] = str(exc)
    try: base.verify_sources(plan["sources"])
    except Exception as exc: failures["source_checks"] = str(exc)
    base.write_json(args.output / "status.json", dict(status="failed" if failures or base.STOP else "complete", n=97,
                    total=len(plan["jobs"]), outcomes=outcomes, failures=failures))
    if failures or base.STOP: raise RuntimeError("Financial batch incomplete; outputs preserved; resume the same frozen release")


def wait_shared(path):
    lock = path.open("a")
    try:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
                return lock
            except BlockingIOError:
                print("WAITING: existing Katie batch still holds " + path.name + "; no process interrupted.", flush=True)
                if base.STOP: raise InterruptedError("Stopped while waiting")
                time.sleep(15)
    except BaseException:
        lock.close()
        raise


def main():
    os.umask(0)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True, help="Canonical SD checkout, separate from the frozen code release")
    parser.add_argument("--families", default="activation,connectivity")
    parser.add_argument("--jobs", type=int, default=16)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    args.project = args.project.resolve()
    args.families = args.families.split(",")
    if args.families not in (["activation"], ["activation", "connectivity"]): parser.error("Use activation or activation,connectivity")
    if not 1 <= args.jobs <= 16: parser.error("--jobs must be 1..16 (16 total jobs with both image families)")
    args.baseline = args.project / "derivatives/fsl/randomise/katie-v1"
    args.connectivity = args.project / "derivatives/fsl/randomise/katie-remaining-v1/connectivity"
    args.output = args.project / "derivatives/fsl/randomise/katie-financial-v1"
    args.report = args.project / "results/randomise/katie-financial-v1"
    args.upstream = Path("/ZPOOL/data/projects/rf1-sra-linux2").resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGTERM, base.stop); signal.signal(signal.SIGINT, base.stop)
    locks = []
    try:
        own = (args.output.parent / ".katie-financial-v1.lock").open("a")
        fcntl.flock(own, fcntl.LOCK_EX | fcntl.LOCK_NB); locks.append(own)
        for name in (".katie-remaining-v1.lock", ".katie-v1.lock"):
            locks.append(wait_shared(args.output.parent / name))
        # Children retain the shared remaining-batch lease even after coordinator death.
        base.LEASE_FD = locks[1].fileno()
        run(args)
    finally:
        for lock in reversed(locks): lock.close()


if __name__ == "__main__":
    try: main()
    except Exception as exc:
        print(f"FAILED ({type(exc).__name__}): {exc}", file=sys.stderr, flush=True); sys.exit(1)
