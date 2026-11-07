#!/usr/bin/env bash
set -euo pipefail
umask 0000
if [[ ${1:-} == --worker ]]; then
  PROJECT=${2:?Missing project}; RELEASE=${3:?Missing release}; STAMP=${4:?Missing label}
  UPSTREAM=/ZPOOL/data/projects/rf1-sra-linux2
  BASE="$PROJECT/work/venv-katie/bin/python"
  mkdir -p "$PROJECT/work/katie-results-ready-v1" "$PROJECT/work/katie-review-cache/matplotlib"
  exec 9>"$PROJECT/work/katie-results-ready-v1/.coordinator.lock"
  flock -n 9 || { echo 'STOP: closeout coordinator already active; nothing interrupted.'; exit 1; }
  trap 'python3 "$UPSTREAM/code/publish_run_logs.py" --project "$UPSTREAM" || echo "Run-log publication failed; retry publish_run_logs.py."' EXIT
  export PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
  export MPLCONFIGDIR="$PROJECT/work/katie-review-cache/matplotlib"
  cd "$RELEASE"
  REQ=$(sha256sum code/requirements-review.txt | cut -c1-12)
  ENVIRONMENT="$PROJECT/work/venv-katie-review-$REQ"
  [[ -x "$ENVIRONMENT/bin/python" ]] || "$BASE" -m venv "$ENVIRONMENT"
  PYTHON="$ENVIRONMENT/bin/python"
  if [[ ! -f "$ENVIRONMENT/.requirements-complete" ]]; then
    "$PYTHON" -m pip install --no-cache-dir -r code/requirements-review.txt
    "$PYTHON" -m pip check
    touch "$ENVIRONMENT/.requirements-complete"
  fi
  bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-tests" --include-full-log -- \
    "$PYTHON" -m unittest discover -s tests -p test_katie_closeout.py -v
  bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-regression-corrected" --include-full-log -- \
    "$PYTHON" -m unittest discover -s tests -p test_corrected_mspss.py -v
  bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-regression-adjustments" --include-full-log -- \
    "$PYTHON" -m unittest discover -s tests -p test_fevs_imaging_adjustments.py -v
  bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-source-publish" --include-full-log -- \
    "$BASE" code/publish_katie_closeout_sources.py --project "$PROJECT" --release "$RELEASE"
  bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-sensitivity" --include-full-log -- \
    "$BASE" code/run_katie_support_sensitivity.py run --project "$PROJECT" \
    --check "$BASE" code/run_katie_support_sensitivity.py check-results --project "$PROJECT"
  bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-descriptions" --include-full-log -- \
    "$PYTHON" code/review_katie_closeout.py build --project "$PROJECT" \
    --check "$PYTHON" code/review_katie_closeout.py check --project "$PROJECT"
  bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-evidence-publish" --include-full-log -- \
    "$PYTHON" code/publish_katie_review.py --project "$PROJECT" --report "$PROJECT/work/katie-results-ready-v1/report" \
    --destination results/review/katie-closeout-analysis-v1
  echo 'ANALYSIS EVIDENCE PUBLISHED. PDF assembly/visual review is the next reporting step; no more permutation jobs are planned.'
  exit 0
fi
[[ $# -eq 0 ]] || { echo 'Usage: launch_katie_closeout.sh'; exit 1; }
PROJECT=$(pwd -P)
BASE="$PROJECT/work/venv-katie/bin/python"
[[ -x "$BASE" ]] || { echo 'STOP: original analysis Python missing.'; exit 1; }
mkdir -p "$PROJECT/work" "$PROJECT/logs/runs"
PLAN="$PROJECT/derivatives/fsl/randomise/katie-vs-fevs-support-sensitivity-v1/plan.json"
if [[ -f "$PLAN" ]]; then
  RELEASE=$("$BASE" -c 'import json,sys;from pathlib import Path;p=Path(json.loads(Path(sys.argv[1]).read_text())["data_root"]).resolve();assert p.is_relative_to((Path(sys.argv[2])/"work").resolve());assert (p/"code/launch_katie_closeout.sh").is_file();print(p)' "$PLAN" "$PROJECT")
else
  REV=$(git rev-parse FETCH_HEAD)
  RELEASE="$PROJECT/work/katie-closeout-release-${REV:0:12}"
  if [[ ! -d "$RELEASE" ]]; then
    STAGE=$(mktemp -d "$PROJECT/work/.katie-closeout-release.XXXXXX");chmod 0777 "$STAGE"
    git archive "$REV" | tar -x -C "$STAGE"
    mv "$STAGE" "$RELEASE"
  fi
fi
STAMP=katie-closeout-$(date +%Y%m%d-%H%M%S)
LOG="$PROJECT/logs/runs/$STAMP.nohup.out"
nohup setsid -f -w bash "$RELEASE/code/launch_katie_closeout.sh" --worker "$PROJECT" "$RELEASE" "$STAMP" > "$LOG" 2>&1 &
echo "LAUNCHED: $LOG"
echo 'Only two new scientific randomise jobs (four signed/CDT maps); all selected-cluster follow-ups are descriptive.'
echo 'Frozen N=97, original masks/images/covariates and completed inference are preserved. Source, evidence and logs publish automatically.'
sleep 5
tail -35 "$LOG"
