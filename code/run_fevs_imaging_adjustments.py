#!/usr/bin/env python3
"""Matched additive ADI/Ecog sensitivity checks of three completed FEVS fits."""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import fcntl
import json
import os
from pathlib import Path
import signal
import tempfile
from types import SimpleNamespace

import nibabel as nib
import numpy as np
from scipy.stats import norm, t

import run_behavioral_moderation as behavior
import run_reward_extension as extension
import summarize_katie_randomise as summary

base = extension.base
ROOT = Path(__file__).resolve().parents[1]
VERSION = "katie-fevs-adjustments-provisional-v1"
TARGETS = (
    ("activation_fevs", "activation", "win_only", "fevs"),
    ("activation_fevs_pm25", "activation", "win_only", "fevsxpm25"),
    ("vs_fevs_pm25", "connectivity", "social_specific", "fevsxpm25"),
)
ADDITIONS = (("adi",), ("ecog",), ("adi", "ecog"))
COMMON = ["ones", "delta_fd", "delta_tsnr", "e11", "xa30", "gender_code1", "age"]
LABELS = dict(activation_fevs="Activation: Social win - Doors win; standalone FEVS",
              activation_fevs_pm25="Activation: Social win - Doors win; FEVS at mean PM2.5",
              vs_fevs_pm25="VS connectivity: (Social win-loss) - (Doors win-loss); FEVS at mean PM2.5")


def design(job, ids, values, added):
    path = Path(job["design"])
    fields, rows = base.cohort.read_table(path.with_suffix(".tsv"))
    names = COMMON + (["fevs"] if job["model"] == "fevs" else ["fevs", "pm25", "fevsxpm25"])
    x = extension.audit.matrix(path)
    if (len(ids) != 97 or len(set(ids)) != 97 or fields != ["subject", *names]
            or [r["subject"] for r in rows] != ids or x.shape != (97, len(names))):
        raise ValueError("Baseline columns or frozen participant order differ")
    if not np.allclose(x, [[float(r[n]) for n in names] for r in rows], rtol=0, atol=1e-12):
        raise ValueError("Baseline numeric/labeled matrix differs")
    for name in ("fevs", "age", *(["pm25"] if job["model"] == "fevsxpm25" else [])):
        if not np.allclose(x[:, names.index(name)], values[name] - values[name].mean(), rtol=0, atol=1e-10):
            raise ValueError("Baseline design does not match approved centered scores: " + name)
    if not np.allclose(x[:, names.index("gender_code1")],
                       values["gender_code1"] - values["gender_code1"].mean(), rtol=0, atol=1e-12):
        raise ValueError("Baseline gender coding differs")
    if (not np.array_equal(x[:, 0], np.ones(97))
            or (job["model"] == "fevsxpm25" and not np.allclose(x[:, -1], x[:, 7] * x[:, 8], rtol=0, atol=1e-10))):
        raise ValueError("Baseline intercept/interaction differs")
    if added not in ADDITIONS:
        raise ValueError("Only the three requested additive adjustments are authorized")
    adjusted = np.column_stack([x, *[values[n] - values[n].mean() for n in added]])
    if not np.isfinite(adjusted).all() or np.linalg.matrix_rank(adjusted) != adjusted.shape[1]:
        raise ValueError("Adjustment must retain finite, full-rank N=97; no rows may be dropped")
    return names + list(added), adjusted


def completed(plan, job, folder):
    path = folder / "jobs" / job["key"] / "success.json"
    saved = json.loads(path.read_text())
    attempt = Path(saved["attempt"])
    if not attempt.resolve().is_relative_to((path.parent / "attempts").resolve()):
        raise ValueError("Unsafe completed attempt path")
    prefix = attempt / "randomise"
    mask = plan["masks"][job["family"]]
    if (saved["job"] != job or saved["plan_sha256"] != base.cohort.digest(folder / "plan.json")
            or saved["smoke"] is not False
            or saved["command"] != base.command(dict(plan, mask=mask), job, prefix)
            or extension.products(prefix, mask, job["contrasts"]) != saved["outputs"]):
        raise ValueError("Completed job command, receipt or products differ")
    return prefix, [base.fingerprint(path), *saved["outputs"]]


