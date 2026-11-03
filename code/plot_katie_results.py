#!/usr/bin/env python3
"""Render audited brain maps and explicitly descriptive ROI/JN follow-ups."""
from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import html
import importlib.metadata
import json
import multiprocessing
import os
from pathlib import Path
import sys
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np
from nilearn import plotting
from PIL import Image
from scipy.ndimage import label
from scipy.stats import pearsonr, spearmanr, t
import statsmodels.api as sm

import audit_katie_results as audit
import review_financial_models as financial
import run_katie_randomise as base

LABELS = dict(fevs="FEVS", oafem="OAFEM", mspss="MSPSS", ecog="Ecog", adi="ADI", pm25="PM2.5")
CAUTION = "Descriptive follow-up; pointwise intervals, not an independent whole-brain test"


def short_id(value):
    return hashlib.sha256(str(value).encode()).hexdigest()[:14]


def render_task(function, task):
    path = Path(task["path"]); receipt = path.with_suffix(".receipt.json")
    signature = hashlib.sha256(base.cohort.json_text(dict(task=task, code=base.cohort.digest(Path(__file__)))).encode()).hexdigest()
    if receipt.exists():
        saved = json.loads(receipt.read_text())
        if saved["signature"] != signature or base.cohort.digest(path) != saved["png_sha256"]:
            raise ValueError("Existing completed figure differs; preserve it and choose a new review version")
        return saved["result"]
    if path.exists():
        archive = Path(task.get("details", str(path.parent / "unsealed"))).parent / ("unsealed-"+base.cohort.digest(path)+".png")
        archive.parent.mkdir(parents=True, exist_ok=True); path.rename(archive)
    result = function(task)
    receipt.write_text(base.cohort.json_text(dict(signature=signature,png_sha256=base.cohort.digest(path),result=result)))
    return result


