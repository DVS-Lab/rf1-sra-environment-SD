#!/usr/bin/env python3
"""Assemble a source-verified evidence brief; never fit or rerun an analysis."""
import argparse
import hashlib
import json
from pathlib import Path

import build_fevs_results_pdf as old

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output/pdf/FEVS_Working_Results_Overview_2026-11-04.pdf"
TEMP = ROOT / "work/pdf-results-overview"
REVIEW = ROOT / "results/review"
SECTIONS = ("1. Behavior", "2. Basic Activation", "3. Exploratory Activation",
            "4. Exploratory Connectivity", "Appendix: Design Validation")


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
    for relative in ("data/derived/financial-model-review-v1/correlations.tsv",
                     "data/derived/financial-model-review-v1/provenance.json",
                     "results/review/fevs-behavioral-adjustments-provisional-v1/adjustments.tsv",
                     "results/review/fevs-behavioral-adjustments-provisional-v1/provenance.json"):
        sources[relative] = old.digest(ROOT / relative)
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


def striatal_task_check():
    """Summarize existing corrected clusters and independent anatomical ROI data."""
    clusters = old.rows(REVIEW / "katie-review-v1/clusters.tsv")
    peaks = []
    for outcome in ("socialdoors", "doors", "average"):
        for side, bounds in (("Left", (-25, 0)), ("Right", (0, 25))):
            matches = [r for r in clusters if r["batch"] == "group_activation" and r["outcome"] == outcome
                       and r["z"] == "3.1" and r["direction"] == "positive"
                       and bounds[0] < float(r["peak_x_mm"]) < bounds[1]
                       and 0 < float(r["peak_y_mm"]) < 20 and -15 < float(r["peak_z_mm"]) < 0]
            assert matches, "Previously reported ventral-striatal-region peak missing"
            selected = max(matches, key=lambda r: float(r["peak_contrast_t"]))
            peaks.append(dict(outcome=outcome, side=side,
                              xyz=[float(selected[f"peak_{axis}_mm"]) for axis in "xyz"],
                              t=float(selected["peak_contrast_t"]),
                              cluster_p=float(selected["cluster_fwe_p_min"])))
    roi = {r["outcome"]: r for r in old.rows(REVIEW / "katie-review-v1/vs_group_response.tsv")}
    assert all(int(r["n"]) == 97 for r in roi.values())
    return peaks, roi


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


