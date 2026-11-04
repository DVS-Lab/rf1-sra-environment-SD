# Katie Evidence Review And Missing Task-Mean Contrast

Requested November 4, 2026. Frozen N=97, provisional scoring and settled
exclusions remain unchanged. This package supplies the revised brief with
matched brain/association figures, task-effect context and executed designs.

## What Exists And What Is Missing

- **Win > loss:** the average of social and nonsocial win-minus-loss COPEs was
  explicitly tested with a +/- intercept contrast, as were each task separately.
  The average has minimum per-map cluster-FWE p approximately .0001 at both CDTs.
- **Double subtraction:** (social win-loss) - (nonsocial win-loss) was explicitly
  tested. Neither direction has a corrected group cluster at either CDT.
- **Social win > nonsocial win:** this image exists for the predictor analyses,
  but the group-mean intercept was not included in their tested contrasts.
  A column of ones does not imply that its coefficient was tested.

Only the missing third task effect is added: two randomise jobs, CDTs
Z-equivalent 2.6/3.1, both directions, 10,000 permutations, seed 20261101.
The existing 97-volume component stack, original common mask and centered
seven-column group design are reused: intercept, signed FD/tSNR differences,
E11/XA30 indicators, gender and age. Residual df=90; each intercept contrast is
explicitly +/-[1,0,0,0,0,0,0]. A native smoke test must confirm sign flipping.
No scientific FEVS model, existing task-mean job, L1 or L2 is rerun.

## Figures And Their Meaning

The three FEVS targets each receive a four-row paired panel: original, +ADI,
+Ecog, +both. Left: the actual corresponding whole-brain map; right: the exact
model's covariate-adjusted participant scatter. The original corrected cluster
is held fixed for all four descriptive ROI summaries, including adjusted null
whole-brain results. All 97 points remain. No ROI p value is presented as an
independent confirmation. HC3 intervals and leave-one-out/influence descriptions
are same-sample diagnostics, not new exclusions or independent replications.

The focal neural term is a FEVS main coefficient (at mean PM2.5 in the interaction
models), so scatterplots are appropriate. A JN plot is reserved for an actual
interaction, such as the behavioral PM2.5 x MSPSS result; a model containing an
interaction does not make every constituent coefficient an interaction test.

The report separates **context** (the question), **content** (map, stats and plot)
and **conclusion** (what the result can and cannot establish). The revised PDF
should preserve this structure, the activation anatomy/Ecog caveat, distinct
social-winning and domain-by-valence outcomes, and provisional scoring.

## Design Review

Custom heatmaps read the actual executed .mat and .con files, not a recreated
cohort model: standalone FEVS, FEVS/PM2.5, jointly adjusted FEVS/PM2.5, and the new
task intercept. Column-max scaling is display-only. The aggregate table records
rank, residual df, scaled condition number, and whether the intercept is tested.

Native FEAT design.png/design_cov.png are copied unchanged for the first frozen
participant's two canonical activation L1s when available, after checking actual
win/loss/win-minus-loss contrast weights. Missing PNGs are reported, never used
to trigger a FEAT rerun. L3 custom heatmaps are labeled distinctly from native
FEAT screenshots. Participant row labels are not published in these diagrams.

## Linux2

Run the complete block. No pull or environment changes to an existing analysis
venv; native checks use the original analysis interpreter and plots use the
isolated review interpreter. Everything is archived from HTTPS Git first.

```bash
(
set -euo pipefail
umask 0000
cd /ZPOOL/data/projects/rf1-sra-environment-SD
git -c remote.origin.url=https://github.com/DVS-Lab/rf1-sra-environment-SD.git fetch origin main
bash <(git show FETCH_HEAD:code/launch_katie_evidence.sh)
)
```

New native task-mean outputs: derivatives/fsl/randomise/katie-social-win-mean-v1/.
All original analyses remain unchanged. Compatible completed jobs are reused;
failed partial attempts are preserved. A recorded native release is reused on
restart. New plots/metadata: work/katie-evidence-v1/report/. Aggregates publish
automatically to results/review/katie-evidence-v1/; no NIfTIs or case-level ROI
data are published. A clean main checkout fast-forwards after publication;
dirty/divergent trees stop sync without reset/rebase/stash. Logs publish on exit.

Manual log-publication retry:

```bash
python3 /ZPOOL/data/projects/rf1-sra-linux2/code/publish_run_logs.py \
  --project /ZPOOL/data/projects/rf1-sra-linux2
```
