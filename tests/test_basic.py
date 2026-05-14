from __future__ import annotations

from clotho import __version__
from clotho.cli import main


def test_package_has_version() -> None:
    assert isinstance(__version__, str)
    assert __version__


def test_cli_version(capsys) -> None:
    exit_code = main(["version"])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out.strip() == __version__
