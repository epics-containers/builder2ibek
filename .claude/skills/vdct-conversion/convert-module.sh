#!/bin/bash
# Convert one DLS VDCT support module's Db sources to msi-native templates.
#
#   convert-module.sh <module> <dls-module-dir> <out-dir>
#
# Implements section 4 of the vdct-conversion skill, plus the two fixups that
# vdct2template cannot do itself (see FIXUPS below).  Re-runnable: it always
# starts from a clean copy of the read-only DLS sources.
set -euo pipefail

MOD=$1
SRC=$2
OUT=$3
HERE=$(cd "$(dirname "$0")" && pwd)

rm -rf "$OUT"; mkdir -p "$OUT"
find "$SRC" -maxdepth 3 -path '*App/Db/*' \
     \( -name '*.vdb' -o -name '*.template' -o -name '*.db' \) \
     -exec cp {} "$OUT"/ \;
chmod u+w "$OUT"/*

bash "$HERE/rename-vdct-orphans.sh" "$OUT" > "$OUT/.renames"
PYTHONPATH=$HERE uv run --no-project --with typer --with typing_extensions \
    python -m vdct2template --no-use-builder "$OUT" > "$OUT/.convert.log" 2>&1 \
    || { cat "$OUT/.convert.log"; exit 1; }

# drop the now-redundant VDCT sources
for v in "$OUT"/*.vdb; do
    [ -f "${v%.vdb}.template" ] && rm "$v" || echo "KEEP (no .template): $v"
done

# ---------------------------------------------------------------- FIXUPS ----
case "$MOD" in
OXCryo)
    # Nested expansion: OXCB700/OXCB800/OXNH700 -> OXcommonCB -> OXcommon.
    # vdct2template writes a middle-layer file twice and the second write (as
    # an Expansion) loses the `_` prefix its parents substitute with.  Both
    # levels pass CTEMP_DRVL/CTEMP_DRVH straight through unchanged, so the
    # middle layer's re-substitution is redundant *and* would be a msi
    # self-reference (`_CTEMP_DRVL=$(_CTEMP_DRVL)`).  Delete it: the parent's
    # `substitute "_CTEMP_DRVL=..."` is still in scope when OXcommon.template
    # is included one level down.
    sed -i '/^substitute "_CTEMP_DRV[LH]=\$(CTEMP_DRV[LH])"$/d' \
        "$OUT/OXcommonCB.template"
    ;;
gardasoftLED)
    # PP600SeriesChannel.template has two roles: DLS installs it standalone
    # (Db/Makefile) *and* PP612LED expands it twice.  vdct2template's `_`
    # prefix would make the standalone form unusable.  The prefix is only
    # needed when the parent passes a value that references the same macro
    # name; here the parent passes literals (N=1, N=2), and a `substitute`
    # beats a global -M/subst value, so the unprefixed name is safe for both.
    sed -i 's/^substitute "_N=/substitute "N=/' "$OUT/PP612LED.template"
    sed -i 's/\$(_N)/$(N)/g' "$OUT/PP600SeriesChannel.template"
    ;;
microlab500)
    # VDCT instance-port references.  `$(microlab500Left.STARTUP)` means "the
    # record bound to the STARTUP port of the microlab500Left expand instance";
    # VisualDCT resolves it at flatten time, vdct2template leaves it alone.
    # The child names that record "$(_P)$(_R):$(_SIDE):STARTUP" and the parent
    # expands it with _SIDE=LEFT / _SIDE=RIGHT.
    sed -i -e 's|\$(microlab500Left\.STARTUP)|$(P)$(R):LEFT:STARTUP|g' \
           -e 's|\$(microlab500Right\.STARTUP)|$(P)$(R):RIGHT:STARTUP|g' \
        "$OUT/microlab500whole.template"
    ;;
esac
# -----------------------------------------------------------------------------

bash "$HERE/default-annotation-macros.sh" "$OUT" > "$OUT/.defaults"

# assert no VDCT syntax survived and no source was left behind
if grep -l '^#!\|^ *expand(\|^template() {' "$OUT"/*.template 2>/dev/null; then
    echo "ERROR: VDCT syntax survives in $MOD" >&2; exit 1
fi
if ls "$OUT"/*.vdb >/dev/null 2>&1; then
    echo "ERROR: unconverted .vdb left in $MOD" >&2; exit 1
fi
echo "$MOD: converted $(ls "$OUT"/*.template | wc -l) templates"
