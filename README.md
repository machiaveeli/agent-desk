# agent-desk

A terminal dashboard to browse and manage the data that AI coding CLIs keep on disk: sessions, memory files, and projects.

Tools like the Claude Code CLI and the Codex CLI store every session as plain files in your home directory (`~/.claude`, `~/.codex`). Over time these folders grow, projects get renamed or deleted, and there is no built-in way to see what is there. agent-desk reads those folders and gives you one place to list, read, resume, and clean them up.

## Status

**Early development. Not usable yet.**

What works today (Claude Code and Codex, read-only except for resume):
- `agent-desk` with no command opens the dashboard: every project in one table, with a text filter (`/`). Enter opens a project's sessions, which sort by date or size (`s`) and filter by title or date; running sessions are marked `active`. Enter on a session shows its condensed transcript (your messages, the replies, and one line per tool call), loaded in the background. `r` resumes the selected session in its own CLI (it asks first if the session is open somewhere else) and brings you back to the same place when you exit. Escape goes back, `?` shows the keys, `q` quits.
- `agent-desk projects`: every project with its session count, last activity, and size.
- `agent-desk sessions --project <path>`: the sessions of one project (`.` for the current folder).
- `--provider claude-code` or `--provider codex` on both commands shows only that CLI.
- `agent-desk resume <session-id>`: reopen a session in `claude` or `codex`, inside its project folder.
- `agent-desk --version`

Codex sessions are read from `~/.codex/sessions` (or `$CODEX_HOME`). Compressed (`.jsonl.zst`) and archived sessions are not shown yet.

Planned for the first release:
- A terminal dashboard, including a condensed transcript of each session.
- Move sessions to an app trash and restore them.
- Manage memory files.
- Find orphan projects and large folders, and clean them up with a preview.

Supported platforms: Linux and Windows, Python 3.12+.

## Your data stays local

agent-desk only reads and writes files on your machine. It makes no network calls and collects no telemetry.

It never edits the contents of a session. When it removes something, the files go to the app's own trash first, so you can restore them. It also refuses to touch a session that is still running.

## Install

You need [uv](https://docs.astral.sh/uv/) and Git. agent-desk is not on PyPI yet, so install it from GitHub, once per machine:

```sh
uv tool install git+https://github.com/machiaveeli/agent-desk.git
agent-desk
```

If the command is not found, run `uv tool update-shell` and open a new terminal.

The installed copy does not follow the repository by itself. To get the latest `main`, run:

```sh
uv tool upgrade agent-desk
```

If that keeps the old code, reinstall with `uv tool install --reinstall git+https://github.com/machiaveeli/agent-desk.git`. Remove with `uv tool uninstall agent-desk`.

## Run from source

You need [uv](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/machiaveeli/agent-desk.git
cd agent-desk
uv sync
uv run agent-desk
```

`uv run` works only inside this folder. To use your working copy from any terminal, run `uv tool install --editable .` The command then runs the code in this folder, so `git pull` is enough to update it. Run `uv tool install --editable . --reinstall` only when the dependencies change.

Run the checks:

```sh
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
