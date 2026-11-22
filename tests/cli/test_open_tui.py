"""`agent-desk` with no command opens the TUI. A fake runner stands in for the real app."""

from typer.testing import CliRunner

from agent_desk.cli.main import Dependencies, app
from agent_desk.domain.errors import ConfigError
from agent_desk.services.catalog import CatalogService

EXIT_FAILURE = 1

runner = CliRunner()


class RecordingTuiRunner:
    def __init__(self) -> None:
        self.catalogs: list[CatalogService] = []

    def __call__(self, catalog: CatalogService) -> None:
        self.catalogs.append(catalog)


def test_no_command_opens_the_tui_with_the_catalog() -> None:
    catalog = CatalogService([])
    run_tui = RecordingTuiRunner()

    result = runner.invoke(app, [], obj=Dependencies(load_catalog=lambda: catalog, run_tui=run_tui))

    assert result.exit_code == 0
    assert run_tui.catalogs == [catalog]


def test_a_command_does_not_open_the_tui() -> None:
    run_tui = RecordingTuiRunner()

    result = runner.invoke(
        app,
        ["projects"],
        obj=Dependencies(load_catalog=lambda: CatalogService([]), run_tui=run_tui),
    )

    assert result.exit_code == 0
    assert run_tui.catalogs == []


def test_config_error_is_reported_instead_of_opening_the_tui() -> None:
    def load_catalog() -> ConfigError:
        return ConfigError("trash.retention_days", "wrong_type", "'trash' must be a table")

    run_tui = RecordingTuiRunner()

    result = runner.invoke(app, [], obj=Dependencies(load_catalog=load_catalog, run_tui=run_tui))

    assert result.exit_code == EXIT_FAILURE
    assert result.stderr == "Error: config: 'trash' must be a table\n"
    assert run_tui.catalogs == []
