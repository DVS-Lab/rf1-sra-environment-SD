#!/usr/bin/env python3
"""Read-only, fixed-scope Katie follow-up. No imaging inference or input edits."""
from __future__ import annotations

import argparse
from itertools import combinations
import json
import os
from pathlib import Path
import tempfile

import numpy as np
from scipy.ndimage import label
from scipy.stats import t

import review_katie_closeout as prior
import run_social_win_mean as group_mean

base, audit = prior.base, prior.extension.audit
plt, nib = prior.plt, prior.nib
ROOT = Path(__file__).resolve().parents[1]
VERSION = "katie-targeted-native-v1"
AUTH = ROOT / "config/katie_targeted_followup_v1.json"
OUTCOMES = ("average", "loss_only", "social_specific")
LABELS = {"average": "Domain-average win-loss", "loss_only": "Social minus nonsocial loss",
          "social_specific": "Social-by-valence"}
STRUCTURE = np.ones((3, 3, 3), dtype=bool)
COLORS = ("#156971", "#ac4c25", "#3b536e")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def one(rows):
    rows = list(rows)
    require(len(rows) == 1, "Expected exactly one authorized source; found " + str(len(rows)))
    return rows[0]


def write(path, value):
    path.write_text(base.cohort.json_text(value))


def table(out, name, rows, fields=None):
    (out / (name + ".tsv")).write_text(base.review.tsv(rows, fields))


def values():
    ids, v = prior.previous.behavior.inputs(ROOT)
    v["mspss"] = prior.correction.corrected_scores(ROOT, ids, v["mspss"])
    return ids, v


def support_groups(s):
    levels = np.quantile(s, [.16, .50, .84], method="nearest")
    lo, _, hi = levels
    require(lo < hi, "Support tails are not distinct")
    return levels, (s <= lo, (s > lo) & (s < hi), s >= hi)


def slope_vectors(names, exposure, term, s, levels, curvature=None):
    delta = np.asarray(levels) - np.mean(s)
    vectors = np.zeros((len(delta), len(names)))
    vectors[:, names.index(exposure)] = 1
    vectors[:, names.index(term)] = delta
    if curvature:
        vectors[:, names.index(curvature)] = delta ** 2
    return vectors


def slopes(fit, vectors):
    y = vectors @ fit.params
    se = np.sqrt(np.maximum(0, np.einsum("ij,jk,ik->i", vectors, fit.cov_params(), vectors)))
    half = t.ppf(.975, fit.df_resid) * se
    return y, y - half, y + half


def named_fit(names, x, y, term):
    ordinary, robust, info, _ = prior.fit_summary(x, y, names, term)
    return ordinary, robust, info


def quadratic(names, x):
    s2 = x[:, names.index("mspss")] ** 2
    p = x[:, names.index("pm25")]
    return [*names, "mspss_squared", "pm25_x_mspss_squared"], np.column_stack((x, s2, p*s2))


def density_rows(s, exposure, exposure_name):
    levels, groups = support_groups(s)
    return [dict(group=key, n=int(g.sum()), lower_support_cut=float(levels[0]),
                 upper_support_cut=float(levels[2]), support_min=float(s[g].min()),
                 support_max=float(s[g].max()), exposure=exposure_name,
                 exposure_min=float(exposure[g].min()), exposure_max=float(exposure[g].max()),
                 exposure_q10=float(np.quantile(exposure[g], .1)),
                 exposure_q90=float(np.quantile(exposure[g], .9)))
            for key, g in zip(("lower_tail", "middle", "upper_tail"), groups)]


def curve(ax, fit, names, exposure, term, moderator, color, name, curvature=None):
    grid = np.linspace(moderator.min(), moderator.max(), 201)
    v = slope_vectors(names, exposure, term, moderator, grid, curvature)
    estimate, lo, hi = slopes(fit, v)
    ax.plot(grid, estimate, color=color, lw=2, label=name)
    ax.fill_between(grid, lo, hi, color=color, alpha=.13)