def specification(output, original, ids, values):
    files = {"subjects.tsv": base.review.tsv([dict(subject=s) for s in ids])}
    jobs, baselines = [], []
    for target, family, outcome, model in TARGETS:
        for z in (2.6, 3.1):
            matches = [j for j in original["jobs"] if (j["family"], j["outcome"], j["model"], j["z"])
                       == (family, family + "/" + outcome, model, z)]
            if len(matches) != 1:
                raise ValueError("Expected exactly one completed target baseline")
            source = matches[0]
            definitions = [r for r in source["contrasts"] if r["term"] == "fevs"]
            if [(r["term"], r["direction"]) for r in definitions] != [("fevs", "positive"), ("fevs", "negative")]:
                raise ValueError("Baseline must test both FEVS main-effect directions, not the interaction")
            baselines.append(dict(target=target, job=source, definitions=definitions))
            for added in ADDITIONS:
                adjustment = "_".join(added)
                names, x = design(source, ids, values, added)
                folder = Path("designs") / target / adjustment
                files[str(folder / "design.mat")] = base.vest_matrix(x)
                files[str(folder / "design.tsv")] = base.review.tsv(
                    [dict(subject=s, **dict(zip(names, row))) for s, row in zip(ids, x)])
                text, definitions = extension.contrast_text(names, ["fevs"])
                files[str(folder / "design.con")] = text
                df = 97 - x.shape[1]
                jobs.append(dict(key=f"{target}/{adjustment}/z-" + str(z).replace(".", "p"),
                    target=target, adjustment=adjustment, family=family, outcome=source["outcome"],
                    model=model + "_adjust_" + adjustment, z=z, residual_dof=df,
                    t_cutoff=float(t.isf(norm.sf(z), df)), permutations=10000, seed=20261101,
                    design=str(output / folder / "design.mat"), contrast=str(output / folder / "design.con"),
                    contrasts=definitions, columns=names))
    if len(jobs) != 18 or len(baselines) != 6:
        raise ValueError("Unexpected matched adjustment inventory")
    return files, jobs, baselines


def original_inputs(args):
    folder = args.project / "derivatives/fsl/randomise/katie-reward-extension-v1"
    original = extension.check(SimpleNamespace(project=args.project, output=folder))
    ids, values = behavior.inputs(ROOT)
    _, ordered = base.cohort.read_table(folder / "subjects.tsv")
    if [r["subject"] for r in ordered] != ids:
        raise ValueError("Original image-volume order differs from frozen N=97")
    return folder, original, ids, values


def build(args):
    if (args.output / "plan.json").exists():
        return check(args)
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Unrecognized existing output; preserve it, do not overwrite")
    folder, original, ids, values = original_inputs(args)
    files, jobs, baselines = specification(args.output, original, ids, values)
    records = {r["path"]: r for r in original["sources"]}
    paths = [folder / "plan.json", folder / "plan.sha256", Path(__file__), Path(base.__file__),
             Path(extension.__file__), Path(summary.__file__), Path(behavior.__file__),
             Path(base.cohort.__file__), Path(base.review.__file__)]
    paths += [folder / name for name in original["outputs"]]
    paths += [ROOT / p for p in (behavior.ROSTER, behavior.SCORE_FILE, behavior.VARIABLES, behavior.SOURCE_RECEIPT, behavior.POLICY)]
    for item in baselines:
        _, evidence = completed(original, item["job"], folder)
        for r in evidence:
            extension.audit.add_record(records, r["path"], r["sha256"], r["size"])
        paths += [Path(item["job"]["design"]), Path(item["job"]["design"]).with_suffix(".tsv"),
                  Path(item["job"]["contrast"]), Path(original["images"][item["job"]["outcome"]]),
                  Path(original["masks"][item["job"]["family"]])]
    paths.append(Path(original["randomise"]))
    for path in paths:
        r = base.fingerprint(path)
        extension.audit.add_record(records, r["path"], r["sha256"], r["size"])
    stage = Path(tempfile.mkdtemp(prefix=".fevs-adjustments-", dir=args.output.parent))
    stage.chmod(0o777)
    for name, text in files.items():
        path = stage / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    plan = dict(n=97, provisional_scoring=True, project=str(args.project), data_root=str(ROOT),
        original=str(folder), jobs=jobs, baselines=baselines, images=original["images"], masks=original["masks"],
        randomise=original["randomise"], sources=list(records.values()),
        code_sha256=base.cohort.digest(Path(__file__)), exclusions_changed=False, existing_outputs_changed=False,
        outputs={str(p.relative_to(stage)): base.cohort.digest(p) for p in stage.rglob("*") if p.is_file()})
    base.write_json(stage / "plan.json", plan)
    (stage / "plan.sha256").write_text(base.cohort.digest(stage / "plan.json") + "\n")
    if base.STOP:
        raise InterruptedError("Stopped; completed outputs and staged inputs preserved")
    stage.rename(args.output)
    return check(args)


