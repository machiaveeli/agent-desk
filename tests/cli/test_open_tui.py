"""`agent-desk` with no command opens the TUI. A fake runner stands in for the real app."""

from typer.testing import CliRunner

from agent_desk.cli.main import Dependencies, app
from agent_desk.domain.errors import ConfigError
from agent_desk.services.catalog import CatalogService
from agent_desk.services.resume import ResumeService
from agent_desk.services.trash import TrashService
from fixtures.tui_app import make_unusable_trash

EXIT_FAILURE = 1

runner = CliRunner()


class RecordingTuiRunner:
    def __init__(self) -> None:
        self.catalogs: list[CatalogService] = []
        self.resume_services: list[ResumeService] = []
        self.trashes: list[TrashService] = []

    def __call__(self, catalog: CatalogService, resume: ResumeService, trash: TrashService) -> None:
        self.catalogs.append(catalog)
        self.resume_services.append(resume)
        self.trashes.append(trash)


def make_dependencies(catalog: CatalogService, run_tui: RecordingTuiRunner) -> Dependencies:
    """The trash is injected too: the default one would read the real config."""
    trash = make_unusable_trash(catalog)
    return Dependencies(load_catalog=lambda: catalog, run_tui=run_tui, load_trash=lambda _: trash)


def test_no_command_opens_the_tui_with_the_catalog_and_the_trash() -> None:
    catalog = CatalogService([])
    run_tui = RecordingTuiRunner()
    dependencies = make_dependencies(catalog, run_tui)

    result = runner.invoke(app, [], obj=dependencies)

    assert result.exit_code == 0
    assert (run_tui.catalogs, run_tui.trashes) == ([catalog], [dependencies.load_trash(catalog)])


def test_a_trash_config_error_is_reported_instead_of_opening_the_tui() -> None:
    error = ConfigError("trash.retention_days", "out_of_range", "'trash.retention_days' bad")
    run_tui = RecordingTuiRunner()
    dependencies = Dependencies(
        load_catalog=lambda: CatalogService([]), run_tui=run_tui, load_trash=lambda _: error
    )

    result = runner.invoke(app, [], obj=dependencies)

    assert (result.exit_code, run_tui.catalogs) == (EXIT_FAILURE, [])


def test_a_command_does_not_open_the_tui() -> None:
    run_tui = RecordingTuiRunner()

    result = runner.invoke(app, ["projects"], obj=make_dependencies(CatalogService([]), run_tui))

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
