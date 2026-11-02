# Run the Remaining Katie Analyses

## What Runs

One scheduler caps all new work at **48 top-level workers**, with OMP/BLAS threads
set to one. It does not start independent 48-worker pools for each analysis.
The completed original 24 randomise jobs are never repeated.

| Additional branch | Randomise jobs | Directional maps |
|---|---:|---:|
| Conditional predictor main effects in the four interaction models | 16 | 64 |
| Group task activation: Social, Doors, paired mean, paired difference | 8 | 16 |
| VS-PPI: six original models x paired mean/difference x two CDTs | 24 | 48 |
| Total additional | 48 | 128 |

All use the same frozen 97 participants, both Z-equivalent CDTs (2.6, 3.1),
10,000 permutations, fixed seed and per-map cluster-FWE p<0.05. No PALM/TFCE,
new exclusions or extra family correction. FEVS/OAFEM await the current data join
and are not invented or silently added here.

## Domain-Agnostic Images and Covariates

For each participant, the existing verified average image is
`(Social COPE4 + Doors COPE4)/2`; COPE4 is outcome win-loss. There is exactly
one image per participant, in the frozen roster order. The paired mean uses
`(Social FD + Doors FD)/2` and the same arithmetic mean for tSNR, centered across
the 97 participants. Age, gender and scanner era remain single participant-level
values; they are not duplicated as independent task observations.

The group-mean design tests the intercept, with centered QC, two scanner-era
columns, gender and age (seven columns, residual df=90). Social/Doors use each
task's own FD/tSNR; the difference uses signed differences, and the average uses
pair means. No environmental exposure or interaction is included in this task
sanity-check design. The standalone task stacks are checked against the original
selected images. The paired mean/difference are reused from the validated first
batch without rewriting them. These group means are distinct from predictor
slopes tested in the environmental models.

We use randomise now, not a simultaneous FLAME branch. Randomise takes the
one-per-person effect stack, without requiring a newly fabricated L2 variance
map. A future FLAME alternative would need its own reviewed L2 COPE/VARCOPE and
DOF lineage; averaging COPEs alone is not that FLAME input contract.