def behavioral_plots(temporary):
    """Visualize published estimates only; do not refit or correct the scores."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    estimates = [r for r in old.rows(REVIEW / "behavioral-moderation-provisional-v1/conditional_slopes.tsv")
                 if r["model"] == "fevs_pm25_mspss"]
    fig, ax = plt.subplots(figsize=(8, 3.1), layout="constrained")
    x = [float(r["moderator_value"]) for r in estimates]
    ax.fill_between(x, [float(r["ci_lower"]) for r in estimates],
                    [float(r["ci_upper"]) for r in estimates], color="#126A70", alpha=.18,
                    label="HC3 pointwise 95% interval")
    ax.plot(x, [float(r["conditional_exposure_slope"]) for r in estimates], color="#126A70", lw=2,
            label="Estimated PM2.5-FEVS slope")
    ax.axhline(0, color="#54636b", lw=.8)
    ax.set(xlim=(0, 7), xlabel="Original screener MSPSS mean (coding correction pending)",
           ylabel="FEVS points per unit PM2.5")
    ax.set_title("Historical scores: the entire support scale needs verification", fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=8)
    fig.savefig(temporary / "historical-pm25-support.png", dpi=200)
    plt.close(fig)
    correlations = [r for r in old.rows(ROOT / "data/derived/financial-model-review-v1/correlations.tsv")
                    if r["variable_1"] == "fevs"]
    labels = dict(adi="ADI", pm25="PM2.5", mspss="MSPSS (old coding)", ecog="Ecog", oafem="OAFEM")
    fig, ax = plt.subplots(figsize=(8, 2.7), layout="constrained")
    bars = ax.barh([labels[r["variable_2"]] for r in correlations],
                   [float(r["pearson_r"]) for r in correlations],
                   color=["#a6afb3" if r["variable_2"] == "mspss" else "#126A70" for r in correlations])
    for bar, row in zip(bars, correlations):
        value = float(row["pearson_r"])
        if row["variable_2"] == "mspss":
            bar.set_hatch("///")
        ax.text(value + (.025 if value >= 0 else -.025), bar.get_y() + bar.get_height()/2,
                f"{value:.2f}", va="center", ha="left" if value >= 0 else "right", fontsize=9)
    ax.axvline(0, color="#54636b", lw=.8)
    ax.set(xlim=(-.65, .65), xlabel="Unadjusted Pearson correlation with FEVS (N=97)")
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(temporary / "fevs-descriptive-correlations.png", dpi=200)
    plt.close(fig)


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
    correlation_plot = temporary / "fevs-descriptive-correlations.png"
    assert old.digest(correlation_plot) == design_record["correlation_figure_sha256"], "Correlation figure changed"
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
    page_metadata = []

    def p(value, style="body"):
        story.append(Paragraph(value, styles[style]))

    def heading(title, context, section):
        assert section in SECTIONS and title.endswith("?"), "Each subsection must ask a specific question"
        page_metadata.append(dict(section=section, question=title))
        p(section, "section")
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

    peaks, roi = striatal_task_check()
    heading("Do wins elicit the expected striatal response?",
            "Yes: both Social Doors and nonsocial Doors show bilateral ventral-striatal-region win > loss responses. "
            "This is expected-effect/task validation, not a preregistered confirmatory analysis. Social specificity is a separate question.", SECTIONS[1])
    evidence_root = REVIEW / "katie-evidence-v1"
    evidence = json.loads((evidence_root / "summary.json").read_text())
    story.append(image(evidence_root / "group-average.png", 690, 240))
    table([["Win > loss outcome", "Left / right regional peak t", "Left / right cluster-FWE p", "Anatomical VS mean [descriptive 95% CI]"]] +
          [[label,
            " / ".join(f"{next(r for r in peaks if r['outcome'] == outcome and r['side'] == side)['t']:.2f}" for side in ("Left", "Right")),
            " / ".join(f"{next(r for r in peaks if r['outcome'] == outcome and r['side'] == side)['cluster_p']:.4f}" for side in ("Left", "Right")),
            f"{float(roi[outcome]['mean']):.2f} [{float(roi[outcome]['descriptive_ci_lower']):.2f}, {float(roi[outcome]['descriptive_ci_upper']):.2f}]"]
           for outcome, label in (("socialdoors", "Social Doors"), ("doors", "Nonsocial Doors"), ("average", "Across-task average"))],
          [160, 165, 160, 227])
    conclusion("The expected striatal reward response is present, not missing: averaged win > loss peaks near MNI [-12.7, 6.3, -9.6] "
               "and [14.3, 9.0, -9.6] lie in corrected clusters with FWE p=.0001. "
               "Both tasks therefore recover the expected reward response; this is task validation, not the novel financial-vulnerability result.")
    p("Figure rows: unthresholded context, corrected CDT 2.6, corrected CDT 3.1. Red/blue show positive/negative coefficients. "
      "Cluster p-values are not voxel-FWE claims. ROI summaries are descriptive COPE units, not percent signal change or new ROI tests. "
      "Existing no-TEDANA sm-5 FEAT inputs and exclusions are unchanged.", "small")

    story.append(PageBreak())
    heading("Do winning responses differ by social context?",
            "Compare social win minus nonsocial win. This is distinct from the double subtraction, which additionally references losses.", SECTIONS[1])
    story.append(image(evidence_root / "group-social_win.png", 690, 265))
    means = [r for r in evidence["group_means"] if r["outcome"] == "social_win"]
    table([["CDT (Z-equivalent)", "Direction", "Minimum cluster-FWE p", "Corrected voxels"]] +
          [[str(r["z"]), r["direction"], f"{r['min_cluster_fwe_p']:.4f}", r["significant_voxels"]] for r in means],
          [170, 160, 205, 177])
    conclusion("There are regions with social > nonsocial winning responses and regions showing the reverse, at both thresholds. "
               "This establishes domain differentiation for winning, not a universal social-reward increase or a domain-by-valence interaction. "
               "It should not be presented as proof of additional striatal activation for social wins.")
    p("The displayed domain effects include temporal and posterior cortical areas, with both positive and negative regions. "
      "These are coarse visual descriptions, not new atlas assignments; exact striatal overlap for this contrast has not been quantified.", "small")
    p("Both new intercept jobs and four directional maps passed validation, including the native sign-flip gate; 10,000 permutations, residual df=90. "
      "The pre-existing win-loss and double-subtraction tests were reused, not rerun.", "small")

    story.append(PageBreak())
    heading("Is win-loss differentiation stronger for social outcomes?",
            "Test (social win-loss) minus (nonsocial win-loss). A social-winning difference alone does not answer this domain-by-valence question.", SECTIONS[1])
    story.append(Table([[image(evidence_root / "group-social_specific.png", 348, 170),
                         image(REVIEW / "katie-review-v1/figures/vs-group-response.png", 348, 170)]], colWidths=[356, 356]))
    table([["CDT", "Direction", "Minimum cluster-FWE p", "Corrected voxels"]] +
          [[r["z"], r["direction"], f"{r['min_cluster_fwe_p']:.4f}", r["significant_voxels"]]
           for r in evidence["group_means"] if r["outcome"] == "social_specific"], [120, 150, 250, 192])
    p("ROI values are arbitrary COPE units, not percent signal change. The anatomical seed-VS mask was intersected with the common analysis mask, "
      "and all 97 participants remain. These are descriptive ROI summaries, not new small-volume-corrected tests. "
      "The ROI intervals do not replace the whole-brain cluster-corrected tests.", "small")
    conclusion("No corrected group-average domain-by-valence effect was detected at either CDT. "
               "The anatomical VS social-minus-nonsocial win-loss mean is -11.29 [descriptive 95% CI -29.65, 7.06]. "
               "This does not establish equivalence and does not rule out individual-difference associations. "
               "The contrast is not social win minus nonsocial win, because it also subtracts losses.")

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
            questions = {
                "activation_fevs": ("Does FEVS relate to social-winning activation?", "Does the activation association persist with Ecog adjustment?"),
                "activation_fevs_pm25": ("Does the FEVS activation effect remain when PM2.5 is modeled?", "Does PM2.5-adjusted activation survive ADI/Ecog control?"),
                "vs_fevs_pm25": ("Does FEVS relate to socially differentiated VS connectivity?", "Does the connectivity association persist with ADI/Ecog control?"),
            }
            heading(questions[target][half], context + (" Rows: original and +ADI." if half == 0 else " Rows: +Ecog and +ADI/Ecog."),
                    SECTIONS[3] if target.startswith("vs_") else SECTIONS[2])
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
    heading("Does perceived support modify the PM2.5-FEVS association?",
            "FEVS is the primary financial-vulnerability outcome. These age/gender-adjusted models ask whether the PM2.5 association varies with perceived support. "
            "The displayed findings use the original screener MSPSS scores and remain provisional pending their coding correction.", SECTIONS[0])
    story.append(image(curve, 690, 215))
    adjustments = old.rows(REVIEW / "fevs-behavioral-adjustments-provisional-v1/adjustments.tsv")
    table([["Historical fit", "Interaction b", "HC3 p (uncorrected sensitivity check)"]] +
          [[r["adjustment"], f"{float(r['interaction_beta']):.3f}", f"{float(r['hc3_p']):.6f}"] for r in adjustments],
          [240, 180, 292])
    p("The displayed conditional-slope plot uses the old scores. Pointwise intervals and any JN regions are exploratory, "
      "not simultaneous bands. Original primary behavioral interaction: b=-.802, HC3 CI [-1.208,-.396], p=.000168; "
      "Holm p=.000336 across the original two primary tests. Those numbers are not scoring-corrected findings.", "small")
    conclusion("In the original export, the PM2.5-FEVS association becomes less positive as reported support increases, and the interaction persists after adding ADI/Ecog. "
               "That is the candidate behavioral pattern, not a finalized buffering result: the coding correction can affect all 97 scores, not just five low values. "
               "Verify both MSPSS administrations, assess agreement, then rerun the affected models and original multiplicity summaries without changing the cohort.")
    p("The focal FEVS neural models shown earlier do not include MSPSS and are unaffected by its correction. "
      "No matching corrected neural PM2.5 x support result has been established. Separate behavioral and neural associations do not demonstrate mediation.", "small")

    story.append(PageBreak())
    heading("How does financial vulnerability relate to the other measures?",
            "Before linking behavior to brain responses, inspect the already-computed marginal associations. "
            "These descriptive correlations are not adjusted effects, causal paths or criteria for choosing whichever model is significant.", SECTIONS[0])
    story.append(image(correlation_plot, 690, 190))
    pairs = [r for r in old.rows(ROOT / "data/derived/financial-model-review-v1/correlations.tsv") if r["variable_1"] == "fevs"]
    labels = dict(adi="ADI", pm25="PM2.5", mspss="MSPSS (old coding; pending)", ecog="Ecog", oafem="OAFEM (secondary)")
    table([["Measure paired with FEVS", "Pearson r", "Spearman rho", "N"]] +
          [[labels[r["variable_2"]], f"{float(r['pearson_r']):.2f}", f"{float(r['spearman_rho']):.2f}", r["n"]] for r in pairs],
          [352, 120, 140, 100])
    conclusion("FEVS has modest descriptive associations with Ecog and OAFEM, but weak marginal associations with ADI and PM2.5. "
               "The MSPSS association needs rescoring. Neither weak exposure correlations nor the support interaction establish an environment-brain-FEVS pathway.")
    p("Next specific question: does Ecog agree with objective cognitive performance? "
      "Inventory NIH EXAMINER/TabCAT executive measures, Salthouse Letter/Pattern Comparisons, and WIAT-IV Math Fluency, with assessment dates and availability within N=97. "
      "No comparison results are available yet; no cohort or neural-model changes are implied.", "small")

    story.append(PageBreak())
    heading("Did the group designs test the intended effects?",
            "Check the actual contrast weights, rank and image-volume ordering rather than inferring the test from the presence of a column of ones.", SECTIONS[4])
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
    heading("Were the intended win and loss outcomes modeled?",
            "Inspect unmodified native FEAT screenshots from the first frozen participant's two activation L1s, not custom group-design heatmaps.", SECTIONS[4])
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
    ordered_metadata = []
    def footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(teal)
        canvas.line(40, 582, 752, 582)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(40, 22, "PRELIMINARY | N=97 | Scoring unresolved | Existing results preserved | November 4, 2026")
        canvas.drawRightString(752, 22, str(document.page))
        info = ordered_metadata[document.page - 1]
        key = "page-" + str(document.page)
        canvas.bookmarkPage(key)
        if document.page == 1 or ordered_metadata[document.page - 2]["section"] != info["section"]:
            canvas.bookmarkPage(key + "-section")
            canvas.addOutlineEntry(info["section"], key + "-section", level=0)
        canvas.addOutlineEntry(info["question"], key, level=1)
        canvas.restoreState()
    doc = SimpleDocTemplate(str(output), pagesize=(792, 612), leftMargin=40, rightMargin=40,
                            topMargin=39, bottomMargin=36, title="FEVS Working Results: Behavior, Activation And Connectivity",
                            author="RF1-SRA research team")
    pages = [[]]
    for item in story:
        if isinstance(item, PageBreak):
            pages.append([])
        else:
            pages[-1].append(item)
    assert len(pages) == len(page_metadata)
    order = sorted(range(len(pages)), key=lambda i: SECTIONS.index(page_metadata[i]["section"]))
    ordered_metadata.extend(page_metadata[i] for i in order)
    framed = []
    for index, original_index in enumerate(order):
        if index:
            framed.append(PageBreak())
        framed.append(KeepInFrame(width, 520, pages[original_index], mode="shrink", hAlign="LEFT", vAlign="TOP"))
    doc.build(framed, onFirstPage=footer, onLaterPages=footer)
    provenance = dict(n=97, exclusions_changed=False, new_analysis=False,
                      mspss_status="Known screener coding error; corrected scores and reliability comparison pending",
                      unpublished_evidence_batch=False, evidence_publication="11ab6e6", design_hashes=design_checks,
                      sections=list(SECTIONS), pages=ordered_metadata,
                      derived_figures={key: value for key, value in design_record.items() if key.endswith("sha256")},
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
        behavioral_plots(args.temporary)
        record = dict(design_hashes=checks, figure_sha256=old.digest(args.temporary / "executed-fevs-design.png"),
                      behavioral_figure_sha256=old.digest(args.temporary / "historical-pm25-support.png"),
                      correlation_figure_sha256=old.digest(args.temporary / "fevs-descriptive-correlations.png"))
        (args.temporary / "design-checks.json").write_text(json.dumps(record, indent=2) + "\n")
    else:
        build(args.output, args.temporary)
