"""Adding a converted IOC's runtime patterns to its instance, with ibek mocked.

The published image schemas are mocked too, except for images not in SCHEMAS:
those go to ibek's real fetch, which IBEK_SCHEMA_CACHE (set by conftest) keeps
away from the user's cache.
"""

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from builder2ibek import convert, vendor_patterns
from builder2ibek.patterns import Pattern, PatternPlan
from builder2ibek.vendor_patterns import (
    RUNTIME_IMAGE,
    RUNTIME_TAG_ENV,
    add_patterns,
    runtime_image,
)

RUNTIME = f"{RUNTIME_IMAGE}:2.0ec2"
# stand-in for a generic IOC image whose published schema is mocked
VAC = "ghcr.io/epics-containers/ioc-dlslinuxvac:2026.8.1"
# a registry ibek has no published schema for: fails without the network
GITLAB = "gitlab.diamond.ac.uk:5050/controls/containers/ioc-vac:1.0"
SAMPLE = Path(__file__).parent / "samples" / "BL99P-EA-IOC-05.xml"
LOCK = """\
version: 1
patterns:
  attocubeInterf:
    version: 0.1.0
    source: github.com/epics-containers/ibek-runtime-streamdevice
    files: {}
"""


def _pattern(module: str, model: str) -> Pattern:
    return Pattern(
        library="ibek-runtime-streamdevice",
        module=module,
        version="0.8.1",
        models=frozenset({model}),
        support_yaml=Path("unused"),
    )


ATTO = _pattern("attocubeInterf", "ids3010")
SCROLL = _pattern("EdwardsScroll", "EdwardsScroll")
ENTITIES = [
    {"type": "asyn.AsynIP", "name": "p", "port": "localhost:1"},
    {"type": "attocubeInterf.ids3010", "P": "X", "PORT": "p", "Q": "01"},
    {"type": "EdwardsScroll.EdwardsScroll", "P": "Y", "port": "p"},
]
SCHEMAS = {
    RUNTIME: frozenset({"asyn.AsynIP", "epics.EpicsEnvSet"}),
    VAC: frozenset(
        {"asyn.AsynIP", "digitelMpc.digitelMpc", "EdwardsScroll.EdwardsScroll"}
    ),
}


def _schema(types: frozenset[str]) -> dict:
    mapping = {t: f"#/$defs/{t}" for t in types}
    items = {"discriminator": {"mapping": mapping}}
    return {"properties": {"entities": {"items": items}}}


class FakeIndex:
    def plan(self, entities):
        return PatternPlan(patterns=[ATTO, SCROLL])


@pytest.fixture
def ibek(monkeypatch) -> Iterator[list[tuple[str, ...]]]:
    """Mock the index, the image schemas and ibek; return ibek's calls."""
    calls: list[tuple[str, ...]] = []

    def run(*args: str):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    real_fetch = vendor_patterns._fetch_base_schema

    def fetch(image: str) -> dict:
        if image in SCHEMAS:
            return _schema(SCHEMAS[image])
        return real_fetch(image)

    monkeypatch.setattr(vendor_patterns, "pattern_index", FakeIndex)
    monkeypatch.setattr(vendor_patterns, "_fetch_base_schema", fetch)
    monkeypatch.setattr(vendor_patterns, "runtime_image", lambda: (RUNTIME, ""))
    monkeypatch.setattr(vendor_patterns, "_ibek", run)
    vendor_patterns.image_entity_types.cache_clear()
    yield calls
    vendor_patterns.image_entity_types.cache_clear()


def _instance(root: Path, image: str) -> Path:
    instance = root / "services" / "bl01t-ea-ioc-01"
    (instance / "config").mkdir(parents=True)
    (instance / "values.yaml").write_text(f"ioc-instance:\n  image: {image}\n")
    return instance


def _adds(calls) -> list[str]:
    return [c[2] for c in calls if c[:2] == ("pattern", "add")]


