from contextlib import redirect_stdout
import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"code"))
import snapshot_reward_extension as snapshot


class Snapshot(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.folder=self.root/"derivatives/fsl/randomise/katie-reward-extension-v1"
        self.folder.mkdir(parents=True)
        self.job=dict(key="activation/win_only/adi/z-2p6",contrasts=[dict(index=1),dict(index=2)])
        plan=self.folder/"plan.json";plan.write_text(json.dumps(dict(n=97,jobs=[self.job])))
        self.digest=hashlib.sha256(plan.read_bytes()).hexdigest()
        (self.folder/"plan.sha256").write_text(self.digest)

    def tearDown(self):self.tmp.cleanup()

    def receipt(self):
        folder=self.folder/"jobs"/self.job["key"];attempt=folder/"attempts/attempt-0001"
        attempt.mkdir(parents=True)
        for index in (1,2):
            for kind in ("tstat","clustere_corrp_tstat"):
                (attempt/f"randomise_{kind}{index}.nii.gz").write_bytes(b"presence-only fixture")
        receipt=folder/"success.json"
        receipt.write_text(json.dumps(dict(job=self.job,plan_sha256=self.digest,smoke=False,attempt=str(attempt))))
        return receipt,attempt

    def test_missing_stale_and_invalid_state_do_not_claim_full_validation(self):
        (self.folder/"status.json").write_text(json.dumps(dict(status="running",outcomes={})))
        r=snapshot.progress(self.folder,220)
        self.assertEqual(r["receipt_inventory"],dict(missing_receipt=1))
        self.assertIsNone(r["recorded_validated"])
        self.assertIn("not image hashes",r["verification_scope"])
        receipt,attempt=self.receipt()
        r=snapshot.progress(self.folder,220)
        self.assertEqual(r["receipt_inventory"]["receipt_metadata_and_product_presence_ok"],1)
        (attempt/"randomise_tstat2.nii.gz").unlink()
        self.assertEqual(snapshot.progress(self.folder,220)["receipt_inventory"]["missing_or_empty_products"],1)
        receipt.write_text(json.dumps(dict(job=self.job,plan_sha256="wrong",smoke=True,attempt=str(attempt))))
        self.assertEqual(snapshot.progress(self.folder,220)["receipt_inventory"]["invalid_receipt_metadata"],1)

    def test_partial_results_not_reported_and_existing_findings_not_called_new(self):
        self.assertFalse(snapshot.results(self.folder)["available"])
        row=dict(family="activation",outcome="win_only",model="adi",term="adi",direction="positive",z="2.6",
                 origin="extension",min_cluster_fwe_p="1",significant_voxels="0")
        def write(rows):
            with (self.folder/"maps.tsv").open("w") as stream:
                writer=csv.DictWriter(stream,fieldnames=list(row),delimiter="\t")
                writer.writeheader();writer.writerows(rows)
        write([row]);self.assertFalse(snapshot.results(self.folder)["available"])
        rows=[dict(row) for _ in range(1328)]
        rows[0].update(min_cluster_fwe_p=".01",significant_voxels="20")
        rows[1].update(origin="existing",min_cluster_fwe_p=".001",significant_voxels="30")
        write(rows);r=snapshot.results(self.folder)
        self.assertTrue(r["available"]);self.assertEqual(len(r["new_corrected_findings"]),1)
        self.assertEqual(r["new_corrected_findings"][0]["min_cluster_fwe_p"],".01")

    def test_snapshot_is_read_only_and_captures_launcher_failure(self):
        logs=self.root/"logs/runs";logs.mkdir(parents=True)
        (logs/"reward-extension-synthetic.nohup.out").write_text("synthetic launcher failure\n")
        before={p:p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        output=io.StringIO()
        with patch.object(snapshot,"processes",return_value=[]),redirect_stdout(output):snapshot.snapshot(self.root)
        self.assertIn("synthetic launcher failure",output.getvalue())
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_status_launcher_parses_and_analysis_runner_is_not_changed(self):
        code=Path(snapshot.__file__).parent
        subprocess.run(["bash","-n",str(code/"launch_reward_extension.sh")],check=True)
        text=(code/"launch_reward_extension.sh").read_text()
        self.assertIn("--status)",text);self.assertIn("snapshot_reward_extension.py",text)
        self.assertIn("--include-full-log",text);self.assertIn("publish_run_logs.py",text)


if __name__=="__main__":unittest.main()
