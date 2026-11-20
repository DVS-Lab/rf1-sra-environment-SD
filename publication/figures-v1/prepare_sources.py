"""Collect sealed figure inputs. Only histogram bins, never individual rows, are exported."""
from pathlib import Path
import csv
import hashlib
import json
import shutil
import sys

import numpy as np

KIT = Path(__file__).resolve().parent
ROOT = KIT.parents[1]
sys.path.insert(0, str(ROOT / "code"))
import review_katie_targeted as targeted

REVIEW = ROOT / "results/review"
BEH = "katie-targeted-behavior-v1"
NAT = "katie-targeted-native-v1"
OLD = "katie-results-ready-v1"
ASSETS = {
    "fig1": (BEH, ["behavior_curves.tsv", "behavior_coefficients.tsv", "behavior_tail_counts.tsv",
                   "behavior_anchors.tsv", "behavior_influence.tsv"]),
    "fig2": (OLD, ["figure-2-vs-original-brain.png", "figure-2-vs-components.png", "vs_component_estimates.tsv"]),
    "fig3": (NAT, ["activation_components.tsv", "activation_slopes.tsv", "activation_group_overlap.tsv",
                   "activation_tail_counts.tsv"]),
    "fig4": (NAT, ["vs_clusters.tsv", "vs_cluster_overlap.tsv", "vs_map_overlap.tsv", "vs_maps.tsv"]),
}

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def prepare():
    index = []
    for key, group, files in [*( (k,*v) for k,v in ASSETS.items()), ("fig3", OLD, ["figure-3-adi-support-brain.png"])]:
        root = REVIEW/group
        m = json.loads((root / ("report-manifest.json" if group == OLD else "review_manifest.json")).read_text())
        for name in files:
            src = root/name
            expected = m["outputs"][str(src.relative_to(ROOT)) if group == OLD else name]
            if digest(src) != expected:
                raise ValueError("Source seal differs: " + name)
            dst = KIT/"sources"/key/name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src,dst)
            index.append((str(dst.relative_to(KIT)),str(src.relative_to(ROOT)),expected))

    # Recover the original histogram bins from the approved scores and saved coefficients,
    # without fitting a model. Only counts and bin boundaries leave this function.
    ids,v = targeted.values()
    names,x = targeted.prior.previous.behavior.design(v,"pm25","mspss")
    home = KIT/"sources/fig1"
    read = targeted.prior.read
    coef = {r["term"]:float(r["beta"]) for r in read(home/"behavior_coefficients.tsv") if r["model"]=="linear"}
    resid = v["fevs"] - x @ [coef[n] for n in names]
    h = np.square(np.linalg.qr(x,mode="reduced")[0]).sum(axis=1)
    mse = resid@resid/(len(ids)-len(names))
    cooks = resid**2*h/(len(names)*mse*(1-h)**2)
    diag = next(r for r in read(home/"behavior_influence.tsv") if r["model"]=="linear")
    if not (len(ids)==97 and np.isclose(cooks.max(),float(diag["max_cooks_d"]),rtol=1e-10)
            and sum(cooks>4/97)==int(diag["n_cooks_above_4_over_n"])):
        raise ValueError("Cook histogram does not reconcile")
    counts, sx, py = np.histogram2d(v["mspss"], v["pm25"], bins=(np.linspace(1,7,13),10))
    cc, edges = np.histogram(cooks,bins=13)
    if counts.sum()!=97 or cc.sum()!=97:
        raise ValueError("Histogram lost observations")
    (home/"histograms.json").write_text(json.dumps(dict(n=97, mspss_edges=sx.tolist(),
        pm25_edges=py.tolist(), joint_counts=counts.astype(int).tolist(),
        cook_edges=edges.tolist(), cook_counts=cc.tolist()), indent=2)+"\n")
    with (KIT/"sources/provenance.tsv").open("w",newline="") as f:
        writer=csv.writer(f,delimiter="\t",lineterminator="\n")
        writer.writerow(["asset","sealed_repository_source","sha256"])
        writer.writerows(index)

if __name__=="__main__":
    prepare()
