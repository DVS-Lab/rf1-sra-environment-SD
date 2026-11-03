# Complete Katie Activation And Connectivity Review

## Launch On Linux2

```bash
cd /ZPOOL/data/projects/rf1-sra-environment-SD
git -c remote.origin.url=https://github.com/DVS-Lab/rf1-sra-environment-SD.git fetch origin main
bash <(git show FETCH_HEAD:code/launch_katie_review.sh) --jobs 24
```

The launcher uses nohup/setsid. It freezes reporting code into ignored work/,
does not pull/reset/switch the live checkout, and uses umask 0000. There are
**no new randomise, FEAT, preprocessing, smoothing or exclusion decisions**.
Workers hash files or render figures, not run new inference. `--jobs` may be
1..48; 24 is the initial rendering/hash cap, not a change to completed analyses.

A separate versioned `work/venv-katie-review-REQUIREMENTS_HASH` installs the
tested pinned plotting/statistics dependencies. Existing analysis environments
are not upgraded. A local MNI152NLin6Asym TemplateFlow anatomy is preferred;
otherwise the installed FSL MNI152 T1 background is used **for display only**,
with the chosen filename/hash recorded. There is no template download or data
resampling saved back into the analysis tree. Network is needed for first-time
Python installation and HTTPS Git publication, not for rerunning MRI tools.

Background selection checks the file contents, not just existence. TemplateFlow
can contain zero-byte cache placeholders. Empty, corrupt, nonfinite or constant
anatomical candidates are rejected before launching rendering workers, and the
installed FSL background is tried next. The rejected candidates and selected
background are logged. Nothing is downloaded, deleted or repaired in the cache.
This fixes the 2026-11-02 review failure: the data audit passed, 64 association
plots completed, but all 84 brain panels hit an empty TemplateFlow placeholder.
The retry leaves the renderer unchanged, so those completed PNG receipts are
reused; only previously failed brain panels are newly rendered. No inference
or preprocessing is repeated.

Progress:

```bash
cd /ZPOOL/data/projects/rf1-sra-environment-SD
tail -40 "$(ls -1t logs/runs/katie-review-*.nohup.out | head -1)"
```

Run records publish automatically on exit, including failure. Manual publication:

```bash
python3 /ZPOOL/data/projects/rf1-sra-linux2/code/publish_run_logs.py --project /ZPOOL/data/projects/rf1-sra-linux2
```

## Audit Scope

| Batch | Jobs | Directional Maps |
|---|---:|---:|
| Environmental activation | 24 | 48 |
| Conditional constituent activation effects | 16 | 64 |
| Group activation: Social, Doors, average, difference | 8 | 16 |
| Environmental VS connectivity | 24 | 48 |
| FEVS / secondary OAFEM predictors | 16 | 32 |
| Financial two-way moderation | 64 | 128 |
| Total | 152 | 336 |

The audit requires all success receipts. It validates plan and generated-file
hashes, the deduplicated full source/result fingerprint graph, exact 97-person
matrix/volume order, finite full-rank designs, actual native commands, all
contrast vectors, 10,000 permutations, fixed seed, residual degrees of freedom,
Z-to-t CDTs, masks, grids, and corrected-map probabilities. It confirms native
sign flipping for the group intercept. Significant voxels must exceed their
declared CDT. Both directions and both CDTs are retained, including every null.

The 194 actual activation COPEs are independently mapped back to participant
volumes, and their average/difference arithmetic is checked. Actual L1 FSFs,
contrasts and feedback EVs are reread against BIDS under the already-settled
onset formatter rule. The 194 PPI source receipts/designs/EVs/seed series are
revalidated for matching no-TEDANA input lineage, then independently matched to
the two PPI stacks and paired arithmetic. No sources are renamed, split or fixed.
The source/result hash graph is rechecked after plotting to catch mid-review
changes. Inputs remain sm-5 FEAT, not the experimental 6-mm AFNI evaluation.

## Brain Images

