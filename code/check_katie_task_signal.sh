#!/usr/bin/env bash
set -euo pipefail
umask 0000
cd "$(dirname "${BASH_SOURCE[0]}")/.."
UPSTREAM=/ZPOOL/data/projects/rf1-sra-linux2
PYTHON="$PWD/work/venv-katie/bin/python"
STAMP="katie-task-signal-$(date +%Y%m%d-%H%M%S)"
STATUS=0
bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-outcome" --include-full-log -- \
  "$PYTHON" code/audit_katie_outcome.py || STATUS=$?
# Inventory/descriptive checks remain useful if a separate timing audit fails.
bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-VS-inventory" --include-full-log -- \
  "$PYTHON" code/inspect_katie_activation.py || STATUS=$?
python3 "$UPSTREAM/code/publish_run_logs.py" --project "$UPSTREAM"

REPORTS=()
for folder in results/validation/outcome-phase-v2 results/validation/activation-connectivity-v1; do
  if [[ -d "$folder" ]]; then
    git add -- "$folder"
    REPORTS+=("$folder")
  fi
done
if (( ${#REPORTS[@]} )); then
  if ! git diff --cached --quiet -- "${REPORTS[@]}"; then
    git commit -m "Publish Katie outcome audit, descriptive VS signal and PPI inventory" -- "${REPORTS[@]}"
  fi
  git push origin main
fi
echo "Read-only task-signal checks exit: $STATUS; no L1, PPI or randomise jobs launched."
exit "$STATUS"
