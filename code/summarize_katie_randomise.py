#!/usr/bin/env python3
"""Summarize verified completed Katie maps; never rerun or modify inference."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

import nibabel as nib
import numpy as np
from scipy.ndimage import label

import run_katie_randomise as runner


def map_summary(job, direction, t_image, corrected_image, mask_image):
    runner.grid(mask_image, t_image)
    runner.grid(mask_image, corrected_image)
    mask = mask_image.get_fdata() > 0
    statistic, corrected = t_image.get_fdata(), corrected_image.get_fdata()
    if (not mask.any() or not np.isfinite(statistic).all()
            or not np.isfinite(corrected).all()
            or corrected.min() < 0 or corrected.max() > 1):
        raise ValueError("Invalid mask/statistic/corrected probability image")
    # FSL corrected images contain 1-p. Extent components here are descriptive:
    # inference is taken from the existing permutation-corrected map, not refit.
    significant = mask & (corrected > .95)
    components, count = label(significant, structure=np.ones((3, 3, 3), dtype=bool))
    common = dict(job=job["key"], outcome=job["outcome"], model=job["model"],
                  direction=direction, z=job["z"], t_cutoff=job["t_cutoff"], n=97)
    row = dict(**common, min_cluster_fwe_p=float(1 - corrected[mask].max()),
               significant_voxels=int(significant.sum()), significant_clusters=count,
               max_contrast_t=float(statistic[mask].max()))
    clusters = []
    voxel_volume = float(abs(np.linalg.det(mask_image.affine[:3, :3])))
    for component in range(1, count + 1):
        selected = components == component
        indices = np.argwhere(selected)
        peak = indices[np.argmax(statistic[selected])]
        world = nib.affines.apply_affine(mask_image.affine, peak)
        clusters.append(dict(**common, component=component, voxels=int(selected.sum()),
                             volume_mm3=float(selected.sum() * voxel_volume),
                             cluster_fwe_p_min=float(1 - corrected[selected].max()),
                             cluster_fwe_p_max=float(1 - corrected[selected].min()),
                             peak_contrast_t=float(statistic[tuple(peak)]),
                             peak_x_mm=float(world[0]), peak_y_mm=float(world[1]), peak_z_mm=float(world[2])))
    return row, clusters


def summarize(output):
    plan = runner.load_plan(output)
    if plan["n"] != 97 or len(plan["jobs"]) != 24:
        raise ValueError("Expected the frozen 97-person, 24-job analysis")
    for name, digest in plan["outputs"].items():
        if runner.cohort.digest(output / name) != digest:
            raise ValueError("Frozen input/design changed: " + name)
    plan_hash = runner.cohort.digest(output / "plan.json")
    mask = nib.load(plan["mask"])
    maps, clusters, receipts = [], [], []
    for job in plan["jobs"]:
        path = output / "jobs" / job["key"] / "success.json"
        saved = json.loads(path.read_text())
        if saved["plan_sha256"] != plan_hash or saved["job"] != job or saved["smoke"]:
            raise ValueError("Completed result receipt differs: " + job["key"])
        runner.verify_sources(saved["outputs"])
        prefix = Path(saved["attempt"]) / "randomise"
        if runner.output_images(prefix, plan["mask"]) != saved["outputs"]:
            raise ValueError("Completed result inventory differs: " + job["key"])
        receipts.append(runner.fingerprint(path))
        for index, direction in ((1, "positive"), (2, "negative")):
            t_image = nib.load(str(prefix) + f"_tstat{index}.nii.gz")
            corrected = nib.load(str(prefix) + f"_clustere_corrp_tstat{index}.nii.gz")
            row, found = map_summary(job, direction, t_image, corrected, mask)
            maps.append(row)
            clusters.extend(found)
    if len(maps) != 48:
        raise ValueError("Expected 48 directional maps")
    runner.verify_sources(plan["sources"])
    provenance = dict(plan_sha256=plan_hash, receipts=receipts, n=97, jobs=24, maps=48,
                      alpha=.05, rule="corrected_1_minus_p > 0.95 inside the frozen common mask",
                      components="26-connected significant-map components, descriptive only",
                      cross_analysis_correction="none; exploratory across models/outcomes/directions/CDTs",
                      images_changed=False, exclusions_changed=False)
    return maps, clusters, provenance


CLUSTER_FIELDS = ["job", "outcome", "model", "direction", "z", "t_cutoff", "n", "component", "voxels",
                  "volume_mm3", "cluster_fwe_p_min", "cluster_fwe_p_max", "peak_contrast_t",
                  "peak_x_mm", "peak_y_mm", "peak_z_mm"]


def report_files(maps, clusters, provenance):
    lines = ["# Katie N=97 Preliminary Randomise Results", "",
             "All 24 jobs / 48 directional maps passed receipt, image and input-hash checks.",
             "These are exploratory per-map cluster-FWE results; no additional correction",
             "across models, outcomes, directions or CDTs. Both CDTs are shown, including nulls.",
             "No inference was rerun and no images, cohort or exclusions changed.", "",
             "| Outcome | Model | Direction | CDT Z | Minimum cluster-FWE p | Significant voxels | Components |",
             "|---|---|---|---|---|---|---|"]
    for row in maps:
        lines.append(f"| {row['outcome']} | {row['model']} | {row['direction']} | {row['z']} | "
                     f"{row['min_cluster_fwe_p']:.4f} | {row['significant_voxels']} | {row['significant_clusters']} |")
    lines += ["", "`maps.tsv` contains all 48 maps; `clusters.tsv` contains only components passing",
              "p<0.05 (1-p>0.95). Empty cluster tables are valid null results. Components use",
              "26-connectivity and are descriptive summaries of existing corrected maps, not",
              "a new cluster-inference procedure. Peak t is the signed-contrast statistic:",
              "a positive peak for a negative contrast indicates a negative association.",
              "Peak locations are world millimetres in the input MNI image grid, not subject",
              "addresses or other geographic coordinates. Cluster labels are not anatomical labels.", "",
              "The standalone ADI/PM2.5 models test their main effects. Interaction models",
              "test the interaction only; constituent main effects are included but not separately",
              "contrasted. Intercept/group-average activation has not been tested.", ""]
    return {"README.md": "\n".join(lines), "maps.tsv": runner.review.tsv(maps),
            "clusters.tsv": runner.review.tsv(clusters, CLUSTER_FIELDS),
            "provenance.json": runner.cohort.json_text(provenance)}


def main():
    os.umask(0)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, default=runner.ROOT / "derivatives/fsl/randomise/katie-v1")
    parser.add_argument("--report", type=Path, default=runner.ROOT / "results/randomise/katie-v1")
    args = parser.parse_args()
    maps, clusters, provenance = summarize(args.analysis.resolve())
    files = report_files(maps, clusters, provenance)
    for name, content in files.items():
        path = args.report / name
        if path.exists() and path.read_text() != content:
            raise ValueError("Existing report differs; preserve it and select a new --report directory")
    args.report.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        path = args.report / name
        if not path.exists():
            path.write_text(content)
    print("CHECK PASSED: all 24 jobs / 48 maps verified; summary only; no inference or exclusions changed.")
    for row in maps:
        print(f"{row['job']} {row['direction']}: min cluster-FWE p={row['min_cluster_fwe_p']:.4f}; "
              f"significant voxels={row['significant_voxels']}; components={row['significant_clusters']}")
    print("REPORT: " + str(args.report.resolve()))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAILED ({type(exc).__name__}): {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
