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


def compare_events(actual, expected, context):
    if actual.shape != expected.shape or not np.isfinite(actual).all():
        raise ValueError("L1 outcome EV count/columns/finite values differ: " + context)
    actual = actual[np.argsort(actual[:, 0], kind="stable")]
    expected = expected[np.argsort(expected[:, 0], kind="stable")]
    delta = np.max(np.abs(actual - expected), axis=0)
    # BIDSto3col uses awk printf("%s", onset-0), whose default CONVFMT
    # is %.6g. Reproduce that documented transform, not a wider time tolerance.
    formatted = np.array([float(format(value, ".6g")) for value in expected[:, 0]])
    exact = np.isclose(actual[:, 0], expected[:, 0], rtol=0, atol=1e-5)
    legacy = np.isclose(actual[:, 0], formatted, rtol=0, atol=1e-10)
    if (not np.all(exact | legacy)
            or not np.allclose(actual[:, 1], expected[:, 1], rtol=0, atol=1e-5)
            or not np.array_equal(actual[:, 2], expected[:, 2])):
        raise ValueError(f"L1 outcome timing/duration/amplitude differs: {context}; "
                         f"max_abs_onset_delta_s={delta[0]:.9g}; max_abs_duration_delta_s={delta[1]:.9g}; "
                         f"max_abs_amplitude_delta={delta[2]:.9g}")
    return dict(max_abs_onset_delta_s=float(delta[0]), max_abs_duration_delta_s=float(delta[1]),
                timing_match="awk_6_significant_digit_onsets" if not exact.all() else "direct_decimal_match")


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
        comparison = compare_events(actual, expected_events, f"sub-{subject} {task} {event}")
        counts.update({event + "_" + name: value for name, value in comparison.items()})
        counts[event + "_events"] = len(actual)
        paths.append(path)
    return dict(subject=subject, task=task, session="01", contrast=4,
                phase="feedback_outcome", weights="1 -1 0 0; additional nuisance weights zero",
                **counts, status="passed", detail=""), paths


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
            feat, cope = Path(pair[task + "_feat_dir"]), Path(pair[task + "_cope"])
            paths.update(p for p in (feat / "design.fsf", feat / "design.con", cope, events) if p.is_file())
            try:
                record, used = inspect_run(subject, task, feat, cope, events)
                paths.update(used)
            except (ValueError, OSError, KeyError) as exc:
                record = dict(subject=subject, task=task, session="01", contrast=4, phase="unverified",
                              status="failed", detail=f"{type(exc).__name__}: {exc}")
            records.append(record)
    fingerprints = [base.fingerprint(path) for path in sorted(paths)]
    base.verify_sources(plan["sources"])
    base.verify_sources(fingerprints)
    failures = sum(row["status"] != "passed" for row in records)
    provenance = dict(n=97, runs=len(records), failures=failures, status="failed" if failures else "passed",
                      plan_sha256=base.cohort.digest(analysis / "plan.json"),
                      sources=fingerprints, processing_changed=False,
                      onset_comparison="Direct decimal match or exact documented awk %.6g onset formatting; no global timing shift allowed",
                      meaning="L1 COPE4 is feedback win-loss; decision/miss/nuisance weights zero; live EVs match BIDS timing")
    return records, provenance


def main():
    os.umask(0)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, default=base.ROOT / "derivatives/fsl/randomise/katie-v1")
    parser.add_argument("--report", type=Path, default=base.ROOT / "results/validation/outcome-phase-v2")
    args = parser.parse_args()
    records, provenance = audit(args.analysis.resolve())
    fields = list(dict.fromkeys(key for row in records for key in row))
    files = {"runs.tsv": base.review.tsv(records, fields), "provenance.json": base.cohort.json_text(provenance),
             "README.md": f"# Katie Outcome-Phase Validation\n\nChecked {len(records)} L1 runs / 97 pairs; "
             f"{provenance['failures']} failures. Passing runs use outcome win-loss COPE 4 with zero "
             "decision/miss/nuisance weights, and EV timing matches BIDS directly or via the documented "
             "awk six-significant-digit onset conversion. Review runs.tsv for residuals and failures. "
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
    if provenance["failures"]:
        for row in records:
            if row["status"] != "passed":
                print(f"REVIEW sub-{row['subject']} {row['task']}: {row['detail']}", flush=True)
        print(f"CHECK FAILED: {provenance['failures']}/194 outcome runs need attention; report saved; no processing changed.", flush=True)
    else:
        print("CHECK PASSED: all 194 actual L1 runs / 97 pairs use outcome-phase win-loss COPE 4; "
              "decision/miss/nuisance contrast weights zero; EV timing matches BIDS after documented formatting; no processing changed.", flush=True)
        formatted = sum(any(row.get(event + "_timing_match") == "awk_6_significant_digit_onsets"
                            for event in ("win", "loss")) for row in records)
        maximum = max(row[event + "_max_abs_onset_delta_s"] for row in records for event in ("win", "loss"))
        print(f"TIMING: {formatted}/194 runs used existing awk numeric onset formatting; max_abs_onset_delta_s={maximum:.9g}", flush=True)
    print("REPORT: " + str(args.report.resolve()), flush=True)
    if provenance["failures"]:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAILED ({type(exc).__name__}): {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
