#!/bin/bash
# Run the mechanical stages of the sweep: candidate set, both eligibility gates,
# the description audit, and the skip report. Roughly three and a half minutes,
# nearly all of it stage 2 walking /dls_sw/prod.
#
# This does NOT generate or refresh any pattern folder. Sections 4-7 of SKILL.md
# (VDCT, docs curation, the manifest, entity models) need judgement and are
# worked per module.
#
# usage: run-sweep.sh [<workdir>] [<ioc-streamdevice>] [<ibek-runtime-streamdevice>]
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
WORK=${1:-$(mktemp -d)}
IOC=${2:-/workspaces/ioc-streamdevice}
LIB=${3:-/workspaces/ibek-runtime-streamdevice}
PY=${PY:-python3}

mkdir -p "$WORK"
echo "workdir: $WORK"

echo "== 1. the image's module set (gate 2's reference), from $IOC/Dockerfile"
bash "$HERE/image-modules.sh" "$IOC" | tee "$WORK/image-modules.txt"
"$PY" -c 'import json,sys; print(json.dumps([l.strip() for l in open(sys.argv[1]) if l.strip()]))' \
    "$WORK/image-modules.txt" > "$WORK/image-modules.json"

echo "== 2. candidate set + case-duplicate rule (~3 min: walks /dls_sw/prod)"
"$PY" "$HERE/scan-candidates.py" -o "$WORK" > "$WORK/candidates.tsv"

echo "== 3. eligibility gates"
"$PY" "$HERE/check-eligibility.py" \
    --candidates "$WORK/candidates.json" \
    --image-modules "$WORK/image-modules.txt" \
    -o "$WORK/eligibility.json" > "$WORK/eligibility.tsv"

echo "== 4. description quality across the patterns already in $LIB"
# The flags are part of the committed report (issue #115: "add those to the
# report alongside the skips"), so a failure here must stop the sweep - not
# leave a report that is silently missing a section. audit-descriptions.py is
# the one stage that needs a third-party import.
AUDIT=("$PY")
if ! "$PY" -c 'import yaml' 2>/dev/null; then
    command -v uv > /dev/null || {
        echo "audit-descriptions.py needs pyyaml, and there is no uv to borrow it from" >&2
        exit 1
    }
    echo "   ($PY has no pyyaml - running this stage through uv)"
    AUDIT=(uv run --no-project --with pyyaml python)
fi
"${AUDIT[@]}" "$HERE/audit-descriptions.py" --json "$WORK/descriptions.json" "$LIB" \
    > "$WORK/descriptions.tsv"

echo "== 5. skip report"
"$PY" "$HERE/render-report.py" --outdir "$WORK" --repo "$LIB" \
    > "$WORK/BUILD-TIME-ONLY.md"

echo
echo "candidates : $(($(wc -l < "$WORK/candidates.tsv") - 1))"
echo "PASS       : $(grep -c '^PASS' "$WORK/eligibility.tsv" || true)"
echo "SKIP       : $(grep -c '^SKIP' "$WORK/eligibility.tsv" || true)"
echo "REVIEW     : $(grep -c '^REVIEW' "$WORK/eligibility.tsv" || true)"
echo
echo "next: review $WORK/BUILD-TIME-ONLY.md, then work the PASS list per module"
echo "      (docs sweep needs a --skips-json run per module - see SKILL.md §5)"
