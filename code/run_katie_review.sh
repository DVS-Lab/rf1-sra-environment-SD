#!/usr/bin/env bash
set -euo pipefail
umask 0000
PROJECT=${1:?Missing canonical project}
RELEASE=${2:?Missing frozen release}
JOBS=${3:-24}
STAMP=${4:?Missing label}
UPSTREAM=/ZPOOL/data/projects/rf1-sra-linux2
ROOT="$PROJECT/work/katie-review-v1"
REPORT="$ROOT/report"
mkdir -p "$ROOT" "$PROJECT/work/katie-review-cache/matplotlib"
exec 9>"$ROOT/.review.lock"
flock -n 9 || { echo "STOP: a review is already running; no duplicate started."; exit 1; }
trap 'python3 "$UPSTREAM/code/publish_run_logs.py" --project "$UPSTREAM" || true' EXIT
export MPLCONFIGDIR="$PROJECT/work/katie-review-cache/matplotlib"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 PYTHONUNBUFFERED=1
REQ=$(sha256sum "$RELEASE/code/requirements-review.txt" | cut -c1-12)
ENVIRONMENT="$PROJECT/work/venv-katie-review-$REQ"
if [[ ! -x "$ENVIRONMENT/bin/python" ]]; then
  "$PROJECT/work/venv-katie/bin/python" -m venv "$ENVIRONMENT"
fi
PYTHON="$ENVIRONMENT/bin/python"
if [[ ! -f "$ENVIRONMENT/.requirements-complete" ]]; then
  "$PYTHON" -m pip install --no-cache-dir -r "$RELEASE/code/requirements-review.txt"
  "$PYTHON" -m pip check
  touch "$ENVIRONMENT/.requirements-complete"
fi
BACKGROUND="${TEMPLATEFLOW_HOME:-$HOME/.cache/templateflow}/tpl-MNI152NLin6Asym/tpl-MNI152NLin6Asym_res-02_T1w.nii.gz"
if [[ ! -f "$BACKGROUND" ]]; then
  BACKGROUND="${FSLDIR:-/usr/local/fsl}/data/standard/MNI152_T1_2mm.nii.gz"
fi
[[ -f "$BACKGROUND" ]] || { echo "STOP: no local MNI anatomical background; no template downloaded or guessed."; exit 1; }
cd "$RELEASE"
if [[ ! -f "$REPORT/review_manifest.json" ]]; then
  bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-audit" --include-full-log -- \
    "$PYTHON" code/audit_katie_results.py --project "$PROJECT" --report "$REPORT" --jobs "$JOBS"
  bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-figures" --include-full-log -- \
    "$PYTHON" code/plot_katie_results.py build --project "$PROJECT" --report "$REPORT" \
      --details "$ROOT/participant-diagnostics" --background "$BACKGROUND" --jobs "$JOBS"
fi
bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-check" --include-full-log -- \
  "$PYTHON" code/plot_katie_results.py check --project "$PROJECT" --report "$REPORT" --jobs "$JOBS"
bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-publish" --include-full-log -- \
  "$PYTHON" code/publish_katie_review.py --project "$PROJECT" --report "$REPORT"
