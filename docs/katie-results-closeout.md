# Katie Results Closeout: Authorized November 7, 2026

This phase implements the user-supplied final-analysis brief. The cognitive export
and missing-subject recovery remain separate. No manuscript Results text is drafted.
The immutable original analysis-decision snapshot is preserved; the narrow new
scope is recorded in `config/katie_results_closeout_v1.json`.

## Scientific scope

Exactly two new randomise jobs add centered corrected Island screener MSPSS to
VS-PPI domain-by-valence `FEVS + PM2.5 + FEVS:PM2.5`. Original age/gender,
scanner-era, signed FD and tSNR differences, N=97, mask, image volumes, VS seed,
and all original numeric columns are unchanged. Only FEVS at mean PM2.5 is
contrasted, in both directions. Ten thousand permutations, seed 20261101,
Z-equivalent CDTs 2.6/3.1 converted with adjusted df=86; four new maps in total.
There is one short two-permutation native smoke test; it is not scientific inference.
No FEVS:MSPSS term or new whole-brain component search is added.

The rest is read-only extraction and descriptive modeling of fixed selected
regions: corrected ADI:MSPSS winning activation at CDT3.1, the original 44-voxel
negative FEVS VS-PPI region and its social/nonsocial win-loss components, and
HC3 conditional behavioral slopes at nearest observed 16th/50th/84th percentile
MSPSS scores. The existing behavioral model is reproduced only to recover the
HC3 covariance matrix; its coefficient and interval must match published corrected
results before the conditional contrasts are computed. No new behavioral formula.

No participant is omitted. Selected-cluster HC3 intervals, conditional curves,
Cook's distance and leave-one-out estimates are descriptive, not independent
confirmation. A positive ADI:MSPSS coefficient does not establish protective
buffering: the conditional slopes and meaning of the activation outcome matter.
Atlas tissue labels are not native tissue segmentation. Financial totals remain
unchanged and provisional; only versions/rules/timepoint documentation is pending.

## Execution and publication

The launcher uses an ignored frozen release and the existing base and pinned
review environments. It runs focused new tests and existing corrected-MSPSS /
FEVS-adjustment regression tests, publishes only sealed source files through an
isolated HTTPS clone, runs/resumes the two new jobs, creates validated aggregate
figures/tables, and publishes the evidence to
`results/review/katie-closeout-analysis-v1/`. The live branch/index is untouched.
Source publication rejects concurrent conflicting edits. Completed native jobs
are reused only when plan, commands and products still match. A coordinator lease
and inherited native lease prevent duplicate workers; interrupted attempts are
preserved, never reset or deleted. Repeating the launcher resumes its recorded
release. Missing inputs stop the relevant analysis rather than substituting data.

Local output roots:

- `derivatives/fsl/randomise/katie-vs-fevs-support-sensitivity-v1/`
- `work/katie-results-ready-v1/` (participant diagnostics and source paths remain here)

The evidence inventory reconciles all 1,328 original directional/CDT tests,
replacing exactly 384 historical MSPSS maps with the corrected 384. This yields
71 maps with passing clusters versus the historical 69, not independent findings.
All nulls remain listed. The four newly requested sensitivity maps are separate.
Completed 220-job extension and 64-job corrected-output fingerprints are rechecked.

After the evidence is inspected, the next phase assembles and visually checks a
new three-question PDF, compact evidence table, supplementary inventories and
short supported-conclusions Markdown file. Historical PDFs stay unchanged. The
final PDF/code/results package is then committed; no manuscript Results drafting.

Once this source is on main, normal launch is:

```bash
(
set -euo pipefail
umask 0000
cd /ZPOOL/data/projects/rf1-sra-environment-SD
git -c remote.origin.url=https://github.com/DVS-Lab/rf1-sra-environment-SD.git fetch origin main
bash <(git show FETCH_HEAD:code/launch_katie_closeout.sh)
)
```

The launcher fetches code only; no participant rows or native images are embedded
in the launch command. Publication uses explicit aggregate/source manifests.