def behavior(out):
    _, v = values()
    s, p, y = v["mspss"], v["pm25"], v["fevs"]
    levels, _ = support_groups(s)
    names, x = prior.previous.behavior.design(v, "pm25", "mspss")
    qnames, qx = quadratic(names, x)
    original = ROOT / "results/review/behavioral-mspss-corrected-provisional-v1"
    manifest = json.loads((original/"review_manifest.json").read_text())
    for name in ("diagnostics.tsv", "interactions.tsv"):
        require(base.cohort.digest(original/name) == manifest["outputs"][name], "Baseline aggregate seal differs")
    diag = one(r for r in prior.read(original/"diagnostics.tsv") if r["model"]=="fevs_pm25_mspss")
    effect = one(r for r in prior.read(original/"interactions.tsv") if r["model"]=="fevs_pm25_mspss")
    summary, anchors, curves, coefficients = [], [], [], []
    fig, axes = plt.subplots(2, 2, figsize=(10, 6.25), layout="constrained")
    # Aggregate bins only; no point corresponds to a participant record.
    h = axes[0, 0].hist2d(s, p, bins=(np.linspace(1, 7, 13), np.histogram_bin_edges(p, bins=10)), cmap="GnBu", cmin=1)
    fig.colorbar(h[3], ax=axes[0, 0], label="Observations per bin")
    axes[0, 0].set(title="Observed joint distribution", xlabel="Corrected MSPSS", ylabel="PM2.5 (µg/m³)")
    axes[0, 1].hist(s, bins=np.linspace(1, 7, 13), color=COLORS[0])
    axes[0, 1].set(title="Density across support scores", xlabel="Corrected MSPSS", ylabel="Observations per 0.5 points")
    rows = density_rows(s, p, "PM2.5")
    axes[0, 1].text(.03, .96, f"Lower tail: n={rows[0]['n']}\nUpper tail: n={rows[2]['n']}", transform=axes[0, 1].transAxes, va="top")
    for ax in axes[0]:
        for level in levels[[0, 2]]:
            ax.axvline(level, ls="--", color="#494b50", lw=.9)
    for i, (name, columns, design, extra) in enumerate((
        ("linear", names, x, None), ("quadratic_support", qnames, qx, "pm25_x_mspss_squared")
    )):
        ordinary, robust, info = named_fit(columns, design, y, "interaction")
        coefficients.extend(dict(model=name, term=k, beta=float(b), hc3_se=float(se),
                                 hc3_lower=float(ci[0]), hc3_upper=float(ci[1]))
                            for k,b,se,ci in zip(columns,robust.params,robust.bse,robust.conf_int()))
        if i == 0:
            for field in ("max_cooks_d", "n_cooks_above_4_over_n", "max_leverage", "loo_beta_min", "loo_beta_max"):
                require(np.isclose(info[field], float(diag[field]), atol=1e-9, rtol=0), "Published influence check differs")
            require(np.isclose(info["beta"], float(effect["interaction_beta"]), atol=1e-9, rtol=0), "Published interaction differs")
        vectors = slope_vectors(columns, "pm25", "interaction", s, levels, extra)
        estimates, lows, highs = slopes(robust, vectors)
        loo = np.stack([np.linalg.lstsq(np.delete(design, j, 0), np.delete(y, j), rcond=None)[0] for j in range(97)])
        conditional_loo = loo @ vectors.T
        for j, percentile in enumerate((16, 50, 84)):
            anchors.append(dict(model=name, percentile=percentile, support=float(levels[j]),
                pm25_slope=float(estimates[j]), hc3_lower=float(lows[j]), hc3_upper=float(highs[j]),
                loo_min=float(conditional_loo[:, j].min()), loo_max=float(conditional_loo[:, j].max())))
        info.pop("selected_cluster_descriptive")
        summary.append(dict(model=name, r_squared=float(ordinary.rsquared), **info))
        grid = np.linspace(s.min(), s.max(), 201)
        vectors = slope_vectors(columns, "pm25", "interaction", s, grid, extra)
        curvevals = slopes(robust, vectors)
        curves.extend(dict(model=name, support=float(g), pm25_slope=float(b), hc3_lower=float(l), hc3_upper=float(h))
                      for g, b, l, h in zip(grid, *curvevals))
        curve(axes[1, 0], robust, columns, "pm25", "interaction", s, COLORS[i],
              ("Linear", "Quadratic support")[i], extra)
        if i == 0:
            axes[1, 1].hist(ordinary.get_influence().cooks_distance[0], bins=13, color=COLORS[0])
            axes[1, 1].axvline(4/97, ls="--", color="#494b50", label="4/N diagnostic guide")
    axes[1, 0].axhline(0, color="#494b50", lw=.8)
    axes[1, 0].set(title="Conditional PM2.5 slopes (pointwise HC3 95% CIs)", xlabel="Corrected MSPSS", ylabel="FEVS points per PM2.5 unit")
    axes[1, 0].legend(frameon=False)
    axes[1, 1].set(title="Original linear-model influence", xlabel="Cook's distance", ylabel="Observations")
    axes[1, 1].legend(frameon=False)
    fig.savefig(out/"behavior.png", dpi=200); plt.close(fig)
    table(out, "behavior_tail_counts", rows)
    table(out, "behavior_anchors", anchors)
    table(out, "behavior_curves", curves)
    table(out, "behavior_influence", summary)
    table(out, "behavior_coefficients", coefficients)
    write(out/"behavior.json", dict(n=97, tails=rows, anchors=anchors, fits=summary,
        baseline_holm_p=float(effect["holm_family_p"]), financial_scoring_provisional=True,
        authorization_sha256=base.cohort.digest(AUTH)))


