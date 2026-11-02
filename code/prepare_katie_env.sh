#!/usr/bin/env bash
set -euo pipefail
umask 0000
cd "$(dirname "${BASH_SOURCE[0]}")/.."
BASE=/ZPOOL/data/tools/anaconda/tug87422/envs/tedana-26.0.3/bin/python
ENV="$PWD/work/venv-katie"
[[ -x "$BASE" ]] || { echo "Required existing Python not found: $BASE" >&2; exit 1; }
if [[ ! -x "$ENV/bin/python" ]]; then
  "$BASE" -m venv --system-site-packages "$ENV"
fi
if ! "$ENV/bin/python" -c 'import numpy, pandas, nibabel, scipy, openpyxl'; then
  "$ENV/bin/python" -m pip install -r code/requirements-katie.txt
fi
"$ENV/bin/python" -c 'import sys, numpy, pandas, nibabel, scipy, openpyxl; assert sys.version_info >= (3,11); print("KATIE ENV READY:",sys.executable); print("numpy",numpy.__version__,"pandas",pandas.__version__,"nibabel",nibabel.__version__,"scipy",scipy.__version__,"openpyxl",openpyxl.__version__)'
