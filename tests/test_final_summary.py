import copy
import csv
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
import summarize_katie_final as summary


class FinalSummary(unittest.TestCase):
    def setUp(self):
        self.rows = []
        for (family, outcome), (_, count) in summary.EXPECTED.items():
            for i in range(count):
                self.rows.append(dict(family=family, outcome=outcome, model=f"m{i}", term="x",
                                      direction="positive", z=3.1, n=97, min_cluster_fwe_p=.03,
                                      significant_voxels=40, significant_clusters=1))
        self.preview = dict(n=97, completed_jobs=220, pending_jobs=0, verified_completed_maps=996,
                            preliminary=False, corrected_findings=self.rows)
        self.snapshot = dict(recorded_status="complete", recorded_validated=True, recorded_failures={},
                             invalid_job_keys=[], outcome_counts={"COMPLETED": 220},
                             recorded_final_validation=dict(n=97, directional_tests=1328,
                                                            original_results_changed=False, exclusions_changed=False))
        self.catalog = dict(rows=1328, summary=[dict(family=f, outcome=o, total_maps=v[0])
                                               for (f, o), v in summary.EXPECTED.items()],
                            new_corrected_findings=copy.deepcopy(self.rows))

    def test_complete_and_json_with_log_suffix(self):
        self.assertEqual(len(summary.reconcile([], self.preview, self.snapshot, self.catalog)), 69)
        self.assertEqual(summary.json_after("HEADER\n {\"x\": 2}\ntrailer", "HEADER"), {"x": 2})

    def test_incomplete_failed_and_changed_cohort_rejected(self):
        for field, value in (("pending_jobs", 1), ("n", 96), ("preliminary", True)):
            preview = dict(self.preview, **{field: value})
            with self.assertRaises(ValueError):
                summary.reconcile([], preview, self.snapshot, self.catalog)
        snapshot = dict(self.snapshot, recorded_failures={"bad": 1})
        with self.assertRaises(ValueError):
            summary.reconcile([], self.preview, snapshot, self.catalog)

    def test_duplicate_missing_and_mismatched_snapshot_rejected(self):
        for rows in (self.rows + [self.rows[0]], self.rows[:-1]):
            with self.assertRaises(ValueError):
                summary.reconcile([], dict(self.preview, corrected_findings=rows), self.snapshot, self.catalog)
        catalog = dict(self.catalog, new_corrected_findings=[])
        with self.assertRaises(ValueError):
            summary.reconcile([], self.preview, self.snapshot, catalog)

    def test_published_output_and_curated_hashes(self):
        root = Path(__file__).resolve().parents[1]
        summary.verify_reports(root)
        report = root / "results/review/final-summary-v1"
        if report.exists():
            with (report / "corrected_maps.tsv").open() as stream:
                rows = list(csv.DictReader(stream, delimiter="\t"))
            self.assertEqual(len(rows), 69)
            self.assertEqual(len({summary.token(r) for r in rows}), 69)
            provenance = json.loads((report / "provenance.json").read_text())
            for name, expected in provenance["outputs"].items():
                self.assertEqual(summary.digest((report / name).read_bytes()), expected)


if __name__ == "__main__":
    unittest.main()
