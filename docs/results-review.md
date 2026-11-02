# Review the Completed Katie N=97 Results

The Linux2 record `20261101-232106_katie-overnight-20261101-231810-randomise.md`
confirms 24/24 jobs and all 48 directional corrected maps passed. Both command
and final verification exited 0. The numerical findings are not printed by the
original completion checker; they must be read from the existing corrected maps.

`code/summarize_katie_randomise.py` verifies the frozen input/design fingerprints,
all 24 completion receipts and their output inventories, then reports all 48 maps
without rerunning randomise or modifying any image, configuration or exclusion.
It preserves an existing identical report and refuses to overwrite a differing
one. Null maps are reported alongside significant maps at both CDTs. Descriptive
26-connected components are calculated only in the already-corrected significant
maps; this is not a new cluster-inference procedure. Peak locations are MNI-grid
world millimetres, not geographic coordinates or participant-level records.

## Exact Linux2 Commands

The jobs must be finished before updating this checkout. These commands use
HTTPS, leave completed processing untouched, and publish just the four text
summary files through Git. They do not transfer or commit any NIfTI images.

```bash
(
set -euo pipefail
umask 0000
cd /ZPOOL/data/projects/rf1-sra-environment-SD
if pgrep -u "$USER" -af '[r]un_katie_overnight.sh|[r]un_katie_randomise.py (build|check|run)( |$)'; then
  echo "STOP: Katie processing is still active; do not update its checkout."
  exit 1
fi
git remote set-url origin https://github.com/DVS-Lab/rf1-sra-environment-SD.git
git pull --ff-only origin main
STAMP=katie-results-summary-$(date +%Y%m%d-%H%M%S)
STATUS=0
bash /ZPOOL/data/projects/rf1-sra-linux2/code/run_logged.sh \
  --label "$STAMP" --include-full-log -- \
  "$PWD/work/venv-katie/bin/python" code/summarize_katie_randomise.py \
  || STATUS=$?
python3 /ZPOOL/data/projects/rf1-sra-linux2/code/publish_run_logs.py \
  --project /ZPOOL/data/projects/rf1-sra-linux2
[[ "$STATUS" -eq 0 ]] || exit "$STATUS"
git add -- results/randomise/katie-v1
if ! git diff --cached --quiet -- results/randomise/katie-v1; then
  git commit -m "Publish verified Katie N97 randomise results summary" -- results/randomise/katie-v1
fi
git push origin main
)
```

The report is `results/randomise/katie-v1/README.md`, with `maps.tsv` (all 48),
`clusters.tsv` (only corrected p<0.05 components, possibly empty) and
`provenance.json`. Map-level minimum cluster-FWE p is **not** corrected across
models, outcomes, directions or CDTs. These are exploratory per-map FWE results.

## What Has and Has Not Been Tested

- The ADI and PM2.5 standalone models each test the exposure in both directions.
- Four moderation models each include exposure and moderator main effects but
  test only the interaction in both directions.
- There are no constituent main-effect contrasts within the interaction models,
  and no intercept/group-average activation tests.

The useful optional follow-up is a separate immutable contrast-only batch for
the exposure and moderator main effects in the four interaction designs. That
would be 16 jobs (four models x two outcomes x two CDTs), with four contrasts per
job (both constituent effects, each direction). These conditional effects are
interpreted at the centered other predictor's reference value; they are not the
same coefficients as the standalone exposure models. They must not replace the
existing interaction results or alter the cohort, images or design matrices.
Review the primary completed results before deciding on further analyses.
