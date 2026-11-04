#!/usr/bin/env python3
"""Assemble a source-verified evidence brief; never fit or rerun an analysis."""
import argparse
import hashlib
import json
from pathlib import Path

import build_fevs_results_pdf as old

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output/pdf/FEVS_Evidence_Brief_2026-11-04.pdf"
TEMP = ROOT / "work/pdf-evidence-brief"
REVIEW = ROOT / "results/review"


def verified_inputs():
    old.verify_sources()
    sources = {}
    for name in ("fevs-win-v1", "fevs-vs-v1", "fevs-adjustment-maps-v1",
                 "katie-review-v1", "behavioral-moderation-provisional-v1", "katie-evidence-v1"):
        folder = REVIEW / name
        manifest = json.loads((folder / "review_manifest.json").read_text())
        assert manifest["n"] == 97
        for relative, sha in manifest["outputs"].items():
            path = folder / relative
            assert path.is_relative_to(folder) and ".." not in Path(relative).parts
            assert old.digest(path) == sha, f"Published evidence changed: {path}"
            sources[str(path.relative_to(ROOT))] = sha
    evidence = json.loads((REVIEW / "katie-evidence-v1/summary.json").read_text())
    assert evidence["n"] == 97 and not evidence["exclusions_changed"]
    assert len(evidence["descriptive_fits"]) == 12 and len(evidence["group_means"]) == 12
    assert all(r["n"] == 97 and not r["exclusions_changed"] for r in evidence["descriptive_fits"])
    return sources


def executed_design():
    """Recreate bytes only if they match the recorded executed .mat AND .con."""
    import numpy as np
    import run_katie_randomise as base

    path = ROOT / "data/derived/financial-model-review-v1/previews/social_specific/fevs/design.tsv"
    values = old.rows(path)
    names = list(values[0])[1:]
    x = np.array([[float(r[n]) for n in names] for r in values])
    assert x.shape == (97, 8) and np.linalg.matrix_rank(x) == 8
    assert np.all(x[:, 0] == 1)
    assert [r["subject"] for r in values] == [r["subject"] for r in old.rows(
        ROOT / "data/derived/katie-cohort-v1/subjects.tsv")]
    audit = json.loads((REVIEW / "katie-review-v1/audit.json").read_text())
    suffix = "/katie-financial-v1/designs/social_specific/fevs/design."
    checks = {}
    for extension, content in (("mat", base.vest_matrix(x)),
                               ("con", base.vest_contrasts(names, "fevs"))):
        expected = next(r["sha256"] for r in audit["fingerprint_records"]
                        if r["path"].endswith(suffix + extension))
        actual = hashlib.sha256(content.encode()).hexdigest()
        assert actual == expected, "Design reconstruction does not match the executed file"
        checks[extension] = actual
    c = np.zeros((2, len(names)))
    c[0, -1], c[1, -1] = 1, -1
    return names, x, c, checks


def design_plot(destination):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    names, x, c, checks = executed_design()
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), layout="constrained",
                             gridspec_kw={"width_ratios": [1.6, 1]})
    axes[0].imshow(x / np.max(np.abs(x), axis=0), aspect="auto", cmap="RdBu_r", vmin=-1, vmax=1,
                   interpolation="nearest")
    axes[0].set(title="Executed design.mat: 97 rows, rank 8, residual df 89",
                ylabel="Frozen participant / image-volume row")
    axes[1].imshow(c, aspect="auto", cmap="RdBu_r", vmin=-1, vmax=1, interpolation="nearest")
    axes[1].set(title="Executed design.con: +/- FEVS", ylabel="Contrast")
    axes[1].set_yticks([0, 1], ["+FEVS", "-FEVS"])
    for ax in axes:
        ax.set_xticks(range(len(names)), names, rotation=45, ha="right", fontsize=9)
    fig.suptitle("Both reconstructed files match the audited executed SHA256 hashes exactly", fontsize=12)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination, dpi=180)
    plt.close(fig)
    return checks


