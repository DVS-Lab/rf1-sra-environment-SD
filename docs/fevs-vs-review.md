# FEVS VS-Connectivity Cluster Review

This read-only report maps the completed negative FEVS coefficient in
`connectivity/social_specific/fevsxpm25/z-3p1`. It preserves N=97, all exclusions,
running jobs, the original VS seed and every completed output/report.

**Outcome:** `[Social VS PPI(win-loss)] - [Nonsocial VS PPI(win-loss)]`.
This is the **domain-by-valence** task-modulated coupling contrast, not activation
and not Social win minus nonsocial win. A negative coefficient describes a
decreasing domain-by-valence coupling difference with FEVS, not globally weaker
VS connectivity. The contrast alone cannot identify whether wins or losses drive it.

**Coefficient:** the FEVS main effect at mean PM2.5 in the full FEVS + PM2.5 +
FEVS x PM2.5 model. It is not a moderation/JN test. All original age, gender,
scanner-era and signed FD/tSNR-difference terms remain in the design.

## Linux2

Run the whole block. No live checkout pull, SSH, SCP, rsync or inference rerun:

```bash
(
set -euo pipefail
umask 0000
cd /ZPOOL/data/projects/rf1-sra-environment-SD
git -c remote.origin.url=https://github.com/DVS-Lab/rf1-sra-environment-SD.git fetch origin main
bash <(git show FETCH_HEAD:code/launch_fevs_vs_review.sh)
)
```

It archives a separate reporting release under ignored `work/`, reuses the review
environment and runs detached via nohup. The lock belongs only to this report;
no analysis process is signalled or restarted. Progress is captured before/after.

The report verifies frozen source hashes, the native completed-job receipt,
full-rank design and actual negative-FEVS contrast, all 97 row/volume identities,
centered interaction products, permutation settings and model-specific CDT.
It explicitly uses the **connectivity mask and connectivity/social_specific 4D
stack**, never an activation or win-only fallback. The gzip stack is loaded once.

Outputs include blue signed-negative orthogonal brain views through every
surviving cluster peak, MNI/atlas locations and physical volumes. Each cluster
gets raw and covariate-adjusted FEVS scatterplots plus influence diagnostics:
HC3 intervals, Cook's D, leverage and leave-one-out coefficient ranges. All 97
participants remain; influence diagnostics create no exclusions. Statistical
images are never resampled, and no anatomy/atlas downloads are needed.

These are same-sample selected-cluster **descriptions, not independent
confirmation**. Mapwise cluster-FWE does not correct across the exploratory
model/outcome family. No voxelwise leave-one-out randomise tests are run.

After successful validation, aggregate PNGs, tables and the README automatically
publish through an isolated HTTPS clone to:

`results/review/fevs-vs-v1/README.md`

Subject-level influence tables and input fingerprints stay outside that report
in `work/fevs-vs-review-v1/`. Repeating the block verifies/reuses the sealed report
and refreshes progress; it does not overwrite completed plots.

Run records publish automatically with Linux2's `code/publish_run_logs.py`. If
publication fails, retry from any directory:

```bash
umask 0000
python3 /ZPOOL/data/projects/rf1-sra-linux2/code/publish_run_logs.py --project /ZPOOL/data/projects/rf1-sra-linux2
```
