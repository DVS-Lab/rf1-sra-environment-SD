#!/usr/bin/env bash
# Only group maps may enter Git. Individual ROI tables and editable scatter stay under work/.
set -euo pipefail
umask 0000
repo=/ZPOOL/data/projects/rf1-sra-environment-SD
upstream=/ZPOOL/data/projects/rf1-sra-linux2
url=https://github.com/DVS-Lab/rf1-sra-environment-SD.git
cd "$repo"
kit=publication/figures-v1
[[ $(git branch --show-current) == main ]] || { echo 'Stop: expected main.'; exit 1; }
git diff --quiet && git diff --cached --quiet || { echo 'Stop: inspect existing tracked edits first.'; exit 1; }
req=$(sha256sum code/requirements-review.txt | cut -c1-12)
py="$repo/work/venv-katie-review-$req/bin/python"
[[ -x "$py" ]] || { echo "Missing review interpreter: $py"; exit 1; }
export MPLBACKEND=Agg MPLCONFIGDIR="$repo/work/katie-review-cache/matplotlib"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
exec 9>"$repo/work/.figure-sources-v1.lock"
flock -n 9 || { echo 'Stop: another figure export is active.'; exit 1; }
trap 'python3 "$upstream/code/publish_run_logs.py" --project "$upstream" || echo "Log publication failed; rerun publish_run_logs.py."' EXIT
bash "$upstream/code/run_logged.sh" --label "katie-figure-sources-$(date +%Y%m%d-%H%M%S)" --include-full-log -- \
  "$py" "$kit/export_linux2.py" --check "$py" "$kit/export_linux2.py"

src=work/katie-figure-sources-v1/group-maps
dst="$kit/group-maps"
mkdir -p "$dst"
files=("$src"/Fig[234]_*_mask.nii.gz "$src"/Fig[234]_*_signed-t.nii.gz "$src/maps.tsv")
[[ ${#files[@]} == 25 ]] || { echo 'Stop: unexpected group payload.'; exit 1; }
paths=()
for f in "${files[@]}"; do
  target="$dst/${f##*/}"
  if [[ -e "$target" ]]; then
    cmp -s "$f" "$target" || { echo "Stop: preserving differing $target"; exit 1; }
  else
    cp -- "$f" "$target"
  fi
  paths+=("$target")
done
git add -- "${paths[@]}"
if ! git diff --cached --quiet -- "${paths[@]}"; then
  git commit --only -m 'Publish validated group-level figure masks and signed t maps' -- "${paths[@]}"
fi
git push "$url" HEAD:main
echo "Published group files: $repo/$dst"
echo "Lab-only extractions and editable Fig2B: $repo/work/katie-figure-sources-v1/extractions/"
