# PM2.5 Reward Components: N=97

This isolated additive-model follow-up compares three related outcomes:

- `win_only`: Social Doors win minus Doors win, using activation COPE1.
- `loss_only`: Social Doors loss minus Doors loss, using activation COPE2.
- `social_specific`: (Social win-loss) minus (Doors win-loss), reusing the
  original validated COPE4 difference stack.

All three use the **same** nine-column design: intercept, signed task differences
in FD and tSNR, E11 and XA30 scanner indicators, gender, age, PM2.5 and Ecog.
The existing centered design is reused with only the PM2.5 x Ecog column removed.
Only positive/negative PM2.5 slopes are tested; there are no interaction terms.
The cohort and settled exclusions remain unchanged at 97 participants (df=88).

Six native randomise jobs cover three outcomes and two Z-equivalent CDTs,
2.6 and 3.1, converted to t using df=88. Each job tests both PM2.5 directions,
with 10,000 permutations and the existing seed. Cluster-FWE is per map; there
is no additional across-outcome/direction/CDT correction. These component tests
were added after inspecting earlier results and remain exploratory.

The runner verifies actual L1 contrast weights (including zero nuisance weights),
existing win/loss event timing, each source COPE, exact participant/image order,
win-minus-loss arithmetic, the original common mask and all frozen hashes.
Missing inputs stop the batch; nobody is silently dropped or substituted.
Completed compatible jobs are reused. Partial attempts are retained separately.
Nothing in existing preprocessing, L1s, randomise batches or exclusions is changed.

## Linux2

```bash
cd /ZPOOL/data/projects/rf1-sra-environment-SD
umask 0000
git -c remote.origin.url=https://github.com/DVS-Lab/rf1-sra-environment-SD.git fetch origin main
bash <(git show FETCH_HEAD:code/launch_pm25_components.sh) --jobs 6
```

The launcher freezes code/data under ignored `work/`, uses the existing
`work/venv-katie` environment, runs through nohup, checks all results and publishes
the compact Linux2 run record automatically. It does not pull over live code or
automatically publish images, participant tables or the bulk results to Git.

Outputs: `derivatives/fsl/randomise/katie-pm25-components-v1/`, including
`maps.tsv`, `clusters.tsv`, `source_order.tsv`, `design.tsv`, `design.con`,
`plan.json`, `status.json`, and the per-job native command/receipt/attempt files.

If log publication needs retrying:

```bash
python3 /ZPOOL/data/projects/rf1-sra-linux2/code/publish_run_logs.py --project /ZPOOL/data/projects/rf1-sra-linux2
```
