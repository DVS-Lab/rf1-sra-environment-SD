# Corrected MSPSS Randomise Refits

## Question And Scope

Does correcting the Island screener MSPSS coding change the previous support-related neural associations?
Use the corrected `mspss_sum` means from Ryan's revised November 5 export, not the prescan retest,
an average of administrations, or a selected subscale. The same 97 participants remain in the same order.
The minimal frozen table in `data/derived/mspss-correction-v1/` contains only their IDs and corrected means.
The full 351-person export and administration dates are not published. Eighty-two cohort means change;
15 remain unchanged. Changes are participant-specific, so these are not equivalent to adding one constant
to every centered score. These refits replace uncorrected-MSPSS inference, not the historical files.

The corrected means were supplied by the acquisition team; this does not claim an independent item-level
rescore. Selected screener records are preserved, including repeat screeners after the scan. This timing
caveat is not a new exclusion or a reason to substitute the prescan administration.
FEVS/OAFEM totals remain unchanged; their separate item-scoring validation is not resolved by this correction.

## What Runs

- Four models: ADI x MSPSS, PM2.5 x MSPSS, FEVS x MSPSS, OAFEM x MSPSS.
- Activation and original VS-seeded PPI connectivity.
- Four outcomes: `(Social win-loss) - (Doors win-loss)`, the mean of the two win-loss contrasts,
  `Social win - Doors win`, and `Social loss - Doors loss`.
- Two cluster-forming thresholds, Z-equivalent 2.6 and 3.1 converted to t with residual df=87.
- Each job tests both directions of both main coefficients and the two-way interaction: six maps/job.

Total: **64 jobs, 384 directional maps**. Ten thousand permutations, seed 20261101, cluster extent;
no TFCE, PALM, three-way terms, or new models. Cluster-FWE remains per map, not across this exploratory
family of outcomes, signs, models and CDTs. All results, including nulls, are reported.

Only the centered MSPSS column and its product interaction change. Every other numeric design column
is required to match the original exactly. Hashes verify original images, masks, participant order,
covariates and the source-plan lineage, including retained fits outside the 220-job extension.
Legacy source records without a size field retain their original SHA when normalized.

Unaffected: non-MSPSS fits, task-mean activation maps, FEVS additive ADI/Ecog checks, preprocessing,
settled exclusions, and completed TEDANA. Behavioral models are not launched by this command.

## Exact Linux2 Launch

Paste this entire block into Linux2. It does not require a pull, SSH, SCP, a new environment,
or manual copying of the CSV. It archives fetched code/data into an ignored frozen release.

```bash
(
set -euo pipefail
umask 0000
cd /ZPOOL/data/projects/rf1-sra-environment-SD
git -c remote.origin.url=https://github.com/DVS-Lab/rf1-sra-environment-SD.git fetch origin main
bash <(git show FETCH_HEAD:code/launch_corrected_mspss.sh) --jobs 75
)
```

This is detached with `nohup`/`setsid`, using the existing `work/venv-katie/bin/python` without modifying
that environment. Each worker receives single-threaded BLAS/OpenMP settings. A worker limit of 75
allows all **64** actual jobs concurrently after the two short native smoke tests; there are not 75
distinct jobs. Values 1 through 80 are accepted. CPU count alone does not guarantee sufficient RAM;
watch available memory and sustained swap activity alongside other users' work.

Output: `/ZPOOL/data/projects/rf1-sra-environment-SD/derivatives/fsl/randomise/katie-mspss-corrected-v1/`.
Original outputs remain in their original directories. A separate lease rejects duplicate coordinators;
native children inherit it. On interruption, repeat the same launch block: the recorded release is used,
successful jobs are validated/reused, and incomplete attempts get separate attempt directories.
Do not delete locks, alter receipts, or overwrite partial outputs to force a restart.

## Progress And Publication

```bash
cd /ZPOOL/data/projects/rf1-sra-environment-SD
LOG=$(ls -1t logs/runs/mspss-corrected-*.nohup.out | head -1)
tail -45 "$LOG"
free -h
vmstat 2 5
```

On success, all 64 receipts, commands, output grids/probabilities, opposite-direction t maps,
and all 384 scientific results are verified. Aggregate maps/clusters tables, provenance and README
publish automatically to `results/review/mspss-corrected-v1/` using HTTPS Git. No participant rows
or NIfTIs are in that report. A clean analysis checkout is fast-forwarded only after publication;
dirty/non-main checkouts are preserved and reported, never stashed/reset/rebased.
Upstream logs publish on success or failure. The manual retry for log publication is:

```bash
umask 0000
python3 /ZPOOL/data/projects/rf1-sra-linux2/code/publish_run_logs.py \
  --project /ZPOOL/data/projects/rf1-sra-linux2
```

Do not interpret the original support-related results as final while this corrected batch is pending.