def save_figure(fig, path):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.stem + ".tmp.png")
    fig.savefig(temporary, dpi=150, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    with Image.open(temporary) as image:
        pixels = np.asarray(image.convert("RGB"), dtype=float)
        if min(image.size) < 200 or pixels.std() < 2:
            raise ValueError("Blank or undersized figure")
    temporary.replace(path)


def jn_curve(fit, predictor, interaction, observed_centered, raw_mean):
    low, high = float(np.min(observed_centered)), float(np.max(observed_centered))
    grid = np.linspace(low, high, 401)
    weights = np.zeros((len(grid), len(fit.params)))
    weights[:, predictor] = 1; weights[:, interaction] = grid
    tested = fit.t_test(weights)
    ci = np.asarray(tested.conf_int(alpha=.05))
    beta, covariance = np.asarray(fit.params), np.asarray(fit.cov_params())
    critical = float(t.ppf(.975, fit.df_resid))
    coefficients = [beta[predictor]**2-critical**2*covariance[predictor, predictor],
        2*(beta[predictor]*beta[interaction]-critical**2*covariance[predictor, interaction]),
        beta[interaction]**2-critical**2*covariance[interaction, interaction]]
    roots = np.polynomial.polynomial.polyroots(np.trim_zeros(coefficients, "b")) if any(coefficients) else []
    roots = sorted(float(r.real) for r in roots if abs(r.imag) < 1e-8 and low <= r.real <= high)
    boundaries = sorted(set([low, *roots, high]))
    regions = []
    for a, b in zip(boundaries[:-1], boundaries[1:]):
        contrast = np.zeros(len(fit.params)); contrast[predictor] = 1; contrast[interaction] = (a+b)/2
        interval = fit.t_test(contrast).conf_int()[0]
        regions.append(dict(lower_raw=a+raw_mean, upper_raw=b+raw_mean,
                            pointwise_ci_excludes_zero=bool(interval[0] > 0 or interval[1] < 0)))
    return dict(raw_grid=grid+raw_mean, slope=np.asarray(tested.effect), ci=ci,
                roots_raw=[r+raw_mean for r in roots], regions=regions, residual_df=float(fit.df_resid))


def roi_figure(task):
    path = Path(task["path"])
    names, x, y = task["names"], np.asarray(task["x"]), np.asarray(task["y"])
    if x.shape[0] != 97 or y.shape != (97,) or not np.isfinite(y).all(): raise ValueError("ROI row alignment differs")
    for name in names[7:]:
        if name in task["raw"]:
            raw = np.asarray(task["raw"][name])
            if not np.allclose(x[:,names.index(name)],raw-raw.mean(),rtol=0,atol=1e-10):
                raise ValueError("Raw plot axes do not match the frozen centered design")
    fit = sm.OLS(y, x, hasconst=True).fit()
    robust = fit.get_robustcov_results(cov_type="HC3", use_t=True)
    target = names.index(task["term"])
    influence = fit.get_influence()
    cooks = np.asarray(influence.cooks_distance[0])
    information = dict(id=task["id"], title=task["title"], selection=task["selection"], n=97,
        term=task["term"], estimate=float(fit.params[target]), ols_ci=list(map(float, fit.conf_int()[target])),
        hc3_ci=list(map(float, robust.conf_int()[target])), residual_df=float(fit.df_resid),
        max_cooks_d=float(cooks.max()), max_leverage=float(influence.hat_matrix_diag.max()),
        n_cooks_above_4_over_n=int((cooks > 4/97).sum()), exclusions_made=False)
    if "e11" in names and "xa30" in names:
        era=np.where(x[:,names.index("e11")]>0,"E11",np.where(x[:,names.index("xa30")]>0,"XA30","XA60"))
        information["residual_sd_by_era"]={e:dict(n=int((era==e).sum()),sd=float(np.std(fit.resid[era==e],ddof=1))) for e in ("E11","XA30","XA60")}
    # Leave-one-out parameter ranges are influence diagnostics, never a new exclusion rule.
    leave_one_out = np.asarray(influence.params_not_obsi)[:, target]
    information["leave_one_out_estimate_min"] = float(leave_one_out.min())
    information["leave_one_out_estimate_max"] = float(leave_one_out.max())
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.2), constrained_layout=True)
    fig.suptitle(task["title"] + "\n" + task["selection"], fontsize=11)
    if task["interaction"]:
        exposure, moderator = names[-3:-1]
        p, m, interaction = names.index(exposure), names.index(moderator), len(names)-1
        if target != interaction: raise ValueError("JN requested for a constituent coefficient rather than interaction")
        raw_x, raw_m = np.asarray(task["raw"][exposure]), np.asarray(task["raw"][moderator])
        mean = float(raw_m.mean())
        ordinary = jn_curve(fit, p, interaction, x[:, m], mean)
        sensitivity = jn_curve(robust, p, interaction, x[:, m], mean)
        information.update(ols_jn_roots=ordinary["roots_raw"], hc3_jn_roots=sensitivity["roots_raw"],
                           ols_jn_regions=ordinary["regions"], hc3_jn_regions=sensitivity["regions"])
        a = axes[0]
        a.fill_between(ordinary["raw_grid"], ordinary["ci"][:,0], ordinary["ci"][:,1], color="#a5d8e2", alpha=.65, label="OLS 95% pointwise CI")
        a.plot(ordinary["raw_grid"], ordinary["slope"], color="#075c72", lw=2)
        a.plot(sensitivity["raw_grid"], sensitivity["ci"], color="#4c5154", ls="--", lw=.8)
        a.axhline(0, color="black", lw=.8)
        for root in ordinary["roots_raw"]: a.axvline(root, color="#b83232", ls=":", lw=1)
        a.plot(raw_m, np.full(97, .02), "|", color="#555555", alpha=.5, transform=a.get_xaxis_transform())
        a.set(xlabel=LABELS.get(moderator, moderator), ylabel="Conditional " + LABELS.get(exposure, exposure) + " slope", title="Johnson-Neyman; observed range only")
        a.legend(fontsize=7, loc="best")
        a.text(.02, .96, "Dashed: HC3 95% CI", va="top", transform=a.transAxes, fontsize=7)
        a = axes[1]
        adjusted = y - x[:, 1:7] @ fit.params[1:7]
        cloud = a.scatter(raw_x, adjusted, c=raw_m, cmap="viridis", s=16, alpha=.65, edgecolors="none")
        xx = np.linspace(raw_x.min(), raw_x.max(), 100)
        for value, color in zip(np.quantile(raw_m, [.16, .5, .84]), ("#3b4eaa", "#16776f", "#ac611a")):
            design = np.zeros((100, x.shape[1])); design[:,0] = 1
            design[:,p] = xx-raw_x.mean(); design[:,m] = value-mean
            design[:,interaction] = design[:,p]*design[:,m]
            a.plot(xx, fit.predict(design), color=color, label=f"{LABELS.get(moderator, moderator)}={value:.2f}")
        a.set(xlabel=LABELS.get(exposure, exposure), ylabel="Nuisance-adjusted region estimate", title="Conditional fitted associations")
        a.legend(fontsize=7)
    else:
        raw_x = np.asarray(task["raw"][task["term"]])
        axes[0].scatter(raw_x, y, color="#667b88", s=19, alpha=.7, edgecolors="none")
        axes[0].set(xlabel=LABELS.get(task["term"], task["term"]), ylabel="Region estimate", title="Raw participant values")
        adjusted = fit.resid + fit.params[0] + fit.params[target]*x[:,target]
        axes[1].scatter(raw_x, adjusted, color="#16776f", s=19, alpha=.7, edgecolors="none")
        xx = np.linspace(raw_x.min(), raw_x.max(), 100)
        design = np.zeros((100, x.shape[1])); design[:,0] = 1; design[:,target] = xx-raw_x.mean()
        interval = fit.get_prediction(design).summary_frame(alpha=.05)
        axes[1].plot(xx, interval["mean"], color="#075c72")
        axes[1].fill_between(xx, interval["mean_ci_lower"], interval["mean_ci_upper"], color="#a5d8e2", alpha=.6)
        axes[1].set(xlabel=LABELS.get(task["term"], task["term"]), ylabel="Adjusted region estimate", title="Adjusted scatter; OLS pointwise 95% CI")
    axes[2].scatter(fit.fittedvalues, fit.resid, c=cooks, cmap="magma", s=19, alpha=.8, edgecolors="none")
    axes[2].axhline(0, color="black", lw=.8)
    axes[2].set(xlabel="Fitted region estimate", ylabel="Residual", title="Influence check: color = Cook's D")
    axes[2].text(.02, .98, f"Max Cook's D: {cooks.max():.3f}\nNo participants removed", va="top", transform=axes[2].transAxes, fontsize=8)
    for a in axes:
        a.spines[["top", "right"]].set_visible(False); a.tick_params(labelsize=8)
    fig.supxlabel(CAUTION, fontsize=8)
    save_figure(fig, path)
    details = Path(task["details"]); details.parent.mkdir(parents=True, exist_ok=True)
    details.write_text(base.review.tsv([dict(subject=sub, region_estimate=float(value), cooks_d=float(cook), leverage=float(lev))
        for sub,value,cook,lev in zip(task["ids"], y, cooks, influence.hat_matrix_diag)]))
    return information


