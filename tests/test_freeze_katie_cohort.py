import copy
import csv
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
import freeze_katie_cohort as freeze

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UPSTREAM = ROOT.parent / "rf1-sra-linux2-geometry"
if not DEFAULT_UPSTREAM.exists():
    DEFAULT_UPSTREAM = ROOT.parent / "rf1-sra-linux2"
UPSTREAM = Path(os.environ.get("RF1_SRA_UPSTREAM_ROOT", DEFAULT_UPSTREAM))


def analysis_row(**changes):
    return dict(dict(rf1_id=10001, sub_age=60, gender=0, ecog_score=40,
                     mspss_sum=60, adi_natrank=30, pm25_mean_2013_2023=9.5), **changes)


class WorkbookValidation(unittest.TestCase):
    def test_zero_values_preserved_no_gender_recode(self):
        result = freeze.validate_analysis([analysis_row(gender=0, ecog_score=0)])
        self.assertEqual(result["10001"]["gender"], 0)
        self.assertEqual(result["10001"]["ecog_score"], 0)

    def test_no_new_age_filter(self):
        self.assertIn("10001", freeze.validate_analysis([analysis_row(sub_age=54)]))

    def test_duplicate_id(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            freeze.validate_analysis([analysis_row(), analysis_row(rf1_id="sub-10001")])

    def test_missing_gender_or_invalid_number_fails_not_silent_drop(self):
        for changes in ({"gender": None}, {"gender": ""}, {"sub_age": float("nan")},
                        {"adi_natrank": float("inf")}, {"ecog_score": True}):
            with self.subTest(changes=changes), self.assertRaises((ValueError, TypeError)):
                freeze.validate_analysis([analysis_row(**changes)])

    def test_invalid_ids(self):
        for value in (True, None, "10001_duplicate", "abc", 10001.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                freeze.identifier(value)


class ExistingImagingValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tables = {name: freeze.read_table(UPSTREAM / freeze.SNAPSHOT / (name + ".tsv"))[1]
                      for name in ("strict_pairs", "diagnostic_pairs", "pair_membership", "run_membership")}

    def validate(self, tables):
        return freeze.validate_imaging(tables["strict_pairs"], tables["diagnostic_pairs"],
                                       tables["pair_membership"], tables["run_membership"])

    def test_all_original_strict_rows_and_decisions_agree(self):
        pool, _, _ = self.validate(self.tables)
        self.assertEqual(len(pool), 121)

    def test_cannot_add_flagged_pair_or_drop_good_pair(self):
        for alter in ("drop", "add"):
            tables = copy.deepcopy(self.tables)
            if alter == "drop":
                tables["strict_pairs"].pop()
            else:
                tables["strict_pairs"].append(next(r for r in tables["diagnostic_pairs"] if r["group"] != "strict_pass"))
            with self.subTest(alter=alter), self.assertRaisesRegex(ValueError, "exactly"):
                self.validate(tables)

    def test_duplicate_contrast_fails(self):
        tables = copy.deepcopy(self.tables)
        tables["strict_pairs"].append(tables["strict_pairs"][0])
        with self.assertRaisesRegex(ValueError, "Duplicate source identity"):
            self.validate(tables)

    def test_settled_source_hold_cannot_be_overridden(self):
        tables = copy.deepcopy(self.tables)
        sub = tables["strict_pairs"][0]["subject"]
        run = next(r for r in tables["run_membership"] if r["subject"] == sub and r["task"] == "doors")
        run["previous_selection_status"] = "held_existing_decision"
        with self.assertRaisesRegex(ValueError, "settled source/run decision"):
            self.validate(tables)

    def test_changed_fence_or_metric_fails(self):
        tables = copy.deepcopy(self.tables)
        tables["strict_pairs"][0]["doors_fd_mean_fence"] = "99"
        with self.assertRaisesRegex(ValueError, "exactly"):
            self.validate(tables)

    def test_unexpected_unavailable_reason_not_reclassified(self):
        pool, members, runs = self.validate(self.tables)
        analysis = freeze.read_analysis(ROOT / freeze.WORKBOOK)
        sub = next(s for s in analysis if s not in pool)
        members[(sub, "01")] = dict(members[(sub, "01")], group="new_unreviewed_hold")
        with self.assertRaisesRegex(ValueError, "Unexpected existing decision"):
            freeze.reconcile(analysis, pool, members, runs)


class CompleteFreeze(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files, cls.summary = freeze.generate(ROOT, UPSTREAM)

    def test_counts_and_existing_reasons(self):
        self.assertEqual(self.summary["counts"], freeze.EXPECTED)
        rows = list(csv.DictReader(io.StringIO(self.files["reconciliation.tsv"]), delimiter="\t"))
        self.assertEqual(len(rows), 110)
        self.assertEqual(sum(r["status"] == "retained" for r in rows), 97)
        self.assertEqual(sum(r["status"] == "existing_run_qc" for r in rows), 11)
        self.assertEqual(sum(r["status"] == "existing_coverage" for r in rows), 2)

    def test_order_and_aligned_variables_and_all_contrasts(self):
        subjects = [r["subject"] for r in csv.DictReader(io.StringIO(self.files["subjects.tsv"]), delimiter="\t")]
        variables = list(csv.DictReader(io.StringIO(self.files["analysis_variables.tsv"]), delimiter="\t"))
        pairs = list(csv.DictReader(io.StringIO(self.files["selected_pairs.tsv"]), delimiter="\t"))
        self.assertEqual(len(subjects), 97)
        self.assertEqual(subjects, sorted(set(subjects)))
        self.assertEqual([r["subject"] for r in variables], subjects)
        self.assertEqual([(r["subject"], r["contrast"]) for r in pairs],
                         [(s, str(c)) for s in subjects for c in range(1, 5)])
        self.assertFalse(self.summary["gender_recode_applied"])
        self.assertEqual(self.summary["gender_source_code_counts"], {"0": 48, "1": 49})

    def test_repeat_is_portable_and_identical(self):
        other, _ = freeze.generate(ROOT, UPSTREAM)
        self.assertEqual(other, self.files)
        provenance = json.loads(self.files["provenance.json"])
        self.assertEqual(len(provenance["sources"]), 6)
        self.assertNotIn("/Users/", self.files["provenance.json"])
        self.assertFalse(provenance["policy"]["image_bundle_validated"])
        self.assertFalse(provenance["policy"]["randomise_run"])

    def test_output_integrity_extra_file_and_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            for name, text in self.files.items():
                (output / name).write_bytes(text.encode())
            freeze.verify(output, self.files)
            (output / "unexpected.tsv").write_text("extra")
            with self.assertRaisesRegex(ValueError, "inventory"):
                freeze.verify(output, self.files)
            (output / "unexpected.tsv").unlink()
            (output / "subjects.tsv").write_text("subject\n10001\n")
            with self.assertRaisesRegex(ValueError, "content/provenance"):
                freeze.verify(output, self.files)

    def test_source_workbook_bytes_are_unchanged(self):
        before = freeze.digest(ROOT / freeze.WORKBOOK)
        freeze.generate(ROOT, UPSTREAM)
        self.assertEqual(before, freeze.digest(ROOT / freeze.WORKBOOK))


if __name__ == "__main__":
    unittest.main()
