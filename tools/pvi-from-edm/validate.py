#!/usr/bin/env python3
"""Validate generated PVI held in a staging folder, one entity at a time.

For every entity with a `pvi:` section a test IOC instance is built from the
entity's parameters. ibek's generate2 and generate must both succeed and agree,
a .bob must appear, and real `msi` expands the IOC's ioc.subst, so that every
PVI record is compared with the records the IOC would load.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from dbparse import parse_db  # noqa: E402
from fielddefs import fields_of  # noqa: E402
from gen import entity_block, head_text  # noqa: E402
from release import db_search_path  # noqa: E402
from settings import CFG  # noqa: E402

IBEK = str(Path(sys.executable).parent / "ibek")
RECORD = re.compile(r'^\s*g?record\s*\(\s*"?([\w*]+)"?\s*,\s*(?:"([^"]+)"|([^",\s)]+))\s*\)', re.M)
FIELD_MARK = "__FIELD__"


def required_value(name: str, p: dict, entity: str):
    t = p.get("type")
    if t == "id":
        return f"ID-{entity}-{name}"
    if t == "str":
        return f"TEST-{name}"
    if t == "int":
        return 1
    if t == "float":
        return 1.0
    if t == "bool":
        return False
    if t == "enum":
        return next(iter(p["values"]))
    if t == "list":
        return []
    if t == "dict":
        return {}
    raise ValueError(f"parameter type {t}")


def object_attrs(block: str, param: str) -> list[str]:
    return sorted(set(re.findall(rf"\b{re.escape(param)}\.(\w+)", block)))


def build_instance(em: dict, module: str, numeric: bool = False) -> tuple[list[dict], list[dict]]:
    """Stub entity models for object parameters, and the instance entities."""
    block = yaml.safe_dump(em, width=100000)  # anchors expanded
    stubs: list[dict] = []
    entities: list[dict] = []
    me: dict = {"type": f"{module}.{em['name']}"}
    for name, p in (em.get("parameters") or {}).items():
        if p.get("default") is not None:
            continue
        if p.get("type") == "object":
            model = f"Stub{em['name']}{name}"
            attrs = [a for a in object_attrs(block, name) if a != "name"]
            stubs.append(
                {
                    "name": model,
                    "description": "test stand-in",
                    "parameters": {
                        "name": {"type": "id", "description": "id"},
                        **{a: {"type": "int" if numeric else "str", "description": "attribute"} for a in attrs},
                    },
                }
            )
            sid = f"STUB-{em['name']}-{name}"
            entities.append({"type": f"sweepstub.{model}", "name": sid, **{a: 1 if numeric else f"TEST-{a}" for a in attrs}})
            me[name] = sid
        else:
            me[name] = required_value(name, p, em["name"])
    return stubs, entities + [me]


def foreign_modules(text: str, own: str) -> set[str]:
    return {m for m in re.findall(r"\btype:\s*[\"']?(\w+)\.\w+", text) if m != own}


def definitions_map() -> dict[str, Path]:
    out: dict[str, Path] = {}
    for repo in CFG.repos.values():
        for f in sorted(repo.glob("*/*.ibek.support.yaml")):
            m = re.search(r"^module:\s*(\S+)", f.read_text(errors="replace"), re.M)
            if m:
                out.setdefault(m.group(1), f)
    return out


def dep_definitions(text: str, own: str, defs: dict[str, Path]) -> list[Path]:
    found: list[Path] = []
    todo = list(foreign_modules(text, own))
    seen = {own}
    while todo:
        m = todo.pop()
        if m in seen or m not in defs:
            continue
        seen.add(m)
        found.append(defs[m])
        todo.extend(foreign_modules(defs[m].read_text(errors="replace"), m))
    return found


def strip_blocks(subst: str, search: list[Path], extra: list[Path]) -> tuple[str, list[str]]:
    """Point every `file` at its base name for -I; drop the ones nowhere to be found."""
    missing: list[str] = []
    dirs = search + extra

    def rep(m):
        base = m.group(1).rsplit("/", 1)[-1]
        if any((d / base).is_file() for d in dirs):
            return f'file "{base}" {{{m.group(2)}}}'
        missing.append(m.group(1))
        return ""

    return re.sub(r'^file "([^"]+)" \{(.*?)^\}', rep, subst, flags=re.S | re.M), missing


def parse_subst(text: str) -> list[tuple[str, dict]]:
    out = []
    for m in re.finditer(r'^file "([^"]+)" \{\s*\npattern\s*\n(.*?)^\}', text, re.S | re.M):
        rows = [re.findall(r'"((?:[^"\\]|\\.)*)"', ln) for ln in m.group(2).splitlines() if ln.strip().startswith("{")]
        for row in rows[1:]:
            out.append((m.group(1), dict(zip(rows[0], row, strict=False))))
    return out


def expand_all(s: str, env: dict) -> str:
    s = re.sub(r"\$\((\w+)=([^)]*)\)", lambda m: env.get(m.group(1), m.group(2)), s)
    return re.sub(r"\$\((\w+)\)", lambda m: env.get(m.group(1), m.group(0)), s)


def expand_db(subst: str, search: list[Path], runtime: Path, box: Path) -> dict:
    """All records of an ioc.subst, with real msi; our own parser only if msi fails."""
    text, missing = strip_blocks(subst, search, [runtime])
    tmp = box / "msi.subst"
    tmp.write_text(text)
    msi = CFG.msi_path()
    cmd = [str(msi)] + [a for d in [*search, runtime] for a in ("-I", str(d))] + ["-S", str(tmp)]
    if msi:
        p = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    else:
        p = subprocess.CompletedProcess(cmd, 1, "", "msi not found")
    real: dict[str, str] = {}
    pvi: list[str] = []
    expander = "msi"
    if p.returncode == 0:
        for t, a, b in RECORD.findall(p.stdout):
            (pvi.append(a or b) if t == "*" else real.__setitem__(a or b, t))
    else:
        expander = "own parser (msi: " + (p.stderr.strip().splitlines() or ["failed"])[-1][:120] + ")"
        for fname, macros in parse_subst(text):
            d = runtime if fname.endswith(".pvi.template") else next((x for x in search if (x / fname).is_file()), None)
            if d is None:
                continue
            if fname.endswith(".pvi.template"):
                pvi += [expand_all(a or b, macros) for t, a, b in RECORD.findall((d / fname).read_text()) if t == "*"]
            else:
                real |= {expand_all(r, macros): v.rtype for r, v in parse_db(d / fname, macros, search=search).records.items()}
    groups = sorted(set(re.findall(r'"([^"]*PVI)": \{', p.stdout))) if p.returncode == 0 else []
    return dict(real=real, pvi=pvi, expander=expander, missing_templates=missing, groups=groups)


def marked_device(text: str) -> str:
    """A device with `X.FIELD` as `X__FIELD__FIELD`, a legal name msi carries through."""
    return re.sub(r"^(\s*(?:read_pv|write_pv): .*)\.([A-Z0-9]+\$?)[ \t]*$", rf"\1{FIELD_MARK}\2", text, flags=re.M)


def add_pv_true(text: str, entity: str) -> str:
    s, e = entity_block(text, entity)
    lines = text.splitlines()
    i = next(j for j in range(s, e) if lines[j].startswith("      pv_prefix:"))
    return "\n".join([*lines[:i], "      pv: true", *lines[i:]]) + "\n"


def run_ibek(args: list[str], env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([IBEK, "runtime", *args], env=env, capture_output=True, text=True, errors="replace")


def last_error(p: subprocess.CompletedProcess) -> str:
    """The end of the Python exception, which follows the traceback frames."""
    text = (p.stdout + p.stderr).strip()
    text = re.sub(r"[│╭╰─╮╯]+", " ", text)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    start = next((i for i, ln in reversed(list(enumerate(lines))) if re.match(r"[\w.]*(Error|Exception)\b.*", ln)), max(len(lines) - 4, 0))
    return " | ".join(lines[start : start + 8])[:600]


def validate_entity(module: str, em: dict, staged: Path, text: str, ov: dict, defs: dict, box: Path) -> dict:
    """Stub attributes are text first; a template that does arithmetic on them needs numbers."""
    r = _validate_entity(module, em, staged, text, ov, defs, box, False)
    if not r.get("ok") and r.get("cls") == "test_instance" and any(a for a in ("real number", "must be real", "unsupported operand") if a in r.get("reason", "")):
        return _validate_entity(module, em, staged, text, ov, defs, box, True)
    return r


def _validate_entity(module: str, em: dict, staged: Path, text: str, ov: dict, defs: dict, box: Path, numeric: bool) -> dict:
    res: dict = dict(entity=em["name"])
    shutil.rmtree(box, ignore_errors=True)
    (box / "pvi-defs").mkdir(parents=True)
    (box / "ioc" / "config").mkdir(parents=True)
    for f in staged.glob("*.pvi.device.yaml"):
        shutil.copy(f, box / "pvi-defs" / f.name)
    stubs, entities = build_instance(em, module, numeric)
    inst = box / "test-ioc.ibek.ioc.yaml"
    inst.write_text(yaml.safe_dump(dict(ioc_name="test-ioc", description=f"test instance for {module}", entities=entities), sort_keys=False))
    stubf = box / "sweepstub.ibek.support.yaml"
    stubf.write_text(yaml.safe_dump(dict(module="sweepstub", entity_models=stubs), sort_keys=False))
    sup = staged / ov.get("yaml", f"{module}.ibek.support.yaml")
    dep_defs = dep_definitions(text, module, defs)
    for d in dep_defs:
        for f in d.parent.glob("*.pvi.device.yaml"):
            if not (box / "pvi-defs" / f.name).exists():
                shutil.copy(f, box / "pvi-defs" / f.name)
    all_defs = [sup, stubf, *dep_defs]
    env = {**os.environ, "EPICS_ROOT": str(box), "IOC_NAME": "test-ioc"}
    out = box / "runtime"
    defargs = [a for d in all_defs for a in ("--definitions", str(d))]
    g2 = run_ibek(["generate2", "-i", str(inst), *defargs, "-o", str(out)], env)
    if g2.returncode:
        base = run_ibek(["generate2", "-i", str(inst), *defargs, "-o", str(out), "--no-pvi"], env)
        res.update(ok=False, cls="test_instance" if base.returncode else "ibek_pvi", reason=last_error(g2))
        return res
    subst2 = (out / "ioc.subst").read_text()
    stcmd2 = (out / "st.cmd").read_text()
    g1 = run_ibek(["generate", str(inst), *map(str, all_defs), "-o", str(out)], env)
    if g1.returncode:
        res.update(ok=False, cls="ibek_pvi", reason="generate: " + last_error(g1))
        return res
    subst = (out / "ioc.subst").read_text()
    res["generate_matches_generate2"] = subst == subst2 and (out / "st.cmd").read_text() == stcmd2
    release = Path(ov["release"])
    search = db_search_path(release, [CFG.repos[ov["repo"]] / ov.get("dir", module)])
    for d in dep_defs:
        if d.parent not in search:
            search.append(d.parent)
    # what the instance itself emits: no PVI PV, so no record("*") in any file or under msi
    res["n_record_star_in_files"] = sum(f.read_text(errors="replace").count('record("*"') for f in out.rglob("*") if f.is_file())
    res["n_record_star_under_msi"] = len(expand_db(subst, search, out, box)["pvi"])
    # no PVI records to expand, so a copy with them, its field PVs marked, gives
    # msi the same macros: only the check uses it
    shadow = box / "shadow"
    (shadow / "pvi-defs").mkdir(parents=True)
    (shadow / "ioc" / "config").mkdir(parents=True)
    for f in (box / "pvi-defs").glob("*.pvi.device.yaml"):
        (shadow / "pvi-defs" / f.name).write_text(marked_device(f.read_text()))
    sup2 = shadow / sup.name
    sup2.write_text(add_pv_true(sup.read_text(), em["name"]))
    shadow_defs = [a for d in [sup2, stubf, *dep_defs] for a in ("--definitions", str(d))]
    g3 = run_ibek(["generate2", "-i", str(inst), *shadow_defs, "-o", str(shadow / "runtime")], {**env, "EPICS_ROOT": str(shadow)})
    if g3.returncode:
        res.update(ok=False, cls="validator_error", reason="check copy: " + last_error(g3))
        return res
    out = shadow / "runtime"
    x = expand_db((out / "ioc.subst").read_text(), search, out, box)
    real, pvi = x["real"], x["pvi"]
    res.update(expander=x["expander"], missing_templates=x["missing_templates"], n_records_loaded=len(real), n_pvi_signals=len(pvi))
    unexpanded = sorted({n for n in pvi if "$(" in n})
    bases = {n: n.partition(FIELD_MARK)[0] for n in pvi}
    missing = sorted({n.replace(FIELD_MARK, ".") for n in pvi if bases[n] not in real and "$(" not in n})
    bad_fields = []
    for n in pvi:
        fld = n.partition(FIELD_MARK)[2].rstrip("$")
        if fld and bases[n] in real:
            defs = fields_of(real[bases[n]], release)
            if defs is None or fld not in defs:
                bad_fields.append(f"{bases[n]}.{fld} ({real[bases[n]]})")
    res["n_field_pvs"] = sum(1 for n in pvi if FIELD_MARK in n)
    res["field_pv_invalid"] = sorted(set(bad_fields))
    res.update(pvi_pv_missing_from_db=missing, pvi_pv_unexpanded=unexpanded)
    if bad_fields:
        res.update(ok=False, cls="field_invalid", reason=f"{len(res['field_pv_invalid'])} PVs name no field of their record, e.g. {res['field_pv_invalid'][0]}")
        return res
    if not pvi:
        res.update(ok=False, cls="no_pvi_template", reason="ioc.subst loads no PVI records")
        return res
    res["pvi_group_pvs"] = x["groups"]
    badgroup = [g for g in x["groups"] if "$(" in g]
    if badgroup:
        res.update(ok=False, cls="pv_unexpanded", reason=f"PVI PV keeps a macro: {badgroup[0]}")
        return res
    if unexpanded:
        res.update(ok=False, cls="pv_unexpanded", reason=f"{len(unexpanded)} PVs keep a macro, e.g. {unexpanded[0]}")
        return res
    if missing:
        res.update(ok=False, cls="pv_missing", reason=f"{len(missing)} of {len(pvi)} PVs not in the expanded db, e.g. {missing[0]}")
        return res
    bobs = sorted(p.name for p in (box / "opi").glob("*.bob"))
    res["bobs"] = bobs
    want = em["pvi"]["yaml_path"].split(".")[0] + ".pvi.bob"
    if want not in bobs:
        res.update(ok=False, cls="no_bob", reason=f"{want} not generated")
        return res
    res["ok"] = True
    return res


def yaml_only_adds_pvi(head: str, new: str) -> str:
    """Empty when the support yaml differs from HEAD only by added pvi sections."""
    removed = [ln for ln in difflib.ndiff(head.splitlines(), new.splitlines()) if ln.startswith("- ")]
    if removed:
        return f"yaml lines changed: {removed[0][2:]}"
    a, b = yaml.safe_load(head), yaml.safe_load(new)
    for em in b.get("entity_models") or []:
        em.pop("pvi", None)
    for em in a.get("entity_models") or []:
        em.pop("pvi", None)
    return "" if a == b else "yaml content differs beyond pvi sections"


def hygiene(staged: Path) -> list[str]:
    """Files of a public repo must hold nothing the hygiene pattern matches."""
    if not CFG.hygiene_pattern:
        return []
    pattern = re.compile(CFG.hygiene_pattern, re.I)
    hits = []
    for f in staged.glob("*.pvi.device.yaml"):
        for i, ln in enumerate(f.read_text().splitlines(), 1):
            if pattern.search(ln):
                hits.append(f"{f.name}:{i}: {ln.strip()}")
    return hits


def validate_stage(module: str, ov: dict, staged: Path, defs: dict | None = None) -> dict:
    """Per-entity results for a staged module; merged .bob files land in <sandbox>/<module>/opi."""
    defs = defs or definitions_map()
    repo = CFG.repos[ov["repo"]]
    yaml_name = ov.get("yaml", f"{module}.ibek.support.yaml")
    text = (staged / yaml_name).read_text()
    sup = yaml.safe_load(text)
    root = CFG.sandbox / module
    shutil.rmtree(root, ignore_errors=True)
    (root / "opi").mkdir(parents=True)
    res: dict = dict(module=module, entities={})
    res["yaml_purity"] = yaml_only_adds_pvi(head_text(repo, f"{ov.get('dir', module)}/{yaml_name}"), text)
    mod_name = sup["module"]
    for em in sup.get("entity_models") or []:
        if not em.get("pvi"):
            continue
        box = root / re.sub(r"\W", "_", em["name"])
        try:
            r = validate_entity(mod_name, em, staged, text, ov, defs, box)
        except Exception as e:  # noqa: BLE001
            r = dict(entity=em["name"], ok=False, cls="validator_error", reason=f"{type(e).__name__}: {e}")
        res["entities"][em["name"]] = r
        if r.get("ok"):
            for b in (box / "opi").glob("*.bob"):
                if b.name != "index.bob" or not (root / "opi" / "index.bob").exists():
                    shutil.copy(b, root / "opi" / b.name)
        keep = box / "failed.txt"
        if r.get("ok"):
            shutil.rmtree(box, ignore_errors=True)
        else:
            keep.write_text(json.dumps(r, indent=1, default=str))
    res["hygiene"] = hygiene(staged) if ov["repo"] in CFG.public_repos else []
    res["ok_entities"] = sorted(k for k, v in res["entities"].items() if v.get("ok"))
    return res