def brain_figure(task):
    rows = task["rows"]; reference = nib.load(rows[0]["mask"]); support = reference.get_fdata() > 0
    positive = next(r for r in rows if r["direction"] == "positive")
    original = nib.load(positive["tstat"]); signed = original.get_fdata()
    vmax = max(3.5, float(np.max(np.abs(signed[support]))))
    fig = plt.figure(figsize=(15, 7))
    fig.suptitle(task["title"] + "\nRed = positive coefficient; blue = negative coefficient", fontsize=11)
    for index, z in enumerate((None, 2.6, 3.1)):
        if z is None:
            values = np.where(support, signed, 0); subtitle = "Unthresholded t: context only, not significant"
        else:
            values = np.zeros(signed.shape)
            for row in (r for r in rows if float(r["z"]) == z):
                image = nib.load(row["tstat"]); statistic = image.get_fdata()
                sign = 1 if row["direction"] == "positive" else -1
                if not np.allclose(statistic[support]*sign, signed[support], rtol=1e-5, atol=1e-5):
                    raise ValueError("Directional/CDT t maps do not agree")
                selected = (nib.load(row["corrp"]).get_fdata() > .95) & support
                values[selected] = statistic[selected]*sign
            subtitle = f"Cluster-FWE p<.05; CDT Z-equivalent {z}" + ("; no surviving clusters" if not np.any(values) else "")
        axes = [0.02, .67-index*.29, .95, .22]
        fig.text(.02,axes[1]+axes[3]+.008,subtitle,fontsize=9,va="bottom")
        image = nib.Nifti1Image(values.astype(np.float32), original.affine)
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore",message="(?i).*empty mask.*")
            plotting.plot_stat_map(image, bg_img=task["background"], display_mode="z", cut_coords=[-48,-32,-16,0,16,32,48,64,80],
                figure=fig, axes=axes, threshold=1e-12, cmap="RdBu_r", symmetric_cbar=True, vmin=-vmax, vmax=vmax,
                colorbar=True, draw_cross=False, black_bg=False, title=None)
    fig.text(.02, .025, "N=97; existing randomise results. CDTs are sensitivity choices, not independent replications. Background: " + Path(task["background"]).name, fontsize=8)
    save_figure(fig, task["path"])
    return dict(id=task["id"], title=task["title"], path=task["relative"])


