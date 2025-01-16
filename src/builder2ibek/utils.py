"""
General utility functions to assist conversion
"""

from typing import Any

from builder2ibek.types import Entity


def make_bool(value: Any):
    value = str(value)
    if value.lower() in ["true", "yes", "1"]:
        result = True
    elif value.lower() in ["false", "no", "0"]:
        result = False
    else:
        raise (ValueError(f"Cannot convert {value} to a boolean"))

    return result


def hex_to_int(entity: Entity, prefix: str):
    """
    Loop through A-F suffixes on the prefix supplied.
    If the entity has a key with that prefix-suffix, rename it to the
    # integer equivalent
    """
    for n in range(10, 16):
        hex_key = f"{prefix}{hex(n)[2:].upper()}"
        if hex_key in entity:
            entity.rename(hex_key, f"{prefix}{n}")
