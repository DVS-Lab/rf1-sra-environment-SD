#!/usr/bin/env bash
set -euo pipefail
umask 0000

if [[ ${1:-} == --worker ]]; then
  PROJECT=${2:?Missing project}; RELEASE=${3:?Missing release}
  JOBS=${4:?Missing worker count}; STAMP=${5:?Missing label}
  UPSTREAM=/ZPOOL/data/projects/rf1-sra-linux2
  PYTHON="$PROJECT/work/venv-katie/bin/python"
  export PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
  trap 'python3 "$UPSTREAM/code/publish_run_logs.py" --project "$UPSTREAM" || echo "Log publication failed; retry publish_run_logs.py."' EXIT
  cd "$RELEASE"
  echo "=== Memory before launch; jobs are single-threaded ==="
  free -h
  bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP" --include-full-log -- \
    "$PYTHON" code/run_reward_extension.py run --project "$PROJECT" --upstream "$UPSTREAM" --jobs "$JOBS" \
    --check "$PYTHON" code/run_reward_extension.py check-results --project "$PROJECT" --upstream "$UPSTREAM"
  exit 0
fi

JOBS=60
MODE=run
while [[ $# -gt 0 ]]; do
  case "$1" in
    --jobs) JOBS=${2:?Missing worker count}; shift 2;;
    --status) MODE=status; shift;;
    *) echo "Unknown argument: $1"; exit 1;;
  esac
done
[[ "$JOBS" =~ ^[0-9]+$ && "$JOBS" -ge 1 && "$JOBS" -le 60 ]] || { echo "Use --jobs 1..60"; exit 1; }
PROJECT=$(pwd -P)
[[ -x "$PROJECT/work/venv-katie/bin/python" ]] || { echo "STOP: existing work/venv-katie Python not found; no environment changed."; exit 1; }
REV=$(git rev-parse FETCH_HEAD)
RELEASE="$PROJECT/work/reward-extension-release-${REV:0:12}"
mkdir -p "$PROJECT/work" "$PROJECT/logs/runs"
if [[ ! -d "$RELEASE" ]]; then
  STAGE=$(mktemp -d "$PROJECT/work/.reward-extension-release.XXXXXX"); chmod 0777 "$STAGE"
  git archive "$REV" code data config | tar -x -C "$STAGE"
  mv "$STAGE" "$RELEASE"
fi
if [[ "$MODE" == status ]]; then
  UPSTREAM=/ZPOOL/data/projects/rf1-sra-linux2
  STAMP=reward-extension-status-$(date +%Y%m%d-%H%M%S)
  trap 'python3 "$UPSTREAM/code/publish_run_logs.py" --project "$UPSTREAM" || echo "Log publication failed; retry publish_run_logs.py."' EXIT
  bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP" --include-full-log -- \
    python3 "$RELEASE/code/snapshot_reward_extension.py" --project "$PROJECT"
  exit 0
fi
STAMP=reward-extension-$(date +%Y%m%d-%H%M%S)
LOG="$PROJECT/logs/runs/$STAMP.nohup.out"
nohup setsid -f -w bash "$RELEASE/code/launch_reward_extension.sh" --worker "$PROJECT" "$RELEASE" "$JOBS" "$STAMP" > "$LOG" 2>&1 &
echo "LAUNCHED: $LOG"
echo "220 extension jobs; 97 participants; old results preserved; six-job additive batch reused/resumed without duplication."
echo "Up to $JOBS single-threaded workers, reserving six slots while the additive helper is active."
sleep 5
tail -30 "$LOG"