def group_roi_figure(values, path):
    names = ("socialdoors","doors","average","social_specific")
    fig, axes = plt.subplots(1,2,figsize=(11,4.5),constrained_layout=True)
    axes[0].boxplot([values[n] for n in names], tick_labels=["Social","Doors","Average","Social-Doors"], showfliers=False)
    rng = np.random.default_rng(20261101)
    for i,n in enumerate(names,1): axes[0].scatter(i+rng.uniform(-.12,.12,97),values[n],s=10,color="#16776f",alpha=.5)
    axes[0].axhline(0,color="black",lw=.8); axes[0].set(ylabel="VS win-loss COPE (arbitrary units)",title="Anatomical VS ROI: all 97 participants")
    axes[1].scatter(values["doors"],values["socialdoors"],s=20,color="#426783",alpha=.7)
    low=min(values["doors"].min(),values["socialdoors"].min()); high=max(values["doors"].max(),values["socialdoors"].max())
    axes[1].plot([low,high],[low,high],color="#777777",ls="--")
    axes[1].set(xlabel="Doors win-loss",ylabel="Social win-loss",title="Paired participant estimates")
    fig.supxlabel("Descriptive ROI summaries; not replacements for the corrected group maps",fontsize=9)
    save_figure(fig,path)


def raw_terms(ids):
    _, rows = base.cohort.read_table(base.ROOT / "data/derived/model-review-v1/aligned_raw_terms.tsv")
    if [r["subject"] for r in rows] != ids: raise ValueError("Raw covariate order differs")
    scores, _ = financial.read_scores(financial.SCORES, ids)
    result = {name: np.array([float(r[name]) for r in rows]) for name in LABELS if name not in ("fevs", "oafem")}
    result.update({name: np.array([r[name] for r in scores]) for name in ("fevs", "oafem")})
    return result


