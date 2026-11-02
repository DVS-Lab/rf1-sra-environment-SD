# Katie's Frozen Paired Cohort

The canonical cohort is owned by **this analysis repository**:

```text
data/derived/katie-cohort-v1/subjects.tsv
```

It contains one `subject` column, 97 unique IDs, sorted in ascending RF1-ID order.
Use this exact file with the preprocessing repository's `--cohort` option. Do not
maintain a second hand-edited roster or assume that the older upstream
`docs/paper-handoff/cohorts/katie-final.tsv` placeholder has been populated.

## Frozen Selection

The unchanged 110-person, seven-column linked workbook is intersected with the
existing 121-person, age-55+, session-01 strict paired imaging pool. Both tasks
must already pass source validity, coverage >=95%, and the existing task/session
FD/tSNR fences. No thresholds, age rules, or source decisions are recomputed.
The screener age is retained as an analysis variable, not used to reapply a
different age selection to the approved imaging roster.

| Quantity | Participants |
| --- | ---: |
| Committed linked workbook | 110 |
| Existing strict paired imaging pool | 121 |
| Frozen intersection | **97** |
| Workbook participants outside the strict pool: existing FD/tSNR flags | 11 |
| Workbook participants outside the strict pool: existing Doors coverage failure | 2 |
| Strict-pool participants not in this committed linked workbook | 24 |

The 24 are labeled only as not present in this workbook; no new reason or
exclusion is inferred. The 13 not retained from the workbook preserve existing
upstream decisions. No TEDANA-count, contrast-effect, or difference-outlier
exclusion is introduced. No imaging, survey or linkage source is modified.

## Files and Provenance

All files are under `data/derived/katie-cohort-v1/`:

- `subjects.tsv`: the sole canonical ordered ID-only roster.
- `analysis_variables.tsv`: the seven approved analysis fields in that order,
  with `rf1_id` renamed `subject`. Values and source gender codes are unchanged;
  no recoding, centering, model selection or statistical inference is performed.
- `selected_pairs.tsv`: the exact four matched upstream L1 contrast rows for
  each retained participant (388 rows), in subject then contrast order.
- `reconciliation.tsv`: all 110 workbook IDs and their existing selection status
  and reasons. This is not a new exclusion decision table.
- `strict_pool_not_in_workbook.tsv`: the 24 remaining strict imaging IDs.
- `summary.json`: independently reproduced counts and raw-code summaries.
- `provenance.json`: SHA256 of the workbook, all four upstream selection/evidence
  tables, this freeze script, and every generated output. Source-data file commits
  are recorded; paths are repository-relative so checks are portable.

`freeze_katie_cohort.py check` regenerates expected bytes from the exact live
sources and compares every file and its hashes. It also verifies that the strict
list is exactly the diagnostic's strict subset and agrees with source/run holds
and numeric task/session fences. Unknown decisions, duplicate IDs/contrasts,
changed inputs, missing values, or changed outputs fail instead of silently
altering the cohort. Re-running build on an existing directory verifies it; it
does not replace it.

The committed `SD_analysis_data_2026-10-26.xlsx` workbook remains unchanged.
Existing code assumes gender 0=male and 1=female, but these raw codes are preserved
here. Any model coding must be documented separately, using the source codebook.

## Linux2 Verification

After other jobs using these tracked checkouts have stopped, synchronize both
repositories through Git. These commands assume the analysis clone already exists
at the path shown, as used by the project:

```bash
(
set -euo pipefail
umask 0000
cd /ZPOOL/data/projects/rf1-sra-linux2
git fetch origin
python3 code/sync_published_checkout.py --project "$PWD" --apply --processing-stopped

cd /ZPOOL/data/projects/rf1-sra-environment-SD
git pull --ff-only origin main
python3 -c 'import sys, openpyxl; assert sys.version_info >= (3, 11), "Python >=3.11 required"'
STAMP=katie-cohort-check-$(date +%Y%m%d-%H%M%S)
STATUS=0
bash ../rf1-sra-linux2/code/run_logged.sh \
  --label "$STAMP" --include-full-log -- \
  python3 code/freeze_katie_cohort.py check \
    --upstream /ZPOOL/data/projects/rf1-sra-linux2 || STATUS=$?
python3 ../rf1-sra-linux2/code/publish_run_logs.py \
  --project /ZPOOL/data/projects/rf1-sra-linux2
exit "$STATUS"
)
```

This verifies tables only. It does not run randomise or validate unavailable
images on this Mac. Missing Python packages are environment issues, not exclusions.

## Later: Assemble the 97-Person Image Bundle

The original 121-person pool is already validated and must stay untouched.
Its 4D stacks and centered covariates cannot simply be reused unchanged for N=97.
The supported upstream builder reuses existing checked diagnostic maps, subsets
in this roster's order, recomputes the common masks, and recenters paired QC
covariates. It does not rerun preprocessing, L1, MRIQC, or TEDANA.

After the cohort check above succeeds, this optional input-assembly step is
independent of choosing model formulas. It **does not launch randomise**:

```bash
(
set -euo pipefail
umask 0000
cd /ZPOOL/data/projects/rf1-sra-environment-SD
AUDIT_PYTHON=/ZPOOL/data/tools/anaconda/tug87422/envs/tedana-26.0.3/bin/python
UPSTREAM=/ZPOOL/data/projects/rf1-sra-linux2
OUTPUT="$UPSTREAM/work/randomise-katie-final-v1"
COHORT="$PWD/data/derived/katie-cohort-v1/subjects.tsv"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
python3 code/freeze_katie_cohort.py check --upstream "$UPSTREAM"
STAMP=katie-final-bundle-$(date +%Y%m%d-%H%M%S)
STATUS=0
bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP" --include-full-log -- \
  env PYTHONUNBUFFERED=1 "$AUDIT_PYTHON" "$UPSTREAM/code/build_socialdoors_randomise.py" build \
    --cohort "$COHORT" --output "$OUTPUT" \
  --check env PYTHONUNBUFFERED=1 "$AUDIT_PYTHON" "$UPSTREAM/code/build_socialdoors_randomise.py" check \
    --output "$OUTPUT" || STATUS=$?
python3 "$UPSTREAM/code/publish_run_logs.py" --project "$UPSTREAM"
exit "$STATUS"
)
```

Output: `/ZPOOL/data/projects/rf1-sra-linux2/work/randomise-katie-final-v1/`.
This subset's image validation remains **pending Linux2 execution**. Do not
claim it passed on the basis of the table freeze alone. A pre-existing bundle
with a different cohort or configuration must not be overwritten.

Use Git for the shareable roster, tables, documentation and validation logs.
No SCP/rsync or raw/private survey export is needed.
