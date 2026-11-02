#!/usr/bin/env bash
set -euo pipefail
umask 0000
cd "$(dirname "${BASH_SOURCE[0]}")/.."
UPSTREAM=/ZPOOL/data/projects/rf1-sra-linux2
PYTHON="$PWD/work/venv-katie/bin/python"
JOBS=48
STAMP="katie-all-$(date +%Y%m%d-%H%M%S)"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --jobs) JOBS=${2:?Missing jobs}; shift 2 ;;
    --label) STAMP=${2:?Missing label}; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
trap 'python3 "$UPSTREAM/code/publish_run_logs.py" --project "$UPSTREAM" || true' EXIT
export FSLDIR=${FSLDIR:-/usr/local/fsl}
if [[ -f "$FSLDIR/etc/fslconf/fsl.sh" ]]; then
  set +u
  source "$FSLDIR/etc/fslconf/fsl.sh"
  set -u
fi
umask 0000
export PATH="$FSLDIR/share/fsl/bin:$FSLDIR/bin:$PATH"
export FSLOUTPUTTYPE=NIFTI_GZ PYTHONUNBUFFERED=1 FSLSUB_PARALLEL=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
for executable in randomise feat fslmeants fslnvols; do
  command -v "$executable" >/dev/null || { echo "Missing FSL command: $executable" >&2; exit 1; }
done
bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-inputs" --include-full-log -- \
  "$PYTHON" code/run_katie_remaining.py --jobs "$JOBS" --prepare-only
python3 "$UPSTREAM/code/publish_run_logs.py" --project "$UPSTREAM"
bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP" --include-full-log -- \
  "$PYTHON" code/run_katie_remaining.py --jobs "$JOBS"
echo "KATIE REMAINING ANALYSES COMPLETE; reports are under results/randomise/katie-remaining-v1 and katie-main-effects-v1."
