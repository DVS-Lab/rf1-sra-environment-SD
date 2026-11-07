# Results-ready evidence report, November 7, 2026

The three-question report is `output/pdf/FEVS_Results_Ready_2026-11-07.pdf`.
Its aggregate figures, principal evidence table, complete signed/CDT and cluster
inventories, model/null summary, supported conclusions, and analysis record are
under `results/review/katie-results-ready-v1/`.

Build from the published analysis evidence, with the reporting dependencies in
`code/requirements-results-ready.txt`:

```bash
python code/build_katie_results_ready.py --source-revision a9e39e77dc6bb79309c435ebaa15e55a8db984f0
python -m unittest discover -s tests -p test_katie_results_ready.py -v
```

The builder uses table/hash helpers from the existing financial-results builder
and the existing landscape evidence-report layout. It has its own corrected-input
gates. It never calls historical MSPSS result assertions, performs new inference,
or changes historical report builders/PDFs. All support-dependent correlations,
tables and figures use the corrected Island screener scores. Updated marginal
correlations are descriptive, without tests or additional regression models.

The two new Linux2 sensitivity jobs found no corrected FEVS VS-PPI clusters after
adding corrected support. At CDT3.1 the negative-direction map minimum is .0751;
at CDT2.6 it is .1021. The report retains both signs and thresholds, the original
finding, and earlier ADI/ECog sensitivities. Component and ADI/support selected-region
plots are descriptive. Native integrity checks were completed on Linux2; this Mac
independently verifies published manifests, all 384 corrected replacement maps,
and all retained historical passing maps. Historical null-map preservation relies
on the sealed Linux2 audit and inventory. No unthresholded adjusted map/peak or
adjusted fixed-ROI coefficient was included in the published aggregate payload;
the report does not infer spatial persistence or reversal from the corrected null.

The main text contains three principal figure candidates; appendices retain the
behavioral nulls, additional neural findings, influence limitations, acquisition
audit limits, all 71 maps with clusters, and all 134 model/outcome combinations.
The 1,328-row supplementary table retains every canonical tested map, including
nulls; the four new sensitivity maps are separate. Cluster-FWE is per map, not
correction across exploratory analyses. Financial scoring documentation remains
provisional and cognitive recovery is deferred. No manuscript Results section is
drafted.

The reporting tests check corrected-score propagation, rejection of score
tampering, the new sensitivity nulls, all-map preservation, PDF structure,
text boundaries, and exclusion of participant IDs. All PDF pages are rasterized
for visual inspection before publication. `report-manifest.json` seals the PDF,
aggregate payload, and its published sources; the separate validation receipt
records checks and page rendering without circularly hashing itself.
