# Financial Vulnerability Moderation: Frozen N=97

## Question and Specification

Does the association between financial vulnerability and neural reward responses
vary with perceived social support (MSPSS), ADI, PM2.5, or Ecog?

FEVS leads; OAFEM is secondary. Each moderator is tested in its own model:

`brain outcome ~ financial score + moderator + financial score:moderator + nuisance terms`

There are no three-way interactions, no simultaneous four-moderator model, and
no new cohort selection. Both constituent main effects are always included.
Continuous scores are mean centered before multiplication. Nuisance terms are
age, gender_code1, two scanner indicators, and the same outcome-specific FD/tSNR
terms used in the validated predictor batch. Signed QC differences accompany
the social-specific outcome; pair means accompany the domain average.

The two outcomes are `(Social win-loss)-(Doors win-loss)` and
`((Social win-loss)+(Doors win-loss))/2`. Both existing activation and matched
no-TEDANA VS-PPI image families are reused without regeneration or resmoothing.
Every design has 97 rows, 10 columns, full rank and 87 residual degrees of freedom.
The interaction alone is tested in positive and negative directions. The separate
predictor batch remains the test of the simpler financial-score association.

This is a voxelwise model with **brain image as outcome**, not a model predicting
FEVS from brain activity. A nonzero interaction supports a conditional association,
not causation or mediation. The reversed regression is not statistically identical.
Any later financial-score-outcome analysis should use independently defined ROIs
or cross-validation, not clusters selected by these same interaction tests.

## Scope and Interpretation

FEVS: 32 jobs; secondary OAFEM: 32 jobs. Total 64 jobs / 128 directional maps,
10,000 permutations, fixed seed 20261101, CDTs equivalent to Z=2.6 and 3.1
(converted to t using df=87). Per-map cluster-FWE p<0.05; there is no additional
correction across this exploratory family. Report all models, directions, CDTs
and nulls rather than choosing a story based on the most significant result.

In these 97 participants, FEVS correlates more clearly with MSPSS (Pearson r=-.322)
and Ecog (r=.393) than ADI (.085) or PM2.5 (.111). These marginal correlations do
not decide whether an interaction exists. A defensible framing is whether social
and cognitive context modifies the financial-vulnerability/reward association;
environmental moderation is a separate exploratory hypothesis. Do not describe
an environmental-to-financial causal pathway as already established.

## Exact Linux2 Launch

Paste these **three lines only**, without Markdown fences or terminal prompts:

```bash
cd /ZPOOL/data/projects/rf1-sra-environment-SD
git -c remote.origin.url=https://github.com/DVS-Lab/rf1-sra-environment-SD.git fetch origin main
bash <(git show FETCH_HEAD:code/launch_financial_followup.sh) moderation
```

This is a Bash launcher. It extracts a frozen release under ignored `work/`,
does not pull, switch, reset or edit the running checkout, and starts a detached
job with umask 0000. It waits for the earlier predictor/remaining batches' locks
rather than killing them or increasing their concurrency. Default: 16 workers.
It uses the existing `work/venv-katie` environment and native FSL smoke tests.
Inputs, roster order, source hashes, image grids and all designs are checked.
Run records are automatically published after preflight and again on exit.

The prior pasted-shell syntax errors do not prove the detached predictor job
failed: its printed input-stage record proves it launched, but not that it passed.
Check its current process/log state without restarting it:

```bash
cd /ZPOOL/data/projects/rf1-sra-environment-SD
git -c remote.origin.url=https://github.com/DVS-Lab/rf1-sra-environment-SD.git fetch origin main
bash <(git show FETCH_HEAD:code/launch_financial_followup.sh) status
```

If the predictor truly stopped, `predictors` instead of `status` resumes/reuses
its original outputs; if active, the helper prints its state and starts no duplicate.
An active orphan native process is also guarded by the existing per-job receipts
and process-group checks. Do not delete `running.json` or output directories.

## Outputs and Logs

Images remain at their original paths. New designs/results are isolated under:

`derivatives/fsl/randomise/katie-financial-moderation-v1/`

Verified summaries, all 128 maps including nulls, are under:

`results/randomise/katie-financial-moderation-v1/`

Progress log: `logs/runs/katie-moderation-*.nohup.out`.
Settled exclusions, completed financial predictor results and all earlier jobs
are preserved. Resume with the recorded frozen release if code later changes.

Manual log publication (safe even if already published):

```bash
python3 /ZPOOL/data/projects/rf1-sra-linux2/code/publish_run_logs.py --project /ZPOOL/data/projects/rf1-sra-linux2
```