def checked_matrix(job, ids, v, outcome, term, direction, index):
    x, c = audit.matrix(job["design"]), audit.matrix(job["contrast"])
    fields, rows = base.cohort.read_table(Path(job["design"]).with_suffix(".tsv"))
    names = fields[1:]
    require(len(names) == x.shape[1] and len(set(names)) == len(names), "Invalid design columns")
    qc = ["pair_mean_fd", "pair_mean_tsnr"] if outcome == "average" else ["delta_fd", "delta_tsnr"]
    expected = ["ones", *qc, "e11", "xa30", "gender_code1", "age"]
    if term != "ones":
        a, b = "adi", "mspss" if term == "adixmspss" else "ecog"
        expected += [a, b, term]
    require(names == expected and fields[0] == "subject" and [r["subject"] for r in rows] == ids
            and x.shape == (97, len(names)) and np.isfinite(x).all()
            and np.linalg.matrix_rank(x) == len(names)
            and job["residual_dof"] == 97 - len(names)
            and np.array_equal(x[:, 0], np.ones(97))
            and np.allclose(x, [[float(r[n]) for n in names] for r in rows], rtol=0, atol=1e-12),
            "Saved design, labels or N=97 order differ")
    for name in set(names) & set(v):
        require(np.allclose(x[:,names.index(name)], v[name]-v[name].mean(), rtol=0, atol=1e-10),
                "Saved centered covariate differs: " + name)
    if term != "ones":
        require(np.allclose(x[:, -1], x[:, -2]*x[:, -3], rtol=0, atol=1e-10), "Saved interaction differs")
    weight = np.zeros(len(names)); weight[names.index(term)] = 1 if direction == "positive" else -1
    require(c.shape[1] == len(names) and 1 <= index <= len(c) and np.array_equal(c[index-1], weight),
            "Native contrast does not test the requested signed coefficient")
    return names, x