def check(args):
    plan = base.load_plan(args.output)
    if (plan["project"] != str(args.project) or plan["data_root"] != str(ROOT) or plan["n"] != 97
            or plan["code_sha256"] != base.cohort.digest(Path(__file__)) or not plan["provisional_scoring"]
            or plan["exclusions_changed"] or plan["existing_outputs_changed"]):
        raise ValueError("Frozen adjustment identity differs; use its original release")
    folder = args.project / "derivatives/fsl/randomise/katie-reward-extension-v1"
    original = json.loads((folder / "plan.json").read_text())
    ids, values = behavior.inputs(ROOT)
    files, jobs, baselines = specification(args.output, original, ids, values)
    if jobs != plan["jobs"] or baselines != plan["baselines"] or plan["original"] != str(folder):
        raise ValueError("Matched job inventory differs")
    if plan["images"] != original["images"] or plan["masks"] != original["masks"] or plan["randomise"] != original["randomise"]:
        raise ValueError("Original image/mask/native executable differs")
    if set(files) != set(plan["outputs"]):
        raise ValueError("Frozen adjustment artifact inventory differs")
    for name, text in files.items():
        if (args.output / name).read_text() != text or base.cohort.digest(args.output / name) != plan["outputs"][name]:
            raise ValueError("Frozen design, contrast or row order differs")
    for item in baselines:
        reference = nib.load(plan["masks"][item["job"]["family"]])
        image = nib.load(plan["images"][item["job"]["outcome"]])
        base.grid(reference, image, 4)
        if image.shape[3] != 97 or not np.any(reference.get_fdata() > 0):
            raise ValueError("Expected 97-volume image and nonempty original whole-brain mask")
    print("CHECK PASSED: matched N=97, unchanged images/masks/order and baseline columns; 18 additive adjustment jobs, "
          "both FEVS directions, model-specific Z-to-t CDTs. Scoring provisional; exclusions unchanged.", flush=True)
    return plan


def results(args, plan):
    maps, clusters, evidence, selected = [], [], [], {}
    original_folder = Path(plan["original"])
    original = json.loads((original_folder / "plan.json").read_text())
    units = [(b["target"], "baseline", b["job"], b["definitions"], original, original_folder) for b in plan["baselines"]]
    units += [(j["target"], j["adjustment"], j, j["contrasts"], plan, args.output) for j in plan["jobs"]]
    for target, adjustment, job, definitions, owner, folder in units:
        prefix, records = completed(owner, job, folder)
        evidence.extend(records)
        mask_image = nib.load(owner["masks"][job["family"]])
        support = mask_image.get_fdata() > 0
        positive = None
        for definition in definitions:
            index, direction = definition["index"], definition["direction"]
            statistic = nib.load(str(prefix) + f"_tstat{index}.nii.gz")
            corrected = nib.load(str(prefix) + f"_clustere_corrp_tstat{index}.nii.gz")
            data = statistic.get_fdata()
            active = support & (corrected.get_fdata() > .95)
            if np.any(data[active] < job["t_cutoff"] - 1e-5):
                raise ValueError("Corrected cluster below its native CDT")
            if direction == "positive":
                positive = data
            elif positive is None or not np.allclose(data[support], -positive[support], rtol=1e-5, atol=1e-5):
                raise ValueError("Opposite FEVS directional t maps disagree")
            row, found = summary.map_summary(job, direction, statistic, corrected, mask_image)
            meta = dict(target=target, adjustment=adjustment, term="fevs", provisional_scoring=True)
            selected[(target, adjustment, job["z"], direction)] = active
            maps.append(dict(row, **meta))
            clusters.extend(dict(r, **meta) for r in found)
    for row in maps:
        a = selected[(row["target"], row["adjustment"], row["z"], row["direction"])]
        b = selected[(row["target"], "baseline", row["z"], row["direction"])]
        total = int(a.sum() + b.sum())
        row["baseline_overlap_voxels"] = int((a & b).sum())
        row["baseline_dice"] = 2 * int((a & b).sum()) / total if total else ""
        print(f"RESULT {row['target']} +{row['adjustment']} Z={row['z']} {row['direction']} "
              f"p={row['min_cluster_fwe_p']:.6g} voxels={row['significant_voxels']}", flush=True)
    base.verify_sources(plan["sources"])
    base.verify_sources(evidence)
    report = args.output / "report"
    report.mkdir(exist_ok=True)
    texts = {"maps.tsv": base.review.tsv(maps),
             "clusters.tsv": base.review.tsv(clusters, [*summary.CLUSTER_FIELDS, "target", "adjustment", "term", "provisional_scoring"])}
    lines = ["# Matched FEVS Imaging Adjustments: Provisional N=97", "",
        "18 new jobs / 36 directional maps validated, compared with 6 retained baseline jobs / 12 FEVS maps.",
        "All three requested additive adjustments are reported: ADI, Ecog, and both. No baseline was rerun.",
        "Identical frozen images, whole-brain masks, volume order and original columns; no participant exclusions changed.",
        "FEVS/OAFEM item scoring remains unverified. MSPSS coding remains provisional; MSPSS is not in these designs.",
        "The PM2.5 models retain FEVS, centered PM2.5 and FEVS x PM2.5. They test FEVS at mean PM2.5, not that interaction.",
        "No new interaction is added. Both signs, 10,000 permutations, seed 20261101, model-specific Z-equivalent CDTs 2.6/3.1.",
        "Per-map cluster-FWE only; no joint correction across these correlated sensitivity tests. They are not independent replications.",
        "Overlap with the original corrected clusters is descriptive, not a restricted-mask test or evidence of equivalence.", ""]
    for target, *_ in TARGETS:
        lines += ["## " + LABELS[target], "", "| Added | CDT Z | Direction | Min cluster-FWE p | Voxels | Baseline overlap |",
                  "|---|---:|---|---:|---:|---:|"]
        for r in maps:
            if r["target"] == target:
                lines.append(f"| {r['adjustment']} | {r['z']} | {r['direction']} | {r['min_cluster_fwe_p']:.4f} | "
                             f"{r['significant_voxels']} | {r['baseline_overlap_voxels']} |")
        lines.append("")
    texts["README.md"] = "\n".join(lines)
    texts["provenance.json"] = base.cohort.json_text(dict(n=97, provisional_scoring=True,
        jobs=18, baseline_jobs_reused=6, directional_maps=48, exclusions_changed=False,
        plan_sha256=base.cohort.digest(args.output / "plan.json"),
        source_records=len(plan["sources"]), result_records=len(evidence),
        note="All requested sensitivity tests, including nulls; completed baseline inference unchanged"))
    for name, text in texts.items():
        path = report / name
        if path.exists() and path.read_text() != text:
            raise ValueError("Sealed report differs; refusing overwrite")
        path.write_text(text)
    base.write_json(report / "review_manifest.json", dict(n=97, provisional_scoring=True,
        outputs={name: base.cohort.digest(report / name) for name in texts}))
    print("CHECK PASSED: 18/18 adjustment jobs and all 48 baseline/adjusted FEVS maps verified; original results unchanged.", flush=True)


