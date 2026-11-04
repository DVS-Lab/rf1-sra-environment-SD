#!/usr/bin/env python3
"""Build a preliminary PDF from sealed results; needs ReportLab, Pillow and Matplotlib.

Use --chart-only and --reuse-figure when scientific/PDF libraries are in separate environments.
No model is fitted by this reporting utility.
"""

import argparse
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path):
    with path.open() as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def verify_sources():
    review = ROOT / "results/review"
    for folder in ("behavioral-moderation-provisional-v1", "fevs-win-v1", "fevs-vs-v1"):
        root = review / folder
        manifest = json.loads((root / "review_manifest.json").read_text())
        assert manifest["n"] == 97 and not manifest["exclusions_changed"]
        for name, expected in manifest["outputs"].items():
            assert digest(root / name) == expected, f"Published source changed: {folder}/{name}"
    behavioral = rows(review / "behavioral-moderation-provisional-v1/interactions.tsv")
    target = next(r for r in behavioral if r["model"] == "fevs_pm25_mspss")
    assert len(behavioral) == 8 and float(target["hc3_p"]) < .001
    assert abs(float(target["interaction_beta"]) - (-.802238003563228)) < 1e-10
    final = rows(review / "final-summary-v1/corrected_maps.tsv")
    assert len(final) == 69
    assert not any(r["term"] in ("pm25xmspss", "fevsxmspss") for r in final)
    assert not any(r["family"] == "activation" and r["outcome"] == "social_specific" for r in final)
    assert not any(r["family"] == "connectivity" and r["outcome"] == "win_only" and r["term"].startswith("fevs") for r in final)
    return target


