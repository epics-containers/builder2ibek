"""
Dispatch Builder XML elements to the appropriate handlers
"""

from typing import Dict


def dispatch(
    arch: str, builder_name: str, attributes: Dict[str, str]
) -> Dict[str, str]:
    """
    Choose the correct handler for a given Builder XML element and return a
    Dictionary representing a ibek Entity
    """
    entity: Dict[str, str] = {}

    module, item = builder_name.split(".", 1)

    if module == "pmac":
        # use the pmac handler
        pass
    else:
        # default handling (is this possible)
        pass

    return entity
