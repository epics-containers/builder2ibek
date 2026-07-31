#!/bin/bash
# Give an empty default to every macro that appears ONLY inside #% annotation
# comments (DLS EDM/GDA tooling: name, gda_bpm_name, gda_curr_name, ...).
#
#   $(name)  ->  $(name=)
#
# Those macros have no counterpart in epics-containers, but msi still sees them,
# so they must be defaulted rather than turned into entity-model parameters.
# Macros that reach a record body are left alone - they become parameters.
#
# Usage: default-annotation-macros.sh <folder> [--dry-run]
shopt -s nullglob
DIR="$1"; DRY="$2"
[ -d "$DIR" ] || { echo "usage: $0 <folder> [--dry-run]" >&2; exit 1; }

# strip the name out of a $(NAME) or $(NAME=default) occurrence
names() { sed 's/[=)].*//;s/\$(//'; }

for f in "$DIR"/*.template; do
  # macros surviving once comment lines are removed -> real parameters
  body=$(grep -v '^[[:space:]]*#' "$f" \
         | grep -o '\$([A-Za-z_][A-Za-z0-9_]*[^)]*)' | names | sort -u)
  # every macro mentioned anywhere, including inside #% annotations
  all=$(grep -o '\$([A-Za-z_][A-Za-z0-9_]*[^)]*)' "$f" | names | sort -u)
  # annotation-only = all - body
  todo=$(comm -23 <(printf '%s\n' "$all") <(printf '%s\n' "$body"))

  for m in $todo; do
    # skip if it already carries a default somewhere
    grep -q "\$($m=" "$f" && continue
    grep -q "\$($m)" "$f" || continue
    echo "${f##*/}: \$($m) -> \$($m=)"
    [ "$DRY" = "--dry-run" ] || sed -i "s/\$($m)/\$($m=)/g" "$f"
  done
done
