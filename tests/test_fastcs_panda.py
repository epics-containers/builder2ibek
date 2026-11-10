"""
Tests for ADPandABlocks -> fastcs-pandablocks.

A dedicated PandA IOC (PandAs plus boilerplate) becomes one fastcs-pandablocks
instance in place of its ioc.yaml. A mixed IOC keeps an ioc.yaml for its other
devices, and each PandA becomes a sibling fastcs instance named from its PV
prefix. Every address here is loopback or a made-up hostname.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from ruamel.yaml import YAML

from builder2ibek import reconvert as rc
from builder2ibek.convert import convert_file
from builder2ibek.fastcs_panda import (
    CONTROLLER_TYPE,
    FASTCS_PANDABLOCKS_IMAGE,
    beamline_data_dir,
)

SCHEMA = "/epics/ibek-defs/ioc.schema.json"
VERSION = FASTCS_PANDABLOCKS_IMAGE.rsplit(":", 1)[1]
FASTCS_SCHEMA = (
    Path(__file__).parent / "samples" / "fastcs-pandablocks" / f"schema-{VERSION}.json"
)

DEDICATED = """<?xml version="1.0" ?>
<components arch="linux-x86_64">
  <EPICS_BASE.EpicsEnvSet key="EPICS_CA_MAX_ARRAY_BYTES" value="6000000"/>
  <devIocStats.devIocStatsHelper ioc="BL01C-EA-IOC-01" name="STATS"/>
  <autosave.Autosave bl="True" iocName="BL01C-EA-IOC-01" name="autosave"
    path="/tmp/autosave"/>
  <pvlogging.PvLogging name="pvlogging"/>
  <pvlogging.BlacklistPv name="BL01C-MO-PANDA-01:HDF5:FilePath"/>
  <ADPandABlocks.ADPandABlocks HOST="127.0.0.1" P="BL01C-MO-PANDA-01"
    PORT="PANDA1.DRV" R=":DRV:"/>
  <ADPandABlocks.MotorSync ENC_IND="1" MOTOR="BL01C-MO-STAGE-01:X"
    PANDA="PANDA1.DRV" name="PANDA1.XSYNC"/>
  <ADCore.NDAttrPlot ENABLED="1" NDARRAY_PORT="PANDA1.DRV"
    P="BL01C-MO-PANDA-01" PORT="PANDA1.PLT" R=":PLT:"/>
  <ADCore.NDPosPlugin ENABLED="1" NDARRAY_PORT="PANDA1.DRV"
    P="BL01C-MO-PANDA-01" PORT="PANDA1.POS" QUEUE="10000" R=":POS:"/>
  <ADCore.NDFileHDF5 ENABLED="1" NDARRAY_PORT="PANDA1.POS"
    P="BL01C-MO-PANDA-01" PORT="PANDA1.HDF" QUEUE="10000" R=":HDF5:"/>
  <EPICS_BASE.dbpf pv="BL01C-MO-PANDA-01:HDF5:NumFramesFlush" value="50"/>
  <EPICS_BASE.StartupCommand
    command="dbpf BL01C-MO-PANDA-01:HDF5:LazyOpen 1" post_init="True"/>
  {extra}
</components>
"""

SECOND_PANDA = """
  <ADPandABlocks.ADPandABlocks HOST="panda-02.invalid" P="BL01C-MO-PANDA-02"
    PORT="PANDA2.DRV" R=":DRV:"/>
  <ADCore.NDPosPlugin ENABLED="1" NDARRAY_PORT="PANDA2.DRV"
    P="BL01C-MO-PANDA-02" PORT="PANDA2.POS" R=":POS:"/>
"""

# a camera, a plugin on the camera's port and a record that reads a PandA PV
MIXED_DEVICES = """
  <ADAravis.aravisCamera CLASS="AVT_Manta_G235C" ID="127.0.0.1"
    P="BL01C-DI-CAM-01" PORT="CAM1.CAM" R=":CAM:"/>
  <ADCore.NDStats NDARRAY_PORT="CAM1.CAM" P="BL01C-DI-CAM-01" PORT="CAM1.STAT"
    R=":STAT:" HIST_SIZE="256" XSIZE="1000" YSIZE="1000"/>
  <EPICS_BASE.dbpf pv="BL01C-DI-CAM-01:STAT:EnableCallbacks" value="1"/>
  <BL01C.shutter_status INPUT="BL01C-MO-PANDA-01:TTLIN2:VAL" P="BL01C-EA-SHTR-01"/>
