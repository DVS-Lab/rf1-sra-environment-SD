# Katie/Social Doors: Inherited Models and Remaining Decisions

**Status: six inherited model structures adapted to N=97 as numerical previews.
No FSL design files or randomise jobs have been created.** The settled cohort
and exclusion decisions are unchanged. The remaining choices concern paired QC
adjustment and inference, not whether ADI/MSPSS/ECog moderation was ever intended.

## What Jacob Already Specified

The [UG repository](https://github.com/DVS-Lab/rf1-sra-environment-UG/tree/cf8707b2b948130f4374c31951a9e1bccef004c8)
contains six distinct model structures. Its current FSF templates use one gender
indicator, age, mean FD, tSNR, and two scanner indicators (E11 and XA30, with XA60
as reference) alongside the scientific terms below. Continuous predictors are
mean-centered, interactions are products of the centered constituent terms, and
orthogonalization is disabled.

| Model | Scientific terms beyond the common adjustments | Focal positive/negative coefficient tests |
| --- | --- | --- |
| `adi` | ADI | ADI |
| `pm25` | PM2.5 | PM2.5 |
| `adixmspss` | ADI + MSPSS + ADI x MSPSS | ADI x MSPSS |
| `pm25xmspss` | PM2.5 + MSPSS + PM2.5 x MSPSS | PM2.5 x MSPSS |
| `adixecog` | ADI + ECog + ADI x ECog | ADI x ECog |
| `pm25xecog` | PM2.5 + ECog + PM2.5 x ECog | PM2.5 x ECog |

This is a **separate-exposure** family, not one model containing both exposures
and all interactions. The `adi2` FSF is byte-identical to `adi`; it is not a
seventh or quadratic model. The source template audit verifies the model terms,
focal contrasts and full-rank numeric matrices. Small product discrepancies
reflect rounded FSF values rather than a different interaction formula.

The UG runner defaults to `adi` and uses **FLAME1**, not randomise. Available
templates are evidence of specified models, not proof that every model was run.
Its generic model workbook still has both centered gender indicators, while the
latest FSFs correctly retain one. We adapt the latest FSFs' structure, not that
redundant workbook design or the old 116-person values/paths.

The earlier `Katie_Methods_clean.docx` draft is consistent with this scientific
structure: its research questions and group-level models section specify ADI
associations and separate moderation by social support or everyday cognitive
decline. Its neuroimaging analyses section defines the social-minus-monetary
feedback-valence outcome. It also discusses PPI/connectivity, which is a separate
analysis not added to this activation batch.
The draft describes FLAME1/cluster inference; the current requested implementation
is randomise/TFCE, so the methods will need that implementation update rather
than wholesale invention of new hypotheses. `FINAL_PIPELINE_METHODS.docx`
describes centered covariates and K-1 software indicators but has older cohort
counts and cannot override the frozen imaging handoff.

Source-document identities for this read-only comparison (no Word documents
were edited or republished):

- `Katie_Methods_clean.docx`, SHA256
  `274ae06ff9490c830d573f560b809890ac6e9e4bfa3878737dcdb9447112c9e2`.
- `FINAL_PIPELINE_METHODS.docx`, SHA256
  `fd9a111290a93c27f00bdd5bd8f06f796fb8075ae941ae5428743372cfa3dcac`.

## Outcomes Now Specified by the User

Write S for Social Doors win-minus-loss and D for Doors win-minus-loss.

- **Primary social-specific outcome:** S - D.
- **Secondary general reward-valence outcome:** (S + D) / 2.

Both use the same frozen 97 participants and existing sm5/base-only/no-TEDANA
L1 estimates, not the experimental AFNI 6-mm products. These are COPE effects,
not z/t differences. The original Social Doors runner already contained both
the difference and average outcomes, although its design was intercept-only.

The average is a useful secondary question, but an association with it is not
evidence of social specificity. Plan to estimate and report it as secondary
regardless of whether S-D reaches significance, rather than selecting the outcome
after seeing the maps. No outcome-based participant exclusions or changes to the
settled absolute-quality gates are introduced.

## Correlations in the Actual Frozen N=97 Sample

These are unadjusted correlations, with no pairwise deletion and no new filtering.

| Pair | Pearson r | Spearman rho |
| --- | ---: | ---: |
| ADI / PM2.5 | 0.062 | 0.188 |
| ADI / MSPSS | -0.201 | -0.159 |
| ADI / ECog | 0.243 | 0.226 |
| PM2.5 / MSPSS | 0.034 | -0.036 |
| PM2.5 / ECog | 0.087 | 0.095 |
| MSPSS / ECog | -0.191 | -0.266 |

The four scientific predictors have predictor-only VIFs of 1.01-1.09 when entered
together. They are not strongly redundant in this sample. This is not a reason
to add an unplanned joint model or evidence that they are independent. Jacob's
separate-exposure models remain the starting structure. Higher ECog indicates
greater reported everyday decline, not a clinical diagnosis or measured
longitudinal decline.

The stored field named `mspss_sum` ranges from 0 to 7, with one zero; ECog ranges
from 1 to 2.917. Values are preserved exactly as supplied. Before final reporting,
document the exported scale scoring and whether zero is a valid response/score
rather than assuming the MSPSS field is a literal questionnaire total. This is
a scoring check, not a newly applied imaging exclusion.

## Adaptation and Numerical Checks Already Completed

[Review outputs](../data/derived/model-review-v1/) include the six-model catalog,
source-template audit and hashes, correlation table, aligned raw and centered
terms, and two paired-QC variants of every design (12 previews). Every row follows
the canonical [97-person roster](../data/derived/katie-cohort-v1/subjects.tsv).

The inherited seven common terms are intercept, two QC variables, two scanner
indicators, one gender indicator, and age. Replacing the exposure/moderator values
with the current 97-person data gives eight-column main-effect models and
ten-column interaction models. All 12 previews are full rank, leaving 89 or
87 residual degrees of freedom. Across these previews the largest VIF is 2.80
and the largest standardized condition number is 3.16. These are design checks,
not image results and not automatic approval of a nuisance strategy.

The scanner snapshot assigns 25 E11, 5 XA30 and 67 XA60 participants, with matching
labels for both tasks. The preview keeps XA60 as reference, matching Jacob's
templates. The live selected BIDS sidecars and final image order must still be
verified on Linux2 before execution; source paths are not inferred from ID order.

Interactions retain both constituent main effects. We keep Jacob's product of
the mean-centered main terms, without orthogonalization. The product itself need
not have mean zero. The gender term is one centered source-code indicator, not
both male/female dummies. Changing which binary category is the reference does
not change the other coefficients' fits or tests.

## What Genuinely Still Needs Agreement

1. **Paired QC mapping.** Jacob used FD/tSNR from the selected UGR input. We have
   two runs here, so copying only Social Doors' QC is not an equivalent adjustment.
   The previews compare pair-mean FD/tSNR (overall pair quality) with signed
   Social-minus-Doors FD/tSNR (task imbalance). A reasonable proposal is signed
   differences for S-D and pair means for the average, with an explicitly labeled
   sensitivity check for overall quality in S-D. This is a proposal, not a choice
   made by the code. Do not choose based on which version produces significance.
2. **Inference family and reporting.** The requested six models across two
   outcomes give 12 focal coefficient/outcome questions, each with positive and
   negative directions. Agree how the exploratory family and directions will be
   handled. Per-map TFCE/FWE does not by itself correct across separate models,
   outcomes or tail-specific maps. The legacy group-mean/age contrasts need not
   silently become additional primary environmental hypotheses.
3. **Scope beyond this inherited family.** A joint ADI+PM2.5 model could be a
   labeled sensitivity analysis given the modest correlation, but is not required
   to reproduce Jacob's model family. Do not add three-way interactions, split
   participants by significance, or introduce PPI/ROI claims in this activation
   batch without an explicit separate plan.

There is no need to revisit the cohort, thresholds, source exclusions, or to ask
Jacob for another ID list. Model structures and centered coding are already
specified. The code produces only review TSVs, not `design.mat`, `design.con`,
images or randomise commands. The 97-person image subset still needs the
[documented Linux2 build/check](katie-cohort.md).

To reproduce the review with both repositories checked out beside this one:

```bash
python3 code/review_katie_models.py check \
  --upstream ../rf1-sra-linux2 --ug-root ../rf1-sra-environment-UG
```

Requires Python >=3.11, numpy, pandas and openpyxl. For an alternate source-repo
location, pass its actual root; missing source inputs fail rather than changing N.

FSL's [randomise documentation](https://fsl.fmrib.ox.ac.uk/fsl/docs/statistics/randomise.html)
describes testing contrasts against the full design including nuisance terms,
and exchangeability restrictions for dependent observations. Scientific model
and family agreement precede executable designs and randomise.
