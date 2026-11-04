# Illustrated Evidence Brief

The [November 4 evidence brief](../output/pdf/FEVS_Evidence_Brief_2026-11-04.pdf)
uses context, content and conclusion for each section. It replaces neither the
complete results inventory nor prior PDF versions.

## Included

- Explicit striatal sanity-check answer: both tasks show bilateral ventral-
  striatal-region win-minus-loss peaks in corrected clusters. The across-task
  average peaks at approximately [-12.7, 6.3, -9.6] and [14.3, 9.0, -9.6],
  t=11.79/11.70, cluster-FWE p=.0001. Existing anatomical VS summaries also have
  positive means in both tasks. Peak locations are regional descriptions, not
  newly assigned atlas nuclei; cluster p-values are not voxel-FWE p-values.
- The anatomical VS distribution plot and task-specific descriptive 95% CIs.
  The double-subtraction ROI summary is kept distinct from social-minus-
  nonsocial winning. No new ROI model, atlas overlap or inference is claimed.

- All four original/ADI/Ecog/joint standalone and PM2.5-containing FEVS activation
  brain maps with their exact model-adjusted scatterplots beside them.
- All four conditional FEVS VS-connectivity brain maps with matching scatters.
- All four original/ADI/Ecog/joint sensitivity p-values, including nulls.
- Activation tissue-label caveat; the original corrected ROI held fixed across
  every descriptive scatter, including whole-brain null fits.
- Average win-minus-loss, double-subtraction and social-minus-nonsocial winning
  group maps. The last contrast's two new jobs passed, with positive/negative
  corrected clusters at both thresholds (CDT 3.1 minimum p=.0021/.0011).
- Actual executed group design/contrast heatmaps, rank/df/condition checks and
  intercept-test status, plus native FEAT design and covariance screenshots.
- Historical behavioral conditional slopes, explicitly labeled as using the
  now-known erroneous screener MSPSS coding, not corrected findings.

No ROI p-values are sold as independent confirmation. All 97 observations remain.
The four-row paired panels are split into two rows per page using a layout
viewport for legibility; source PNGs stay intact. Context, numerical content and
plain-English conclusions are retained for every page.

## Validated Evidence Publication

The evidence package appeared during PDF preparation at analysis commit
`11ab6e6`, with Linux2 run records published at `98f35394`. Task-mean, figure and
publication commands/checks passed. The report checked 6,604 unique input files.
The PDF was updated to include the actual artifacts instead of the earlier
pending labels. No additional jobs are required to produce these figures.

## Reproduce

In the scientific Python environment, run:

```bash
python code/build_katie_evidence_pdf.py --figures-only
```

Then in an environment with Pillow and ReportLab:

```bash
python code/build_katie_evidence_pdf.py
```

Both can be the same Python if all dependencies are installed. The new PDF has
a source-hash/provenance companion. Existing images, results, cohort and settled
exclusions remain unchanged. PDF pages are rendered and visually checked before
publication. MSPSS-dependent models remain provisional until the correction and
administration/timepoint choice are verified; no models are rerun by this builder.
