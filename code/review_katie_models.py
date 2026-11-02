#!/usr/bin/env python3
"""Audit Jacob's UG models and prepare N=97 numerical design previews only."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
import shlex
import sys

import numpy as np
import pandas as pd

import freeze_katie_cohort as cohort

ROOT = Path(__file__).resolve().parents[1]
PREDICTORS = dict(adi="adi_natrank", pm25="pm25_mean_2013_2023", mspss="mspss_sum", ecog="ecog_score")
MODELS = dict(adi=("adi", None), pm25=("pm25", None),
              adixmspss=("adi", "mspss"), pm25xmspss=("pm25", "mspss"),
              adixecog=("adi", "ecog"), pm25xecog=("pm25", "ecog"))
QC_OPTIONS = dict(pair_means=("pair_mean_fd", "pair_mean_tsnr"),
                  signed_differences=("delta_fd", "delta_tsnr"))
BASE_TITLES = ["ones", "fdmean", "tsnr", "e11", "xa30", "male", "age"]


def tsv(rows, fields=None):
    return cohort.table(rows, list(rows[0]) if fields is None else fields)


def center(values):
    x = np.asarray(values, dtype=float)
    if not np.isfinite(x).all() or x.ndim != 1:
        raise ValueError("Nonfinite or malformed covariate")
    return x - x.mean()


def correlations(matrix):
    x = np.asarray(matrix, dtype=float)
    if x.ndim != 2 or len(x) < 3 or not np.isfinite(x).all() or np.any(x.std(axis=0) == 0):
        raise ValueError("Correlations require complete finite nonconstant columns")
    r = np.corrcoef(x, rowvar=False)
    ranked = pd.DataFrame(x).rank(method="average").to_numpy()
    rho = np.corrcoef(ranked, rowvar=False)
    return r, rho


def fsf_audit(path):
    settings = {}
    for line in path.read_text().splitlines():
        match = re.match(r"set fmri\(([^)]+)\)\s+(.+)", line)
        if match:
            settings[match[1]] = shlex.split(match[2])[0]
    n, p = int(settings["npts"]), int(settings["evs_real"])
    names = [settings[f"evtitle{i}"] for i in range(1, p + 1)]
    x = np.array([[float(settings[f"evg{r}.{c}"]) for c in range(1, p + 1)] for r in range(1, n + 1)])
    tests = []
    for index in range(1, int(settings["ncon_real"]) + 1):
        weights = [float(settings.get(f"con_real{index}.{c}", 0)) for c in range(1, p + 1)]
        tests.append(dict(name=settings[f"conname_real.{index}"], weights=dict(zip(names, weights))))
    if not np.isfinite(x).all() or np.linalg.matrix_rank(x) != p:
        raise ValueError("UG source model is nonfinite or rank deficient")
    if any(float(v) != 0 for k, v in settings.items() if k.startswith("ortho")):
        raise ValueError("Unexpected source-model orthogonalization")
    audit = dict(file=path.name, sha256=cohort.digest(path), n=n, columns=names, rank=p,
                 tests=tests, orthogonalization=False, inference="FLAME1_not_randomise")
    if p == 10:
        delta = float(np.max(np.abs(x[:, -1] - x[:, -2] * x[:, -3])))
        # FSF values are rounded; the workbook contains the full-precision products.
        if delta > 5e-5:
            raise ValueError("UG interaction is not the product of its constituent columns")
        audit["interaction_product_max_rounding_delta"] = delta
    return audit


def audit_ug(root):
    result = {}
    for name, (exposure, moderator) in MODELS.items():
        path = root / "templates" / f"L3_task-ugr_model-3_type-act_group-{name}_n116_flame1.fsf"
        audit = fsf_audit(path)
        expected = BASE_TITLES + [exposure] + ([moderator, name] if moderator else [])
        if audit["columns"] != expected:
            raise ValueError("UG model terms differ from the reviewed family: " + name)
        target = name if moderator else exposure
        for suffix, direction in (("pos", 1), ("neg", -1)):
            test = next(t for t in audit["tests"] if t["name"] == target + "_" + suffix)
            if {k: v for k, v in test["weights"].items() if v} != {target: direction}:
                raise ValueError("Unexpected focal UG contrast")
        result[name] = audit
    original = root / "templates/L3_task-ugr_model-3_type-act_group-adi_n116_flame1.fsf"
    duplicate = root / "templates/L3_task-ugr_model-3_type-act_group-adi2_n116_flame1.fsf"
    if original.read_bytes() != duplicate.read_bytes():
        raise ValueError("adi2 is no longer an exact duplicate; inspect rather than assume a seventh model")
    return dict(models=result, adi2_is_byte_identical_duplicate=True,
                source_repository="https://github.com/DVS-Lab/rf1-sra-environment-UG")


def aligned_terms(variables, pairs, era_rows):
    ids = [r["subject"] for r in variables]
    if len(ids) != 97 or len(set(ids)) != 97:
        raise ValueError("Use the frozen 97-person ordered cohort")
    pair_lookup = cohort.unique(pairs, ("subject", "contrast"))
    eras = cohort.unique([r for r in era_rows if r["session"] == "01" and r["run"] == "1"
                          and r["task"] in cohort.TASKS and r["subject"] in ids], ("subject", "task"))
    raw = []
    for v in variables:
        sub = v["subject"]
        pair = pair_lookup[(sub, "4")]
        labels = {eras[(sub, task)]["software_era"] for task in cohort.TASKS}
        if len(labels) != 1 or not labels <= {"E11", "XA30", "XA60"}:
            raise ValueError("Both task runs must have one known matching scanner era")
        for task in cohort.TASKS:
            for metric in ("tsnr", "fd_mean"):
                if float(eras[(sub, task)][metric]) != float(pair[f"{task}_{metric}"]):
                    raise ValueError("Scanner report QC differs from frozen pair QC")
        if v["gender"] not in ("0", "1"):
            raise ValueError("Unexpected source gender code; do not silently recode")
        sd_fd, d_fd, sd_t, d_t = [float(pair[f]) for f in
                                ("socialdoors_fd_mean", "doors_fd_mean", "socialdoors_tsnr", "doors_tsnr")]
        row = dict(subject=sub, software_era=next(iter(labels)), age=float(v["sub_age"]),
                   gender_code1=float(v["gender"]), pair_mean_fd=(sd_fd + d_fd) / 2,
                   pair_mean_tsnr=(sd_t + d_t) / 2, delta_fd=sd_fd - d_fd, delta_tsnr=sd_t - d_t)
        row.update({label: float(v[field]) for label, field in PREDICTORS.items()})
        raw.append(row)
    terms = {name: center([r[name] for r in raw]) for name in
             ("age", "gender_code1", *PREDICTORS, *QC_OPTIONS["pair_means"], *QC_OPTIONS["signed_differences"])}
    terms.update(ones=np.ones(len(ids)), e11=center([r["software_era"] == "E11" for r in raw]),
                 xa30=center([r["software_era"] == "XA30" for r in raw]))
    for name, (exposure, moderator) in MODELS.items():
        if moderator:
            terms[name] = terms[exposure] * terms[moderator]
    return ids, raw, terms


def model_preview(terms, model, qc_mode):
    exposure, moderator = MODELS[model]
    names = ["ones", *QC_OPTIONS[qc_mode], "e11", "xa30", "gender_code1", "age", exposure]
    if moderator:
        names += [moderator, model]
    x = np.column_stack([terms[name] for name in names])
    if not np.isfinite(x).all() or np.linalg.matrix_rank(x) != len(names):
        raise ValueError("Preview is nonfinite or rank deficient: " + model + "/" + qc_mode)
    z = (x[:, 1:] - x[:, 1:].mean(axis=0)) / x[:, 1:].std(axis=0, ddof=1)
    vif = np.diag(np.linalg.inv(np.corrcoef(z, rowvar=False)))
    target = model if moderator else exposure
    contrasts = [dict(name=target + "_" + suffix, **{n: direction if n == target else 0 for n in names})
                 for suffix, direction in (("pos", 1), ("neg", -1))]
    return names, x, contrasts, dict(model=model, qc_mode=qc_mode, n=len(x), columns=len(names),
                                    rank=int(np.linalg.matrix_rank(x)), residual_dof=len(x) - len(names),
                                    standardized_condition_number=float(np.linalg.cond(np.column_stack([np.ones(len(z)), z]))),
                                    max_vif=float(vif.max()), vif_by_column=dict(zip(names[1:], vif)),
                                    scientific_target=target, approved_for_execution=False)


def generate(upstream, ug):
    folder = ROOT / "data/derived/katie-cohort-v1"
    expected, _ = cohort.generate(ROOT, upstream)
    cohort.verify(folder, expected)
    audit = audit_ug(ug)
    _, variables = cohort.read_table(folder / "analysis_variables.tsv")
    _, pairs = cohort.read_table(folder / "selected_pairs.tsv")
    era_file = upstream / "qc/scanner_era/run_metrics.tsv"
    _, era = cohort.read_table(era_file)
    ids, raw, terms = aligned_terms(variables, pairs, era)
    r, rho = correlations([[row[label] for label in PREDICTORS] for row in raw])
    pair_rows = [dict(variable_1=a, variable_2=b, n=len(ids), pearson_r=float(r[i, j]), spearman_rho=float(rho[i, j]))
                 for i, a in enumerate(PREDICTORS) for j, b in enumerate(PREDICTORS) if i < j]
    files = {"correlations.tsv": tsv(pair_rows), "ug_template_audit.json": cohort.json_text(audit),
             "aligned_raw_terms.tsv": tsv(raw),
             "centered_candidate_terms.tsv": tsv([dict(subject=s, **{n: terms[n][i] for n in terms}) for i, s in enumerate(ids)])}
    diagnostics = []
    for mode in QC_OPTIONS:
        for model in MODELS:
            names, x, contrasts, diagnostic = model_preview(terms, model, mode)
            prefix = f"previews/{mode}/{model}/"
            files[prefix + "design.tsv"] = tsv([dict(subject=s, **dict(zip(names, vector))) for s, vector in zip(ids, x)])
            files[prefix + "focal_contrasts.tsv"] = tsv(contrasts)
            diagnostics.append(diagnostic)
    files["preview_diagnostics.json"] = cohort.json_text(diagnostics)
    catalog = dict(status="review_only_no_randomise_or_FSL_design_files", n=97,
                   models={name: dict(exposure=exposure, moderator=moderator,
                                      scientific_terms=[exposure] + ([moderator, name] if moderator else []),
                                      inherited_from="Jacob_UG", product="mean_centered_main_terms_no_orthogonalization")
                           for name, (exposure, moderator) in MODELS.items()},
                   outcomes=dict(primary="(Social_win-loss)-(Doors_win-loss)",
                                 secondary="((Social_win-loss)+(Doors_win-loss))/2"),
                   secondary_selection="run_and_report_as_secondary_not_only_when_primary_is_null",
                   qc_options_for_review=QC_OPTIONS, qc_option_approved=False,
                   scanner_reference="XA60", gender="one_centered_source_code1_indicator_not_both_dummies",
                   multiplicity_family="pending_user_agreement", randomise_run=False,
                   ppi="not_in_this_activation_bundle")
    files["model_catalog.json"] = cohort.json_text(catalog)
    sources = [dict(repository="analysis", path=str(p.relative_to(ROOT)), sha256=cohort.digest(p)) for p in
               [folder / "provenance.json", folder / "analysis_variables.tsv", folder / "selected_pairs.tsv", Path(__file__)]]
    sources.append(dict(repository="preprocessing", path="qc/scanner_era/run_metrics.tsv", sha256=cohort.digest(era_file),
                        use="cached_preview_metadata_live_BIDS_verification_needed_before_execution"))
    sources += [dict(repository="UG", path="templates/" + a["file"], sha256=a["sha256"]) for a in audit["models"].values()]
    summary = dict(n=97, models=6, qc_preview_options=2, previews=len(diagnostics),
                   scientific_predictor_only_vif=dict(zip(PREDICTORS, np.diag(np.linalg.inv(r)))),
                   all_previews_full_rank=True, scanner_era_counts={label: sum(v["software_era"] == label for v in raw)
                                                                  for label in ("E11", "XA30", "XA60")},
                   mspss_observed_min=min(v["mspss"] for v in raw), mspss_observed_max=max(v["mspss"] for v in raw),
                   mspss_zero_count=sum(v["mspss"] == 0 for v in raw), new_exclusions=0,
                   randomise_run=False, image_bundle_verified=False)
    files["summary.json"] = cohort.json_text(summary)
    files["provenance.json"] = cohort.json_text(dict(sources=sources,
        outputs={name: hashlib.sha256(text.encode()).hexdigest() for name, text in files.items()}))
    return files, summary


def verify(output, files):
    actual = {str(p.relative_to(output)) for p in output.rglob("*") if p.is_file()}
    if actual != set(files):
        raise ValueError("Review artifact inventory changed")
    for name, text in files.items():
        if (output / name).read_bytes() != text.encode():
            raise ValueError("Review changed: " + name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "check"))
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--ug-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "data/derived/model-review-v1")
    args = parser.parse_args()
    files, summary = generate(args.upstream.resolve(), args.ug_root.resolve())
    if args.command == "build" and not args.output.exists():
        for name, text in files.items():
            path = args.output / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode())
    verify(args.output, files)
    print("CHECK PASSED: correlations, six inherited model families and 12 full-rank N=97 previews.")
    print("Review only: QC option and multiplicity not selected; no images, FSL designs or randomise jobs created.")
    print(cohort.json_text(summary))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAILED ({type(exc).__name__}): {exc}", file=sys.stderr)
        sys.exit(1)
