"""
userIO entities become raw records in records.db, expanded from userIO 2-32's
templates as builder did, with autosave info tags from the templates' tags.
"""

from builder2ibek.builder import Builder
from builder2ibek.convert import dispatch
from builder2ibek.converters.records import render_records

XML = """\
<components arch="linux-x86_64">
  <userIO.ao DTYP="asynFloat64" OUT="@asyn(P1)" P="BL05I-EA-USER-01" R=":AO1"
    SCAN="1 second" DRVH="10" DRVL="0" EGUF="10" EGUL="0" LINR="NO CONVERSION"
    name="AO1"/>
  <userIO.ai_sim DTYP="Hy8401ip" INP="#C50 S4" P="BL05I-EA-USER-01" R=":AI1"
    SCAN="1 second" EGUF="1" EGUL="-1" LINR="LINEAR" PREC="3" EGU="V"
    name="AI1"/>
  <userIO.sel P="BL05I-EA-USER-01" R=":SEL" INPA="A" SELN="2" name="SEL"/>
</components>
"""


def _ioc():
    builder = Builder()
    builder.load_string(XML)
    return dispatch(builder, "BL05I-EA-IOC-99.xml")


def test_userio_entities_leave_the_ioc_yaml_for_records_db():
    ioc = _ioc()

    assert not [e for e in ioc.entities if str(e["type"]).startswith("userIO.")]
    assert ioc.post_db_files == ["records.db"]
    assert "records.db" in ioc.side_files


def test_template_defaults_fill_what_the_xml_leaves_out():
    ioc = _ioc()

    record_type, fields = ioc.raw_records["BL05I-EA-USER-01:AO1"]
    assert record_type == "ao"
    assert fields["DESC"] == "Analogue Output"
    assert fields["OUT"] == "@asyn(P1)"
    # a quoted default loses its quotes
    assert ioc.raw_records["BL05I-EA-USER-01:SEL"][1]["DESC"] == "Sel record"


def test_simulation_class_empties_the_link_and_uses_soft_channel():
    fields = _ioc().raw_records["BL05I-EA-USER-01:AI1"][1]

    assert fields["INP"] == ""
    assert fields["DTYP"] == "Soft Channel"


def test_autosave_tags_become_info_tags():
    ioc = _ioc()

    assert ioc.raw_record_info["BL05I-EA-USER-01:AO1"] == {"autosaveFields": "VAL"}
    assert "BL05I-EA-USER-01:AI1" not in ioc.raw_record_info
    rendered = render_records(ioc.raw_records, ioc.raw_record_info)
    assert '    info(autosaveFields, "VAL")\n}' in rendered


MOVING_AVERAGE_XML = """\
<components arch="linux-x86_64">
  <userIO.movingAverage ADEL="0.1" INP="BL24I-MO-STEP-01:X.RBV" P="BL24I-MO-AVG-01"
    TYPE="DOUBLE" name="AVG1"/>
</components>
"""


def test_moving_average_stays_a_userio_entity():
    """Its aSub calls calcAverage from userIO's library, so the IOC needs it."""
    builder = Builder()
    builder.load_string(MOVING_AVERAGE_XML)
    ioc = dispatch(builder, "BL24I-MO-IOC-99.xml")

    (average,) = [e for e in ioc.entities if e["type"] == "userIO.movingAverage"]
    assert average["INP"] == "BL24I-MO-STEP-01:X.RBV"
    assert "name" not in average
    assert not ioc.raw_records
    # so the module plan keeps userIO as build-time
    assert "userIO" in {str(e["type"]).split(".")[0] for e in ioc.entities}
