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

## How to use the devcontainer

This repo includes a devcontainer for testing and developing converters.

To use this re-open in container.

- First make sure you have the submodules
  - git submodule update --init
- This adds ibek-support and ibek-support-dls meaning that we can validate converted projects against a global ibek schema that include all support modules currently defined in ibek-support*.
- To add a new IOC to the tests simply copy its XML definition into `tests/samples`. Then run `./tests/samples/make_samples.sh` to convert the XML to YAML and create a test for it.
- important: this will re-convert all of the sample XML files in the samples folder. Always check the diff before committing.

Once you have done this you can iterate on converting your XML:

- make changes to the ibek support yaml in `ibek-support-dls` and `ibek-support`
- make changes/additions to src/builder2ibek/converters/*.py
- re-convert your XML with `./tests/samples/make_samples.sh`
- rebuild the global ioc yaml schema with `./update-schema`
- Inspect your generated YAML in `tests/samples` and look for schema validation issues (make sure you have the RedHat YAML extension installed in VSCode)
- NOTE: sometimes the YAML extension does not notice changes to the schema. If you are seeing errors that you think are incorrect, opening the exttension settings and toggling the `Yaml: Validate` off and on again can help - it's the last option.
