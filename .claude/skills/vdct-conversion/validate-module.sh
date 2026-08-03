#!/bin/bash
# Prove a converted module is semantically identical to the DLS VDCT build.
#
#   validate-module.sh <module> <dls-module-dir> <converted-dir>
#
# For every template DLS installs into db/, expand both sides with the same
# macro values and compare canonical (sorted record -> sorted field) sets.
# This is section 6c of the vdct-conversion skill.
set -uo pipefail

MOD=$1
SRC=$2
NEW=$3
HERE=$(cd "$(dirname "$0")" && pwd)
MSI=${MSI:-/dls_sw/epics/R7.0.7/base/bin/linux-x86_64/msi}
TMP=$(mktemp -d)

fail=0
for dls in "$SRC"/db/*.template; do
    t=$(basename "$dls")
    if [ ! -f "$NEW/$t" ]; then
        echo "MISSING in conversion: $t"; fail=1; continue
    fi

    # every macro named on either side, with defaults stripped
    macros=$( { cat "$dls" "$NEW/$t"; } \
        | grep -o '\$([A-Za-z_][A-Za-z0-9_]*[^)]*)' \
        | sed 's/[=)].*//;s/\$(//' | sort -u | grep -v '^_' )
    m=$(for x in $macros; do printf '%s=<%s>,' "$x" "$x"; done)

    ( cd "$SRC/db" && $MSI -I. -M "${m%,}" "$t" ) > "$TMP/$t.dls.db" 2> "$TMP/$t.dls.err"
    ( cd "$NEW"     && $MSI -I. -M "${m%,}" "$t" ) > "$TMP/$t.new.db" 2> "$TMP/$t.new.err"

    if [ -s "$TMP/$t.new.err" ]; then
        echo "MSI ERROR ($t): $(head -2 "$TMP/$t.new.err" | tr '\n' ' ')"; fail=1; continue
    fi
    # unresolved macros on the new side are a conversion bug
    if grep -qo '\$([A-Za-z_][^)]*)' "$TMP/$t.new.db"; then
        echo "UNRESOLVED ($t): $(grep -o '\$([A-Za-z_][^)]*)' "$TMP/$t.new.db" | sort -u | tr '\n' ' ')"
        fail=1
    fi

    for side in dls new; do
        uv run --no-project python "$HERE/canon-db.py" "$TMP/$t.$side.db" > "$TMP/$t.$side.canon"
    done

    if diff -q "$TMP/$t.dls.canon" "$TMP/$t.new.canon" > /dev/null; then
        echo "OK      $t  ($(grep -c '^record\|^[a-z]* ' "$TMP/$t.new.canon" 2>/dev/null || echo ?) records)"
    else
        echo "DIFFERS $t"
        diff "$TMP/$t.dls.canon" "$TMP/$t.new.canon" | head -20
        fail=1
    fi
done
echo "canon dir: $TMP"
exit $fail
