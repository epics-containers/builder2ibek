#!/bin/bash
# Report the entity-model parameter set for each installed template.
#
#   macro-report.sh <converted-dir> <template> [<template> ...]
#
# Walks the msi include closure, then splits the macros a caller must supply
# from those the templates default themselves.  `_`-prefixed macros are
# supplied by the parent's `substitute` and are never parameters.
set -uo pipefail
DIR=$1; shift

closure() {   # emit this template and everything it includes, transitively
    local t=$1
    echo "$t"
    grep -ho '^include *"[^"]*"' "$DIR/$t" 2>/dev/null \
        | sed 's/include *"//;s/"//' | while read -r c; do closure "$c"; done
}

for t in "$@"; do
    files=$(closure "$t" | sort -u)
    echo "=== $t   [closure: $(echo $files | tr '\n' ' ')]"

    all=$(cd "$DIR" && cat $files | grep -o '\$([A-Za-z_][A-Za-z0-9_]*[^)]*)')
    # macros the parent supplies itself via `substitute` are not parameters
    subst=$(cd "$DIR" && cat $files | grep -ho '^substitute *"[A-Za-z_][A-Za-z0-9_]*=' \
        | sed 's/substitute *"//;s/=$//' | sort -u)
    # names appearing at least once with no default
    req=$(echo "$all" | grep -v '=' | sed 's/\$(//;s/)//' | grep -v '^_' | sort -u)
    req=$(comm -23 <(echo "$req") <(echo "$subst"))
    # names that always carry a default
    defd=$(echo "$all" | grep '=' | sed 's/\$(//;s/[=)].*//' | grep -v '^_' | sort -u)
    defd=$(comm -23 <(echo "$defd") <(echo "$req"))

    echo "  required: $(echo $req)"
    echo "  defaulted: $(echo $defd)"
    echo "  docs:"
    (cd "$DIR" && cat $files) | grep -h '^# *% *macro,' | sed 's/^# *% *macro, */    /' | sort -u
    echo
done
