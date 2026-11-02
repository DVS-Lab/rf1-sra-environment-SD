#!/usr/bin/env python3
"""Read-only VS ROI outcome sanity check and bounded inventory of existing VS PPI."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys

import nibabel as nib
import numpy as np

import run_katie_randomise as base


def descriptive(values):
    values = np.asarray(values, dtype=float)
    if values.shape != (97,) or not np.isfinite(values).all():
        raise ValueError("Expected 97 finite participant ROI means")
    mean, sd = float(values.mean()), float(values.std(ddof=1))
    se = sd / np.sqrt(len(values))
    return dict(n=97, mean_cope=mean, sd=sd, se=float(se),
                descriptive_t=mean / se if se else "undefined_zero_variance",
                participants_positive=int((values > 0).sum()), inference="descriptive_only_no_corrected_p")


def ppi_candidates(project, subject, task):
    rows = []
    for variant in ("fsl-no-tedana-age55", "fsl"):
        parent = project / "derivatives" / variant / ("sub-" + subject)
        for folder in (parent / "ses-01", parent):
            if not folder.is_dir():
                continue
            for path in sorted(folder.glob("L1*.feat")):
                name = path.name.lower()
                if (f"task-{task}_" not in name or not re.search(r"ppi[_-](?:seed[_-])?vs(?:_|\.)", name)
                        or not re.search(r"run-0?1(?:_|\.)", name)):
                    continue
                session = re.search(r"ses-(\d+)(?:_|\.)", name)
                if session and session[1] not in ("01", "1"):
                    continue
                session_identity = "ses-01" if session or folder.name == "ses-01" else "legacy_session_unverified"
                required = [path / name for name in ("design.fsf", "design.con", "mask.nii.gz",
                                                    "stats/cope4.nii.gz", "stats/varcope4.nii.gz")]
                rows.append(dict(subject=subject, task=task, variant=variant, session_identity=session_identity, path=str(path),
                                 status="files_present_not_yet_lineage_validated" if all(p.is_file() for p in required)
                                 else "incomplete_files", missing=";".join(str(p) for p in required if not p.is_file())))
    return rows


def inspect(analysis, project):
    plan = base.load_plan(analysis)
    for name, digest in plan["outputs"].items():
        if base.cohort.digest(analysis / name) != digest:
            raise ValueError("Frozen analysis input changed: " + name)
    seed_path = project / "masks/seed-VS.nii.gz"
    seed, support = nib.load(seed_path), nib.load(plan["mask"])
    base.grid(support, seed)
    seed_values = seed.get_fdata()
    if not np.isfinite(seed_values).all() or not np.isin(seed_values, (0, 1)).all():
        raise ValueError("Expected the existing binary VS mask; no implicit resampling")
    roi = (seed_values > 0) & (support.get_fdata() > 0)
    if not roi.any():
        raise ValueError("VS mask does not overlap the common analysis mask")
    _, roster = base.cohort.read_table(analysis / "subjects.tsv")
    ids = [r["subject"] for r in roster]
    _, pairs = base.cohort.read_table(base.ROOT / "data/derived/katie-cohort-v1/selected_pairs.tsv")
    lookup = base.cohort.unique(pairs, ("subject", "contrast"))
    values = {task: [] for task in ("socialdoors", "doors")}
    inventory, paths = [], {seed_path, Path(__file__), analysis / "plan.json"}
    for subject in ids:
        pair = lookup[(subject, "4")]
        for task in values:
            path = Path(pair[task + "_cope"])
            image = nib.load(path)
            base.grid(support, image)
            data = image.get_fdata()[roi]
            if not np.isfinite(data).all():
                raise ValueError("Nonfinite VS COPE: " + str(path))
            values[task].append(float(data.mean()))
            paths.add(path)
            found = ppi_candidates(project, subject, task)
            inventory.extend(found or [dict(subject=subject, task=task, variant="scanned_both_roots", session_identity="ses-01", path="",
                                            status="not_found_in_scanned_roots", missing="")])
    a, b = np.asarray(values["socialdoors"]), np.asarray(values["doors"])
    outcomes = dict(socialdoors=a, doors=b, average=(a + b) / 2, social_specific=a - b)
    rows = [dict(outcome=name, **descriptive(data)) for name, data in outcomes.items()]
    counts = {task: dict(runs_with_any_candidate=len({r["subject"] for r in inventory if r["task"] == task and r["path"]}),
                        runs_with_files_present=len({r["subject"] for r in inventory if r["task"] == task
                                                     and r["status"] == "files_present_not_yet_lineage_validated"
                                                     and r["session_identity"] == "ses-01"}))
              for task in ("socialdoors", "doors")}
    provenance = dict(n=97, seed_mask_voxels=int((seed_values > 0).sum()), common_support_vs_voxels=int(roi.sum()),
                      sources=[base.fingerprint(p) for p in sorted(paths)], ppi_availability=counts,
                      note="ROI summaries are descriptive, not permutation tests or striatal activation claims. "
                           "PPI inventory is bounded to fsl and fsl-no-tedana-age55, subject/ses-01 and legacy subject folders; "
                           "file presence does not establish model/seed/confound compatibility. A seed mask is not a completed PPI.",
                      original_processing_changed=False)
    base.verify_sources(plan["sources"])
    base.verify_sources(provenance["sources"])
    return rows, inventory, provenance


def main():
    os.umask(0)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, default=base.ROOT / "derivatives/fsl/randomise/katie-v1")
    parser.add_argument("--task-project", type=Path, default=Path("/ZPOOL/data/projects/rf1-sra-socdoors"))
    parser.add_argument("--report", type=Path, default=base.ROOT / "results/validation/activation-connectivity-v1")
    args = parser.parse_args()
    roi, inventory, provenance = inspect(args.analysis.resolve(), args.task_project.resolve())
    files = {"vs_roi_descriptive.tsv": base.review.tsv(roi), "ppi_inventory.tsv": base.review.tsv(inventory),
             "provenance.json": base.cohort.json_text(provenance)}
    for name, text in files.items():
        path = args.report / name
        if path.exists() and path.read_text() != text:
            raise ValueError("Existing report differs; preserve it and select a new --report directory")
    args.report.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        path = args.report / name
        if not path.exists():
            path.write_text(text)
    print("READ-ONLY INSPECTION COMPLETE: descriptive ROI and PPI file inventory only; no inferential validation or exclusions.")
    print(f"VS mask voxels={provenance['seed_mask_voxels']}; common-support VS voxels={provenance['common_support_vs_voxels']}")
    for row in roi:
        print(json.dumps(row))
    print("PPI FILE AVAILABILITY (NOT MODEL VALIDATION): " + json.dumps(provenance["ppi_availability"]))
    print("REPORT: " + str(args.report.resolve()))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAILED ({type(exc).__name__}): {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
