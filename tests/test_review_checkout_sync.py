import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import publish_katie_review as publisher


class ReviewCheckoutSync(unittest.TestCase):
    def test_clean_main_https_fast_forward_only(self):
        outputs=["main\n","","","","d8e622b\n"]
        with patch.object(publisher.subprocess,"run",side_effect=[subprocess.CompletedProcess([],0,s,"") for s in outputs]) as run:
            publisher.sync_checkout(Path("/project"))
        calls=[c.args[0][1:] for c in run.call_args_list]
        self.assertEqual(calls,[
            ["symbolic-ref","--quiet","--short","HEAD"], ["status","--porcelain"],
            ["-c","remote.origin.url="+publisher.REMOTE,"fetch","origin","main"],
            ["merge","--ff-only","origin/main"], ["rev-parse","--short","HEAD"]])

    def test_dirty_or_other_branch_never_fetches_or_merges(self):
        for branch,status in (("feature",""),("main"," M code/example.py")):
            with patch.object(publisher.subprocess,"run",side_effect=[
                    subprocess.CompletedProcess([],0,branch,"") ,subprocess.CompletedProcess([],0,status,"")]) as run:
                with self.assertRaises(ValueError):publisher.sync_checkout(Path("/project"))
            self.assertLessEqual(len(run.call_args_list),2)

    def test_divergence_stops_without_force_or_recovery(self):
        responses=[subprocess.CompletedProcess([],0,"main", ""), subprocess.CompletedProcess([],0,"", ""),
                   subprocess.CompletedProcess([],0,"", ""), subprocess.CompletedProcess([],128,"","Not possible to fast-forward")]
        with patch.object(publisher.subprocess,"run",side_effect=responses) as run:
            with self.assertRaisesRegex(RuntimeError,"no recovery attempted"):
                publisher.sync_checkout(Path("/project"))
        self.assertEqual(len(run.call_args_list),4)


if __name__=="__main__":unittest.main()
