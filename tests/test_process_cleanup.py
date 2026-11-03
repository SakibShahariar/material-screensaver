"""Focused tests for descendant-only WebKit process cleanup."""
import os
import signal
import tempfile
import unittest
from unittest import mock

import support


class TestWebKitProcessCleanup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctl = support.load_ctl()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.proc_root = self.temp.name
        self.kills = []
        self.scheduled = []

    def tearDown(self):
        self.temp.cleanup()

    def _write_process(self, pid, ppid, cmd, start_time):
        process_dir = os.path.join(self.proc_root, str(pid))
        task_dir = os.path.join(process_dir, "task", str(pid))
        os.makedirs(task_dir, exist_ok=True)
        # /proc/PID/stat fields 3..22: state, ppid, ..., starttime.
        fields = ["S", str(ppid)] + ["0"] * 17 + [str(start_time)]
        with open(os.path.join(process_dir, "stat"), "w", encoding="utf-8") as stream:
            stream.write(f"{pid} (test process) {' '.join(fields)}")
        with open(os.path.join(process_dir, "cmdline"), "wb") as stream:
            stream.write(cmd.replace(" ", "\0").encode())

    def _write_children(self, pid, children, thread_id=None):
        thread_id = str(pid) if thread_id is None else str(thread_id)
        task_dir = os.path.join(self.proc_root, str(pid), "task", thread_id)
        os.makedirs(task_dir, exist_ok=True)
        with open(os.path.join(task_dir, "children"), "w", encoding="ascii") as stream:
            stream.write(" ".join(str(child) for child in children))

    def _kill(self, pid, sig):
        self.kills.append((pid, sig))

    def _run_cleanup(self):
        return self.ctl._kill_orphan_webkit(
            proc_root=self.proc_root,
            root_pid=100,
            kill_process=self._kill,
            schedule_force_kill=self.scheduled.append,
        )

    def _make_nested_tree(self):
        self._write_process(100, 1, "screensaver-viewer", 1000)
        self._write_process(101, 100, "WebKitNetworkProcess", 1001)
        self._write_process(102, 101, "WebKitWebProcess", 1002)
        self._write_process(103, 1, "WebKitWebProcess unrelated", 1003)
        self._write_children(100, [101, 103])
        self._write_children(101, [102])
        self._write_children(102, [])
        self._write_children(103, [])

    def test_walks_nested_descendants_without_scanning_unrelated_processes(self):
        self._make_nested_tree()
        self.assertEqual(self._run_cleanup(), 2)
        self.assertEqual(
            self.kills,
            [(101, signal.SIGTERM), (102, signal.SIGTERM)],
        )
        self.assertEqual(len(self.scheduled), 1)

    def test_escalates_only_unchanged_process_identity(self):
        self._make_nested_tree()
        self._run_cleanup()
        self.scheduled[0]()
        self.assertEqual(
            self.kills,
            [
                (101, signal.SIGTERM),
                (102, signal.SIGTERM),
                (101, signal.SIGKILL),
                (102, signal.SIGKILL),
            ],
        )

    def test_delayed_kill_skips_reused_pid(self):
        self._make_nested_tree()
        self._run_cleanup()
        # Simulate PID 101 exiting and the number being reused by another app.
        self._write_process(101, 100, "unrelated-browser", 9001)
        self.scheduled[0]()
        self.assertEqual(
            self.kills,
            [(101, signal.SIGTERM), (102, signal.SIGTERM)],
        )

    def test_term_skips_pid_reused_after_discovery(self):
        self._make_nested_tree()
        read_process = self.ctl._read_proc_process
        child_reads = 0

        def reuse_before_signal(proc_root, pid):
            nonlocal child_reads
            info = read_process(proc_root, pid)
            if pid == 101:
                child_reads += 1
                if child_reads == 4:
                    return info[0], "unrelated-browser", "9001"
            return info

        with mock.patch.object(self.ctl, "_read_proc_process", side_effect=reuse_before_signal):
            self._run_cleanup()
        self.assertEqual(self.kills, [])

    def test_ignores_stale_child_entry_that_is_no_longer_ours(self):
        self._write_process(100, 1, "screensaver-viewer", 1000)
        self._write_process(101, 1, "WebKitWebProcess", 1001)
        self._write_children(100, [101])
        self.assertEqual(self._run_cleanup(), 0)
        self.assertEqual(self.kills, [])

    def test_finds_children_spawned_by_non_leader_thread(self):
        self._write_process(100, 1, "screensaver-viewer", 1000)
        self._write_process(104, 100, "WebKitWebProcess", 1004)
        self._write_children(100, [], thread_id=100)
        self._write_children(100, [104], thread_id=1007)
        self._write_children(104, [])
        self.assertEqual(self._run_cleanup(), 1)
        self.assertEqual(self.kills, [(104, signal.SIGTERM)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
