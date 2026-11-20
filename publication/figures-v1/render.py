"""Render manuscript figures from the adjacent aggregate source files only."""
from pathlib import Path
import argparse
import csv
import json
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

KIT = Path(__file__).resolve().parent
S = KIT / "sources"
TEAL, RUST, INK = "#156971", "#a64724", "#324b62"
plt.rcParams.update({"font.family":"DejaVu Sans", "font.size":10, "axes.titlesize":11,
    "svg.fonttype":"none", "svg.hashsalt":"katie-publication-v1", "pdf.fonttype":42,
    "axes.spines.top":False, "axes.spines.right":False})

def rows(figure,filename):
    with (S/figure/filename).open(newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def arr(data,key):
    return np.array([float(r[key]) for r in data])

def panel(ax, title):
    ax.set_title(title,loc="left",fontweight="bold",pad=9)

def band(ax,x,y,lo,hi,color,label):
    ax.plot(x,y,color=color,lw=2,label=label)
    ax.fill_between(x,lo,hi,color=color,alpha=.14,linewidth=0)

def behavior():
    fig,axes = plt.subplots(2,2,figsize=(10,6.4),layout="constrained")
    h = json.loads((S/"fig1/histograms.json").read_text())
    counts = np.array(h["joint_counts"])
    a,b,c,d = axes.flat
    hm = a.pcolormesh(h["mspss_edges"], h["pm25_edges"], np.ma.masked_equal(counts.T,0),cmap="GnBu")
    fig.colorbar(hm,ax=a,label="Participants per bin")
    a.set(xlabel="Perceived support (MSPSS)",ylabel="PM2.5 (µg/m³)")
    panel(a,"A   Exposure and support")
    b.stairs(counts.sum(axis=1),h["mspss_edges"],fill=True,color=TEAL)
    b.set(xlabel="Perceived support (MSPSS)",ylabel="Participants per 0.5-point bin")
    panel(b,"B   Distribution of support")
    tails=rows("fig1","behavior_tail_counts.tsv")
    for ax in (a,b):
        for field in ("lower_support_cut","upper_support_cut"):
            ax.axvline(float(tails[0][field]),ls="--",lw=1,color="#565859")
    b.text(.03,.96,f"Lower tail: n = {tails[0]['n']}\nUpper tail: n = {tails[-1]['n']}",transform=b.transAxes,va="top")
    data=rows("fig1","behavior_curves.tsv")
    for key,color,label in [("linear",TEAL,"Linear support"),("quadratic_support",RUST,"Quadratic support")]:
        z=[r for r in data if r["model"]==key]
        band(c,arr(z,"support"),arr(z,"pm25_slope"),arr(z,"hc3_lower"),arr(z,"hc3_upper"),color,label)
    c.axhline(0,lw=.8,color="#666")
    panel(c,"C   PM2.5 slope across support")
    c.set(xlabel="Perceived support (MSPSS)",ylabel="FEVS points per µg/m³")
    c.legend(frameon=False,fontsize=9)
    d.stairs(h["cook_counts"],h["cook_edges"],fill=True,color=TEAL)
    d.axvline(4/97,ls="--",color="#666",label="4/N reference")
    panel(d,"D   Influence in the linear model")
    d.set(xlabel="Cook’s distance",ylabel="Participants")
    d.legend(frameon=False,fontsize=9)
    return fig

def image_panel(ax,path):
    ax.imshow(plt.imread(path),interpolation="none"); ax.set_axis_off()

def pair(width,ratios,titles):
    fig,axes=plt.subplots(1,2,figsize=(width,4.1),gridspec_kw={"width_ratios":ratios},layout="constrained")
    for ax,title in zip(axes,titles):
        panel(ax,title)
    return fig,axes

def connectivity():
    fig,(a,b)=pair(14,(1,1.45),("A   Left frontal target","B   Coupling in the selected region"))
    image_panel(a,S/"fig2/figure-2-vs-original-brain.png")
    image_panel(b,S/"fig2/figure-2-vs-components.png")
    return fig

def activation():
    fig,(a,b)=pair(11.6,(1.14,1),("A   Right posterior temporal target","B   ADI slopes by support"))
    image_panel(a,S/"fig3/figure-3-adi-support-brain.png")
    d=rows("fig3","activation_slopes.tsv")
    tails=rows("fig3","activation_tail_counts.tsv")
    x=np.linspace(min(arr(tails,"support_min")),max(arr(tails,"support_max")),201)
    for component,color,label in [("socialdoors",TEAL,"Social win"),("doors",RUST,"Nonsocial win"),
                                  ("difference",INK,"Social minus nonsocial")]:
        z=[r for r in d if r["component"]==component]
        m,y,lo,hi=(arr(z,k) for k in ("moderator","slope","hc3_lower","hc3_upper"))
        # A linear contrast has linear slope and quadratic variance in the moderator.
        # Three published anchors determine both curves exactly; these are not new fits.
        linear=np.polynomial.Polynomial.fit(m[[0,2]],y[[0,2]],1)
        var=np.polynomial.Polynomial.fit(m,((hi-lo)/2)**2,2)
        if not (np.allclose(linear(m),y) and np.allclose((hi+lo)/2,y) and np.all(var(x)>0)):
            raise ValueError("Cannot reconstruct pointwise intervals from sealed anchors")
        slope=linear(x); half=np.sqrt(var(x))
        band(b,x,slope,slope-half,slope+half,color,label)
    b.set(xlabel="Perceived support (corrected MSPSS)",ylabel="Mean COPE per ADI rank")
    b.axhline(0,lw=.8,color="#666"); b.legend(frameon=False,fontsize=9)
    return fig

def overlap():
    clusters=rows("fig4","vs_clusters.tsv")
    d=rows("fig4","vs_cluster_overlap.tsv")
    ids=[r["id"] for r in clusters]
    mat=np.full((len(ids),len(ids)),np.nan); np.fill_diagonal(mat,1)
    for r in d:
        i,j=ids.index(r["a"]),ids.index(r["b"])
        mat[i,j]=mat[j,i]=float(r["dice"])
    if len(ids)!=10 or len(d)!=45 or not np.isfinite(mat).all():
        raise ValueError("Incomplete overlap matrix")
    fig,ax=plt.subplots(figsize=(8.1,6),layout="constrained")
    im=ax.pcolormesh(np.arange(11)-.5,np.arange(11)-.5,mat,vmin=0,vmax=1,cmap="GnBu")
    ax.set_aspect("equal"); ax.invert_yaxis()
    fig.colorbar(im,ax=ax,shrink=.85,label="Dice overlap")
    names={"average":"Avg","loss_only":"Loss","social_specific":"DxV"}
    ticks=[f"{r['id']} · {names[r['outcome']]} {r['z']}" for r in clusters]
    ax.set_xticks(range(10),ticks,rotation=50,ha="right",fontsize=8)
    ax.set_yticks(range(10),ticks,fontsize=8)
    for (i,j),v in np.ndenumerate(mat):
        ax.text(j,i,f"{v:.2f}",ha="center",va="center",fontsize=7.5,color="white" if v>.65 else "#223")
    ax.set_title("ADI × ECog: overlap of corrected VS connectivity clusters",pad=12)
    return fig

def run(out):
    os.environ.setdefault("SOURCE_DATE_EPOCH","0")
    out.mkdir(parents=True,exist_ok=True)
    for name,build in [("Fig1_behavior",behavior),("Fig2_FEVS_VS_coupling",connectivity),
                       ("Fig3_ADI_support_activation",activation),("Fig4_ADI_ECog_VS_overlap",overlap)]:
        f=build()
        for fmt in ("svg","pdf"):
            f.savefig(out/f"{name}.{fmt}",dpi=240)
        plt.close(f)

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=KIT/"figures")
    run(parser.parse_args().output)