def behavioral_figure(path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    data = [r for r in rows(ROOT / "results/review/behavioral-moderation-provisional-v1/conditional_slopes.tsv")
            if r["model"] == "fevs_pm25_mspss"]
    x = [float(r["moderator_value"]) for r in data]
    y = [float(r["conditional_exposure_slope"]) for r in data]
    fig, axis = plt.subplots(figsize=(7.2, 3.2))
    axis.axvspan(0, 1, color="#EDEFF0", zorder=0)
    axis.fill_between(x, [float(r["ci_lower"]) for r in data], [float(r["ci_upper"]) for r in data],
                      color="#117A83", alpha=.17, label="HC3 pointwise 95% interval")
    axis.plot(x, y, color="#126A70", lw=2.2, label="Estimated PM2.5-FEVS slope")
    axis.axhline(0, color="#3A444A", lw=.8)
    axis.axvline(1, color="#899297", lw=.8, ls="--")
    axis.set(xlim=(0, 7), xlabel="Perceived social support (exported MSPSS mean)",
             ylabel="FEVS points per unit PM2.5")
    axis.spines[["top", "right"]].set_visible(False)
    axis.legend(loc="upper right", frameon=False, fontsize=8)
    axis.text(.5, .03, "Coding\ncheck", transform=axis.get_xaxis_transform(), ha="center", color="#68747A", fontsize=8)
    fig.tight_layout(pad=1.1)
    fig.savefig(path, dpi=200)
    plt.close(fig)


def build(output, temporary, as_of, reuse_figure=False):
    from PIL import Image as PILImage
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, PageBreak, Table, TableStyle

    TEAL = colors.HexColor("#126A70")
    INK = colors.HexColor("#182329")
    MUTED = colors.HexColor("#4B5960")
    target = verify_sources()
    temporary.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    curve = temporary / "behavioral-pm25-support.png"
    if not reuse_figure:
        behavioral_figure(curve)
    elif not curve.is_file():
        raise ValueError("Create the scientific figure with --chart-only first")
    width = 510
    styles = {
        "title": ParagraphStyle("Title", fontName="Helvetica-Bold", fontSize=22, leading=26, textColor=INK, spaceAfter=9),
        "h1": ParagraphStyle("Section", fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=INK, spaceAfter=7),
        "h2": ParagraphStyle("Subsection", fontName="Helvetica-Bold", fontSize=11.5, leading=15, textColor=TEAL, spaceBefore=8, spaceAfter=4),
        "body": ParagraphStyle("Body", fontName="Helvetica", fontSize=10.2, leading=14, textColor=INK, spaceAfter=7),
        "small": ParagraphStyle("Small", fontName="Helvetica", fontSize=8.5, leading=11.5, textColor=MUTED, spaceAfter=5),
        "caption": ParagraphStyle("Caption", fontName="Helvetica", fontSize=9, leading=12, textColor=MUTED, spaceAfter=8),
        "banner": ParagraphStyle("Banner", fontName="Helvetica-Bold", fontSize=9.3, leading=12, textColor=TEAL, spaceAfter=9),
    }
    story = []
    def text(value, style="body"):
        story.append(Paragraph(value, styles[style]))
    def figure(path, max_height=None):
        with PILImage.open(path) as image:
            w, h = image.size
        factor = min(width / w, (max_height or 1000) / h)
        story.append(Image(str(path), width=w * factor, height=h * factor))
        story.append(Spacer(1, 6))
    def link(label, path):
        return f'<link href="https://github.com/DVS-Lab/rf1-sra-environment-SD/blob/main/{path}" color="#126A70">{label}</link>'

    text("Financial vulnerability and<br/>social reward", "title")
    text(f"RF1-SRA / Katie Social Doors | Main results brief | {as_of}", "small")
    text("PRELIMINARY: financial-score verification and MSPSS coding checks remain open. N=97 and settled exclusions are unchanged.", "banner")
    text("1. Support Moderates The PM2.5-FEVS Association", "h2")
    text(f"Interaction b = <b>{float(target['interaction_beta']):.3f}</b>; HC3 95% CI "
         f"<b>[{float(target['ci_lower']):.3f}, {float(target['ci_upper']):.3f}]</b>; "
         "two-sided p = <b>0.000168</b>; Holm p = <b>0.000336</b> across the two primary behavioral tests.")
    figure(curve, 225)
    text("The plotted quantity is the estimated PM2.5-FEVS slope, not the FEVS score itself. "
         "The association is more positive at lower support and weakens as support increases. "
         "Bands are pointwise, not simultaneous. The shaded 0-1 region flags values below the standard MSPSS mean-score range.", "caption")
    text("Model And Influence", "h2")
    text("FEVS ~ PM2.5 + MSPSS + PM2.5 x MSPSS + age + gender. N=97; residual df=91. "
         "Every single-case omission retains a negative interaction (b=-0.939 to -0.724); maximum Cook's D=0.135. "
         "This does not rule out sensitivity to multiple questionable scores together.")
    text("Scoring check: five exported MSPSS values are below 1, including one zero. They were retained as supplied, "
         "not declared missing or imputed. Verify the administered coding and recompute scores from original items. "
         "FEVS/OAFEM versions, item coding, timepoints and missing-item rules also require confirmation.", "small")
    text("Eight behavioral models were reported: two primary FEVS/support interactions and six secondary tests. "
         "None of the other seven interactions survives its within-family Holm adjustment. " +
         link("Behavioral results and complete tables", "results/review/behavioral-moderation-provisional-v1/README.md"), "small")

    story.append(PageBreak())
    text("2. FEVS And Social-Specific Winning", "h1")
    text("ACTIVATION | Social Doors win - nonsocial Doors win", "banner")
    text("Higher FEVS is associated with a larger social-minus-nonsocial winning activation difference in a small "
         "left anterior/ventral frontal region near OFC. This contrast isolates the difference between domains during wins; "
         "it is not the domain difference in win-minus-loss responding.")
    table_data = [["FEVS coefficient", "Voxels", "Cluster-FWE p", "Peak MNI (mm)"],
                  ["Separate FEVS predictor", "56", "0.0411", "-31.6, 49.5, -6.7"],
                  ["At mean PM2.5", "67", "0.0315", "-31.6, 49.5, -3.7"]]
    grid = Table(table_data, colWidths=[190, 52, 95, 173])
    grid.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                             ("FONTNAME", (0, 1), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), 9),
                             ("TEXTCOLOR", (0, 0), (-1, -1), INK), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDF4F4")),
                             ("LINEBELOW", (0, 0), (-1, 0), .5, TEAL), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                             ("TOPPADDING", (0, 0), (-1, -1), 7)]))
    story.extend([grid, Spacer(1, 9)])
    review = ROOT / "results/review"
    figure(review / "fevs-win-v1/fevsxpm25-brain.png", 220)
    text("Displayed: positive FEVS coefficient at mean PM2.5, CDT Z-equivalent 3.1. "
         "The model includes FEVS, PM2.5 and their interaction, plus age, gender, scanner era and signed FD/tSNR differences. "
         "This is a conditional main effect, <b>not</b> a significant winning-related FEVS x PM2.5 interaction.", "caption")
    figure(review / "fevs-win-v1/fevsxpm25-cluster-1-scatter.png", 162)
    text("The two related models overlap by 48 voxels (Dice=0.78); they are not independent replications. "
         "No single-case omission reverses either descriptive FEVS slope. Selected-cluster scatterplots and their "
         "analytical intervals are descriptive, not independent confirmation of the whole-brain test.", "small")
    text("Anatomical caution: substantial portions of the clusters are white-matter-labeled in the atlas. "
         "Report coordinates and cautious frontal localization; do not call this an established cortical vmPFC or VS activation effect. " +
         link("FEVS activation report", "results/review/fevs-win-v1/README.md"), "small")

    story.append(PageBreak())
    text("3. FEVS And VS Connectivity", "h1")
    text("VS PPI | [Social win - social loss] - [nonsocial win - nonsocial loss]", "banner")
    text("At mean PM2.5, higher FEVS is associated with a smaller social-by-valence difference in task-modulated VS coupling "
         "with a left frontal-pole target: <b>cluster-FWE p=0.0303</b>, 44 voxels; peak MNI <b>[-20.8, 57.6, 11.2]</b>. "
         "The frontal cluster is the coupling target, not the VS seed.")
    figure(review / "fevs-vs-v1/fevs-vs-cluster-1-brain.png", 210)
    text("Displayed: negative FEVS coefficient at mean PM2.5, CDT Z-equivalent 3.1. "
         "This is not a FEVS x PM2.5 interaction, not winning-specific coupling and not a statement about globally weaker connectivity.", "caption")
    figure(review / "fevs-vs-v1/fevs-vs-cluster-1-scatter.png", 151)
    text("The descriptive slope remains negative under every single-case omission (-0.114 to -0.098). "
         "Selected-cluster plots are not independent confirmation. Most cluster voxels are cortex-labeled, but the peak is white-matter-labeled.", "small")
    text(link("Full VS connectivity report", "results/review/fevs-vs-v1/README.md"), "small")

    story.append(PageBreak())
    text("Interpretation And Next Steps", "h1")
    text("FEVS-FIRST SYNTHESIS | Contextual and neural correlates, not a causal pathway", "banner")
    text("Financial exploitation vulnerability (FEVS) has both contextual and neural correlates in this older-adult sample. "
         "The PM2.5-FEVS association varies with perceived support; separate analyses associate FEVS with social-winning "
         "activation and socially differentiated VS coupling. These findings do not establish a connecting causal pathway.")
    text("What The Combined Results Do Not Show", "h2")
    text("There is no matching corrected neural PM2.5 x support interaction, and no corrected FEVS x support interaction. "
         "The completed catalog also has no FEVS social-winning VS-connectivity finding and no social-by-valence activation finding. "
         "The behavioral and neural results are complementary FEVS associations, not a demonstrated buffering mechanism or mediation pathway.")
    text("Analysis Scope", "h2")
    text("N=97, paired ses-01, approved age-55+ imaging cohort. Neural inputs are the completed no-TEDANA sm-5 FEAT variant "
         "and original VS seed. Neural inference uses 10,000 permutations and cluster extent at Z-equivalent CDTs 2.6/3.1; "
         "highlighted FEVS clusters pass at 3.1. Cluster-FWE is per map, not across the exploratory model/outcome/CDT family. "
         "No three-way interaction or new exclusion is introduced in this brief.", "small")
    text("This focused summary presents selected main findings, not the full analysis inventory. "
         "Other tested models, nulls and secondary findings remain documented. " +
         link("VS report", "results/review/fevs-vs-v1/README.md") + " | " +
         link("Full results and model inventory", "results/review/final-summary-v1/README.md"), "small")
    text("Scoring Closeout Before Final Interpretation", "h2")
    text("Verify the administered MSPSS response coding and calculation for all 97 participants, including the five exported values below 1. "
         "The standard mean-score range is 1-7; a documented modified version could differ. Low values do not by themselves prove questionnaires are missing. "
         "Obtain the original FEVS/OAFEM item coding, instrument versions, source timepoints and missing-item rules, and recompute totals against the export.")
    text("Preserve all 97 participants, original exports and completed neural results. Save any corrections as a versioned export and assess their implications "
         "before changing analyses. Do not replace zeros, impute items or exclude participants simply to resolve the coding question.")
    text("Status", "h2")
    text("Computation and output validation are complete. Financial-score and MSPSS coding checks remain open before final interpretation. "
         "No participant selection, score correction or new inferential analysis was performed to create this brief.")
    text('<link href="https://www.bristol.ac.uk/media-library/sites/sps/documents/c-change/mspss.pdf" color="#126A70">'
         'MSPSS instrument and standard scoring instructions</link>', "small")

    def page(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(TEAL)
        canvas.setLineWidth(1.2)
        canvas.line(51, 756, 561, 756)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(51, 29, "PRELIMINARY | Scoring verification pending | Frozen N=97")
        canvas.drawRightString(561, 29, f"{doc.page} / 4")
        canvas.restoreState()

    document = SimpleDocTemplate(str(output), pagesize=(612, 792), rightMargin=51, leftMargin=51,
                                 topMargin=47, bottomMargin=45, title="FEVS: Main Behavioral And Neural Results",
                                 author="RF1-SRA research team", subject="Preliminary exploratory results; scoring verification pending")
    document.build(story, onFirstPage=page, onLaterPages=page)
    print(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "output/pdf/FEVS_Main_Results_2026-11-03.pdf")
    parser.add_argument("--temporary", type=Path, default=ROOT / "work/pdf-main-results")
    parser.add_argument("--as-of", default="November 3, 2026")
    parser.add_argument("--chart-only", action="store_true")
    parser.add_argument("--reuse-figure", action="store_true")
    args = parser.parse_args()
    if args.chart_only:
        verify_sources()
        behavioral_figure(args.temporary / "behavioral-pm25-support.png")
    else:
        build(args.output, args.temporary, args.as_of, args.reuse_figure)