def figures(project, report, details, background, jobs):
    if not (report / "audit.json").exists(): raise ValueError("Run the complete audit before plotting")
    if details.resolve().is_relative_to(report.resolve()):raise ValueError("Keep participant diagnostics separate from the public aggregate report")
    _, maps = base.cohort.read_table(report / "maps.tsv")
    _, roster = base.cohort.read_table(base.ROOT / "data/derived/katie-cohort-v1/subjects.tsv")
    ids = [r["subject"] for r in roster]; raw = raw_terms(ids)
    review_sources=[base.fingerprint(p) for p in (background,Path(__file__),Path(audit.__file__),financial.SCORES,
        base.ROOT / "data/derived/model-review-v1/aligned_raw_terms.tsv",project.parent / "rf1-sra-socdoors/masks/seed-VS.nii.gz")]
    grouped = defaultdict(list)
    for row in maps: grouped[(row["batch"], row["family"], row["outcome"], row["model"], row["term"])].append(row)
    cache = {}
    def data(path):
        if path not in cache: cache[path] = np.asarray(nib.load(path).dataobj, dtype=np.float32)
        return cache[path]
    tasks, rois = [], []
    for key, rows in grouped.items():
        identifier = short_id(key); title = " | ".join(key)
        tasks.append((brain_figure, dict(id=identifier, title=title, rows=rows, background=str(background),
            path=str(report / f"figures/brain-{identifier}.png"), relative=f"figures/brain-{identifier}.png")))
        first = rows[0]; names, order = base.cohort.read_table(Path(first["design"]).with_suffix(".tsv")); names = names[1:]
        if [r["subject"] for r in order] != ids: raise ValueError("ROI design order differs")
        x = audit.matrix(first["design"])
        interaction = first["term"] == names[-1] and len(names) == 10
        if first["term"] == "ones": continue
        definitions = []
        # Selected clusters are descriptive follow-ups, kept separately for each CDT/direction.
        for row in rows:
            selected = (nib.load(row["corrp"]).get_fdata() > .95) & (nib.load(row["mask"]).get_fdata() > 0)
            components, number = label(selected, structure=np.ones((3,3,3)))
            for component in range(1, number+1):
                definitions.append((f"z-{row['z']}-{row['direction']}-c{component}", components == component,
                    "SAME-SAMPLE SELECTED CLUSTER: descriptive only"))
        if first["family"] == "activation" and first["batch"] != "conditional_activation":
            seed = project.parent / "rf1-sra-socdoors/masks/seed-VS.nii.gz"
            seed_image, support = nib.load(seed), nib.load(first["mask"]); base.grid(support, seed_image)
            values = seed_image.get_fdata()
            if not np.isin(values, (0,1)).all(): raise ValueError("VS anatomical mask is not binary")
            roi = (values > 0) & (support.get_fdata() > 0)
            if not roi.any(): raise ValueError("VS anatomical ROI has no analysis support")
            definitions.append(("anatomical-VS", roi, "Anatomical VS ROI; exploratory region-level follow-up"))
        for name, roi, selection in definitions:
            identifier = short_id((key, name)); values = data(first["image"])[roi].mean(axis=0, dtype=np.float64)
            task = dict(id=identifier, title=title+" | "+name, selection=selection, path=str(report / f"figures/association-{identifier}.png"),
                details=str(details / f"influence-{identifier}.tsv"), names=names, x=x.tolist(), y=values.tolist(), raw={k:v.tolist() for k,v in raw.items()},
                term=first["term"], interaction=interaction, ids=ids)
            tasks.append((roi_figure, task)); rois.append(dict(id=identifier, title=task["title"], path=f"figures/association-{identifier}.png"))
    if len(grouped) != 84: raise ValueError("Expected 84 combined-direction/CDT brain panels")
    completed, fits = [], []
    failures=[]
    with ProcessPoolExecutor(max_workers=jobs, mp_context=multiprocessing.get_context("spawn")) as pool:
        pending = {pool.submit(render_task, function, task): (function, task) for function,task in tasks}
        for number, future in enumerate(as_completed(pending), 1):
            function, task = pending[future]
            try: result = future.result()
            except Exception as exc:
                failures.append(dict(id=task["id"],error=str(exc)))
                print("FIGURE FAILED "+task["title"]+": "+str(exc),flush=True)
                continue
            completed.append(dict(path=str(Path(task["path"]).relative_to(report)), sha256=base.cohort.digest(Path(task["path"]))))
            if function == roi_figure: fits.append(result)
            print(f"FIGURE {number}/{len(tasks)} {Path(task['path']).name}", flush=True)
    if failures:
        (details / "figure-failures.json").parent.mkdir(parents=True,exist_ok=True)
        (details / "figure-failures.json").write_text(base.cohort.json_text(failures))
        raise RuntimeError("Figure tasks failed; completed receipts preserved; no review published")
    group = json.loads((project / "derivatives/fsl/randomise/katie-remaining-v1/activation/plan.json").read_text())
    seed_image = nib.load(project.parent / "rf1-sra-socdoors/masks/seed-VS.nii.gz")
    support = nib.load(group["mask"]); base.grid(support,seed_image)
    roi = (seed_image.get_fdata()>0)&(support.get_fdata()>0)
    values = {name:data(path)[roi].mean(axis=0,dtype=np.float64) for name,path in group["images"].items()}
    group_roi_figure(values,report / "figures/vs-group-response.png")
    (report / "vs_group_response.tsv").write_text(base.review.tsv([dict(outcome=n,n=97,mean=float(v.mean()),sd=float(v.std(ddof=1)),
        descriptive_ci_lower=float(v.mean()-t.ppf(.975,96)*v.std(ddof=1)/np.sqrt(97)),
        descriptive_ci_upper=float(v.mean()+t.ppf(.975,96)*v.std(ddof=1)/np.sqrt(97))) for n,v in values.items()]))
    # Correlation overview uses the complete raw N=97 data; no casewise dropping.
    names = list(LABELS); array = np.column_stack([raw[n] for n in names]); r = np.corrcoef(array, rowvar=False)
    rho = spearmanr(array).statistic
    fig, ax = plt.subplots(figsize=(7,6), constrained_layout=True)
    combined = np.where(np.triu(np.ones_like(r),1).astype(bool), rho, r)
    image = ax.imshow(combined, cmap="RdBu_r", vmin=-1, vmax=1)
    for i in range(6):
        for j in range(6): ax.text(j,i,f"{combined[i,j]:.2f}",ha="center",va="center",color="white" if abs(combined[i,j])>.65 else "black")
    ax.set_xticks(range(6),[LABELS[n] for n in names]); ax.set_yticks(range(6),[LABELS[n] for n in names])
    ax.set_title("N=97 | Lower triangle: Pearson; upper: Spearman")
    fig.colorbar(image, ax=ax, shrink=.8); save_figure(fig, report / "figures/correlations.png")
    # Complex JN interval structures are serialized in JSON, not ambiguously flattened.
    (report / "region_fits.json").write_text(base.cohort.json_text(fits))
    sections = ["# Katie Results Review: N=97", "", "All 152 jobs / 336 maps audited; 84 brain panels include nulls and both CDTs/directions.",
        "Existing per-map cluster-FWE only; no additional correction across exploratory models/outcomes.",
        "Association/JN plots from selected clusters are descriptive and circular as inferential confirmation.",
        "JN uses observed moderator ranges and pointwise OLS/HC3 95% t intervals, not spatially corrected intervals.",
        "No participants removed. Per-participant influence tables remain in the separate work details directory.",
        "The dependent variable is the neural estimate, not financial vulnerability. Negative interaction terms mean the focal-score slope becomes more negative as the moderator increases.",
        "Inputs remain the frozen no-TEDANA sm-5 FEAT variant; experimental 6-mm smoothing outputs were not substituted.",
        "", "![Correlations](figures/correlations.png)", "", "![Anatomical VS response](figures/vs-group-response.png)",
        "", "## Corrected Findings", "", "| Batch | Family | Outcome | Model | Term | Direction | CDT | Minimum cluster-FWE p | Voxels |", "|---|---|---|---|---|---|---|---|---|"]
    for row in maps:
        if int(row["significant_voxels"]):
            sections.append("| "+" | ".join(row[n] for n in ("batch","family","outcome","model","term","direction","z","min_cluster_fwe_p","significant_voxels"))+" |")
    sections += ["", "## Brain Maps", ""]
    for result in sorted((r for r in completed if "/brain-" in r["path"]), key=lambda r:r["path"]):
        title = next(t[1]["title"] for t in tasks if t[1]["path"].endswith(result["path"]))
        sections.append(f"- [{title}]({result['path']})")
    sections += ["", "## Association And JN Plots", ""]
    for row in rois: sections.append(f"- [{row['title']}]({row['path']})")
    sections += ["", "## Limits And Untested Effects", "",
        "These plots do not establish mediation, causation, longitudinal cognitive decline, or successful financial-score prediction.",
        "Supplied score/ID completeness is audited; item-level questionnaire scoring and missing-item rules are not independently reconstructed from the score CSV.",
        "Financial/moderation models test the interaction; constituent terms were included, not separately whole-brain contrasted in that batch.",
        "Environmental conditional main effects were separately tested for activation, not VS connectivity. No group-mean PPI contrast was added.",
        "Anatomical VS activation follow-ups include null models. Null connectivity models have no selected cluster to plot; no post-hoc target was invented.",
        "JN regions/ROI intervals are pointwise analytical OLS/HC3 descriptions, not the whole-brain permutation test; selected-cluster intervals are subject to selection bias.",
        "Influence and residual-variance diagnostics do not change the 97-person cohort or trigger new exclusions."]
    (report / "README.md").write_text("\n".join(sections)+"\n")
    body = "<h1>Katie Results Review: N=97</h1><p>152 audited jobs / 336 directional maps. Per-map cluster-FWE; exploratory across models.</p>"
    body += "<p>Selected-cluster association/JN plots are descriptive, not independent confirmation. No cohort/exclusion changes.</p>"
    body += '<p><a href="maps.tsv">All maps, including nulls</a> | <a href="clusters.tsv">Cluster summaries</a> | <a href="region_fits.json">ROI/JN diagnostics</a></p>'
    body += '<img src="figures/correlations.png" alt="Factor correlations"><img src="figures/vs-group-response.png" alt="Anatomical VS group response">'
    for function, task in tasks:
        relative = str(Path(task["path"]).relative_to(report))
        body += f'<h2>{html.escape(task["title"])}</h2><img loading="lazy" src="{relative}" alt="{html.escape(task["title"])}">'
    (report / "index.html").write_text('<!doctype html><html><head><meta charset="utf-8"><title>Katie Results Review</title><style>body{font:15px system-ui;margin:24px;color:#222;max-width:1500px}img{max-width:100%;height:auto}h2{font-size:16px;margin-top:32px}</style></head><body>'+body+'</body></html>')
    # Seal only aggregate tables/plots. Raw participant influence values are outside this tree.
    outputs = {str(p.relative_to(report)):base.cohort.digest(p) for p in report.rglob("*") if p.is_file() and p.name != "review_manifest.json"}
    base.verify_sources(review_sources)
    manifest = dict(n=97, jobs=152, maps=336, brain_panels=84, association_plots=len(rois), outputs=outputs,
        review_sources=review_sources,
        background=base.fingerprint(background), code=base.fingerprint(Path(__file__)),
        versions={n:importlib.metadata.version(n) for n in ("numpy","scipy","statsmodels","nilearn","matplotlib","nibabel")},
        selected_cluster_plots_are_descriptive=True, exclusions_changed=False)
    (report / "review_manifest.json").write_text(base.cohort.json_text(manifest))
    print(f"CHECK PASSED: {len(outputs)} aggregate review artifacts; 84 brain panels; {len(rois)} association/JN plots.", flush=True)