def load_map(folder, plan, job, index, records):
    receipt = folder/"jobs"/job["key"]/"success.json"
    saved = json.loads(receipt.read_text())
    prefix = Path(saved["attempt"])/"randomise"
    mask = plan.get("mask") or plan["masks"][job["family"]]
    require(prefix.parent.resolve().is_relative_to((receipt.parent/"attempts").resolve())
            and saved["job"] == job and saved["plan_sha256"] == base.cohort.digest(folder/"plan.json")
            and saved["smoke"] is False and job["permutations"] == 10000 and job["seed"] == 20261101
            and saved["command"] == base.command(dict(plan, mask=mask), job, prefix), "Native completion receipt differs")
    prior.add(records, receipt)
    for r in saved["outputs"]:
        audit.add_record(records, r["path"], r["sha256"], r.get("size"))
    paths = [Path(str(prefix)+f"_tstat{index}.nii.gz"), Path(str(prefix)+f"_clustere_corrp_tstat{index}.nii.gz")]
    for p in paths:
        require(p.resolve().as_posix() in records, "Target native map not sealed by receipt")
    ref = nib.load(mask)
    stat, prob = (nib.load(p) for p in paths)
    base.grid(ref, stat); base.grid(ref, prob)
    data, p = stat.get_fdata(), prob.get_fdata()
    support = ref.get_fdata() > 0
    selected = support & (p > .95)
    require(support.any() and np.isfinite(data).all() and np.isfinite(p).all() and p.min() >= 0 and p.max() <= 1
            and np.all(data[selected] >= job["t_cutoff"]-1e-5), "Invalid native corrected map/CDT")
    selected_path = Path(plan["images"][job["outcome"]])
    for path in (Path(mask), selected_path, Path(job["design"]), Path(job["contrast"]),
                 Path(job["design"]).with_suffix(".tsv")):
        require(str(path.resolve()) in records, "Target input not sealed by original plan: " + path.name)
    return ref, data, p, selected


def region_values(path, ref, region):
    image = nib.load(path)
    base.grid(ref, image, 4)
    require(image.shape[3] == 97 and region.any(), "Invalid fixed region/stack")
    result = image.get_fdata(dtype=np.float32)[region]
    require(np.isfinite(result).all(), "Nonfinite selected region")
    return result


def overlap(a, b):
    na, nb, both = int(a.sum()), int(b.sum()), int((a & b).sum())
    return dict(voxels_a=na, voxels_b=nb, shared_voxels=both,
                fraction_a=both/na if na else None, fraction_b=both/nb if nb else None,
                dice=2*both/(na+nb) if na+nb else None)


def same_mask(a, b):
    base.grid(a, b)
    require(np.array_equal(a.get_fdata() > 0, b.get_fdata() > 0), "Native search masks differ")


def components(original_folder, records, ids, ref, region, stack):
    source = original_folder/"source_order.tsv"
    require(str(source.resolve()) in records, "Component order not sealed")
    all_rows = prior.read(source)
    lookup = base.cohort.unique([r for r in all_rows if r["family"]=="activation" and r["cope"]=="1"],
                                ("subject", "task"))
    require(len(lookup) == 194, "Expected 194 sealed activation win COPEs")
    arrays = {key: [] for key in ("socialdoors", "doors")}
    for i, s in enumerate(ids):
        for task in arrays:
            row = lookup[(s, task)]
            path = Path(row["source"])
            require(int(row["volume"]) == i and path.name == "cope1.nii.gz"
                    and str(path.resolve()) in records, "Win COPE provenance/order differs")
            image = nib.load(path); base.grid(ref, image)
            arrays[task].append(image.get_fdata()[region])
        require(np.array_equal((arrays["socialdoors"][-1]-arrays["doors"][-1]).astype(np.float32), stack[:, i]),
                "Wrong component data or contrast direction: social minus nonsocial win did not reconstruct")
    return {key: np.asarray(a).mean(axis=1) for key, a in arrays.items()}


