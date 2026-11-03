"""Every test runs on made-up settings, with no release tree and no site data."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import classify  # noqa: E402
import edl  # noqa: E402
import fielddefs  # noqa: E402
import release  # noqa: E402
import render  # noqa: E402
import settings  # noqa: E402

RECORD_FIELDS = {
    "ai": ["VAL", "RVAL"],
    "ao": ["VAL", "HOPR", "LOPR"],
    "bo": ["VAL", "ZNAM", "ONAM"],
    "mbbo": ["VAL", "ZRST"],
    "calcout": ["VAL", "CALC"],
    "motor": ["VAL", "RBV", "JOGF", "JOGR", "STOP", "HOMF", "HOMR", "VELO"],
}


def dbd_folder(root: Path) -> Path:
    folder = root / "dbd"
    folder.mkdir()
    (folder / "dbCommon.dbd").write_text("field(DESC,DBF_STRING)\nfield(SCAN,DBF_MENU)\nfield(PROC,DBF_UCHAR)\nfield(DISA,DBF_SHORT)\nfield(SEVR,DBF_MENU)\n")
    for rtype, names in RECORD_FIELDS.items():
        body = "".join(f"\tfield({n},DBF_DOUBLE) {{\n\t}}\n" for n in names)
        (folder / f"{rtype}Record.dbd").write_text(f"recordtype({rtype}) {{\n{body}}}\n")
    return folder


@pytest.fixture(autouse=True)
def made_up_site(tmp_path_factory):
    root = tmp_path_factory.mktemp("site")
    real_msi = settings.Settings().msi_path()
    s = settings.Settings(
        repos={"one": root / "one", "two": root / "two"},
        prod=[],
        work=[],
        older=[],
        last_resort_modules=[],
        base_dbd=dbd_folder(root),
        support_dbd_glob=str(root / "none" / "{}Record.dbd"),
        output=root / "out",
        sandbox=root / "sandbox",
        review=root / "review",
        status=root / "status",
    )
    s.msi = real_msi or root / "no-msi"
    (root / "status").mkdir()
    settings.install(s)
    for cached in (fielddefs._common, fielddefs._file, fielddefs._anywhere, fielddefs.fields_of, release.deps, classify.site_rules, render.edm_colors):
        cached.cache_clear()
    edl._CACHE.clear()
    yield s
