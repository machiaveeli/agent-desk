import json
from pathlib import Path

import pytest

from agent_desk.domain.models import Session
from agent_desk.providers.claude_code import ClaudeCodeProvider
from agent_desk.providers.processes import NOT_RUNNING, ProcessState
from fixtures.claude_tree import FAKE_PROC_START, ClaudeTree

SESSION_ID = "00000000-0000-4000-8000-000000000001"
OTHER_SESSION_ID = "00000000-0000-4000-8000-000000000002"
CWD = "/work/app"
PID = 4242
RUNNING_SAME_START = ProcessState(is_running=True, start_marker=FAKE_PROC_START)
RUNNING_OTHER_START = ProcessState(is_running=True, start_marker="999999")
RUNNING_UNKNOWN_START = ProcessState(is_running=True, start_marker=None)


def make_session(claude_tree: ClaudeTree) -> Session:
    path = claude_tree.root / "projects" / "-work-app" / f"{SESSION_ID}.jsonl"
    return Session("claude-code", SESSION_ID, path, None, Path(CWD))


def make_provider_where_every_pid_runs(claude_tree: ClaudeTree) -> ClaudeCodeProvider:
    return ClaudeCodeProvider(
        root=claude_tree.root, inspect_process=lambda pid: RUNNING_UNKNOWN_START
    )


def make_provider(claude_tree: ClaudeTree, state: ProcessState) -> ClaudeCodeProvider:
    def inspect_process(pid: int) -> ProcessState:
        return state if pid == PID else NOT_RUNNING

    return ClaudeCodeProvider(root=claude_tree.root, inspect_process=inspect_process)


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (RUNNING_SAME_START, True),
        (RUNNING_UNKNOWN_START, True),
        (RUNNING_OTHER_START, False),
        (NOT_RUNNING, False),
    ],
    ids=[
        "running-and-same-start",
        "running-and-start-unknown-to-the-os",
        "pid-reused-by-another-process",
        "process-gone",
    ],
)
def test_session_is_active_only_while_its_own_process_runs(
    claude_tree: ClaudeTree, state: ProcessState, expected: bool
) -> None:
    claude_tree.add_active_session_file(pid=PID, session_id=SESSION_ID, cwd=CWD)

    assert make_provider(claude_tree, state).is_active(make_session(claude_tree)) is expected


@pytest.mark.parametrize(
    "record",
    [
        {"pid": PID, "sessionId": SESSION_ID},
        {"pid": PID, "sessionId": SESSION_ID, "procStart": 424242},
    ],
    ids=["no-start-time", "start-time-not-text"],
)
def test_record_without_a_usable_start_time_trusts_the_running_pid(
    claude_tree: ClaudeTree, record: dict[str, object]
) -> None:
    # Erring towards "active" is the safe side: an active session must never be modified.
    claude_tree.add_raw_session_file(f"{PID}.json", json.dumps(record))

    provider = make_provider(claude_tree, RUNNING_OTHER_START)

    assert provider.is_active(make_session(claude_tree)) is True


def test_record_of_another_session_does_not_make_it_active(claude_tree: ClaudeTree) -> None:
    claude_tree.add_active_session_file(pid=PID, session_id=OTHER_SESSION_ID, cwd=CWD)

    provider = make_provider(claude_tree, RUNNING_SAME_START)

    assert provider.is_active(make_session(claude_tree)) is False


def test_session_without_any_record_is_not_active(claude_tree: ClaudeTree) -> None:
    claude_tree.root.mkdir(parents=True)

    provider = make_provider(claude_tree, RUNNING_SAME_START)

    assert provider.is_active(make_session(claude_tree)) is False


@pytest.mark.parametrize(
    ("file_name", "text"),
    [
        ("1.json", "{not json"),
        ("2.json", "[1, 2]"),
        ("3.json", json.dumps({"pid": "4242", "sessionId": SESSION_ID})),
        ("4.json", json.dumps({"pid": True, "sessionId": SESSION_ID})),
        ("5.json", json.dumps({"pid": PID, "sessionId": 7})),
        (f"{PID}.abc.key", "fake-key"),
    ],
    ids=[
        "malformed-json",
        "not-an-object",
        "pid-as-text",
        "pid-as-bool",
        "session-id-not-text",
        "key-file",
    ],
)
def test_unreadable_records_are_ignored(claude_tree: ClaudeTree, file_name: str, text: str) -> None:
    claude_tree.add_raw_session_file(file_name, text)

    provider = make_provider_where_every_pid_runs(claude_tree)

    assert provider.is_active(make_session(claude_tree)) is False


def test_a_valid_record_is_found_among_unreadable_ones(claude_tree: ClaudeTree) -> None:
    claude_tree.add_raw_session_file("1.json", "{not json")
    claude_tree.add_active_session_file(pid=PID, session_id=SESSION_ID, cwd=CWD)

    provider = make_provider(claude_tree, RUNNING_SAME_START)

    assert provider.is_active(make_session(claude_tree)) is True
