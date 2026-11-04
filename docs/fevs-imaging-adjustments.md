# Matched FEVS Imaging Adjustment Checks

Requested November 4, 2026, after reviewing the completed exploratory findings.
This is a sensitivity batch, not a new primary-analysis designation. FEVS scoring
remains provisional pending item-level verification. MSPSS coding is unchanged;
MSPSS is not included in these neural designs.

Three retained fits, each with additive ADI, Ecog, or both:

1. Activation: Social win minus Doors win, standalone FEVS.
2. Same activation outcome, FEVS at mean PM2.5 in the existing
   FEVS + PM2.5 + FEVS x PM2.5 model.
3. VS connectivity: (Social win-loss) minus (Doors win-loss), FEVS at mean
   PM2.5 in that same interaction model.

Original intercept, signed FD/tSNR differences, scanner-era indicators, gender,
age, FEVS and existing PM2.5 terms remain numerically unchanged. ADI/Ecog are
mean-centered in original units and appended as additive main effects.
No new interactions, exclusions, seed definitions, masks, images or smoothing.
All 97 participants remain in the exact original 4D-volume/design order.

Eighteen new jobs: 3 fits x 3 adjustments x 2 CDTs. Each tests both FEVS
directions. Baseline residual df are 89 (standalone) and 87 (PM2.5 model);
adjusted df are 88/87 and 86/85 respectively. CDTs are Z-equivalent 2.6/3.1
converted to t for each design, with 10,000 permutations and seed 20261101.
Per-map cluster-FWE is not joint correction across sensitivity fits, directions
or thresholds. No significant-cluster-restricted inference is used.

Six baseline jobs are authenticated and reused, not rerun. All 48 baseline and
adjusted directional FEVS maps, including null results, are summarized. Cluster
overlap is descriptive; retained significance is not equivalence or causal
independence, and loss of significance does not establish loss of the association.

## Linux2 Launch

Run the complete block on Linux2. No pull, SSH, source copy or environment rebuild:

```bash
(
set -euo pipefail
umask 0000
cd /ZPOOL/data/projects/rf1-sra-environment-SD
git -c remote.origin.url=https://github.com/DVS-Lab/rf1-sra-environment-SD.git fetch origin main
bash <(git show FETCH_HEAD:code/launch_fevs_imaging_adjustments.sh)
)
```

The launcher freezes code/data/config from the fetched revision in ignored work/.
New inputs come from that release, never an outdated live checkout. It uses the
existing work/venv-katie Python, nohup/setsid, 18 single-threaded workers, inherited
experiment locks, native smoke tests for both families, and final independent
receipt/product/source checks. Completed compatible jobs are reused; incomplete
attempts are preserved and retried separately. Changed inputs/products stop
execution rather than being overwritten. To resume, repeat the same launch block:
when a plan exists, it automatically uses its recorded data_root release rather
than newly fetched code. Never remove locks or completed success receipts.

Native outputs:
`/ZPOOL/data/projects/rf1-sra-environment-SD/derivatives/fsl/randomise/katie-fevs-adjustments-provisional-v2/`.
All previous batches remain read-only. On success, sealed aggregate README,
maps.tsv, clusters.tsv and provenance publish automatically to
`results/review/fevs-imaging-adjustments-provisional-v1/` through isolated HTTPS
Git. No NIfTIs or participant-level scores are published. Logs publish on exit,
including failures; manual retry:

```bash
python3 /ZPOOL/data/projects/rf1-sra-linux2/code/publish_run_logs.py \
  --project /ZPOOL/data/projects/rf1-sra-linux2
```

## Receipt Compatibility Fix

The initial v1 launch stopped before smoke tests or new randomise jobs. Inherited
audit records may contain path/SHA-256 without size; the older parallel auditor
accepts that valid schema, whereas the new strict verifier compared the entire
record with a three-field fingerprint and misreported it as changed.

V2 verifies every inherited SHA-256 and any recorded size before adding the
missing size field. It never replaces a stored hash with a current hash. Real
hash/size changes still stop execution. The failed v1 plan/logs remain untouched,
and no old release, baseline receipt or completed result is edited. The same
launch block above fetches the fix and starts the isolated v2 batch; subsequent
launches reuse v2's recorded release and compatible completed jobs.

## Completed Validation And Checkout Sync

The November 4 v2 run completed all 18 jobs and all 48 baseline/adjusted
directional maps. Command and independent check both exited 0. Aggregate
publication also exited 0 at commit 3df0136. N=97, original results and exclusions
are unchanged; scoring remains provisional.

