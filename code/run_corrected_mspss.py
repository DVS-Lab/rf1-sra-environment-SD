#!/usr/bin/env python3
"""Versioned corrected-screener MSPSS refits; never replace original inference."""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import csv
import fcntl
import json
import os
from pathlib import Path
import signal
import tempfile

import nibabel as nib
import numpy as np
from scipy.stats import norm, t

import run_fevs_imaging_adjustments as adjustments

extension = adjustments.extension
base = extension.base
ROOT = Path(__file__).resolve().parents[1]
VERSION = "katie-mspss-corrected-v1"
SCORES = "data/derived/mspss-correction-v1/screener_scores.tsv"
PROVENANCE = "data/derived/mspss-correction-v1/provenance.json"
EXPORT_SHA = "75924cc86f754d347078b8cc349598e24e3a4527a9004fee392624dd30ee4511"
MODELS = ("adixmspss", "pm25xmspss", "fevsxmspss", "oafemxmspss")
OUTCOMES = ("social_specific", "average", "win_only", "loss_only")
LABELS = dict(social_specific="(Social win-loss) - (Doors win-loss)",
              average="Mean of Social and Doors win-loss", win_only="Social win - Doors win",
              loss_only="Social loss - Doors loss")


def corrected_scores(root, ids, old):
    fields, rows = base.cohort.read_table(root / SCORES)
    receipt = json.loads((root / PROVENANCE).read_text())
    if (fields != ["subject", "mspss"] or [r["subject"] for r in rows] != ids
            or len(ids) != 97 or len(set(ids)) != 97
            or receipt["n"] != 97 or receipt["field"] != "mspss_sum"
            or receipt["administration"] != "island_screener"
            or receipt["raw_export_sha256"] != EXPORT_SHA
            or receipt["scores_sha256"] != base.cohort.digest(root / SCORES)
            or receipt["roster_sha256"] != base.cohort.digest(root / adjustments.behavior.ROSTER)):
        raise ValueError("Corrected screener scores, provenance or frozen N=97 order differ")
    scores = np.array([float(r["mspss"]) for r in rows])
    change = scores - old
    if (not np.isfinite(scores).all() or np.any((scores < 1) | (scores > 7))
            or np.any(change < -1e-7) or np.any(change > 1 + 1e-7)):
        raise ValueError("Corrected MSPSS outside 1..7 or authorized 0..1 recoding increment")
    return scores


def freeze_export(path):
    """Generate only the approved cohort's IDs/means; raw dates/items stay local."""
    if base.cohort.digest(path) != EXPORT_SHA:
        raise ValueError("Expected Ryan's revised November 5 export; source hash differs")
    ids, values = adjustments.behavior.inputs(ROOT)
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    keyed = {}
    for row in rows:
        subject = base.cohort.identifier(row["rf1-id"])
        if subject in keyed:
            raise ValueError("Duplicate participant in revised source export")
        keyed[subject] = row
    selected = []
    for subject in ids:
        row = keyed[subject]
        total = float(row["mspss_sum"])
        parts = [float(row["mspss_" + n]) for n in ("friends", "family", "sig_other")]
        if not np.isfinite([total, *parts]).all() or abs(total - np.mean(parts)) > .00501:
            raise ValueError("MSPSS mean/subscales do not reconcile")
        selected.append(dict(subject=subject, mspss=row["mspss_sum"]))
    text = base.review.tsv(selected, ["subject", "mspss"])
    destination = ROOT / SCORES
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.read_text() != text:
        raise ValueError("Existing corrected source differs; refusing overwrite")
    destination.write_text(text)
    receipt = dict(n=97, administration="island_screener", field="mspss_sum",
        raw_export_sha256=EXPORT_SHA, scores_sha256=base.cohort.digest(destination),
        roster_sha256=base.cohort.digest(ROOT / adjustments.behavior.ROSTER),
        source="Ryan's revised MSPSS Island-Screener / RF1 Prescan export, 2026-11-05",
        timing_note="Selected screener record preserved, including repeat screeners after scan; not prescan retest or an average of administrations.",
        item_scoring_note="Corrected REDCap means supplied by acquisition team; no independent item-level rescore claimed.",
        exclusions_changed=False)
    text = base.cohort.json_text(receipt)
    target = ROOT / PROVENANCE
    if target.exists() and target.read_text() != text:
        raise ValueError("Existing corrected provenance differs; refusing overwrite")
    target.write_text(text)
    scores = corrected_scores(ROOT, ids, values["mspss"])
    print(f"FROZEN N=97 corrected screener means; {np.count_nonzero(abs(scores-values['mspss']) > 1e-7)} changed; no dates/raw export copied.")


