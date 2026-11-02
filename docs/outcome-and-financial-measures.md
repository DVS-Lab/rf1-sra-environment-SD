# Outcome Phase and Financial Measures

## What the Existing Outcomes Mean

The Social Doors and Doors activation templates define four task EVs in order:
`win`, `loss`, `decision`, `miss`. COPE 4 is `win-loss`, with weights
`1 -1 0 0`. The task source `stimuli/Scan-Social_Doors/social_doors.py` labels
win/loss as feedback-screen events and writes `feedback_onset` and
`feedback_dur` to their BIDS onset/duration fields. Decision events instead use
`decision_onset` and `decision_dur`. The canonical converter retains those
Social Doors event labels/timings, and the 3-column converter splits by
`trial_type` without an onset shift in the standard invocation.

Thus the intended primary image is the **outcome-valence difference**
`(Social win-loss) - (Doors win-loss)`. The secondary image is
`((Social win-loss) + (Doors win-loss))/2`. This is not a decision-phase effect,
nor is the secondary image all outcomes versus baseline.

Source/template inspection establishes the intended semantics. To verify the
actual finished files rather than just their labels, `audit_katie_outcome.py`
checks each of the 97 participants' two selected L1 runs (194 total):

- The selected image is that run's `stats/cope4.nii.gz`.
- Actual `design.fsf` identifies win/loss in the expected columns, with no
  temporal-derivative expansion and COPE-4 weights `1 -1 0 0`.
- Actual `design.con` row 4 has those two weights, with zero on decision,
  missed-decision and any additional nuisance columns.
- Actual win/loss EV files match canonical BIDS win/loss onset, duration and
  amplitude directly or with the converter's specific documented awk `%.6g`
  numeric onset formatting. Durations and amplitudes must still match; arbitrary
  offsets or a generally wider timing tolerance are not accepted.
- The frozen original analysis inputs and order remain unchanged.

This is a read-only semantic/timing audit, not an L1 or randomise rerun. It does
not establish psychological specificity or reconstruct unrecorded acquisition
facts. Unexpected differences are reported, not repaired automatically.

## Run Only the Outcome Audit First

```bash
(
set -euo pipefail
umask 0000
cd /ZPOOL/data/projects/rf1-sra-environment-SD
if pgrep -u "$USER" -af \
  '[r]un_katie_(overnight|main_effects)\.sh|[r]un_katie_(randomise|main_effects)\.py (build|check|run)( |$)'; then
  echo "STOP: Katie processing is active; do not update its checkout."
  exit 1
fi
git remote set-url origin https://github.com/DVS-Lab/rf1-sra-environment-SD.git
git pull --ff-only origin main
STAMP=katie-outcome-audit-$(date +%Y%m%d-%H%M%S)
STATUS=0
bash /ZPOOL/data/projects/rf1-sra-linux2/code/run_logged.sh \
  --label "$STAMP" --include-full-log -- \
  "$PWD/work/venv-katie/bin/python" code/audit_katie_outcome.py \
  || STATUS=$?
python3 /ZPOOL/data/projects/rf1-sra-linux2/code/publish_run_logs.py \
  --project /ZPOOL/data/projects/rf1-sra-linux2
exit "$STATUS"
)
```

The report is `results/validation/outcome-phase-v2/`. No study files are changed.
The separate main-effect launcher automatically requires this same audit before
starting any of its new inference. Hold further launches until this passes.
The initial v1 audit used a too-strict onset comparison and stopped on Linux2;
the revised audit reproduces the existing converter's numeric transform and
records actual onset/duration residuals. It checks all 194 runs and publishes
all genuine mismatches rather than stopping at the first one. This does not
alter the converter or any timing/model file. See [task-signal checks](task-signal-check.md).

## FEVS and OAFEM: Available Historically, Current Join Still Needed

The current approved 97-person analysis workbook intentionally contains seven
fields: RF1 ID, age, gender, Ecog, MSPSS, ADI and PM2.5. It does not contain FEVS
or OAFEM, and neither is in the completed model matrices.

The historical task repository has `code/rf1_covariates_2024_09_09.csv` with
`fevs_sum` and `oafem_total`. Read-only matching by `sub_id_rf1_data` against the
current frozen roster found:

| Historical snapshot | Current IDs matched | Finite FEVS | Finite OAFEM |
|---|---|---|---|
| September 9, 2024 | 13/97 | 13/97 | 12/97 |
| April 2, 2024 | 5/97 | 5/97 | 5/97 |

There were no duplicate matched IDs in those snapshots. These counts describe
old exports, not current survey availability: absence from a 2024 snapshot must
not become a new exclusion. The historical CSVs contain additional private
fields; do not copy or republish them into this environment repository.

Jacob's concrete next step is to join the **current** linked survey exports to
`data/derived/katie-cohort-v1/subjects.tsv` and deliver a separate table with all
97 RF1 IDs in that order, `fevs_sum` and `oafem_total`. Preserve missing values;
do not replace them with zero, silently choose between conflicting records, or
drop anyone. Supply counts available for each score and jointly, plus unresolved
duplicates and the scoring/missing-item policy and chosen source wave/timepoint.
Measurement dates/provenance can stay in the authorized private audit.

The original seven-column workbook and settled imaging cohort remain unchanged.
Whether these scores enter as predictors or moderators, and whether a separate
complete-case supplemental sample is needed, should be specified after current
coverage and score definitions are confirmed. No FEVS/OAFEM models have launched.
