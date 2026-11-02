from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

import nibabel as nib
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
import inspect_katie_activation as probe


class ActivationProbe(unittest.TestCase):
    def test_descriptive_mean_t_and_no_inference(self):
        values = np.arange(97, dtype=float) - 10
        row = probe.descriptive(values)
        self.assertEqual(row["n"], 97)
        self.assertEqual(row["participants_positive"], 86)
        self.assertAlmostEqual(row["mean_cope"], 38.)
        self.assertAlmostEqual(row["descriptive_t"], values.mean() / (values.std(ddof=1) / np.sqrt(97)))
        self.assertEqual(row["inference"], "descriptive_only_no_corrected_p")

    def test_missing_or_nonfinite_participant_never_silently_dropped(self):
        for values in (np.ones(96), np.r_[np.ones(96), np.nan]):
            with self.assertRaisesRegex(ValueError, "97 finite"):
                probe.descriptive(values)
        self.assertEqual(probe.descriptive(np.zeros(97))["descriptive_t"], "undefined_zero_variance")

    def test_ppi_inventory_is_session_specific_and_does_not_claim_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            parent = project / "derivatives/fsl/sub-10001"
            correct = parent / "ses-01/L1_task-socialdoors_ses-01_model-1_type-ppi_seed-VS_run-1_sm-5.feat"
            correct.mkdir(parents=True)
            for name in ("design.fsf", "design.con", "mask.nii.gz", "stats/cope4.nii.gz", "stats/varcope4.nii.gz"):
                path = correct / name
                path.parent.mkdir(exist_ok=True)
                path.write_text("presence only")
            (parent / "L1_task-socialdoors_ses-02_model-1_type-ppi_seed-VS_run-1_sm-5.feat").mkdir()
            (parent / "L1_task-socialdoors_ses-01_model-1_type-ppi_seed-VS_run-10_sm-5.feat").mkdir()
            legacy = parent / "L1_task-socialdoors_model-1_type-ppi_seed-VS_run-1_sm-5.feat"
            legacy.mkdir()
            rows = probe.ppi_candidates(project, "10001", "socialdoors")
            self.assertEqual(len(rows), 2)
            direct = next(row for row in rows if row["path"] == str(correct))
            self.assertEqual(direct["status"], "files_present_not_yet_lineage_validated")
            self.assertEqual(direct["session_identity"], "ses-01")
            historical = next(row for row in rows if row["path"] == str(legacy))
            self.assertEqual(historical["session_identity"], "legacy_session_unverified")
            self.assertEqual(probe.ppi_candidates(project, "10001", "doors"), [])

    def test_full_97_pair_descriptive_probe_preserves_images(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "task"
            (project / "masks").mkdir(parents=True)
            seed_path = project / "masks/seed-VS.nii.gz"
            shape = (2, 3, 4)
            seed = np.zeros(shape); seed[0, 0, 0] = 1
            nib.save(nib.Nifti1Image(seed, np.eye(4)), seed_path)
            mask = root / "mask.nii.gz"
            nib.save(nib.Nifti1Image(np.ones(shape), np.eye(4)), mask)
            roster_path = root / "subjects.tsv"
            roster = [dict(subject=str(10001 + i)) for i in range(97)]
            roster_path.write_text(probe.base.review.tsv(roster))
            pairs = []
            for i, row in enumerate(roster):
                pair = dict(subject=row["subject"], contrast="4")
                for task, value in (("socialdoors", i + 3.), ("doors", i + 1.)):
                    path = root / f"{row['subject']}_{task}.nii.gz"
                    nib.save(nib.Nifti1Image(np.full(shape, value), np.eye(4)), path)
                    pair[task + "_cope"] = str(path)
                pairs.append(pair)
            plan = dict(outputs={}, sources=[], mask=str(mask))
            (root / "plan.json").write_text(json.dumps(plan))
            native_read = probe.base.cohort.read_table

            def read(path):
                if Path(path).name == "selected_pairs.tsv":
                    return list(pairs[0]), pairs
                return native_read(path)

            original = {str(p): (p.stat().st_mtime_ns, probe.base.cohort.digest(p)) for p in root.glob("*.nii.gz")}
            with patch.object(probe.base, "load_plan", return_value=plan), \
                    patch.object(probe.base.cohort, "read_table", side_effect=read):
                rows, inventory, provenance = probe.inspect(root, project)
            indexed = {row["outcome"]: row for row in rows}
            self.assertEqual(indexed["socialdoors"]["mean_cope"], 51.)
            self.assertEqual(indexed["doors"]["mean_cope"], 49.)
            self.assertEqual(indexed["average"]["mean_cope"], 50.)
            self.assertEqual(indexed["social_specific"]["mean_cope"], 2.)
            self.assertEqual(provenance["common_support_vs_voxels"], 1)
            self.assertEqual(len(inventory), 194)
            self.assertEqual(provenance["ppi_availability"]["doors"]["runs_with_files_present"], 0)
            self.assertEqual(original, {str(p): (p.stat().st_mtime_ns, probe.base.cohort.digest(p)) for p in root.glob("*.nii.gz")})


if __name__ == "__main__":
    unittest.main()
