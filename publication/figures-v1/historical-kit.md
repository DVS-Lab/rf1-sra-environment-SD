# Katie and Jacob's manuscript figure kit

Start with the **SVG** to change labels, colors or layout in Illustrator or Inkscape. Use the matching **PDF** as a visual proof. These are the four figures in the [Results and supplement layout](Katie_Results_and_Supplement_v3.docx), not the entire exploratory map inventory. The Word file preserves the original six embedded panels; the SVG/PDF versions are editable layouts of those results. No cohort, model, exclusion or permutation changed.

| Main figure | Files | What you can edit |
|---|---|---|
| **1. Perceived support and PM2.5 in relation to FEVS** | [SVG](figures/Fig1_behavior.svg) · [PDF](figures/Fig1_behavior.pdf) · [sources](sources/fig1) | Histogram bins, curves, ribbons and text. The histograms contain counts, not participant rows. |
| **2. FEVS and ventral striatal coupling** | [SVG](figures/Fig2_FEVS_VS_coupling.svg) · [PDF](figures/Fig2_FEVS_VS_coupling.pdf) · [sources](sources/fig2) | Reposition the original brain and scatter panels independently. The shared scatter panel is a high-resolution raster, not editable dots. The Linux2 export below produces a fully editable scatter panel and the exact plotted points and bands. |
| **3. Neighborhood disadvantage, support and winning activation** | [SVG](figures/Fig3_ADI_support_activation.svg) · [PDF](figures/Fig3_ADI_support_activation.pdf) · [sources](sources/fig3) | Original raster brain slices, editable conditional slopes, ribbons and labels. To change the slice or overlay, use the native group map. |
| **4. ADI × ECog and corticostriatal connectivity** | [SVG](figures/Fig4_ADI_ECog_VS_overlap.svg) · [PDF](figures/Fig4_ADI_ECog_VS_overlap.pdf) · [sources](sources/fig4) | Each cell and label is editable. This was Figure S1. Cite **Figure 4** in the main text; the cluster catalogue and influence results remain in **Supplementary Table S1**. |

### Captions and checks when editing

**Figure 1.** Perceived support and the association between PM2.5 exposure and financial exploitation vulnerability (FEVS; N = 97). Panels A and B show the joint distribution and the support histogram; dashed lines mark the observed 16th and 84th percentiles (16 participants in each inclusive tail). Panel C shows the conditional exposure slope with pointwise HC3 95% intervals for the linear model and the prespecified quadratic-support sensitivity. Panel D shows Cook's distance for the linear model; 4/N is a diagnostic guide, not an exclusion rule. The reduction in slope at higher support is clearer than a reversal: the quadratic interval includes zero at the upper anchor.

**Figure 2.** At mean PM2.5, higher FEVS was associated with a more negative domain-by-valence contrast in coupling between the ventral striatal seed and a left frontal target (44 voxels; peak MNI −20.8, 57.6, 11.2 mm; cluster-FWE p = .0303, CDT 3.1). The adjacent panels show social win minus loss, nonsocial win minus loss, and the difference in the same selected region. Points are covariate-adjusted COPEs, not raw COPEs; ribbons are pointwise HC3 95% intervals. Keep common axes. This is a seed-connectivity effect, not striatal activation. No whole-brain cluster survived adding corrected MSPSS.

**Figure 3.** ADI interacted with corrected screener MSPSS for social minus nonsocial winning activation in a right posterior temporal cluster (87 voxels; peak MNI 54.8, −31.5, 8.2 mm; cluster-FWE p = .0255, CDT 3.1). Lines show conditional ADI slopes for the two winning components and their difference with pointwise HC3 95% intervals. The social and nonsocial components contributed in opposite directions. Both Figures 2B and 3B describe regions selected from the same sample; neither is independent confirmation.

