# Squash Commit Mapping

This documents how the 80 commits from `refactor-multi-agent` were squashed into
10 logical commits on `multi-agent-refactor-squash`.

## Commit 1: Update devcontainer, CI, and project config

| Hash | Original message |
|------|-----------------|
| bda8536 | getting ready to use claude in the devcontainer |
| 9741841 | updates for claude running in the devcontainer |
| 00d7490 | Gitignore .claude/settings.local.json |
| 622452f | devcontainer: install GitHub CLI (gh) |
| da3642b | Merge pull request #79 from epics-containers/claudeing |
| a99fa40 | devcontainer: add Claude auth mount; update ioc-convert skill for parallel subagents |
| 6c82837 | ci: upgrade to Python 3.13; update ibek-support-dls submodule |
| b5baaa8 | devcontainer: broaden write/read/clone permissions in settings.json |
| 849a178 | gitignore: add ioc-convert/ioc-check last-services-repo cache files |
| 9e5cfdb | update ibek-support-dls with i19-vac changes |
| 02e7648 | allow all bash inside the devcontainer |
| ed9f254 | Use per-agent EPICS_ROOT for parallel ioc-convert/ioc-check |
| 1d7980f | add hook to block Claude Code outside devcontainer |
| 650a725 | use EPICS_TZ=GMT0BST default to match .ioc_template |
| 1151656 | update ibek support with new CI |
| 2542c3c | Fix mypy errors and docs build |
| 784d790 | Fix CI test failure: use temp dir for EPICS_ROOT when /epics not writable |
| 1a821a9 | CI: checkout submodules so update-schema can find support YAMLs |
| 2f5c41a | CI: init only ibek-support submodule (not ibek-support-dls) |
| 174d66a | skip tests that wont work in github |
| 1818f0f | Consolidate devIocStats: remove DLS copy, use public iocStats module |

## Commit 2: Add Claude Code skills, settings, and CLAUDE.md

| Hash | Original message |
|------|-----------------|
| 043f982 | add the ioc-convert skill |
| 99c1c43 | Rename AGENTS.md to CLAUDE.md and improve ioc-convert skill |
| 597b081 | ioc-convert skill: make services repo arg optional |
| 7d177e0 | ioc-convert skill: infer services repo from IOC prefix |
| cc9583e | refine ioc-convert skill using i19-va-ioc-01 |
| ff17960 | skills: note that entity_enabled/type in ioc.subst patterns are harmless |
| 248e92e | settings/skills: allow all bash commands; fix support YAML lookup |
| 2df5901 | ioc-convert skill: run pytest after converter/support YAML changes |
| e39e8a3 | Add support-inspect skill and shared builder.py analysis methodology |
| ea9e9d7 | ioc-check: reference shared vxworks-to-rtems-differences.md |
| 0f09bf6 | support-inspect: allow Skill tool invocation |
| 1801207 | support-inspect: search all EPICS versions when locating module |
| 4aeb2e2 | Add ioc-inspect skill for inspecting IOC XML definitions |
| b75fd5b | ioc-convert: resolve _RELEASE paths and pass to subagents |
| 6a53844 | Document XML template pattern (auto_xml_*) across all skills |
| 8ea17f1 | Trim CLAUDE.md from 270 to 57 lines, extract ibek-concepts skill |
| 45bffe9 | Decompose ioc-convert into composable skills with shared references |
| f8eb5bd | Prevent duplicate module folders across ibek-support and ibek-support-dls |
| d416eeb | Consolidate duplicated ibek rules — ibek-concepts is single source of truth |
| bb5218f | add the skill beamline-check |
| cd9d3a8 | Increase parallel subagent batch size from 3-5 to 10 in orchestrator skills |
| 4f7d4ae | record builder2bek syntax for claude |
| 1110203 | add memory to skills and make a skill edit skill |
| 72544df | add the beamline-reconvert skill |
| e34e1cd | Fix uppercase service folder names in beamline reconvert |
| e84707d | add a ibek-support-ansible skill |
| 80b0ae9 | Add MCP server for sharing tools with GitHub Copilot users |
| d1e6ee7 | Remove MCP server — tools provide data without the intelligence to act on it |

## Commit 3: Improve converter framework: default omission and --description

