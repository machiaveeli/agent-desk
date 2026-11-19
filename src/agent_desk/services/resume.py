"""Resumes a session in its provider's own CLI, in the session's cwd, in this terminal."""

import signal
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import FrameType

from agent_desk.domain.errors import ResumeError
from agent_desk.services.catalog import CatalogService

type ExecutableFinder = Callable[[str], str | None]
type Launcher = Callable[[list[str], Path], int]


@dataclass(frozen=True)
class ResumePlan:
    """Everything checked, nothing started yet. An active session is still open somewhere
    else, so the caller asks the user before launching it."""

    argv: list[str]
    cwd: Path
    is_active: bool


@dataclass(frozen=True)
class ResumeService:
    catalog: CatalogService
    # Injected so tests decide what is on PATH and never start a real AI CLI.
    find_executable: ExecutableFinder
    launch: Launcher

    def prepare(self, session_id: str) -> ResumePlan | ResumeError:
        found = self.catalog.find_session(session_id)
        if found is None:
            return ResumeError("session_not_found", f"no session with id {session_id}.")
        session = found.summary.session
        if session.cwd is None:
            return ResumeError("cwd_unknown", "the session does not record its project folder.")
        if not session.cwd.is_dir():
            return ResumeError("cwd_missing", f"the project folder {session.cwd} no longer exists.")
        executable, *arguments = found.provider.resume_command(session)
        executable_path = self.find_executable(executable)
        if executable_path is None:
            return ResumeError("cli_not_found", f"'{executable}' is not installed or not on PATH.")
        return ResumePlan(
            argv=[executable_path, *arguments],
            cwd=session.cwd,
            is_active=found.provider.is_active(session),
        )

    def launch_plan(self, plan: ResumePlan) -> int:
        return self.launch(plan.argv, plan.cwd)


def run_in_foreground(argv: list[str], cwd: Path) -> int:
    """Runs the AI CLI in this terminal and waits; argv goes straight to the OS, no shell.

    Ctrl+C reaches both processes. While the child runs, agent-desk swallows it with a
    do-nothing handler, so only the AI CLI reacts. A handler, not SIG_IGN: an ignored signal
    would be inherited by the child, a handler is reset when the child starts."""
    previous = signal.signal(signal.SIGINT, ignore_signal)
    try:
        return subprocess.run(argv, cwd=cwd, check=False).returncode
    finally:
        signal.signal(signal.SIGINT, previous)


def ignore_signal(signal_number: int, frame: FrameType | None) -> None:
    return None
