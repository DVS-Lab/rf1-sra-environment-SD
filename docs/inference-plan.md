# Approved Exploratory Randomise Plan

The user's latest instruction supersedes the earlier discussion of joint FWER
and PALM. **Use randomise, cluster extent, and both requested cluster-forming
thresholds. No PALM or TFCE.** The plan is in
[analysis_decisions.json](../config/analysis_decisions.json).

## Inputs and Models Stay Fixed

- Keep the same frozen **97 participants**, the settled source/coverage/FD/tSNR
  exclusions, and the six inherited exposure/moderation models.
- Primary social-specific outcome: Social Doors win-loss minus Doors win-loss.
  Its nuisance QC terms are signed FD/tSNR differences.
- Secondary average outcome: (Social Doors win-loss + Doors win-loss)/2.
  Its nuisance QC terms are the pair means.
- Use the existing sm5/no-TEDANA L1 estimates. Do not add preprocessing, smoothing,
  TEDANA, source-identity changes, new participants or new exclusions.

## Thresholds and Inference

Run permutation-based **cluster-extent FWE correction within each map**, retaining
the conventional cluster-FWE p<0.05 rule and the existing SD runner's 10,000
permutations. Use both **Z-equivalent cluster-forming thresholds 2.6 and 3.1**.
These define which voxels enter candidate clusters; they are not the final
cluster-level corrected p-value cutoff.

Randomise's `-c` option takes a **t-statistic threshold** for t contrasts. Do not
blindly pass `-c 2.6` or `-c 3.1` and label the results Z=2.6/Z=3.1. Match their
one-sided Gaussian tail probabilities using the residual degrees of freedom:

```text
t_cutoff = qt(pnorm(z_cutoff), df = N - rank(design))
```

The current full-rank previews give:

| Model type | Residual df | Z-equivalent 2.6: t cutoff | Z-equivalent 3.1: t cutoff |
| --- | ---: | ---: | ---: |
| ADI or PM2.5 main effect (8 columns) | 89 | 2.65785388280732 | 3.19496506641500 |
| Exposure x moderator (10 columns) | 87 | 2.65921204869935 | 3.19721001565352 |

Values were computed with base R `stats::qt` and `stats::pnorm`, not a custom
distribution approximation. The corresponding one-sided probabilities are
0.0046611880 and 0.0009676032. Recompute from the actual final matrix rank before
execution, and fail if it differs from the checked plan; do not hard-code the
same df for every model. Use the same positive cutoff for the positive and
negative contrast rows, which reverse the coefficient sign themselves.

Cluster extent uses `-c`, not the cluster-mass `-C` option. Its corrected output
is `*_clustere_corrp_tstat*`. Randomise stores **1-p**, so cluster-FWE p<0.05
corresponds to values greater than 0.95 in these corrected maps. Do not use the
uncorrected cluster p maps or raw t images to declare corrected significance.
Do not include `-T`/`--T2` in the launch command.

## Exploratory Reporting Scope

The user does not want an extra cross-model/outcome correction. We will therefore
**not** apply the previously discussed 12/24-test Bonferroni rule or substitute
PALM. The cluster-FWE rule is per map; it does not establish 5% FWER across all
models, outcomes, both directions and both cluster-forming thresholds.

There are six focal model coefficients x two outcomes = 12 coefficient/outcome
questions. Positive and negative contrasts yield 24 one-sided maps at each CDT,
48 across the two CDTs. Each map has its own spatial cluster-FWE correction.
Do not call these separately thresholded positive/negative maps a jointly
two-sided 5% FWER test.

Report both threshold analyses and identify the cross-model/outcome results as
exploratory. The two CDTs are sensitivity analyses, not independent replications
and not two opportunities to select whichever gives the preferred result.
The average remains secondary, not evidence of social specificity and not a
participant-selection rule. Keep all effect directions, tested models, thresholds
and null results traceable in the run manifest/report.

## Execution Status

These settings are recorded but **no group inference has been launched**. The
97-person image subset, average images, live BIDS-era metadata, exact subject
order and final designs still need the Linux2 build/check before execution.
The local numerical previews establish full rank; they do not validate images
that are not present on this Mac. Final runs should record the actual randomise
version, mask, design/contrast hashes, seed, permutation count and converted t
cutoff. Preserve any completed outputs; do not overwrite earlier analyses.

## Source

[FSL randomise documentation](https://fsl.fmrib.ox.ac.uk/fsl/docs/statistics/randomise.html)
documents `-c` cluster-extent inference for t contrasts, cluster-corrected outputs,
their spatial FWE scope and the 1-p convention. This is permutation-based cluster
inference, not switching back to the older FLAME parametric cluster procedure.