def check(report, jobs):
    manifest = json.loads((report / "review_manifest.json").read_text())
    records = {str(report / p):dict(path=str(report / p),sha256=d) for p,d in manifest["outputs"].items()}
    audit.verify_records(records, jobs)
    base.verify_sources(manifest["review_sources"])
    audit.verify_records({r["path"]:r for r in json.loads((report / "audit.json").read_text())["fingerprint_records"]}, jobs)
    print("CHECK PASSED: review artifacts and full original-source/result graph unchanged after plotting.", flush=True)


def main():
    os.umask(0)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build","check")); parser.add_argument("--project",type=Path,required=True)
    parser.add_argument("--report",type=Path,required=True); parser.add_argument("--details",type=Path)
    parser.add_argument("--background",type=Path); parser.add_argument("--jobs",type=int,default=24)
    args = parser.parse_args()
    if not 1 <= args.jobs <= 48: parser.error("--jobs must be 1..48")
    if args.command == "check": check(args.report,args.jobs); return
    if args.background is None or not args.background.is_file(): parser.error("A local MNI background is required; no downloads guessed")
    figures(args.project.resolve(),args.report.resolve(),args.details.resolve(),args.background.resolve(),args.jobs)


if __name__ == "__main__":
    try: main()
    except Exception as exc:
        print(f"FAILED ({type(exc).__name__}): {exc}",file=sys.stderr,flush=True);sys.exit(1)
