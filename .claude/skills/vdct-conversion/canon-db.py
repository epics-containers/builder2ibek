import re
import sys

txt = open(sys.argv[1]).read()
txt = re.sub(r"#.*", "", txt)  # drop comments
blocks = re.findall(
    r'record\s*\(\s*(\w+)\s*,\s*"([^"]*)"\s*\)\s*\{(.*?)\n\}', txt, re.S
)
out = []
for typ, name, body in blocks:
    fields = sorted(re.findall(r'field\s*\(\s*(\w+)\s*,\s*"([^"]*)"\s*\)', body))
    out.append(f"{typ} {name}\n" + "".join(f"    {f}={v}\n" for f, v in fields))
print("".join(sorted(out)))
