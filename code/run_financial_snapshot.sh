#!/usr/bin/env bash
set -euo pipefail
umask 0000
RELEASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
PROJECT=$(pwd -P)
UPSTREAM=/ZPOOL/data/projects/rf1-sra-linux2
STAMP=financial-snapshot-$(date +%Y%m%d-%H%M%S)
REPORT="$PROJECT/results/progress/$STAMP"
trap 'python3 "$UPSTREAM/code/publish_run_logs.py" --project "$UPSTREAM" || true' EXIT
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP" --include-full-log -- \
  "$PROJECT/work/venv-katie/bin/python" "$RELEASE/code/snapshot_financial_results.py" \
  --project "$PROJECT" --report "$REPORT"
