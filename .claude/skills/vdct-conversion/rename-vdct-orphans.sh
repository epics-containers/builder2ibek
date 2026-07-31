#!/bin/bash
# Rename VDCT-tagged source files to .vdb so vdct2template's *.vdb glob sees them.
# EXCLUDES files named inside an expand() block - those must keep their .template
# name or the reference breaks.
shopt -s nullglob
cd "$1" || exit 1
refs=$(grep -ho 'expand("[^"]*"' * 2>/dev/null | sed 's/expand("//;s/"//' | sort -u)
for f in *.template *.db; do
  [ -f "$f" ] || continue
  head -40 "$f" | grep -q '^#!\|^ *expand(\|^template() {' || continue
  if printf '%s\n' "$refs" | grep -qxF "$f"; then
    echo "SKIP (expand-referenced): $f"; continue
  fi
  echo "RENAME: $f -> ${f%.*}.vdb"
  mv "$f" "${f%.*}.vdb"
done
