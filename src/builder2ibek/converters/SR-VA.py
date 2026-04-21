from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "SR-VA"


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the SR-VA support module.

    gaugeSet / gaugeSetA declare id_a, id_b, gc_no as strings in the support
    YAML (they are used as PV name segments via Jinja). XML attribute values
    that look numeric get parsed to int by default, so coerce them back.
    """
    if entity_type in ("gaugeSet", "gaugeSetA"):
        for field in ("id_a", "id_b", "gc_no"):
            if hasattr(entity, field) and entity[field] is not None:
                entity[field] = str(entity[field])

    # These entities are leaves — nothing cross-references their `name`.
    # Drop it so ibek doesn't reject it as extra.
    if entity_type in ("common", "gaugeSet", "gaugeSetA"):
        entity.remove("name")

    # SR-VA.common's sub_entities include devIocStats.devIocStatsHelper,
    # which already loads iocAdminSoft.db and iocAdminScanMon.db.  Drop the
    # default devIocStats.iocAdminSoft entity that convert.dispatch inserts
    # to avoid loading those db files twice.
    if entity_type == "common":
        ioc.entities = [
            e
            for e in ioc.entities
            if not (isinstance(e, dict) and e.get("type") == "devIocStats.iocAdminSoft")
        ]
