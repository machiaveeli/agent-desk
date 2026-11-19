import json
from datetime import datetime
from pathlib import Path

from fixtures.codex_tree import (
    CORRUPTED_LINE,
    CodexTree,
    timestamp_at,
    user_message,
)

SESSION_ID = "00000000-0000-4000-8000-0000000000c1"
CWD = "/work/my-app"
CREATED = datetime(2026, 1, 1, 10, 0, 0)


def read_lines(path: Path) -> list[str]:
    return path.read_bytes().decode("utf-8").split("\n")


def test_rollout_lands_in_the_dated_sessions_folder_with_codex_file_name(
    codex_tree: CodexTree,
) -> None:
    path = codex_tree.add_session(SESSION_ID, cwd=CWD, created=CREATED, lines=[])

    # Codex's own rollout_path(): sessions/YYYY/MM/DD/rollout-<YYYY-MM-DDThh-mm-ss>-<id>.jsonl
    expected_name = f"rollout-2026-01-01T10-00-00-{SESSION_ID}.jsonl"
    assert path == codex_tree.root / "sessions" / "2026" / "01" / "01" / expected_name


def test_first_line_is_the_session_meta_with_id_and_cwd(codex_tree: CodexTree) -> None:
    path = codex_tree.add_session(SESSION_ID, cwd=CWD, created=CREATED, lines=[])

    meta = json.loads(read_lines(path)[0])
    assert meta["type"] == "session_meta"
    assert meta["payload"]["id"] == SESSION_ID
    assert meta["payload"]["cwd"] == CWD
    assert meta["payload"]["history_mode"] == "legacy"


def test_lines_follow_the_meta_one_per_line_and_broken_lines_stay_verbatim(
    codex_tree: CodexTree,
) -> None:
    path = codex_tree.add_session(
        SESSION_ID, cwd=CWD, created=CREATED, lines=[user_message("hi"), CORRUPTED_LINE]
    )

    _meta, first, second, trailing = read_lines(path)
    assert json.loads(first)["payload"] == {"type": "user_message", "message": "hi"}
    assert second == CORRUPTED_LINE
    assert trailing == ""


def test_paginated_rollout_numbers_every_json_line_with_an_ordinal(
    codex_tree: CodexTree,
) -> None:
    path = codex_tree.add_session(
        SESSION_ID,
        cwd=CWD,
        created=CREATED,
        lines=[user_message("hi")],
        history_mode="paginated",
    )

    meta, first, _trailing = read_lines(path)
    assert json.loads(meta)["payload"]["history_mode"] == "paginated"
    assert [json.loads(meta)["ordinal"], json.loads(first)["ordinal"]] == [0, 1]


def test_thread_names_are_appended_to_the_session_index(codex_tree: CodexTree) -> None:
    codex_tree.add_thread_name(SESSION_ID, "First name", minute=0)
    path = codex_tree.add_thread_name(SESSION_ID, "Second name", minute=1)

    assert path == codex_tree.root / "session_index.jsonl"
    first, second, _trailing = read_lines(path)
    assert json.loads(first)["thread_name"] == "First name"
    assert json.loads(second) == {
        "id": SESSION_ID,
        "thread_name": "Second name",
        "updated_at": timestamp_at(1),
    }


def test_timestamps_are_iso_utc_with_milliseconds_minutes_after_a_fixed_base() -> None:
    assert timestamp_at(5) == "2026-01-01T10:05:00.000Z"
