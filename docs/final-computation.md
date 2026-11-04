# Katie / Social Doors: Final Computation Record

## Verified Completion

The [published Linux2 completion record](https://github.com/DVS-Lab/rf1-sra-linux2/blob/main/logs/records/20261103-001224_reward-extension-20261103-001224.md)
records **220/220 extension jobs completed**, command exit 0 and check exit 0.
The complete catalog contains **1,328 directional scientific maps**: 996 new
maps plus 332 retained maps. Earlier group-average activation checks remain
separate from this catalog. No new exclusions or preprocessing were performed.

The frozen **N=97**, settled exclusions, no-TEDANA sm-5 FEAT inputs and original
VS seed remain unchanged. Validation checked exact participant/image/design
order, paired arithmetic, outcome-phase contrasts, compatible PPI components,
full-rank designs, source fingerprints (6,117 unique files), native outputs and
successful job receipts. Completed results do not need to be rerun.

## Final Map Counts

| Outcome | Activation maps | Activation maps with corrected clusters | VS-PPI maps | VS-PPI maps with corrected clusters |
| --- | ---: | ---: | ---: | ---: |
| Social modulation of win minus loss | 168 | 0 | 168 | 17 |
| Domain-average win minus loss | 160 | 3 | 160 | 19 |
| Social win minus nonsocial win | 168 | 5 | 168 | 7 |
| Social loss minus nonsocial loss | 168 | 4 | 168 | 14 |

"With corrected clusters" means at least one cluster with per-map cluster-FWE
p < 0.05. These are **maps, not independent discoveries or cluster counts**.
Directions, related models and the two CDTs can capture the same association.
Inference uses 10,000 permutations, seed 20261101 and Z-equivalent CDTs 2.6 and
3.1 converted to t using each design's residual degrees of freedom. There is
no additional correction across models, outcomes, directions or CDTs. All
analyses are exploratory; report nulls and the tested search space as well.

The outcome definitions must remain distinct:

- Social modulation of valence: (Social win - Social loss) - (Doors win - Doors loss).
- Domain-average valence: 0.5 * [(Social win - Social loss) + (Doors win - Doors loss)].
- Social-specific winning: Social win - Doors win.
- Social-specific losing: Social loss - Doors loss.

For VS PPI, the corresponding contrasts concern task-modulated VS coupling,
not activation or overall connectivity strength. Main effects in interaction
models are conditional on the other centered predictor being zero. They are
not interaction effects or independent replications of reduced models.

## Canonical Final Files

Linux2 result root:

```text
/ZPOOL/data/projects/rf1-sra-environment-SD/derivatives/fsl/randomise/katie-reward-extension-v1/
```

- `maps.tsv`: all 1,328 scientific maps, including null results.
- `clusters.tsv`: corrected passing clusters and their coordinates.
- `validation.json`: final validation checks.
- `subjects.tsv` and `source_order.tsv`: frozen cohort and source-image order.
- `plan.json`, `plan.sha256` and job `success.json` receipts: frozen analysis provenance.

These files remain in ignored derivatives. The [final read-only extraction](https://github.com/DVS-Lab/rf1-sra-linux2/blob/main/logs/records/20261103-201516_reward-extension-status-20261103-201516-results.md)
also exited 0: N=97, 220 completed jobs, zero pending, all 996 extension maps
verified against 6,453 unique source/result files. The accompanying snapshot
confirms zero recorded failures, no active extension workers and the complete
1,328-row final catalog. No additional computation or exclusions are required.

The seven social-win-minus-nonsocial-win VS-PPI maps are:

| Model | Tested term | Direction | Z-equivalent CDT | Minimum cluster-FWE p |
| --- | --- | --- | ---: | ---: |
| OAFEM x Ecog | OAFEM at mean Ecog | Positive | 3.1 | 0.0264 |
| OAFEM x Ecog | OAFEM at mean Ecog | Negative | 3.1 | 0.0297 |
| OAFEM x Ecog | OAFEM at mean Ecog | Positive | 2.6 | 0.0310 |
| OAFEM x MSPSS | OAFEM at mean MSPSS | Positive | 3.1 | 0.0441 |
| ADI x Ecog | Ecog at mean ADI | Positive | 3.1 | 0.0479 |
| OAFEM x Ecog | Ecog at mean OAFEM | Positive | 2.6 | 0.0487 |
| Additive PM2.5 + Ecog | Ecog adjusted for PM2.5 | Positive | 2.6 | 0.0497 |

None is a FEVS effect or an interaction. Positive and negative maps can reflect
different brain regions; no anatomical interpretation follows from this table
alone. The published extraction does not include those cluster coordinates or
new influence diagnostics. Their anatomical/figure review remains a reporting
follow-up. The previously reviewed FEVS social-winning activation associations
remain present (standalone p=0.0411; conditional at mean PM2.5 p=0.0315).

## Read-Only Final Findings Extraction

Run this exact block on Linux2. Despite its historical `--partial-results`
name, it now summarizes all completed extension results, with the final catalog
summary included. It does not launch randomise or modify completed images,
exclusions or the live checkout. Run records publish through HTTPS Git
automatically; bulk images are not published.

```bash
(
set -euo pipefail
umask 0000
cd /ZPOOL/data/projects/rf1-sra-environment-SD
git -c remote.origin.url=https://github.com/DVS-Lab/rf1-sra-environment-SD.git fetch origin main
bash <(git show FETCH_HEAD:code/launch_reward_extension.sh) --partial-results
)
```

The remaining scientific closeout is to reconcile these final findings with
the existing curated reports, review new cluster anatomy/influence diagnostics
where needed, and choose the manuscript's focal results transparently. No
participant deletions should be made from selected-cluster scatterplots or
Cook's-distance flags. Those follow-ups are descriptive, not independent
confirmation of the selection that produced the clusters.

Existing curated reports:

- [FEVS social-winning activation](../results/review/fevs-win-v1/README.md).
- [FEVS domain-by-valence VS connectivity](../results/review/fevs-vs-v1/README.md).
- [Loss moderation and Ecog follow-ups](../results/review/reward-followup-v1/README.md).
- [Earlier 152-job / 336-map review](../results/review/katie-review-v1/README.md), which predates the final extension.
