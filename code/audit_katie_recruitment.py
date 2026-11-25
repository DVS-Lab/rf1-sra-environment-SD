"""Verify the frozen imaging denominator and optionally compare an independently sourced historical roster."""
import argparse
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNS = Path("qc/paired_difference/socialdoors-v1/run_membership.tsv")
RUNS_SHA = "d045abe84e2cda92205e111e3f6f54bacd372658ee3dedd74b1e7ed62a63aba3"
OCT21 = "433d026e5f60ebceaecc24355b57f0e3d672390f"
ID_FIELDS = {"rf1_id", "subject", "participant_id", "subject_id"}


def subject(raw):
    match = re.fullmatch(r"(?:sub-)?([0-9]{5})", (raw or "").strip())
    if not match:
        raise ValueError("Expected a five-digit RF1 ID (with optional sub- prefix)")
    return match[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tsv(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def frozen(up):
    path = up / RUNS
    if digest(path) != RUNS_SHA:
        raise ValueError("Imaging roster hash differs from the Katie cohort freeze")
    rows = [r for r in tsv(path) if (r["task"],r["session"],r["run"]) == ("socialdoors","01","1")]
    all_rows = {subject(r["subject"]): r for r in rows}
    eligible = {s:r for s,r in all_rows.items() if r["frozen_status"]!="under_55"}
    counts = Counter(r["previous_selection_status"] for r in eligible.values())
    if len(rows)!=len(all_rows) or len(rows)!=352 or counts!={"eligible":137,"not_in_verified_plan":12,"exclude_below_95":2}:
        raise ValueError("Frozen baseline membership does not reproduce 352 / 151 / 139 / 137")
    return all_rows, eligible


def recruitment(path):
    if path.suffix.lower() not in (".csv",".tsv"):
        raise ValueError("Supply a CSV or TSV export of the original roster with an rf1_id header")
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter="," if path.suffix.lower()==".csv" else "\t")
        fields = reader.fieldnames or []
        ids = ID_FIELDS.intersection(fields)
        if len(fields)!=len(set(fields)) or len(ids)!=1:
            raise ValueError("Expected exactly one ID column (prefer rf1_id) and unique headers")
        key = ids.pop()
        result = {}
        for i,r in enumerate(reader,2):
            if None in r or any(v is None for v in r.values()):
                raise ValueError(f"Malformed roster row {i}")
            s = subject(r[key])
            if s in result:
                raise ValueError(f"Duplicate ID on row {i}; do not silently deduplicate the recruitment count")
            note, ref = (r.get(k,"").strip() for k in ("documented_disposition","evidence_ref"))
            if bool(note)!=bool(ref):
                raise ValueError(f"Row {i}: a disposition requires a source reference and vice versa")
            result[s] = (note,ref)
    if len(result)!=164:
        raise ValueError(f"Source contains {len(result)} unique IDs, not 164. Check its date, age definition, and eligibility rules.")
    return result


def live_ages(path):
    ages = {}
    for r in tsv(path):
        s = subject(r["participant_id"])
        if s in ages:
            raise ValueError("Duplicate ID in current BIDS participants.tsv")
        ages[s] = r["age"]
    known = {}
    for s, raw in ages.items():
        if raw.strip().lower() in {"", "n/a", "na", "nan"}:
            continue
        try:
            age = Decimal(raw)
        except InvalidOperation as exc:
            raise ValueError("Invalid age in current BIDS participants.tsv") from exc
        if not age.is_finite() or not 0 <= age <= 120:
            raise ValueError("Invalid age in current BIDS participants.tsv")
        known[s] = age
    return ages, {s for s,age in known.items() if age>=55}


def mismatch_rows(recruits, imaging, all_rows, excluded, ages, inventory, bids):
    for s in sorted(set(recruits) ^ set(imaging)):
        in_recruits = s in recruits
        note, ref = recruits.get(s,("",""))
        if not in_recruits:
            evidence = "imaging_only_check_recruitment_version_or_id"
        elif s in all_rows and all_rows[s]["frozen_status"]=="under_55":
            evidence = "under_55_in_frozen_imaging_age_filter"
        elif s in excluded:
            evidence = "listed_in_Oct21_source_exclusions"
        else:
            evidence = "not_in_frozen_imaging_table"
        baseline = bids / ("sub-"+s) / "ses-01"
        yield dict(rf1_id=s, difference="recruitment_only" if in_recruits else "imaging_only",
                   historical_evidence=evidence, oct21_source_exclusion=int(s in excluded),
                   oct15_inventory_status=inventory.get(s,"not_in_saved_inventory"),
                   current_bids_participant=int(s in ages) if ages is not None else "",
                   current_bids_age=ages.get(s,"") if ages is not None else "",
                   current_bids_ses01_directory=int(baseline.is_dir()) if bids.is_dir() else "",
                   documented_disposition=note,evidence_ref=ref)


def candidates(roots):
    # Names only. Never traverse scan trees, assume a spreadsheet's purpose, or open a screener.
    skip={".git","bids","sourcedata","derivatives","stimuli","work","logs","results",
          "node_modules","__pycache__","venv","envs",".heudiconv"}
    for root in roots:
        if not root.is_dir():
            continue
        for d,dirs,files in os.walk(root,onerror=lambda e: print(f"Search skipped an unreadable directory: {e.filename}",file=sys.stderr)):
            depth=len(Path(d).relative_to(root).parts)
            dirs[:]=[x for x in dirs if depth<4 and x.lower() not in skip and not x.startswith(".")]
            for name in sorted(files):
                p=Path(d)/name
                if (p.suffix.lower() in {".csv",".tsv",".txt",".xlsx",".xls"} and
                        re.search(r"recruit|enroll|roster|subject|participant|screener|older.adult|age.?55|164",p.stem,re.I)):
                    yield p


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream",type=Path,default=ROOT.parent/"rf1-sra-linux2")
    parser.add_argument("--roster",type=Path,help="Confirmed original 164-ID recruitment export, not a downstream roster")
    parser.add_argument("--source-note",help="Provenance: recruitment report/version, cutoff and age rule")
    parser.add_argument("--search-root",type=Path,action="append",default=[],
                        help="Optional bounded filename search; no directories are searched by default")
    args=parser.parse_args()
    all_rows,imaging=frozen(args.upstream)
    print("Frozen baseline: 151 age-eligible; 12 without a usable Social Doors run; 2 failed the original coverage rule; 137 selected.")
    bids=args.upstream/"bids"
    live=bids/"participants.tsv"
    ages=None
    if live.is_file():
        ages, live_pool=live_ages(live)
        print("Date/age check only (NOT a recruitment roster): "
              f"current BIDS age >=55: {len(live_pool)}; current only: {len(live_pool-imaging.keys())}; "
              f"frozen only: {len(imaging.keys()-live_pool)}.")
    else:
        print("Current BIDS participants.tsv unavailable; live age comparison not performed.")
    if not args.roster:
        if args.search_root:
            print("Candidate filenames only; no file is treated as a recruitment roster:")
            for p in sorted(set(candidates(args.search_root))):
                print(p)
        print("Verified baseline imaging flow: 151 -> 139 -> 137. No recruitment comparison performed; "
              "the difference from the historical figure of 164 is not an exclusion count.")
        return
    if not (args.source_note or "").strip():
        raise ValueError("Provide --source-note identifying the authority, cutoff and age rule for this roster")
    recruits=recruitment(args.roster)
    prov=json.loads(subprocess.check_output(["git","-C",str(args.upstream),"show",OCT21+":qc/provenance.json"]))
    excluded={subject(s) for s in prov["inventory"]["source_excluded_subjects"]}
    old=args.upstream/"work/participants-coverage-20261015-131536/inventory.json"
    inventory={subject(r["subject"]):r["status"] for r in json.loads(old.read_text())["subjects"]} if old.is_file() else {}
    rows=list(mismatch_rows(recruits,imaging,all_rows,excluded,ages,inventory,bids))
    overlap=len(recruits.keys() & imaging.keys())
    summary=dict(recruited=len(recruits),imaging=len(imaging),intersection=overlap,
                 recruitment_only=len(recruits)-overlap,imaging_only=len(imaging)-overlap,
                 historical_evidence=dict(Counter(r["historical_evidence"] for r in rows)),
                 with_supplied_disposition_reference=sum(bool(r["evidence_ref"]) for r in rows),
                 optional_oct15_inventory_available=old.is_file(),live_bids_age_table_available=ages is not None)
    work=ROOT/"work"; work.mkdir(exist_ok=True)
    output=Path(tempfile.mkdtemp(prefix="recruitment-flow-",dir=work))
    with (output/"discrepancies.tsv").open("w",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]),delimiter="\t",lineterminator="\n")
        writer.writeheader();writer.writerows(rows)
    (output/"provenance.json").write_text(json.dumps(dict(roster_sha256=digest(args.roster),roster=str(args.roster.resolve()),
        source_note=args.source_note,run_table_sha256=RUNS_SHA,source_exclusion_commit=OCT21,
        live_participants_sha256=digest(live) if ages is not None else None,inventory_sha256=digest(old) if old.is_file() else None),indent=2)+"\n")
    print(json.dumps(summary,indent=2))
    (output/"counts.json").write_text(json.dumps(summary,indent=2)+"\n")
    print(f"Private ID-level review: {output/'discrepancies.tsv'}")
    print("Compare source records for unexplained IDs. Live file absence is not evidence of withdrawal or no scan.")


if __name__=="__main__":
    try:
        main()
    except (OSError,ValueError,KeyError,subprocess.CalledProcessError) as exc:
        sys.exit("STOP: "+str(exc))
