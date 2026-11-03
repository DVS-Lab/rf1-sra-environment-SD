# Complete Reward-Component Model Extension

The frozen **97-person** cohort, settled exclusions, no-TEDANA sm-5 activation
inputs and original VS seed are unchanged. No preprocessing or L1 FEAT rerun
is performed. Missing or incompatible source estimates stop validation; they do
not cause participant deletion or substitution.

## Coverage

All 16 previous models are carried forward:

- Six environmental models: ADI, PM2.5, and their separate MSPSS/Ecog interactions.
- Two separate financial-score predictors: FEVS and OAFEM.
- Eight financial interactions: each financial score with MSPSS, ADI, PM2.5 or Ecog.

For activation and VS-seeded connectivity, the new outcomes are Social Doors
minus Doors **wins** and Social Doors minus Doors **losses**. The original
social-specific valence difference and average-reward outcomes are retained.
In every interaction design, both constituent main effects and the interaction
are explicitly contrasted in both directions. Main effects are conditional on
the other centered scientific predictor being zero, not a separate reduced model.
There are no three-way interactions or new group-mean PPI tests.

The additive PM2.5 + Ecog model also covers activation and VS connectivity for
wins, losses and the social-specific valence difference, testing both scientific
main effects. Its existing six PM2.5 activation jobs remain owned by the earlier
runner. A separate helper waits for that runner's lock or resumes its missing
jobs; it never interrupts or duplicates an active batch.

## New Work Versus Retained Results

| New work | Jobs |
| --- | ---: |
| Two components x two families x 16 models x two CDTs | 128 |
| Previously untested constituent main effects in old environmental VS/financial moderation batches | 80 |
| Additive Ecog activation effects, three outcomes x two CDTs | 6 |
| Additive PM2.5/Ecog VS effects, three outcomes x two CDTs | 6 |
| **Total extension jobs** | **220** |

Existing focal and activation conditional-effect results are linked and verified,
not rerun. Together with the six-job additive batch, the complete scientific
catalog has 1,328 directional tests: 996 new maps and 332 retained maps.
Each native job tests two, four or six contrasts. Group-average activation maps
from the earlier batch remain intact and are not counted in this model catalog.

Inference remains 10,000 permutations, fixed seed 20261101, cluster extent with
Z-equivalent CDTs 2.6 and 3.1 converted to t for each design's residual df.
Correction is per map, not jointly across models, directions, outcomes, seeds
or CDTs. Components and CDTs are related exploratory analyses, not replications.

## Linux2: One Launch Block

```bash
cd /ZPOOL/data/projects/rf1-sra-environment-SD
umask 0000
git -c remote.origin.url=https://github.com/DVS-Lab/rf1-sra-environment-SD.git fetch origin main
bash <(git show FETCH_HEAD:code/launch_reward_extension.sh) --jobs 60
```

The launcher uses an ignored frozen release, the existing `work/venv-katie`
Python, nohup/setsid, umask 0000 and single-threaded numerical libraries.
It performs full input checks and a native FSL smoke test for each image family
before the large batch. Up to 60 jobs from this workflow run concurrently; six
slots are reserved while the additive helper is active. Other unrelated server
jobs are not managed by this limit. CPU count alone does not guarantee RAM is
sufficient; memory is printed before launch and should be monitored under load.

The same block resumes completed compatible jobs without replacing them.
Input changes, result corruption and live orphan workers stop reuse safely.
An interrupted attempt is preserved and any retry uses a new attempt directory.

Output: `derivatives/fsl/randomise/katie-reward-extension-v1/`.
`maps.tsv` covers all 1,328 tests including nulls; `clusters.tsv` contains the
passing clusters; `validation.json` records the final checks and receipts;
`source_order.tsv` binds every component image to its participant and task.
The existing six-job additive folder remains separate and untouched.

Only compact run logs are published automatically, not bulk figures or tables.
To capture and publish a read-only progress/result snapshot (including failures
and any final result-table findings), run:

```bash
cd /ZPOOL/data/projects/rf1-sra-environment-SD
git -c remote.origin.url=https://github.com/DVS-Lab/rf1-sra-environment-SD.git fetch origin main
bash <(git show FETCH_HEAD:code/launch_reward_extension.sh) --status
```

This does not start or stop analyses. It records live matching processes, state,
receipt metadata, product presence, the latest log ending and any complete
1,328-row results table. It does not substitute for full image/source hash checks.

To also summarize already-completed extension maps before the batch finishes,
use `--partial-results` instead of `--status`. This adds a read-only source/input
and completed-result hash check, then records every corrected finding from those
completed maps. Pending jobs are not summarized or treated as nulls. No bulk
figures/tables are published and no analysis is restarted.

Retry log publication with:

```bash
python3 /ZPOOL/data/projects/rf1-sra-linux2/code/publish_run_logs.py --project /ZPOOL/data/projects/rf1-sra-linux2
```