def build(output=OUTPUT, temporary=TEMP):
    from PIL import Image as PILImage
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (Flowable, Image, KeepInFrame, PageBreak, Paragraph, SimpleDocTemplate,
                                    Spacer, Table, TableStyle)

    sources = verified_inputs()
    design = temporary / "executed-fevs-design.png"
    assert design.is_file(), "Run --figures-only in the scientific Python environment first"
    design_record = json.loads((temporary / "design-checks.json").read_text())
    assert old.digest(design) == design_record["figure_sha256"], "Design figure changed"
    curve = temporary / "historical-pm25-support.png"
    assert old.digest(curve) == design_record["behavioral_figure_sha256"], "Behavioral figure changed"
    design_checks = design_record["design_hashes"]
    audit = json.loads((REVIEW / "katie-review-v1/audit.json").read_text())
    for extension, sha in design_checks.items():
        expected = next(r["sha256"] for r in audit["fingerprint_records"] if r["path"].endswith(
            "/katie-financial-v1/designs/social_specific/fevs/design." + extension))
        assert sha == expected, "Design receipt differs from the executed audit"
    teal = colors.HexColor("#126A70")
    styles = {name: ParagraphStyle(name, fontName=font, fontSize=size, leading=leading,
               textColor=teal if name == "section" else colors.HexColor("#182329"), spaceAfter=6)
              for name, font, size, leading in (
                  ("title", "Helvetica-Bold", 21, 25), ("section", "Helvetica-Bold", 11, 14),
                  ("body", "Helvetica", 10, 13), ("small", "Helvetica", 8.5, 11))}
    width = 712
    story = []

    def p(value, style="body"):
        story.append(Paragraph(value, styles[style]))

    def heading(title, context):
        p(title, "title")
        p("PRELIMINARY | Frozen N=97 | Exploratory, not preregistered", "small")
        p("Context", "section")
        p(context)
        p("Content", "section")

    def image(path, w, h):
        with PILImage.open(path) as im:
            iw, ih = im.size
        scale = min(w / iw, h / ih)
        return Image(str(path), width=iw * scale, height=ih * scale)

    class FigurePanel(Flowable):
        """Layout viewport; split a sealed four-row figure without editing it."""
        def __init__(self, path, box, w=712, h=240):
            Flowable.__init__(self)
            self.path, self.box, self.width, self.height = path, box, w, h

        def draw(self):
            with PILImage.open(self.path) as im:
                iw, ih = im.size
            left, top, right, bottom = self.box
            assert 0 <= left < right <= iw and 0 <= top < bottom <= ih
            scale = min(self.width / (right - left), self.height / (bottom - top))
            shown_width = (right - left) * scale
            shown_height = (bottom - top) * scale
            offset = (self.height - shown_height) / 2
            self.canv.saveState()
            clip = self.canv.beginPath()
            clip.rect(0, offset, shown_width, shown_height)
            self.canv.clipPath(clip, stroke=0)
            self.canv.drawImage(str(self.path), -left * scale, offset - (ih - bottom) * scale,
                               width=iw * scale, height=ih * scale, mask="auto")
            self.canv.restoreState()

    def table(rows, widths):
        cells = [[Paragraph(str(v), styles["small"]) for v in row] for row in rows]
        t = Table(cells, colWidths=widths, hAlign="LEFT")
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDF4F4")),
                              ("LINEBELOW", (0, 0), (-1, 0), .6, teal),
                              ("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("TOPPADDING", (0, 0), (-1, -1), 4),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        story.extend([t, Spacer(1, 5)])

    def conclusion(value):
        p("Conclusion", "section")
        p(value)

    heading("Task Effects Before Individual Differences",
            "Do the tasks elicit reward responses, and do the two definitions of social specificity show a group-average effect?")
    evidence_root = REVIEW / "katie-evidence-v1"
    evidence = json.loads((evidence_root / "summary.json").read_text())
    t = Table([[image(evidence_root / "group-average.png", 348, 170),
                image(evidence_root / "group-social_specific.png", 348, 170)]], colWidths=[356, 356])
    story.append(t)
    table([
        ["Outcome", "Existing result", "Interpretation"],
        ["Average win > loss across domains", "Minimum cluster-FWE p=.0001 at both CDTs; 11,811 corrected voxels at CDT 3.1", "Clear group task response (left figure)."],
        ["Double subtraction: (social win-loss) - (nonsocial win-loss)", "No corrected cluster in either direction at either CDT", "No detected group-average domain-by-valence effect (right figure)."],
        ["Social win - nonsocial win", "Corrected positive and negative clusters at both CDTs; see next page", "A domain difference in winning responses, not a win-loss interaction."],
    ], [237, 260, 215])
    conclusion("Reward activation is present. A null group-average double subtraction does not rule out individual differences. "
               "Social-winning and domain-by-valence contrasts answer different questions and must remain distinct.")
    p("Figure rows: unthresholded context, corrected CDT 2.6, corrected CDT 3.1. Red/blue show positive/negative coefficients. "
      "All results use existing no-TEDANA sm-5 FEAT inputs; no preprocessing or exclusions changed.", "small")

    story.append(PageBreak())
    heading("Group Mean: Social Win Minus Nonsocial Win",
            "Does the response to winning differ between social and nonsocial contexts? This is distinct from the double subtraction, which additionally references losses.")
    story.append(image(evidence_root / "group-social_win.png", 690, 265))
    means = [r for r in evidence["group_means"] if r["outcome"] == "social_win"]
    table([["CDT (Z-equivalent)", "Direction", "Minimum cluster-FWE p", "Corrected voxels"]] +
          [[str(r["z"]), r["direction"], f"{r['min_cluster_fwe_p']:.4f}", r["significant_voxels"]] for r in means],
          [170, 160, 205, 177])
    conclusion("There are regions with social > nonsocial winning responses and regions showing the reverse, at both thresholds. "
               "This establishes domain differentiation for winning, not a universal social-reward increase or a domain-by-valence interaction.")
    p("Both new intercept jobs and four directional maps passed validation, including the native sign-flip gate; 10,000 permutations, residual df=90. "
      "The pre-existing win-loss and double-subtraction tests were reused, not rerun.", "small")

    maps = old.rows(REVIEW / "fevs-imaging-adjustments-provisional-v1/maps.tsv")
    targets = [
        ("activation_fevs", "FEVS And Social-Winning Activation", "fevs-win-v1", "fevs-brain.png", "fevs-cluster-1-scatter.png", "positive",
         "Does financial vulnerability relate to the social win-minus-nonsocial win activation contrast?",
         "The original association is positive, but adding Ecog removes whole-brain corrected significance. Treat this as qualified evidence, not an adjustment-robust cortical vmPFC/OFC finding."),
        ("activation_fevs_pm25", "Activation With PM2.5 In The Model", "fevs-win-v1", "fevsxpm25-brain.png", "fevsxpm25-cluster-1-scatter.png", "positive",
         "Does the FEVS activation coefficient remain when PM2.5 and FEVS x PM2.5 are included? The coefficient is evaluated at mean PM2.5.",
         "The conditional FEVS coefficient retains a similar location, but correction is borderline and depends on adjustment. This is a main coefficient, not a significant winning-related FEVS x PM2.5 interaction."),
        ("vs_fevs_pm25", "FEVS And Social-By-Valence VS Connectivity", "fevs-vs-v1", "fevs-vs-cluster-1-brain.png", "fevs-vs-cluster-1-scatter.png", "negative",
         "Does financial vulnerability relate to VS coupling for (social win-loss) minus (nonsocial win-loss), at mean PM2.5?",
         "Higher FEVS relates to a lower social-by-valence connectivity contrast with a left frontal target. This is more consistent across ADI/Ecog adjustment than activation, but it is not evidence of globally weaker connectivity or a winning-only effect."),
    ]
    for target, title, folder, brain, scatter, direction, context, takeaway in targets:
        for half, selected in enumerate((("baseline", "adi"), ("ecog", "adi_ecog"))):
            story.append(PageBreak())
            heading(title + (": Original / +ADI" if half == 0 else ": +Ecog / +Both"), context)
            path = evidence_root / (target + "-paired.png")
            box = (0, 120, 2485, 950) if half == 0 else (0, 975, 2485, 1800)
            story.append(FigurePanel(path, box))
            p("Each brain row is beside its exact model-adjusted scatter. Cyan: original corrected cluster; gold: adjusted corrected cluster. "
              "The same original ROI is used for every scatter, including whole-brain null fits. Brain shading |t|>=2 is descriptive, not corrected significance.", "small")
            records = {r["adjustment"]: r for r in evidence["descriptive_fits"] if r["target"] == target}
            probabilities = {r["adjustment"]: r for r in maps if r["target"] == target and r["direction"] == direction and r["z"] == "3.1"}
            table([["Model", "Cluster-FWE p, CDT 3.1", "ROI slope / HC3 interval (descriptive)", "Leave-one-out slope range / max Cook's D"]] +
                  [[key, f"{float(probabilities[key]['min_cluster_fwe_p']):.4f}",
                    f"{records[key]['beta']:.3g} [{records[key]['hc3_lower']:.3g}, {records[key]['hc3_upper']:.3g}]",
                    f"[{records[key]['loo_beta_min']:.3g}, {records[key]['loo_beta_max']:.3g}] / {records[key]['max_cooks_d']:.3f}"] for key in selected],
                  [100, 170, 220, 222])
            conclusion(takeaway)
            if target.startswith("activation"):
                p("Anatomy caveat: original clusters are predominantly white-matter-labeled in a standard atlas; the jointly adjusted conditional cluster is approximately 64% white-matter-labeled. "
                  "The conditional activation centroid shifts only 1.1 mm with joint adjustment. Neither fact validates a clean cortical vmPFC/OFC claim.", "small")
            else:
                p("The left frontal target is not the VS seed. Joint adjustment retains 42 voxels, 32 overlapping the original 44; centroid shift=1.3 mm. "
                  "Every adjusted peak remains inside the original cluster.", "small")
            p("All 97 participants retained. Selected-ROI scatter slopes/HC3 intervals are descriptive only, not independent confirmation or a rescue of a null whole-brain result. "
              "No cases removed; leave-one-out checks do not exclude collective influence. Findings pass only at CDT 3.1; correction is per map, not across the exploratory model family. "
              "None of these focal models contains MSPSS.", "small")

    story.append(PageBreak())
    heading("Behavioral Context: Support Result Awaiting Correction",
            "Does perceived support moderate the PM2.5-FEVS association? The previous screener MSPSS coding is now known to be incorrect, so this is a historical result awaiting rerun.")
    story.append(image(curve, 690, 215))
    adjustments = old.rows(REVIEW / "fevs-behavioral-adjustments-provisional-v1/adjustments.tsv")
    table([["Historical fit", "Interaction b", "HC3 p (uncorrected sensitivity check)"]] +
          [[r["adjustment"], f"{float(r['interaction_beta']):.3f}", f"{float(r['hc3_p']):.6f}"] for r in adjustments],
          [240, 180, 292])
    p("The displayed conditional-slope panels use the old scores. Pointwise intervals and any JN regions are exploratory, "
      "not simultaneous bands. Original primary behavioral interaction: b=-.802, HC3 CI [-1.208,-.396], p=.000168; "
      "Holm p=.000336 across the original two primary tests. Those numbers are not scoring-corrected findings.", "small")
    conclusion("Do not finalize the support-buffering story yet. Obtain corrected screener and pre-scan scores/dates, verify scoring, "
               "and assess agreement. Preserve N=97; rerun only MSPSS-dependent models and their existing multiplicity summaries after verification.")
    p("The focal FEVS neural models shown earlier do not include MSPSS and are unaffected by its correction. "
      "No matching corrected neural PM2.5 x support result has been established. Separate behavioral and neural associations do not demonstrate mediation.", "small")

    story.append(PageBreak())
    heading("Design Audit And Reporting Decisions",
            "Were the intended coefficients actually contrasted, and does each design retain the same 97 image-volume rows?")
    story.append(Table([[image(evidence_root / "design-activation_fevs-baseline.png", 345, 235),
                         image(evidence_root / "design-activation_fevs_pm25-adi_ecog.png", 345, 235)]], colWidths=[356, 356]))
    p("Left: standalone FEVS. Right: FEVS/PM2.5 with additive ADI and Ecog. These published heatmaps read actual executed .mat/.con files, "
      "not newly chosen designs, and are not native FEAT screenshots. Display-only column scaling; participant identifiers omitted. "
      "The separate complete audit verified image/design ordering.", "small")
    table([["Executed model", "Rank / residual df", "Condition number (scaled)", "Intercept tested?"]] +
          [[r["id"], f"{r['rank']} / {r['residual_df']}", f"{r['scaled_condition_number']:.2f}", "Yes" if r["ones_contrasted"] else "No"]
           for r in evidence["designs"]], [292, 140, 160, 120])
    table([["Check", "Verdict"],
           ["Column of ones", "Included, but NOT tested in the plotted FEVS +/- contrasts. An intercept must have its own nonzero contrast weight."],
           ["FEVS coefficient versus interaction", "Standalone plot tests FEVS. PM2.5-containing figures test FEVS at mean PM2.5, not FEVS x PM2.5."],
           ["Preserved", "Frozen N=97, settled exclusions, all completed imaging results, and original PDF versions."],
          ], [180, 532])
    conclusion("The current coherent description is provisional financial-vulnerability associations with socially differentiated brain responses. "
               "Activation is qualified; the VS-connectivity sensitivity result is more consistent. The environmental-support behavioral link awaits corrected MSPSS scoring.")

    story.append(PageBreak())
    heading("Native FEAT Design Views: Outcome-Phase Check",
            "Are the reward estimates tied to the intended task model? These are unmodified native FEAT screenshots from the first frozen participant's two activation L1s, not custom group-design heatmaps.")
    table([["Social Doors", "Nonsocial Doors"]], [356, 356])
    story.append(Table([[image(evidence_root / "L1-socialdoors-design.png", 345, 137),
                         image(evidence_root / "L1-doors-design.png", 345, 137)],
                        [image(evidence_root / "L1-socialdoors-design_cov.png", 270, 175),
                         image(evidence_root / "L1-doors-design_cov.png", 270, 175)]], colWidths=[356, 356]))
    p("Top: native design.png (design and contrast display). Bottom: native design_cov.png. Both tasks' actual design.fsf/.mat/.con "
      "were checked for the expected win, loss and win-minus-loss contrast weights before these PNGs were copied unchanged. "
      "These are representative design views, not evidence that every participant has identical event timing.", "small")
    conclusion("The expected outcome contrasts are present, and all requested evidence artifacts passed the saved-input checks. "
               "N=97, previous analyses and exclusions remain unchanged. The remaining measurement issue is scoring verification and the planned comparison of MSPSS administrations, not a new imaging exclusion.")

    output.parent.mkdir(parents=True, exist_ok=True)
    def footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(teal)
        canvas.line(40, 582, 752, 582)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(40, 22, "PRELIMINARY | N=97 | Scoring unresolved | Existing results preserved | November 4, 2026")
        canvas.drawRightString(752, 22, str(document.page))
        canvas.restoreState()
    doc = SimpleDocTemplate(str(output), pagesize=(792, 612), leftMargin=40, rightMargin=40,
                            topMargin=39, bottomMargin=36, title="FEVS Evidence Brief: Maps, Associations And Designs",
                            author="RF1-SRA research team")
    pages = [[]]
    for item in story:
        if isinstance(item, PageBreak):
            pages.append([])
        else:
            pages[-1].append(item)
    framed = []
    for index, contents in enumerate(pages):
        if index:
            framed.append(PageBreak())
        framed.append(KeepInFrame(width, 520, contents, mode="shrink", hAlign="LEFT", vAlign="TOP"))
    doc.build(framed, onFirstPage=footer, onLaterPages=footer)
    provenance = dict(n=97, exclusions_changed=False, new_analysis=False,
                      mspss_status="Known screener coding error; corrected scores and reliability comparison pending",
                      unpublished_evidence_batch=False, evidence_publication="11ab6e6", design_hashes=design_checks,
                      inputs=sources, pdf_sha256=old.digest(output), builder_sha256=old.digest(Path(__file__)))
    output.with_suffix(".provenance.json").write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    print(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--temporary", type=Path, default=TEMP)
    parser.add_argument("--figures-only", action="store_true")
    args = parser.parse_args()
    if args.figures_only:
        verified_inputs()
        checks = design_plot(args.temporary / "executed-fevs-design.png")
        old.behavioral_figure(args.temporary / "historical-pm25-support.png")
        record = dict(design_hashes=checks, figure_sha256=old.digest(args.temporary / "executed-fevs-design.png"),
                      behavioral_figure_sha256=old.digest(args.temporary / "historical-pm25-support.png"))
        (args.temporary / "design-checks.json").write_text(json.dumps(record, indent=2) + "\n")
    else:
        build(args.output, args.temporary)
