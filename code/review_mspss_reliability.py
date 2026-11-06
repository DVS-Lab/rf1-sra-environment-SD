#!/usr/bin/env python3
"""Read-only MSPSS export review; no cohort, model or source-file changes.

ICC(A,1): two-way, single-measure absolute agreement for the two observed
administrations. Percentile CIs resample paired participants, not occasions.
McGraw/Wong ANOVA formula; see https://pmc.ncbi.nlm.nih.gov/articles/PMC6439259/.
Ryan clarified that fs_date is the scan visit date associated with the pre-scan
retest. Date-order checks identify repeated/later screeners without swapping
occasions or changing the paper cohort.
"""
import argparse
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
SCALES = {
    "total": ("mspss_sum", "mspss_retest_scoring"),
    "friends": ("mspss_friends", "mspss_retest_friends"),
    "family": ("mspss_family", "mspss_retest_family"),
    "significant_other": ("mspss_sig_other", "mspss_retest_sig_other"),
}


def read(path, delimiter=","):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream, delimiter=delimiter))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def icc(values):
    """Accept one n-by-2 sample, or a batch of paired bootstrap samples."""
    values = np.asarray(values, dtype=float)
    n, k = values.shape[-2:]
    if k != 2 or n < 3 or not np.isfinite(values).all():
        raise ValueError("ICC requires at least three finite paired observations")
    grand = values.mean(axis=(-2, -1), keepdims=True)
    row = values.mean(axis=-1, keepdims=True)
    column = values.mean(axis=-2, keepdims=True)
    ms_subject = k * ((row-grand)**2).sum(axis=(-2, -1)) / (n-1)
    ms_occasion = n * ((column-grand)**2).sum(axis=(-2, -1)) / (k-1)
    ms_error = ((values-row-column+grand)**2).sum(axis=(-2, -1)) / ((n-1)*(k-1))
    with np.errstate(divide="ignore", invalid="ignore"):
        absolute = (ms_subject-ms_error) / (ms_subject+(k-1)*ms_error+k*(ms_occasion-ms_error)/n)
        consistency = (ms_subject-ms_error) / (ms_subject+(k-1)*ms_error)
    return absolute, consistency


def describe(values):
    values = np.asarray(values, dtype=float)
    return dict(n=len(values), mean=float(values.mean()), sd=float(values.std(ddof=1)),
                minimum=float(values.min()), q1=float(np.quantile(values, .25)),
                median=float(np.median(values)), q3=float(np.quantile(values, .75)), maximum=float(values.max()))


