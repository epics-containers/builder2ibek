from builder2ibek.converters.globalHandler import globalHandler
from builder2ibek.types import Entity, Generic_IOC

xml_component = "procServControl"

REASON = (
    "procServControl is not used in containers: "
    "Kubernetes and argocd-monitor replace it"
)


@globalHandler
def handler(entity: Entity, entity_type: str, ioc: Generic_IOC):
    """
    XML to YAML specialist convertor function for the procServControl support module

    builder2ibek won't convert procServControl: every entity type it defines
    (procServControl, procServControlGui) is left out with a warning.
    """
    ioc.wont_convert(entity, REASON)
