#!/usr/bin/env python
"""List the classes in a builder.py that are Ident() targets.

Any class printed as LOCAL must keep `name: type: id` in its ibek entity model --
something references it. Classes not listed can drop `name`.

Handles the tuple form `Ident('desc', (ClassA, ClassB))`, where EVERY class in the
tuple is a target. A naive `sed 's/.*, *//'` silently keeps only the last one.

Usage: find-id-targets.py <path/to/builder.py>
"""

import re
import sys

txt = open(sys.argv[1]).read()

# classes defined in this file
local = set(re.findall(r"^class\s+(\w+)", txt, re.M))

# Ident( <quoted desc> , <target> ) where target is a name or a (a, b) tuple
targets: dict[str, list[str]] = {}
for m in re.finditer(
    r"""Ident\s*\(\s*(?:"[^"]*"|'[^']*')\s*,\s*(\([^)]*\)|[A-Za-z_][\w.]*)""", txt
):
    for name in re.findall(r"[A-Za-z_][\w.]*", m.group(1)):
        targets.setdefault(name, []).append(m.group(0)[:60])

if not targets:
    print("no Ident() targets - every class may drop `name`")

for name in sorted(targets):
    kind = "LOCAL " if name in local else "extern"
    note = (
        "" if name in local else "  (asyn port / other module - not this module's id)"
    )
    print(f"{kind} {name}{note}")

missing = sorted(local - set(targets))
if missing:
    print("\nnot referenced, may drop `name`:")
    for name in missing:
        print(f"       {name}")
