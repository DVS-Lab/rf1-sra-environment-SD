# Behavioral Moderation: FEVS Primary, OAFEM Secondary

## Scope And Current Scoring Status

This is a bounded new exploratory behavioral analysis of the **same frozen
97-person cohort**, not another whole-brain search. It changes no imaging
inputs, neural results, masks, settled exclusions or participant selection.
It is specified after the neural analyses and is not represented as preregistered.

Both exported financial totals are complete, finite, nonnegative and uniquely
linked to all 97 IDs. That establishes numerical completeness, **not validated
item scoring**. The supplied CSV does not document questionnaire versions,
item keys, missing-item handling or source timepoints. Observed score ranges
(FEVS 0-17, OAFEM 0-78) are not asserted to be the instruments' possible ranges.

The user explicitly authorized running **provisionally on those exports**, with
item scoring to be verified afterward. The approved MSPSS column includes zero
values; they are retained as supplied, neither declared missing nor silently
recoded. Their validity needs the source coding rule. "Nothing should be missing"
is not treated as an item-level scoring verification.

Every provisional report, manifest and log carries the unresolved scoring
status. If an actual item specification is supplied and reveals a discrepancy,
the runner stops even in provisional mode. Provisional authorization never
overrides a known failed item-to-total comparison.

## Frozen Model Family

Each model is:

```text
financial outcome ~ exposure + moderator + exposure:moderator + age + gender_code1
```

| Outcome | Exposure | Moderator | Family |
| --- | --- | --- | --- |
| FEVS | ADI | MSPSS | Primary |
| FEVS | PM2.5 | MSPSS | Primary |
| FEVS | ADI | Ecog | Secondary |
| FEVS | PM2.5 | Ecog | Secondary |
| OAFEM | ADI | MSPSS | Secondary |
| OAFEM | PM2.5 | MSPSS | Secondary |
| OAFEM | ADI | Ecog | Secondary |
| OAFEM | PM2.5 | Ecog | Secondary |

ADI and PM2.5 are tested separately, as are the moderators. There is no joint
all-variable model, three-way term, imaging FD/tSNR adjustment, scanner-era
adjustment, new age filter, outcome transformation or imputation. Source
gender_code1 remains the approved 0/1 indicator; no new gender interpretation
or recoding is inferred here. Age uses the existing approved screener-derived
covariate, not a newly invented scan-age reference.

Continuous exposure, moderator and age are mean-centered in original units;
the interaction is the product of the centered exposure and moderator. All
eight models have 97 rows, six full-rank columns and 91 residual df.

Inference is OLS with **HC3 covariance, two-sided t tests and 95% intervals**.
All coefficients and all eight interaction results are reported. Raw HC3 p
values are primary numerical outputs; within-family Holm p values are also
shown for transparency (two primary interactions; six secondary interactions).
These adjustments do not trigger participant exclusions or select models for
reporting. No further brain analyses are launched.

Report influence diagnostics and single-case leave-one-out interaction ranges;
retain every participant. OAFEM's floor/right tail is described, not used to
choose an unplanned transform or remove observations. Conditional exposure-slope
curves span observed moderator values with **pointwise**, not simultaneous,
HC3 intervals. They do not establish causality, mediation or prospective risk.
FEVS financial/relational distress content overlaps conceptually with the
contextual predictors; avoid claiming an entirely independent endpoint.

## Exact Linux2 Launch

Paste the complete block below on Linux2. It fetches over HTTPS, extracts a
frozen reporting release into ignored `work/`, and uses the existing analysis
Python plus the existing pinned review environment. The live checkout and
completed neural releases are not pulled, switched or overwritten.

```bash
(
set -euo pipefail
umask 0000
cd /ZPOOL/data/projects/rf1-sra-environment-SD
git -c remote.origin.url=https://github.com/DVS-Lab/rf1-sra-environment-SD.git fetch origin main
bash <(git show FETCH_HEAD:code/launch_behavioral_moderation.sh) --provisional
)
```

