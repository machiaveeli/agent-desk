from importlib.metadata import version

from typer.testing import CliRunner

from agent_desk.cli.main import app

runner = CliRunner()


def test_version_option_prints_package_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == f"agent-desk {version('agent-desk')}"
