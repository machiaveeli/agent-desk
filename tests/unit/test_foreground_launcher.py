"""Runs real child processes, so it also checks the Windows CI job."""

import signal
import sys
from collections.abc import Iterator
from pathlib import Path
from types import FrameType

import pytest

from agent_desk.services.resume import run_in_foreground

EXIT_CODE = 3


def sentinel_handler(signal_number: int, frame: FrameType | None) -> None:
    return None


@pytest.fixture
def known_ctrl_c_handler() -> Iterator[None]:
    """A handler of our own, so a leak from an earlier call cannot pass for a restore."""
    original = signal.signal(signal.SIGINT, sentinel_handler)
    yield
    signal.signal(signal.SIGINT, original)


def test_child_exit_code_is_passed_through(tmp_path: Path) -> None:
    argv = [sys.executable, "-c", f"raise SystemExit({EXIT_CODE})"]

    assert run_in_foreground(argv, tmp_path) == EXIT_CODE


def test_child_runs_inside_the_given_cwd(tmp_path: Path) -> None:
    argv = [sys.executable, "-c", "open('marker.txt', 'w').close()"]

    run_in_foreground(argv, tmp_path)

    assert (tmp_path / "marker.txt").is_file()


@pytest.mark.usefixtures("known_ctrl_c_handler")
def test_ctrl_c_handling_is_restored_after_the_child_exits(tmp_path: Path) -> None:
    run_in_foreground([sys.executable, "-c", "pass"], tmp_path)

    assert signal.getsignal(signal.SIGINT) is sentinel_handler


@pytest.mark.usefixtures("known_ctrl_c_handler")
def test_ctrl_c_handling_is_restored_when_the_child_cannot_start(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        run_in_foreground([str(tmp_path / "missing-program")], tmp_path)

    assert signal.getsignal(signal.SIGINT) is sentinel_handler


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals; Windows sends Ctrl+C events")
def test_ctrl_c_while_the_child_runs_does_not_stop_agent_desk(tmp_path: Path) -> None:
    # The terminal sends Ctrl+C to both processes; only the resumed AI CLI should react.
    child = "import os, signal, time; os.kill(os.getppid(), signal.SIGINT); time.sleep(0.2)"

    assert run_in_foreground([sys.executable, "-c", child], tmp_path) == 0
