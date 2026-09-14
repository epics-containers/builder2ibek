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
  # comm requires strict C-locale byte order. sort -u under the ambient locale
  # (e.g. en_US.UTF-8) sorts letter case differently and desyncs from that,
  # so comm -23 below silently misclassifies real parameters as
  # annotation-only whenever a file mixes uppercase and lowercase macro names
  # (P/Q/NCHAN vs gda_name/gda_desc is exactly this case -- verified on
  # ODPsu's gda templates, where it flagged P, PV, Q and NCHAN for defaulting).
  # LC_ALL=C on both sort calls keeps them in the order comm expects.
  # macros surviving once comment lines are removed -> real parameters
  body=$(grep -v '^[[:space:]]*#' "$f" \
         | grep -o '\$([A-Za-z_][A-Za-z0-9_]*[^)]*)' | names | LC_ALL=C sort -u)
  # every macro mentioned anywhere, including inside #% annotations
  all=$(grep -o '\$([A-Za-z_][A-Za-z0-9_]*[^)]*)' "$f" | names | LC_ALL=C sort -u)
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