def original_plan(project):
    folder = project / "derivatives/fsl/randomise/katie-reward-extension-v1"
    if base.cohort.digest(folder / "plan.json") != (folder / "plan.sha256").read_text().strip():
        raise ValueError("Original extension plan seal differs")
    plan = json.loads((folder / "plan.json").read_text())
    if (plan["n"] != 97 or len(plan["jobs"]) != 220 or len(plan["coverage"]) != 1328
            or plan["project"] != str(project) or plan["exclusions_changed"] or plan["original_results_changed"]):
        raise ValueError("Original extension inventory differs")
    return folder, plan


def design(source, ids, values, corrected, outcome, model):
    first = model.split("x")[0]
    nuisance = ["ones", *(["pair_mean_fd", "pair_mean_tsnr"] if outcome == "average"
                           else ["delta_fd", "delta_tsnr"]), "e11", "xa30", "gender_code1", "age"]
    names = [*nuisance, first, "mspss", model]
    path = Path(source["design"])
    fields, rows = base.cohort.read_table(path.with_suffix(".tsv"))
    x = extension.audit.matrix(path)
    if (fields != ["subject", *names] or [r["subject"] for r in rows] != ids
            or x.shape != (97, 10) or not np.isfinite(x).all()
            or not np.allclose(x, [[float(r[n]) for n in names] for r in rows], rtol=0, atol=1e-12)):
        raise ValueError("Original design columns, values or participant order differ")
    for name in (first, "mspss", "age", "gender_code1"):
        if not np.allclose(x[:, names.index(name)], values[name] - values[name].mean(), rtol=0, atol=1e-10):
            raise ValueError("Original design differs from authenticated centered scores: " + name)
    if not np.array_equal(x[:, 0], np.ones(97)) or not np.allclose(x[:, 9], x[:, 7]*x[:, 8], rtol=0, atol=1e-10):
        raise ValueError("Original intercept/interaction differs")
    adjusted = x.copy()
    adjusted[:, 8] = corrected - corrected.mean()
    adjusted[:, 9] = adjusted[:, 7] * adjusted[:, 8]
    if (not np.array_equal(x[:, :8], adjusted[:, :8]) or not np.isfinite(adjusted).all()
            or np.linalg.matrix_rank(adjusted) != 10):
        raise ValueError("Corrected model must retain all other columns and full-rank N=97")
    return names, adjusted


def specification(output, original, ids, values, corrected):
    files = {"subjects.tsv": base.review.tsv([dict(subject=s) for s in ids])}
    jobs, references = [], []
    lookup = {j["key"]: j for j in original["jobs"]}
    for family in ("activation", "connectivity"):
        for outcome in OUTCOMES:
            for model in MODELS:
                rows = [r for r in original["coverage"] if
                        (r["family"], r["outcome"], r["model"]) == (family, outcome, model)]
                expected = {(z, d["term"], d["direction"]) for z in (2.6, 3.1)
                            for d in extension.definitions([model.split("x")[0], "mspss", model])}
                if len(rows) != 12 or {(r["z"], r["term"], r["direction"]) for r in rows} != expected:
                    raise ValueError("Incomplete or duplicate original MSPSS scientific coverage")
                chosen = None
                for row in rows:
                    source = row["source"]
                    job = lookup[source["job"]] if source["origin"] == "extension" else source["source_job"]
                    if (job["family"] if "family" in job else family) != family or job["model"] != model:
                        raise ValueError("Coverage points to a different model/family")
                    names, x = design(job, ids, values, corrected, outcome, model)
                    if chosen is not None and (chosen[0] != names or not np.array_equal(chosen[1], x)):
                        raise ValueError("Retained/extension MSPSS matrices disagree")
                    chosen = names, x
                    references.extend([Path(job["design"]), Path(job["design"]).with_suffix(".tsv"), Path(job["contrast"])])
                names, x = chosen
                folder = Path("designs") / family / outcome / model
                files[str(folder / "design.mat")] = base.vest_matrix(x)
                files[str(folder / "design.tsv")] = base.review.tsv(
                    [dict(subject=s, **dict(zip(names, row))) for s, row in zip(ids, x)])
                text, definitions = extension.contrast_text(names, names[7:])
                files[str(folder / "design.con")] = text
                for z in (2.6, 3.1):
                    jobs.append(dict(key=f"{family}/{outcome}/{model}/z-"+str(z).replace(".", "p"),
                        family=family, outcome=family+"/"+outcome, model=model, z=z, residual_dof=87,
                        t_cutoff=float(t.isf(norm.sf(z), 87)), permutations=10000, seed=20261101,
                        design=str(output/folder/"design.mat"), contrast=str(output/folder/"design.con"),
                        contrasts=definitions, columns=names))
    if len(jobs) != 64 or sum(len(j["contrasts"]) for j in jobs) != 384:
        raise ValueError("Expected exactly 64 corrected jobs / 384 directional tests")
    return files, jobs, sorted(set(references))


