#!/usr/bin/env python3
"""Apply the two eligibility gates to candidate support modules.

A module is convertible to a runtime StreamDevice pattern only if it needs
nothing in the IOC binary. Both gates are mechanical:

  gate 1 (filesystem)  no compiled code: no `*App/src/*.{c,cpp,cc,cxx}` and no
                       module-authored `*App/src/*.dbd`.
  gate 2 (builder.py)  `LibFileList` and `DbdFileList` empty or absent, and
                       `Dependencies` a subset of the modules the target image
                       already ships.

`Initialise` / `PostIocInitialise` emitting st.cmd lines is NOT a disqualifier -
ibek expresses those as pre_init/post_init. With LibFileList/DbdFileList empty,
anything a module emits must come from a dependency, which gate 2 covers.

usage:
    check-eligibility.py --candidates candidates.json --image-modules mods.txt
    check-eligibility.py --module /dls_sw/prod/R3.14.12.7/support/fw102/2-1 \
                         --image-modules mods.txt

Verdicts: PASS / SKIP / REVIEW (see --help output of the report for meanings).
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------- gate 1 ----

COMPILED_SUFFIXES = (".c", ".cpp", ".cc", ".cxx")
# State-notation programs are compiled into the binary and need the seq module,
# so they count as compiled code even though they are not C.
SNL_SUFFIXES = (".st", ".stt")

# The DLS support-module template (makeBaseApp) drops an example IOC binary into
# every module: `<mod>Main.cpp` plus the generated registerRecordDeviceDriver.
# Neither is device code, and excluding them is what lets a pure-StreamDevice
# module such as fw102 pass gate 1.
GENERATED_RE = re.compile(r".*_registerRecordDeviceDriver\.(cpp|c)$")
MAIN_RE = re.compile(r".*Main\.(c|cpp|cc)$")
# The canonical body: iocsh(argv[1]) / iocsh(NULL) / epicsExit(0) and nothing
# else. Checked by content, so a module that hid real code in a *Main.cpp is
# still caught.
MAIN_MARKERS = ("iocsh(", "epicsExit(")
MAIN_MAX_BYTES = 4096


def is_boilerplate_main(path: Path) -> bool:
    if not MAIN_RE.match(path.name):
        return False
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return False
    if len(text.encode()) > MAIN_MAX_BYTES:
        return False
    if not all(m in text for m in MAIN_MARKERS):
        return False
    # exactly one function definition, and it is main()
    defs = re.findall(r"^\w[\w \t\*]*\b(\w+)\s*\(", text, re.M)
    return set(defs) <= {"main"}


def gate_filesystem(module_dir: Path) -> tuple[bool, list[str]]:
    """Return (passed, reasons)."""
    reasons: list[str] = []
    for app in sorted(module_dir.glob("*App")):
        src = app / "src"
        if not src.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(src):
            dirnames[:] = [d for d in dirnames if not d.startswith("O.")]
            for fname in sorted(filenames):
                p = Path(dirpath) / fname
                rel = p.relative_to(module_dir)
                if fname.endswith(".dbd"):
                    reasons.append(f"module-authored dbd: {rel}")
                elif fname.endswith(COMPILED_SUFFIXES):
                    if GENERATED_RE.match(fname):
                        continue
                    if is_boilerplate_main(p):
                        continue
                    reasons.append(f"compiled source: {rel}")
                elif fname.endswith(SNL_SUFFIXES):
                    reasons.append(f"SNL program (needs seq): {rel}")
    return (not reasons), reasons


# ---------------------------------------------------------------- gate 2 ----

# DLS iocbuilder module name -> the name the image uses. Compared
# case-insensitively first, so only genuine renames need an entry.
MODULE_ALIASES = {
    "devIocStats": "iocStats",
    "streamdevice": "StreamDevice",
}

# `from iocbuilder.hardware import Calc` is not an import from a module called
# `iocbuilder`: `hardware` is iocbuilder's aggregate namespace, into which every
# loaded module injects its exported names (iocbuilder/libversion.py). The
# import therefore says nothing about which module a class came from, so the
# class name is resolved against the image set instead - `Calc` -> `calc`. The
# table below covers the image's classes whose name is not their module's.
HARDWARE_NS = "<iocbuilder.hardware>"
HARDWARE_CLASS_MODULE = {
    "asyn": "asyn",
    "asynip": "asyn",
    "asynserial": "asyn",
    "asynport": "asyn",
    "asynoctet": "asyn",
    "deviocstats": "iocStats",
    "iocstats": "iocStats",
    "protocolfile": "StreamDevice",
    "streamprotocol": "StreamDevice",
    "autosaverestore": "autosave",
}

PY2_PRINT = re.compile(r"^(\s*)print\s+(?!\()(.*?)\s*$", re.M)


def parse_builder(text: str) -> tuple[ast.Module | None, str]:
    """Parse a DLS builder.py, repairing python-2 print statements if needed."""
    try:
        return ast.parse(text), "ast"
    except SyntaxError:
        pass
    repaired = PY2_PRINT.sub(
        lambda m: f"{m.group(1)}print({m.group(2).rstrip(',')})", text
    )
    try:
        return ast.parse(repaired), "ast(py2-print-repaired)"
    except SyntaxError:
        return None, "regex-fallback"


def _str_items(node: ast.AST) -> list[str]:
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [
            e.value
            for e in node.elts
            if isinstance(e, ast.Constant) and isinstance(e.value, str)
        ]
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    return []


def _name_items(node: ast.AST) -> list[str]:
    out = []
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        elts = node.elts
    else:
        elts = [node]
    for e in elts:
        if isinstance(e, ast.Name):
            out.append(e.id)
        elif isinstance(e, ast.Attribute):
            out.append(e.attr)
    return out


def analyse_builder_ast(tree: ast.Module) -> dict:
    """Collect LibFileList / DbdFileList / Dependencies and the import map."""
    imports: dict[str, str] = {}  # imported class name -> iocbuilder module
    libs: list[tuple[str, str]] = []  # (class, entry)
    dbds: list[tuple[str, str]] = []
    deps: list[tuple[str, str]] = []
    local_classes: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            m = re.match(r"iocbuilder\.modules\.(\w+)", node.module)
            if m:
                for alias in node.names:
                    imports[alias.asname or alias.name] = m.group(1)
            elif node.module == "iocbuilder.hardware":
                for alias in node.names:
                    imports[alias.asname or alias.name] = HARDWARE_NS
            elif node.module not in ("iocbuilder", "iocbuilder.arginfo"):
                # `from genSub import GenSub` - a bare module import, which DLS
                # also uses; the module name is the segment before the dot.
                for alias in node.names:
                    imports.setdefault(
                        alias.asname or alias.name, node.module.split(".")[0]
                    )
        if isinstance(node, ast.ClassDef):
            local_classes.add(node.name)

    def walk_class(cls_name: str, body: list[ast.stmt]) -> None:
        for stmt in body:
            targets = []
            if isinstance(stmt, ast.Assign):
                targets = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
                value = stmt.value
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                targets = [stmt.target.id]
                value = stmt.value
            else:
                continue
            if value is None:
                continue
            for t in targets:
                if t == "LibFileList":
                    libs.extend((cls_name, s) for s in _str_items(value))
                elif t == "DbdFileList":
                    dbds.extend((cls_name, s) for s in _str_items(value))
                elif t == "Dependencies":
                    deps.extend((cls_name, n) for n in _name_items(value))

    walk_class("<module>", tree.body)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            walk_class(node.name, node.body)

    return {
        "imports": imports,
        "libs": libs,
        "dbds": dbds,
        "deps": deps,
        "local_classes": local_classes,
        "lib_classes": _lib_classes(tree, libs, dbds),
    }


def _lib_classes(
    tree: ast.Module, libs: list[tuple[str, str]], dbds: list[tuple[str, str]]
) -> set[str]:
    """Local classes that contribute a library or dbd, directly or by base class."""
    direct = {c for c, _ in libs} | {c for c, _ in dbds}
    bases: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bases[node.name] = [b.id for b in node.bases if isinstance(b, ast.Name)]
    out = set(direct)
    for _ in range(len(bases) + 1):  # transitive closure, bounded
        grown = {c for c, bs in bases.items() if out & set(bs)} | out
        if grown == out:
            break
        out = grown
    return out


LINE_LIST = re.compile(r"^\s*(LibFileList|DbdFileList|Dependencies)\s*=\s*(.+)$", re.M)
LINE_IMPORT = re.compile(
    r"^\s*from\s+iocbuilder\.modules\.(\w+)\s+import\s+(.+)$", re.M
)


def analyse_builder_regex(text: str) -> dict:
    """Fallback for a builder.py python cannot parse at all."""
    imports: dict[str, str] = {}
    for mod, names in LINE_IMPORT.findall(text):
        for n in re.split(r"[,\s]+", names.split("#")[0].strip()):
            if n:
                imports[n.strip("()")] = mod
    libs: list[tuple[str, str]] = []
    dbds: list[tuple[str, str]] = []
    deps: list[tuple[str, str]] = []
    for key, rhs in LINE_LIST.findall(text):
        rhs = rhs.split("#")[0]
        items = [i.strip(" ()[]'\"") for i in rhs.split(",")]
        items = [i for i in items if i]
        if key == "LibFileList":
            libs += [("?", i) for i in items]
        elif key == "DbdFileList":
            dbds += [("?", i) for i in items]
        else:
            deps += [("?", i) for i in items]
    return {
        "imports": imports,
        "libs": libs,
        "dbds": dbds,
        "deps": deps,
        "local_classes": set(re.findall(r"^class\s+(\w+)", text, re.M)),
        # The regex fallback cannot attribute a list to a class, so it cannot
        # tell a benign module-local dependency from a library one. Assume the
        # worst; the verdict is REVIEW anyway.
        "lib_classes": set(re.findall(r"^class\s+(\w+)", text, re.M)),
    }


def in_image(mod: str, image: set[str]) -> str | None:
    """The image's own spelling of `mod`, or None if the image does not ship it."""
    lowered = {m.lower(): m for m in image}
    alias = MODULE_ALIASES.get(mod, MODULE_ALIASES.get(mod.lower(), mod))
    return lowered.get(alias.lower())