def agreement(x, y, bootstrap=5000):
    x, y = np.asarray(x), np.asarray(y)
    n = len(x)
    delta = y-x
    absolute, consistency = icc(np.column_stack((x, y)))
    rng = np.random.default_rng(20261105)
    draw = rng.integers(0, n, size=(bootstrap, n))
    a, c = icc(np.stack((x[draw], y[draw]), axis=-1))
    valid = np.isfinite(a) & np.isfinite(c)
    dx = x[draw]-x[draw].mean(axis=1, keepdims=True)
    dy = y[draw]-y[draw].mean(axis=1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = (dx*dy).sum(axis=1) / np.sqrt((dx*dx).sum(axis=1)*(dy*dy).sum(axis=1))
    critical = stats.t.ppf(.975, n-1)
    half = critical * delta.std(ddof=1)/np.sqrt(n)
    return dict(n=n, screener=describe(x), prescan=describe(y),
                pearson_r=float(stats.pearsonr(x, y).statistic),
                pearson_ci_bootstrap=np.nanquantile(r, [.025, .975]).tolist(),
                spearman_rho=float(stats.spearmanr(x, y).statistic),
                icc_absolute_single=float(absolute), icc_consistency_single=float(consistency),
                icc_absolute_ci_bootstrap=np.quantile(a[valid], [.025, .975]).tolist(),
                icc_consistency_ci_bootstrap=np.quantile(c[valid], [.025, .975]).tolist(),
                bootstrap_pairs=bootstrap, bootstrap_valid=int(valid.sum()),
                mean_difference_prescan_minus_screener=float(delta.mean()),
                mean_difference_ci=[float(delta.mean()-half), float(delta.mean()+half)],
                bland_altman_limits=[float(delta.mean()-1.96*delta.std(ddof=1)),
                                     float(delta.mean()+1.96*delta.std(ddof=1))],
                absolute_difference_over_1=int((np.abs(delta)>1).sum()),
                absolute_difference_at_least_2=int((np.abs(delta)>=2).sum()),
                absolute_difference_at_least_3=int((np.abs(delta)>=3).sum()))


def date_gaps(rows):
    return np.array([(datetime.strptime(r["fs_date"], "%m/%d/%Y")-
                      datetime.strptime(r["screener_date"], "%m/%d/%Y")).days for r in rows])


def scale_agreement(rows, bootstrap):
    return {name: agreement(np.array([float(r[a]) for r in rows]),
                            np.array([float(r[b]) for r in rows]), bootstrap) for name, (a, b) in SCALES.items()}


def population_review(records, bootstrap=5000):
    """All supplied pairs are primary; chronology is a descriptive sensitivity."""
    gaps = date_gaps(records)
    ordered = [r for r, days in zip(records, gaps) if days > 0]
    reverse = [dict(subject=r["rf1-id"], screener_date=r["screener_date"], scan_date=r["fs_date"],
                    scan_minus_screener_days=int(days)) for r, days in zip(records, gaps) if days < 0]
    chronological = None
    if len(ordered) >= 3:
        chronological = dict(n=len(ordered), interval_days=describe(gaps[gaps>0]),
                             total=agreement(np.array([float(r["mspss_sum"]) for r in ordered]),
                                             np.array([float(r["mspss_retest_scoring"]) for r in ordered]), bootstrap),
                             purpose="Date-order sensitivity only; no cohort exclusions, swapping or imputation")
    return dict(n=len(records), scales=scale_agreement(records, bootstrap),
                signed_interval_days=describe(gaps), absolute_interval_days=describe(np.abs(gaps)),
                n_scan_before_screener=int((gaps<0).sum()), n_same_day=int((gaps==0).sum()),
                n_scan_after_screener=int((gaps>0).sum()), reversed_date_records=reverse,
                scan_after_screener_sensitivity=chronological)


def review(source, project=ROOT, bootstrap=5000):
    records = read(source)
    ids = [r["subject"] for r in read(project/"data/derived/katie-cohort-v1/subjects.tsv", "\t")]
    if len(ids) != 97 or len(set(ids)) != 97:
        raise ValueError("Frozen cohort differs; no alternative roster inferred")
    lookup = {}
    for row in records:
        key = row["rf1-id"].strip()
        if not key.isdigit() or key in lookup:
            raise ValueError("Missing, malformed or duplicate RF1 ID; no first-record selection")
        lookup[key] = row
    missing = [key for key in ids if key not in lookup]
    rows = [lookup[key] for key in ids if key in lookup]
    old_path = project/"data/derived/model-review-v1/aligned_raw_terms.tsv"
    old = {r["subject"]: float(r["mspss"]) for r in read(old_path, "\t")}
    old_values = np.array([old[r["rf1-id"].strip()] for r in rows])
    new = np.array([float(r["mspss_sum"]) for r in rows])
    changes = new-old_values
    suspect = [dict(subject=r["rf1-id"], old_score=float(o), new_score=float(v), change=float(v-o))
               for r, o, v in zip(rows, old_values, new) if v-o < -1e-7 or v-o > 1+1e-7]
    scoring = {}
    for label, total, columns in (
        ("screener", "mspss_sum", [SCALES[s][0] for s in SCALES if s != "total"]),
        ("prescan", "mspss_retest_scoring", [SCALES[s][1] for s in SCALES if s != "total"]),
    ):
        values = np.array([[float(r[k]) for k in [total, *columns]] for r in records])
        if not np.isfinite(values).all():
            raise ValueError("Nonfinite score present; no imputation or silent complete-case selection")
        errors = values[:, 0]-values[:, 1:].mean(axis=1)
        scoring[label] = dict(all_scores_in_1_to_7=bool(((values>=1)&(values<=7)).all()),
                              max_total_minus_mean_subscales=float(np.abs(errors).max()),
                              discrepancies_beyond_rounding=int((np.abs(errors)>.00501).sum()),
                              nonquarter_subscale_rows=int((np.abs(values[:, 1:]*4-np.round(values[:, 1:]*4))>.02001).any(axis=1).sum()))
    intervals = date_gaps(rows)
    all_intervals = date_gaps(records)
    scales = scale_agreement(rows, bootstrap)
    delta = np.array([float(r["mspss_retest_scoring"])-float(r["mspss_sum"]) for r in rows])
    return dict(source_sha256=sha(source), old_covariates_sha256=sha(old_path),
                frozen_roster_sha256=sha(project/"data/derived/katie-cohort-v1/subjects.tsv"),
                n_export=len(records), n_frozen=97, n_paired=len(rows), missing_cohort_ids=missing,
                cohort_changed=False, models_changed=False, scoring=scoring, scales=scales,
                interval_days=describe(intervals),
                cohort_dates_reversed=int((intervals<0).sum()), all_dates_reversed=int((all_intervals<0).sum()),
                all_same_dates=int((all_intervals==0).sum()),
                fs_date_semantics="Scan visit date associated with prescan retest, as clarified by Ryan",
                full_export=population_review(records, bootstrap),
                interval_vs_absolute_change_spearman=float(stats.spearmanr(intervals, np.abs(delta)).statistic),
                correction_change=describe(changes), correction_unchanged=int((np.abs(changes)<1e-7).sum()),
                correction_old_new_r=float(stats.pearsonr(old_values, new).statistic),
                changes_inconsistent_with_item_recode_alone=suspect,
                note="Aggregate totals/subscales only: item recoding and original-record identity are not fully verified"), rows


def plot(rows, result, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    x = np.array([float(r["mspss_sum"]) for r in rows])
    y = np.array([float(r["mspss_retest_scoring"]) for r in rows])
    stats_total = result["scales"]["total"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), layout="constrained")
    axes[0].scatter(x, y, s=25, color="#126A70", alpha=.65, edgecolors="none")
    axes[0].plot([1, 7], [1, 7], color="#59646b", lw=1, ls="--")
    axes[0].set(xlim=(.8, 7.2), ylim=(.8, 7.2), xlabel="Revised screener mean", ylabel="Pre-scan mean",
                title=f"Paired scores (n={len(rows)})\nPearson r={stats_total['pearson_r']:.2f}; absolute-agreement ICC={stats_total['icc_absolute_single']:.2f}")
    axes[1].scatter((x+y)/2, y-x, s=25, color="#126A70", alpha=.65, edgecolors="none")
    axes[1].axhline(0, color="#a2a9ae", lw=.7)
    for value, label, style in ((stats_total["mean_difference_prescan_minus_screener"], "Mean difference", "-"),
                                (stats_total["bland_altman_limits"][0], "Lower agreement limit", "--"),
                                (stats_total["bland_altman_limits"][1], "Upper agreement limit", "--")):
        axes[1].axhline(value, color="#59646b", ls=style, lw=1, label=f"{label}: {value:.2f}")
    axes[1].set(xlabel="Average of the two scores", ylabel="Pre-scan minus screener",
                title="Bland-Altman comparison\nLimits are descriptive, not exclusion cutoffs")
    axes[1].legend(frameon=False, fontsize=8, loc="lower left")
    for ax in axes:
        ax.title.set_fontsize(11)
        ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(output, dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--project", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap", type=int, default=5000)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Existing review preserved; choose a new output directory")
    original = sha(args.source)
    result, rows = review(args.source, args.project, args.bootstrap)
    args.output.mkdir(parents=True, exist_ok=True)
    plot(rows, result, args.output/"agreement.png")
    plot(read(args.source), result["full_export"], args.output/"full-sample-agreement.png")
    if sha(args.source) != original:
        raise ValueError("Input changed during read-only review")
    (args.output/"summary-private.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    print(json.dumps(result, indent=2, allow_nan=False))
