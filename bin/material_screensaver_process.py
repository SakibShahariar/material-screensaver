"""Procfs helpers for discovering a process's own descendants.

These are pure readers: no signals, no GLib, no daemon state. The control script
keeps thin wrappers so existing call sites (and tests that patch them) continue
to work unchanged.
"""
from __future__ import annotations

import os


def read_proc_process(proc_root, pid):
    """Return ``(ppid, command, start_time)`` for one PID, or ``None``."""
    try:
        with open(os.path.join(proc_root, str(pid), "stat"), encoding="utf-8") as stream:
            stat = stream.read()
        # comm is parenthesized and may contain spaces or ')'.
        tail = stat[stat.rfind(")") + 2:].split()
        # tail starts at field 3 (state); ppid is field 4 and starttime is 22.
        if len(tail) < 20:
            return None
        ppid = int(tail[1])
        start_time = tail[19]
        with open(os.path.join(proc_root, str(pid), "cmdline"), "rb") as stream:
            raw_cmd = stream.read()
        cmd = raw_cmd.replace(b"\0", b" ").decode(errors="replace").strip()
        return ppid, cmd, start_time
    except (OSError, ValueError, IndexError):
        return None


def proc_child_pids(proc_root, pid):
    """Return child PIDs reported by every thread of one process."""
    task_dir = os.path.join(proc_root, str(pid), "task")
    try:
        thread_ids = os.listdir(task_dir)
    except OSError:
        return set()

    children = set()
    for thread_id in thread_ids:
        if not thread_id.isdigit():
            continue
        path = os.path.join(task_dir, thread_id, "children")
        try:
            with open(path, encoding="ascii") as stream:
                children.update(int(value) for value in stream.read().split())
        except (OSError, ValueError):
            continue
    return children


def discover_proc_descendants(proc_root, root_pid, read_process=None, child_pids=None):
    """Walk only this process tree using procfs child lists, not all of /proc.

    ``read_process`` and ``child_pids`` are injectable so callers can keep their
    own patch points in place.
    """
    read_process = read_process or read_proc_process
    child_pids = child_pids or proc_child_pids
    root_info = read_process(proc_root, root_pid)
    if root_info is None:
        return []

    pending = [(root_pid, root_info[2])]
    seen = {root_pid}
    descendants = []
    while pending:
        parent_pid, parent_start = pending.pop()
        parent_info = read_process(proc_root, parent_pid)
        if parent_info is None or parent_info[2] != parent_start:
            continue

        found_children = child_pids(proc_root, parent_pid)
        # Do not trust a child list if the parent exited and its PID was reused
        # while the list was being read.
        parent_after = read_process(proc_root, parent_pid)
        if parent_after is None or parent_after[2] != parent_start:
            continue

        for child_pid in found_children:
            if child_pid in seen:
                continue
            child_info = read_process(proc_root, child_pid)
            if child_info is None or child_info[0] != parent_pid:
                continue
            seen.add(child_pid)
            descendants.append((
                child_pid, parent_pid, parent_start, child_info[2], child_info[1]
            ))
            pending.append((child_pid, child_info[2]))
    return descendants