def resolve_dependency(name: str, info: dict, image: set[str]) -> tuple[str, str]:
    """Return (status, detail). status in {ok, not-in-image, module-local}."""
    mod = info["imports"].get(name)
    if mod == HARDWARE_NS:
        guess = HARDWARE_CLASS_MODULE.get(name.lower(), name)
        shipped = in_image(guess, image)
        if shipped:
            return "ok", f"{name} -> {shipped} (via iocbuilder.hardware)"
        return (
            "not-in-image",
            f"{name} (via iocbuilder.hardware; no image module of that name)",
        )
    if mod is None:
        if name in info["local_classes"]:
            # A dependency on one of this module's own classes is only
            # disqualifying if that class contributes a library or dbd - which
            # gate 2 already reports in its own right. A module-local dependency
            # on a pure template/protocol class (HostLink's own
            # `HostLinkTemplate`, say) needs nothing in the binary.
            if name in info["lib_classes"]:
                return (
                    "module-local",
                    f"{name} is a local class carrying LibFileList/DbdFileList",
                )
            return "ok", f"{name} (module-local, no library or dbd)"
        return "not-in-image", f"{name} (unresolved import)"
    shipped = in_image(mod, image)
    if shipped:
        return "ok", f"{name} -> {shipped}"
    return "not-in-image", f"{name} -> {mod}"


