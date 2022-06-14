from pathlib import Path
from typing import Optional

import typer
from ruamel.yaml import YAML

from builder2ibek import __version__

cli = typer.Typer()
yaml = YAML()


def version_callback(value: bool):
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@cli.callback()
def main(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        callback=version_callback,
        is_eager=True,
        help="Print the version of builder2ibek and exit",
    )
):
    """Convert build XML to ibek YAML"""


@cli.command()
def file(
    input: Path = typer.Argument(..., help="Filename of the builder XML file"),
    output: Path = typer.Option(..., help="Output file"),
):
    """Convert a single builder XML file into a single ibek YAML"""


@cli.command()
def beamline(
    input: Path = typer.Argument(..., help="Path to root folder BLXX-BUILDER"),
    output: Path = typer.Argument(..., help="Output root folder"),
):
    """
    Convert a beamline's IOCs from builder to ibek
    """


# test with:
#     pipenv run python -m builder2ibek
if __name__ == "__main__":
    cli()