def inputs(args):
    folder, original = original_plan(args.project)
    ids, values = adjustments.behavior.inputs(ROOT)
    _, roster = base.cohort.read_table(folder / "subjects.tsv")
    if [r["subject"] for r in roster] != ids:
        raise ValueError("Original image-volume order differs from approved roster")
    corrected = corrected_scores(ROOT, ids, values["mspss"])
    return folder, original, ids, values, corrected


def build(args):
    if (args.output / "plan.json").exists():
        return check(args)
    if args.output.exists():
        raise ValueError("Unrecognized existing correction folder; nothing overwritten")
    folder, original, ids, values, corrected = inputs(args)
    files, jobs, references = specification(args.output, original, ids, values, corrected)
    records = {}
    for r in original["sources"]:
        extension.audit.add_record(records, r["path"], r["sha256"], r.get("size"))
    for name, digest in original["outputs"].items():
        extension.audit.add_record(records, folder/name, digest)
    paths = [folder/"plan.json", folder/"plan.sha256", folder/"subjects.tsv", *references,
             *map(Path, original["images"].values()), *map(Path, original["masks"].values()),
             Path(original["randomise"]), ROOT/SCORES, ROOT/PROVENANCE]
    paths += [Path(m.__file__) for m in (adjustments, extension, base, adjustments.behavior,
                                       adjustments.summary, base.cohort, base.review, extension.audit)]
    paths += [Path(__file__)]
    paths += [ROOT/p for p in (adjustments.behavior.ROSTER, adjustments.behavior.SCORE_FILE,
                              adjustments.behavior.VARIABLES, adjustments.behavior.SOURCE_RECEIPT, adjustments.behavior.POLICY)]
    for path in set(paths):
        r = base.fingerprint(path)
        extension.audit.add_record(records, r["path"], r["sha256"], r["size"])
    sources = adjustments.normalize_sources(records)
    stage = Path(tempfile.mkdtemp(prefix=".mspss-corrected-", dir=args.output.parent))
    stage.chmod(0o777)
    for name, text in files.items():
        path = stage/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    plan = dict(n=97, project=str(args.project), data_root=str(ROOT), original=str(folder), jobs=jobs,
        images=original["images"], masks=original["masks"], randomise=original["randomise"], sources=sources,
        exclusions_changed=False, existing_outputs_changed=False, corrected_administration="island_screener",
        code_sha256=base.cohort.digest(Path(__file__)),
        outputs={str(p.relative_to(stage)): base.cohort.digest(p) for p in stage.rglob("*") if p.is_file()})
    base.write_json(stage/"plan.json", plan)
    (stage/"plan.sha256").write_text(base.cohort.digest(stage/"plan.json")+"\n")
    if base.STOP:
        raise InterruptedError("Stopped; staged inputs preserved")
    stage.rename(args.output)
    return check(args)


