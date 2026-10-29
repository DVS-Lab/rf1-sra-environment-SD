#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"

# Build repository-local L3 artifacts from the public-safe fixed analysis file
# and the validated imaging handoff on the Linux analysis machine.
source "${SCRIPT_DIR}/project_config.sh"

session="01"
analysis_file="${ANALYSIS_FILE:-${PROJECT_ROOT}/data/derived/SD_analysis_data_2026-10-26.xlsx}"
helper="${SCRIPT_DIR}/build_L3_covariates.py"
monetary_inputs="${HANDOFF_ROOT}/doors/selected_inputs.tsv"

l3_dir="${PROJECT_ROOT}/data/derived/l3"
mkdir -p "$l3_dir"
subjects_file="${SCRIPT_DIR}/L3-act-subjects.txt"
paths_file="${l3_dir}/L3-act-input-paths.txt"
selected_file="${SCRIPT_DIR}/L3-act-selected-inputs.tsv"
final_qc_file="${SCRIPT_DIR}/L3-act-final-qc.csv"
covariates_file="${SCRIPT_DIR}/L3-act-covariates.xlsx"
exclusions_file="${SCRIPT_DIR}/L3-act-exclusions.tsv"

for required in "$analysis_file" "$SELECTED_INPUTS" "$monetary_inputs" "$RUN_DECISIONS" "$helper"; do
    [[ -r "$required" ]] || {
        echo "ERROR: required input is not readable: $required" >&2
        exit 1
    }
done

[[ -d "$BIDS_ROOT" ]] || {
    echo "ERROR: BIDS root not found: $BIDS_ROOT" >&2
    exit 1
}

python3 -c 'import openpyxl' >/dev/null 2>&1 || {
    echo "ERROR: Python package 'openpyxl' is required." >&2
    exit 1
}

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

python3 "$helper" inputs \
    --analysis "$analysis_file" \
    --selected-inputs "$SELECTED_INPUTS" \
    --run-decisions "$RUN_DECISIONS" \
    --subjects-output "${tmpdir}/subjects.txt" \
    --selected-output "${tmpdir}/selected-inputs.tsv" \
    --final-qc-output "${tmpdir}/final-qc.csv" \
    --exclusions-output "${tmpdir}/exclusions.tsv"

python3 "$helper" workbook \
    --analysis "$analysis_file" \
    --subjects "${tmpdir}/subjects.txt" \
    --final-qc "${tmpdir}/final-qc.csv" \
    --bids-root "$BIDS_ROOT" \
    --output "${tmpdir}/covariates.xlsx"

subject_n="$(wc -l < "${tmpdir}/subjects.txt")"
selected_n="$(awk 'NR > 1 {print $1}' "${tmpdir}/selected-inputs.tsv" | sort -u | wc -l)"
[[ "$subject_n" -eq "$selected_n" ]] || {
    echo "ERROR: subject and selected-input participant counts do not match." >&2
    exit 1
}

# Keep the historical one-path-per-subject file used by the L3 template.
# TASK is replaced with socialdoors or doors and COPENUM with the cope number
# by L3stats.sh.
awk -F '\t' '
NR == 1 {
    for (column = 1; column <= NF; column++) header[$column] = column
    next
}
$(header["contrast"]) == 1 {
    path = $(header["cope"])
    sub(/cope[0-9]+\.nii\.gz$/, "copeCOPENUM.nii.gz", path)
    sub(/task-socialdoors/, "task-TASK", path)
    print path
}' "${tmpdir}/selected-inputs.tsv" > "${tmpdir}/input-paths.txt"

path_n="$(wc -l < "${tmpdir}/input-paths.txt")"
[[ "$subject_n" -eq "$path_n" ]] || {
    echo "ERROR: L3 input-path count does not match the subject count." >&2
    exit 1
}

grep -q 'task-TASK' "${tmpdir}/input-paths.txt" || {
    echo "ERROR: could not create Social/Monetary task paths." >&2
    exit 1
}

# The Katie randomise analyses are paired. Confirm that every constructed
# Monetary Doors cope-4 path is one of the validated Doors handoff rows.
paste "${tmpdir}/subjects.txt" "${tmpdir}/input-paths.txt" |
while IFS=$'\t' read -r subject input_path; do
    monetary_path="${input_path/TASK/doors}"
    monetary_path="${monetary_path/COPENUM/4}"
    printf '%s\t%s\n' "$subject" "$monetary_path"
done > "${tmpdir}/monetary-paths.tsv"

awk -F '\t' '
    NR == FNR {
        expected[$1] = $2
        next
    }
    FNR == 1 {
        for (column = 1; column <= NF; column++) header[$column] = column
        next
    }
    {
        subject = $(header["subject"])
        sub(/^sub-/, "", subject)
        if (subject in expected &&
            $(header["session"]) ~ /^(ses-)?0?1$/ &&
            tolower($(header["analysis"])) == "doors" &&
            $(header["contrast"]) == 4 &&
            $(header["cope"]) == expected[subject]) {
            found[subject] = 1
        }
    }
    END {
        failed = 0
        for (subject in expected) {
            if (!found[subject]) {
                print "ERROR: no validated Monetary Doors cope-4 input for sub-" subject > "/dev/stderr"
                failed = 1
            }
        }
        exit failed
    }
' "${tmpdir}/monetary-paths.tsv" "$monetary_inputs"

mv "${tmpdir}/subjects.txt" "$subjects_file"
mv "${tmpdir}/input-paths.txt" "$paths_file"
mv "${tmpdir}/selected-inputs.tsv" "$selected_file"
mv "${tmpdir}/final-qc.csv" "$final_qc_file"
mv "${tmpdir}/covariates.xlsx" "$covariates_file"
mv "${tmpdir}/exclusions.tsv" "$exclusions_file"

# Remove outputs created by the earlier layout after the replacement files are
# safely in place. The per-contrast manifests duplicated selected-inputs.tsv.
rm -rf -- "${l3_dir}/L3-act-contrast-inputs"
rm -f -- \
    "${l3_dir}/L3-act-subjects.txt" \
    "${l3_dir}/L3-act-selected-inputs.tsv" \
    "${l3_dir}/L3-act-final-qc.csv" \
    "${l3_dir}/L3-act-covariates.xlsx" \
    "${l3_dir}/L3-act-exclusions.tsv"

echo "Katie Social/Monetary Doors L3 inputs complete (session ${session}; n=${subject_n})."
echo "Subjects:   $subjects_file"
echo "Paths:      $paths_file"
echo "Inputs:     $selected_file"
echo "Covariates: $covariates_file"
echo "Exclusions: $exclusions_file"
