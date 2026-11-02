#!/usr/bin/env bash
# Run via `bash <(git show FETCH_HEAD:code/launch_financial_followup.sh) MODE`.
set -euo pipefail
umask 0000
MODE=${1:-moderation}
PROJECT=$(pwd -P)
[[ "$MODE" == predictors || "$MODE" == moderation || "$MODE" == moderation-concurrent || "$MODE" == status ]] || {
  echo "Usage: launch_financial_followup.sh [predictors|moderation|moderation-concurrent|status]"; exit 1;
}
echo "=== Current financial coordinators ==="
pgrep -u "$USER" -af '[p]ython[^ ]* .*code/run_financial_(models|moderation)\.py' || true
echo "=== Recent financial logs ==="
python3 - "$PROJECT" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
for pattern in ("katie-financial-*.nohup.out", "katie-moderation-*.nohup.out"):
    paths = list((root / "logs/runs").glob(pattern))
    if paths:
        path = max(paths, key=lambda p: p.stat().st_mtime)
        print(path, flush=True)
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - 12000))
            print("\n".join(stream.read().decode(errors="replace").splitlines()[-20:]))
PY
[[ "$MODE" != status ]] || exit 0
if [[ "$MODE" == predictors ]]; then
  SCRIPT=run_financial_models; LABEL=katie-financial
else
  SCRIPT=run_financial_moderation; LABEL=katie-moderation
fi
if [[ "$MODE" != moderation-concurrent ]] && pgrep -u "$USER" -af "[r]un_financial_$( [[ "$MODE" == predictors ]] && echo models || echo moderation )\.(py|sh)( |$)"; then
  echo "Already active: preserving it; no second launcher started."
  exit 0
fi
REV=$(git rev-parse FETCH_HEAD)
git cat-file -e "$REV:code/$SCRIPT.sh"
RELEASE="$PROJECT/work/financial-followup-${REV:0:12}"
mkdir -p "$PROJECT/work" "$PROJECT/logs/runs"
if [[ ! -d "$RELEASE" ]]; then
  STAGE=$(mktemp -d "$PROJECT/work/.financial-followup.XXXXXX")
  chmod 0777 "$STAGE"
  git archive "$REV" code data config | tar -x -C "$STAGE"
  mv "$STAGE" "$RELEASE"
fi
[[ -x "$PROJECT/work/venv-katie/bin/python" ]] || { echo "Missing existing Katie environment; stopped."; exit 1; }
STAMP="$LABEL-$(date +%Y%m%d-%H%M%S)"
LOG="$PROJECT/logs/runs/$STAMP.nohup.out"
EXTRA=()
if [[ "$MODE" == moderation-concurrent ]]; then
  UPSTREAM=/ZPOOL/data/projects/rf1-sra-linux2
  bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-unqueue" --include-full-log -- \
    "$PROJECT/work/venv-katie/bin/python" "$RELEASE/code/unqueue_financial_moderation.py" --project "$PROJECT"
  python3 "$UPSTREAM/code/publish_run_logs.py" --project "$UPSTREAM"
  EXTRA+=(concurrent)
fi
nohup setsid -f -w bash "$RELEASE/code/$SCRIPT.sh" "$PROJECT" "$STAMP" "${EXTRA[@]}" > "$LOG" 2>&1 &
echo "LAUNCHED: $LOG"
sleep 5
tail -30 "$LOG"