def neural(project, out, records):
    ids, v = values()
    bf = project/"derivatives/fsl/randomise"
    original_folder = bf/"katie-reward-extension-v1"
    corrected_folder = bf/"katie-mspss-corrected-v1"
    group_folder = bf/group_mean.VERSION
    original, corrected, group = [prior.plan_and_receipts(p, records, False)
                                  for p in (original_folder, corrected_folder, group_folder)]
    for folder, plan in zip((original_folder, corrected_folder, group_folder), (original, corrected, group)):
        require(plan["project"] == str(project) and not plan["exclusions_changed"], "Plan project/cohort changed")
        require([r["subject"] for r in prior.read(folder/"subjects.tsv")] == ids, "Native stack order differs")
    require(len(original["coverage"]) == 1328 and len(corrected["jobs"]) == 64 and len(group["jobs"]) == 2, "Wrong source batch")
    published = ROOT/"results/review/katie-results-ready-v1"
    for name in ("scientific_inventory.tsv", "scientific_clusters.tsv"):
        manifest = json.loads((published/"report-manifest.json").read_text())
        require(base.cohort.digest(published/name)==manifest["outputs"][str((published/name).relative_to(ROOT))], "Published map seal differs")
        prior.add(records, published/name)
    old_maps = {prior.key(row): row for row in prior.read(published/"scientific_inventory.tsv")}
    old_clusters = prior.read(published/"scientific_clusters.tsv")

    def reconcile(family, outcome, term, direction, z, ref, data, p, selected):
        k = (family, outcome, term, term, direction, z)
        row = old_maps[k]
        expected = [r for r in old_clusters if prior.key(r) == k]
        labels, count = label(selected, structure=STRUCTURE)
        require(count == int(row["significant_clusters"]) == len(expected)
                and int(selected.sum()) == int(row["significant_voxels"])
                and np.isclose(1-p[ref.get_fdata()>0].max(), float(row["min_cluster_fwe_p"]), atol=1e-7, rtol=0),
                "Native map does not reconcile with November 7 catalog")
        clusters = []
        for r in expected:
            region = labels == int(r["component"])
            voxel = np.argwhere(region)[data[region].argmax()]
            peak = nib.affines.apply_affine(ref.affine, voxel)
            cluster_p = 1-p[region].max()
            require(int(region.sum()) == int(r["voxels"])
                    and np.isclose(cluster_p, float(r["cluster_fwe_p_min"]), atol=1e-7, rtol=0)
                    and np.allclose(peak, [float(r["peak_"+axis+"_mm"]) for axis in "xyz"], atol=1e-5, rtol=0),
                    "Native component does not reconcile with November 7 cluster table")
            atlas = prior.atlas_annotations(ref, region, peak, records)
            clusters.append((region, dict(component=int(r["component"]), voxels=int(region.sum()),
                p=float(cluster_p), peak=peak.tolist(), atlas=atlas)))
        return clusters, float(row["min_cluster_fwe_p"])

    job = one(j for j in corrected["jobs"] if j["key"]=="activation/win_only/adixmspss/z-3p1")
    index = one(d for d in job["contrasts"] if (d["term"],d["direction"])==("adixmspss","positive"))["index"]
    ref, data, p, region = load_map(corrected_folder, corrected, job, index, records)
    names, x = checked_matrix(job, ids, v, "win_only", "adixmspss", "positive", index)
    clusters, _ = reconcile("activation", "win_only", "adixmspss", "positive", 3.1, ref, data, p, region)
    require(len(clusters)==1 and clusters[0][1]["voxels"]==87 and abs(clusters[0][1]["p"]-.0255)<1e-7,
            "Fixed activation cluster differs")
    win = corrected["images"][job["outcome"]]
    require(win == original["images"]["activation/win_only"] == group["images"]["social_win"], "Social-win image lineage differs")
    stack = region_values(win, ref, region)
    estimates = components(original_folder, records, ids, ref, region, stack)
    estimates["difference"] = stack.mean(axis=0, dtype=np.float64)
    group_overlap = []
    for g in group["jobs"]:
        signed = []
        for index, direction in enumerate(("positive", "negative"), 1):
            gg, _, _, mask = load_map(group_folder, group, g, index, records)
            same_mask(ref, gg); checked_matrix(g, ids, v, "win_only", "ones", direction, index)
            group_overlap.append(dict(z=g["z"], direction=direction, **overlap(region, mask)))
            signed.append(mask)
        group_overlap.append(dict(z=g["z"], direction="either", **overlap(region, signed[0]|signed[1])))
    activation, activ_slopes = [], []
    fig, ax = plt.subplots(figsize=(8.3, 4.1), layout="constrained")
    for i, (component, y) in enumerate(estimates.items()):
        _, robust, result = named_fit(names, x, y, "adixmspss")
        activation.append(dict(component=component, **result))
        levels, _, _, _, _ = prior.conditional(robust, names, "adi", "adixmspss", v["mspss"])
        activ_slopes.extend(dict(component=component, **row) for row in levels)
        curve(ax, robust, names, "adi", "adixmspss", v["mspss"], COLORS[i],
              ("Social win", "Nonsocial win", "Social minus nonsocial")[i])
    require(np.isclose(activation[0]["beta"]-activation[1]["beta"], activation[2]["beta"], atol=1e-7, rtol=0),
            "Fixed-region coefficient decomposition differs")
    ax.axhline(0, color="#494b50", lw=.8)
    ax.set(title="ADI slopes in the same selected 87-voxel region", xlabel="Corrected MSPSS",
           ylabel="Mean activation (COPE units) per ADI rank")
    ax.legend(frameon=False, fontsize=9)
    fig.savefig(out/"activation.png", dpi=200); plt.close(fig)
    table(out,"activation_components",activation); table(out,"activation_slopes",activ_slopes)
    table(out,"activation_group_overlap",group_overlap)
    tails = density_rows(v["mspss"], v["adi"], "ADI")
    table(out,"activation_tail_counts",tails)

    map_rows, vs_clusters, map_masks, cluster_masks = [], [], {}, {}
    vs_folder = bf/"katie-remaining-v1/connectivity"
    retained = prior.plan_and_receipts(vs_folder, records, False)
    require([r["subject"] for r in prior.read(vs_folder/"subjects.tsv")]==ids, "Original VS roster differs")
    jobs = {j["key"]: j for j in original["jobs"]}
    vsref = nib.load(original["masks"]["connectivity"])
    for outcome in OUTCOMES:
        for z in (2.6,3.1):
            for direction in ("positive","negative"):
                entry = one(r for r in original["coverage"] if prior.key(r)==("connectivity",outcome,"adixecog","adixecog",direction,z))
                source = entry["source"]
                if source["origin"] == "extension":
                    owner, folder, job = original, original_folder, jobs[source["job"]]
                else:
                    require(source["origin"]=="existing" and source["batch"]=="environment_connectivity","Unknown VS map source")
                    owner, folder, job = retained, vs_folder, source["source_job"]
                    require(job in owner["jobs"] and Path(source["receipt"])==folder/"jobs"/job["key"]/"success.json",
                            "Retained VS receipt differs")
                index = source["index"]
                require(job["model"]=="adixecog" and job["z"]==z
                        and owner["images"][job["outcome"]]==original["images"]["connectivity/"+outcome],
                        "VS map points to wrong outcome/model")
                vv, data, p, selected = load_map(folder,owner,job,index,records)
                same_mask(vsref,vv)
                names,x = checked_matrix(job,ids,v,outcome,"adixecog",direction,index)
                found, minp = reconcile("connectivity",outcome,"adixecog",direction,z,vv,data,p,selected)
                tag = dict(outcome=outcome,z=z,direction=direction)
                map_id = f"{outcome}/{z}/{direction}"
                map_rows.append(dict(map=map_id, **tag, min_p=minp, voxels=int(selected.sum()), clusters=len(found)))
                # Aggregate across signs for map-scale overlap, without conflating the signs of clusters.
                map_masks[(outcome,z)] = map_masks.get((outcome,z),np.zeros_like(selected)) | selected
                if not found:
                    continue
                allvalues = region_values(owner["images"][job["outcome"]],vv,selected)
                for rr, info in found:
                    y=allvalues[rr[selected]].mean(axis=0,dtype=np.float64)
                    _, _, fit = named_fit(names,x,y,"adixecog")
                    cluster_id = f"C{len(vs_clusters)+1:02d}"
                    vs_clusters.append(dict(id=cluster_id, **tag, **info, **fit))
                    cluster_masks[cluster_id]=(rr,info["peak"])
    vs_overlaps = []
    for aa,bb in combinations(vs_clusters,2):
        a,b = aa["id"],bb["id"]
        ra,pa=cluster_masks[a]; rb,pb=cluster_masks[b]
        vs_overlaps.append(dict(a=a,b=b,peak_distance_mm=float(np.linalg.norm(np.subtract(pa,pb))),
                                 **overlap(ra,rb)))
    map_overlap = [dict(outcome_a=a[0],z_a=a[1],outcome_b=b[0],z_b=b[1],**overlap(map_masks[a],map_masks[b]))
                   for a,b in combinations(map_masks,2)]
    table(out,"vs_maps",map_rows); table(out,"vs_cluster_overlap",vs_overlaps); table(out,"vs_map_overlap",map_overlap)
    flat = [dict(**{k:v for k,v in c.items() if k not in ("peak","atlas")},
                 peak_x=c["peak"][0],peak_y=c["peak"][1],peak_z=c["peak"][2],
                 atlas_peak="; ".join(a["peak_label"] for a in c["atlas"])) for c in vs_clusters]
    table(out,"vs_clusters",flat)
    plot_overlap(out,vs_clusters,cluster_masks)
    write(out/"native.json",dict(n=97, activation=dict(cluster=clusters[0][1], fits=activation,
        group_overlap=group_overlap, support=tails), vs=dict(maps=map_rows, clusters=vs_clusters,
        cluster_overlap=vs_overlaps,map_overlap=map_overlap), new_permutation_jobs=0, exclusions_changed=False))


