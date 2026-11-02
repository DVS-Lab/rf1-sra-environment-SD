#!/usr/bin/env python3
"""Freeze the linked workbook intersected with the settled paired imaging pool.

Read-only with respect to source data. This creates tables, never images,
scientific models, new exclusion rules, or randomise jobs.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import fcntl
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = Path("data/derived/SD_analysis_data_2026-10-26.xlsx")
SNAPSHOT = Path("qc/paired_difference/socialdoors-v1")
FIELDS = ("rf1_id", "sub_age", "gender", "ecog_score", "mspss_sum", "adi_natrank", "pm25_mean_2013_2023")
TASKS = ("socialdoors", "doors")
EXPECTED = dict(linked=110, strict_imaging_pool=121, retained=97,
                existing_run_qc=11, existing_coverage=2, strict_pool_not_in_workbook=24)
POLICY = dict(version=1, order="ascending_RF1_ID", session="01",
              age="original_approved_imaging_age55_pool_no_new_screener_age_filter",
              selection="intersection_only_preserve_settled_source_and_run_QC_decisions",
              coverage_minimum_pct=95, fd_tsnr="existing_task_session_1.5_IQR_fences",
              tedana_component_exclusion=False, effect_outlier_exclusion=False,
              workbook_unchanged=True, model_specification="pending_user_agreement",
              image_bundle_validated=False, randomise_run=False)


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def json_text(value):
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"


def table(rows, fields):
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def read_table(path):
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = reader.fieldnames
        rows = list(reader)
    if not fields or len(set(fields)) != len(fields) or not rows:
        raise ValueError("Empty table or duplicate headers: " + str(path))
    if any(None in r or any(v is None for v in r.values()) for r in rows):
        raise ValueError("Malformed table: " + str(path))
    return fields, rows


def identifier(value):
    if isinstance(value, bool):
        raise ValueError("Boolean participant ID")
    if isinstance(value, (int, float)) and math.isfinite(value) and int(value) == value:
        value = str(int(value))
    text = str(value).removeprefix("sub-")
    if not re.fullmatch(r"\d{5}", text):
        raise ValueError("Invalid RF1 ID")
    return text


def numeric(value):
    if isinstance(value, bool):
        raise ValueError("Boolean numeric value")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Nonfinite numeric value")
    return result


def validate_analysis(rows):
    result = {}
    for original in rows:
        if set(original) != set(FIELDS):
            raise ValueError("Analysis schema must be the approved seven columns")
        sub = identifier(original["rf1_id"])
        if sub in result:
            raise ValueError("Duplicate workbook participant: " + sub)
        row = dict(original)
        for field in FIELDS[1:]:
            if field == "gender":
                if original[field] is None or str(original[field]).strip() == "":
                    raise ValueError("Missing source gender code")
            else:
                numeric(original[field])
        result[sub] = row
    if not result:
        raise ValueError("Empty analysis workbook")
    return result


def read_analysis(path):
    from openpyxl import load_workbook
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        if workbook.sheetnames != ["Data"]:
            raise ValueError("Expected exactly the approved Data sheet")
        values = iter(workbook["Data"].values)
        fields = tuple(next(values))
        if fields != FIELDS:
            raise ValueError("Workbook schema/order differs from approved seven columns")
        return validate_analysis([dict(zip(fields, row)) for row in values if any(v is not None for v in row)])
    finally:
        workbook.close()


def unique(rows, fields):
    result = {}
    for row in rows:
        key = tuple(row[f] for f in fields)
        if key in result:
            raise ValueError("Duplicate source identity: " + repr(key))
        result[key] = row
    return result


def validate_imaging(strict, diagnostic, members, runs):
    key_fields = ("subject", "session", "contrast")
    selected = unique(strict, key_fields)
    all_pairs = unique(diagnostic, key_fields)
    expected = {k: r for k, r in all_pairs.items() if r["group"] == "strict_pass"}
    if selected != expected:
        raise ValueError("Strict list is not exactly the existing diagnostic strict subset")
    membership = unique(members, ("subject", "session"))
    run_lookup = unique(runs, ("subject", "session", "task", "run"))
    pool = {r["subject"] for r in strict}
    member_pool = {sub for (sub, ses), row in membership.items() if ses == "01" and row["group"] == "strict_pass"}
    if pool != member_pool:
        raise ValueError("Strict subject pool differs from existing paired membership")
    for sub in pool:
        identifier(sub)
        member = membership[(sub, "01")]
        if member["diagnostic_pair"] != "True" or member["unavailable_partner_reasons"]:
            raise ValueError("Strict member has an existing hold/missing partner")
        if {(r["session"], r["contrast"]) for r in strict if r["subject"] == sub} != {
                ("01", str(c)) for c in range(1, 5)}:
            raise ValueError("Participant lacks four unique session-01 matched contrasts")
    for row in strict:
        if row["flags"]:
            raise ValueError("Strict pair has existing QC flags")
        for task in TASKS:
            run = run_lookup[(row["subject"], "01", task, "1")]
            if (run["previous_selection_status"] != "eligible"
                    or run["strict_selection_status"] != "eligible"
                    or run["qc_failure_reasons"] or run["coverage_decision"] != "pass"
                    or run["fd_mean_decision"] != "pass" or run["tsnr_decision"] != "pass"):
                raise ValueError("Strict pair conflicts with a settled source/run decision")
            for field in ("fd_mean", "tsnr", "coverage_pct", "fd_mean_fence", "tsnr_fence", "qc_failure_reasons"):
                if row[task + "_" + field] != run[field]:
                    raise ValueError("Paired QC differs from the frozen run decision")
            coverage, fd, tsnr = (numeric(run[f]) for f in ("coverage_pct", "fd_mean", "tsnr"))
            if (not 95 <= coverage <= 100 or not 0 <= fd <= numeric(run["fd_mean_fence"])
                    or tsnr < max(0, numeric(run["tsnr_fence"]))):
                raise ValueError("Strict row fails the existing numerical fences")
    return pool, membership, run_lookup


def reconcile(analysis, pool, members, runs):
    rows = []
    for sub in sorted(analysis):
        member = members.get((sub, "01"))
        if member is None:
            raise ValueError("Linked participant absent from existing paired membership: " + sub)
        group = member["group"]
        if sub in pool:
            status, reason = "retained", "in_linked_workbook_and_settled_strict_pair_pool"
        elif group == "fd_tsnr_flagged":
            status = "existing_run_qc"
            failures = []
            for task in TASKS:
                run = runs[(sub, "01", task, "1")]
                if run["qc_failure_reasons"]:
                    failures.append(task + ":" + run["qc_failure_reasons"])
            if not failures:
                raise ValueError("Existing flagged member has no recorded run-QC failure")
            reason = "|".join(failures)
        elif group == "not_paired" and member["unavailable_partner_reasons"] == "doors:exclude_below_95":
            status, reason = "existing_coverage", member["unavailable_partner_reasons"]
        else:
            raise ValueError("Unexpected existing decision; do not invent a new exclusion: " + sub)
        rows.append(dict(subject=sub, status=status, existing_pair_group=group, reason=reason))
    return rows


def git_source(root, relative):
    return subprocess.check_output(
        ["git", "-C", str(root), "log", "-1", "--format=%H", "--", relative.as_posix()], text=True).strip()


def generate(project, upstream):
    paths = [("analysis_repository", WORKBOOK, project),
             *(("preprocessing_repository", SNAPSHOT / name, upstream) for name in
               ("strict_pairs.tsv", "diagnostic_pairs.tsv", "pair_membership.tsv", "run_membership.tsv")),
             ("analysis_repository", Path("code/freeze_katie_cohort.py"), project)]
    sources = []
    for repo, rel, root in paths:
        record = dict(repository=repo, path=rel.as_posix(), sha256=digest(root / rel))
        if rel != Path("code/freeze_katie_cohort.py"):
            record["last_file_commit"] = git_source(root, rel)
        sources.append(record)
    analysis = read_analysis(project / WORKBOOK)
    strict_fields, strict = read_table(upstream / SNAPSHOT / "strict_pairs.tsv")
    _, diagnostic = read_table(upstream / SNAPSHOT / "diagnostic_pairs.tsv")
    _, members = read_table(upstream / SNAPSHOT / "pair_membership.tsv")
    _, runs = read_table(upstream / SNAPSHOT / "run_membership.tsv")
    pool, member_lookup, run_lookup = validate_imaging(strict, diagnostic, members, runs)
    reconciliation = reconcile(analysis, pool, member_lookup, run_lookup)
    subjects = sorted(set(analysis) & pool)
    counts = dict(linked=len(analysis), strict_imaging_pool=len(pool), retained=len(subjects),
                  existing_run_qc=sum(r["status"] == "existing_run_qc" for r in reconciliation),
                  existing_coverage=sum(r["status"] == "existing_coverage" for r in reconciliation),
                  strict_pool_not_in_workbook=len(pool - set(analysis)))
    if counts != EXPECTED:
        raise ValueError("Frozen study counts changed; investigate without silently changing cohort: " + repr(counts))
    lookup = {(r["subject"], r["contrast"]): r for r in strict}
    selected = [lookup[(s, str(c))] for s in subjects for c in range(1, 5)]
    variables = [dict(subject=s, **{f: analysis[s][f] for f in FIELDS[1:]}) for s in subjects]
    summary = dict(counts=counts, gender_source_code_counts=dict(Counter(str(r["gender"]) for r in variables)),
                   gender_recode_applied=False, analysis_variables_centered=False,
                   screener_age_min=min(numeric(r["sub_age"]) for r in variables),
                   screener_age_max=max(numeric(r["sub_age"]) for r in variables), policy=POLICY)
    files = {
        "subjects.tsv": table([dict(subject=s) for s in subjects], ["subject"]),
        "analysis_variables.tsv": table(variables, ["subject", *FIELDS[1:]]),
        "selected_pairs.tsv": table(selected, strict_fields),
        "reconciliation.tsv": table(reconciliation, ["subject", "status", "existing_pair_group", "reason"]),
        "strict_pool_not_in_workbook.tsv": table([dict(subject=s, status="not_in_committed_linked_workbook")
                                                   for s in sorted(pool - set(analysis))], ["subject", "status"]),
        "summary.json": json_text(summary),
    }
    if any(digest(root / rel) != record["sha256"] for (_, rel, root), record in zip(paths, sources)):
        raise ValueError("Input changed during cohort generation")
    provenance = dict(schema_version=1, sources=sources,
                      repositories=dict(analysis="https://github.com/DVS-Lab/rf1-sra-environment-SD",
                                        preprocessing="https://github.com/DVS-Lab/rf1-sra-linux2"),
                      workbook_sheet="Data", workbook_range="A1:G111", policy=POLICY,
                      outputs={name: hashlib.sha256(text.encode()).hexdigest() for name, text in files.items()})
    files["provenance.json"] = json_text(provenance)
    return files, summary


def verify(output, files):
    actual = {p.name for p in output.iterdir() if p.is_file()}
    if actual != set(files) or any(p.is_dir() for p in output.iterdir()):
        raise ValueError("Frozen cohort artifact inventory differs")
    for name, expected in files.items():
        if (output / name).read_bytes() != expected.encode():
            raise ValueError("Frozen cohort content/provenance changed: " + name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "check"))
    parser.add_argument("--upstream", type=Path, default=Path(os.environ.get("RF1_SRA_UPSTREAM_ROOT", "/ZPOOL/data/projects/rf1-sra-linux2")))
    parser.add_argument("--output", type=Path, default=ROOT / "data/derived/katie-cohort-v1")
    args = parser.parse_args()
    output, upstream = args.output.resolve(), args.upstream.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with (output.parent / ("." + output.name + ".lock")).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        files, summary = generate(ROOT, upstream)
        if args.command == "build" and not output.exists():
            output.mkdir()
            for name, text in files.items():
                (output / name).write_bytes(text.encode())
        verify(output, files)
    print("CHECK PASSED: 97 frozen participants; 11 existing run-QC and 2 existing coverage exclusions reconciled.")
    print("No new exclusions, source changes, image processing, model design or randomise jobs.")
    print(json_text(summary))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAILED ({type(exc).__name__}): {exc}", file=sys.stderr)
        sys.exit(1)
