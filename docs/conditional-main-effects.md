# Katie Conditional Main-Effect Follow-Up

## Original Results Stay Final

The original 24 jobs / 48 maps passed all checks. No map had a cluster with
per-map cluster-FWE p<0.05 at either requested CDT. The smallest corrected p was
0.1114 (negative ADI association with the social-specific outcome, CDT Z=2.6).
For the average outcome, the smallest was 0.1232 (negative ADI x Ecog
interaction, CDT Z=3.1). These are not significant findings or evidence of
absence. See [all original results](../results/randomise/katie-v1/README.md).

This separate follow-up completes the constituent main-effect contrasts already
discussed before inspecting the numerical results. It does not change the
analysis thresholds, outcomes or sample in response to the null results.

## Additional Tests

There are **16 additional jobs**: four interaction designs x two outcomes x two
CDTs. Each has four contrasts, in this exact order:

1. Exposure positive (ADI or PM2.5).
2. Exposure negative.
3. Moderator positive (MSPSS or Ecog).
4. Moderator negative.

Total: **64 additional directional corrected maps**. The contrast's term,
direction and output index are recorded in `contrasts.tsv` beside each new
`design.con`. For example, the ADI x MSPSS columns remain:

```text
intercept QC_FD QC_tSNR E11 XA30 gender age ADI MSPSS ADIxMSPSS
```

The four new rows are:

```text
0 0 0 0 0 0 0  1  0 0
0 0 0 0 0 0 0 -1  0 0
0 0 0 0 0 0 0  0  1 0
0 0 0 0 0 0 0  0 -1 0
```

The interaction column is still in the unchanged original design. The exposure
effect is conditional on the moderator being at its centered reference value,
and vice versa. These are not substitutes for the standalone ADI/PM2.5 models.
No intercept/group-average activation test is added in this batch.

N=97, volume/row order, original matrices, images, common mask, paired-QC choices,
10,000 permutations, seed and model-specific Z-equivalent CDTs are reused.
No PALM/TFCE or new cross-analysis correction is introduced. Each map is
cluster-FWE corrected; the larger exploratory family is not jointly corrected.

## Preservation and Validation

The original Python runner and configuration are fingerprint-frozen and are not
edited. A separate runner verifies the completed original batch and writes only
new contrasts, plans, numbered attempts and reports. Original image/design paths
are referenced directly, with hashes; no image or matrix is rebuilt or copied.
The shell launcher first requires a read-only audit of all 194 actual L1 FSFs,
contrast matrices and win/loss EV files against canonical BIDS timing. A failure
stops before any new inference. See [outcome and survey checks](outcome-and-financial-measures.md).
All four contrasts must pass a real two-permutation FSL smoke test before the
16 full jobs start. Completion requires all eight image products per job
(four t maps and four corrected maps), with geometry, finite-value and receipt
checks. Completed new attempts are reused; partial attempts are preserved.
A separate lock, inherited by workers, prevents duplicate coordinators.

## Exact Linux2 Launch

```bash
(
set -euo pipefail
umask 0000
cd /ZPOOL/data/projects/rf1-sra-environment-SD
if pgrep -u "$USER" -af \
  '[r]un_katie_(overnight|main_effects)\.sh|[r]un_katie_(randomise|main_effects)\.py (build|check|run)( |$)'; then
  echo "STOP: Katie processing is already active."
  exit 1
fi
[[ -z "$(git status --porcelain)" ]] || {
  git status --short
  echo "STOP: preserve local changes before updating."
  exit 1
}
git remote set-url origin https://github.com/DVS-Lab/rf1-sra-environment-SD.git
git pull --ff-only origin main
bash code/prepare_katie_env.sh

STAMP=katie-main-effects-$(date +%Y%m%d-%H%M%S)
mkdir -p logs/runs
LOG="$PWD/logs/runs/${STAMP}.nohup.out"
nohup setsid -f -w bash code/run_katie_main_effects.sh \
  --jobs 16 --label "$STAMP" > "$LOG" 2>&1 &
echo "LOG=$LOG"
sleep 10
tail -40 "$LOG"
)
```

All 16 jobs run concurrently, single-threaded. Look for `SMOKE PASSED` and
`STAGE RANDOMISE MAIN EFFECTS: 16 jobs`. The detached launcher survives closing
SSH/the terminal; it uses no SSH Git remote or SCP/rsync. Do not pull/update this
checkout while processing is active.

The launcher publishes run records after the input check and on completion or
failure. The final log includes all 64 numerical summaries, including null maps,
so they can be reviewed from Git even before publishing the report tables.
Manual publishing remains:

```bash
python3 /ZPOOL/data/projects/rf1-sra-linux2/code/publish_run_logs.py \
  --project /ZPOOL/data/projects/rf1-sra-linux2
```

Analysis output is `derivatives/fsl/randomise/katie-main-effects-v1/`;
the group-only report is `results/randomise/katie-main-effects-v1/`.
After completion, publish just those text tables through Git:

```bash
cd /ZPOOL/data/projects/rf1-sra-environment-SD
git add -- results/randomise/katie-main-effects-v1
git commit -m "Publish verified Katie conditional main-effect results" -- results/randomise/katie-main-effects-v1
git push origin main
```

To resume after a stop, wait for existing workers to exit, then rerun the launch
block. Generated untracked summary files after a completed run should be
published first; do not discard them to satisfy the clean-checkout guard.
