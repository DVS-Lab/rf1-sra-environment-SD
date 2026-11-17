# Katie targeted interpretation follow-up

This version extends the November 7 Results-ready evidence; it does not draft the manuscript.
The scope is fixed in `config/katie_targeted_followup_v1.json`. All 97 participants, corrected support
scores, original COPEs, masks and permutation outputs remain unchanged. FEVS scoring remains provisional.

## Reproduce

Run the behavior analysis with the existing scientific Python environment:

```bash
python code/review_katie_targeted.py build --kind behavior
python code/review_katie_targeted.py check --kind behavior
```

This recovers the published linear fit and exactly one sensitivity adding the squared centered support
term and its interaction with centered PM2.5. Conditional slopes use pointwise HC3 95% intervals.
The omitted-case slope ranges evaluate each fit at the same full-sample anchors and centering;
they are influence diagnostics, not a cohort change. The 16th/84th percentile tails include ties.
No significance screen selects between the two specifications.

On Linux2, run this block to read native images, validated source-order rows, and retained randomise receipts.
It does not invoke randomise or update the live checkout. Only approved aggregate files and run logs publish.

```bash
(
set -euo pipefail
umask 0000
cd /ZPOOL/data/projects/rf1-sra-environment-SD
git -c remote.origin.url=https://github.com/DVS-Lab/rf1-sra-environment-SD.git fetch origin main
bash <(git show FETCH_HEAD:code/launch_katie_targeted.sh)
)
```

The native command identifies the existing corrected 87-voxel positive ADI x MSPSS cluster.
It validates each social/nonsocial winning COPE against the sealed extension source order and reconstructs
the original difference voxel by voxel within the region. The three OLS/HC3 fits reuse the exact executed
design, with equivalence of the component and difference coefficients checked. Group overlap uses the
existing signed Social win minus Doors win intercept maps at both CDTs; the direction-agnostic union
is labelled separately. Mean-effect and interaction maps test different hypotheses.

The ADI x ECog analysis uses the 12 existing signed contrast/CDT configurations (including nulls),
recovers each corrected component (native 1-p > .95), reconciles its voxel count, peak and p against
the November 7 catalog, and fits the original design to each selected-cluster mean for influence
diagnostics. Pairwise tables give intersection, fraction of each cluster covered, Dice and peak distance.
Overlap is exact in the native common grid; no resampling, threshold optimizations, or new search.
Cluster locations use Harvard-Oxford labels plus native MNI coordinates; labels are approximate.

Only aggregate tables and figures are publishable; input fingerprints stay under ignored `work/`.
Selected-region fits and influence ranges describe the observed clusters, not independent tests.
Cluster-FWE is mapwise only; recurrence across CDTs is not replication, nor does a non-overlap at
p < .05 prove that underlying signals have no common spatial support.

## Assemble the evidence PDF

After the Linux2 launcher publishes `results/review/katie-targeted-native-v1`, fast-forward a
clean checkout. With the reporting environment (`reportlab` and `pypdf`), run:

```bash
python -m unittest discover -s tests -p test_katie_targeted_report.py -v
python code/build_katie_targeted_report.py
```

The builder requires and verifies both targeted aggregate manifests, the fixed-frontal-region
diagnostic, and the November 7 PDF and selected-cluster figure seals. It refuses missing native
data or an existing destination. It writes `output/pdf/FEVS_Targeted_Results_Followup_v1.pdf` and
its SHA-256 manifest; render and inspect every page before sharing. The previous PDF is retained.

The [Linux2 native run record](https://github.com/DVS-Lab/rf1-sra-linux2/blob/67e5f161/logs/records/20261116-222609_katie-targeted-20261116-222555-1425437-native.md)
records successful build and check exits and verification of 6,715 input fingerprints.
The published imaging payload is at commit `b1cdea3`.
