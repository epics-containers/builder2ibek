# Cached base schemas for offline vendoring

The published `ibek.ioc.schema.json` of each image the tests vendor runtime
patterns for, laid out as ibek caches it under `$IBEK_SCHEMA_CACHE`:
`<registry>/<org>/<image without -runtime>/<tag>.json`, with a
`<tag>.validators.json` naming the URL it came from.

The tests and `tests/samples/make_samples.sh` point `IBEK_SCHEMA_CACHE` at a copy
of this folder and send ibek's fetch to a dead proxy, so `ibek pattern add` uses
these copies and never the network. See "Vendoring offline in the tests" in
`.claude/skills/shared/testing-and-ci.md`.

To add a tag:

```bash
gh release download <tag> -R epics-containers/ioc-streamdevice -p ibek.ioc.schema.json
mv ibek.ioc.schema.json ghcr.io/epics-containers/ioc-streamdevice/<tag>.json
echo '{"url": "https://github.com/epics-containers/ioc-streamdevice/releases/download/<tag>/ibek.ioc.schema.json"}' \
  > ghcr.io/epics-containers/ioc-streamdevice/<tag>.validators.json
```
