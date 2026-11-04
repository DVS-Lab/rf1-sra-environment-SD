from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class GeneratedReportPaths(unittest.TestCase):
    def test_only_local_exports_ignored_canonical_reports_remain_publishable(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            subprocess.run(["git", "init", "-q", str(workspace)], check=True)
            shutil.copyfile(root / ".gitignore", workspace / ".gitignore")
            ignored = ["results/progress/snapshot/jobs.tsv"]
            ignored += [f"results/randomise/{name}/README.md" for name in (
                "katie-financial-moderation-v1", "katie-financial-v1",
                "katie-main-effects-v1", "katie-remaining-v1")]
            retained = ["results/review/fevs-imaging-adjustments-provisional-v1/README.md",
                        "results/review/katie-review-v1/maps.tsv",
                        "results/randomise/katie-v1/README.md",
                        "results/randomise/new-reviewed-batch/maps.tsv",
                        "code/run_fevs_imaging_adjustments.py"]
            for path in ignored + retained:
                result = subprocess.run(["git", "-c", "core.excludesFile=/dev/null",
                    "check-ignore", "--no-index", "-q", path], cwd=workspace)
                self.assertEqual(result.returncode, 0 if path in ignored else 1, path)


if __name__ == "__main__":
    unittest.main()
