"""
Converted pmac entities validate against ibek-support's pmac model, which
forbids parameters it does not declare, such as the builder's GUI name.
"""

import warnings
from typing import Any

from ibek.entity_factory import EntityFactory
from ibek.ioc import clear_entity_model_ids
from ibek.ioc_factory import IocFactory
from pydantic.warnings import PydanticDeprecatedSince211

from builder2ibek.builder import Builder
from builder2ibek.convert import dispatch
from tests.conftest import REPO_ROOT

# each leaf type with the name builder XML gives it, as in BL05I-MO-IOC-03
# (pmacSetCoordStepsPerUnit) and BL08J's XMLs
PMAC_XML = """\
<components arch="linux-x86_64">
  <pmac.pmacAsynIPPort IP="10.0.0.1:1025" name="BRICK1port"/>
  <pmac.GeoBrick P="BL05I-MO-STEP-01" Port="BRICK1port" name="BRICK1"/>
  <pmac.CS Controller="BRICK1" CS="2" PLCNum="16" name="BRICK1.CS2"/>
  <pmac.pmacSetCoordStepsPerUnit Axis="7" CS="BRICK1.CS2" Scale="1000000"
    name="PGM.NRJ_RES"/>
  <pmac.pmacSetOpenLoopEncoderAxis Axis="1" Controller="BRICK1" Encoder_axis="9"
    name="ENC1"/>
  <pmac.pmacMonitorVariables Controller="BRICK1" Variables="P4801"
    name="MRES_5"/>
  <pmac.pmacVariableRead EGU="%" P="BL05I-MO-STEP-01" PORT="BRICK1" Q=":XF:DAC"
    SPEED="F" VAR="P2011" VARIABLE_PREC="1" name="VAR2"/>
</components>
"""

SUPPORT_YAMLS = [
    REPO_ROOT / "ibek-support" / "_ansible" / "epics.ibek.support.yaml",
    REPO_ROOT / "ibek-support" / "asyn" / "asyn.ibek.support.yaml",
    REPO_ROOT / "ibek-support" / "motor" / "motor.ibek.support.yaml",
    REPO_ROOT / "ibek-support" / "pmac" / "pmac.ibek.support.yaml",
]


def _entities(xml: str) -> list[dict[str, Any]]:
    builder = Builder()
    builder.load_string(xml)
    return [dict(e) for e in dispatch(builder, "test.xml").entities]


def test_pmac_leaf_entities_validate_against_the_pmac_model():
    entities = [e for e in _entities(PMAC_XML) if e["type"].startswith("pmac.")]
    model = IocFactory().make_ioc_model(
        EntityFactory().make_entity_models(SUPPORT_YAMLS)
    )
    clear_entity_model_ids()
    try:
        with warnings.catch_warnings():
            # raised from inside ibek's Entity, as in builder2ibek.patterns
            warnings.simplefilter("ignore", PydanticDeprecatedSince211)
            model(ioc_name="test", description="test", entities=entities)
    finally:
        clear_entity_model_ids()


def test_pmac_leaf_entities_drop_name():
    by_type = {e["type"]: e for e in _entities(PMAC_XML)}

    for leaf in (
        "pmacSetCoordStepsPerUnit",
        "pmacSetOpenLoopEncoderAxis",
        "pmacMonitorVariables",
        "pmacVariableRead",
    ):
        assert "name" not in by_type[f"pmac.{leaf}"]
    assert by_type["pmac.pmacSetCoordStepsPerUnit"]["SCALE"] == 1000000
    monitor = by_type["pmac.pmacMonitorVariables"]
    assert (monitor["CONTROLLER"], monitor["VARIABLES"]) == ("BRICK1", "P4801")
