# generate2 Error Categorization

How to diagnose errors from `ibek runtime generate2` and determine the fix type.

| Error pattern | Cause | Fix type |
|---|---|---|
| Unknown entity type `foo.Bar` | No entity model exists | Support YAML — add entity model |
| Unknown parameter `X` on `foo.Bar` | Parameter missing or renamed | Support YAML — add parameter; or Converter — rename/drop attribute |
| Validation error on a field | Wrong ibek type, or XML value ibek can't accept | Support YAML — fix type; or Converter — transform value |
| `object BL19I-VA-... not found` or `object XXX not found` | Referenced entity's id field is `type: str` not `type: id`, or `name`/`type: id` was wrongly removed from a non-leaf entity | Support YAML — change id field to `type: id`; or restore `name: type: id` and update converter to keep `name` |
| `Field required` on a parameter | Parameter has no default and wasn't set in XML | Support YAML — add `default:` |
| `database arg 'fooN' not found in context` | Template uses a param name the entity model doesn't define | Support YAML — add param or fix databases.args; or Converter — rename attribute |
| Attribute value wrong or unwanted | XML value needs transformation | Converter — re-run xml2yaml after fix |

## Fix type distinction

- **Support YAML fixes** do not require re-running `xml2yaml` — only
  `./update-schema` and `generate2` need re-running.
- **Converter fixes** require re-running `xml2yaml` first (to regenerate
  `ioc.yaml` with the transformed attributes), then `./update-schema` and
  `generate2`.

## Known recurring issues

Patterns seen across multiple beamline conversions:

| Issue | Symptom | Fix |
|---|---|---|
| `when: last` not in ibek | `pingWait` entities fail generate2 | Known gap — ibek 3.3.3 hasn't implemented `When.last` |
| gdaPlugins incomplete expansion | Only primary ROI+Stat chain generated; missing roi1-6, stat1-6, ffmpeg, PVA | Major gap in gdaPlugins converter — deliberate simplification |
| Dropped `records.*` entities | calcout/calc/bi/mbbi records silently omitted | Converter TODO — raw EPICS records not yet supported |
| NDAttributes `%s` format strings | `dbpf %s%s` in post_init outputs unresolved format strings | ADCore support YAML bug — PV names not resolved |
| vacValveGroup column misalignment | Rows have wrong number of values for multi-column pattern | dlsPLC support YAML — check column count matches template |
| Moxa16 fixed channel count | NCHANS<16 devices still get 16 channels | terminalServer support YAML — handle NCHANS param |
| `when: last` not implemented | All `utility.pingWait` uses fail | Known ibek gap |

## Object-reference chain note

If you see `object BL19I-VA-... not found`, check the `type:` of the id field
in the **referenced** entity's support YAML — it must be `type: id` not
`type: str`. Also check the `name` vs `device` pattern: some modules use
`name` as `type: id` (e.g. `mks937b.mks937bImg` → id = `IMG01`), others use
`device` as `type: id` (e.g. `mks937a.mks937aImg` → id = `BL19I-VA-IMG-03`).
