# Financial Batches: Live Progress and Interim Results

Run on Linux2 while predictors and/or moderation continue:

```bash
cd /ZPOOL/data/projects/rf1-sra-environment-SD
git -c remote.origin.url=https://github.com/DVS-Lab/rf1-sra-environment-SD.git fetch origin main
bash <(git show FETCH_HEAD:code/launch_financial_followup.sh) snapshot
```

This fetches reporting code into a separate ignored release without pulling or
editing the code used by active analyses. It runs in the foreground with the
existing environment, umask 0000, no new dependency installation, no native
inference, no signals or locks changed, and no new exclusions.

## What Is Checked

- 16 predictor and 64 moderation jobs, reported separately.
- Each frozen plan hash, N=97 roster order, support-mask hashes, and saved design/roster artifacts.
- Completed success receipts, job/plan identity, all result hashes, grids and
  finite/probability-map values before summarizing either direction.
- Live process-group/command matches versus stale markers, incomplete attempts,
  queued jobs, invalid receipts, and recorded coordinator failures.
- Two native/coordinator process samples five seconds apart: cumulative CPU
  time, lifetime-average CPU%, elapsed time, RSS and process state.

There is no repeated hashing of the large original input images: their lineage
was checked by the original preflight. A receipt is required before any result
image is read. Partial live corrected maps are never summarized. A job can
complete during the snapshot window; an incomplete/stale marker is not itself
an exclusion or proof of a failed analysis. Buffered console output can remain
silent while the native job is actively computing. Inspect native CPU-time
increments and process state, not just coordinator JSON or console timestamps.

Both directions and nulls are reported for every completed job. Significant
components use the existing corrected maps (1-p>0.95), with descriptive MNI peak
coordinates; these are not newly fitted clusters or anatomical labels. This is
an interim view of an incomplete exploratory family, with per-map cluster-FWE,
not correction across models/outcomes/directions/CDTs. Do not stop jobs, pick
models, or revise thresholds based on this peek.

## Artifacts and Publication

New tables are under `results/progress/financial-snapshot-TIMESTAMP/`: jobs.tsv,
maps.tsv, clusters.tsv, provenance.json and README.md. Existing reports are never
overwritten. The run record prints progress, process samples, live/incomplete job
details, all completed-map results and cluster summaries, then publishes through
the Linux2 log publisher automatically, including on snapshot failure. This lets
the collaborator inspect the live snapshot through Git, not SCP/rsync.

```bash
python3 /ZPOOL/data/projects/rf1-sra-linux2/code/publish_run_logs.py --project /ZPOOL/data/projects/rf1-sra-linux2
```

Each current batch uses at most 16 native workers. If both are full, about 32
workers can run, not all 96 cores. Low host-wide CPU alone is expected under
that cap. If few jobs remain, they may be long-running tail jobs; raising the
worker cap cannot accelerate one already-running single-threaded process.
The snapshot does not automatically stop/restart or increase concurrency.