def plot_overlap(out, clusters, masks):
    n=len(clusters)
    matrix=np.array([[overlap(masks[a["id"]][0],masks[b["id"]][0])["dice"] for b in clusters] for a in clusters])
    fig, ax = plt.subplots(figsize=(8,5.2),layout="constrained")
    im=ax.imshow(matrix,vmin=0,vmax=1,cmap="GnBu")
    fig.colorbar(im,ax=ax,label="Dice overlap")
    ticks=[f'{c["id"]} · {dict(average="Avg",loss_only="Loss",social_specific="DxV")[c["outcome"]]} {c["z"]}' for c in clusters]
    ax.set_xticks(range(n),ticks,rotation=50,ha="right",fontsize=8)
    ax.set_yticks(range(n),ticks,fontsize=8)
    for i,j in np.ndindex(matrix.shape):
        ax.text(j,i,f"{matrix[i,j]:.2f}",ha="center",va="center",fontsize=7,color="white" if matrix[i,j]>.65 else "#223")
    ax.set_title("ADI × ECog VS connectivity: overlap of corrected clusters")
    fig.savefig(out/"vs_overlap.png",dpi=200); plt.close(fig)


def aggregate(project, kind):
    root = project/"work"/(VERSION if kind=="native" else "katie-targeted-behavior-v1")
    root.mkdir(parents=True,exist_ok=True)
    report = root/"report"
    if report.exists():
        verify(root,kind)
        return
    stage = Path(tempfile.mkdtemp(prefix=".targeted-",dir=root)); stage.chmod(0o777)
    records = {}
    for path in (AUTH, Path(__file__), Path(prior.__file__), Path(group_mean.__file__),
                 ROOT/prior.correction.SCORES, ROOT/prior.correction.PROVENANCE):
        prior.add(records,path)
    for p in (prior.previous.behavior.ROSTER,prior.previous.behavior.VARIABLES,prior.previous.behavior.SCORE_FILE,
              prior.previous.behavior.SOURCE_RECEIPT,prior.previous.behavior.POLICY):
        prior.add(records,ROOT/p)
    if kind=="native":
        neural(project,stage,records)
    else:
        behavior(stage)
        baseline = ROOT/"results/review/behavioral-mspss-corrected-provisional-v1"
        for name in ("review_manifest.json","diagnostics.tsv","interactions.tsv"):
            prior.add(records,baseline/name)
    audit.verify_records(records,12)
    intro = f"# Katie targeted follow-up: {kind}\n\nN=97 unchanged; no exclusions and no permutations. Aggregate-only output.\n"
    if kind == "behavior":
        result = json.loads((stage/"behavior.json").read_text())
        lo,hi = result["tails"][0],result["tails"][-1]
        linear,quadratic_high = [r for r in result["anchors"] if r["percentile"]==84]
        intro += (f"\nSupport tails (inclusive 16th/84th-percentile anchors): "
                  f"n={lo['n']} at or below {lo['lower_support_cut']:.2f} and "
                  f"n={hi['n']} at or above {hi['upper_support_cut']:.2f}.\n\n"
                  f"At high support, the linear PM2.5 slope is {linear['pm25_slope']:.2f} "
                  f"[{linear['hc3_lower']:.2f}, {linear['hc3_upper']:.2f}]; "
                  f"the fixed quadratic-support sensitivity gives {quadratic_high['pm25_slope']:.2f} "
                  f"[{quadratic_high['hc3_lower']:.2f}, {quadratic_high['hc3_upper']:.2f}]. "
                  "The negative point estimate survives the sensitivity and every single omission, but "
                  "the quadratic interval includes zero. Distinguish attenuation from a reliably negative high-support association. "
                  "HC3 intervals are pointwise; FEVS scoring remains provisional.\n\n![Behavioral sensitivity](behavior.png)\n")
    else:
        intro += "\nFixed-cluster estimates are descriptive. No new whole-brain tests.\n"
    (stage/"README.md").write_text(intro)
    write(stage/"review_manifest.json",dict(n=97, kind=kind,new_permutation_jobs=0,
        spec_sha256=base.cohort.digest(AUTH),renderer_sha256=base.cohort.digest(Path(__file__)),
        outputs={p.name:base.cohort.digest(p) for p in sorted(stage.iterdir())}))
    write(root/"input_fingerprints_private.json",dict(sources=list(records.values())))
    stage.rename(report)
    verify(root,kind)


