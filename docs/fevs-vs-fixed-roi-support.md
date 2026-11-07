# Fixed original frontal region: corrected support adjustment

Requested follow-up: determine how much adding corrected MSPSS changes the FEVS
coefficient versus its precision. This is a read-only extraction from completed
analysis inputs, not a new whole-brain search or permutation analysis.

Both fits use the original 44-voxel negative-FEVS region (CDT3.1, p=.0303), the
same N=97 domain-by-valence VS-PPI image values, and the same original ten design
columns. The adjusted model adds only centered corrected Island screener MSPSS,
using its already executed design (rank11, df86 versus rank10, df87).

The original coefficient and HC3 interval must reproduce the published estimates
before the adjusted fit is reported. Outputs include coefficient, HC3 SE and 95%
t interval, OLS SE, CI width, and explicit magnitude/SE ratios. Native source and
completed-output fingerprints, cohort order, corrected-score provenance and both
completed-job receipts are verified. No participants, individual values, or input
paths are published. Repeated execution verifies/reuses the sealed extraction.

The fixed region was selected from the original same-sample analysis, so both
fits and confidence intervals remain descriptive. A regional comparison cannot
fully explain changes in voxelwise cluster extent or whole-brain permutation p.
Financial scoring remains provisional. Existing reports are preserved.

Launch on Linux2:

```bash
(
set -euo pipefail
cd /ZPOOL/data/projects/rf1-sra-environment-SD
git -c remote.origin.url=https://github.com/DVS-Lab/rf1-sra-environment-SD.git fetch origin main
bash <(git show FETCH_HEAD:code/launch_fevs_vs_fixed_roi_support.sh)
)
```

The launcher detaches, uses the existing completed-review environment, and
publishes aggregate results to `results/review/fevs-vs-fixed-roi-mspss-v1/` plus
run logs. Local source fingerprints stay in the ignored work directory. Completion
is `FIXED-ROI COMPARISON PUBLISHED`.