def check(args):
    plan = base.load_plan(args.output)
    folder, original, ids, values, corrected = inputs(args)
    files, jobs, _ = specification(args.output, original, ids, values, corrected)
    if (plan["project"] != str(args.project) or plan["data_root"] != str(ROOT) or plan["n"] != 97
            or plan["code_sha256"] != base.cohort.digest(Path(__file__)) or plan["original"] != str(folder)
            or plan["exclusions_changed"] or plan["existing_outputs_changed"]
            or plan["corrected_administration"] != "island_screener" or plan["jobs"] != jobs
            or plan["images"] != original["images"] or plan["masks"] != original["masks"]
            or plan["randomise"] != original["randomise"] or set(files) != set(plan["outputs"])):
        raise ValueError("Correction identity/inventory differs; resume its original frozen release")
    for name, text in files.items():
        if (args.output/name).read_text() != text or base.cohort.digest(args.output/name) != plan["outputs"][name]:
            raise ValueError("Frozen corrected design, contrast or row order differs")
    for family in ("activation", "connectivity"):
        mask = nib.load(plan["masks"][family])
        if not np.isfinite(mask.get_fdata()).all() or not np.any(mask.get_fdata() > 0):
            raise ValueError("Nonempty finite original mask required")
        for outcome in OUTCOMES:
            image = nib.load(plan["images"][family+"/"+outcome])
            base.grid(mask, image, 4)
            if image.shape[3] != 97:
                raise ValueError("Exactly 97 original image volumes required")
    print("CHECK PASSED: corrected screener MSPSS only; N=97, image/mask/order and all other columns unchanged; "
          "64 jobs / 384 signed tests, activation and VS-PPI, all four contrasts; exclusions unchanged.", flush=True)
    return plan


def results(args, plan):
    maps, clusters, evidence = [], [], []
    for job in plan["jobs"]:
        prefix, records = adjustments.completed(plan, job, args.output)
        evidence.extend(records)
        mask = nib.load(plan["masks"][job["family"]])
        support = mask.get_fdata() > 0
        positives = {}
        for definition in job["contrasts"]:
            index, term, direction = (definition[n] for n in ("index", "term", "direction"))
            statistic = nib.load(str(prefix)+f"_tstat{index}.nii.gz")
            corrected = nib.load(str(prefix)+f"_clustere_corrp_tstat{index}.nii.gz")
            data = statistic.get_fdata()
            active = support & (corrected.get_fdata() > .95)
            if np.any(data[active] < job["t_cutoff"] - 1e-5):
                raise ValueError("Corrected cluster below native cluster-forming threshold")
            if direction == "positive":
                positives[term] = data
            elif term not in positives or not np.allclose(data[support], -positives[term][support], rtol=1e-5, atol=1e-5):
                raise ValueError("Opposite directional maps disagree")
            row, found = adjustments.summary.map_summary(job, direction, statistic, corrected, mask)
            meta = dict(family=job["family"], term=term, outcome_label=LABELS[job["outcome"].split("/")[-1]])
            maps.append(dict(row, **meta))
            clusters.extend(dict(r, **meta) for r in found)
    if len(maps) != 384:
        raise ValueError("Incomplete corrected scientific map inventory")
    base.verify_sources(plan["sources"])
    base.verify_sources(evidence)
    report = args.output/"report"
    report.mkdir(exist_ok=True)
    texts = {"maps.tsv": base.review.tsv(maps), "clusters.tsv": base.review.tsv(clusters,
             [*adjustments.summary.CLUSTER_FIELDS, "family", "term", "outcome_label"])}
    texts["README.md"] = "\n".join([
        "# Corrected MSPSS Randomise Refits", "", "Validated: 64/64 jobs; 384 directional maps; fixed N=97.",
        "Corrected Island screener means from Ryan's revised export replace only MSPSS and its interaction.",
        "All original images, masks, participant order, other covariates and exclusions are unchanged.",
        "Models: ADI x MSPSS, PM2.5 x MSPSS, FEVS x MSPSS, OAFEM x MSPSS. Both main coefficients and interactions tested.",
        "Families: activation and original VS-seeded PPI. All four outcomes, both signs and both CDTs included, including nulls.",
        *[f"- {name}: {label}" for name, label in LABELS.items()], "",
        "10,000 permutations, seed 20261101; cluster extent, model-specific t thresholds equivalent to Z=2.6/3.1; df=87.",
        "Cluster-FWE is per map only, not across models/outcomes/signs/CDTs. All analyses remain exploratory.",
        "Selected screener records are retained even when from a repeat screener after scan; not interchangeable with prescan support.",
        "Corrected means were supplied by the acquisition team; this is not an independent item-level scoring audit.",
        "FEVS/OAFEM totals remain unchanged; their item-level scoring validation is a separate outstanding check.",
        "Original uncorrected-MSPSS fits remain archived in their existing folders; use these refits for MSPSS inference.",
        "Non-MSPSS fits, task-mean maps, FEVS additive ADI/Ecog checks and behavioral fits were not rerun.", ""])
    texts["provenance.json"] = base.cohort.json_text(dict(n=97, jobs=64, directional_maps=384,
        plan_sha256=base.cohort.digest(args.output/"plan.json"), raw_export_sha256=EXPORT_SHA,
        administration="island_screener", exclusions_changed=False, existing_outputs_changed=False,
        result_records=len(evidence), scope=list(MODELS)))
    for name, text in texts.items():
        path = report/name
        if path.exists() and path.read_text() != text:
            raise ValueError("Sealed corrected report differs; refusing overwrite")
        if not path.exists():
            path.write_text(text)
    base.write_json(report/"review_manifest.json", dict(n=97, outputs={n: base.cohort.digest(report/n) for n in texts}))
    print("CHECK PASSED: 64/64 corrected-MSPSS jobs, all 384 directional maps; original outputs unchanged.", flush=True)


