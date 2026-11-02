#!/usr/bin/env python3
"""Isolated two-way financial-score moderation; frozen N=97, no three-way terms."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import fcntl
import io
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
from types import SimpleNamespace

import nibabel as nib
import numpy as np
from scipy.stats import norm, t

import run_financial_models as predictor

base = predictor.base
ROOT = Path(__file__).resolve().parents[1]
MODERATORS = ("mspss", "adi", "pm25", "ecog")


def specifications(output, references, families):
    _, _, ids, scores = predictor.frozen_previews()
    folder = ROOT / "data/derived/model-review-v1"
    for name, digest in json.loads((folder / "provenance.json").read_text())["outputs"].items():
        if base.cohort.digest(folder / name) != digest:
            raise ValueError("Original model preview changed: " + name)
    _, raw = base.cohort.read_table(folder / "aligned_raw_terms.tsv")
    if [r["subject"] for r in raw] != ids:
        raise ValueError("Moderator rows differ from the frozen roster")
    # Reuse the predictor's independent check against the live seven nuisance columns.
    predictor.specifications(output, families, references)
    files, jobs, diagnostics = {}, [], []
    for outcome in ("social_specific", "average"):
        reference = np.loadtxt(io.StringIO(Path(references[outcome]).read_text().split("/Matrix", 1)[1]), ndmin=2)
        qc = base.review.QC_OPTIONS["signed_differences" if outcome == "social_specific" else "pair_means"]
        for score in ("fevs", "oafem"):
            a = base.review.center([r[score] for r in scores])
            for moderator in MODERATORS:
                b = base.review.center([float(r[moderator]) for r in raw])
                interaction = score + "x" + moderator
                names = ["ones", *qc, "e11", "xa30", "gender_code1", "age", score, moderator, interaction]
                x = np.column_stack([reference[:, :7], a, b, a * b])
                if x.shape != (97, 10) or not np.isfinite(x).all() or np.linalg.matrix_rank(x) != 10:
                    raise ValueError("Moderation design must be finite, full rank, 97 by 10")
                standardized = (x[:, 1:] - x[:, 1:].mean(axis=0)) / x[:, 1:].std(axis=0, ddof=1)
                vif = np.diag(np.linalg.inv(np.corrcoef(standardized, rowvar=False)))
                q, _ = np.linalg.qr(x, mode="reduced")
                diagnostics.append(dict(outcome=outcome, model=interaction, n=97, rank=10, residual_dof=87,
                    max_vif=float(vif.max()), interaction_vif=float(vif[-1]), max_leverage=float((q*q).sum(axis=1).max()),
                    exclusions_made=False))
                relative = Path("designs") / outcome / interaction
                files[str(relative / "design.tsv")] = base.review.tsv([dict(subject=s, **dict(zip(names, row))) for s, row in zip(ids, x)])
                files[str(relative / "design.mat")] = base.vest_matrix(x)
                files[str(relative / "design.con")] = base.vest_contrasts(names, interaction)
                for family in families:
                    for z in (2.6, 3.1):
                        cutoff = float(t.isf(norm.sf(z), 87))
                        if not np.isclose(cutoff, base.approved_config()["inference"]["verified_t_thresholds"]["87"][str(z)], rtol=0, atol=1e-10):
                            raise ValueError("Model-specific CDT conversion changed")
                        jobs.append(dict(key=f"{family}/{outcome}/{interaction}/z-" + str(z).replace(".", "p"),
                            family=family, outcome=family + "/" + outcome, model=interaction, moderator=moderator,
                            role="lead_financial_score" if score == "fevs" else "secondary_financial_score",
                            z=z, t_cutoff=cutoff, residual_dof=87, permutations=10000, seed=20261101,
                            design=str(output / relative / "design.mat"), contrast=str(output / relative / "design.con")))
    files["design_diagnostics.json"] = base.cohort.json_text(diagnostics)
    return files, jobs


def check(args):
    plan = base.load_plan(args.output)
    if plan["code_sha256"] != base.cohort.digest(Path(__file__)) or plan["release_root"] != str(ROOT):
        raise ValueError("Resume moderation with its recorded frozen code release")
    files, jobs = specifications(args.output, plan["reference_designs"], plan["families"])
    if jobs != plan["jobs"] or plan["n"] != 97 or plan["interaction_order"] != 2:
        raise ValueError("Frozen moderation specification changed")
    for name, text in files.items():
        if (args.output / name).read_text() != text:
            raise ValueError("Moderation design changed: " + name)
    for name, digest in plan["outputs"].items():
        if base.cohort.digest(args.output / name) != digest:
            raise ValueError("Moderation artifact changed: " + name)
    print(f"CHECK PASSED: N=97; {len(jobs)} two-way moderation jobs; both main effects; no three-way terms or exclusions.", flush=True)
    return plan


def build(args):
    if (args.output / "plan.json").exists():
        return check(args)
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Nonempty unrecognized moderation output; refusing overwrite")
    baseline = base.check(SimpleNamespace(output=args.baseline, upstream=args.upstream))
    plans = {"activation": predictor.checked_image_plan(args.baseline),
             "connectivity": predictor.checked_image_plan(args.connectivity)}
    references = {o: next(j["design"] for j in baseline["jobs"] if j["outcome"] == o and j["model"] == "adi")
                  for o in ("social_specific", "average")}
    files, jobs = specifications(args.output, references, list(plans))
    for family, plan in plans.items():
        for outcome in references:
            job = next(j for j in plan["jobs"] if j["outcome"] == outcome and j["model"] == "adi")
            actual = np.loadtxt(io.StringIO(Path(job["design"]).read_text().split("/Matrix", 1)[1]), ndmin=2)
            expected = np.loadtxt(io.StringIO(Path(references[outcome]).read_text().split("/Matrix", 1)[1]), ndmin=2)
            if not np.allclose(actual[:, :7], expected[:, :7], rtol=0, atol=1e-12):
                raise ValueError("Image-family covariate row mismatch: " + family)
    staging = Path(tempfile.mkdtemp(prefix=".financial-moderation-", dir=args.output.parent)); staging.chmod(0o777)
    for name, text in files.items():
        path = staging / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
    (staging / "subjects.tsv").write_text((ROOT / "data/derived/katie-cohort-v1/subjects.tsv").read_text())
    sources, images, masks = [], {}, {}
    for family, plan in plans.items():
        folder = args.baseline if family == "activation" else args.connectivity
        sources += plan["sources"] + [base.fingerprint(folder / n) for n in [*plan["outputs"], "plan.json"]]
        masks[family] = plan["mask"]
        images.update({family + "/" + o: plan["images"][o] for o in references})
    sources += [base.fingerprint(p) for p in [Path(__file__), Path(predictor.__file__), Path(predictor.financial.__file__),
        predictor.financial.SCORES, ROOT / "data/derived/financial-model-review-v1/provenance.json",
        ROOT / "data/derived/model-review-v1/provenance.json", ROOT / "data/derived/model-review-v1/aligned_raw_terms.tsv"]]
    plan = dict(n=97, jobs=jobs, families=list(plans), images=images, masks=masks, sources=sources,
        randomise=baseline["randomise"], reference_designs=references, code_sha256=base.cohort.digest(Path(__file__)),
        release_root=str(ROOT), interaction_order=2, original_exclusions_changed=False,
        outputs={str(p.relative_to(staging)): base.cohort.digest(p) for p in staging.rglob("*") if p.is_file()})
    base.write_json(staging / "plan.json", plan)
    (staging / "plan.sha256").write_text(base.cohort.digest(staging / "plan.json") + "\n")
    if base.STOP: raise InterruptedError("Stopped; staging preserved")
    staging.rename(args.output)
    return check(args)


def results(args, plan):
    maps, clusters, receipts = [], [], []
    digest = base.cohort.digest(args.output / "plan.json")
    for job in plan["jobs"]:
        path = args.output / "jobs" / job["key"] / "success.json"
        saved = json.loads(path.read_text())
        if saved["job"] != job or saved["plan_sha256"] != digest or saved["smoke"]:
            raise ValueError("Moderation receipt mismatch")
        base.verify_sources(saved["outputs"])
        prefix = Path(saved["attempt"]) / "randomise"
        if base.output_images(prefix, plan["masks"][job["family"]]) != saved["outputs"]:
            raise ValueError("Moderation result inventory changed")
        receipts.append(base.fingerprint(path))
        for i, direction in ((1, "positive"), (2, "negative")):
            row, found = predictor.summary.map_summary(job, direction, nib.load(str(prefix) + f"_tstat{i}.nii.gz"),
                nib.load(str(prefix) + f"_clustere_corrp_tstat{i}.nii.gz"), nib.load(plan["masks"][job["family"]]))
            extra = dict(family=job["family"], role=job["role"], moderator=job["moderator"])
            maps.append(dict(row, **extra)); clusters.extend(dict(r, **extra) for r in found)
    files = {"maps.tsv": base.review.tsv(maps),
        "clusters.tsv": base.review.tsv(clusters, predictor.summary.CLUSTER_FIELDS + ["family", "role", "moderator"]),
        "provenance.json": base.cohort.json_text(dict(n=97, jobs=len(plan["jobs"]), maps=len(maps), receipts=receipts,
            plan_sha256=digest, interaction_order=2, cross_analysis_correction="none; exploratory per-map FWE")),
        "README.md": "# Financial Moderation: N=97\n\nSeparate two-way FEVS (lead) / OAFEM (secondary) interactions "
            "with MSPSS, ADI, PM2.5 and Ecog. Brain image is the outcome. Both constituent main effects included. "
            "No three-way terms, causal inference or new exclusions. All directions/CDTs, including nulls, in maps.tsv. "
            "Per-map cluster-FWE only; no correction across the exploratory family.\n"}
    args.report.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        path = args.report / name
        if path.exists() and path.read_text() != text: raise ValueError("Existing moderation report differs")
        if not path.exists(): path.write_text(text)
    for row in maps:
        print(f"RESULT {row['job']} {row['direction']}: min cluster-FWE p={row['min_cluster_fwe_p']:.4f}; voxels={row['significant_voxels']}", flush=True)
    print(f"CHECK PASSED: {len(plan['jobs'])} moderation jobs / {len(maps)} maps; N=97; settled exclusions unchanged.", flush=True)


def run(args):
    plan = build(args)
    if args.prepare_only: return
    digest = base.cohort.digest(args.output / "plan.json")
    for family in plan["families"]:
        job = next(j for j in plan["jobs"] if j["family"] == family and j["model"] == "fevsxmspss")
        if predictor.execute(plan, job, args.output / "smoke" / family, digest, smoke=True) == "NOT_STARTED":
            raise InterruptedError("Stopped before smoke test")
    outcomes, failures = {}, {}
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(predictor.execute, plan, j, args.output / "jobs" / j["key"], digest): j for j in plan["jobs"]}
        while futures:
            done, _ = wait(futures, timeout=60, return_when=FIRST_COMPLETED)
            if not done: print(f"HEARTBEAT moderation finished={len(outcomes)}/{len(plan['jobs'])}", flush=True)
            for future in done:
                job = futures.pop(future)
                try:
                    value = future.result()
                    if value == "NOT_STARTED": raise InterruptedError("Stopped")
                    outcomes[job["key"]] = value
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
    if failures or base.STOP: raise RuntimeError("Moderation incomplete; outputs preserved; resume same frozen release")


def main():
    os.umask(0)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--jobs", type=int, default=16)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args(); args.project = args.project.resolve()
    if not 1 <= args.jobs <= 48: parser.error("--jobs must be 1..48")
    root = args.project / "derivatives/fsl/randomise"
    args.baseline = root / "katie-v1"; args.connectivity = root / "katie-remaining-v1/connectivity"
    args.output = root / "katie-financial-moderation-v1"
    args.report = args.project / "results/randomise/katie-financial-moderation-v1"
    args.upstream = Path("/ZPOOL/data/projects/rf1-sra-linux2").resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGTERM, base.stop); signal.signal(signal.SIGINT, base.stop)
    locks = []
    try:
        own = (root / ".katie-financial-moderation-v1.lock").open("a")
        fcntl.flock(own, fcntl.LOCK_EX | fcntl.LOCK_NB); locks.append(own)
        # Queue behind the predictor batch; its outputs and active children are never signalled.
        for name in (".katie-financial-v1.lock", ".katie-remaining-v1.lock", ".katie-v1.lock"):
            locks.append(predictor.wait_shared(root / name))
        base.LEASE_FD = locks[1].fileno()
        run(args)
    finally:
        for lock in reversed(locks): lock.close()


if __name__ == "__main__":
    try: main()
    except Exception as exc:
        print(f"FAILED ({type(exc).__name__}): {exc}", file=sys.stderr, flush=True); sys.exit(1)
