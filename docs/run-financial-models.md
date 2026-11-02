# Run FEVS, With OAFEM Secondary

This is an isolated supplemental analysis. All 97 participants are preserved;
the existing cohort, images, exclusions, and running code are untouched. The
source CSV has complete finite FEVS and OAFEM values, unique RF1 IDs and the
same roster. The program joins by ID and checks the image and covariate row
order rather than relying on CSV position. Zero scores remain zero.
Saved preview/source hashes are authenticated without requiring Mac and Linux
BLAS builds to reproduce descriptive VIF/leverage decimals byte-for-byte. The
execution matrices use the actual validated baseline nuisance columns; financial
scores and all row identities are independently rechecked. The tiny 1e-12
comparison tolerance is only floating-point roundoff, not a covariate/QC rule.

## Models

FEVS leads the financial-score extension; OAFEM is secondary. They are separate
continuous mean-centered raw-score predictors, not mutually adjusted, not new
nuisance covariates in the earlier environmental models, and not moderators in
this batch. There are **no interactions of any order** in these financial models.

Each model has the score plus age, gender, two scanner indicators and two QC
columns (8 full-rank columns, N=97, residual df=89). The social-specific outcome
uses signed FD/tSNR differences; the averaged outcome uses pair means. No
ADI/PM2.5/MSPSS/Ecog adjustment is added to these first score models. Each score
is tested in both directions at the previously approved Z-equivalent CDTs 2.6
and 3.1, with 10,000 permutations, seed 20261101 and per-map cluster-FWE p<0.05.
The additional model/outcome/direction/threshold family is exploratory, without
joint correction. No PALM/TFCE, score transformations or new exclusions.

The validated activation and matching no-TEDANA VS-PPI paired mean/difference
bundles supply the images. The average has one `(Social COPE4 + Doors COPE4)/2`
image per participant; the difference is Social COPE4 minus Doors COPE4.
The connectivity COPE4 is PPI-win minus PPI-loss, not the seed main effect.
Four numerical designs are shared across the two image families:

2 scores x 2 outcomes x 2 CDTs x 2 image families = **16 jobs / 32 directional maps**.
Half the jobs use FEVS and half OAFEM. Only 16 workers are needed for 16 jobs.
All images are reused; no preprocessing, PPI L1, L2 or earlier randomise jobs are
rerun. Missing or incompatible connectivity inputs stop rather than triggering
an unreviewed substitution or silently reducing N. An activation-only explicit
option is available for a separately frozen eight-job plan if needed.

## Preserve Running Jobs

Do not pull/rebase/checkout the canonical Linux2 tree while the earlier runner is
active. Fetching and extracting a Git archive below ignored `work/` changes no
tracked working files or index. A new release is staged atomically and remains
immutable. Physical paths (`pwd -P`) avoid path-alias differences in numerical
preview provenance; no new environment or dependency update is required.

The financial coordinator takes shared leases on the existing remaining-batch
and original-batch locks. If either is still active, it waits without signalling
or stopping any process. This prevents adding 16 workers on top of an active
48-worker batch. If those runs are finished, it starts immediately. Its own
exclusive lock and verified per-job receipts prevent duplicate financial runs.
The latest published earlier-batch record reports 48/48 finished, but runtime
locks, not a stale log or status JSON, determine whether to wait.

## Exact Linux2 Launch

```bash
(
set -euo pipefail
umask 0000
cd /ZPOOL/data/projects/rf1-sra-environment-SD
PROJECT=$(pwd -P)
if pgrep -u "$USER" -af '[r]un_financial_models\.(py|sh)'; then
  echo "STOP: a financial-model launcher/coordinator is already active."
  exit 1
fi
git -c remote.origin.url=https://github.com/DVS-Lab/rf1-sra-environment-SD.git fetch origin main
REV=$(git rev-parse FETCH_HEAD)
RELEASE="$PROJECT/work/financial-release-${REV:0:12}"
mkdir -p "$PROJECT/work" "$PROJECT/logs/runs"
if [[ ! -d "$RELEASE" ]]; then
  STAGE=$(mktemp -d "$PROJECT/work/.financial-release.XXXXXX")
  chmod 0777 "$STAGE"
  git archive "$REV" code data config | tar -x -C "$STAGE"
  mv "$STAGE" "$RELEASE"
fi
STAMP=katie-financial-$(date +%Y%m%d-%H%M%S)
LOG="$PROJECT/logs/runs/${STAMP}.nohup.out"
nohup setsid -f -w bash "$RELEASE/code/run_financial_models.sh" \
  "$PROJECT" "$STAMP" > "$LOG" 2>&1 &
echo "RELEASE=$RELEASE"
echo "LOG=$LOG"
sleep 10
tail -40 "$LOG"
)
```

