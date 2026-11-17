#!/usr/bin/env python3
"""Assemble a compact follow-up from sealed aggregate evidence; never fit models."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
VERSION = "FEVS_Targeted_Results_Followup_v1"
PDF = ROOT/"output/pdf"/(VERSION+".pdf")
OLD = ROOT/"output/pdf/FEVS_Results_Ready_2026-11-07.pdf"
REVIEW = ROOT/"results/review"
SPEC = ROOT/"config/katie_targeted_followup_v1.json"
WIDTH = 728
LABELS = {"average":"Domain-average win-loss","loss_only":"Social - nonsocial loss","social_specific":"Social-by-valence"}
NAVY, TEAL = colors.HexColor("#122b40"), colors.HexColor("#126970")


def read(path):
    return json.loads(path.read_text())


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def verified(folder):
    manifest = read(folder/"review_manifest.json")
    if manifest["n"]!=97:
        raise ValueError("Frozen cohort differs")
    for name, digest in manifest["outputs"].items():
        if Path(name).name!=name or sha(folder/name)!=digest:
            raise ValueError("Aggregate seal differs: "+name)
    return manifest


def load_evidence():
    behavior=REVIEW/"katie-targeted-behavior-v1"
    native=REVIEW/"katie-targeted-native-v1"
    precedent=REVIEW/"katie-results-ready-v1"
    followup=REVIEW/"fevs-vs-fixed-roi-mspss-v1"
    auth=sha(SPEC)
    for folder,kind in ((behavior,"behavior"),(native,"native")):
        m=verified(folder)
        if (m["kind"]!=kind or m["new_permutation_jobs"]!=0 or m["spec_sha256"]!=auth
                or m["renderer_sha256"]!=sha(ROOT/"code/review_katie_targeted.py")):
            raise ValueError("Unrecognized targeted report lineage")
    verified(followup)
    old_manifest=read(precedent/"report-manifest.json")
    historic=[OLD,precedent/"figure-3-adi-support-brain.png"]
    for path in historic:
        if old_manifest["outputs"][str(path.relative_to(ROOT))]!=sha(path):
            raise ValueError("Historic evidence changed: "+path.name)
    b, n, fixed = read(behavior/"behavior.json"),read(native/"native.json"),read(followup/"summary.json")
    if b["n"]!=97 or n["n"]!=97 or n["new_permutation_jobs"]!=0 or n["exclusions_changed"]:
        raise ValueError("Cohort or computation scope changed")
    vs=n["vs"]
    scope={(out,z,sign) for out in LABELS for z in (2.6,3.1) for sign in ("positive","negative")}
    if (len(vs["maps"])!=12 or {(m["outcome"],m["z"],m["direction"]) for m in vs["maps"]}!=scope
            or sum(m["clusters"] for m in vs["maps"])!=len(vs["clusters"])
            or len(vs["map_overlap"])!=15
            or len(vs["cluster_overlap"])!=len(vs["clusters"])*(len(vs["clusters"])-1)//2
            or len(n["activation"]["group_overlap"])!=6 or n["activation"]["cluster"]["voxels"]!=87):
        raise ValueError("Incomplete targeted map or overlap inventory")
    figs=dict(behavior=behavior/"behavior.png",activation=native/"activation.png",
              activation_brain=historic[-1],overlap=native/"vs_overlap.png")
    return b,n,fixed,figs


def ci(row, names=("hc3_lower","hc3_upper"), places=2):
    return "["+", ".join(f"{row[k]:.{places}f}" for k in names)+"]"


def display(value, places=3):
    return f"{value:.{places}f}"


def activation_conclusion(rows):
    a,b,d = (next(r for r in rows if r["component"]==c)["beta"] for c in ("socialdoors","doors","difference"))
    if a*b<0:
        lead="Opposite signs contribute to the contrast interaction."
    else:
        lead="The component interactions have the same sign; their magnitudes differ."
    dominant = ("social winning" if abs(a)>abs(b) else "nonsocial winning") if abs(a)!=abs(b) else "neither task"
    return (f"{lead} The larger absolute point estimate is for {dominant}. "
            f"Social ({a:+.3f}) minus nonsocial ({b:+.3f}) reconstructs the contrast coefficient ({d:+.3f}). "
            "These are descriptive estimates from a region selected on that contrast.")


def pairing(vs,a,b):
    return [r for r in vs["map_overlap"] if {r["outcome_a"],r["outcome_b"]}=={a,b}]


def vs_conclusion(vs):
    pairs=pairing(vs,"loss_only","social_specific")
    matched=[r for r in pairs if r["z_a"]==r["z_b"]]
    intersection=", ".join(f"Z {r['z_a']}: {r['shared_voxels']} shared voxels (Dice {r['dice']:.3f})" for r in matched)
    if not any(r["shared_voxels"] for r in pairs):
        note="The losing and social-by-valence contrasts share no corrected voxels at either threshold pairing."
    elif not all(r["shared_voxels"] for r in matched):
        note="Spatial support from the losing contrast is threshold-dependent."
    else:
        note="There is some spatial support from losing at both matched thresholds; this does not establish that losing explains the interaction."
    within = [r for r in vs["map_overlap"] if r["outcome_a"]==r["outcome_b"]=="social_specific"][0]
    if within["shared_voxels"]==0:
        note += " The social-by-valence clusters at the two thresholds do not overlap each other."
    avg = [r for r in vs["map_overlap"] if (r["outcome_a"]=="average") != (r["outcome_b"]=="average")]
    max_shared = max(r["shared_voxels"] for r in avg)
    return (f"{intersection}. {note} The domain-average clusters share at most {max_shared} corrected voxels "
            "with either of the other contrasts across threshold pairs. "
            "Corrected overlap is not a test of equality, and opposite signs across losing and the double contrast can follow from subtraction.")


def make_pdf(out, b, n, fixed, figs):
    styles={
        "title":ParagraphStyle("title",fontName="Helvetica-Bold",fontSize=22,leading=25,textColor=NAVY,spaceAfter=10),
        "kicker":ParagraphStyle("kicker",fontName="Helvetica-Bold",fontSize=10,leading=13,textColor=TEAL,spaceAfter=5),
        "heading":ParagraphStyle("heading",fontName="Helvetica-Bold",fontSize=12,leading=15,textColor=NAVY,spaceBefore=6,spaceAfter=4),
        "body":ParagraphStyle("body",fontName="Helvetica",fontSize=10,leading=13.1,textColor=NAVY,spaceAfter=7),
        "cell":ParagraphStyle("cell",fontName="Helvetica",fontSize=8.3,leading=10.1,textColor=NAVY,alignment=TA_LEFT),
        "headcell":ParagraphStyle("headcell",fontName="Helvetica-Bold",fontSize=8.4,leading=10.1,textColor=colors.white),
    }
    story=[]
    def p(text,kind="body"):
        story.append(Paragraph(escape(text),styles[kind]))
    def header(kicker,title):
        p(kicker,"kicker"); p(title,"title")
    def grid(rows,widths):
        data=[[Paragraph(escape(str(v)),styles["headcell" if i==0 else "cell"]) for v in row]
              for i,row in enumerate(rows)]
        t=Table(data,colWidths=widths,hAlign="LEFT",repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),TEAL),("VALIGN",(0,0),(-1,-1),"TOP"),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.HexColor("#edf4f5"),colors.white]),
            ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4)]))
        story.append(t)
    def image(name,w,h):
        return Image(str(figs[name]),width=w,height=h,kind="proportional")
    def row_panels(*items):
        t=Table([list(items)],colWidths=[WIDTH/len(items)]*len(items),hAlign="CENTER")
        t.setStyle(TableStyle([("ALIGN",(0,0),(-1,-1),"CENTER"),("VALIGN",(0,0),(-1,-1),"MIDDLE")]))
        story.append(t)

    header("01 / ENVIRONMENTAL MODERATION", "Does the high-support reversal hold up?")
    lo,hi=b["tails"][0],b["tails"][-1]
    p(f"Corrected Island-screener support was at or below {lo['lower_support_cut']:.2f} for {lo['n']} people and "
      f"at or above {hi['upper_support_cut']:.2f} for {hi['n']}. The upper tail spans only "
      f"{hi['support_min']:.2f}-{hi['support_max']:.2f} MSPSS points. The quadratic specification was chosen before examining its results.")
    story.append(image("behavior",590,306))
    rows=[["Model","PM2.5 slope at low support (95% CI)","At median support","At high support","High-support leave-one-out range"]]
    for model in ("linear","quadratic_support"):
        a=[r for r in b["anchors"] if r["model"]==model]
        rows.append([model.replace("_"," ").capitalize(),*[f"{r['pm25_slope']:+.2f} {ci(r)}" for r in a],
                     f"{a[-1]['loo_min']:+.2f} to {a[-1]['loo_max']:+.2f}"])
    grid(rows,[106,156,147,147,172])
    linear=b["fits"][0]
    p(f"Linear interaction b={linear['beta']:+.3f}, primary-family Holm p={b['baseline_holm_p']:.6f}. "
      f"Maximum Cook's D={linear['max_cooks_d']:.3f}; {linear['n_cooks_above_4_over_n']} exceed 4/N; "
      f"leave-one-out interaction b={linear['loo_beta_min']:+.3f} to {linear['loo_beta_max']:+.3f}. "
      "The negative upper-tail estimate survives the functional-form check and each single omission, "
      "but its quadratic interval includes zero. Describe attenuation, not a reliably protective reversal.")

    story.append(PageBreak())
    header("02 / SOCIAL VERSUS NONSOCIAL WINNING", "What generates the ADI-by-support contrast?")
    a=n["activation"]
    p("One fixed 87-voxel interaction cluster near right posterior temporal cortex, Z-equivalent CDT 3.1, cluster-FWE p=.0255. "
      "Social and nonsocial winning COPEs are estimated separately with the exact original design and covariates.")
    row_panels(image("activation_brain",354,215),image("activation",354,215))
    p(activation_conclusion(a["fits"]))
    rows=[["Outcome","ADI × support b (HC3 95% CI)","Max Cook's D (n >4/N)","Leave-one-out b range"]]
    for row in a["fits"]:
        rows.append([{"socialdoors":"Social win","doors":"Nonsocial win","difference":"Social - nonsocial win"}[row["component"]],
            f"{row['beta']:+.3f} {ci(row,places=3)}",f"{row['max_cooks_d']:.3f} ({row['n_cooks_above_4_over_n']})",
            f"{row['loo_beta_min']:+.3f} to {row['loo_beta_max']:+.3f}"])
    grid(rows,[160,209,170,189])
    p("Overlap with group-average Social - nonsocial winning","heading")
    rows=[["CDT Z","Positive mean map","Negative mean map","Either direction"]]
    for z in (2.6,3.1):
        by_sign={r["direction"]:r for r in a["group_overlap"] if r["z"]==z}
        rows.append([z,*[f"{by_sign[s]['shared_voxels']}/87 voxels (Dice {by_sign[s]['dice']:.3f})" for s in ("positive","negative","either")]])
    grid(rows,[65,221,221,221])
    p(f"Support tails: n={a['support'][0]['n']} low and n={a['support'][-1]['n']} high. The component signs "
      "are unchanged under single-case omission. The group-mean and moderation maps test different hypotheses; "
      "spatial overlap and selected-region intervals do not provide independent confirmation.")

    story.append(PageBreak())
    header("03 / ADI × ECOG IN VS CONNECTIVITY", "Do the same locations recur?")
    vs=n["vs"]
    p(vs_conclusion(vs))
    story.append(image("overlap",490,265))
    rows=[["Contrast pairing","CDT Z (A / B)","Shared voxels (A / B sizes)","Dice"]]
    for r in vs["map_overlap"]:
        if r["outcome_a"]==r["outcome_b"] or {r["outcome_a"],r["outcome_b"]}=={"social_specific","loss_only"}:
            # Show within-contrast persistence as well as all loss/double-contrast pairs.
            rows.append([f"{LABELS[r['outcome_a']]} / {LABELS[r['outcome_b']]}",f"{r['z_a']} / {r['z_b']}",
                        f"{r['shared_voxels']} ({r['voxels_a']} / {r['voxels_b']})",f"{r['dice']:.3f}"])
    grid(rows,[344,98,171,115])
    recurrence={r["outcome_a"]:r for r in vs["map_overlap"] if r["outcome_a"]==r["outcome_b"]}
    p(f"The stricter domain-average map retains {recurrence['average']['shared_voxels']} of its corrected voxels "
      f"in the looser map; the stricter losing map retains {recurrence['loss_only']['shared_voxels']}. "
      "These are within-contrast recurrences, not replication across contrasts. See the aggregate tables "
      "for pairwise overlap fractions and peak distances.")

    story.append(PageBreak())
    header("04 / LOCATIONS AND REPORTING DECISIONS", "What should move into the paper?")
    rows=[["ID / contrast","CDT / sign","Peak MNI (mm); atlas peak","Voxels / p","Cook's D / LOO sign"]]
    for r in vs["clusters"]:
        locations="; ".join(a["peak_label"] for a in r["atlas"] if a["peak_label"]!="Unlabeled")
        loc=f"({', '.join(f'{v:.1f}' for v in r['peak'])}) {locations or 'atlas unlabeled'}"
        sign="+" if r["loo_beta_min"]>0 else "-" if r["loo_beta_max"]<0 else "crosses 0"
        rows.append([f"{r['id']} {LABELS[r['outcome']]}",f'{r["z"]} / {r["direction"]}',
                     loc,f'{r["voxels"]} / {r["p"]:.4f}',f'{r["max_cooks_d"]:.3f} / {sign}'])
    grid(rows,[159,86,272,91,120])
    max_cook=max(r["max_cooks_d"] for r in vs["clusters"])
    fixed_signs=sum(r["loo_beta_min"]>0 or r["loo_beta_max"]<0 for r in vs["clusters"])
    p(f"Leave-one-out sign held in {fixed_signs}/{len(vs['clusters'])} selected clusters, but Cook's D reached "
      f"{max_cook:.2f}; influence is not negligible. This does not retest the whole-brain maps. See the cluster table for HC3 intervals "
      "and leave-one-out ranges, and the map table for null signs/CDTs. Atlas labels are approximate.")
    p("Main text","heading")
    p("Lead with the behavioral PM2.5-by-support association, framed as attenuation. Report the original FEVS-VS result "
      "with its support-adjusted whole-brain null at CDT 3.1 (p=.0751). The later fixed frontal-region estimate "
      f"retained its sign and was only {fixed['comparison']['magnitude_reduction_percent']:.1f}% smaller; "
      "that selected-region check does not rescue the whole-brain inference. Treat ADI-by-support activation as an "
      "exploratory contrast-specific result, not evidence of protective buffering.")
    p("Supplement","heading")
    p("Keep the nonlinear bands and influence diagnostics, the full fixed activation component decomposition, "
      "and the ADI-by-ECog cluster and overlap inventory here. Report locations individually; do not describe one stable network.")
    p("Audit and limits","heading")
    p("Original designs, images, masks, permutations and exclusions frozen; N=97. Only one behavioral sensitivity and "
      "same-sample regional descriptive fits were added. Reconstructed activation component differences, matched signed native "
      "maps to the November 7 catalog, and verified input/output hashes. Cluster-FWE is per map, not across this exploratory "
      "family. No causal inference; financial instrument scoring remains provisional. No manuscript Results text is drafted.")

    def footer(canvas, doc):
        canvas.setFont("Helvetica",8); canvas.setFillColor(NAVY)
        canvas.drawString(32,20,"Katie / Social Doors     |     Targeted evidence follow-up v1     |     Frozen N=97")
        canvas.drawRightString(760,20,f"{doc.page}")

    doc=SimpleDocTemplate(str(out),pagesize=(792,612),leftMargin=32,rightMargin=32,topMargin=29,bottomMargin=35,
                          title="Katie Social Doors | Targeted Results Follow-up v1",author="DVS Lab",invariant=1)
    doc.build(story,onFirstPage=footer,onLaterPages=footer)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=PDF)
    args=parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Existing PDF preserved; use another output path")
    b,n,fixed,figs=load_evidence()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    make_pdf(args.output,b,n,fixed,figs)
    provenance=dict(n=97,new_permutation_jobs=0,exclusions_changed=False, pdf_sha256=sha(args.output),
                    spec_sha256=sha(SPEC),builder_sha256=sha(Path(__file__)),historical_pdf_sha256=sha(OLD),
                    source_manifests={name:sha(REVIEW/name/"review_manifest.json") for name in
                        ("katie-targeted-behavior-v1","katie-targeted-native-v1","fevs-vs-fixed-roi-mspss-v1")})
    args.output.with_suffix(".manifest.json").write_text(json.dumps(provenance,indent=2)+"\n")
    print(f"BUILT: {args.output}; render and inspect all pages before sharing.")


if __name__=="__main__":
    main()
