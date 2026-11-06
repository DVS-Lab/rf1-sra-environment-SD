#!/usr/bin/env bash
set -euo pipefail
umask 0000

if [[ ${1:-} == --worker ]]; then
  PROJECT=${2:?Missing project}; RELEASE=${3:?Missing release}; STAMP=${4:?Missing label}; JOBS=${5:?Missing workers}
  UPSTREAM=/ZPOOL/data/projects/rf1-sra-linux2
  PYTHON="$PROJECT/work/venv-katie/bin/python"
  exec 9>"$PROJECT/work/.mspss-corrected-launch.lock"
  flock -n 9 || { echo "STOP: corrected-MSPSS launcher already active; no duplicate started."; exit 1; }
  export PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
  trap 'python3 "$UPSTREAM/code/publish_run_logs.py" --project "$UPSTREAM" || echo "Log publication failed; retry publish_run_logs.py."' EXIT
  cd "$RELEASE"
  free -h
  bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP" --include-full-log -- \
    "$PYTHON" code/run_corrected_mspss.py run --project "$PROJECT" --jobs "$JOBS" \
    --check "$PYTHON" code/run_corrected_mspss.py check-results --project "$PROJECT"
  REPORT="$PROJECT/derivatives/fsl/randomise/katie-mspss-corrected-v1/report"
  bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-publish" --include-full-log -- \
    "$PYTHON" code/publish_katie_review.py --project "$PROJECT" --report "$REPORT" \
    --destination results/review/mspss-corrected-v1 --sync-checkout
  exit 0
fi

JOBS=75
if [[ $# -ne 0 ]]; then
  [[ $# -eq 2 && $1 == --jobs && $2 =~ ^[0-9]+$ ]] || { echo "Usage: launcher [--jobs 1..80]"; exit 1; }
  JOBS=$2
fi
[[ $JOBS -ge 1 && $JOBS -le 80 ]] || { echo "Use --jobs 1..80"; exit 1; }
PROJECT=$(pwd -P)
PYTHON="$PROJECT/work/venv-katie/bin/python"
[[ -x "$PYTHON" ]] || { echo "STOP: existing work/venv-katie Python missing; no environment changed."; exit 1; }
[[ -f /ZPOOL/data/projects/rf1-sra-linux2/code/run_logged.sh ]] || { echo "STOP: Linux2 log runner missing."; exit 1; }
mkdir -p "$PROJECT/work" "$PROJECT/logs/runs"
REV=$(git rev-parse FETCH_HEAD)
RELEASE="$PROJECT/work/mspss-correction-release-${REV:0:12}"
PLAN="$PROJECT/derivatives/fsl/randomise/katie-mspss-corrected-v1/plan.json"
if [[ -f "$PLAN" ]]; then
  RELEASE=$("$PYTHON" -c '
import json, sys
from pathlib import Path
release = Path(json.loads(Path(sys.argv[1]).read_text())["data_root"]).resolve()
work = (Path(sys.argv[2]) / "work").resolve()
if not release.is_relative_to(work) or not (release / "code/launch_corrected_mspss.sh").is_file():
    raise SystemExit("STOP: recorded release missing or outside project/work; no output overwritten")
print(release)
' "$PLAN" "$PROJECT")
  echo "RESUME: recorded frozen release $RELEASE; completed corrected jobs will be verified and reused."
elif [[ ! -d "$RELEASE" ]]; then
  STAGE=$(mktemp -d "$PROJECT/work/.mspss-correction-release.XXXXXX"); chmod 0777 "$STAGE"
  git -c tar.umask=0000 archive "$REV" code data config | tar -x -C "$STAGE"
  mv "$STAGE" "$RELEASE"
fi
STAMP=mspss-corrected-$(date +%Y%m%d-%H%M%S)
LOG="$PROJECT/logs/runs/$STAMP.nohup.out"
nohup setsid -f -w bash "$RELEASE/code/launch_corrected_mspss.sh" --worker "$PROJECT" "$RELEASE" "$STAMP" "$JOBS" > "$LOG" 2>&1 &
echo "LAUNCHED: $LOG"
echo "64 single-threaded randomise jobs / 384 directional maps; worker limit $JOBS; N=97 preserved."
echo "Two native smoke tests run first; then at most 64 full jobs run concurrently."
echo "Original results, non-MSPSS models and exclusions stay untouched. Aggregate results and logs publish automatically using HTTPS Git."
sleep 5
tail -35 "$LOG"
