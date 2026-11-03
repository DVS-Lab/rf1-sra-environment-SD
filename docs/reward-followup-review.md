# FEVS Loss Interaction and Ecog Figures

This is a read-only follow-up of three completed, preidentified negative-direction
activation effects from the 220-job extension. It does not wait for, stop, restart,
or modify ongoing randomise jobs. The original cohort remains N=97 and all settled
exclusions, previous figures and completed analysis products remain unchanged.

| Model | Coefficient | Outcome | CDT Z-equivalent | Plot |
|---|---|---|---:|---|
| FEVS x PM2.5 | Interaction | Social loss minus Doors loss | 3.1 | JN, conditional slopes, influence |
| PM2.5 x Ecog | Ecog at mean PM2.5 | Social loss minus Doors loss | 2.6 | Raw/adjusted scatter, influence |
| OAFEM x Ecog | Ecog at mean OAFEM | Social win minus Doors win | 3.1 | Raw/adjusted scatter, influence |

The two Ecog findings are **main effects, not interactions**. The loss interaction
is not the earlier FEVS win main effect and does not establish moderation of that
win association. Component outcomes are not the original win-minus-loss
difference-of-differences. These targeted CDTs identify the reported findings;
this small report is not a comprehensive threshold/model survey or the final audit.

## Linux2

Run the entire block. No live checkout pull, SSH, SCP, rsync or imaging rerun:

```bash
(
set -euo pipefail
umask 0000
cd /ZPOOL/data/projects/rf1-sra-environment-SD
git -c remote.origin.url=https://github.com/DVS-Lab/rf1-sra-environment-SD.git fetch origin main
bash <(git show FETCH_HEAD:code/launch_reward_followup_review.sh)
)
```

The launcher archives a frozen reporting release into ignored `work/`, reuses
the separate review environment, and runs detached via nohup. Its exclusive lock
is for this report only, never the active analysis. Progress is captured before
and after the report. Build/check and Git publication are separately logged.

The report validates source fingerprints, completed native job receipts, actual
design/contrast matrices, centered interaction products, subject order, original
permutation settings and model-specific Z-to-t cutoffs. Statistical images are
not resampled. The native negative-direction t values are converted to the
coefficient's sign for **blue negative brain overlays**. Cluster locations include
MNI coordinates, physical volume and optional local Harvard-Oxford annotations.
Each compressed 4D outcome stack is loaded once, one outcome at a time.

JN plots retain all 97 participants and restrict slopes/roots to the observed
PM2.5 range. They include ordinary pointwise 95% intervals, HC3 sensitivity,
moderator-value rugs and fitted conditional associations. Ecog adjusted scatters
use the full original models, evaluated at the other predictor's mean. Cook's D,
leverage and leave-one-out slopes are diagnostics, never exclusion rules.

**All ROI/JN plots are same-sample selected-cluster descriptions, not independent
confirmation.** Mapwise cluster-FWE is not correction across the exploratory
models, outcomes, directions or thresholds. No new voxelwise inference is run.

After successful validation, the small sealed report publishes automatically to:

`results/review/reward-followup-v1/README.md`

Only aggregate PNGs, cluster/conditional-curve tables and aggregate fit summaries
are published through an isolated HTTPS clone. Subject-level influence tables
and input fingerprints remain outside the report in `work/reward-followup-review-v1/`.
Repeating the command verifies/reuses completed report artifacts and refreshes
progress; differing or unsealed artifacts are preserved, not overwritten.

Run records are automatically published on exit with Linux2's
`python3 code/publish_run_logs.py --project /ZPOOL/data/projects/rf1-sra-linux2`.