def gate_builder(module_dir: Path, image: set[str]) -> tuple[str, list[str], dict]:
    """Return (verdict, reasons, extra)."""
    builder = module_dir / "etc" / "builder.py"
    no_source = (
        "gate 2 is vacuously satisfied, but there is no entity-model source "
        "either; convert by hand or skip"
    )
    if not builder.is_file():
        return "REVIEW", [f"no etc/builder.py - {no_source}"], {"parse": "none"}
    text = builder.read_text(errors="replace")
    tree, mode = parse_builder(text)
    info = (
        analyse_builder_ast(tree) if tree is not None else analyse_builder_regex(text)
    )

    reasons: list[str] = []
    for cls, entry in info["libs"]:
        reasons.append(f"LibFileList {entry!r} on class {cls}")
    for cls, entry in info["dbds"]:
        reasons.append(f"DbdFileList {entry!r} on class {cls}")
    bad_deps = []
    for cls, dep in info["deps"]:
        status, detail = resolve_dependency(dep, info, image)
        if status != "ok":
            bad_deps.append(f"Dependencies {detail} on class {cls} ({status})")
    reasons += sorted(set(bad_deps))
    if reasons:
        return "SKIP", reasons, {"parse": mode}

    if not info["local_classes"]:
        # An empty (or class-less) builder.py is the same situation as a missing
        # one, and must not be auto-passed: iocbuilder entities are classes, so a
        # file that defines none declares no device. Six candidates ship a
        # two-byte `etc/builder.py`, among them `xspress3_api` - a vendored
        # detector C SDK whose only "protocol" file is a prose description of a
        # network protocol.
        size = builder.stat().st_size
        return (
            "REVIEW",
            [f"etc/builder.py defines no classes ({size} bytes) - {no_source}"],
            {"parse": mode},
        )

    verdict = "PASS"
    if mode == "regex-fallback":
        verdict = "REVIEW"
        reasons.append(
            "builder.py does not parse as python - regex fallback used, confirm by hand"
        )
    return verdict, reasons, {"parse": mode}


