from typing import Any, Dict

from builder2ibek.dataclasses import Generic_IOC

schema = (
    "https://github.com/epics-containers/ioc-pmac/releases/"
    "download/1.2.1/ioc.ibek.schema.yaml"
)

defaults = {
    "pmac.GeoBrick": {
        "numAxes": 8,
        "idlePoll": 100,
        "movingPoll": 500,
    }
}


def handler(entity: Dict[str, Any], entity_type: str, ioc: Generic_IOC):

    pass
