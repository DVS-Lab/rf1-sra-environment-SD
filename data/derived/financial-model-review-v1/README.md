# FEVS and OAFEM: Separate Predictor Previews

All 97 frozen participants have finite numeric FEVS and OAFEM scores, with unique matching RF1 IDs.
The source order also matches, but the join is explicitly by ID. No rows were dropped, imputed or reordered incorrectly.
FEVS leads these supplemental financial-score models; OAFEM is secondary. Original ADI/PM2.5 models are unchanged.

Each separate model contains the score, age, one gender indicator, two scanner-era indicators, and two QC terms.
Social-specific outcome uses FD/tSNR differences; the domain average uses pair means. All four designs are
full rank (8 columns, N=97, residual df=89), with positive/negative score contrasts. No interactions or joint-score
model, additional covariate adjustment, score transformations or new exclusions were introduced.

| Score | N | Range | Mean | SD | Zero scores | Skewness |
|---|---|---|---|---|---|---|
| FEVS | 97 | 0-17 | 5.26 | 4.55 | 10 | 0.88 |
| OAFEM | 97 | 0-78 | 10.05 | 14.18 | 32 | 2.24 |

OAFEM has a right tail and a substantial zero mass. Leverage diagnostics are descriptive, not exclusions.
Any transformation or influence sensitivity must be specified explicitly, not selected to obtain significance.
The CSV does not document instrument version, score direction, missing-item rules or source timepoint;
Jacob should document these alongside the score file, including that zeros are genuine scores rather than missing codes.
Numeric completeness is not independent verification of the scoring calculation.

These are previews only. No FSL/randomise process was launched and no live images were read or changed.
Do not pull or edit frozen running code on Linux2 to inspect these files; review them on GitHub for now.
