# Katie/Social Doors: Model Decisions Before Randomise

**Status: scientific model agreement pending. No design or randomise job has
been generated or run by the cohort freeze.**

## Fixed Inputs and Decisions

- The cohort is the [frozen 97-person intersection](katie-cohort.md), with the
  existing source-validity and per-run coverage/FD/tSNR exclusions preserved.
- Analysis is age-55+, session 01; one observation per retained participant for
  a chosen matched Social Doors minus Doors COPE contrast.
- Existing L1 estimates are sm5, base-only/no-TEDANA, not the later experimental
  AFNI 6-mm outputs. Do not change that lineage as part of model setup.
- Four matched differences are available. Contrast 4 is
  **(Social Doors win-loss) minus (Doors win-loss)**. It is not a difference of
  z/t maps, and it is not the cross-task average.
- The current repository's legacy randomise runner also computes the cross-task
  mean and tests an intercept-only design. That does not establish that the mean
  is a primary hypothesis or that these are Katie's environmental models.

## Decisions to Agree With the User

| Item | Available information | Decision not yet established in the repository |
| --- | --- | --- |
| Primary image outcome | Four matched COPE differences | Whether win-loss alone is primary; which other contrasts, if any, are confirmatory or exploratory |
| Environmental predictors | National ADI rank; 2013-2023 mean PM2.5 | Separate exposure models, joint adjustment, or both; primary estimands and coefficient tests |
| MSPSS | Complete social-support score | Predictor, moderator with a named exposure interaction, or adjustment variable |
| ECog | Complete cognitive-function score | Predictor, moderator, adjustment, or separate secondary analysis |
| Age and gender | Raw values/codes for all 97 | Exact adjustment/coding; source codebook is authoritative |
| Scanner era | Upstream BIDS software metadata is available on Linux2 | Era categories/reference and adjustment; must be extracted and aligned, not guessed from participant ID |
| Paired QC | Signed FD/tSNR differences and pair means available from the bundle builder | Which terms are primary nuisance covariates and which belong in sensitivity analyses |
| Interactions | Can be built after centering is specified | Only named, justified interactions; retain their constituent main effects |
| Inference family | Legacy runner uses TFCE and 10,000 permutations | Hypotheses/directions, contrast/model family and any correction across it; do not treat voxelwise correction as automatic correction across every model |
| Dependence | One selected observation per participant | Any known family/repeated-participant dependence requiring exchangeability restrictions |

These are discussion items, not automatically selected regressors. We do not
need another exclusion audit, a new screener export, or a new ID list from Jacob
to discuss them. The linked workbook already supplies the 97 IDs and the seven
approved analysis fields.

## Design Checks Once the Formulas Are Agreed

Center continuous columns in the final 97-person cohort, not the old 110 or
121-person groups. Preserve one documented row order across images, masks,
predictors and QC terms. Record coding and transformation constants. Check
missingness, full design rank, residual degrees of freedom, conditioning and
correlations before executing any model. Do not select terms based on whether
their inclusion produces a desired image result.

The old workbook builder assumes 0=male and 1=female. The frozen data preserve
the source codes, with 48 zeros and 49 ones. They have not been reinterpreted.
With these two categories, the two centered male/female indicators are exact
negatives; **do not put both in a design**. After confirming source semantics,
use a single documented indicator/reference with the intercept if that adjustment
is agreed. Likewise, do not combine all original task QC metrics with their
derived means and differences: those are linear combinations, not independent
extra information.

QC covariates adjust a model after selection; they do not replace settled
absolute-quality gates or prove that measurement-error differences are removed.
An interaction model needs a documented construction and coefficient contrast,
not a blanket inclusion of all available interactions.

FSL's [randomise documentation](https://fsl.fmrib.ox.ac.uk/fsl/docs/statistics/randomise.html)
describes including nuisance regressors in the main design matrix, testing
contrasts against that full design, and specifying exchangeability blocks when
observations are dependent. Statistical design files and the launch command will
be implemented only after the model specifications are agreed.
