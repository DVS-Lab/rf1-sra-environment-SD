#!/usr/bin/env bash
set -euo pipefail
umask 0000
cd "$(dirname "${BASH_SOURCE[0]}")/.."
UPSTREAM=/ZPOOL/data/projects/rf1-sra-linux2
PYTHON="$PWD/work/venv-katie/bin/python"
JOBS=24
STAMP="katie-overnight-$(date +%Y%m%d-%H%M%S)"
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
RANDOMISE=$(command -v randomise) || { echo "ERROR: randomise not found under FSLDIR=$FSLDIR" >&2; exit 1; }
export FSLOUTPUTTYPE=NIFTI_GZ PYTHONUNBUFFERED=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1

echo "STAGE INPUT BUILD/CHECK; N=97; existing inputs and completed results are preserved"
bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-inputs" --include-full-log -- \
  "$PYTHON" code/run_katie_randomise.py build --randomise "$RANDOMISE" \
  --check "$PYTHON" code/run_katie_randomise.py check --randomise "$RANDOMISE"
python3 "$UPSTREAM/code/publish_run_logs.py" --project "$UPSTREAM"

echo "STAGE OVERNIGHT RUN; smoke test must pass before 24 full jobs start"
bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-randomise" --include-full-log -- \
  "$PYTHON" code/run_katie_randomise.py run --randomise "$RANDOMISE" --jobs "$JOBS" \
  --check "$PYTHON" code/run_katie_randomise.py check-results --randomise "$RANDOMISE"
echo "KATIE COMPLETE: final verification passed; publishing logs"
