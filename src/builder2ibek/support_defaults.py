"""
Load defaults from ibek support YAML files so we can omit parameters
whose values match the defaults during conversion, and the parameter types
that decide what an empty XML attribute becomes (see empty_attribute).

The models are read from the submodules of a source checkout: ibek-support*
for the generic models, and the pinned runtime pattern libraries
(ibek-runtime-streamdevice, and the beamline modules of ibek-runtime-support)
for the parameter types of pattern entities. An installed builder2ibek has
none of them, so it finds no models and drops every empty attribute, leaving
each to its model default.
"""

import re
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from builder2ibek.types import Entity

_project_root = Path(__file__).parent.parent.parent

# {entity_type: {param_name: default_value}}
_defaults: dict[str, dict[str, Any]] = {}
# {entity_type: {param_name, ...}}
_params: dict[str, set[str]] = {}
# {entity_type: {param_name: param_spec}}
_param_specs: dict[str, dict[str, dict[str, Any]]] = {}

# The runtime pattern libraries, as patterns.py chooses between a pattern and
# the generic model: an ibek-runtime-streamdevice pattern only stands in for a
# module with no generic model (or one that matches it), while a beamline
# module comes only from its ibek-runtime-support pattern.
_STREAMDEVICE_PATTERNS = "ibek-runtime-streamdevice"
_SUPPORT_PATTERNS = "ibek-runtime-support"

# A beamline module holds the templates of one beamline, e.g. BL21I
BEAMLINE_MODULE = re.compile(r"BL\d\d[A-Z]")


def is_beamline_module(module: str) -> bool:
    """True for a beamline module, such as BL21I; BL15I-BUILDER is not one."""
    return BEAMLINE_MODULE.fullmatch(module) is not None


def _models(base_dir: Path):
    """(entity_type, parameters) for each entity model in a support folder."""
    yml = YAML(typ="safe", pure=True)
    for yaml_file in sorted(base_dir.glob("*/*.ibek.support.yaml")):
        try:
            data = yml.load(yaml_file.read_text())
        except Exception:
            continue
        if not data:
            continue
        module_name = data.get("module", "")
        for model in data.get("entity_models", []):
            entity_name = model.get("name", "")
            if entity_name:
                yield f"{module_name}.{entity_name}", model.get("parameters") or {}


def _specs(params: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {k: v for k, v in params.items() if isinstance(v, dict)}


def _load_pattern_specs():
    """
    The parameter types of the runtime pattern models, from the pinned
    submodules. They only feed empty_attribute: defaults stay the generic ones.
    """
    for entity_type, params in _models(_project_root / _STREAMDEVICE_PATTERNS):
        _param_specs.setdefault(entity_type, _specs(params))
    # a beamline module never uses a generic model, so its pattern model
    # replaces any; ibek-runtime-support's other modules are not used
    for entity_type, params in _models(_project_root / _SUPPORT_PATTERNS):
        if is_beamline_module(entity_type.partition(".")[0]):
            _param_specs[entity_type] = _specs(params)


def _load_all_support_yamls():
    """Load all support YAML files from ibek-support/ and ibek-support-dls/."""
    for base_dir in _project_root.glob("ibek-support*"):
        for entity_type, params in _models(base_dir):
            _params[entity_type] = set(params)
            _param_specs[entity_type] = _specs(params)
            defaults = {}
            for param_name, param_spec in params.items():
                if isinstance(param_spec, dict) and "default" in param_spec:
                    default_val = param_spec["default"]
                    # Skip Jinja2 template defaults — they're dynamic
                    if isinstance(default_val, str) and "{{" in default_val:
                        continue
                    defaults[param_name] = default_val
            if defaults:
                _defaults[entity_type] = defaults


def entity_params(entity_type: str) -> set[str] | None:
    """The parameter names of an entity model, or None if no model is found."""
    return _params.get(entity_type)


def generic_param_types(entity_type: str) -> dict[str, str] | None:
    """
    The type of each parameter of a non-beamline entity model, or None if no
    model is found.
    """
    if entity_type not in _params or is_beamline_module(entity_type.partition(".")[0]):
        return None
    return {
        name: str(spec.get("type", ""))
        for name, spec in _param_specs.get(entity_type, {}).items()
    }


def entity_defaults(entity_type: str) -> dict[str, Any]:
    """The defaults of an entity model's parameters, by name; {} if none."""
    return _defaults.get(entity_type, {})


def empty_attribute(entity_type: str, param: str) -> Any:
    """
    The value for a parameter whose XML attribute is empty, as the builder
    treated it (iocbuilder includeXml.constructArgDict): a str argument is
    passed on as "", a bool one is False, and int and float ones fail to
    convert, so no working IOC passes them empty. None (use the model's
    default) for a parameter the model does not take as "", or does not have,
    or when there is no model to say.
    """
    spec = _param_specs.get(entity_type, {}).get(param)
    if spec is None:
        return None
    typ = spec.get("type")
    if typ == "str":
        return ""
    if typ == "bool":
        return False
    if typ == "enum" and "" in (spec.get("values") or {}):
        return ""
    return None


def fill_empty_attributes(entity: dict[str, Any]):
    """
    Give each empty XML attribute of entity the value the builder used.

    By the parameter's type in the entity model: a str parameter becomes "",
    a bool parameter becomes False, an enum that lists "" as a value stays "",
    and every other type is dropped (set to None, so the model's default
    applies), as is a parameter with no model to say.

    convert.py calls this for each entity, and the extra entities its converter
    adds, once the converter has run. For an entity made from an XML element,
    only the parameters whose XML attribute is empty are filled: a "" the
    converter set in place of a missing attribute is its own choice. An extra
    entity has no XML attributes, so each of its "" values is filled. A value
    set after the fill, by a finalizer or by the ADCore NDAttributes pass, is
    not filled either.
    """
    entity_type = str(entity.get("type", ""))
    xml = entity.xml_attributes() if isinstance(entity, Entity) else {}
    for key, value in list(entity.items()):
        if value != "" or key == "type":
            continue
        if xml and xml.get(key) != "":
            continue
        entity[key] = empty_attribute(entity_type, key)


def values_match(entity_val: Any, default_val: Any) -> bool:
    """Compare entity value to default, with numeric type tolerance."""
    if entity_val == default_val:
        return True
    # Numeric comparison: 0 == 0.0, 1 == 1.0, etc.
    if isinstance(entity_val, (int, float)) and isinstance(default_val, (int, float)):
        return float(entity_val) == float(default_val)
    return False


def strip_defaults(entity: dict[str, Any]):
    """Remove parameters from entity whose values match the support YAML defaults."""
    entity_type = entity.get("type", "")
    defaults = _defaults.get(entity_type)
    if not defaults:
        return

    for param_name, default_val in defaults.items():
        if param_name in entity and values_match(entity[param_name], default_val):
            del entity[param_name]


# Load at import time: generic models first, so that a streamdevice pattern
# only adds the types of modules they lack
_load_all_support_yamls()
_load_pattern_specs()
