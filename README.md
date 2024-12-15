[![CI](https://github.com/epics-containers/builder2ibek/actions/workflows/ci.yml/badge.svg)](https://github.com/epics-containers/builder2ibek/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/epics-containers/builder2ibek/branch/main/graph/badge.svg)](https://codecov.io/gh/epics-containers/builder2ibek)
[![PyPI](https://img.shields.io/pypi/v/builder2ibek.svg)](https://pypi.org/project/builder2ibek)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)

# builder2ibek

A tool suite for converting DLS XML builder projects to epics-containers ibek.

Source          | <https://github.com/epics-containers/builder2ibek>
:---:           | :---:
PyPI            | `pip install builder2ibek`
Releases        | <https://github.com/epics-containers/builder2ibek/releases>

<pre><font color="#AAAAAA">╭─ Commands ───────────────────────────────────────────────────────────────────╮</font>
<font color="#AAAAAA">│ </font><font color="#2AA1B3"><b>xml2yaml       </b></font> Convert a builder XML IOC instance definition file into an   │
<font color="#AAAAAA">│ </font><font color="#2AA1B3"><b>               </b></font> ibek YAML file                                               │
<font color="#AAAAAA">│ </font><font color="#2AA1B3"><b>beamline2yaml  </b></font> Convert all IOCs in a BLXXI-SUPPORT project into a set of    │
<font color="#AAAAAA">│ </font><font color="#2AA1B3"><b>               </b></font> ibek services folders (TODO)                                 │
<font color="#AAAAAA">│ </font><font color="#2AA1B3"><b>autosave       </b></font> Convert DLS autosave DB template comments into autosave req  │
<font color="#AAAAAA">│ </font><font color="#2AA1B3"><b>               </b></font> files                                                        │
<font color="#AAAAAA">│ </font><font color="#2AA1B3"><b>db-compare     </b></font> Compare two DB files and output the differences              │
<font color="#AAAAAA">╰──────────────────────────────────────────────────────────────────────────────╯</font>
</pre>

```bash
builder2ibek

```python
from builder2ibek import __version__

print(f"Hello builder2ibek {__version__}")
```

Or if it is a commandline tool then you might put some example commands here:

```
python -m builder2ibek --version
```