def test_runtime_image_override_release_and_tag(monkeypatch):
    runtime_image.cache_clear()
    monkeypatch.setenv(RUNTIME_TAG_ENV, "2.8.26ec8")
    assert runtime_image() == (f"{RUNTIME_IMAGE}:2.8.26ec8", "")

    # the latest published release of the generic IOC repo, which has no
    # -runtime suffix
    runtime_image.cache_clear()
    monkeypatch.delenv(RUNTIME_TAG_ENV)
    apis = []
    monkeypatch.setattr(
        vendor_patterns, "_latest_release", lambda api: apis.append(api) or "ec9"
    )
    assert runtime_image() == (f"{RUNTIME_IMAGE}:ec9", "")
    assert apis == ["https://api.github.com/repos/epics-containers/ioc-streamdevice"]

    # else its highest tag, with a warning
    runtime_image.cache_clear()

    def unreachable(api):
        raise OSError("rate limited")

    monkeypatch.setattr(vendor_patterns, "_latest_release", unreachable)
    monkeypatch.setattr(vendor_patterns, "latest_tag", lambda url: "ec10")
    image, warning = runtime_image()
    assert image == f"{RUNTIME_IMAGE}:ec10"
    assert "rate limited" in warning and "may not be published" in warning
    runtime_image.cache_clear()


@pytest.mark.parametrize("image", ["REPLACE_WITH_IMAGE_URI", f"{RUNTIME_IMAGE}:2.0ec1"])
def test_pattern_only_gets_the_runtime_image(tmp_path: Path, ibek, image: str):
    instance = _instance(tmp_path, image)
    entities = ENTITIES[:2]  # asyn is built by the runtime image

    report = add_patterns(entities, instance / "config" / "ioc.yaml")

    assert RUNTIME in (instance / "values.yaml").read_text()
    # every pattern the plan picked, with no --source
    assert ibek == [
        ("pattern", "add", ATTO.ref, str(instance)),
        ("pattern", "add", SCROLL.ref, str(instance)),
    ]
    assert f"image set to {RUNTIME}" in report.notes
    assert not report.warnings


def test_mixed_skips_patterns_the_image_installs(tmp_path: Path, ibek):
    instance = _instance(tmp_path, VAC)
    entities = [*ENTITIES, {"type": "digitelMpc.digitelMpc", "name": "m"}]

    report = add_patterns(entities, instance / "config" / "ioc.yaml")

    assert VAC in (instance / "values.yaml").read_text()
    assert _adds(ibek) == [ATTO.ref]
    assert f"EdwardsScroll: {VAC} installs it" in report.notes


def test_mixed_without_image_schema_adds_all(tmp_path: Path, ibek):
    """ibek's real fetch fails for the image, and the conversion carries on."""
    instance = _instance(tmp_path, GITLAB)
    entities = [*ENTITIES, {"type": "other.thing"}]

    report = add_patterns(entities, instance / "config" / "ioc.yaml")

    assert _adds(ibek) == [ATTO.ref, SCROLL.ref]
    assert report.warnings == [
        f"cannot fetch the ioc schema of {GITLAB}; adding every pattern"
    ]
    assert GITLAB in (instance / "values.yaml").read_text()


def test_unreadable_values_yaml_is_a_warning(tmp_path: Path, ibek):
    instance = _instance(tmp_path, "unused")
    (instance / "values.yaml").write_text("ioc-instance: [unclosed\n")

    report = add_patterns(ENTITIES[:2], instance / "config" / "ioc.yaml")

    assert any("cannot read the image" in w for w in report.warnings)
    assert _adds(ibek) == [ATTO.ref, SCROLL.ref]
    assert (instance / "values.yaml").read_text() == "ioc-instance: [unclosed\n"


def test_mixed_with_placeholder_warns(tmp_path: Path, ibek):
    instance = _instance(tmp_path, "REPLACE_WITH_IMAGE_URI")
    entities = [*ENTITIES, {"type": "digitelMpc.digitelMpc", "name": "m"}]

    report = add_patterns(entities, instance / "config" / "ioc.yaml")

    assert _adds(ibek) == [ATTO.ref, SCROLL.ref]
    assert "REPLACE_WITH_IMAGE_URI" in (instance / "values.yaml").read_text()
    assert report.warnings == [
        "mixed IOC with no image set: patterns added to the instance; set the "
        "generic IOC image and re-run xml2yaml to drop patterns the image "
        "already installs"
    ]