def run(args):
    plan = build(args)
    digest = base.cohort.digest(args.output / "plan.json")
    for family in ("activation", "connectivity"):
        job = next(j for j in plan["jobs"] if j["family"] == family)
        if extension.execute(plan, job, args.output / "smoke" / family, digest, smoke=True) == "NOT_STARTED":
            raise InterruptedError("Stopped before native smoke test")
    outcomes = {}
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(extension.execute, plan, j, args.output / "jobs" / j["key"], digest): j for j in plan["jobs"]}
        while futures:
            done, _ = wait(futures, timeout=60, return_when=FIRST_COMPLETED)
            if not done:
                print(f"HEARTBEAT finished={len(outcomes)}/18 pending_or_running={len(futures)}", flush=True)
            for future in done:
                job = futures.pop(future)
                try:
                    outcomes[job["key"]] = future.result()
                except Exception as exc:
                    outcomes[job["key"]] = "FAILED: " + str(exc)
                print(outcomes[job["key"]] + " " + job["key"], flush=True)
            base.write_json(args.output / "status.json", dict(status="running", validated=False, outcomes=outcomes, total=18))
    if base.STOP or any(v not in ("COMPLETED", "REUSED") for v in outcomes.values()):
        base.write_json(args.output / "status.json", dict(status="stopped" if base.STOP else "failed", validated=False, outcomes=outcomes, total=18))
        raise RuntimeError("Incomplete batch; completed receipts preserved. Resume the identical release.")
    results(args, plan)
    base.write_json(args.output / "status.json", dict(status="complete", validated=True, outcomes=outcomes, total=18))


def main():
    os.umask(0)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "check", "check-results"))
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=18)
    args = parser.parse_args()
    args.project = args.project.resolve()
    if not 1 <= args.jobs <= 18:
        parser.error("Use --jobs 1..18")
    args.output = args.project / "derivatives/fsl/randomise" / VERSION
    args.output.parent.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGTERM, base.stop)
    signal.signal(signal.SIGINT, base.stop)
    with (args.output.parent / ("." + VERSION + ".lock")).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        base.LEASE_FD = lock.fileno()
        try:
            if args.command == "run":
                run(args)
            else:
                plan = check(args)
                if args.command == "check-results":
                    results(args, plan)
        except Exception as exc:
            if args.command == "run" and (args.output / "plan.json").exists():
                path = args.output / "status.json"
                saved = json.loads(path.read_text()) if path.exists() else {}
                base.write_json(path, dict(saved, status="stopped" if base.STOP else "failed",
                                          validated=False, error=str(exc), total=18))
            raise


if __name__ == "__main__":
    main()