The group-mean native smoke must explicitly report sign-flipping before any full
jobs start. The [FSL documentation](https://fsl.fmrib.ox.ac.uk/fsl/docs/statistics/randomise.html)
describes one image per subject for a one-sample test; its
[implementation](https://git.fmrib.ox.ac.uk/fsl/randomise/-/blob/2111.0/randomise.cc?ref_type=tags)
handles the contrast-specific effective regressor and reports sign-flipping.
No `-D` is used to remove the mean being tested. The df=90 CDT conversions were
independently checked against R: 2.6571978972124937 and 3.1938810245004920.

## Existing Connectivity Is Preserved, Not Blindly Mixed

All 194 historical VS-PPI units are checked for the same BOLD, exact nuisance
matrix content and task EVs as the selected no-TEDANA activation analyses.
The actual PPI contrast must be `ppi-win - ppi-loss` (not the seed main effect),
and design, seed and BOLD row counts must align. An existing candidate's VS
series must also match a fresh extraction with the current VS mask.

Compatible outputs are reused in place. Incompatible or missing outputs trigger
an isolated first-level PPI rebuild using a frozen copy of the existing task
code/template, the selected BOLD and exact base-only confounds. The existing
completed activation FEAT is referenced read-only, and all canonical outputs are
preserved. New FEAT outputs live in numbered attempt directories under this
analysis root. No `--overwrite`, anatomy, fMRIPrep, TEDANA, L1 activation or
production L2 reruns occur.

The pool initially runs 16 conditional + 8 activation randomise jobs and uses
remaining slots for PPI checks/rebuilds. Once all 194 PPI units verify, it builds
the paired mean/difference stacks in the same 97-person order, requires a native
smoke test, and queues the 24 PPI randomise jobs automatically. Its common mask
is the existing analysis support intersected with each PPI mask and positive
variance support; no participants are dropped. PPI group models reuse the exact
approved original design matrices, contrasts and paired QC covariates.

Thus there are 48 randomise jobs **total**, but not necessarily all runnable at
the first instant: connectivity may need valid matching first-level inputs.
The limit of 48 also includes any FSL first-level preparation jobs, so it is
not 48 randomise plus another 48 FEAT jobs. First-level FEAT has normal nested
helper processes; the bound is on top-level analysis units.

## Exact Linux2 Launch

```bash
(
set -euo pipefail
umask 0000
cd /ZPOOL/data/projects/rf1-sra-environment-SD
if pgrep -u "$USER" -af \
  '[r]un_katie_(all|overnight|main_effects)\.sh|[r]un_katie_(remaining|randomise|main_effects)\.py'; then
  echo "STOP: a Katie launcher/coordinator is already active; do not duplicate or update it."
  exit 1
fi
[[ -z "$(git status --porcelain)" ]] || {
  git status --short
  echo "STOP: preserve/publish local changes first; nothing discarded."
  exit 1
}
git remote set-url origin https://github.com/DVS-Lab/rf1-sra-environment-SD.git
git pull --ff-only origin main
bash code/prepare_katie_env.sh
STAMP=katie-all-$(date +%Y%m%d-%H%M%S)
mkdir -p logs/runs
LOG="$PWD/logs/runs/${STAMP}.nohup.out"
nohup setsid -f -w bash code/run_katie_all.sh --jobs 48 --label "$STAMP" > "$LOG" 2>&1 &
echo "LOG=$LOG"
sleep 10
tail -40 "$LOG"
)
```

The detached run survives disconnecting. Look for the group sign-flipping smoke
confirmation, then the 16+8 initial randomise jobs and PPI preparation entries.
`--prepare-only` freezes/checks inputs without launching FSL and is automatically
logged/published first. The full runtime record is published on completion or
failure, with numerical summaries of all successful branches. Manual publishing:

```bash
python3 /ZPOOL/data/projects/rf1-sra-linux2/code/publish_run_logs.py \
  --project /ZPOOL/data/projects/rf1-sra-linux2
```

## Monitor, Resume and Reports

```bash
cd /ZPOOL/data/projects/rf1-sra-environment-SD
LOG=$(ls -1t logs/runs/katie-all-*.nohup.out | head -1)
tail -40 "$LOG"
python3 -m json.tool derivatives/fsl/randomise/katie-remaining-v1/status.json
```

The status file is written after the smoke tests and first coordinator heartbeat.
Errors in one PPI unit prevent the connectivity group launch but do not destroy
successful activation/conditional branches. Stop/wait for all old workers before
resuming the same command. Receipted results are checked and reused; failed
attempts are preserved and retries get new numbered folders. Changed sources,
code or completed files stop rather than being reset. Separate inherited locks
also protect the original and standalone conditional coordinators.

Outputs:

- `derivatives/fsl/randomise/katie-remaining-v1/activation/`
- `derivatives/fsl/randomise/katie-remaining-v1/ppi-l1/` (compatible receipts or isolated new FEATs)
- `derivatives/fsl/randomise/katie-remaining-v1/connectivity/`
- Existing/new conditional branch: `derivatives/fsl/randomise/katie-main-effects-v1/`
- Text reports: `results/randomise/katie-remaining-v1/activation/`, `connectivity/`
  and `results/randomise/katie-main-effects-v1/`.

After completion, publish only these text reports through Git:

```bash
cd /ZPOOL/data/projects/rf1-sra-environment-SD
git add -- results/randomise/katie-remaining-v1 results/randomise/katie-main-effects-v1
git commit -m "Publish Katie task activation, conditional effects and VS PPI summaries" \
  -- results/randomise/katie-remaining-v1 results/randomise/katie-main-effects-v1
git push origin main
```

Local tests use synthetic NIfTI data and simulated randomise/FEAT execution;
they do not claim actual Linux2 results. They exercise all 48 additional job
receipts, the shared worker cap, separate PPI failures/recovery, original-file
preservation, correct contrast indices, arithmetic, thresholds and resume.
Actual FSL compatibility remains gated by native smoke tests and live lineage
checks. No NIfTI files, raw surveys or private linkage data are published.
