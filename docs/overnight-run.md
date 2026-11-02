# Katie N=97 Overnight Input Validation and Randomise

This is the supported launcher. It does not call the legacy `L3stats.sh`, delete
old results, change exclusions, rerun L1/preprocessing/TEDANA, or invoke PALM/TFCE.
It uses the frozen 97-person cohort and approved paired-QC choices, six models,
both win-loss outcomes, Z-equivalent CDTs 2.6 and 3.1, and 10,000 permutations.
There are **24 randomise jobs, each testing positive and negative directions**.
The default 24 workers run single-threaded; the underlying machine has 96 cores.
No completion-time guarantee is made before an actual Linux2 run.

## Exact Linux2 Launch

Synchronize while other jobs using these code checkouts are stopped. If Git
reports unrelated local changes, stop rather than discarding them. Everything
under the new output root remains isolated from existing analyses.

```bash
(
set -euo pipefail
umask 0000
cd /ZPOOL/data/projects/rf1-sra-linux2
git fetch origin
python3 code/sync_published_checkout.py --project "$PWD" --apply --processing-stopped

cd /ZPOOL/data/projects
if [[ ! -d rf1-sra-environment-SD/.git ]]; then
  [[ ! -e rf1-sra-environment-SD ]] || { echo "STOP: existing non-Git directory"; exit 1; }
  git clone https://github.com/DVS-Lab/rf1-sra-environment-SD.git
fi
cd rf1-sra-environment-SD
[[ -z "$(git status --porcelain)" ]] || { git status --short; echo "STOP: preserve local changes before updating"; exit 1; }
git pull --ff-only origin main
bash code/prepare_katie_env.sh

STAMP=katie-overnight-$(date +%Y%m%d-%H%M%S)
mkdir -p logs/runs
nohup setsid -f -w bash code/run_katie_overnight.sh --jobs 24 --label "$STAMP" \
  > "logs/runs/${STAMP}.nohup.out" 2>&1 &
echo "LOG=/ZPOOL/data/projects/rf1-sra-environment-SD/logs/runs/${STAMP}.nohup.out"
sleep 10
tail -35 "logs/runs/${STAMP}.nohup.out"
)
```

The environment helper reuses a local `work/venv-katie` if present, or creates a
system-site-packages venv from the existing tedana-26.0.3 Python. Only missing
dependencies are installed in that local venv; no existing environment is
modified or upgraded. All new analysis output is created with **umask 0000**.
The temporary build root is explicitly made shareable because Python's mkdtemp
otherwise forces 0700 regardless of umask. No production permissions are changed.

The launcher does, in order:

1. Validate the unchanged workbook/selection sources and exact frozen roster.
2. Reuse/check an existing final 97-person upstream difference bundle, or build
   it from existing authenticated diagnostic estimates and independently check it.
   Never replace the 121-person pool or an incompatible prior bundle.
3. Verify both selected tasks' live BIDS software-era sidecars and exact QC
   alignment against the reviewed values. Build the average from corresponding
   L1 COPE-4 estimates using the same common valid mask as the difference.
4. Generate and independently recompute the 12 design matrices, their two focal
   contrasts, actual residual df, approved paired-QC columns and Z-to-t cutoffs.
5. Run a **real two-permutation randomise smoke test** in its own directory and
   check both directions' raw t and cluster-extent corrected maps. This smoke
   output is never treated as a full inferential result.
6. Only after those checks pass, launch the 24 full jobs. A heartbeat is printed
   every minute while waiting. Failures do not destroy successful jobs.
7. Independently verify all completion receipts/results and publish logs.

Before leaving it overnight, look for **`SMOKE PASSED`** followed by
**`STAGE RANDOMISE: 24 jobs`** and `STARTED` entries. An initial source/geometry
check can take longer than the first ten-second log sample; that is not yet a
successful launch. The process is detached and survives closing SSH.

## Monitor and Publish

```bash
cd /ZPOOL/data/projects/rf1-sra-environment-SD
LOG=$(ls -1t logs/runs/katie-overnight-*.nohup.out | head -1)
tail -35 "$LOG"
if [[ -f derivatives/fsl/randomise/katie-v1/status.json ]]; then
  python3 -m json.tool derivatives/fsl/randomise/katie-v1/status.json
fi
```

The launcher automatically publishes the input build/check record after it
passes, and the inference/check record on completion or failure, using the
existing upstream log publisher. The following explicit command is also safe:

```bash
python3 /ZPOOL/data/projects/rf1-sra-linux2/code/publish_run_logs.py \
  --project /ZPOOL/data/projects/rf1-sra-linux2
```

There is no completed inference record to publish while inference is still
running. The live console/status stay on Linux2 until the logged command exits.
No SCP/rsync or NIfTI commit is needed. Do not pull/update the source code while
this frozen plan is running; log publishing deliberately leaves it unchanged.

## Resume and Preservation

After the previous launcher and child processes have stopped, rerun the same
launch block. A coordinator lock plus inherited child lease prevents competing
runs; recorded live process groups also block orphan/duplicate jobs. Verified
success receipts are reused without modifying their image files. Incomplete
attempts are kept and a fresh numbered attempt is created. Changed sources,
corrupt completed outputs or an incompatible plan stop rather than being reset.
Staged input builds are committed atomically; interrupted staging directories
remain available for inspection. No blanket deletes or force overwrites occur.

## Outputs and Interpretation

Main analysis root:

```text
/ZPOOL/data/projects/rf1-sra-environment-SD/derivatives/fsl/randomise/katie-v1/
```

- `plan.json` / `plan.sha256`: immutable inputs, software hashes, settings and jobs.
- `subjects.tsv`, `raw_covariates.tsv`, `designs/`: exact aligned N=97 inputs.
- `inputs/average.nii.gz`: newly assembled average; the difference and mask reuse
  the separately validated upstream `work/randomise-katie-final-v1/cope-4/` files.
- `smoke/`: isolated two-permutation command and checked outputs.
- `jobs/<outcome>/<model>/z-2p6` or `z-3p1`: preserved numbered attempts, console
  logs and `success.json` receipt after output verification.
- `status.json`: live runtime status; configuration authorization is not a claim
  that a process has started or finished.
- `results.tsv`: written only after all 24 jobs validate; includes exact output
  prefixes, df, converted cutoff, seed and permutation count.

Use `*_clustere_corrp_tstat1.nii.gz` and `tstat2` for the two directions. Values
are 1-p; the approved per-map cluster-FWE p<0.05 rule corresponds to >0.95.
The two CDT analyses and all model/outcome/direction tests are exploratory,
without an additional cross-analysis correction. Report both CDTs, not only the
one yielding significance. See [the inference plan](inference-plan.md).

Local tests use synthetic NIfTI data and a simulated executable because FSL and
study images are not available on this Mac. They verify build/check, arithmetic,
real N=97 matrix construction, receipts, failed attempts, full job coordination
and resume. Actual FSL compatibility is deliberately gated by the Linux2 smoke.