This uses HTTPS only, not SSH or SCP/rsync. There is no `git pull` and no
canonical-code replacement. The launcher logs/publishes preflight first, then
requires a native two-permutation smoke test for both image families before
the full 16 jobs. A `WAITING` line is expected if the prior batch still holds
its lock. It is not an error and does not consume a randomise worker pool.

## Monitor, Publish and Resume

```bash
cd /ZPOOL/data/projects/rf1-sra-environment-SD
LOG=$(ls -1t logs/runs/katie-financial-*.nohup.out | head -1)
tail -40 "$LOG"
```

The status file appears at
`derivatives/fsl/randomise/katie-financial-v1/status.json` once full jobs run.
The input/design plan and attempts are in that analysis directory; text results
are in `results/randomise/katie-financial-v1/`. Both signs/CDTs, including nulls,
are printed into the final logged record. Only report tables, not NIfTI images,
should be published through Git.

The launcher automatically calls the existing log publisher after preflight and
on completion or failure. The manual command remains:

```bash
python3 /ZPOOL/data/projects/rf1-sra-linux2/code/publish_run_logs.py \
  --project /ZPOOL/data/projects/rf1-sra-linux2
```

To resume, use the same frozen release recorded in `plan.json`/the launch log
after the previous coordinator and workers have stopped. Verified completed
attempts are reused without modification; failed partial attempts are preserved
and receive new numbered retries. Changed sources, scores, model settings or
completed products stop rather than being reset. The archived code has no Git
checkout dependency and is independent of the canonical running tree.

No causal interpretation follows from this cross-sectional analysis. The CSV
does not independently document score calculation/timepoint/missing-item rules;
retain Jacob's values and ask for that metadata separately rather than changing
zeros, imputing or reopening imaging eligibility.

## Behavioral Context and the Brain Question

Complete-case descriptive correlations use the same N=97, not a different
survey sample. Pearson r (full precision and Spearman in
[correlations.tsv](../data/derived/financial-model-review-v1/correlations.tsv)):

| | ADI | PM2.5 | MSPSS | Ecog | FEVS | OAFEM |
|---|---:|---:|---:|---:|---:|---:|
| ADI | 1.00 | .06 | -.20 | .24 | .09 | .16 |
| PM2.5 | .06 | 1.00 | .03 | .09 | .11 | .07 |
| MSPSS | -.20 | .03 | 1.00 | -.19 | -.32 | -.15 |
| Ecog | .24 | .09 | -.19 | 1.00 | .39 | .46 |
| FEVS | .09 | .11 | -.32 | .39 | 1.00 | .33 |
| OAFEM | .16 | .07 | -.15 | .46 | .33 | 1.00 |

The observed marginal environmental-score associations are weak here. The more
apparent financial-score correlates are social support and reported cognitive
difficulties. Correlations neither establish causal effects nor establish
moderation. Weak marginal effects do not exclude an interaction, but an
environment x support hypothesis requires its own explicit test; it is not a
finding already demonstrated by this matrix.

Keep the brain central: **Does financial vulnerability relate to reward
activation or VS task-modulated connectivity, and is the association specific
to social reward rather than common to both domains?** The present separate
score models answer that first. A social-specific association and a domain-
general association are different results, not interchangeable fallback claims.

The latest published earlier-batch log contains preliminary environment x Ecog
VS-PPI clusters at per-map corrected p<0.05, including results at both CDTs.
They require map/anatomical review and are not jointly corrected across the
exploratory family. They motivate inspecting that neural result, not asserting
that the brain mediates an environmental effect on FEVS. No financial-score
imaging results have been inspected to choose these new models.

Candidate follow-ups, not launched here, are separate two-way FEVS x MSPSS or
FEVS x Ecog neural models, retaining both constituent main effects. Avoid a
three-way interaction or indiscriminate factorial search. An environment x
support model predicting FEVS is a distinct behavioral question; it may provide
context but would not itself answer the neural question or distinguish this
paper from a behavior-only proposal. Cross-sectional associations do not
establish a temporal environment-to-brain-to-vulnerability mediation pathway.
