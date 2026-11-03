#!/usr/bin/env bash
set -euo pipefail
umask 0000
JOBS=24
while [[ $# -gt 0 ]]; do
  case "$1" in --jobs) JOBS=${2:?Missing worker count}; shift 2;; *) echo "Unknown argument: $1"; exit 1;; esac
done
[[ "$JOBS" =~ ^[0-9]+$ && "$JOBS" -ge 1 && "$JOBS" -le 48 ]] || { echo "Use --jobs 1..48"; exit 1; }
PROJECT=$(pwd -P)
REV=$(git rev-parse FETCH_HEAD)
RELEASE="$PROJECT/work/katie-review-release-${REV:0:12}"
mkdir -p "$PROJECT/work" "$PROJECT/logs/runs"
if [[ ! -d "$RELEASE" ]]; then
  STAGE=$(mktemp -d "$PROJECT/work/.katie-review-release.XXXXXX"); chmod 0777 "$STAGE"
  git archive "$REV" code data config | tar -x -C "$STAGE"
  mv "$STAGE" "$RELEASE"
fi
STAMP=katie-review-$(date +%Y%m%d-%H%M%S)
LOG="$PROJECT/logs/runs/$STAMP.nohup.out"
nohup setsid -f -w bash "$RELEASE/code/run_katie_review.sh" "$PROJECT" "$RELEASE" "$JOBS" "$STAMP" > "$LOG" 2>&1 &
echo "LAUNCHED read-only audit/figures: $LOG"
sleep 5
tail -30 "$LOG"
