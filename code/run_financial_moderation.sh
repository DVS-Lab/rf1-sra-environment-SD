#!/usr/bin/env bash
set -euo pipefail
umask 0000
RELEASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
PROJECT=${1:?Missing canonical project}
STAMP=${2:?Missing label}
UPSTREAM=/ZPOOL/data/projects/rf1-sra-linux2
PYTHON="$PROJECT/work/venv-katie/bin/python"
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
cd "$RELEASE"
bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-inputs" --include-full-log -- \
  "$PYTHON" "$RELEASE/code/run_financial_moderation.py" --project "$PROJECT" --prepare-only
python3 "$UPSTREAM/code/publish_run_logs.py" --project "$UPSTREAM"
bash "$UPSTREAM/code/run_logged.sh" --label "$STAMP-randomise" --include-full-log -- \
  "$PYTHON" "$RELEASE/code/run_financial_moderation.py" --project "$PROJECT" --jobs 16
