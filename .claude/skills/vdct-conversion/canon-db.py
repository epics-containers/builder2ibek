import re
import sys

txt = open(sys.argv[1]).read()

# Drop comments, but only outside quoted strings. A bare re.sub(r"#.*", ...)
# truncates field values containing '#' - EPICS hardware links look like
# field(OUT, "#C0 S0 @") - and because both sides of a comparison are truncated
# identically, genuinely different records would compare equal.
txt = re.sub(
    r'"[^"\\]*(?:\\.[^"\\]*)*"|#[^\n]*',
    lambda m: m.group(0) if m.group(0).startswith('"') else "",
    txt,
)
blocks = re.findall(
    r'record\s*\(\s*(\w+)\s*,\s*"([^"]*)"\s*\)\s*\{(.*?)\n\}', txt, re.S
)
out = []
for typ, name, body in blocks:
    fields = sorted(re.findall(r'field\s*\(\s*(\w+)\s*,\s*"([^"]*)"\s*\)', body))
    out.append(f"{typ} {name}\n" + "".join(f"    {f}={v}\n" for f, v in fields))
print("".join(sorted(out)))
