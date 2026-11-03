#!/usr/bin/env python3
"""Choose a readable nonempty local anatomical display image, never download or edit it."""
import argparse
import json
import os
from pathlib import Path

import nibabel as nib
import numpy as np

import run_katie_randomise as base


def select(candidates):
    rejected=[]
    for candidate in candidates:
        path=Path(candidate)
        try:
            if not path.is_file() or path.stat().st_size == 0:
                raise ValueError("missing file or empty cache placeholder")
            image=nib.load(path)
            if image.ndim != 3 or min(image.shape)<2 or not np.isfinite(image.affine).all() or abs(np.linalg.det(image.affine[:3,:3]))<1e-12:
                raise ValueError("invalid 3D anatomical geometry")
            data=image.get_fdata(dtype=np.float32)
            if not np.isfinite(data).all() or float(np.ptp(data)) == 0:
                raise ValueError("anatomical data are nonfinite or constant")
            result=dict(path=str(path.resolve()),shape=list(image.shape),fingerprint=base.fingerprint(path),
                rejected_candidates=rejected,display_only=True,source_images_changed=False,downloaded=False)
            print("CHECK PASSED: validated anatomical display background: "+result["path"],flush=True)
            return result
        except (OSError,ValueError,EOFError,nib.filebasedimages.ImageFileError) as exc:
            rejected.append(dict(path=str(path),reason=str(exc)))
            print("BACKGROUND REJECTED: "+str(path)+": "+str(exc),flush=True)
    raise ValueError("No readable nonempty local anatomical background; no sources changed or downloaded")


def main():
    os.umask(0)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate",action="append",type=Path)
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args()
    candidates=args.candidate or [Path(os.environ.get("TEMPLATEFLOW_HOME",str(Path.home()/".cache/templateflow")))/
        "tpl-MNI152NLin6Asym/tpl-MNI152NLin6Asym_res-02_T1w.nii.gz",
        Path(os.environ.get("FSLDIR","/usr/local/fsl"))/"data/standard/MNI152_T1_2mm.nii.gz"]
    result=select(candidates)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(base.cohort.json_text(result))


if __name__=="__main__":main()