def run(args):
    plan = build(args)
    digest = base.cohort.digest(args.output/"plan.json")
    for family in ("activation", "connectivity"):
        job = next(j for j in plan["jobs"] if j["family"] == family)
        if extension.execute(plan, job, args.output/"smoke"/family, digest, smoke=True) == "NOT_STARTED":
            raise InterruptedError("Stopped before native smoke test")
    outcomes = {}
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(extension.execute, plan, j, args.output/"jobs"/j["key"], digest): j for j in plan["jobs"]}
        while futures:
            done, _ = wait(futures, timeout=60, return_when=FIRST_COMPLETED)
            if not done:
                print(f"HEARTBEAT finished={len(outcomes)}/64 pending_or_running={len(futures)}", flush=True)
            for future in done:
                job = futures.pop(future)
                try:
                    outcomes[job["key"]] = future.result()
                except Exception as exc:
                    outcomes[job["key"]] = "FAILED: " + str(exc)
                print(outcomes[job["key"]]+" "+job["key"]+f" ({len(outcomes)}/64)", flush=True)
            base.write_json(args.output/"status.json", dict(status="running", validated=False, outcomes=outcomes, total=64))
    if base.STOP or any(v not in ("COMPLETED", "REUSED") for v in outcomes.values()):
        raise RuntimeError("Incomplete batch; completed results retained. Resume the identical frozen release.")
    results(args, plan)
    base.write_json(args.output/"status.json", dict(status="complete", validated=True, outcomes=outcomes, total=64))


def main():
    os.umask(0)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "run", "check", "check-results"))
    parser.add_argument("--project", type=Path, default=ROOT)
    parser.add_argument("--export", type=Path)
    parser.add_argument("--jobs", type=int, default=75)
    args = parser.parse_args()
    if not 1 <= args.jobs <= 80:
        parser.error("Use --jobs 1..80")
    if args.command == "freeze":
        if args.export is None:
            parser.error("freeze requires --export")
        freeze_export(args.export)
        return
    args.project = args.project.resolve()
    args.output = args.project/"derivatives/fsl/randomise"/VERSION
    args.output.parent.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGTERM, base.stop)
    signal.signal(signal.SIGINT, base.stop)
    with (args.output.parent/("."+VERSION+".lock")).open("a") as lock:
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
            if args.command == "run" and (args.output/"plan.json").exists():
                path = args.output/"status.json"
                saved = json.loads(path.read_text()) if path.exists() else {}
                base.write_json(path, dict(saved, status="stopped" if base.STOP else "failed", validated=False,
                                          error=str(exc), total=64))
            raise


if __name__ == "__main__":
    main()
