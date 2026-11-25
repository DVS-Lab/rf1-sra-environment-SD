import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
import audit_katie_recruitment as audit


class RecruitmentAudit(unittest.TestCase):
    def test_net_thirteen_is_not_always_thirteen_missing(self):
        recruits = {str(n): ("", "") for n in range(10000, 10164)}
        imaging = {str(n): {} for n in range(10016, 10167)}
        frozen = {**imaging, "10000": {"frozen_status": "under_55"}}
        with tempfile.TemporaryDirectory() as tmp:
            rows = list(audit.mismatch_rows(recruits, imaging, frozen, {"10001"}, {}, {}, Path(tmp)))
        reasons = {r["rf1_id"]:r["historical_evidence"] for r in rows}
        self.assertEqual(audit.Counter(r["difference"] for r in rows), {"recruitment_only":16, "imaging_only":3})
        self.assertEqual(reasons["10000"], "under_55_in_frozen_imaging_age_filter")
        self.assertEqual(reasons["10001"], "listed_in_Oct21_source_exclusions")
        self.assertEqual(reasons["10002"], "not_in_frozen_imaging_table")
        self.assertTrue(all(r["documented_disposition"]=="" for r in rows))

    def test_roster_count_collisions_and_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"roster.tsv"
            body="".join(f"{n}\t\t\n" for n in range(10001,10164))
            header="rf1_id\tdocumented_disposition\tevidence_ref\n"
            valid=header+"sub-10000\twithdrew\tvisit log A\n"+body
            path.write_text(valid)
            self.assertEqual(audit.recruitment(path)["10000"], ("withdrew","visit log A"))
            for bad in (valid+"10000\t\t\n",valid.replace("visit log A",""),
                        header+body,valid.replace("sub-10000","X10000"),
                        valid.replace("rf1_id","subject_id\tparticipant_id")):
                path.write_text(bad)
                with self.assertRaises(ValueError):
                    audit.recruitment(path)

    def test_locate_does_not_open_candidates_or_enter_image_trees(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"private data").mkdir()
            candidate=root/"private data/recruitment.xlsx"
            candidate.touch()
            (root/"derivatives").mkdir()
            (root/"derivatives/recruitment.xlsx").touch()
            self.assertEqual(list(audit.candidates([root])),[candidate])

    def test_compare_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            up=root/"up"
            table=up/audit.RUNS
            table.parent.mkdir(parents=True)
            with table.open("w",newline="") as f:
                w=csv.writer(f,delimiter="\t")
                w.writerow(["subject","task","session","run","frozen_status","previous_selection_status"])
                for idx in range(352):
                    status = "eligible" if idx<137 else "exclude_below_95" if idx<139 else "not_in_verified_plan"
                    w.writerow([10000+idx,"socialdoors","01","1","under_55" if idx>=151 else "test",status])
            (up/"bids").mkdir()
            (up/"bids/participants.tsv").write_text("participant_id\tage\nsub-10000\t55\nsub-10151\t54.99\n")
            roster=root/"recruited.tsv"
            roster.write_text("rf1_id\n"+"".join(f"{n}\n" for n in range(10000,10164)))
            with patch.object(audit,"ROOT",root), patch.object(audit,"RUNS_SHA",audit.digest(table)), \
                 patch.object(sys,"argv",["audit","--upstream",str(up),"--roster",str(roster),"--source-note","test only"]), \
                 patch("builtins.print"), \
                 patch.object(audit.subprocess,"check_output",return_value=b'{"inventory":{"source_excluded_subjects":[]}}'):
                audit.main()
            out,=(root/"work").iterdir()
            self.assertEqual(len(audit.tsv(out/"discrepancies.tsv")),13)
            summary=audit.json.loads((out/"counts.json").read_text())
            self.assertEqual((summary["intersection"],summary["imaging_only"]),(151,0))
            self.assertEqual(summary["historical_evidence"],{"under_55_in_frozen_imaging_age_filter":13})
