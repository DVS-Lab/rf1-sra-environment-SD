"""Stage the November 17 manuscript selections from the validated aggregate figure kit."""
import csv
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "publication/figures-v1"
KIT = ROOT / "publication/manuscript-figures"
MAPS = {
    "Fig3_ADIxMSPSS_social_minus_nonsocial_win_z3p1_positive": (
        "f4ea70d4199ed87235a1a893cb110d21d019bfd960abb361ecdd9a796ce913a1",
        "64cd31702e6d3f45ae95d333294b56fdad32ae4d4d06c1f725487c6c0c6f5f5f"),
    "Fig2_FEVS_at_mean_PM25_domain_by_valence_z3p1_negative": (
        "30d794c65b97c4d60ea4630fe9511494d777fbb010f171a990ecb30f4cb8df72",
        "b329c86435e636239b1078c8729b3860830caad9c256cc79efc55a3c0ce8a586"),
}

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))

def table(path, rows):
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

def activation_curve(anchors, x):
    m, y, lo, hi = np.array([[float(r[k]) for k in
        ("moderator","slope","hc3_lower","hc3_upper")] for r in anchors]).T
    # For the saved linear contrast, squared pointwise interval width is quadratic.
    # Three reported anchors recover the curve; no model is fit to participant data.
    b = (y[-1]-y[0])/(m[-1]-m[0])
    sq = np.linalg.solve(np.vander(m-4,3), ((hi-lo)/2)**2)
    if not (np.allclose(y, y[0]+b*(m-m[0]), atol=1e-10, rtol=0)
            and np.allclose(y, (hi+lo)/2, atol=1e-10, rtol=0) and np.all(np.polyval(sq,x-4)>0)):
        raise ValueError("Published conditional-slope anchors are inconsistent")
    val = y[0]+b*(x-m[0])
    half = np.sqrt(np.polyval(sq,x-4))
    return [dict(component=anchors[0]["component"],support=float(a),slope=float(v),
                 hc3_lower=float(v-h),hc3_upper=float(v+h)) for a,v,h in zip(x,val,half)]

def stage():
    for record in read(OLD/"sources/provenance.tsv"):
        if sha(OLD/record["asset"]) != record["sha256"]:
            raise ValueError("Changed source: "+record["asset"])
    source = OLD/"sources"
    f1,f2,f3 = [KIT/f"Figure-{i}" for i in (1,2,3)]
    s1,s3 = [KIT/"supplement"/f"Figure-S{i}" for i in (1,3)]
    linear = [r for r in read(source/"fig1/behavior_curves.tsv") if r["model"]=="linear"]
    if len(linear)!=201:
        raise ValueError("Expected the 201 published primary estimates")
    table(f1/"plotted-values.tsv",linear)
    summary=read(source/"fig3/activation_slopes.tsv")
    for out,comps in ((f2,["difference"]),(s3,["socialdoors","doors"])):
        anchors=[r for r in summary if r["component"] in comps]
        table(out/"published-anchors.tsv",anchors)
        table(out/"plotted-values.tsv",[v for k in comps for v in
              activation_curve([a for a in anchors if a["component"]==k],np.linspace(1,7,201))])
    fevs=[r for r in read(source/"fig2/vs_component_estimates.tsv") if r["component"]=="difference"]
    if len(fevs)!=1 or fevs[0]["n"]!="97":
        raise ValueError("Wrong fixed-region connectivity contrast")
    table(f3/"plotted-values.tsv",[{k:fevs[0][k] for k in ("component","n","beta","hc3_lower","hc3_upper")}])
    shutil.copyfile(source/"fig1/histograms.json",s1/"histogram-counts.json")
    for out,path in [(f2,source/"fig3/figure-3-adi-support-brain.png"),
                     (f3,source/"fig2/figure-2-vs-original-brain.png")]:
        with Image.open(path) as im:
            if im.size!=(2200,946):
                raise ValueError("Original brain plate dimensions changed")
            im.convert("RGB").crop((44,132,2134,778)).save(out/"brain-slices.png")
    for name,hashes in MAPS.items():
        row,=[r for r in read(OLD/"group-maps/maps.tsv") if r["stem"]==name]
        for out in ((f2,s3) if row["direction"]=="positive" else (f3,)):
            stem=name.split("_",1)[1]
            for suffix,expected in zip(("mask","signed-t"),hashes):
                src=OLD/"group-maps"/f"{name}_{suffix}.nii.gz"
                if sha(src)!=expected:
                    raise ValueError("Native map differs: "+src.name)
                shutil.copyfile(src,out/f"{stem}_{suffix}.nii.gz")
            table(out/"map-index.tsv",[dict(row,stem=stem,mask_sha256=hashes[0],signed_t_sha256=hashes[1])])
    if sha(s1/"Figure-S1.png")!="cc14fe9a80da24d524f61b449ee608ae71da8fe51f8de297a105946c74bb3c99":
        raise ValueError("Supplementary diagnostic artwork differs from the submitted Word image")

if __name__=="__main__":
    stage()
