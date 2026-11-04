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
    for folder in ("behavioral-moderation-provisional-v1", "fevs-win-v1", "fevs-vs-v1",
                   "fevs-imaging-adjustments-provisional-v1", "fevs-adjustment-maps-v1"):
        root = review / folder
        manifest = json.loads((root / "review_manifest.json").read_text())
        assert manifest["n"] == 97 and not manifest.get("exclusions_changed", False)
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
    adjusted = review / "fevs-behavioral-adjustments-provisional-v1"
    provenance = json.loads((adjusted / "provenance.json").read_text())
    assert provenance["provisional"] and not provenance["exclusions_changed"]
    for name, expected in provenance["outputs"].items():
        assert digest(adjusted / name) == expected, "Behavioral adjustment report changed"
    checks = rows(adjusted / "adjustments.tsv")
    assert [r["adjustment"] for r in checks] == ["baseline", "adi", "ecog", "adi+ecog"]
    assert all(int(r["n"]) == 97 for r in checks)
    maps = rows(review / "fevs-imaging-adjustments-provisional-v1/maps.tsv")
    locations = json.loads((review / "fevs-adjustment-maps-v1/locations.json").read_text())
    assert len(maps) == 48 and len(locations["locations"]) == 12
    assert locations["provisional_scoring"] and not locations["new_inference"] and not locations["exclusions_changed"]
    correlations = ROOT / "data/derived/financial-model-review-v1"
    expected = json.loads((correlations / "provenance.json").read_text())["outputs"]["correlations.tsv"]
    assert digest(correlations / "correlations.tsv") == expected, "Published descriptive correlations changed"
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

    def table(data, widths):
        cells = [[Paragraph(str(value), styles["small"]) for value in row] for row in data]
        grid = Table(cells, colWidths=widths, hAlign="LEFT")
        grid.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDF4F4")),
                                 ("LINEBELOW", (0, 0), (-1, 0), .5, TEAL),
                                 ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                                 ("TOPPADDING", (0, 0), (-1, -1), 3)]))
        story.extend([grid, Spacer(1, 6)])

    review = ROOT / "results/review"
    adjustments = rows(review / "fevs-behavioral-adjustments-provisional-v1/adjustments.tsv")

    text("Financial vulnerability and<br/>social reward", "title")
    text(f"RF1-SRA / Katie Social Doors | Adjusted results brief | {as_of}", "small")
    text("PRELIMINARY: financial-score verification and MSPSS coding checks remain open. N=97 and settled exclusions are unchanged.", "banner")
    text("Working synthesis: environmental context and perceived support are associated jointly with financial vulnerability; "
         "separate neural analyses relate FEVS to socially differentiated reward responses. "
         "This is an exploratory set of contextual and neural correlates, <b>not a demonstrated causal or mediating pathway</b>.")
    text("1. Support Moderates The PM2.5-FEVS Association", "h2")
    text(f"Interaction b = <b>{float(target['interaction_beta']):.3f}</b>; HC3 95% CI "
         f"<b>[{float(target['ci_lower']):.3f}, {float(target['ci_upper']):.3f}]</b>; "
         "two-sided p = <b>0.000168</b>; Holm p = <b>0.000336</b> across the two primary behavioral tests.")
    figure(curve, 165)
    text("The plotted quantity is the estimated PM2.5-FEVS slope, not the FEVS score itself. "
         "The association is more positive at lower support and weakens as support increases. "
         "Bands are pointwise, not simultaneous. The shaded 0-1 region flags values below the standard MSPSS mean-score range.", "caption")
    text("Matched ADI/Ecog Adjustment Checks", "h2")
    data = [["Added covariates", "Interaction b", "HC3 95% CI", "HC3 p"]]
    for r in adjustments:
        data.append([r["adjustment"], f"{float(r['interaction_beta']):.3f}",
                     f"[{float(r['ci_lower']):.3f}, {float(r['ci_upper']):.3f}]", f"{float(r['hc3_p']):.6f}"])
    table(data, [145, 85, 170, 110])
    text("All fits retain N=97 and PM2.5 + MSPSS + their interaction + age + gender. Added covariates are additive, "
         "not new interactions. Sensitivity p values above are unadjusted across these related checks. "
         "Every single-case omission retains a negative interaction in the baseline and all adjusted fits. "
         "This does not resolve sensitivity to multiple questionable scores together.", "small")
    text("Scoring remains provisional: five exported MSPSS values fall below the standard 1-7 mean range, including one zero. "
         "They remain as supplied; no imputation or exclusions. FEVS/OAFEM instrument versions, items and timepoints also need sign-off. "
         "None of the other seven behavioral interactions survives its within-family Holm correction.", "small")
    text(link("Behavioral model family", "results/review/behavioral-moderation-provisional-v1/README.md") + " | " +
         link("All matched behavioral adjustments", "results/review/fevs-behavioral-adjustments-provisional-v1/README.md"), "small")

    story.append(PageBreak())
    text("2. Activation: Stable Location, Qualified Evidence", "h1")
    text("ACTIVATION | Social Doors win - nonsocial Doors win", "banner")
    figure(review / "fevs-adjustment-maps-v1/activation_fevs_pm25.png", 490)
    text("FEVS coefficient at mean PM2.5 in the FEVS + PM2.5 + FEVS x PM2.5 model. Original, +ADI, +Ecog, +both; "
         "same slices/color scale. Cyan: original corrected cluster; gold: adjusted corrected cluster. "
         "Background |t|&gt;=2 shading is descriptive, <b>not</b> corrected significance.", "caption")
    text("ADI alone leaves the location nearly identical (Dice=.977). Adding both retains 53 voxels, 43 overlapping the original 67; "
         "centroid shift=1.1 mm. The 14.8-mm peak shift stays inside the original cluster. "
         "Ecog alone narrowly misses cluster correction (p=.0505); both p=.0477.", "small")
    text("<b>Activation caveat:</b> standalone FEVS activation also fails correction with Ecog (p=.0666) or both (p=.0709). "
         "The adjusted cluster is approximately 64% white-matter-labeled in a standard atlas, not native tissue segmentation. "
         "Describe left ventral/anterior frontal localization, <b>not clean cortical vmPFC/OFC activation</b>. "
         "This is not a winning-related FEVS x PM2.5 interaction.", "small")
    text(link("All activation and connectivity adjustments, including nulls", "results/review/fevs-imaging-adjustments-provisional-v1/README.md"), "small")

    story.append(PageBreak())
    text("3. VS Connectivity: More Consistent Across Adjustments", "h1")
    text("VS PPI | [Social win - social loss] - [nonsocial win - nonsocial loss]", "banner")
    figure(review / "fevs-adjustment-maps-v1/vs_fevs_pm25.png", 510)
    text("Negative FEVS coefficient at mean PM2.5, not the FEVS x PM2.5 interaction. Rows and contour meanings match page 2. "
         "Higher FEVS relates to a lower social-by-valence VS-connectivity contrast, not globally weaker connectivity or winning-specific coupling.", "caption")
    text("Baseline p=.0303; +ADI p=.0320; +Ecog p=.0349; +both p=.0353. All 43 ADI-adjusted voxels lie in the original "
         "44-voxel cluster. Ecog/both retain 42 voxels, with 32 overlapping the original (Dice=.744). "
         "Centroid shift=1.3 mm with both. Every adjusted peak remains inside the original cluster despite an approximately 15-mm peak shift.", "small")
    text("The adjusted target remains predominantly left frontal-pole cortex (approximately 81% cortex-labeled; adjusted peak "
         "[-20.8, 54.9, 26.0] mm). This frontal target is <b>not the VS seed</b>. "
         "Both neural findings pass only at CDT 3.1, not 2.6; per-map correction is not correction across the exploratory family. " +
         link("Verified maps, locations and overlap", "results/review/fevs-adjustment-maps-v1/README.md"), "small")

    story.append(PageBreak())
    text("A Coherent, Provisional FEVS-Centered Story", "h1")
    text("CONTEXT + FINANCIAL VULNERABILITY + SOCIAL REWARD | Complementary associations, not mediation", "banner")
    text("The strongest working synthesis is that the PM2.5-FEVS association varies with perceived social support, while FEVS "
         "also relates to socially differentiated neural responses. The connectivity association is more consistent across "
         "ADI/Ecog adjustment than activation. These are linked by the same financial phenotype, <b>not a demonstrated biological pathway</b>.")
    table([
        ["Variable", "Role in this brief", "Descriptive r with FEVS"],
        ["FEVS", "Lead financial measure: behavioral outcome; neural predictor. Scoring provisional.", "--"],
        ["PM2.5", "Environmental exposure in the behavioral support interaction; retained in conditional neural fits.", ".11"],
        ["MSPSS", "Behavioral moderator. No matching corrected neural support interaction.", "-.32"],
        ["ADI", "Environmental context and additive sensitivity covariate; not a second headline association here.", ".09"],
        ["Ecog", "Everyday-cognition measure; adjustment tests shared variation, not proof of longitudinal decline.", ".39"],
        ["OAFEM", "Secondary financial measure; no equivalent behavioral moderation result survives family correction.", ".33"],
    ], [62, 348, 100])
    text("Correlations are unadjusted Pearson descriptions of the same provisional exports, not model selection or independent evidence. "
         "The weak marginal PM2.5/ADI correlations do not invalidate a conditional association. Shared Ecog/FEVS variation does not prove confounding.", "small")
    text("Keep The Neural Outcomes Distinct", "h2")
    text("<b>Social winning:</b> social win - nonsocial win (activation finding). "
         "<b>Domain-by-valence:</b> [social win-loss] - [nonsocial win-loss] (VS-connectivity finding). "
         "These are not interchangeable evidence for one replicated social-reward effect. There is <b>no matching corrected neural "
         "PM2.5 x support interaction</b>, no FEVS social-winning VS-connectivity finding, and no domain-by-valence activation finding.", "small")
    text("Scope And Reporting Boundaries", "h2")
    text("Exploratory, not preregistered. Frozen N=97, paired ses-01, age 55+; completed no-TEDANA sm-5 FEAT inputs and original VS seed. "
         "Neural models retain age, gender, scanner era and signed FD/tSNR differences. Age is a covariate, not a lifespan or longitudinal effect here. "
         "Cluster-extent randomise: 10,000 permutations; Z-equivalent CDTs 2.6/3.1; cluster-FWE per map only. "
         "Sensitivity checks are related models, not independent replications. No new three-way interactions, exclusions or inferential fits were added for this brief.", "small")
    text("Closeout Before Final Interpretation", "h2")
    text("Verify MSPSS item coding and all 97 scores, including the five values below 1; confirm FEVS/OAFEM versions, coding, timepoints and missing-item rules. "
         "Do not replace zeros, impute or exclude people to resolve coding. Preserve original exports and all 97 participants; "
         "version any verified corrections before assessing their implications. Computation, adjusted-map review and publication are complete.", "small")
    text(link("Complete neural inventory, nulls and secondary findings", "results/review/final-summary-v1/README.md") + " | " +
         link("All matched neural adjustments", "results/review/fevs-imaging-adjustments-provisional-v1/README.md") + " | " +
         link("Descriptive correlations", "data/derived/financial-model-review-v1/correlations.tsv"), "small")

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
    parser.add_argument("--output", type=Path, default=ROOT / "output/pdf/FEVS_Adjusted_Results_2026-11-04.pdf")
    parser.add_argument("--temporary", type=Path, default=ROOT / "work/pdf-adjusted-results")
    parser.add_argument("--as-of", default="November 4, 2026")
    parser.add_argument("--chart-only", action="store_true")
    parser.add_argument("--reuse-figure", action="store_true")
    args = parser.parse_args()
    if args.chart_only:
        verify_sources()
        behavioral_figure(args.temporary / "behavioral-pm25-support.png")
    else:
        build(args.output, args.temporary, args.as_of, args.reuse_figure)
