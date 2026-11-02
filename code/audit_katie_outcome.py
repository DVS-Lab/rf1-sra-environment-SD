#!/usr/bin/env python3
"""Verify actual L1 COPE-4 weights and outcome EV timing for all 97 Katie pairs."""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
from pathlib import Path
import re
import shlex
import sys

import numpy as np

import run_katie_randomise as base


def settings(path):
    result = {}
    for line in path.read_text().splitlines():
        match = re.match(r"^set\s+fmri\(([^)]+)\)\s+(.+)$", line)
        if match:
            tokens = shlex.split(match[2])
            if len(tokens) != 1 or match[1] in result:
                raise ValueError("Ambiguous FSF setting: " + str(path))
            result[match[1]] = tokens[0]
    return result


def inspect_run(subject, task, feat, cope, events):
    if cope.resolve() != (feat / "stats/cope4.nii.gz").resolve():
        raise ValueError("Selected image is not this run's COPE 4")
    fsf, con = feat / "design.fsf", feat / "design.con"
    values = settings(fsf)
    if values.get("conname_real.4") != "win-loss":
        raise ValueError("L1 contrast 4 is not labeled win-loss")
    if [values.get(f"evtitle{i}") for i in range(1, 5)] != ["win", "loss", "decision", "miss"]:
        raise ValueError("Unexpected L1 event-column order")
    if values.get("evs_real") != "4" or any(values.get(f"deriv_yn{i}") != "0" for i in range(1, 5)):
        raise ValueError("Unexpected expanded task-EV design")
    if [float(values[f"con_real4.{i}"]) for i in range(1, 5)] != [1., -1., 0., 0.]:
        raise ValueError("FSF COPE-4 weights are not outcome win-loss")
    text = con.read_text()
    matrix = np.loadtxt(io.StringIO(text.split("/Matrix", 1)[1]), ndmin=2)
    if matrix.shape[0] != 4 or matrix.shape[1] < 4 or not np.isfinite(matrix).all():
        raise ValueError("Invalid actual FEAT contrast matrix")
    expected = np.zeros(matrix.shape[1]); expected[:2] = [1., -1.]
    if not np.array_equal(matrix[3], expected):
        raise ValueError("Actual design.con COPE-4 row includes non-outcome terms")
    with events.open() as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    paths = [fsf, con, events, cope]
    counts = {}
    for index, event in ((1, "win"), (2, "loss")):
        expected_events = np.array([[float(r["onset"]), float(r["duration"]), 1.]
                                    for r in rows if r["trial_type"] == event])
        if expected_events.ndim != 2 or len(expected_events) < 1 or not np.isfinite(expected_events).all():
            raise ValueError("Missing/nonfinite BIDS outcome events: " + event)
        path = Path(values[f"custom{index}"])
        if not path.is_absolute():
            raise ValueError("Relative L1 EV path requires explicit provenance: " + str(path))
        actual = np.loadtxt(path, ndmin=2)
        if actual.shape != expected_events.shape:
            raise ValueError("L1 outcome EV count/columns differ from canonical BIDS events")
        actual = actual[np.argsort(actual[:, 0], kind="stable")]
        expected_events = expected_events[np.argsort(expected_events[:, 0], kind="stable")]
        # BIDSto3col emits decimal text; allow only microsecond-scale formatting.
        if not np.allclose(actual, expected_events, rtol=0, atol=1e-5):
            raise ValueError("L1 outcome timing/duration/amplitude differs from BIDS " + event)
        counts[event + "_events"] = len(actual)
        paths.append(path)
    return dict(subject=subject, task=task, session="01", contrast=4,
                phase="feedback_outcome", weights="1 -1 0 0; additional nuisance weights zero",
                **counts, status="passed"), paths


def audit(analysis):
    plan = base.load_plan(analysis)
    for name, digest in plan["outputs"].items():
        if base.cohort.digest(analysis / name) != digest:
            raise ValueError("Frozen analysis input changed: " + name)
    _, subjects = base.cohort.read_table(analysis / "subjects.tsv")
    ids = [row["subject"] for row in subjects]
    _, pairs = base.cohort.read_table(base.ROOT / "data/derived/katie-cohort-v1/selected_pairs.tsv")
    pairs = base.cohort.unique(pairs, ("subject", "contrast"))
    if len(ids) != 97 or len(set(ids)) != 97:
        raise ValueError("Expected the unchanged 97-person cohort")
    records, paths = [], {analysis / "plan.json", analysis / "subjects.tsv", Path(__file__),
                          base.ROOT / "data/derived/katie-cohort-v1/selected_pairs.tsv"}
    for subject in ids:
        for task in ("socialdoors", "doors"):
            pair = pairs[(subject, "4")]
            events = Path(plan["upstream"]) / f"bids/sub-{subject}/ses-01/func/sub-{subject}_ses-01_task-{task}_run-1_events.tsv"
            record, used = inspect_run(subject, task, Path(pair[task + "_feat_dir"]), Path(pair[task + "_cope"]), events)
            records.append(record)
            paths.update(used)
    fingerprints = [base.fingerprint(path) for path in sorted(paths)]
    base.verify_sources(plan["sources"])
    base.verify_sources(fingerprints)
    provenance = dict(n=97, runs=len(records), status="passed", plan_sha256=base.cohort.digest(analysis / "plan.json"),
                      sources=fingerprints, processing_changed=False,
                      meaning="L1 COPE4 is feedback win-loss; decision/miss/nuisance weights zero; live EVs match BIDS timing")
    return records, provenance


def main():
    os.umask(0)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, default=base.ROOT / "derivatives/fsl/randomise/katie-v1")
    parser.add_argument("--report", type=Path, default=base.ROOT / "results/validation/outcome-phase-v1")
    args = parser.parse_args()
    records, provenance = audit(args.analysis.resolve())
    files = {"runs.tsv": base.review.tsv(records), "provenance.json": base.cohort.json_text(provenance),
             "README.md": "# Katie Outcome-Phase Validation\n\nAll 194 L1 runs / 97 pairs passed. "
             "Selected COPE 4 uses win minus loss feedback events, with zero decision/miss/nuisance weights. "
             "Actual L1 EV onset/duration/amplitude matches canonical BIDS win/loss events. "
             "No analysis, timing file or exclusion was changed.\n"}
    for name, text in files.items():
        path = args.report / name
        if path.exists() and path.read_text() != text:
            raise ValueError("Existing audit differs; preserve it and choose a new --report")
    args.report.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        path = args.report / name
        if not path.exists():
            path.write_text(text)
    print("CHECK PASSED: all 194 actual L1 runs / 97 pairs use outcome-phase win-loss COPE 4; "
          "decision/miss/nuisance contrast weights zero; EV timing matches BIDS; no processing changed.", flush=True)
    print("REPORT: " + str(args.report.resolve()), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAILED ({type(exc).__name__}): {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