| Hash | Original message |
|------|-----------------|
| 630f917 | omit parameters matching support YAML defaults during conversion |
| c5818e2 | Add --description option to xml2yaml CLI |
| 0cf7c43 | fix incorrect string coersions in motors |
| 67e8a68 | linting |

## Commit 4: Add converters for early IOC samples (BL15I, hidenRGA, CryoCoolerXV)

| Hash | Original message |
|------|-----------------|
| 143d16b | Add hidenRGA support: converter, ibek YAML, and test sample |
| 98a962d | Add s7nodave and CryoCoolerXV support; add CryoCoolerXV converter |
| cbee083 | BL15I-VA-IOC-01: converters, support YAMLs, and test sample |
| 245dc1f | make all ADAravis AutoADGenICam |
| 5f3afdc | update vacuum test outputs |

## Commit 5: Add converters for BL19I beamline conversion

| Hash | Original message |
|------|-----------------|
| e360873 | first pass implementing i19 va 01 |
| cc9583e | refine ioc-convert skill using i19-va-ioc-01 |
| 1189c96 | ipac converter: fix Hy8002 carrier interrupt vector offset |
| 0c95daf | fixes for bl19i-va-ioc-01 |
| 08eed91 | /beamline-convert BL19I phase 1 |
| 335ebc2 | BL19I beamline convert phase 2: converter and sample fixes |
| c6e12a0 | fixes to converters after i19 beamline convert phase 2 |
| 3fcf4f8 | fix conversion of all test xml files |

## Commit 6: Add converters for BL21I beamline conversion

| Hash | Original message |
|------|-----------------|
| 688556b | fixes to support yaml after i21 beamline convert phase 1 |
| aaa3273 | fixes after i21 beamline convert phase 2 |
| 0cf7c43 | fix incorrect string coersions in motors |
| 001ed78 | fixes for i21 beamline-convert phase 3 |

## Commit 7: Add converters for BL11I and BL04I beamline conversions

| Hash | Original message |
|------|-----------------|
| 18b3c4c | updates to support i11 beamline conversion |
| 0f1aa4f | updates for i04 beamline convert |

## Commit 8: Parametrize tests and add runtime asset generation

| Hash | Original message |
|------|-----------------|
| 355ca2c | Parametrize test_convert and test_generate per sample XML |
| 6fd7c2a | make all xml tests also test runtime assets |
| 8f06f72 | Fix all sample IOCs to generate runtime assets (st.cmd + ioc.subst) |
| e155bba | fix tests after I19 beamline convert phase 1 |
| 784d790 | Fix CI test failure: use temp dir for EPICS_ROOT when /epics not writable |
| 174d66a | skip tests that wont work in github |

## Commit 9: Add and update test samples with runtime assets

| Hash | Original message |
|------|-----------------|
| 14 5f3afdc | update vacuum test outputs |
| adbb498 | add i19 VA 01 to samples to test |
| 09a3cba | also fix motorpositioner.yaml |
| 3fcf4f8 | fix conversion of all test xml files |
| 8f06f72 | Fix all sample IOCs to generate runtime assets (st.cmd + ioc.subst) |
| 0c95daf | fixes for bl19i-va-ioc-01 |
| 335ebc2 | BL19I beamline convert phase 2: converter and sample fixes |
| 688556b | fixes to support yaml after i21 beamline convert phase 1 |
| aaa3273 | fixes after i21 beamline convert phase 2 |
| 001ed78 | fixes for i21 beamline-convert phase 3 |
| 18b3c4c | updates to support i11 beamline conversion |
| 0f1aa4f | updates for i04 beamline convert |

## Commit 10: Add documentation for beamline conversion workflow

| Hash | Original message |
|------|-----------------|
| 4406160 | add docs on converted beamline |
| 1a7db1b | add post-conversion workflow guidance to after-beamline-convert doc |
| b41f14e | add runtime support how-to and update after-beamline-convert |
| 2fab252 | clarify that auto-conversion support YAML may need manual adjustments |
| 2542c3c | Fix mypy errors and docs build |
| 80b0ae9 | Add MCP server for sharing tools with GitHub Copilot users (ADR only) |
| d1e6ee7 | Remove MCP server — tools provide data without the intelligence to act on it (ADR only) |
