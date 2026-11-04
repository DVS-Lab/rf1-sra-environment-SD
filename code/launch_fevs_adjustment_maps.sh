#!/usr/bin/env bash
set -euo pipefail
umask 0000

if [[ ${1:-} == --worker ]]; then
  PROJECT=${2:?Missing project}; RELEASE=${3:?Missing release}; STAMP=${4:?Missing label}
  UPSTREAM=/ZPOOL/data/projects/rf1-sra-linux2
  REVIEW="$PROJECT/work/fevs-adjustment-map-review-v1"
  REPORT="$REVIEW/report"
  mkdir -p "$REVIEW" "$PROJECT/work/katie-review-cache/matplotlib"
  exec 9>"$REVIEW/.launcher.lock"
  flock -n 9 || { echo "STOP: map review already running; nothing interrupted."; exit 1; }
  trap 'python3 "$UPSTREAM/code/publish_run_logs.py" --project "$UPSTREAM" || echo "Log publication failed; retry publish_run_logs.py."' EXIT
  cd "$RELEASE"
  export PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
  export MPLCONFIGDIR="$PROJECT/work/katie-review-cache/matplotlib"
  REQ=$(sha256sum code/requirements-review.txt | cut -c1-12)
  ENVIRONMENT="$PROJECT/work/venv-katie-review-$REQ"
  if [[ ! -x "$ENVIRONMENT/bin/python" ]]; then
    "$PROJECT/work/venv-katie/bin/python" -m venv "$ENVIRONMENT"
  fi
  PYTHON="$ENVIRONMENT/bin/python"
  if [[ ! -f "$ENVIRONMENT/.requirements-complete" ]]; then
    "$PYTHON" -m pip install --no-cache-dir -r code/requirements-review.txt
    "$PYTHON" -m pip check
    touch "$ENVIRONMENT/.requirements-complete"
  fi
  bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-figures" --include-full-log -- \
    "$PYTHON" code/review_fevs_adjustment_maps.py build --project "$PROJECT" --report "$REPORT" \
    --check "$PYTHON" code/review_fevs_adjustment_maps.py check --project "$PROJECT" --report "$REPORT"
  bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-publish" --include-full-log -- \
    "$PYTHON" code/publish_katie_review.py --project "$PROJECT" --report "$REPORT" \
    --destination results/review/fevs-adjustment-maps-v1 --sync-checkout
  exit 0
fi

[[ $# -eq 0 ]] || { echo "No launch arguments required."; exit 1; }
PROJECT=$(pwd -P)
[[ -x "$PROJECT/work/venv-katie/bin/python" ]] || { echo "STOP: existing analysis Python not found; no outputs changed."; exit 1; }
REV=$(git rev-parse FETCH_HEAD)
RELEASE="$PROJECT/work/fevs-map-review-release-${REV:0:12}"
mkdir -p "$PROJECT/work" "$PROJECT/logs/runs"
if [[ ! -d "$RELEASE" ]]; then
  STAGE=$(mktemp -d "$PROJECT/work/.fevs-map-review-release.XXXXXX"); chmod 0777 "$STAGE"
  git archive "$REV" code data config | tar -x -C "$STAGE"
  mv "$STAGE" "$RELEASE"
fi
STAMP=fevs-adjustment-maps-$(date +%Y%m%d-%H%M%S)
LOG="$PROJECT/logs/runs/$STAMP.nohup.out"
nohup setsid -f -w bash "$RELEASE/code/launch_fevs_adjustment_maps.sh" --worker "$PROJECT" "$RELEASE" "$STAMP" > "$LOG" 2>&1 &
echo "LAUNCHED: $LOG"
echo "Read-only original/adjusted FEVS anatomy review; N=97; no randomise or preprocessing."
echo "Three fixed-slice panels, cluster overlap, peak shifts and available atlas labels; results and logs publish automatically through Git."
sleep 5
tail -30 "$LOG"
