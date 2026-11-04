# FEVS Behavioral Adjustment Checks: Provisional N=97

Requested November 4, 2026, after the original behavioral result. Three additive adjustment checks, all reported.
FEVS ~ PM2.5 + MSPSS + PM2.5:MSPSS + age + gender + listed additional covariates.
Same frozen 97 participants, scores and coding; no omissions, imputation, transformations or new neural models.
Financial item scoring remains unverified. Five MSPSS values below 1 remain as supplied; adding covariates does not validate them.
OLS with two-sided HC3 t inference. These are sensitivity estimates, not independent replications or newly designated primary tests.
Intervals/p values below are unadjusted across these correlated sensitivity fits. No model is selected by its p value.

| Added covariates | N | Interaction beta | HC3 95% CI | HC3 p | Single-case LOO beta range |
|---|---:|---:|---|---:|---|
| baseline | 97 | -0.8022 | [-1.2082, -0.3963] | 0.000168183 | [-0.9393, -0.7237] |
| adi | 97 | -0.8023 | [-1.2167, -0.3878] | 0.000224187 | [-0.9410, -0.7176] |
| ecog | 97 | -0.7140 | [-1.1344, -0.2936] | 0.00109318 | [-0.8305, -0.5853] |
| adi+ecog | 97 | -0.7109 | [-1.1365, -0.2852] | 0.00131257 | [-0.8331, -0.5884] |

Additive adjustment is not the same as adding exposure/moderator interactions. It changes the conditional association being estimated; it does not establish causal independence.
No completed neural or behavioral outputs were overwritten. Imaging adjustment questions require their own matched designs; these regressions cannot answer them.
