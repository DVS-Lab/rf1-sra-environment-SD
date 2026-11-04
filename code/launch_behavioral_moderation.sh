#!/usr/bin/env bash
set -euo pipefail
umask 0000

if [[ ${1:-} == --worker ]]; then
  PROJECT=${2:?Missing project}
  RELEASE=${3:?Missing release}
  STAMP=${4:?Missing label}
  MODE=${5:?Missing scoring mode}
  UPSTREAM=/ZPOOL/data/projects/rf1-sra-linux2
  NAME=behavioral-moderation-v1
  FLAGS=()
  if [[ "$MODE" == provisional ]]; then
    NAME=behavioral-moderation-provisional-v1
    FLAGS=(--provisional)
  fi
  ROOT="$PROJECT/work/$NAME"
  mkdir -p "$ROOT" "$PROJECT/work/katie-review-cache/matplotlib"
  exec 9>"$ROOT/.analysis.lock"
  flock -n 9 || { echo "STOP: this behavioral batch already holds its lock; nothing interrupted."; exit 1; }
  trap 'python3 "$UPSTREAM/code/publish_run_logs.py" --project "$UPSTREAM" || echo "Log publication failed; retry publish_run_logs.py."' EXIT
  export PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
  export MPLCONFIGDIR="$PROJECT/work/katie-review-cache/matplotlib"
  cd "$RELEASE"
  BASE="$PROJECT/work/venv-katie/bin/python"
  bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-scoring" --include-full-log -- \
    "$BASE" code/run_behavioral_moderation.py audit --project "$PROJECT" --root "$ROOT" "${FLAGS[@]}"
  REQ=$(sha256sum code/requirements-review.txt | cut -c1-12)
  ENVIRONMENT="$PROJECT/work/venv-katie-review-$REQ"
  if [[ ! -x "$ENVIRONMENT/bin/python" ]]; then
    "$BASE" -m venv "$ENVIRONMENT"
  fi
  PYTHON="$ENVIRONMENT/bin/python"
  if [[ ! -f "$ENVIRONMENT/.requirements-complete" ]]; then
    "$PYTHON" -m pip install --no-cache-dir -r code/requirements-review.txt
    "$PYTHON" -m pip check
    touch "$ENVIRONMENT/.requirements-complete"
  fi
  bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-models" --include-full-log -- \
    "$PYTHON" code/run_behavioral_moderation.py run --project "$PROJECT" --root "$ROOT" "${FLAGS[@]}" \
    --check "$PYTHON" code/run_behavioral_moderation.py check --project "$PROJECT" --root "$ROOT" "${FLAGS[@]}"
  bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-publish" --include-full-log -- \
    "$PYTHON" code/publish_katie_review.py --project "$PROJECT" --report "$ROOT/report" \
      --destination "results/review/$NAME"
  exit 0
fi

MODE=verified
if [[ $# -eq 1 && "$1" == --provisional ]]; then
  MODE=provisional
elif [[ $# -ne 0 ]]; then
  echo "Usage: launch_behavioral_moderation.sh [--provisional]"
  exit 1
fi
PROJECT=$(pwd -P)
[[ -x "$PROJECT/work/venv-katie/bin/python" ]] || { echo "STOP: existing work/venv-katie Python not found; nothing changed."; exit 1; }
REV=$(git rev-parse FETCH_HEAD)
RELEASE="$PROJECT/work/behavioral-moderation-release-${REV:0:12}"
mkdir -p "$PROJECT/work" "$PROJECT/logs/runs"
if [[ ! -d "$RELEASE" ]]; then
  STAGE=$(mktemp -d "$PROJECT/work/.behavioral-release.XXXXXX")
  chmod 0777 "$STAGE"
  git archive "$REV" code data config | tar -x -C "$STAGE"
  mv "$STAGE" "$RELEASE"
fi
STAMP=katie-behavioral-$MODE-$(date +%Y%m%d-%H%M%S)
LOG="$PROJECT/logs/runs/$STAMP.nohup.out"
nohup setsid -f -w bash "$RELEASE/code/launch_behavioral_moderation.sh" --worker "$PROJECT" "$RELEASE" "$STAMP" "$MODE" > "$LOG" 2>&1 &
echo "LAUNCHED: $LOG"
echo "Eight behavioral models; frozen N=97; scoring mode=$MODE. Neural jobs/outputs and exclusions untouched."
echo "Report and logs publish automatically through HTTPS Git; no pull, SSH or data transfer."
sleep 5
tail -30 "$LOG"