The detached nohup/setsid worker automatically:

1. Checks all 97 IDs, exported totals and aligned approved covariates; records
   unresolved item scoring and the count of retained MSPSS zero values.
2. Reuses/prepares the pinned review environment without altering the base
   environment. This setup may take longer than the regressions themselves.
3. Fits the eight models serially, generates all results and two four-panel
   conditional-slope figures, and validates the sealed outputs/source hashes.
4. Publishes only aggregate tables/plots and the explicitly provisional README
   through an isolated HTTPS Git clone. No participant-level diagnostics,
   raw questionnaire items or private scoring source files are published.
5. Automatically publishes all new run records to `rf1-sra-linux2` on exit,
   including failures. No SSH, SCP or rsync is involved.

Only one worker can hold this batch's lock. Repeating the launch reuses
identical validated outputs; incompatible inputs/runtime versions stop rather
than overwrite the completed report. Eight small regressions do not need a
large `--jobs` value or any randomise workers.

## Status And Publication

Run this exact block to inspect the detached worker and latest log:

```bash
(
set -euo pipefail
cd /ZPOOL/data/projects/rf1-sra-environment-SD
echo '=== Behavioral worker ==='
pgrep -u "$USER" -af '[r]un_behavioral_moderation.py|[l]aunch_behavioral_moderation.sh --worker' || true
echo '=== Latest behavioral log ==='
LOG=$(find logs/runs -maxdepth 1 -name 'katie-behavioral-provisional-*.nohup.out' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)
if [[ -n "$LOG" ]]; then tail -50 "$LOG"; else echo 'No behavioral launch log found'; fi
python3 /ZPOOL/data/projects/rf1-sra-linux2/code/publish_run_logs.py --project /ZPOOL/data/projects/rf1-sra-linux2
)
```

Private/local workspace:

```text
/ZPOOL/data/projects/rf1-sra-environment-SD/work/behavioral-moderation-provisional-v1/
```

The `report/` subdirectory contains aggregate outputs. `scoring-status.json`,
`provenance-private.json`, `influence-private.tsv` and any `error-private.txt`
stay outside the published payload. The launcher respects **umask 0000**; the
word private here denotes publication scope, not restrictive lab permissions.

Published report after successful completion:

```text
https://github.com/DVS-Lab/rf1-sra-environment-SD/blob/main/results/review/behavioral-moderation-provisional-v1/README.md
```

The publisher leaves Linux2's branch/index unchanged, so do not follow it with
`git add .` or a blind pull merely to synchronize these run records.

## Scoring Closeout Tomorrow

Obtain the administered FEVS/OAFEM versions, raw item export(s), RF1 ID field,
event/visit linkage, authoritative scoring key, reverse coding, missing-item
rules and confirmation of the source timepoints. Also obtain the MSPSS
range/coding rule and explain the retained zero values. No participant is
removed while that is investigated.

The runner writes a deliberately incomplete `scoring-spec.template.json` into
the workspace. A real specification must identify each instrument version,
source reference, timepoint, absolute raw CSV/TSV path, ID field, explicit
record filters, item count and each raw-response-to-points mapping. Financial
directions must be `higher_more_vulnerability` for FEVS and
`higher_more_reported_exploitation` for OAFEM. No item keys are guessed from
column names or observed totals. The template is not an attestation to approve.

Strict mode supports documented complete-item sums, compares every recomputed
total against the exported value, rejects duplicate records or missing/unmapped
items, and never selects the first repeat or treats blanks as zero. Other
legitimate missing-item/scoring rules need an explicit code update, not a
fabricated key to make the check pass.

Do not silently relabel the provisional result as verified. A documented
scoring closeout and a separately versioned verified run should follow. If
scores change, preserve the provisional and completed neural outputs, then
assess which score-dependent analyses require a separate update. No automatic
neural rerun or exclusion change is part of this runner.
