import re
from pathlib import Path
from typing import Optional

import typer
from ruamel.yaml import YAML, CommentedMap

from builder2ibek import __version__
from builder2ibek.builder import Builder
from builder2ibek.convert import dispatch

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
    ),
):
    """Convert build XML to ibek YAML"""


@cli.command()
def file(
    xml: Path = typer.Argument(..., help="Filename of the builder XML file"),
    yaml: Optional[Path] = typer.Option(..., help="Output file"),
    schema: Optional[str] = typer.Option(
        "/epics/ibek-defs/ioc.schema.json",
        help="Generic IOC schema (added to top of the yaml output)",
    ),
):
    def tidy_up(yaml):
        # add blank lines between major fields
        for field in [
            "ioc_name",
            "description",
            "entities",
            "  - type",
        ]:
            yaml = re.sub(rf"(\n{field})", "\n\\g<1>", yaml)
        return yaml

    """Convert a single builder XML file into a single ibek YAML"""
    builder = Builder()
    builder.load(xml)
    ioc = dispatch(builder, xml)

    if not yaml:
        yaml = xml.absolute().with_suffix("yaml")

    ruamel = YAML()

    ruamel.default_flow_style = False
    # this attribute is for internal use, remove before serialising
    delattr(ioc, "source_file")
    yaml_map = CommentedMap(ioc.model_dump())

    # add support yaml schema
    yaml_map.yaml_add_eol_comment(f"yaml-language-server: $schema={schema}", column=0)

    ruamel.indent(mapping=2, sequence=4, offset=2)

    with yaml.open("w") as stream:
        ruamel.dump(yaml_map, stream, transform=tidy_up)


@cli.command()
def beamline(
    input: Path = typer.Argument(..., help="Path to root folder BLXX-BUILDER"),
    output: Path = typer.Argument(..., help="Output root folder"),
):
    """
    Convert a beamline's IOCs from builder to ibek
    """
    typer.echo("Not implemented yet")
    raise typer.Exit(code=1)


if __name__ == "__main__":
    cli()
