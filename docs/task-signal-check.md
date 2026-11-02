# Task Activation Is Not an Environmental Main Effect

## Current Status

- Completed: 24 original randomise jobs testing standalone ADI/PM2.5 slopes and
  four interactions for the two outcomes. No cluster-FWE p<0.05 finding in 48 maps.
- Prepared, not established as running: 16 conditional predictor main-effect
  jobs. These are not tests of the group-average neural response.
- Not yet run in this N=97 workflow: group-intercept/one-sample win>loss maps.
  The absence of environmental associations says nothing about whether mean
  ventral-striatal win>loss activation is present.
- Not yet analyzed in this workflow: N=97 VS-seeded task-modulated connectivity.
  The existing task repository has `masks/seed-VS.nii.gz` and seed-PPI templates,
  but mask presence does not prove all participants have compatible PPI outputs.

The locally inspected VS mask has 114 binary voxels on the 57x70x54 MNI grid
(2.7x2.7x2.97 mm); it is compatible with the canonical grid. The actual Linux2
mask and its overlap with the frozen common-support mask must be checked live.
In the PPI template, contrast 4 is `ppi-win - ppi-loss` (columns 6 minus 7),
whereas contrast 5 is the physiological/seed regressor. These must not be confused.
Historical TEDANA-confound PPI must not be mixed into the current base-only
activation variant simply because both have a VS seed filename.

## Initial Timing-Audit Failure

The first audit log (`20261102-080804_katie-outcome-audit-20261102-080804.md`)
stopped with an onset/duration/amplitude comparison error. It did not identify a
wrong COPE weight or establish a faulty L1 model. Code inspection reproduced a
specific explanation for small timing residuals: `BIDSto3col.sh` uses
`awk printf("%s", onset-0)`, which converts numeric onsets using six significant
digits by default. For example, 325.123456789 becomes 325.123 seconds. The
initial 0.00001-second comparison was too strict for that conversion.

The new audit accepts that exact documented transformation, not a broad timing
shift, and retains strict duration/amplitude checks. It prints residuals and
reports all failing runs. Whether this fully explains the actual Linux2 mismatch
remains to be established from the revised report. No L1, EV or BIDS file is
rewritten. v1 results are preserved; v2 has a separate report directory.

## One Read-Only Diagnostic Block

```bash
(
set -euo pipefail
umask 0000
cd /ZPOOL/data/projects/rf1-sra-environment-SD
if pgrep -u "$USER" -af \
  '[r]un_katie_(overnight|main_effects)\.sh|[r]un_katie_(randomise|main_effects)\.py (build|check|run)( |$)|[a]udit_katie_outcome\.py|[i]nspect_katie_activation\.py'; then
  echo "STOP: a Katie process is active; wait before updating code."
  exit 1
fi
git remote set-url origin https://github.com/DVS-Lab/rf1-sra-environment-SD.git
git pull --ff-only origin main
bash code/check_katie_task_signal.sh
)
```

The shell helper runs two logged checks, publishes the run records using
`publish_run_logs.py`, then commits and pushes only its generated diagnostic text
tables through HTTPS. No imaging data, existing results or exclusions are changed.
It runs the descriptive/inventory step even if the independent timing audit
fails, so that useful diagnostics are still collected. A nonzero final exit must
be reviewed; no further inference is launched automatically.

Reports:

- `results/validation/outcome-phase-v2/`: all 194 actual L1 contrast/EV checks,
  per-condition timing residuals, and any remaining mismatches.
- `results/validation/activation-connectivity-v1/vs_roi_descriptive.tsv`: ROI-mean
  COPE summaries for Social win-loss, Doors win-loss, their average and their
  difference, all using the same 97 people and same common-support VS voxels.
- `results/validation/activation-connectivity-v1/ppi_inventory.tsv`: bounded
  candidate search in `fsl` and `fsl-no-tedana-age55`, not a blind recursive scan.

The VS summary reports mean, SD, SE, positive-participant count and a descriptive
one-sample t statistic. It has **no corrected p-values** and is not a claim of
significant activation. A positive ROI mean alone is not a whole-brain result.
The PPI table distinguishes explicit ses-01 from unverified legacy sessions and
reports file presence only, not source, confound or PPI-model validation. Missing
files in the scanned roots do not mean the participant lacks a seed everywhere.

After semantic validation passes, the task sanity-check inference should be a
separate group-intercept batch for Social win-loss, Doors win-loss, their average
and difference at the existing two CDTs (eight jobs, both directions). These
would check task responses, not revise the null environmental results. They are
not launched by this diagnostic helper. VS PPI reuse additionally requires
confirming both tasks' seed/model/confound lineage before building group inputs.
