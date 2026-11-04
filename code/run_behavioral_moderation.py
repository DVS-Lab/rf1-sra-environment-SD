#!/usr/bin/env python3
"""Scoring-gated behavioral models, isolated from all completed neural analyses."""

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import traceback
import importlib.metadata

import numpy as np

import freeze_katie_cohort as cohort

SCORE_FILE = "data/derived/FEVS_OAFEM_scores_katie-cohort-v1.csv"
ROSTER = "data/derived/katie-cohort-v1/subjects.tsv"
VARIABLES = "data/derived/model-review-v1/aligned_raw_terms.tsv"
POLICY = "config/behavioral_moderation_v1.json"
SOURCE_RECEIPT = "data/derived/financial-model-review-v1/provenance.json"
MISSING = {"", "na", "n/a", "nan", "none", "null"}


class ScoringRequired(ValueError):
    pass


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n")


def table(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t" if path.suffix == ".tsv" else ",")
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError("Missing or duplicate table headers")
        rows = list(reader)
        if any(None in row for row in rows):
            raise ValueError("Malformed table width")
        return reader.fieldnames, rows


def keyed(rows, column, ids):
    lookup = {}
    for row in rows:
        try:
            subject = cohort.identifier(row[column])
        except ValueError:
            continue
        if subject not in ids:
            continue
        if subject in lookup:
            raise ValueError("Repeated cohort ID: provide explicit event/record filters, never choose first")
        lookup[subject] = row
    if set(lookup) != set(ids):
        raise ValueError("Not all 97 frozen IDs have a unique source record")
    return [lookup[s] for s in ids]


def inputs(project):
    receipt = json.loads((project / SOURCE_RECEIPT).read_text())
    approved = {r["path"]: r["sha256"] for r in receipt["sources"]}
    if any(approved.get(p) != sha(project / p) for p in (ROSTER, SCORE_FILE, VARIABLES)):
        raise ValueError("Approved cohort, score export or covariate fingerprint changed")
    _, roster = table(project / ROSTER)
    ids = [cohort.identifier(r["subject"]) for r in roster]
    if len(ids) != 97 or len(set(ids)) != 97:
        raise ValueError("Expected frozen unique N=97")
    headers, scores = table(project / SCORE_FILE)
    if headers != ["sub-num", "fevs", "OAFEM"] or len(scores) != 97:
        raise ValueError("Financial export differs from the approved three-column N=97 file")
    scores = keyed(scores, "sub-num", ids)
    _, raw = table(project / VARIABLES)
    if [cohort.identifier(r["subject"]) for r in raw] != ids:
        raise ValueError("Approved behavioral covariates differ from frozen roster order")
    values = {name: np.array([cohort.numeric(r[name]) for r in raw])
              for name in ("age", "gender_code1", "adi", "pm25", "mspss", "ecog")}
    for name, source in (("fevs", "fevs"), ("oafem", "OAFEM")):
        values[name] = np.array([cohort.numeric(r[source]) for r in scores])
        if np.any(values[name] < 0):
            raise ValueError("Unexpected negative financial score")
    if not np.isin(values["gender_code1"], [0, 1]).all():
        raise ValueError("Gender coding changed")
    policy = json.loads((project / POLICY).read_text())
    expected = dict(n=97, outcomes=["fevs", "oafem"], exposures=["adi", "pm25"],
                    moderators=["mspss", "ecog"], covariates=["age", "gender_code1"],
                    primary_tests=2, secondary_tests=6, three_way_interactions=False,
                    exclusions_changed=False, imaging_quality_covariates=False)
    if any(policy.get(k) != v for k, v in expected.items()):
        raise ValueError("Behavioral model family changed; use a separately reviewed version")
    return ids, values


def scoring_template():
    instrument = dict(instrument_version="REQUIRED", source_timepoint="REQUIRED",
                      scoring_reference="REQUIRED", raw_table="REQUIRED_ABSOLUTE_CSV_OR_TSV_PATH",
                      id_column="REQUIRED", record_filters={}, n_items_expected=None,
                      score_direction="REQUIRED", aggregation="sum", missing_rule="complete_items_required",
                      missing_tokens=["", "NA", "N/A", "NaN"],
                      items=[dict(column="REQUIRED_ITEM_COLUMN", points={})])
    return dict(version=1, instruments={name: dict(instrument) for name in ("fevs", "oafem")})


def recompute(spec, ids, expected, name):
    required = ("instrument_version", "source_timepoint", "scoring_reference", "raw_table", "id_column")
    if any(not isinstance(spec.get(k), str) or not spec[k].strip() or "REQUIRED" in spec[k] for k in required):
        raise ScoringRequired("Instrument version, source/timepoint and authoritative scoring reference required")
    directions = {"fevs": "higher_more_vulnerability", "oafem": "higher_more_reported_exploitation"}
    if spec.get("score_direction") != directions[name]:
        raise ScoringRequired("Verify financial score direction against the administered instrument")
    if spec.get("aggregation") != "sum" or spec.get("missing_rule") != "complete_items_required":
        raise ScoringRequired("Only explicitly complete-item sums supported; no invented missing-item rule")
    items = spec.get("items", [])
    if not items or spec.get("n_items_expected") != len(items):
        raise ScoringRequired("Document the administered item set and expected item count")
    columns = [item["column"] for item in items]
    if len(columns) != len(set(columns)):
        raise ValueError("Duplicate scoring item")
    missing = MISSING | {str(v).strip().lower() for v in spec["missing_tokens"]}
    mappings = []
    for item in items:
        points = item.get("points")
        if not isinstance(points, dict) or len(points) < 2:
            raise ScoringRequired("Supply each item's explicit raw-response-to-points key, including reverse coding")
        if any(str(k).strip().lower() in missing for k in points):
            raise ValueError("A missing token cannot be scored as zero or another response")
        mapped = {str(k).strip(): float(v) for k, v in points.items()}
        if len(mapped) != len(points):
            raise ValueError("Item response keys collapse after whitespace normalization")
        if any(not np.isfinite(v) or v < 0 for v in mapped.values()):
            raise ValueError("Invalid item point mapping")
        mappings.append(mapped)
    raw_path = Path(spec["raw_table"])
    if not raw_path.is_absolute():
        raise ScoringRequired("Use an explicit absolute raw-item table path")
    before = sha(raw_path)
    headers, rows = table(raw_path)
    filters = spec.get("record_filters", {})
    if not isinstance(filters, dict) or not set([spec["id_column"], *columns, *filters]).issubset(headers):
        raise ValueError("Scoring source lacks required item/ID/filter columns")
    rows = [r for r in rows if all(str(r[k]).strip() == str(v) for k, v in filters.items())]
    rows = keyed(rows, spec["id_column"], ids)
    totals = []
    for row in rows:
        total = 0.
        for item, points in zip(items, mappings):
            response = row[item["column"]].strip()
            if response.lower() in missing or response not in points:
                raise ScoringRequired("A frozen participant has a missing or unmapped item; no row dropped")
            total += points[response]
        totals.append(total)
    totals = np.asarray(totals)
    if not np.allclose(totals, expected, rtol=0, atol=1e-9):
        raise ScoringRequired("Item-derived total differs from the exported score; preserve both and resolve scoring")
    if sha(raw_path) != before:
        raise ValueError("Raw item source changed during scoring audit")
    return dict(instrument_version=spec["instrument_version"], source_timepoint=spec["source_timepoint"],
                scoring_reference=spec["scoring_reference"], score_direction=spec["score_direction"],
                items=len(items), n=97, totals_match=97, missing_items=0,
                zero_scores=int((totals == 0).sum()), minimum=float(totals.min()), maximum=float(totals.max()),
                raw_table=str(raw_path), raw_sha256=before)


def audit(project, root, spec_path, provisional=False):
    export_hashes = {p: sha(project / p) for p in (ROSTER, SCORE_FILE, VARIABLES, POLICY, SOURCE_RECEIPT)}
    ids, values = inputs(project)
    root.mkdir(parents=True, exist_ok=True)
    if not spec_path.exists():
        template = root / "scoring-spec.template.json"
        if not template.exists():
            write_json(template, scoring_template())
        record = dict(status="UNVERIFIED_SCORING" if provisional else "SCORING_REQUIRED", n=97,
                   exported_totals_complete=True, item_scoring_verified=False, models_run_by_this_audit=False,
                   export_hashes=export_hashes,
                   mspss_zero_count=int((values["mspss"] == 0).sum()),
                   zero_handling="Retained as supplied; validity of MSPSS zero coding unresolved; not declared missing",
                   needed="Raw items plus instrument version, timepoint, missing-item rules and scoring key for both measures")
        write_json(root / "scoring-status.json", record)
        if provisional:
            if any(sha(project / p) != expected for p, expected in export_hashes.items()):
                raise ValueError("Approved export changed during audit")
            print("PROVISIONAL: all 97 exported totals retained; item scoring and MSPSS zero coding remain unverified.")
            return ids, values, record
        raise ScoringRequired("Totals are complete for all 97, but item scoring is not documented; no models run")
    before = sha(spec_path)
    spec = json.loads(spec_path.read_text())
    if spec.get("version") != 1 or set(spec.get("instruments", {})) != {"fevs", "oafem"}:
        raise ScoringRequired("Expected explicit scoring definitions for FEVS and OAFEM")
    checked = {name: recompute(spec["instruments"][name], ids, values[name], name) for name in ("fevs", "oafem")}
    if sha(spec_path) != before:
        raise ValueError("Scoring specification changed during audit")
    record = dict(status="PASSED", n=97, item_scoring_verified=True, instruments=checked,
                  export_hashes=export_hashes,
                  scoring_spec=str(spec_path), scoring_spec_sha256=before,
                  interpretation="Recomputed against the supplied authoritative key, not independent validation of that key")
    if any(sha(project / p) != expected for p, expected in export_hashes.items()):
        raise ValueError("Approved export changed during scoring audit")
    write_json(root / "scoring-status.json", record)
    print("SCORING PASSED: both measures recomputed from complete items; 97/97 totals match for each; no exclusions.")
    return ids, values, record


def design(values, exposure, moderator):
    centered = {k: values[k] - values[k].mean() for k in (exposure, moderator, "age")}
    names = ["ones", exposure, moderator, "age", "gender_code1", "interaction"]
    x = np.column_stack([np.ones(97), centered[exposure], centered[moderator], centered["age"],
                         values["gender_code1"], centered[exposure] * centered[moderator]])
    if x.shape != (97, 6) or not np.isfinite(x).all() or np.linalg.matrix_rank(x) != 6:
        raise ValueError("Expected finite full-rank six-column N=97 design")
    return names, x


def tsv(path, rows):
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(stream.getvalue())


def sources(project, spec_path, scoring):
    files = [project / p for p in (ROSTER, SCORE_FILE, VARIABLES, POLICY, SOURCE_RECEIPT)] + [Path(__file__), Path(cohort.__file__)]
    files += [Path(v["raw_table"]) for v in scoring.get("instruments", {}).values()]
    result = {str(p.resolve()): sha(p) for p in files}
    if any(result[str((project / p).resolve())] != expected for p, expected in scoring["export_hashes"].items()):
        raise ValueError("Approved export changed after scoring audit")
    if any(result[str(Path(v["raw_table"]).resolve())] != v["raw_sha256"] for v in scoring.get("instruments", {}).values()):
        raise ValueError("Raw item source changed after scoring audit")
    result[str(spec_path.resolve())] = sha(spec_path) if spec_path.exists() else "ABSENT: scoring unverified"
    return result


def fit_models(values):
    import statsmodels.api as sm
    from statsmodels.stats.multitest import multipletests
    from scipy.stats import t

    rows, coefficients, diagnostics, curves, private = [], [], [], [], []
    for outcome in ("fevs", "oafem"):
        for exposure in ("adi", "pm25"):
            for moderator in ("mspss", "ecog"):
                key = f"{outcome}_{exposure}_{moderator}"
                names, x = design(values, exposure, moderator)
                fitted = sm.OLS(values[outcome], x).fit()
                robust = fitted.get_robustcov_results(cov_type="HC3", use_t=True)
                if not np.isfinite(robust.cov_params()).all():
                    raise ValueError("Invalid HC3 covariance")
                family = "primary" if outcome == "fevs" and moderator == "mspss" else "secondary"
                ci = robust.conf_int()
                rows.append(dict(model=key, outcome=outcome, exposure=exposure, moderator=moderator,
                                 family=family, n=97, residual_df=91, interaction_beta=float(robust.params[-1]),
                                 hc3_se=float(robust.bse[-1]), ci_lower=float(ci[-1, 0]), ci_upper=float(ci[-1, 1]),
                                 hc3_p=float(robust.pvalues[-1]), holm_family_p=0., r_squared=float(fitted.rsquared),
                                 delta_r_squared=float(fitted.rsquared - sm.OLS(values[outcome], x[:, :-1]).fit().rsquared)))
                for i, term in enumerate(names):
                    coefficients.append(dict(model=key, term=term, beta=float(robust.params[i]),
                                             hc3_se=float(robust.bse[i]), ci_lower=float(ci[i, 0]),
                                             ci_upper=float(ci[i, 1]), hc3_p=float(robust.pvalues[i])))
                influence = fitted.get_influence()
                loo = [float(sm.OLS(np.delete(values[outcome], i), np.delete(x, i, axis=0)).fit().params[-1]) for i in range(97)]
                if not np.isfinite(loo).all():
                    raise ValueError("Invalid leave-one-out estimate")
                diagnostics.append(dict(model=key, n=97, max_cooks_d=float(influence.cooks_distance[0].max()),
                                        n_cooks_above_4_over_n=int((influence.cooks_distance[0] > 4 / 97).sum()),
                                        max_leverage=float(influence.hat_matrix_diag.max()),
                                        loo_beta_min=min(loo), loo_beta_max=max(loo),
                                        zero_outcomes=int((values[outcome] == 0).sum()), exclusions_made=False))
                for i in range(97):
                    private.append(dict(model=key, row=i, fitted=float(fitted.fittedvalues[i]),
                                        residual=float(fitted.resid[i]), cooks_d=float(influence.cooks_distance[0][i]),
                                        leverage=float(influence.hat_matrix_diag[i]), loo_beta=loo[i]))
                for m in np.linspace(values[moderator].min(), values[moderator].max(), 101):
                    vector = np.zeros(6)
                    vector[1], vector[-1] = 1, m - values[moderator].mean()
                    beta = float(vector @ robust.params)
                    se = np.sqrt(float(vector @ robust.cov_params() @ vector))
                    half = t.ppf(.975, 91) * se
                    curves.append(dict(model=key, outcome=outcome, exposure=exposure, moderator=moderator,
                                       moderator_value=float(m), conditional_exposure_slope=beta,
                                       ci_lower=float(beta - half), ci_upper=float(beta + half)))
    for family, count in (("primary", 2), ("secondary", 6)):
        selected = [r for r in rows if r["family"] == family]
        if len(selected) != count:
            raise ValueError("Behavioral multiplicity family changed")
        adjusted = multipletests([r["hc3_p"] for r in selected], method="holm")[1]
        for row, p in zip(selected, adjusted):
            row["holm_family_p"] = float(p)
    return rows, coefficients, diagnostics, curves, private


def plot_slopes(report, curves, provisional):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    for outcome in ("fevs", "oafem"):
        labels = dict(adi="ADI", pm25="PM2.5", mspss="MSPSS", ecog="Ecog")
        fig, axes = plt.subplots(2, 2, figsize=(10, 7))
        for axis, (exposure, moderator) in zip(axes.flat, [(e, m) for e in ("adi", "pm25") for m in ("mspss", "ecog")]):
            rows = [r for r in curves if r["model"] == f"{outcome}_{exposure}_{moderator}"]
            axis.plot([r["moderator_value"] for r in rows], [r["conditional_exposure_slope"] for r in rows], color="#087e83")
            axis.fill_between([r["moderator_value"] for r in rows], [r["ci_lower"] for r in rows],
                              [r["ci_upper"] for r in rows], color="#087e83", alpha=.15)
            axis.axhline(0, color="black", lw=.7)
            axis.set(title=f"{labels[exposure]} association with {outcome.upper()}", xlabel=labels[moderator],
                     ylabel=f"{outcome.upper()} points / {labels[exposure]} unit")
        prefix = "PROVISIONAL | " if provisional else ""
        fig.suptitle(f"{prefix}{outcome.upper()} moderation | N=97, age/gender adjusted")
        fig.text(.5, .015, "HC3 pointwise 95% intervals; observed moderator range; no participant exclusions. Not a causal effect.", ha="center", fontsize=9)
        fig.tight_layout(rect=(0, .035, 1, .95))
        fig.savefig(report / f"{outcome}-conditional-slopes.png", dpi=140)
        plt.close(fig)


def run(project, root, spec_path, provisional=False):
    ids, values, scoring = audit(project, root, spec_path, provisional)
    fingerprints = sources(project, spec_path, scoring)
    report = root / "report"
    if report.exists():
        check(project, root, spec_path, provisional)
        print("REUSED: existing validated behavioral report; no models overwritten.")
        return
    result = fit_models(values)
    stage = Path(tempfile.mkdtemp(prefix=".behavioral-report-", dir=root))
    stage.chmod(0o777)
    rows, coefficients, diagnostics, curves, private = result
    tsv(stage / "interactions.tsv", rows)
    tsv(stage / "coefficients.tsv", coefficients)
    tsv(stage / "diagnostics.tsv", diagnostics)
    tsv(stage / "conditional_slopes.tsv", curves)
    plot_slopes(stage, curves, provisional=not scoring["item_scoring_verified"])
    verified = scoring["item_scoring_verified"]
    lines = ["# " + ("Provisional " if not verified else "") + "Behavioral Moderation: Frozen N=97", "",
             "Scoring: both scores match complete item-derived totals for all 97." if verified else
             "PROVISIONAL: complete exported totals used as supplied. Item scoring, version, timepoint and missing-item rules are not yet verified. Do not treat this report as final.",
             f"MSPSS zero values retained: {int((values['mspss'] == 0).sum())}. Their coding validity is unresolved; zero was not silently recoded as missing.",
             "FEVS/support models are primary (2 interactions); FEVS/Ecog and all OAFEM models are secondary (6).",
             "All eight models retain both main terms, age and gender. No three-way terms, imaging QC covariates, transformations or exclusions.",
             "OLS, HC3 two-sided t intervals/tests, df=91. Raw p and within-family Holm p are both reported; no significance-based model selection.",
             "OAFEM is a distinct reported-exploitation outcome, not a replication of FEVS contextual vulnerability.",
             "Conditional-slope bands are pointwise, not simultaneous. These associations do not establish causality or mediation.",
             "FEVS financial/relational distress content overlaps conceptually with exposures/support; interpret accordingly.",
             "Item scoring is checked against the supplied key; instrument authenticity/timepoint selection require source documentation.", "",
             "| Outcome | Exposure | Moderator | Family | Interaction beta | HC3 95% CI | HC3 p | Holm p |",
             "|---|---|---|---|---:|---|---:|---:|"]
    for r in rows:
        lines.append(f"| {r['outcome']} | {r['exposure']} | {r['moderator']} | {r['family']} | {r['interaction_beta']:.4g} | [{r['ci_lower']:.4g}, {r['ci_upper']:.4g}] | {r['hc3_p']:.4g} | {r['holm_family_p']:.4g} |")
    lines += ["", "![FEVS conditional associations](fevs-conditional-slopes.png)", "",
              "![OAFEM conditional associations](oafem-conditional-slopes.png)", "",
              "See diagnostics.tsv for influence and leave-one-out summaries. Flags never remove participants.",
              "This is a new bounded exploratory behavioral family specified after the neural analyses, not preregistered.",
              "Completed neural inputs/results, masks, quality rules and exclusions were not readjusted.", ""]
    (stage / "README.md").write_text("\n".join(lines))
    if sources(project, spec_path, scoring) != fingerprints:
        raise ValueError("Inputs changed during behavioral modeling")
    for r in private:
        r["subject"] = ids[r.pop("row")]
    tsv(root / "influence-private.tsv", private)
    write_json(root / "provenance-private.json", dict(inputs=fingerprints, n=97, models=8,
               subject_order=ids, scoring=scoring, provisional=provisional, runner_sha256=sha(Path(__file__)),
               packages={name: importlib.metadata.version(name) for name in ("numpy", "scipy", "statsmodels", "matplotlib")}))
    outputs = {p.name: sha(p) for p in stage.iterdir()}
    write_json(stage / "review_manifest.json", dict(n=97, models=8, primary_tests=2, secondary_tests=6,
               scoring_passed=verified, provisional=not verified, exclusions_changed=False, neural_analyses_changed=False,
               new_neural_inference=False, outputs=outputs))
    stage.rename(report)
    check(project, root, spec_path, provisional)


def check(project, root, spec_path, provisional=False):
    ids, _, scoring = audit(project, root, spec_path, provisional)
    provenance = json.loads((root / "provenance-private.json").read_text())
    if (provenance["inputs"] != sources(project, spec_path, scoring) or provenance["subject_order"] != ids
            or provenance["provisional"] != provisional):
        raise ValueError("Behavioral input lineage changed; preserved report cannot be silently reused")
    report = root / "report"
    manifest = json.loads((report / "review_manifest.json").read_text())
    for name, expected in manifest["outputs"].items():
        if Path(name).name != name or sha(report / name) != expected:
            raise ValueError("Behavioral report artifact changed")
    _, rows = table(report / "interactions.tsv")
    if len(rows) != 8 or len({r["model"] for r in rows}) != 8 or any(int(r["n"]) != 97 or int(r["residual_df"]) != 91 for r in rows):
        raise ValueError("Behavioral model coverage differs")
    current_packages = {name: importlib.metadata.version(name) for name in provenance["packages"]}
    if provenance["packages"] != current_packages:
        raise ValueError("Statistical runtime versions changed; do not silently reuse the report")
    status = "item scores reconciled" if scoring["item_scoring_verified"] else "PROVISIONAL exported scores; item scoring remains unverified"
    print(f"CHECK PASSED: {status}; eight full-rank N=97 behavioral models; HC3 inference; no neural changes or exclusions.")


def main():
    os.umask(0)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("audit", "run", "check"))
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--scoring-spec", type=Path)
    parser.add_argument("--provisional", action="store_true", help="Explicitly authorize exported-score analyses while item documentation is pending")
    args = parser.parse_args()
    project = args.project.resolve()
    default_name = "behavioral-moderation-provisional-v1" if args.provisional else "behavioral-moderation-v1"
    root = (args.root or project / "work" / default_name).resolve()
    if not root.is_relative_to(project / "work"):
        parser.error("Behavioral outputs must stay isolated under project/work")
    spec = args.scoring_spec or root / "scoring-spec.json"
    root.mkdir(parents=True, exist_ok=True)
    try:
        if args.command == "audit":
            audit(project, root, spec, args.provisional)
        elif args.command == "run":
            run(project, root, spec, args.provisional)
        else:
            check(project, root, spec, args.provisional)
    except Exception as exc:
        (root / "error-private.txt").write_text(traceback.format_exc())
        if isinstance(exc, ScoringRequired):
            write_json(root / "scoring-status.json", dict(status="SCORING_REQUIRED", n=97,
                       item_scoring_verified=False, models_run_by_this_attempt=False, reason=str(exc)))
            print("SCORING REQUIRED: " + str(exc), file=sys.stderr)
            return 2
        print(f"STOPPED ({type(exc).__name__}); inspect {root / 'error-private.txt'}. No neural processing changed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
