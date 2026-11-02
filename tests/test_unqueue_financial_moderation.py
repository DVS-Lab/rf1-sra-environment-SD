from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
import unqueue_financial_moderation as unqueue


class UnqueueSafety(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name).resolve()
        self.argv = ["/env/bin/python", "/release/code/run_financial_moderation.py", "--project", str(self.project), "--prepare-only"]
        self.memory = patch.object(unqueue, "memory_available_kib", return_value=114*1024*1024)
        self.memory.start()

    def tearDown(self):
        self.memory.stop()
        self.temporary.cleanup()

    def test_proc_inventory_distinguishes_predictor_logged_wrappers_and_other_projects(self):
        proc = self.project / "proc"; proc.mkdir()
        rows = [self.argv, ["bash", "/release/code/run_financial_moderation.sh", str(self.project), "stamp"],
            ["python", "/release/code/run_financial_models.py", "--project", str(self.project)],
            ["bash", "run_logged.sh", *self.argv],
            ["python", "run_financial_moderation.py", "--project", "/unrelated"]]
        for pid, argv in enumerate(rows, 100):
            directory = proc / str(pid); directory.mkdir()
            (directory / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
        self.assertEqual(unqueue.processes(self.project, proc), ([(100, self.argv)], [101]))

    def test_only_preflight_is_stopped_and_no_files_removed(self):
        with patch.object(unqueue, "processes", side_effect=[([(100, self.argv)], [101]), ([], [])]), \
                patch.object(unqueue, "stop_preflight") as stop:
            unqueue.unqueue(self.project)
        stop.assert_called_once_with(100, self.argv, self.project)

    def test_existing_outputs_full_runner_multiple_coordinators_low_memory_all_refuse(self):
        with patch.object(unqueue, "stop_preflight") as stop:
            for coordinators in ([(100, self.argv[:-1])], [(100, self.argv), (101, self.argv)]):
                with patch.object(unqueue, "processes", return_value=(coordinators, [])), self.assertRaises(RuntimeError):
                    unqueue.unqueue(self.project)
            with patch.object(unqueue, "memory_available_kib", return_value=100), self.assertRaises(RuntimeError):
                unqueue.unqueue(self.project)
            output = self.project / "derivatives/fsl/randomise/katie-financial-moderation-v1"
            output.mkdir(parents=True); (output / "plan.json").write_text("preserve")
            with self.assertRaisesRegex(RuntimeError, "already exist"):
                unqueue.unqueue(self.project)
            self.assertEqual((output / "plan.json").read_text(), "preserve")
            stop.assert_not_called()

    def test_pidfd_rechecks_target_and_uses_only_term(self):
        with patch.object(unqueue.os, "pidfd_open", return_value=900, create=True), \
                patch.object(unqueue.signal, "pidfd_send_signal", create=True) as send, \
                patch.object(unqueue.os, "close") as close, \
                patch.object(unqueue, "processes", return_value=([(100, self.argv)], [])):
            unqueue.stop_preflight(100, self.argv, self.project)
        send.assert_called_once_with(900, signal.SIGTERM)
        close.assert_called_once_with(900)
        with patch.object(unqueue.os, "pidfd_open", return_value=900, create=True), \
                patch.object(unqueue.signal, "pidfd_send_signal", create=True) as send, \
                patch.object(unqueue.os, "close"), patch.object(unqueue, "processes", return_value=([], [])):
            with self.assertRaisesRegex(RuntimeError, "changed"):
                unqueue.stop_preflight(100, self.argv, self.project)
            send.assert_not_called()

    def test_wrapper_timeout_never_forces_exit_or_starts_replacement(self):
        with patch.object(unqueue, "processes", return_value=([], [101])), \
                patch.object(unqueue, "stop_preflight") as stop, self.assertRaisesRegex(RuntimeError, "still exiting"):
            unqueue.unqueue(self.project, timeout=0)
        stop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
