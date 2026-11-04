import copy
import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import shutil
import subprocess

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
import run_behavioral_moderation as behavior


class BehavioralModeration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.root = self.project / "work/behavioral"
        self.root.mkdir(parents=True)
        self.spec_path = self.root / "scoring-spec.json"
        self.ids = [str(20000 + i) for i in range(97)]
        rng = np.random.default_rng(42)
        self.item_values = rng.integers(0, 3, size=(97, 4))
        for path in (behavior.ROSTER, behavior.SCORE_FILE, behavior.VARIABLES, behavior.POLICY):
            (self.project / path).parent.mkdir(parents=True, exist_ok=True)
        behavior.tsv(self.project / behavior.ROSTER, [dict(subject=s) for s in self.ids])
        with (self.project / behavior.SCORE_FILE).open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["sub-num", "fevs", "OAFEM"])
            for s, items in zip(self.ids, self.item_values):
                writer.writerow([s, int(items[0] + items[1]), int(2 * (items[2] + items[3]))])
        raw = [dict(subject=s, age=float(rng.uniform(55, 89)), gender_code1=i % 2,
                    adi=float(rng.uniform(1, 100)), pm25=float(rng.uniform(6, 10)),
                    mspss=float(rng.uniform(1, 7)) if i else 0., ecog=float(rng.uniform(1, 3)))
               for i, s in enumerate(self.ids)]
        behavior.tsv(self.project / behavior.VARIABLES, raw)
        source_policy = Path(behavior.__file__).resolve().parents[1] / behavior.POLICY
        (self.project / behavior.POLICY).write_bytes(source_policy.read_bytes())
        receipt = self.project / behavior.SOURCE_RECEIPT
        receipt.parent.mkdir(parents=True, exist_ok=True)
        behavior.write_json(receipt, dict(sources=[dict(path=p, sha256=behavior.sha(self.project / p))
                                                   for p in (behavior.ROSTER, behavior.SCORE_FILE, behavior.VARIABLES)]))
        self.item_table = self.project / "items.tsv"
        self.item_rows = [dict(subject=s, visit="baseline", **{f"item{i}": int(v) for i, v in enumerate(items)})
                          for s, items in zip(self.ids, self.item_values)]
        behavior.tsv(self.item_table, self.item_rows)
        instruments = {}
        for name, columns, multiplier, direction in (
                ("fevs", [0, 1], 1, "higher_more_vulnerability"),
                ("oafem", [2, 3], 2, "higher_more_reported_exploitation")):
            instruments[name] = dict(instrument_version="SYNTHETIC TEST ONLY", source_timepoint="fixture",
                                     scoring_reference="Synthetic fixture, not study scoring approval", raw_table=str(self.item_table),
                                     id_column="subject", record_filters={"visit": "baseline"}, n_items_expected=2,
                                     score_direction=direction, aggregation="sum", missing_rule="complete_items_required",
                                     missing_tokens=["", "NA", "999"],
                                     items=[dict(column=f"item{i}", points={str(v): v * multiplier for v in range(3)}) for i in columns])
        self.spec = dict(version=1, instruments=instruments)

    def save_spec(self):
        behavior.write_json(self.spec_path, self.spec)

    def test_strict_missing_spec_stops_before_models(self):
        with self.assertRaises(behavior.ScoringRequired):
            behavior.run(self.project, self.root, self.spec_path)
        self.assertFalse((self.root / "report").exists())
        self.assertEqual(json.loads((self.root / "scoring-status.json").read_text())["status"], "SCORING_REQUIRED")

    def test_explicit_provisional_keeps_all_97_and_zero(self):
        ids, values, audit = behavior.audit(self.project, self.root, self.spec_path, provisional=True)
        self.assertEqual(ids, self.ids)
        self.assertEqual(audit["mspss_zero_count"], 1)
        self.assertFalse(audit["item_scoring_verified"])
        self.assertEqual(len(values["fevs"]), 97)

    def test_item_scoring_matches_both_outcomes_without_dropping(self):
        self.save_spec()
        ids, values, audit = behavior.audit(self.project, self.root, self.spec_path)
        self.assertTrue(audit["item_scoring_verified"])
        self.assertEqual(audit["instruments"]["fevs"]["totals_match"], 97)
        self.assertEqual(audit["instruments"]["oafem"]["totals_match"], 97)
        np.testing.assert_array_equal(values["oafem"], self.item_values[:, 2:].sum(axis=1) * 2)

    def test_missing_unknown_and_total_mismatch_cannot_use_provisional_bypass(self):
        self.save_spec()
        original = copy.deepcopy(self.item_rows)
        for bad in ("", "999", "unknown", "2" if str(original[0]["item0"]) != "2" else "0"):
            self.item_rows[0]["item0"] = bad
            behavior.tsv(self.item_table, self.item_rows)
            with self.assertRaises(behavior.ScoringRequired):
                behavior.audit(self.project, self.root, self.spec_path, provisional=True)
            self.item_rows = copy.deepcopy(original)

    def test_repeated_records_require_explicit_filters(self):
        self.item_rows.append(dict(self.item_rows[0], visit="followup"))
        behavior.tsv(self.item_table, self.item_rows)
        self.save_spec()
        behavior.audit(self.project, self.root, self.spec_path)
        self.spec["instruments"]["fevs"]["record_filters"] = {}
        self.save_spec()
        with self.assertRaises(ValueError):
            behavior.audit(self.project, self.root, self.spec_path)

    def test_changed_approved_export_and_audit_race_rejected(self):
        target = self.project / behavior.VARIABLES
        original = target.read_bytes()
        target.write_bytes(original + b"\n")
        with self.assertRaises(ValueError):
            behavior.inputs(self.project)
        target.write_bytes(original)
        original_inputs = behavior.inputs
        def changed(project):
            result = original_inputs(project)
            target.write_bytes(original + b"\n")
            return result
        with patch.object(behavior, "inputs", side_effect=changed):
            with self.assertRaises(ValueError):
                behavior.audit(self.project, self.root, self.spec_path, provisional=True)

    def test_full_models_hc3_family_sizes_and_native_preservation(self):
        self.save_spec()
        native = self.project / "derivatives/fsl/randomise/completed-native.dat"
        native.parent.mkdir(parents=True)
        native.write_bytes(b"completed-neural-result-do-not-touch")
        protected = behavior.sha(native)
        behavior.run(self.project, self.root, self.spec_path)
        _, rows = behavior.table(self.root / "report/interactions.tsv")
        self.assertEqual(len(rows), 8)
        self.assertEqual(sum(r["family"] == "primary" for r in rows), 2)
        self.assertTrue(all(int(r["n"]) == 97 and int(r["residual_df"]) == 91 for r in rows))
        self.assertTrue(all(float(r["holm_family_p"]) >= float(r["hc3_p"]) - 1e-12 for r in rows))
        _, values = behavior.inputs(self.project)
        _, x = behavior.design(values, "adi", "mspss")
        y = values["fevs"]
        beta = np.linalg.lstsq(x, y, rcond=None)[0]
        inv = np.linalg.inv(x.T @ x)
        leverage = np.einsum("ij,jk,ik->i", x, inv, x)
        scaled = (y - x @ beta) / (1 - leverage)
        cov = inv @ (x.T @ (x * scaled[:, None] ** 2)) @ inv
        first = next(r for r in rows if r["model"] == "fevs_adi_mspss")
        self.assertAlmostEqual(float(first["interaction_beta"]), beta[-1], places=10)
        self.assertAlmostEqual(float(first["hc3_se"]), np.sqrt(cov[-1, -1]), places=10)
        self.assertEqual(behavior.sha(native), protected)
        manifest = json.loads((self.root / "report/review_manifest.json").read_text())
        self.assertFalse(any("private" in name for name in manifest["outputs"]))
        old = behavior.sha(self.root / "report/interactions.tsv")
        behavior.run(self.project, self.root, self.spec_path)
        self.assertEqual(behavior.sha(self.root / "report/interactions.tsv"), old)
        (self.root / "report/interactions.tsv").write_text("tampered")
        with self.assertRaises(ValueError):
            behavior.check(self.project, self.root, self.spec_path)

    def test_provisional_report_never_claims_scoring_verified(self):
        behavior.run(self.project, self.root, self.spec_path, provisional=True)
        manifest = json.loads((self.root / "report/review_manifest.json").read_text())
        self.assertTrue(manifest["provisional"])
        self.assertFalse(manifest["scoring_passed"])
        self.assertIn("PROVISIONAL", (self.root / "report/README.md").read_text())
        self.save_spec()
        with self.assertRaises(ValueError):
            behavior.check(self.project, self.root, self.spec_path, provisional=True)

    def frozen_cli(self, command):
        code = self.project / "code"
        code.mkdir(exist_ok=True)
        for module in (behavior, behavior.cohort):
            shutil.copyfile(module.__file__, code / Path(module.__file__).name)
        live = self.project / "older-live-checkout"
        live.mkdir(exist_ok=True)
        return subprocess.run([sys.executable, str(code / "run_behavioral_moderation.py"), command,
                               "--project", str(live), "--data-root", str(self.project), "--provisional"],
                              capture_output=True, text=True)

    def test_frozen_release_runs_with_old_live_checkout_and_keeps_native_outputs(self):
        live = self.project / "older-live-checkout"
        native = live / "derivatives/fsl/completed.dat"
        native.parent.mkdir(parents=True)
        native.write_bytes(b"preserve-completed-neural")
        before = behavior.sha(native)
        for command in ("audit", "run", "check"):
            result = self.frozen_cli(command)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((live / behavior.POLICY).exists())
        self.assertFalse((live / behavior.SCORE_FILE).exists())
        self.assertEqual(behavior.sha(native), before)
        report = live / "work/behavioral-moderation-provisional-v1/report"
        self.assertTrue((report / "interactions.tsv").exists())
        self.assertTrue(json.loads((report / "review_manifest.json").read_text())["provisional"])

    def test_missing_frozen_file_reports_relative_path_and_never_fits(self):
        (self.project / behavior.POLICY).unlink()
        result = self.frozen_cli("audit")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Missing frozen input: config/behavioral_moderation_v1.json", result.stderr)
        self.assertFalse((self.project / "older-live-checkout/work/behavioral-moderation-provisional-v1/report").exists())


if __name__ == "__main__":
    unittest.main()
