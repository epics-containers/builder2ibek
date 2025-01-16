"""
General utility functions to assist conversion
"""

from typing import Any


def make_bool(value: Any):
    value = str(value)
    if value.lower() in ["true", "yes", "1"]:
        result = True
    elif value.lower() in ["false", "no", "0"]:
        result = False
    else:
        raise (ValueError(f"Cannot convert {value} to a boolean"))

    return result
