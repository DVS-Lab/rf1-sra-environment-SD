#!/usr/bin/env python3
"""Three requested additive-covariate sensitivity checks; never read neural images."""

import argparse
import json
from pathlib import Path

import numpy as np
import statsmodels.api as sm

import run_behavioral_moderation as behavior

ROOT = Path(__file__).resolve().parents[1]
ADJUSTMENTS = ((), ("adi",), ("ecog",), ("adi", "ecog"))


def fit(values):
    names, original = behavior.design(values, "pm25", "mspss")
    results = []
    for extra in ADJUSTMENTS:
        added = [values[name] - values[name].mean() for name in extra]
        x = np.column_stack([original, *added])
        if x.shape[0] != 97 or np.linalg.matrix_rank(x) != x.shape[1]:
            raise ValueError("Adjustment design must retain full-rank N=97")
        fitted = sm.OLS(values["fevs"], x).fit()
        robust = fitted.get_robustcov_results(cov_type="HC3", use_t=True)
        index = names.index("interaction")
        ci = robust.conf_int()[index]
        loo = [float(sm.OLS(np.delete(values["fevs"], i), np.delete(x, i, axis=0)).fit().params[index]) for i in range(97)]
        results.append(dict(adjustment="baseline" if not extra else "+".join(extra), n=97,
                            columns=x.shape[1], residual_df=int(fitted.df_resid),
                            interaction_beta=float(robust.params[index]), hc3_se=float(robust.bse[index]),
                            ci_lower=float(ci[0]), ci_upper=float(ci[1]), hc3_p=float(robust.pvalues[index]),
                            max_cooks_d=float(fitted.get_influence().cooks_distance[0].max()),
                            loo_beta_min=min(loo), loo_beta_max=max(loo)))
    return results


def build(output):
    ids, values = behavior.inputs(ROOT)
    sources = [ROOT / p for p in (behavior.ROSTER, behavior.SCORE_FILE, behavior.VARIABLES, behavior.SOURCE_RECEIPT)]
    sources += [Path(__file__), Path(behavior.__file__), Path(behavior.cohort.__file__)]
    before = {str(p.relative_to(ROOT)): behavior.sha(p) for p in sources}
    results = fit(values)
    original = behavior.table(ROOT / "results/review/behavioral-moderation-provisional-v1/interactions.tsv")[1]
    baseline = next(r for r in original if r["model"] == "fevs_pm25_mspss")
    if not np.isclose(float(baseline["interaction_beta"]), results[0]["interaction_beta"], atol=1e-10, rtol=0):
        raise ValueError("Baseline does not reproduce the completed behavioral model")
    if any(behavior.sha(ROOT / name) != expected for name, expected in before.items()):
        raise ValueError("Approved input changed during sensitivity checks")
    if output.exists():
        raise ValueError("Preserve existing sensitivity report; use an explicitly versioned destination")
    output.mkdir(parents=True)
    behavior.tsv(output / "adjustments.tsv", results)
    text = ["# FEVS Behavioral Adjustment Checks: Provisional N=97", "",
            "Requested November 4, 2026, after the original behavioral result. Three additive adjustment checks, all reported.",
            "FEVS ~ PM2.5 + MSPSS + PM2.5:MSPSS + age + gender + listed additional covariates.",
            "Same frozen 97 participants, scores and coding; no omissions, imputation, transformations or new neural models.",
            "Financial item scoring remains unverified. Five MSPSS values below 1 remain as supplied; adding covariates does not validate them.",
            "OLS with two-sided HC3 t inference. These are sensitivity estimates, not independent replications or newly designated primary tests.",
            "Intervals/p values below are unadjusted across these correlated sensitivity fits. No model is selected by its p value.", "",
            "| Added covariates | N | Interaction beta | HC3 95% CI | HC3 p | Single-case LOO beta range |",
            "|---|---:|---:|---|---:|---|"]
    for r in results:
        text.append(f"| {r['adjustment']} | 97 | {r['interaction_beta']:.4f} | [{r['ci_lower']:.4f}, {r['ci_upper']:.4f}] | {r['hc3_p']:.6g} | [{r['loo_beta_min']:.4f}, {r['loo_beta_max']:.4f}] |")
    text += ["", "Additive adjustment is not the same as adding exposure/moderator interactions. It changes the conditional association being estimated; it does not establish causal independence.",
             "No completed neural or behavioral outputs were overwritten. Imaging adjustment questions require their own matched designs; these regressions cannot answer them.", ""]
    (output / "README.md").write_text("\n".join(text))
    behavior.write_json(output / "provenance.json", dict(n=len(ids), provisional=True, exclusions_changed=False,
                        neural_analyses_changed=False, model_family=[list(a) for a in ADJUSTMENTS], inputs=before,
                        outputs={p.name: behavior.sha(p) for p in output.iterdir()},
                        note="Published aggregate sensitivity checks using the approved score export, not item-validated scores"))
    print((output / "README.md").read_text())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "results/review/fevs-behavioral-adjustments-provisional-v1")
    args = parser.parse_args()
    build(args.output)