def test_runtime_schema_unavailable_leaves_the_image(tmp_path: Path, ibek, monkeypatch):
    monkeypatch.setattr(vendor_patterns, "runtime_image", lambda: (GITLAB, ""))
    instance = _instance(tmp_path, "REPLACE_WITH_IMAGE_URI")

    report = add_patterns(ENTITIES[:2], instance / "config" / "ioc.yaml")

    assert "REPLACE_WITH_IMAGE_URI" in (instance / "values.yaml").read_text()
    assert report.warnings == [
        f"runtime image schema unavailable ({GITLAB}): pattern-only check skipped"
    ]
    assert _adds(ibek) == [ATTO.ref, SCROLL.ref]


def test_no_instance_only_reports(tmp_path: Path, ibek):
    report = add_patterns(ENTITIES[:2], tmp_path / "ioc.yaml")

    assert ibek == []
    assert report.notes == [
        f"would add runtime pattern {ATTO.ref}",
        f"would add runtime pattern {SCROLL.ref}",
        f"image: {RUNTIME}",
    ]


def test_locked_pattern_is_left_alone(tmp_path: Path, ibek):
    instance = _instance(tmp_path, RUNTIME)
    (instance / "runtime-lock.yaml").write_text(LOCK)

    report = add_patterns(ENTITIES[:2], instance / "config" / "ioc.yaml")

    assert _adds(ibek) == [SCROLL.ref]
    assert (instance / "runtime-lock.yaml").read_text() == LOCK
    assert any(
        "attocubeInterf stays at 0.1.0" in n and "not 0.8.1" in n for n in report.notes
    )


def test_all_locked_regenerates_the_schema(tmp_path: Path, ibek, monkeypatch):
    monkeypatch.setattr(FakeIndex, "plan", lambda self, e: PatternPlan([ATTO]))
    instance = _instance(tmp_path, RUNTIME)
    (instance / "runtime-lock.yaml").write_text(LOCK)

    add_patterns(ENTITIES[:2], instance / "config" / "ioc.yaml")

    # the ioc.yaml was rewritten, so ibek sets its schema header again
    assert ibek == [("pattern", "schema", str(instance))]


def test_any_failure_is_a_conversion_warning(tmp_path: Path, monkeypatch):
    """Whatever adding patterns raises, the ioc.yaml is written."""

    def fail(entities, ioc_yaml):
        raise OSError("read-only file system")

    monkeypatch.setattr(convert, "add_patterns", fail)
    ioc_yaml = tmp_path / "ioc.yaml"

    result = convert.convert_file(SAMPLE, ioc_yaml, "schema")

    assert ioc_yaml.is_file()
    assert "runtime patterns not added: read-only file system" in result.warnings


def test_set_image_replaces_only_the_image_line(tmp_path: Path):
    instance = _instance(tmp_path, "REPLACE_WITH_IMAGE_URI  # set me")
    values = instance / "values.yaml"
    values.write_text("# was REPLACE_WITH_IMAGE_URI\n" + values.read_text())

    assert vendor_patterns._set_image(instance, RUNTIME)[0]

    assert values.read_text() == (
        f"# was REPLACE_WITH_IMAGE_URI\nioc-instance:\n  image: {RUNTIME}  # set me\n"
    )


def test_set_image_never_downgrades(tmp_path: Path, ibek):
    newer = f"{RUNTIME_IMAGE}:2.0ec3"
    instance = _instance(tmp_path, newer)

    report = add_patterns(ENTITIES[:2], instance / "config" / "ioc.yaml")

    assert newer in (instance / "values.yaml").read_text()
    assert f"values.yaml keeps {newer}, not older {RUNTIME}" in report.notes
