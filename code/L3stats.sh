#!/bin/bash

# This script performs the two paired Social/Monetary Doors Level 3 tests.

set -euo pipefail

scriptdir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
maindir="$(dirname "$scriptdir")"
l3dir="${maindir}/data/derived/l3"

subjects=${scriptdir}/L3-act-subjects.txt
inputpaths=${l3dir}/L3-act-input-paths.txt
templatedir=${maindir}/templates
template=${templatedir}/L3_task-socialdoors_model-3_type-act_group-brainhealth-environment_randomise.fsf

for input in "$subjects" "$inputpaths" "$template"; do
	if [ ! -f "$input" ]; then
		echo "Missing required file: $input"
		exit 1
	fi
done

N=$(wc -l < "$subjects")
Npaths=$(wc -l < "$inputpaths")

if [ $N -ne $Npaths ]; then
	echo "Subject and input-path counts do not match."
	exit 1
fi

copenum=4
copename=win-loss
permutations=10000
MAINOUTPUT=${maindir}/derivatives/fsl/randomise/L3_model-3_task-socialdoors+doors_type-act_n${N}
mkdir -p $MAINOUTPUT

for analysis in social-minus-monetary social-monetary-mean; do

	OUTPUT=${MAINOUTPUT}/L3_model-3_task-socialdoors+doors_type-act_cnum-${copenum}_cname-${copename}_${analysis}
	effects=${OUTPUT}/subject-effects
	masks=${OUTPUT}/subject-masks
	mkdir -p $effects $masks

	effect_inputs=()
	mask_inputs=()
	count=0

	while IFS=$'\t' read -r subject inputpath; do
		count=$((count + 1))
		subject=${subject#sub-}
		social=${inputpath//TASK/socialdoors}
		social=${social//COPENUM/$copenum}
		monetary=${inputpath//TASK/doors}
		monetary=${monetary//COPENUM/$copenum}

		if [ ! -f $social ] || [ ! -f $monetary ]; then
			echo "Missing Social or Monetary Doors cope for sub-${subject}."
			exit 1
		fi

		effect=${effects}/sub-${subject}_${analysis}.nii.gz
		if [ $analysis == "social-minus-monetary" ]; then
			fslmaths $social -sub $monetary $effect
		else
			fslmaths $social -add $monetary -div 2 $effect
		fi

		socialmask=${social%/stats/*}/mask.nii.gz
		monetarymask=${monetary%/stats/*}/mask.nii.gz
		mask=${masks}/sub-${subject}_mask.nii.gz
		fslmaths $socialmask -mul $monetarymask -bin $mask

		effect_inputs+=("$effect")
		mask_inputs+=("$mask")
	done < <(paste "$subjects" "$inputpaths")

	if [ $count -ne $N ]; then
		echo "Not all subjects were included in ${analysis}."
		exit 1
	fi

	fslmerge -t ${OUTPUT}/filtered_func_data.nii.gz "${effect_inputs[@]}"
	fslmerge -t ${OUTPUT}/all_masks.nii.gz "${mask_inputs[@]}"
	fslmaths ${OUTPUT}/all_masks.nii.gz -Tmin -bin ${OUTPUT}/mask.nii.gz

	OTEMPLATE=${OUTPUT}/design.fsf
	sed -e 's@OUTPUT@'$OUTPUT'@g' \
	-e 's@NPTS@'$N'@g' \
	-e 's@PERMUTATIONS@'$permutations'@g' \
	<"$template" >"$OTEMPLATE"

	for (( i=1; i<=N; i++ )); do
		echo "set feat_files(${i}) \"${effect_inputs[$((i - 1))]}\"" >> $OTEMPLATE
		echo "set fmri(evg${i}.1) 1" >> $OTEMPLATE
		echo "set fmri(groupmem.${i}) 1" >> $OTEMPLATE
	done

	feat_model ${OUTPUT}/design

	randomise -i ${OUTPUT}/filtered_func_data.nii.gz \
		-o ${OUTPUT}/randomise \
		-d ${OUTPUT}/design.mat \
		-t ${OUTPUT}/design.con \
		-m ${OUTPUT}/mask.nii.gz \
		-T -n $permutations

	echo "Completed ${analysis} (n=${N})."
done
