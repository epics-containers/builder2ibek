from pathlib import Path
from typing import Optional

import typer
from apischema import serialize
from ruamel.yaml import YAML

from builder2ibek import __version__
from builder2ibek.builder import Builder
from builder2ibek.dispatch import dispatch

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
    xml: Path = typer.Argument(..., help="Filename of the builder XML file"),
    yaml: Optional[Path] = typer.Option(..., help="Output file"),
):
    """Convert a single builder XML file into a single ibek YAML"""
    builder = Builder()
    builder.load(xml)
    ioc = dispatch(builder)

    if not yaml:
        yaml = xml.absolute().with_suffix("yaml")

    data = serialize(ioc)
    with yaml.open("w") as stream:
        YAML().dump(data, stream)


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
