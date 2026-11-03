# Targeted FEVS Win Review

This read-only report inspects the two already-completed positive FEVS **main effects**
for activation, Social Doors win minus Doors win, at cluster-defining Z-equivalent
3.1. It does not rerun randomise, preprocessing, or exclusions. The frozen cohort
remains N=97. It does not replace the full 220-job final audit.

The second effect comes from the FEVS x PM2.5 model, conditional at mean PM2.5;
it is **not** an interaction finding. Both models share the participants and images.
Cluster-selected scatterplots, analytical confidence intervals, HC3 intervals and
leave-one-out diagnostics are descriptive, not independent confirmation. All 97
participants remain in every scatter; influence does not trigger exclusions.
Mapwise cluster-FWE does not correct across the exploratory model/outcome family.

## Linux2

Run this entire block from a Linux2 terminal. It fetches over HTTPS, archives a
separate reporting release under ignored `work/`, and leaves the live checkout,
running inference and completed outputs untouched. No SSH or file transfers.

```bash
(
set -euo pipefail
umask 0000
cd /ZPOOL/data/projects/rf1-sra-environment-SD
git -c remote.origin.url=https://github.com/DVS-Lab/rf1-sra-environment-SD.git fetch origin main
bash <(git show FETCH_HEAD:code/launch_fevs_win_review.sh)
)
```

The detached nohup job captures current progress both before and after the report,
verifies the frozen source/design/result fingerprints and native completed-job
receipts, maps corrected clusters in MNI coordinates, and optionally annotates
local FSL Harvard-Oxford atlases. Missing atlases are explicitly reported, not
downloaded or guessed. No statistical images are resampled; nearest-neighbor
atlas lookup supplies approximate anatomical annotations only.

Brain views include sagittal, coronal and axial slices through the peak. Scatterplots
show raw and covariate-adjusted region estimates, plus influence diagnostics. The
adjusted conditional-model scatter removes other fitted terms, including the
interaction, to illustrate the FEVS slope at centered PM2.5=0. The report also
quantifies cluster overlap between models. The input 4D stack is loaded once.

Only the small sealed aggregate report is published, via an isolated HTTPS clone:

`results/review/fevs-win-v1/README.md`

Participant-level influence tables and the full input fingerprint ledger stay
outside the published report in `work/fevs-win-review-v1/`. No bulk NIfTI or
individual-level tables enter Git. Repeating the command verifies/reuses the
sealed report and refreshes progress without overwriting completed figures.

Run records publish automatically through Linux2's `code/publish_run_logs.py` on
exit. If that publication fails, retry:

```bash
cd /ZPOOL/data/projects/rf1-sra-linux2
umask 0000
python3 code/publish_run_logs.py --project "$PWD"
```
