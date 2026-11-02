#!/usr/bin/env bash
set -euo pipefail
umask 0000
cd "$(dirname "${BASH_SOURCE[0]}")/.."
UPSTREAM=/ZPOOL/data/projects/rf1-sra-linux2
PYTHON="$PWD/work/venv-katie/bin/python"
JOBS=16
STAMP="katie-main-effects-$(date +%Y%m%d-%H%M%S)"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --jobs) JOBS=${2:?Missing jobs}; shift 2 ;;
    --label) STAMP=${2:?Missing label}; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
[[ -x "$PYTHON" ]] || { echo "Run bash code/prepare_katie_env.sh first" >&2; exit 1; }
trap 'python3 "$UPSTREAM/code/publish_run_logs.py" --project "$UPSTREAM" || true' EXIT
export FSLDIR=${FSLDIR:-/usr/local/fsl}
if [[ -f "$FSLDIR/etc/fslconf/fsl.sh" ]]; then
  set +u
  source "$FSLDIR/etc/fslconf/fsl.sh"
  set -u
fi
umask 0000
export PATH="$FSLDIR/share/fsl/bin:$FSLDIR/bin:$PATH"
export FSLOUTPUTTYPE=NIFTI_GZ PYTHONUNBUFFERED=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1

bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-outcome-audit" --include-full-log -- \
  "$PYTHON" code/audit_katie_outcome.py
python3 "$UPSTREAM/code/publish_run_logs.py" --project "$UPSTREAM"
bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-inputs" --include-full-log -- \
  "$PYTHON" code/run_katie_main_effects.py build \
  --check "$PYTHON" code/run_katie_main_effects.py check
python3 "$UPSTREAM/code/publish_run_logs.py" --project "$UPSTREAM"
bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-randomise" --include-full-log -- \
  "$PYTHON" code/run_katie_main_effects.py run --jobs "$JOBS" \
  --check "$PYTHON" code/run_katie_main_effects.py check-results
echo "KATIE MAIN EFFECTS COMPLETE: all 16 jobs / 64 maps and text summaries verified."
