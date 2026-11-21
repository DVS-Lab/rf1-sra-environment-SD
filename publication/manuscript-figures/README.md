# Rodman manuscript figures

**Use these three Results figures for Katie's paper.** Each folder has the PDF proof, editable SVG, PNG for Word, caption and plotted values. In Figures 2 and 3 the native thresholded NIfTI and its binary mask are **beside the artwork**. The signed-t image is the color overlay; the mask is its footprint.

| Figure | Files and data | Contrast shown |
|---|---|---|
| **1. PM₂.₅ and financial vulnerability** | [Open folder](Figure-1/) · [PDF](Figure-1/Figure-1.pdf) · [SVG](Figure-1/Figure-1.svg) | The primary linear PM₂.₅ slope across perceived support. One curve and its pointwise 95% interval. |
| **2. Deprivation, support and winning activation** | [Open folder](Figure-2/) · [PDF](Figure-2/Figure-2.pdf) · [SVG](Figure-2/Figure-2.svg) | Right posterior temporal map and the ADI slope for **social wins minus monetary wins**. |
| **3. Financial vulnerability and ventral striatal coupling** | [Open folder](Figure-3/) · [PDF](Figure-3/Figure-3.pdf) · [SVG](Figure-3/Figure-3.svg) | Left frontal target and the FEVS coefficient for **(social win − loss) − (monetary win − loss)**. |

**Crosswalk to the Word files sent to Katie:** those files reserved Figure 1 for a Methods schematic. In this *Results-figure kit*, Figure 1 is the attached Results Figure 2, Figure 2 is the attached Results Figure 3, and Figure 3 is the attached supplemental Figure S2 with only its between-task estimate retained. Figures 1 and 2 reproduce the embedded PNGs byte for byte. The manuscripts themselves have not been renumbered here.

The two remaining supplemental figures are separate: [S1, support and influence diagnostics](supplement/Figure-S1/), and [S3, task-specific winning slopes](supplement/Figure-S3/). Their identifiers match the supplied supplement. There is no Figure 4 in this kit.

**Editing:** open an SVG to change labels, colors or spacing. The main plots have editable text, curves or interval marks; the brain slices are raster underlays with the original overlays. To change slices, use the corresponding NIfTIs. Keep the contrast direction, zero reference and pointwise interval labels. The regional plots describe whole-brain-selected regions in the same 97 participants; they are not independent tests.

**Reproduce the artwork:** with Matplotlib, NumPy and Pillow installed, run `python render.py --output /tmp/rodman-figure-proofs` from this folder. Only the files packaged here are read. No Linux2 export, individual records, model fitting, permutations or rethresholding are needed. The [source-staging script](../../code/stage_rodman_figure_sources.py) records the mapping to the historical validated outputs; each imaging folder's `map-index.tsv` gives the native job, contrast index, peak MNI coordinates, voxel count, corrected p and both NIfTI hashes.