Frozen-release launchers and isolated publishers intentionally do not update
the live checkout, so it can be behind origin/main after a successful run.
Untracked results/progress/ and the four legacy results/randomise/ summary
directories are local generated exports, not modified analysis code. They are
now narrowly ignored without removing local files. Canonical results/review/
reports and the original tracked results/randomise/katie-v1/ remain tracked.
Do not add every local output just to silence git status.

With the batch finished, synchronize the checkout without rebasing, resetting,
deleting local files or rerunning processing:

```bash
(
set -euo pipefail
umask 0000
cd /ZPOOL/data/projects/rf1-sra-environment-SD
git -c remote.origin.url=https://github.com/DVS-Lab/rf1-sra-environment-SD.git fetch origin main
git merge --ff-only origin/main
git status --short --branch
)
```

A fast-forward refuses divergent history or conflicting local files instead of
discarding them. Completed processing and the frozen releases are not changed.

## Read-Only Anatomy Comparison

Render the original and ADI/Ecog-adjusted maps on identical original-peak slices,
with original corrected contours in cyan and adjusted corrected contours in gold:

```bash
(
set -euo pipefail
umask 0000
cd /ZPOOL/data/projects/rf1-sra-environment-SD
git -c remote.origin.url=https://github.com/DVS-Lab/rf1-sra-environment-SD.git fetch origin main
bash <(git show FETCH_HEAD:code/launch_fevs_adjustment_maps.sh)
)
```

No inference, participant-level refitting, image smoothing or source changes.
This uses the existing review environment, preparing that isolated environment
only if missing. Three PNGs, overlap/Dice, peak/centroid coordinates, peak shift,
whether the adjusted peak is within the original corrected cluster, and available
Harvard-Oxford atlas labels publish automatically through Git to
`results/review/fevs-adjustment-maps-v1/`. Local outputs and input hashes stay in
`work/fevs-adjustment-map-review-v1/`. Logs publish on exit.

The background t shading at |t|>=2 is display-only, not new inference. Focal
corrected contours use saved per-map cluster-FWE p<.05 at CDT Z-equivalent 3.1.
All directions and both CDTs remain in the complete adjustment results. A missing
adjusted contour does not establish absence of the association, and atlas labels
are approximate nearest-voxel descriptions, not subject-specific segmentation.

The map reviewer validates the frozen design with the original
`work/venv-katie/bin/python`, while rendering uses the isolated review environment.
The original strict checker reconstructs numeric designs and compares the saved
job specification exactly; substituting the review environment can produce
numeric-library differences and a false inventory mismatch. Do not loosen that
comparison or edit the frozen plan. The original analysis interpreter is now
selected explicitly, and a missing interpreter stops rather than falling back.
The initial map-review attempt failed before creating report figures; rerunning
the same launch block fetches this reporting fix without rerunning inference.

The corrected map review validated and published on November 4 at d8e622b:
render/check/publication all exited 0. Original/adjusted clusters and all 6,580
recorded sources verified, with N=97 and exclusions unchanged.

The map review supports anatomical stability of the surviving clusters, not
uniform statistical robustness. ADI-only Dice overlap is 0.977 for the PM2.5
activation model and 0.989 for VS connectivity. With both ADI/Ecog, Dice is 0.717
and 0.744 respectively. The apparent 15-mm peak changes remain inside the
original corrected clusters; centroid changes are only 1.1 mm (activation) and
1.3 mm (VS connectivity). Ecog-only activation has no corrected cluster
(p=.0505 in the PM2.5 model); standalone FEVS activation also fails correction
with Ecog or both. These are CDT-3.1 descriptions, not additional tests.

The adjusted VS target remains predominantly left frontal-pole/cortex labeled.
The activation cluster remains near the left ventral anterior frontal region,
with approximately 64% standard-atlas white-matter labeling in the jointly
adjusted PM2.5 model. Atlas sampling is approximate, not native tissue
segmentation or proof of artifact; avoid describing this as clean cortical
vmPFC/OFC localization. No exclusion or processing change follows from this
anatomical description. All scoring remains provisional.

Future map-review publications opt into `publish_katie_review.py --sync-checkout`
after successful publication. It fetches through HTTPS and fast-forwards only a
clean main checkout. Dirty trees, other branches or divergent history stop sync;
there is no automatic commit, rebase, stash, reset or deletion. Frozen releases
and native outputs are untouched. Other publishers retain their existing default
of leaving the checkout unchanged. Already-published reports are still checked
before an explicitly requested sync.
