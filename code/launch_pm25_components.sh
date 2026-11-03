#!/usr/bin/env bash
set -euo pipefail
umask 0000

if [[ ${1:-} == --worker ]]; then
  PROJECT=${2:?Missing project}; RELEASE=${3:?Missing release}
  JOBS=${4:?Missing worker count}; STAMP=${5:?Missing label}
  UPSTREAM=/ZPOOL/data/projects/rf1-sra-linux2
  PYTHON="$PROJECT/work/venv-katie/bin/python"
  export PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
  trap 'python3 "$UPSTREAM/code/publish_run_logs.py" --project "$UPSTREAM" || echo "Log publication failed; run publish_run_logs.py again."' EXIT
  cd "$RELEASE"
  bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP" --include-full-log -- \
    "$PYTHON" code/run_pm25_components.py run --project "$PROJECT" --upstream "$UPSTREAM" --jobs "$JOBS" \
    --check "$PYTHON" code/run_pm25_components.py check-results --project "$PROJECT" --upstream "$UPSTREAM"
  exit 0
fi

JOBS=6
while [[ $# -gt 0 ]]; do
  case "$1" in
    --jobs) JOBS=${2:?Missing worker count}; shift 2;;
    *) echo "Unknown argument: $1"; exit 1;;
  esac
done
[[ "$JOBS" =~ ^[1-6]$ ]] || { echo "Use --jobs 1..6; there are six independent jobs."; exit 1; }
PROJECT=$(pwd -P)
[[ -x "$PROJECT/work/venv-katie/bin/python" ]] || { echo "STOP: existing work/venv-katie Python not found; no environment changed."; exit 1; }
REV=$(git rev-parse FETCH_HEAD)
RELEASE="$PROJECT/work/pm25-components-release-${REV:0:12}"
mkdir -p "$PROJECT/work" "$PROJECT/logs/runs"
if [[ ! -d "$RELEASE" ]]; then
  STAGE=$(mktemp -d "$PROJECT/work/.pm25-components-release.XXXXXX"); chmod 0777 "$STAGE"
  git archive "$REV" code data config | tar -x -C "$STAGE"
  mv "$STAGE" "$RELEASE"
fi
STAMP=pm25-components-$(date +%Y%m%d-%H%M%S)
LOG="$PROJECT/logs/runs/$STAMP.nohup.out"
nohup setsid -f -w bash "$RELEASE/code/launch_pm25_components.sh" --worker "$PROJECT" "$RELEASE" "$JOBS" "$STAMP" > "$LOG" 2>&1 &
echo "LAUNCHED six-job PM2.5 component batch: $LOG"
echo "Completed compatible jobs will be reused; original analyses and exclusions stay unchanged."
sleep 5
tail -25 "$LOG"