"""

IOC = "BL01C-EA-IOC-01"


def _services_repo(root: Path) -> Path:
    """A services repo with a .fastcs_ioc_template like the real ones"""
    services = root / "services"
    template = services / ".fastcs_ioc_template"
    (template / "config").mkdir(parents=True)
    (root / ".helm-shared" / "templates").mkdir(parents=True)
    (root / ".helm-shared" / "Chart.yaml").write_text("name: shared\n")
    os.symlink("../../.helm-shared/Chart.yaml", template / "Chart.yaml")
    os.symlink("../../.helm-shared/templates", template / "templates")
    (template / "values.yaml").write_text("image: REPLACE_WITH_FASTCS_IMAGE_URI\n")
    (template / "config" / "controller.yaml").write_text("# EXAMPLE\n")
    return services


def _xml(folder: Path, extra: str = "", name: str = IOC) -> Path:
    xml = folder / f"{name}.xml"
    xml.write_text(DEDICATED.format(extra=extra))
    return xml


def _load(path: Path) -> Any:
    return YAML(typ="safe").load(path.read_text())


def _conforms(value: Any, schema: dict, defs: dict, where: str = "") -> list[str]:
    """
    The JSON schema subset fastcs's generated schema uses: $ref, anyOf, const,
    type, properties, required, additionalProperties false and items.
    """
    if "$ref" in schema:
        schema = defs[schema["$ref"].rsplit("/", 1)[1]]
    if "anyOf" in schema:
        if any(not _conforms(value, s, defs, where) for s in schema["anyOf"]):
            return []
        return [f"{where}: matches none of anyOf"]
    if "const" in schema and value != schema["const"]:
        return [f"{where}: {value!r} is not {schema['const']!r}"]
    kind = schema.get("type")
    python_types = {"object": dict, "array": list, "string": str, "null": type(None)}
    if kind in python_types and not isinstance(value, python_types[kind]):
        return [f"{where}: {value!r} is not {kind}"]
    errors = []
    if kind == "object":
        props = schema.get("properties", {})
        errors += [
            f"{where}: missing {k}"
            for k in schema.get("required", [])
            if k not in value
        ]
        if schema.get("additionalProperties") is False:
            errors += [f"{where}: unexpected {k}" for k in value if k not in props]
        for k, v in value.items():
            if k in props:
                errors += _conforms(v, props[k], defs, f"{where}.{k}")
    if kind == "array":
        for i, item in enumerate(value):
            errors += _conforms(item, schema["items"], defs, f"{where}[{i}]")
    return errors


def _assert_valid_controller_yaml(path: Path):
    schema = json.loads(FASTCS_SCHEMA.read_text())
    assert _conforms(_load(path), schema, schema["$defs"]) == []


def test_vendored_schema_matches_image():
    # bumping FASTCS_PANDABLOCKS_IMAGE needs that release's schema vendored
    assert FASTCS_SCHEMA.is_file(), f"vendor {FASTCS_SCHEMA.name} for {VERSION}"


def test_schema_check_rejects_the_0_1_0_layout():
    # fastcs-pandablocks 0.1.0 took a single controller and a pv_prefix in the
    # transport; 0.2.x takes a list of controllers whose id is the prefix
    schema = json.loads(FASTCS_SCHEMA.read_text())
    old = {
        "controller": {"address": "127.0.0.1"},
        "transport": [
            {
                "epicspva": {"pv_prefix": "BL01C-MO-PANDA-01"},
                "gui": {"output_path": "/epics/opi/index.bob"},
            }
        ],
    }
    errors = _conforms(old, schema, schema["$defs"])
    assert ": missing controllers" in errors
    assert ": unexpected controller" in errors
    assert ".transport[0]: matches none of anyOf" in errors


def test_dedicated_becomes_one_fastcs_instance(tmp_path: Path):
    services = _services_repo(tmp_path)
    instance = services / IOC.lower()
    # an ibek instance as /ioc-convert and `ibek pattern add` leave it
    config = instance / "config"
    config.mkdir(parents=True)
    (config / "ioc.yaml").write_text("entities: []\n")
    (config / "ioc.schema.json").write_text("{}\n")
    (config / "foo.protocol").write_text("# vendored\n")
    (config / "hand-made.txt").write_text("not ours\n")
    (instance / "runtime-lock.yaml").write_text(
        "version: 2\npatterns:\n  foo:\n    files:\n"
        "      config/foo.protocol: sha256:0\n"
    )
    (instance / "values.yaml").write_text("image: REPLACE_WITH_IMAGE_URI\n")

    yaml = config / "ioc.yaml"
    result = convert_file(_xml(tmp_path), yaml, SCHEMA)

    assert not result.ioc_yaml_written
    assert result.fastcs_instances == [instance]
    assert [n for n in result.notes if "dedicated PandA IOC, no ioc.yaml" in n]

    # the ibek-only files go, anything else is kept and named
    for gone in ("ioc.yaml", "ioc.schema.json", "foo.protocol"):
        assert not (config / gone).exists()
    assert not (instance / "runtime-lock.yaml").exists()
    assert (config / "hand-made.txt").exists()
    (removed,) = [n for n in result.notes if "removed the ibek files" in n]
    assert "config/ioc.yaml" in removed and "runtime-lock.yaml" in removed
    assert "config/foo.protocol" in removed
    assert "left in config/: hand-made.txt" in removed

    controller = _load(instance / "config" / "controller.yaml")
    assert controller["controllers"] == [
        {"id": "BL01C-MO-PANDA-01", "type": CONTROLLER_TYPE, "address": "127.0.0.1"}
    ]
    assert controller["transport"] == [
        {"epicspva": {}, "gui": {"title": IOC, "output_dir": "/epics/opi"}}
    ]
    _assert_valid_controller_yaml(instance / "config" / "controller.yaml")

    values = _load(instance / "values.yaml")["ioc-instance"]
    assert values["image"] == FASTCS_PANDABLOCKS_IMAGE
    assert values["args"] == [
        "stdio-expose --ptty --stdin --ctrl-d "
        "'fastcs-pandablocks run /epics/ioc/config/controller.yaml'"
    ]
    assert values["livenessExecutable"] == ""
    assert values["preStopExecutable"] == ""
    assert values["dataVolume"] == {"pvc": False, "hostPath": "/dls/b01-1/data"}

    # scaffolded from .fastcs_ioc_template, symlinks and all
    assert os.readlink(instance / "Chart.yaml") == "../../.helm-shared/Chart.yaml"
    assert os.readlink(instance / "templates") == "../../.helm-shared/templates"


def test_dedicated_warns_about_what_is_lost(tmp_path: Path):
    services = _services_repo(tmp_path)
    yaml = services / IOC.lower() / "config" / "ioc.yaml"
    result = convert_file(_xml(tmp_path), yaml, SCHEMA)

    motor, plugins, settings = result.warnings
    assert "1 ADPandABlocks.MotorSync" in motor
    assert "does its own data capture" in plugins
    for dropped in (
        "1 ADCore.NDAttrPlot",
        "1 ADCore.NDPosPlugin",
        "1 ADCore.NDFileHDF5",
    ):
        assert dropped in plugins
    assert "data capture" not in settings
    for dropped in (
        "1 EPICS_BASE.dbpf",
        "1 EPICS_BASE.StartupCommand",
        "1 pvlogging.BlacklistPv",
    ):
        assert dropped in settings


def test_dedicated_with_two_pandas_has_two_controllers(tmp_path: Path):
    services = _services_repo(tmp_path)
    yaml = services / IOC.lower() / "config" / "ioc.yaml"
    result = convert_file(_xml(tmp_path, SECOND_PANDA), yaml, SCHEMA)

    assert result.fastcs_instances == [services / IOC.lower()]
    controller = services / IOC.lower() / "config" / "controller.yaml"
    assert [(c["id"], c["address"]) for c in _load(controller)["controllers"]] == [
        ("BL01C-MO-PANDA-01", "127.0.0.1"),
        ("BL01C-MO-PANDA-02", "panda-02.invalid"),
    ]
    _assert_valid_controller_yaml(controller)


def test_mixed_writes_ioc_yaml_and_sibling_instances(tmp_path: Path):
    services = _services_repo(tmp_path)
    yaml = services / IOC.lower() / "config" / "ioc.yaml"
    xml = _xml(tmp_path, SECOND_PANDA + MIXED_DEVICES)
    result = convert_file(xml, yaml, SCHEMA)

    assert result.ioc_yaml_written
    assert result.fastcs_instances == [
        services / "bl01c-mo-panda-01",
        services / "bl01c-mo-panda-02",
    ]
    for folder, prefix in zip(
        result.fastcs_instances, ["BL01C-MO-PANDA-01", "BL01C-MO-PANDA-02"], strict=True
    ):
        controller = folder / "config" / "controller.yaml"
        assert [c["id"] for c in _load(controller)["controllers"]] == [prefix]
        _assert_valid_controller_yaml(controller)
        assert os.readlink(folder / "templates") == "../../.helm-shared/templates"

    entities = _load(yaml)["entities"]
    types = [e["type"] for e in entities]
    assert not [t for t in types if t.startswith("ADPandABlocks.")]
    # the PandAs' plugins and their settings go, the camera's stay
    assert "ADAravis.aravisCamera" in types
    assert [e["P"] for e in entities if e["type"].startswith("ADCore.")] == [
        "BL01C-DI-CAM-01"
    ]
    assert not [e for e in entities if "PANDA" in str(e.get("pv", ""))]
    assert [e for e in entities if "CAM-01:STAT" in str(e.get("pv", ""))]


def test_mixed_warnings_name_the_fastcs_instances(tmp_path: Path):
    services = _services_repo(tmp_path)
    yaml = services / IOC.lower() / "config" / "ioc.yaml"
    result = convert_file(_xml(tmp_path, MIXED_DEVICES), yaml, SCHEMA)

    (panda,) = [w for w in result.warnings if " ADPandABlocks.ADPandABlocks " in w]
    assert "fastcs instance(s) bl01c-mo-panda-01" in panda
    (sync,) = [w for w in result.warnings if " ADPandABlocks.MotorSync " in w]
    assert "MotorSync of BL01C-MO-STAGE-01:X (encoder 1)" in sync
    (ref,) = [w for w in result.warnings if "names the PandA PV" in w]
    assert "BL01C.shutter_status INPUT" in ref
    assert "BL01C-MO-PANDA-01:TTLIN2:VAL" in ref


@pytest.mark.parametrize("occupant", ["config/ioc.yaml", "values.yaml", "notes.txt"])
def test_mixed_refuses_any_existing_folder_and_writes_nothing(
    tmp_path: Path, occupant: str
):
    services = _services_repo(tmp_path)
    other = services / "bl01c-mo-panda-02"
    (other / occupant).parent.mkdir(parents=True, exist_ok=True)
    (other / occupant).write_text("someone else's\n")

    yaml = services / IOC.lower() / "config" / "ioc.yaml"
    with pytest.raises(FileExistsError, match="bl01c-mo-panda-02"):
        convert_file(_xml(tmp_path, SECOND_PANDA + MIXED_DEVICES), yaml, SCHEMA)

    # checked before writing: the first PandA's instance was not written either
    assert not (services / "bl01c-mo-panda-01").exists()
    assert not yaml.exists()
    assert (other / occupant).read_text() == "someone else's\n"


def test_dedicated_refuses_a_prefix_served_by_a_0_1_0_instance(tmp_path: Path):
    # the i08 case: services/bl08j-mo-panda-01 already serves the PandA in the
    # 0.1.0 shape, so converting the IOC that held it must not add another
    services = _services_repo(tmp_path)
    existing = services / "bl01c-mo-panda-01" / "config"
    existing.mkdir(parents=True)
    (existing / "controller.yaml").write_text(
        "controller:\n  address: panda-01.invalid\n"
        "transport:\n  - epicspva:\n      pv_prefix: BL01C-MO-PANDA-01\n"
    )
    instance = services / IOC.lower()
    (instance / "config").mkdir(parents=True)
    (instance / "config" / "ioc.yaml").write_text("entities: []\n")

    yaml = instance / "config" / "ioc.yaml"
    result = convert_file(_xml(tmp_path), yaml, SCHEMA)

    assert not result.ioc_yaml_written
    assert result.fastcs_instances == []
    assert result.refused == ["BL01C-MO-PANDA-01"]
    (refusal,) = [w for w in result.warnings if "refused" in w]
    assert str(services / "bl01c-mo-panda-01") in refusal
    # nothing written, nothing removed
    assert (instance / "config" / "ioc.yaml").read_text() == "entities: []\n"
    assert not (instance / "config" / "controller.yaml").exists()


def test_mixed_refuses_an_address_already_served(tmp_path: Path):
    services = _services_repo(tmp_path)
    existing = services / "some-other-panda" / "config"
    existing.mkdir(parents=True)
    (existing / "controller.yaml").write_text(
        "controllers:\n  - id: BL01C-MO-PANDA-99\n"
        "    type: fastcs_pandablocks.PandaController\n"
        "    address: PANDA-02.invalid\n"
    )
    yaml = services / IOC.lower() / "config" / "ioc.yaml"
    result = convert_file(_xml(tmp_path, SECOND_PANDA + MIXED_DEVICES), yaml, SCHEMA)

    assert result.ioc_yaml_written
    assert result.fastcs_instances == [services / "bl01c-mo-panda-01"]
    assert result.refused == ["BL01C-MO-PANDA-02"]
    assert not (services / "bl01c-mo-panda-02").exists()
    (panda,) = [w for w in result.warnings if " ADPandABlocks.ADPandABlocks " in w]
    assert "written as the fastcs instance(s) bl01c-mo-panda-01" in panda
    assert "not written for BL01C-MO-PANDA-02" in panda


def test_rerun_keeps_hand_edits(tmp_path: Path):
    services = _services_repo(tmp_path)
    yaml = services / IOC.lower() / "config" / "ioc.yaml"
    xml = _xml(tmp_path, SECOND_PANDA + MIXED_DEVICES)
    convert_file(xml, yaml, SCHEMA)

    instance = services / "bl01c-mo-panda-01"
    values = instance / "values.yaml"
    controller = instance / "config" / "controller.yaml"
    values.write_text(values.read_text().replace("memory: 4Gi", "memory: 8Gi"))
    controller.write_text(controller.read_text().replace("/epics/opi", "/tmp/opi"))
    edited = values.read_text(), controller.read_text()

    result = convert_file(xml, yaml, SCHEMA)

    assert (values.read_text(), controller.read_text()) == edited
    assert result.fastcs_instances == [instance, services / "bl01c-mo-panda-02"]
    (diff,) = [n for n in result.notes if "differs from what builder2ibek" in n]
    assert str(controller) in diff
    assert '-      output_dir: "/tmp/opi"' in diff
    assert '+      output_dir: "/epics/opi"' in diff
    # the untouched instance gives no diff note
    assert len([n for n in result.notes if "differs" in n]) == 1


def test_legacy_folder_is_recreated(tmp_path: Path):
    services = _services_repo(tmp_path)
    legacy = services / "bl01c-mo-panda-01"
    (legacy / "config").mkdir(parents=True)
    (legacy / "config" / "ioc.yaml").write_text("entities: []\n")
    (legacy / "values.yaml").write_text("dev-c7:\n  enabled: true\n")

    yaml = services / IOC.lower() / "config" / "ioc.yaml"
    convert_file(_xml(tmp_path, MIXED_DEVICES), yaml, SCHEMA)

    assert not (legacy / "config" / "ioc.yaml").exists()
    assert "dev-c7" not in (legacy / "values.yaml").read_text()


def test_outside_a_services_repo(tmp_path: Path):
    # instances are folders next to the ioc.yaml, with no scaffold, and the
    # --yaml file itself is left alone
    yaml = tmp_path / "out" / "ioc.yaml"
    yaml.parent.mkdir()
    yaml.write_text("mine\n")
    result = convert_file(_xml(tmp_path), yaml, SCHEMA)
    assert result.fastcs_instances == [tmp_path / "out" / IOC.lower()]
    assert (tmp_path / "out" / IOC.lower() / "config" / "controller.yaml").is_file()
    assert yaml.read_text() == "mine\n"
    assert [n for n in result.notes if "so it was left alone" in n]


def test_controller_yaml_quotes_its_strings(tmp_path: Path):
    xml = tmp_path / f"{IOC}.xml"
    xml.write_text(DEDICATED.format(extra="").replace("127.0.0.1", "yes"))
    result = convert_file(xml, tmp_path / "out" / "ioc.yaml", SCHEMA)
    controller = result.fastcs_instances[0] / "config" / "controller.yaml"
    assert 'address: "yes"' in controller.read_text()
    assert _load(controller)["controllers"][0]["address"] == "yes"


def test_unknown_beamline_leaves_data_path_placeholder(tmp_path: Path):
    xml = tmp_path / "LA01A-EA-IOC-01.xml"
    xml.write_text(
        DEDICATED.format(extra="").replace("BL01C-MO-PANDA-01", "LA01A-MO-PANDA-01")
    )
    result = convert_file(xml, tmp_path / "out" / "ioc.yaml", SCHEMA)
    values = (result.fastcs_instances[0] / "values.yaml").read_text()
    assert 'hostPath: "REPLACE_WITH_DATA_PATH"' in values
    (warning,) = [w for w in result.warnings if "set dataVolume.hostPath" in w]
    assert warning.startswith("LA01A-EA-IOC-01: ")


@pytest.mark.parametrize(
    "prefix, folder",
    [
        ("BL08J-MO-PANDA-01", "/dls/i08-1/data"),
        ("BL11I-EA-IOC-11", "/dls/i11/data"),
        ("BL09K-EA-PANDA-01", "/dls/i09-2/data"),
        ("BL21B-EA-PANDA-01", "/dls/b21/data"),
        ("BL07C-EA-PANDA-01", "/dls/b07-1/data"),
        ("BL45P-MO-PANDA-01", None),
    ],
)
def test_beamline_data_dir(prefix: str, folder: str | None):
    assert beamline_data_dir(prefix) == folder


def test_xml2yaml_says_what_it_wrote(tmp_path: Path):
    services = _services_repo(tmp_path)
    yaml = services / IOC.lower() / "config" / "ioc.yaml"
    cmd = [
        sys.executable,
        "-m",
        "builder2ibek",
        "xml2yaml",
        str(_xml(tmp_path)),
        "--yaml",
        str(yaml),
    ]
    env = {**os.environ, "NO_COLOR": "1", "TERM": "dumb"}
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert "wrote the fastcs-pandablocks instance" in result.stdout
    assert "dedicated PandA IOC, no ioc.yaml written" in result.stdout
    assert not yaml.exists()


def test_reconvert_writes_fastcs_and_skips_its_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    xml = _xml(tmp_path)
    monkeypatch.setattr(rc, "discover_xmls", lambda _b: ([xml], xml.parent, "work"))
    monkeypatch.setattr(rc, "_run_validation", lambda _r: None)
    services = _services_repo(tmp_path / "services-repo")
    cfg = services / IOC.lower() / "config"
    cfg.mkdir(parents=True)
    (cfg / "ioc.yaml").write_text("ioc_name: x\ndescription: d\nentities: []\n")

    result, code = rc.run_reconvert("BL01C", services.parent, validate=False)
    assert code == 0
    assert result.reconverted == [{"ioc_name": IOC.lower(), "status": "fastcs"}]
    assert result.fastcs == [
        {"ioc_name": IOC.lower(), "instance": str(services / IOC.lower())}
    ]
    assert "FastCS instances: 1" in rc._render_human(result)

    # a second run finds the fastcs folder and keeps its hand edits
    values = services / IOC.lower() / "values.yaml"
    values.write_text(values.read_text() + "# hand edit\n")
    result, code = rc.run_reconvert("BL01C", services.parent, validate=False)
    assert code == 0
    assert result.reconverted == [{"ioc_name": IOC.lower(), "status": "fastcs"}]
    assert values.read_text().endswith("# hand edit\n")


def test_reconvert_reports_a_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    xml = _xml(tmp_path)
    monkeypatch.setattr(rc, "discover_xmls", lambda _b: ([xml], xml.parent, "work"))
    services = _services_repo(tmp_path / "services-repo")
    taken = services / "bl01c-mo-panda-01" / "config"
    taken.mkdir(parents=True)
    (taken / "controller.yaml").write_text(
        "controller:\n  address: 127.0.0.1\ntransport: []\n"
    )
    cfg = services / IOC.lower() / "config"
    cfg.mkdir(parents=True)
    (cfg / "ioc.yaml").write_text("ioc_name: x\ndescription: d\nentities: []\n")

    result, code = rc.run_reconvert("BL01C", services.parent, validate=True)
    assert code == 0
    assert result.reconverted == [{"ioc_name": IOC.lower(), "status": "refused"}]
    assert result.validation == []
    assert [w for w in result.warnings if "refused" in w["warning"]]
