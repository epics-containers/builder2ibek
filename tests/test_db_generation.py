"""
Tests that validate that validate that ibek's interpretation of the yaml files
auto generated from the xml files is correct.

These tests run ibek against the IOC yaml files that are checked in test_convert.
Then validate the resulting db files against the expected db files that come
from the orginal builder project (and thus were gereated by xmlbuilder
from the xml files).

IMPORTANT: These tests are also checking that current ibek-support and
ibek-support-dls are providing the correct support.yaml to enable the conversion.
HENCE: these suite of tests are a good place to debug the latest ibek-support,
ibek and builder2ibek combination.
"""

import os
import re
import subprocess
from pathlib import Path

import ibek.runtime_cmds.commands
from ibek.globals import GLOBALS
from pytest_mock import MockerFixture

root_dir = Path(__file__).parent.parent
samples_dir = root_dir / "tests" / "samples"
templates_dir = samples_dir / "templates"

epics_root = Path("/tmp/builder2ibek/epics")
runtime = epics_root / "runtime"
out_subst = runtime / "ioc.subst"
out_db = runtime / "ioc.db"

sample_db_files = [
    ("BL04I-VA-IOC-01", samples_dir / "bl04i-va-ioc-01.db"),
]

macros = re.compile(r"\$.*\/db\/")


def test_db_generation(samples: Path, mocker: MockerFixture):
    # patch the global EPICS_ROOT to point to the temporary folder
    mocker.patch.object(GLOBALS, "_EPICS_ROOT", epics_root)
    Path.mkdir(runtime, exist_ok=True, parents=True)

    support_yamls = list(root_dir.glob("ibek-support/*/*.ibek.support.yaml"))
    support_yamls += root_dir.glob("ibek-support-dls/*/*.ibek.support.yaml")

    for ioc_name, sample_db in sample_db_files:
        os.environ["IOC_NAME"] = ioc_name
        sample_yaml = Path(str(sample_db.with_suffix(".yaml")).lower())
        ibek.runtime_cmds.commands.generate(sample_yaml, support_yamls)

        # remove all path macros in the substition file
        subst = out_subst.read_text()
        subst = macros.sub("", subst)
        out_subst.write_text(subst)

        # use msi to expand the substition file into a db file
        result = subprocess.run(
            [
                "msi",
                f"-S{out_subst}",
                f"-I{templates_dir}",
                f"-o{out_db}",
            ],
            stderr=subprocess.STDOUT,
            env=os.environ,
        )
        assert result.returncode == 0, result.stdout

        # TODO
        # verify the generated db againt the expected db
