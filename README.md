[![CI](https://github.com/epics-containers/builder2ibek/actions/workflows/ci.yml/badge.svg)](https://github.com/epics-containers/builder2ibek/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/epics-containers/builder2ibek/branch/main/graph/badge.svg)](https://codecov.io/gh/epics-containers/builder2ibek)
[![PyPI](https://img.shields.io/pypi/v/builder2ibek.svg)](https://pypi.org/project/builder2ibek)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)

# builder2ibek

A tool suite for converting DLS XMLbuilder IOC projects to
[epics-containers](https://github.com/epics-containers) ibek.

Source          | <https://github.com/epics-containers/builder2ibek>
:---:           | :---:
PyPI            | `pip install builder2ibek`
Documentation   | <https://epics-containers.github.io/builder2ibek>
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

## Where to start

**Converting an existing DLS IOC XML to ibek YAML**
→ [Convert a builder XML IOC instance](https://epics-containers.github.io/builder2ibek/how-to/convert-ioc-instance.html)

**Verifying the converted IOC against the original builder database**
→ [Verify with devcontainer and db-compare](https://epics-containers.github.io/builder2ibek/how-to/verify-with-devcontainer.html)

**Creating ibek support YAML for a DLS-internal module (new to ibek)**
→ [Tutorial: Creating ibek support YAML from a builder.py module](https://epics-containers.github.io/builder2ibek/tutorials/create-support-yaml.html)

**Creating ibek support YAML for a complex or open-source module**
→ [Advanced: ibek support YAML for a complex builder.py module](https://epics-containers.github.io/builder2ibek/tutorials/create-support-yaml-advanced.html)

**xml2yaml output is wrong for a particular module — fixing the converter**
→ [Create a builder2ibek converter](https://epics-containers.github.io/builder2ibek/how-to/create-converter.html)

**Generating autosave request files from DLS DB templates**
→ [Generate autosave req files](https://epics-containers.github.io/builder2ibek/how-to/autosave.html)

**Migrating old vacuum/interlock modules to dlsPLC**
→ [dlsPLC migration reference](https://epics-containers.github.io/builder2ibek/reference/dlsplc-migration.html)

**Setting up a new Generic IOC repository**
→ [Create a Generic IOC repo](https://epics-containers.github.io/builder2ibek/how-to/create-generic-ioc-repo.html)

<!-- README only content. Anything below this line won't be included in index.md -->

See <https://epics-containers.github.io/builder2ibek> for full documentation.
