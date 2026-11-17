"""These tests talk to the real operating system, so they also run on the Windows CI job."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent_desk.providers.processes import NOT_RUNNING, inspect_process, read_start_time

INVALID_PIDS = [0, -1]


def run_and_wait_for_child() -> int:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


def test_current_process_is_running() -> None:
    assert inspect_process(os.getpid()).is_running is True


def test_finished_child_process_is_not_running() -> None:
    finished_pid = run_and_wait_for_child()

    assert inspect_process(finished_pid) == NOT_RUNNING


@pytest.mark.parametrize("pid", INVALID_PIDS, ids=["zero", "negative"])
def test_invalid_pid_is_not_running(pid: int) -> None:
    assert inspect_process(pid) == NOT_RUNNING


@pytest.mark.skipif(sys.platform != "linux", reason="start time comes from /proc on Linux")
def test_start_marker_on_linux_is_the_proc_start_time() -> None:
    # Independent of the code under test: the name of this python process has no spaces,
    # so a plain split finds field 22 (index 21).
    expected = Path("/proc/self/stat").read_text(encoding="ascii").split()[21]

    assert inspect_process(os.getpid()).start_marker == expected


@pytest.mark.parametrize(
    ("stat", "expected"),
    [
        ("7 (odd) name) S" + " 0" * 18 + " 4321 0 0", "4321"),
        ("7 (short) S" + " 0" * 18, None),
        ("7 (short) S 1 2", None),
    ],
    ids=["name-with-space-and-parenthesis", "one-field-short", "truncated-line"],
)
def test_start_time_is_read_after_the_process_name(stat: str, expected: str | None) -> None:
    assert read_start_time(stat) == expected
