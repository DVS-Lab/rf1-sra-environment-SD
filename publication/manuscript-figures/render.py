"""Draw the manuscript panels from the plotted values and brain plates beside each figure."""
import argparse
import csv
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
TEAL, BLUE, RUST = "#176873", "#234A70", "#AC542F"
INK, GRAY, GRID = "#202832", "#64707B", "#E5E9EC"
IDS = ("Figure-1", "Figure-2", "Figure-3", "supplement/Figure-S1", "supplement/Figure-S3")

def style():
    plt.rcParams.update({"font.family":"DejaVu Sans", "font.size":10, "axes.labelsize":10,
        "axes.edgecolor":GRAY, "axes.labelcolor":INK, "xtick.color":INK, "ytick.color":INK,
        "text.color":INK, "axes.spines.top":False, "axes.spines.right":False,
        "xtick.major.size":3, "ytick.major.size":3, "figure.facecolor":"white",
        "savefig.facecolor":"white", "svg.fonttype":"none", "svg.hashsalt":"rodman-figures",
        "pdf.fonttype":42})

def read(folder):
    with (folder/"plotted-values.tsv").open(newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def slope(ax, rows, term, color, label=None, linestyle="-"):
    x,y,lo,hi=np.array([[float(r[k]) for k in ("support",term,"hc3_lower","hc3_upper")] for r in rows]).T
    if len(x)!=201 or not np.all(np.diff(x)>0) or not np.all((lo<=y)&(y<=hi)):
        raise ValueError("Unexpected plotted curve")
    ax.fill_between(x,lo,hi,facecolor=color,alpha=.15,linewidth=0)
    ax.plot(x,y,color=color,linewidth=2.1,linestyle=linestyle,label=label)

def support_axes(ax,ylabel):
    ax.axhline(0,color=GRAY,lw=.85,zorder=2)
    ax.yaxis.grid(color=GRID,linewidth=.65)
    ax.set_axisbelow(True)
    ax.set(xlim=(1,7),xticks=np.arange(1,8),xlabel="Perceived social support (MSPSS score)",ylabel=ylabel)
    ax.tick_params(axis="both",length=3)
    ax.margins(y=.08)

def label(fig,y,letter,title):
    fig.text(.031,y,letter,fontsize=13,weight="bold",va="bottom")
    fig.text(.085,y,title,fontsize=11,weight="semibold",va="bottom")

def brain(fig, folder, title):
    ax=fig.add_axes((.07,.65,.88,.273))
    with Image.open(folder/"brain-slices.png") as plate:
        ax.imshow(plate,aspect="equal")
    ax.axis("off")
    label(fig,.937,"A",title)

def behavior(folder):
    fig,ax=plt.subplots(figsize=(6.5,3.32),layout="constrained")
    fig.get_layout_engine().set(w_pad=.15,h_pad=.12)
    rows=read(folder)
    if {r["model"] for r in rows}!={"linear"}:
        raise ValueError("Only the primary linear curve belongs in Figure 1")
    slope(ax,rows,"pm25_slope",TEAL)
    support_axes(ax,"Estimated PM₂.₅–vulnerability slope\n(FEVS points per µg/m³ PM₂.₅)")
    ax.set_yticks(np.arange(-2,9,2))
    return fig

def activation(folder):
    fig=plt.figure(figsize=(6.5,6.2))
    brain(fig,folder,"Right temporoparietal region")
    ax=fig.add_axes((.15,.12,.79,.44))
    rows=read(folder)
    if {r["component"] for r in rows}!={"difference"}:
        raise ValueError("Figure 2 must contain only the between-task winning contrast")
    slope(ax,rows,"slope",BLUE)
    support_axes(ax,"Deprivation–activation slope\n(COPE units per ADI rank)")
    label(fig,.588,"B","Social wins minus monetary wins")
    ax.set_yticks(np.arange(-6,5,2))
    return fig

def connectivity(folder):
    fig=plt.figure(figsize=(6.5,6.35))
    brain(fig,folder,"Target near the left frontal pole")
    label(fig,.587,"B","Social minus monetary win–loss coupling")
    ax=fig.add_axes((.15,.107,.72,.455))
    with Image.open(folder/"adjusted-scatter.png") as plate:
        ax.imshow(plate,interpolation="none")
    ax.axis("off")
    fig.text(.146,.335,"Adjusted coupling difference (COPE units)",rotation=90,
             ha="center",va="center")
    fig.text(.526,.077,"Financial exploitation vulnerability (FEVS score)",ha="center")
    fig.text(.526,.030,"N = 97. Line at mean PM₂.₅; shading: pointwise 95% OLS CI for the fitted mean.",
             ha="center",color=GRAY,fontsize=8)
    return fig

def supplemental_components(folder):
    fig,ax=plt.subplots(figsize=(6.5,3.65),layout="constrained")
    fig.get_layout_engine().set(w_pad=.16,h_pad=.14)
    data=read(folder)
    for k,c,title,ls in [("socialdoors",TEAL,"Social wins","-"),("doors",RUST,"Monetary wins","--")]:
        slope(ax,[r for r in data if r["component"]==k],"slope",c,title,ls)
    support_axes(ax,"Deprivation–activation slope\n(COPE units per ADI rank)")
    ax.legend(loc="upper right",frameon=False,fontsize=9,borderaxespad=.6)
    return fig

def supplemental_diagnostics(folder):
    # This supplement used an already-composed raster plate in the authors' DOCX.
    path=folder/"Figure-S1.png"
    with Image.open(path) as image:
        if image.size!=(2080,1308):
            raise ValueError("Unexpected supplemental diagnostic plate")
        data=np.asarray(image.convert("RGB"))
    fig=plt.figure(figsize=(6.5,1308/320))
    ax=fig.add_axes((0,0,1,1))
    ax.imshow(data,interpolation="none"); ax.axis("off")
    return fig

def run(output, only=None):
    os.environ.setdefault("SOURCE_DATE_EPOCH","0")
    style()
    for name,build in zip(IDS,(behavior,activation,connectivity,supplemental_diagnostics,supplemental_components)):
        if only is not None and name!=only:
            continue
        src=ROOT/name
        target=output/name
        target.mkdir(parents=True,exist_ok=True)
        fig=build(src)
        stem=Path(name).name
        for fmt in ("png","svg","pdf"):
            if fmt=="png" and build==supplemental_diagnostics:
                if src.resolve()!=target.resolve():
                    (target/(stem+".png")).write_bytes((src/(stem+".png")).read_bytes())
                continue
            path=target/(stem+"."+fmt)
            fig.savefig(path,dpi=400)
            if fmt=="svg":
                path.write_text("".join(line.rstrip()+"\n" for line in path.read_text().splitlines()))
        plt.close(fig)

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=ROOT)
    parser.add_argument("--figure",choices=IDS,help="Render only the named figure")
    args=parser.parse_args()
    run(args.output,args.figure)
