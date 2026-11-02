#!/usr/bin/env python3
"""Build separate FEVS/OAFEM predictor previews; never change running analyses."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

import numpy as np
from scipy.stats import skew

import review_katie_models as review

ROOT = Path(__file__).resolve().parents[1]
SCORES = ROOT / "data/derived/FEVS_OAFEM_scores_katie-cohort-v1.csv"
FIELDS = {"fevs": "fevs", "oafem": "OAFEM"}


def read_scores(path, ids):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["sub-num", "fevs", "OAFEM"]:
            raise ValueError("Expected only the approved RF1 ID and two score columns")
        rows = list(reader)
    lookup = {}
    order = []
    for row in rows:
        subject = review.cohort.identifier(row["sub-num"])
        if subject in lookup:
            raise ValueError("Duplicate financial-score RF1 ID")
        values = {name: review.cohort.numeric(row[field]) for name, field in FIELDS.items()}
        if any(value < 0 for value in values.values()):
            raise ValueError("Unexpected negative financial score; do not silently recode")
        lookup[subject] = values
        order.append(subject)
    if len(ids) != 97 or len(set(ids)) != 97 or set(lookup) != set(ids):
        raise ValueError("Financial-score IDs must match the frozen 97-person cohort exactly")
    return [dict(subject=sub, **lookup[sub]) for sub in ids], order == ids


def design(terms, score, name, mode):
    names = ["ones", *review.QC_OPTIONS[mode], "e11", "xa30", "gender_code1", "age", name]
    x = np.column_stack([terms[n] for n in names[:-1]] + [review.center(score)])
    if x.shape != (97, 8) or not np.isfinite(x).all() or np.linalg.matrix_rank(x) != 8:
        raise ValueError("Financial design must be finite, full rank and N=97")
    standardized = (x[:, 1:] - x[:, 1:].mean(axis=0)) / x[:, 1:].std(axis=0, ddof=1)
    vif = np.diag(np.linalg.inv(np.corrcoef(standardized, rowvar=False)))
    q, _ = np.linalg.qr(x, mode="reduced")
    leverage = np.sum(q ** 2, axis=1)
    diagnostic = dict(score=name, qc_mode=mode, n=97, rank=8, columns=names, residual_dof=89,
                      max_vif=float(vif.max()), score_vif=float(vif[-1]),
                      standardized_condition_number=float(np.linalg.cond(np.column_stack([np.ones(97), standardized]))),
                      max_leverage=float(leverage.max()), leverage_threshold_2p_over_n=16 / 97,
                      n_above_leverage_diagnostic=int((leverage > 16 / 97).sum()),
                      exclusions_made=False, leverage_is_not_an_exclusion_rule=True)
    return names, x, leverage, diagnostic


def generate(scores_path=SCORES):
    roster = ROOT / "data/derived/katie-cohort-v1/subjects.tsv"
    _, subjects = review.cohort.read_table(roster)
    ids = [row["subject"] for row in subjects]
    _, raw = review.cohort.read_table(ROOT / "data/derived/model-review-v1/aligned_raw_terms.tsv")
    _, centered = review.cohort.read_table(ROOT / "data/derived/model-review-v1/centered_candidate_terms.tsv")
    if [r["subject"] for r in raw] != ids or [r["subject"] for r in centered] != ids:
        raise ValueError("Frozen original covariate/roster order differs")
    old = ROOT / "data/derived/model-review-v1"
    for name, digest in json.loads((old / "provenance.json").read_text())["outputs"].items():
        if review.cohort.digest(old / name) != digest:
            raise ValueError("Original numerical preview changed: " + name)
    scores, same_order = read_scores(scores_path, ids)
    terms = {name: np.array([float(r[name]) for r in centered]) for name in centered[0] if name != "subject"}
    joined = [dict(r, **{name: s[name] for name in FIELDS}) for r, s in zip(raw, scores)]
    labels = ["fevs", "oafem", "adi", "pm25", "mspss", "ecog"]
    r, rho = review.correlations([[float(row[name]) for name in labels] for row in joined])
    correlations = [dict(variable_1=a, variable_2=b, n=97, pearson_r=float(r[i, j]), spearman_rho=float(rho[i, j]))
                    for i, a in enumerate(labels) for j, b in enumerate(labels) if i < j]
    distributions, frequencies = {}, []
    for name in FIELDS:
        values = np.array([row[name] for row in scores])
        distributions[name] = dict(n=97, missing=0, zero_count=int((values == 0).sum()),
            minimum=float(values.min()), maximum=float(values.max()), mean=float(values.mean()),
            median=float(np.median(values)), sd=float(values.std(ddof=1)), skewness=float(skew(values, bias=False)))
        unique, counts = np.unique(values, return_counts=True)
        frequencies.extend(dict(score=name, value=float(value), n=int(n)) for value, n in zip(unique, counts))
    files = {"aligned_scores.tsv": review.tsv(scores), "correlations.tsv": review.tsv(correlations),
             "score_distributions.json": review.cohort.json_text(distributions), "score_frequencies.tsv": review.tsv(frequencies)}
    diagnostics, leverages = [], []
    for outcome, mode in (("social_specific", "signed_differences"), ("average", "pair_means")):
        for score in FIELDS:
            names, x, leverage, info = design(terms, [row[score] for row in scores], score, mode)
            diagnostics.append(dict(outcome=outcome, **info))
            prefix = f"previews/{outcome}/{score}/"
            files[prefix + "design.tsv"] = review.tsv([dict(subject=sub, **dict(zip(names, row))) for sub, row in zip(ids, x)])
            # Numerical previews only; live image lineage is checked separately before launch.
            contrasts = [dict(name=score + "_" + direction, **{n: weight if n == score else 0 for n in names})
                         for direction, weight in (("positive", 1), ("negative", -1))]
            files[prefix + "contrasts.tsv"] = review.tsv(contrasts)
            leverages.extend(dict(subject=sub, outcome=outcome, score=score, leverage=float(value),
                                  above_2p_over_n=bool(value > 16 / 97), exclusion=False) for sub, value in zip(ids, leverage))
    catalog = dict(status="numerical_previews_only_not_launched", n=97, lead_supplemental_score="fevs",
        models={name: dict(source_field=field, role="separate_continuous_predictor", centering="mean_centered_raw_score",
                           transformation="none", interactions=False) for name, field in FIELDS.items()},
        outcomes=dict(social_specific="(Social win-loss)-(Doors win-loss)", average="((Social win-loss)+(Doors win-loss))/2"),
        qc=dict(social_specific="signed_differences", average="pair_means"),
        common_covariates=["age", "gender_code1", "e11", "xa30", "two_outcome_specific_QC_terms"],
        additional_adjustment_for_adi_pm25_mspss_ecog=False, cohort_changed=False, exclusions_changed=False,
        source_file_order_already_matches_roster=same_order, join_method="RF1_ID_keyed_then_frozen_roster_order",
        image_families="activation_first; same designs can later be applied to lineage-validated VS PPI",
        future_jobs_per_image_family=8, interpretation="Association, not causation; score direction follows Jacob's scoring",
        scoring_metadata_supplied_in_csv=False, imputation=False, zero_scores_preserved=True)
    files["model_catalog.json"] = review.cohort.json_text(catalog)
    files["design_diagnostics.json"] = review.cohort.json_text(diagnostics)
    files["leverage_diagnostics.tsv"] = review.tsv(leverages)
    text = ["# FEVS and OAFEM: Separate Predictor Previews", "",
        "All 97 frozen participants have finite numeric FEVS and OAFEM scores, with unique matching RF1 IDs.",
        "The source order also matches, but the join is explicitly by ID. No rows were dropped, imputed or reordered incorrectly.",
        "FEVS leads these supplemental financial-score models; OAFEM is secondary. Original ADI/PM2.5 models are unchanged.", "",
        "Each separate model contains the score, age, one gender indicator, two scanner-era indicators, and two QC terms.",
        "Social-specific outcome uses FD/tSNR differences; the domain average uses pair means. All four designs are",
        "full rank (8 columns, N=97, residual df=89), with positive/negative score contrasts. No interactions or joint-score",
        "model, additional covariate adjustment, score transformations or new exclusions were introduced.", "",
        "| Score | N | Range | Mean | SD | Zero scores | Skewness |", "|---|---|---|---|---|---|---|"]
    for name, value in distributions.items():
        text.append(f"| {name.upper()} | 97 | {value['minimum']:g}-{value['maximum']:g} | {value['mean']:.2f} | {value['sd']:.2f} | {value['zero_count']} | {value['skewness']:.2f} |")
    text += ["", "OAFEM has a right tail and a substantial zero mass. Leverage diagnostics are descriptive, not exclusions.",
             "Any transformation or influence sensitivity must be specified explicitly, not selected to obtain significance.",
             "The CSV does not document instrument version, score direction, missing-item rules or source timepoint;",
             "Jacob should document these alongside the score file, including that zeros are genuine scores rather than missing codes.",
             "Numeric completeness is not independent verification of the scoring calculation.", "",
             "These are previews only. No FSL/randomise process was launched and no live images were read or changed.",
             "Do not pull or edit frozen running code on Linux2 to inspect these files; review them on GitHub for now.", ""]
    files["README.md"] = "\n".join(text)
    paths = [scores_path, roster, old / "aligned_raw_terms.tsv", old / "centered_candidate_terms.tsv", old / "provenance.json", Path(__file__)]
    sources = [dict(path=str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else path.name, sha256=review.cohort.digest(path)) for path in paths]
    files["provenance.json"] = review.cohort.json_text(dict(sources=sources,
        outputs={name: hashlib.sha256(text.encode()).hexdigest() for name, text in files.items()},
        original_code_or_config_changed=False, live_processing_changed=False))
    return files, catalog


def main():
    os.umask(0)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "check"))
    parser.add_argument("--output", type=Path, default=ROOT / "data/derived/financial-model-review-v1")
    args = parser.parse_args()
    files, catalog = generate()
    if args.command == "build" and not args.output.exists():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".financial-review-", dir=args.output.parent)); staging.chmod(0o777)
        for name, text in files.items():
            path = staging / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
        staging.rename(args.output)
    review.verify(args.output, files)
    print("CHECK PASSED: complete N=97 financial scores; exact ID join; four full-rank separate-predictor previews; no exclusions or launches.")
    print(review.cohort.json_text(catalog))


if __name__ == "__main__":
    try: main()
    except Exception as exc:
        print(f"FAILED ({type(exc).__name__}): {exc}", file=sys.stderr); sys.exit(1)
