#!/usr/bin/env bash
set -euo pipefail
umask 0000

if [[ ${1:-} == --worker ]]; then
  PROJECT=${2:?}; RELEASE=${3:?}; STAMP=${4:?}
  UPSTREAM=/ZPOOL/data/projects/rf1-sra-linux2
  mkdir -p "$PROJECT/work/katie-review-cache/matplotlib"
  exec 9>"$PROJECT/work/.katie-targeted-v1.lock"
  flock -n 9 || { echo 'STOP: the targeted follow-up coordinator is already active.'; exit 1; }
  trap 'python3 "$UPSTREAM/code/publish_run_logs.py" --project "$UPSTREAM" || echo "Run-log publication failed; retry the log publisher."' EXIT
  cd "$RELEASE"
  export PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
  export MPLCONFIGDIR="$PROJECT/work/katie-review-cache/matplotlib"
  REQ=$(sha256sum code/requirements-review.txt | cut -c1-12)
  PYTHON="$PROJECT/work/venv-katie-review-$REQ/bin/python"
  [[ -x "$PYTHON" ]] || { echo "STOP: existing closeout environment missing: $PYTHON"; exit 1; }
  bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-tests" --include-full-log -- \
    "$PYTHON" -m unittest discover -s tests -p test_katie_targeted.py -v
  bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-native" --include-full-log -- \
    "$PYTHON" code/review_katie_targeted.py build --kind native --project "$PROJECT" \
    --check "$PYTHON" code/review_katie_targeted.py check --kind native --project "$PROJECT"
  bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-publish" --include-full-log -- \
    "$PYTHON" code/publish_katie_review.py --project "$PROJECT" \
    --report "$PROJECT/work/katie-targeted-native-v1/report" --destination results/review/katie-targeted-native-v1
  exit 0
fi

[[ $# -eq 0 ]] || { echo 'Usage: launch_katie_targeted.sh'; exit 1; }
PROJECT=$(pwd -P)
REV=$(git rev-parse FETCH_HEAD)
mkdir -p "$PROJECT/work" "$PROJECT/logs/runs"
RELEASE="$PROJECT/work/katie-targeted-release-${REV:0:12}"
if [[ ! -d "$RELEASE" ]]; then
  STAGE=$(mktemp -d "$PROJECT/work/.katie-targeted-release.XXXXXX"); chmod 0777 "$STAGE"
  git -c tar.umask=0000 archive "$REV" code data config tests \
    results/review/katie-results-ready-v1 results/review/behavioral-mspss-corrected-provisional-v1 | tar -x -C "$STAGE"
  mv -T "$STAGE" "$RELEASE"
fi
STAMP=katie-targeted-$(date +%Y%m%d-%H%M%S)-$$
LOG="$PROJECT/logs/runs/$STAMP.nohup.out"
nohup setsid -f -w bash "$RELEASE/code/launch_katie_targeted.sh" --worker "$PROJECT" "$RELEASE" "$STAMP" > "$LOG" 2>&1 &
echo "LAUNCHED: $LOG"
echo 'Read-only native extraction and overlap; no randomise jobs. Validated aggregates and logs publish automatically via HTTPS.'
