#!/usr/bin/env bash
set -euo pipefail
umask 0000
if [[ ${1:-} == --worker ]]; then
  PROJECT=${2:?}; RELEASE=${3:?}; STAMP=${4:?}
  UPSTREAM=/ZPOOL/data/projects/rf1-sra-linux2
  mkdir -p "$PROJECT/work/fevs-vs-fixed-roi-mspss-v1" "$PROJECT/work/katie-review-cache/matplotlib"
  exec 9>"$PROJECT/work/fevs-vs-fixed-roi-mspss-v1/.coordinator.lock"
  flock -n 9 || { echo 'STOP: fixed-region extraction is already active.'; exit 1; }
  trap 'python3 "$UPSTREAM/code/publish_run_logs.py" --project "$UPSTREAM" || echo "Run-log publication failed; aggregate publication has its own status above."' EXIT
  cd "$RELEASE"
  [[ -f tests/test_fevs_vs_fixed_roi_support.py ]] || { echo 'STOP: frozen release is missing its extraction tests; fetch the corrected launcher.'; exit 1; }
  export PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
  export MPLCONFIGDIR="$PROJECT/work/katie-review-cache/matplotlib"
  REQ=$(sha256sum code/requirements-review.txt | cut -c1-12)
  PYTHON="$PROJECT/work/venv-katie-review-$REQ/bin/python"
  [[ -x "$PYTHON" ]] || { echo "STOP: completed closeout review environment missing: $PYTHON"; exit 1; }
  bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-tests" --include-full-log -- \
    "$PYTHON" -m unittest discover -s tests -p test_fevs_vs_fixed_roi_support.py -v
  bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-extract" --include-full-log -- \
    "$PYTHON" code/review_fevs_vs_fixed_roi_support.py build --project "$PROJECT" \
    --check "$PYTHON" code/review_fevs_vs_fixed_roi_support.py check --project "$PROJECT"
  bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-publish" --include-full-log -- \
    "$PYTHON" code/publish_katie_review.py --project "$PROJECT" \
    --report "$PROJECT/work/fevs-vs-fixed-roi-mspss-v1/report" --destination results/review/fevs-vs-fixed-roi-mspss-v1
  echo 'FIXED-ROI COMPARISON PUBLISHED. No new permutations or imaging analyses were run.'
  cat "$PROJECT/work/fevs-vs-fixed-roi-mspss-v1/report/coefficients.tsv"
  exit 0
fi
[[ $# -eq 0 ]] || { echo 'Usage: launch_fevs_vs_fixed_roi_support.sh'; exit 1; }
PROJECT=$(pwd -P); REV=$(git rev-parse FETCH_HEAD)
mkdir -p "$PROJECT/work" "$PROJECT/logs/runs"
RELEASE="$PROJECT/work/fevs-vs-fixed-roi-release-${REV:0:12}"
if [[ ! -d "$RELEASE" ]]; then
  STAGE=$(mktemp -d "$PROJECT/work/.fevs-vs-fixed-roi-release.XXXXXX"); chmod 0777 "$STAGE"
  git archive "$REV" code data config tests results/review/katie-closeout-analysis-v1 | tar -x -C "$STAGE"
  mv "$STAGE" "$RELEASE"
fi
[[ -f "$RELEASE/tests/test_fevs_vs_fixed_roi_support.py" ]] || { echo 'STOP: incomplete frozen release; fetch the corrected launcher. Existing files are preserved.'; exit 1; }
STAMP=fevs-vs-fixed-roi-$(date +%Y%m%d-%H%M%S)
LOG="$PROJECT/logs/runs/$STAMP.nohup.out"
nohup setsid -f -w bash "$RELEASE/code/launch_fevs_vs_fixed_roi_support.sh" --worker "$PROJECT" "$RELEASE" "$STAMP" > "$LOG" 2>&1 &
echo "LAUNCHED: $LOG"
echo 'Detached read-only fixed-region extraction; no permutations. Aggregate estimates and logs publish automatically.'
sleep 5
tail -30 "$LOG"