The review produces **84 brain panels**, combining the two directions and both
CDTs for each tested effect. Each panel shows unthresholded signed t values for
context, the corrected CDT 2.6 result, and the corrected CDT 3.1 result. Null
panels explicitly say that no corrected cluster survived. Red/blue refer to
positive/negative coefficients, not to positive/negative raw brain activity.
Backgrounds, orientation labels, z coordinates and color bars are shown. No
atlas/network labels or clinical mechanisms are guessed from peak coordinates.

## Scatterplots And Johnson-Neyman Plots

For each surviving cluster at each CDT/direction, regional participant estimates
are extracted in frozen roster order and fit with **the actual frozen design**.
These plots are selection-dependent descriptive follow-ups: they cannot provide
an independent p-value confirming the cluster that selected the region.

Simple associations show raw scatterplots and nuisance-adjusted partial-residual
scatterplots with pointwise OLS intervals. Interaction panels show:

- The conditional focal-predictor slope over the observed moderator range.
- OLS 95% pointwise t intervals and an HC3 covariance sensitivity overlay.
- JN boundaries restricted to observed values, with a rug showing data support.
- Fitted associations at the moderator's 16th/50th/84th observed percentiles.
- Residuals and Cook's D, leverage and leave-one-out coefficient diagnostics.

JN calculations use [statsmodels OLS and contrasts](https://www.statsmodels.org/stable/generated/statsmodels.regression.linear_model.OLS.html)
and the standard conditional-slope covariance quadratic; the observed-range,
residual-df, pointwise interpretation follows the
[Johnson-Neyman documentation](https://interactions.jacob-long.com/reference/johnson_neyman.html).
No FDR control over moderator values or spatial correction is claimed for these
regional intervals. They do not replace the existing permutation-corrected map.
HC3 is a sensitivity description, not a new whole-brain correction.

All subjects stay in the model; influence flags do not cause exclusions.
Residual SD by scanner era is reported descriptively. OAFEM is not transformed,
winsorized or selectively trimmed. The dependent variable is the neural estimate,
not FEVS/OAFEM; this is not a reverse regression or mediation model. Higher Ecog
is described as a score level, not demonstrated longitudinal cognitive decline.

An anatomical VS activation ROI adds a group response check and association/JN
plots for all focal activation models, including nulls. It is exploratory ROI
inference, not a new whole-brain result. **No VS seed self-connectivity ROI is
invented for PPI.** A null connectivity map has no selected cluster to plot.

The report also includes Pearson/Spearman factor correlations, full maps.tsv,
clusters.tsv, regional fits/JN intervals, source provenance, and a static HTML
gallery. Environmental conditional main effects exist for activation but not
connectivity; financial moderation batches did not separately whole-brain-test
their constituent main effects. These gaps are documented, not silently filled
with new randomise jobs. Three-way interactions remain absent.

## Publication And Preservation

Local report: `work/katie-review-v1/report/index.html`.
Detailed per-participant influence tables: `work/katie-review-v1/participant-diagnostics/`.
Both remain lab-readable under umask 0000. The work location avoids dirtying the
frozen live checkout; it is not a claim that paths are sensitive.

After validation, aggregate PNGs, tables, Markdown and HTML are committed/pushed
automatically to `results/review/katie-review-v1/` on GitHub through an isolated
temporary clone directly from the HTTPS remote (not from the shared live .git
directory). This avoids shared-ownership clone failures without adding global
safe.directory exceptions or changing ownership/permissions. No SCP/rsync, force push, live-index change, or source
image publication is used. Participant-level influence tables are not in that
published payload. Ordinary Git fetch/pull can retrieve the published figures
on the Mac after the run completes.

Start here after successful publication:

https://github.com/DVS-Lab/rf1-sra-environment-SD/blob/main/results/review/katie-review-v1/README.md

If a completed review failed only during publication, rerun the same three-line
launcher above. An existing sealed review skips the audit/figure builders,
rechecks its artifacts and original source hashes, and retries publication only.
It does not rerender or rerun any analysis.

The HTML is useful locally; GitHub itself displays HTML source, not an executed
website. The README links directly to PNGs that GitHub renders.

If interrupted, rerun the same frozen release: completed figure receipts are
reused after hash/specification checks. Existing changed reports/figures are
not silently overwritten. Production images, completed randomise jobs, original
reports, N=97 and settled exclusions are untouched throughout.