**Figure 4.** Pairwise Dice overlap among the ten corrected ADI × ECog ventral-striatal connectivity clusters. Rows and columns match the C01–C10 IDs in Supplementary Table S1. Avg = domain-average win minus loss; Loss = social minus nonsocial losing; DxV = (social win minus loss) minus (nonsocial win minus loss). Labels indicate the Z-equivalent cluster-defining threshold. These are **cluster-pair**, not whole-contrast-mask, Dice values. For example, C05 and C09 share 46 voxels (pair Dice .26; full-mask Dice .099). The two DxV clusters do not overlap across thresholds. Do not depict all clusters as one recurring network. All cluster-FWE corrections here are within map, not across models.

### Regenerate the layouts

From the repository root, using Python with NumPy and Matplotlib:

```bash
python publication/figures-v1/render.py --output work/figure-proofs
```

This needs only the adjacent source files, not Linux2, identifier tables or brain images. Colors are in `render.py`; SVG labels are real text. Change fonts and margins there rather than editing each PDF separately. Preserve the physical aspect ratio and left/right orientation of the brain slices. Use the full-resolution embedded panels, not a screenshot of GitHub's preview. Inspect the proofs at the journal's final column width.

The [source index](sources/provenance.tsv) maps the copied assets to the sealed evidence, with SHA-256 hashes. `prepare_sources.py` is only needed to refresh those copies: it derives the histogram bins from the verified cohort and the *saved* linear coefficients, without fitting a new model. For Figure 3, the slope is linear and its squared confidence half-width is quadratic in support; the three saved anchors specify both curves across the observed range. For Figure 4 use `vs_cluster_overlap.tsv` to redraw the matrix; `vs_map_overlap.tsv` answers the different full-mask question. The original [November 7 report](../../output/pdf/FEVS_Results_Ready_2026-11-07.pdf) and [targeted follow-up](../../output/pdf/FEVS_Targeted_Results_Followup_v1.pdf) are unchanged.

### Native map and extraction handoff (Linux2 only)

The first figure-kit commit contains **no native NIfTIs or individual extraction tables**. Run this once on Linux2 to populate the group-map folder in this repository and produce the lab-only tables. It uses the existing review environment and authenticated HTTPS Git; it does not use SSH or run randomise.

```bash
(
  set -euo pipefail
  umask 0000
  cd /ZPOOL/data/projects/rf1-sra-environment-SD
  url=https://github.com/DVS-Lab/rf1-sra-environment-SD.git
  [[ $(git branch --show-current) == main ]]
  git pull --ff-only "$url" main
  [[ $(git rev-parse HEAD) == $(git rev-parse FETCH_HEAD) ]]
  bash publication/figures-v1/finish_linux2.sh
)
```

- **GitHub:** after a successful export, `publication/figures-v1/group-maps/` contains a binary mask and a thresholded, *signed* t-statistic NIfTI for each of the 12 figure regions, plus `maps.tsv` (figure/cluster, native job, contrast index, direction, voxel count, peak and corrected p). These are actual corrected voxels on the original MNI grid, not spheres around reported peaks. Use the signed-t image for color and the mask for the footprint. Native FSL corrected images encode **1 − p**; the original selection is strictly **> .95** within the search mask. A negative test is shown with negative t, not as red activation.
- **Linux2 only:** `/ZPOOL/data/projects/rf1-sra-environment-SD/work/katie-figure-sources-v1/extractions/` contains `Fig2_VS_PPI_components_and_adjusted_points.tsv` (97 × 3), `Fig2_scatter_lines_and_bands.tsv`, the editable `Fig2B_editable.svg/.pdf`, `Fig3_winning_COPEs.tsv` (97 paired task estimates), and `Fig4_VS_PPI_by_cluster.tsv` (97 × 10). **Do not add this directory to Git.**
- The exporter checks source fingerprints, frozen order, cluster peaks, sizes and corrected p-values, component estimates, and all 45 Dice pairs. It verifies saved outputs on repeat runs. Only the explicitly named group maps and their index are staged. The logged export and verification use the existing Linux2 run-record publisher; no imaging inputs or completed results are overwritten.
