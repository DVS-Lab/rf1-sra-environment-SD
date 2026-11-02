from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
import audit_katie_outcome as audit


class OutcomeAudit(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.feat = self.root / "subject.feat"
        (self.feat / "stats").mkdir(parents=True)
        self.cope = self.feat / "stats/cope4.nii.gz"
        self.cope.write_bytes(b"unused image; pixel identity validated by baseline")
        values = {"evs_real": "4", "conname_real.4": "win-loss"}
        for index, name in enumerate(("win", "loss", "decision", "miss"), 1):
            values[f"evtitle{index}"] = name
            values[f"deriv_yn{index}"] = "0"
            values[f"con_real4.{index}"] = str([1, -1, 0, 0][index - 1])
        for index, name in ((1, "win"), (2, "loss")):
            path = self.root / (name + ".txt")
            path.write_text("5.123456 2.000000 1.000000\n" if index == 1 else "15 2 1\n")
            values[f"custom{index}"] = str(path)
        self.values = values
        self.write_fsf()
        con = np.zeros((4, 6)); con[3, :2] = [1, -1]
        (self.feat / "design.con").write_text("/Matrix\n" + "\n".join(" ".join(map(str, r)) for r in con))
        self.events = self.root / "events.tsv"
        self.events.write_text("onset\tduration\ttrial_type\n0\t2\tdecision\n5.1234563\t2\twin\n15\t2\tloss\n")

    def write_fsf(self):
        (self.feat / "design.fsf").write_text("\n".join(f'set fmri({key}) "{value}"' for key, value in self.values.items()))

    def tearDown(self):
        self.temporary.cleanup()

    def inspect(self):
        return audit.inspect_run("10001", "socialdoors", self.feat, self.cope, self.events)

    def test_outcome_weights_and_microsecond_formatted_timing_pass(self):
        row, paths = self.inspect()
        self.assertEqual(row["phase"], "feedback_outcome")
        self.assertEqual(row["win_events"], 1)
        self.assertEqual(len(paths), 6)

    def test_decision_weight_in_fsf_rejected(self):
        self.values["con_real4.3"] = "1"
        self.write_fsf()
        with self.assertRaisesRegex(ValueError, "FSF COPE-4"):
            self.inspect()

    def test_actual_contrast_nuisance_weight_rejected(self):
        path = self.feat / "design.con"
        path.write_text(path.read_text().rsplit("0.0", 1)[0] + "1.0")
        with self.assertRaisesRegex(ValueError, "non-outcome"):
            self.inspect()

    def test_decision_onset_substitution_rejected(self):
        (self.root / "win.txt").write_text("0 2 1\n")
        with self.assertRaisesRegex(ValueError, "timing/duration/amplitude"):
            self.inspect()

    def test_ev_amplitude_or_duration_change_rejected(self):
        for content in ("5.123456 3 1\n", "5.123456 2 2\n"):
            (self.root / "win.txt").write_text(content)
            with self.assertRaisesRegex(ValueError, "timing/duration/amplitude"):
                self.inspect()

    def test_wrong_selected_cope_rejected(self):
        with self.assertRaisesRegex(ValueError, "not this run's COPE 4"):
            audit.inspect_run("10001", "doors", self.feat, self.feat / "stats/cope3.nii.gz", self.events)

    def test_actual_templates_define_feedback_contrast(self):
        repository = Path(__file__).resolve().parents[2] / "rf1-sra-socdoors-handoff"
        if not repository.exists():
            self.skipTest("Reference task repository is not checked out")
        for task in ("socialdoors", "doors"):
            values = audit.settings(repository / f"templates/L1_task-{task}_model-1_type-act.fsf")
            self.assertEqual(values["conname_real.4"], "win-loss")
            self.assertEqual([float(values[f"con_real4.{i}"]) for i in range(1, 5)], [1, -1, 0, 0])


if __name__ == "__main__":
    unittest.main()
