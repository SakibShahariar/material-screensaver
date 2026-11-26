"""Direct coverage for the extracted procfs reader module."""
import os
from pathlib import Path
import tempfile
import unittest

import support

import material_screensaver_process as proc


class TestProcessModule(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = self.temp.name

    def tearDown(self):
        self.temp.cleanup()

    def _write_process(self, pid, ppid, cmd, start):
        directory = os.path.join(self.root, str(pid))
        os.makedirs(os.path.join(directory, "task", str(pid)), exist_ok=True)
        fields = ["S", str(ppid)] + ["0"] * 17 + [str(start)]
        with open(os.path.join(directory, "stat"), "w", encoding="utf-8") as handle:
            handle.write(f"{pid} (test process) {' '.join(fields)}")
        with open(os.path.join(directory, "cmdline"), "wb") as handle:
            handle.write(cmd.replace(" ", "\0").encode())

    def _write_children(self, pid, children, thread=None):
        thread = str(pid) if thread is None else str(thread)
        path = os.path.join(self.root, str(pid), "task", thread, "children")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="ascii") as handle:
            handle.write(" ".join(str(child) for child in children))

    def test_reads_parent_command_and_start_time(self):
        self._write_process(100, 1, "WebKit WebProcess", 1234)
        self.assertEqual(
            proc.read_proc_process(self.root, 100), (1, "WebKit WebProcess", "1234"))

    def test_missing_process_returns_none(self):
        self.assertIsNone(proc.read_proc_process(self.root, 999))

    def test_child_pids_come_from_every_thread(self):
        self._write_children(100, [101], thread=100)
        self._write_children(100, [102, 103], thread=107)
        os.makedirs(os.path.join(self.root, "100", "task", "not-a-thread"), exist_ok=True)
        self.assertEqual(proc.proc_child_pids(self.root, 100), {101, 102, 103})

    def test_discovers_nested_descendants_only(self):
        self._write_process(100, 1, "viewer", 1000)
        self._write_process(101, 100, "WebKitNetworkProcess", 1001)
        self._write_process(102, 101, "WebKitWebProcess", 1002)
        self._write_process(103, 1, "unrelated", 1003)
        self._write_children(100, [101, 103])
        self._write_children(101, [102])
        self._write_children(102, [])
        self._write_children(103, [])
        found = proc.discover_proc_descendants(self.root, 100)
        self.assertEqual(
            [(row[0], row[1]) for row in found], [(101, 100), (102, 101)])

    def test_control_script_keeps_thin_wrappers(self):
        source = (Path(support.REPO_ROOT) / "bin" / "material-screensaver-ctl.py").read_text(
            encoding="utf-8")
        self.assertIn("import material_screensaver_process as process_store", source)
        self.assertIn("_read_proc_process = process_store.read_proc_process", source)
        self.assertIn("process_store.discover_proc_descendants(", source)
        self.assertNotIn("def _proc_child_pids(proc_root, pid):", source)

    def test_injected_readers_are_used(self):
        calls = []
        def fake_reader(root, pid):
            calls.append(pid)
            if pid == 100:
                return (1, "viewer", "start")
            if pid == 101:
                return (100, "helper", "child-start")
            return None
        result = proc.discover_proc_descendants(
            self.root, 100, read_process=fake_reader,
            child_pids=lambda root, pid: {101} if pid == 100 else set())
        self.assertEqual(len(result), 1)
        self.assertIn(101, calls)


if __name__ == "__main__":
    unittest.main(verbosity=2)
