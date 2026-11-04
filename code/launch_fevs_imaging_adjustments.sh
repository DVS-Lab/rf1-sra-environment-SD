#!/usr/bin/env bash
set -euo pipefail
umask 0000

if [[ ${1:-} == --worker ]]; then
  PROJECT=${2:?Missing project}; RELEASE=${3:?Missing frozen release}; STAMP=${4:?Missing label}
  UPSTREAM=/ZPOOL/data/projects/rf1-sra-linux2
  PYTHON="$PROJECT/work/venv-katie/bin/python"
  export PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
  trap 'python3 "$UPSTREAM/code/publish_run_logs.py" --project "$UPSTREAM" || echo "Log publication failed; retry publish_run_logs.py."' EXIT
  cd "$RELEASE"
  free -h
  bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP" --include-full-log -- \
    "$PYTHON" code/run_fevs_imaging_adjustments.py run --project "$PROJECT" --jobs 18 \
    --check "$PYTHON" code/run_fevs_imaging_adjustments.py check-results --project "$PROJECT"
  REPORT="$PROJECT/derivatives/fsl/randomise/katie-fevs-adjustments-provisional-v2/report"
  bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-publish" --include-full-log -- \
    "$PYTHON" code/publish_katie_review.py --project "$PROJECT" --report "$REPORT" \
    --destination results/review/fevs-imaging-adjustments-provisional-v1
  exit 0
fi

[[ $# -eq 0 ]] || { echo "No launch arguments required; this fixed batch has 18 jobs."; exit 1; }
PROJECT=$(pwd -P)
[[ -x "$PROJECT/work/venv-katie/bin/python" ]] || { echo "STOP: existing work/venv-katie Python not found; no environment changed."; exit 1; }
REV=$(git rev-parse FETCH_HEAD)
RELEASE="$PROJECT/work/fevs-adjustments-release-${REV:0:12}"
mkdir -p "$PROJECT/work" "$PROJECT/logs/runs"
PLAN="$PROJECT/derivatives/fsl/randomise/katie-fevs-adjustments-provisional-v2/plan.json"
if [[ -f "$PLAN" ]]; then
  RELEASE=$("$PROJECT/work/venv-katie/bin/python" -c '
import json, sys
from pathlib import Path
release = Path(json.loads(Path(sys.argv[1]).read_text())["data_root"]).resolve()
work = (Path(sys.argv[2]) / "work").resolve()
if not release.is_relative_to(work) or not (release / "code/launch_fevs_imaging_adjustments.sh").is_file():
    raise SystemExit("STOP: recorded frozen release is missing or outside project/work")
print(release)
' "$PLAN" "$PROJECT")
  echo "RESUME: using recorded release $RELEASE, not newly fetched code."
elif [[ ! -d "$RELEASE" ]]; then
  STAGE=$(mktemp -d "$PROJECT/work/.fevs-adjustments-release.XXXXXX"); chmod 0777 "$STAGE"
  git archive "$REV" code data config | tar -x -C "$STAGE"
  mv "$STAGE" "$RELEASE"
fi
STAMP=fevs-imaging-adjustments-$(date +%Y%m%d-%H%M%S)
LOG="$PROJECT/logs/runs/$STAMP.nohup.out"
nohup setsid -f -w bash "$RELEASE/code/launch_fevs_imaging_adjustments.sh" --worker "$PROJECT" "$RELEASE" "$STAMP" > "$LOG" 2>&1 &
echo "LAUNCHED: $LOG"
echo "18 single-threaded jobs; fixed N=97; additive ADI/Ecog checks; completed outputs untouched."
echo "On success: aggregate tables and logs publish automatically through HTTPS Git. Scoring remains provisional."
sleep 5
tail -30 "$LOG"
