"""
Load defaults from ibek support YAML files so we can omit parameters
whose values match the defaults during conversion, and the parameter types
that decide what an empty XML attribute becomes (see empty_attribute).

The generic models are read from the ibek-support* submodules of a source
checkout. The parameter types of pattern entities come from the runtime pattern
library releases the conversion validates against: the index that
builder2ibek.patterns.pattern_index clones (the latest releases, or those
BUILDER2IBEK_PATTERN_TAG and BUILDER2IBEK_SUPPORT_PATTERN_TAG name), never the
pinned pattern submodules. An installed builder2ibek has no ibek-support*, and
with no index there are no pattern types either: an empty attribute with no
model to say is dropped, leaving it to its model default.
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
# {entity_type: {param_name: param_spec}}, of the generic models
_param_specs: dict[str, dict[str, dict[str, Any]]] = {}

# A beamline module holds the templates of one beamline, e.g. BL21I
BEAMLINE_MODULE = re.compile(r"BL\d\d[A-Z]")

# The modules of ibek-runtime-support other than beamline modules that
# builder2ibek routes to their pattern. One that also has a generic model is
# decided by patterns.ALIGNED or patterns.GENERIC_DIFFERS, as for
# ibek-runtime-streamdevice.
SUPPORT_PATTERN_MODULES = frozenset(
    {"adamCPW", "BLfeedback", "detectorPlugins", "generic"}
)


# A beamline's builder repo, e.g. BL15I-BUILDER. It is never a runtime
# pattern: its templates migrate into the beamline module, e.g. BL15I
BUILDER_MODULE = re.compile(r"(BL\d\d[A-Z])-BUILDER")


def builder_module_target(module: str) -> str | None:
    """The beamline module a builder repo's templates migrate into, or None.

    BL15I for BL15I-BUILDER; None for a module that is not a builder repo.
    """
    match = BUILDER_MODULE.fullmatch(module)
    return match.group(1) if match else None


def is_beamline_module(module: str) -> bool:
    """True for a beamline module, such as BL21I; BL15I-BUILDER is not one."""
    return BEAMLINE_MODULE.fullmatch(module) is not None


def routes_to_support_pattern(module: str) -> bool:
    """True for a module builder2ibek takes from its ibek-runtime-support
    pattern: a beamline module, or one of :data:`SUPPORT_PATTERN_MODULES`."""
    return is_beamline_module(module) or module in SUPPORT_PATTERN_MODULES


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


def param_specs(entity_type: str) -> dict[str, dict[str, Any]]:
    """
    The parameters of the model builder2ibek converts an entity type with, by
    name; {} if there is none.

    That is the generic model in ibek-support*, except where patterns.py takes
    the pattern model instead: for a module routes_to_support_pattern names,
    and for an entity type with no generic model. A pattern model comes from the
    release in patterns.pattern_index, the one the conversion validates
    against; with no index, or no pattern for the type, the generic model (if
    any) is used.
    """
    generic = _param_specs.get(entity_type)
    if generic is not None and not routes_to_support_pattern(
        entity_type.partition(".")[0]
    ):
        return generic
    # patterns.py imports this module
    from builder2ibek import patterns

    try:
        pattern = patterns.pattern_index().param_specs(entity_type)
    except Exception:  # noqa: BLE001 -- no index: plan_patterns reports why
        pattern = None
    return pattern if pattern is not None else generic or {}


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
    spec = param_specs(entity_type).get(param)
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


def _as_number(text: str) -> int | float | None:
    """The number make_entity reads from an XML attribute, or None."""
    try:
        f = float(text)
    except ValueError:
        return None
    return int(f) if f.is_integer() else f


def keep_text_attributes(entity: dict[str, Any]):
    """
    Give a str parameter its XML attribute as written, not as a number.

    make_entity reads every numeric-looking attribute as a number, so that the
    YAML does not quote it; a str parameter would then reject it ("10" for a
    description, "5" for a timeout a pattern takes as text). This puts back the
    attribute's text for each parameter the entity model types as str, when
    the entity still holds the number make_entity read from it: a value a
    converter set is its own choice. A parameter with no model to say keeps
    its number.
    """
    if not isinstance(entity, Entity):
        return
    specs = param_specs(str(entity.get("type", "")))
    for key, text in entity.xml_attributes().items():
        value = entity.get(key)
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and specs.get(key, {}).get("type") == "str"
            and _as_number(text) == value
        ):
            entity[key] = text


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


# Load at import time
_load_all_support_yamls()
