import re
from pathlib import Path

import typer

from builder2ibek import __version__

cli = typer.Typer()


def version_callback(value: bool):
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@cli.callback()
def main(
    version: bool | None = typer.Option(
        None,
        "--version",
        callback=version_callback,
        is_eager=True,
        help="Print the version of builder2ibek and exit",
    ),
):
    """
    Convert DLS autosave DB template comments into autosave req files
    """


regex_autosave = [
    re.compile(rf'# *% *autosave *{n} *(.*)[\s\S]*?record *\(.*, *"?([^"]*)"?\)')
    for n in range(3)
]


@cli.command()
def db_files(
    out_folder: Path = typer.Option(
        ".", help="Output folder to write autosave request files"
    ),
    db_list: list[Path] = typer.Argument(
        ..., help="List of autosave req files to link "
    ),
):
    """
    Convert DLS autosave DB template comments into autosave req files
    """
    parse_templates(out_folder, db_list)


def parse_templates(out_folder: Path, db_list: list[Path]):
    """
    DLS has 3 autosave levels
        0 = save on pass 0
        1 = save on pass 0 and 1
        2 = save on pass 1 only

    Areadetector and other support modules use:
        template_name_positions.req for save on pass 0
        template_name_settings.req for save on pass 0 and pass 1
        the autosave docs seem to back the idea that pass 1 only is not used

    So this translation will make
        0 => template_name_positions.req
        1 => template_name_settings.req
    """
    for db in db_list:
        text = db.read_text()

        positions = set()
        settings = set()
        for n in range(3):
            match n:
                case 0:
                    this_set = positions
                case 1 | 2:
                    this_set = settings
            for match in regex_autosave[n].finditer(text):
                this_set.add(f"{match.group(2)} {match.group(1)}")

        stem = db.stem
        req_file = out_folder / f"{stem}_positions.req"
        req_file.write_text("\n".join(positions))
        req_file = out_folder / f"{stem}_settings.req"
        req_file.write_text("\n".join(settings))