def verify(root, kind):
    report=root/"report"
    manifest=json.loads((report/"review_manifest.json").read_text())
    require(manifest["kind"]==kind and manifest["n"]==97 and manifest["new_permutation_jobs"]==0
            and manifest["spec_sha256"]==base.cohort.digest(AUTH)
            and manifest["renderer_sha256"]==base.cohort.digest(Path(__file__)), "Targeted report identity differs")
    for name, sha in manifest["outputs"].items():
        require(Path(name).name==name and base.cohort.digest(report/name)==sha, "Aggregate output seal differs")
    inputs=json.loads((root/"input_fingerprints_private.json").read_text())
    audit.verify_records({r["path"]:r for r in inputs["sources"]},12)
    print(f"CHECK PASSED: {kind} targeted aggregates and {len(inputs['sources'])} input fingerprints; "
          "N=97, no permutations, participant rows or exclusions changed.")


def main():
    os.umask(0)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("build","check"))
    parser.add_argument("--kind",choices=("behavior","native"),required=True)
    parser.add_argument("--project",type=Path,default=ROOT)
    args=parser.parse_args(); project=args.project.resolve()
    if args.command=="build":
        aggregate(project,args.kind)
    else:
        verify(project/"work"/(VERSION if args.kind=="native" else "katie-targeted-behavior-v1"),args.kind)


if __name__=="__main__":
    main()
