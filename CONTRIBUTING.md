# Contributing

Thanks for your interest. The project is in early development, so please open an issue before starting a larger change.

## Setup

```sh
uv sync
```

## Before opening a pull request

All of these must pass. CI runs them on Linux and Windows with Python 3.12 and 3.14:

```sh
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

## How we work

- **Test first.** Write a failing test for the behavior, then make it pass. Every bug fix comes with a test that reproduces the bug.
- **Synthetic fixtures only.** Tests build fake `~/.claude` and `~/.codex` trees inside `tmp_path`. Never read the real home directory in a test.
- **No personal data.** Never commit real session excerpts, real paths, usernames, or email addresses, in code, tests, fixtures, or docs.
- **Expected failures are return values.** Functions return a result or an error value. Exceptions are only for the unexpected.
- **English** for code, messages, docs, and commit messages.
- **Commit messages** follow `<type>: <description>`, where the type is `feature`, `fix`, `refactor`, `chore`, `test`, or `docs`.
