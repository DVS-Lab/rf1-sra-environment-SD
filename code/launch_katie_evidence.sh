#!/usr/bin/env bash
set -euo pipefail
umask 0000

if [[ ${1:-} == --worker ]]; then
  PROJECT=${2:?Missing project}; RELEASE=${3:?Missing release}; STAMP=${4:?Missing label}
  UPSTREAM=/ZPOOL/data/projects/rf1-sra-linux2
  ANALYSIS="$PROJECT/work/venv-katie/bin/python"
  export PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
  REVIEW="$PROJECT/work/katie-evidence-v1"
  mkdir -p "$REVIEW" "$PROJECT/work/katie-review-cache/matplotlib"
  exec 9>"$REVIEW/.launcher.lock"
  flock -n 9 || { echo "STOP: evidence batch is already active; no duplicate started."; exit 1; }
  trap 'python3 "$UPSTREAM/code/publish_run_logs.py" --project "$UPSTREAM" || echo "Retry publish_run_logs.py: log publication failed."' EXIT
  cd "$RELEASE"
  NATIVE_RELEASE="$RELEASE"
  PLAN="$PROJECT/derivatives/fsl/randomise/katie-social-win-mean-v1/plan.json"
  if [[ -f "$PLAN" ]]; then
    NATIVE_RELEASE=$("$ANALYSIS" -c 'import json,sys; from pathlib import Path; p=Path(json.loads(Path(sys.argv[1]).read_text())["data_root"]).resolve(); assert p.is_relative_to((Path(sys.argv[2])/"work").resolve()); print(p)' "$PLAN" "$PROJECT")
  fi
  bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-task-mean" --include-full-log -- \
    "$ANALYSIS" "$NATIVE_RELEASE/code/run_social_win_mean.py" run --project "$PROJECT" \
    --check "$ANALYSIS" "$NATIVE_RELEASE/code/run_social_win_mean.py" check-results --project "$PROJECT"
  REQ=$(sha256sum code/requirements-review.txt | cut -c1-12)
  ENVIRONMENT="$PROJECT/work/venv-katie-review-$REQ"
  [[ -x "$ENVIRONMENT/bin/python" ]] || "$ANALYSIS" -m venv "$ENVIRONMENT"
  PYTHON="$ENVIRONMENT/bin/python"
  if [[ ! -f "$ENVIRONMENT/.requirements-complete" ]]; then
    "$PYTHON" -m pip install --no-cache-dir -r code/requirements-review.txt
    "$PYTHON" -m pip check
    touch "$ENVIRONMENT/.requirements-complete"
  fi
  export MPLCONFIGDIR="$PROJECT/work/katie-review-cache/matplotlib"
  bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-figures" --include-full-log -- \
    "$PYTHON" code/review_katie_evidence.py build --project "$PROJECT" --report "$REVIEW/report" \
    --check "$PYTHON" code/review_katie_evidence.py check --project "$PROJECT" --report "$REVIEW/report"
  bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-publish" --include-full-log -- \
    "$PYTHON" code/publish_katie_review.py --project "$PROJECT" --report "$REVIEW/report" \
    --destination results/review/katie-evidence-v1 --sync-checkout
  exit 0
fi

[[ $# -eq 0 ]] || { echo "No launch arguments required."; exit 1; }
PROJECT=$(pwd -P)
[[ -x "$PROJECT/work/venv-katie/bin/python" ]] || { echo "STOP: original analysis Python not found; nothing changed."; exit 1; }
REV=$(git rev-parse FETCH_HEAD)
RELEASE="$PROJECT/work/katie-evidence-release-${REV:0:12}"
mkdir -p "$PROJECT/work" "$PROJECT/logs/runs"
if [[ ! -d "$RELEASE" ]]; then
  STAGE=$(mktemp -d "$PROJECT/work/.katie-evidence-release.XXXXXX"); chmod 0777 "$STAGE"
  git archive "$REV" code data config | tar -x -C "$STAGE"
  mv "$STAGE" "$RELEASE"
fi
STAMP=katie-evidence-$(date +%Y%m%d-%H%M%S)
LOG="$PROJECT/logs/runs/$STAMP.nohup.out"
nohup setsid -f -w bash "$RELEASE/code/launch_katie_evidence.sh" --worker "$PROJECT" "$RELEASE" "$STAMP" > "$LOG" 2>&1 &
echo "LAUNCHED: $LOG"
echo "Only 2 new randomise jobs: missing social-win group mean at CDTs 2.6/3.1. Both signs; N=97; native sign-flip gate."
echo "Then matched brain/scatter plots, existing win-loss/double-subtraction maps and actual designs; automatic Git publication, guarded sync and log publication."
sleep 5
tail -30 "$LOG"