# ------------------------------------------------------------- pre-gates ----

# A DLS beamline / accelerator-subsystem module is a collection of that
# beamline's IOC definitions, not a device. Its protocol files belong to devices
# that have their own modules. Reported rather than silently dropped, because the
# name test is a heuristic and the rest of the sweep is not.
FACILITY_RE = re.compile(r"^(BL|SR|LI|BR|TS|FE)[-_]?\d*[A-Z]?([-_].+)?$|BUILDER")


def pre_gate(name: str, image: set[str]) -> tuple[str, str] | None:
    lowered = {m.lower() for m in image}
    if (
        name.lower() in lowered
        or MODULE_ALIASES.get(name.lower(), "").lower() in lowered
    ):
        return "SKIP", f"{name} is already shipped in the generic image"
    if FACILITY_RE.match(name):
        return (
            "REVIEW",
            f"{name} looks like a beamline/facility module rather than a device; "
            "its protocols belong to devices with their own modules",
        )
    return None


# ---------------------------------------------------------------- driver ----


def check(module_dir: Path, image: set[str]) -> dict:
    # A path that does not exist would otherwise be reported as REVIEW ("no
    # etc/builder.py"), which reads like a finding about the module rather than
    # a typo in the command line.
    if not module_dir.is_dir():
        sys.exit(f"no such module release directory: {module_dir}")
    pre = pre_gate(module_dir.parent.name, image)
    if pre is not None:
        verdict, reason = pre
        return {
            "path": str(module_dir),
            "verdict": verdict,
            "gate1": {"passed": True, "reasons": []},
            "gate2": {"verdict": verdict, "reasons": [reason], "parse": "not-run"},
        }
    fs_ok, fs_reasons = gate_filesystem(module_dir)
    b_verdict, b_reasons, extra = gate_builder(module_dir, image)
    if not fs_ok:
        verdict = "SKIP"
    elif b_verdict == "SKIP":
        verdict = "SKIP"
    else:
        verdict = b_verdict
    return {
        "path": str(module_dir),
        "verdict": verdict,
        "gate1": {"passed": fs_ok, "reasons": fs_reasons},
        "gate2": {"verdict": b_verdict, "reasons": b_reasons, **extra},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--candidates", type=Path, help="candidates.json from scan-candidates.py"
    )
    g.add_argument("--module", type=Path, help="a single module release directory")
    ap.add_argument(
        "--image-modules",
        type=Path,
        required=True,
        help="file of module names, one per line (from image-modules.sh)",
    )
    ap.add_argument("-o", "--out", type=Path, help="write full JSON here")
    args = ap.parse_args()

    image = {
        line.strip()
        for line in args.image_modules.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }

    if args.module:
        entries = [
            {
                "name": args.module.parent.name,
                "path": str(args.module),
                "version": args.module.name,
            }
        ]
    else:
        entries = json.loads(args.candidates.read_text())

    results = []
    for e in entries:
        r = check(Path(e["path"]), image)
        r["name"] = e["name"]
        r["version"] = e.get("version", "")
        results.append(r)

    if args.out:
        args.out.write_text(json.dumps(results, indent=1))

    counts = {"PASS": 0, "SKIP": 0, "REVIEW": 0}
    for r in results:
        counts[r["verdict"]] += 1
        reasons = r["gate1"]["reasons"] + r["gate2"]["reasons"]
        print(f"{r['verdict']}\t{r['name']}\t{r['version']}\t{'; '.join(reasons[:3])}")
    print(
        f"\nPASS={counts['PASS']} SKIP={counts['SKIP']} REVIEW={counts['REVIEW']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
