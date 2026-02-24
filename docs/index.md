---
html_theme.sidebar_secondary.remove: true
---

```{include} ../README.md
:end-before: <!-- README only content
```

## What is builder2ibek for?

DLS has hundreds of EPICS IOCs defined using the
[XMLbuilder](https://github.com/dls-controls/iocbuilder) format — XML files
that describe which support modules to load and how to configure them.
`builder2ibek` is the bridge between that legacy world and
[epics-containers](https://epics-containers.github.io), the modern approach
to running EPICS IOCs in containers under Kubernetes.

In epics-containers, each IOC instance is expressed as an ibek `ioc.yaml` file
and support modules are described by `ibek.support.yaml` entity models.
`builder2ibek` converts the former and herein documents how to author the latter.

## Philosophy of conversion

The goal is not to produce a one-off translation that is immediately edited
by hand.  The goal is to make `xml2yaml` produce **correct output directly**,
so that:

- The original builder XML remains the source of truth.  While a beamline
  is being converted it may still ocasionally require updates to its
  traditional builder XML, then you can re-run `xml2yaml` and get
  a correct `ioc.yaml` without manual patching.
- Every IOC that uses the same support module benefits from the same fix.
  Improvements to a converter or support YAML are shared automatically.
- The conversion is reproducible and testable — sample XML/YAML pairs in
  `tests/samples/` catch regressions in CI.

When `xml2yaml` output needs correcting, the right response is almost always
to improve the **converter** (`src/builder2ibek/converters/`) or the **ibek
support YAML** (`ibek-support-dls/` or `ibek-support/`), not to edit the
generated `ioc.yaml` by hand.

## Two levels of conversion work

**Converting IOC instances** (`xml2yaml`) is the common case and should be
straightforward.  For many IOCs the converters and support YAML already exist;
you run the command, review the output, and verify with `db-compare`.

**Creating or updating ibek support YAML** for a module is needed less
frequently — but requires deeper
knowledge of the module's `builder.py`, its DB templates, and the ibek YAML
schema.  It is a good candidate for AI assistance.

Claude AI has been used successfully to create ibek support YAML and install.yml from scratch
for support modules.  For example, the `hidenRGA` support YAML was generated with
Claude and is available as a reference at
[ibek-support-dls hidenRGA-CLAUDE](https://gitlab.diamond.ac.uk/controls/containers/utils/ibek-support-dls/-/tree/hidenRGA-CLAUDE/hidenRGA).

This repository contains an [AGENTS.md](https://github.com/epics-containers/builder2ibek/blob/main/AGENTS.md)
that describes the full context and skills needed for an AI agent to repeat
that process for other modules.

## Where to start

[**Converting an existing DLS IOC XML to ibek YAML**](how-to/convert-ioc-instance.md)

[**Verifying the converted IOC against the original builder database**](how-to/verify-with-devcontainer.md)

[**Creating ibek support YAML for a simple builder.py**](tutorials/create-support-yaml.md)

[**Creating ibek support YAML from a more complex builder.py**](tutorials/create-support-yaml-advanced.md)

[**xml2yaml output is wrong for a particular module — fixing the converter**](how-to/create-converter.md)

[**Generating autosave request files from DLS DB templates**](how-to/autosave.md)

[**Migrating old vacuum/interlock modules to dlsPLC**](reference/dlsplc-migration.md)

[**Setting up a new Generic IOC repository**](how-to/create-generic-ioc-repo.md)

How the documentation is structured
-----------------------------------

Documentation is split into [four categories](https://diataxis.fr), also accessible from links in the top bar.

<!-- https://sphinx-design.readthedocs.io/en/latest/grids.html -->

::::{grid} 2
:gutter: 4

:::{grid-item-card} {material-regular}`directions_walk;2em`
```{toctree}
:maxdepth: 2
tutorials
```
+++
Tutorials for installation and typical usage. New users start here.
:::

:::{grid-item-card} {material-regular}`directions;2em`
```{toctree}
:maxdepth: 2
how-to
```
+++
Practical step-by-step guides for the more experienced user.
:::

:::{grid-item-card} {material-regular}`info;2em`
```{toctree}
:maxdepth: 2
explanations
```
+++
Explanations of how it works and why it works that way.
:::

:::{grid-item-card} {material-regular}`menu_book;2em`
```{toctree}
:maxdepth: 2
reference
```
+++
Technical reference material including APIs and release notes.
:::

::::
