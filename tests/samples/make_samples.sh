# regenerate the tests results files
#
# For each sample XML this script:
#   1. converts XML → YAML via builder2ibek xml2yaml
#   2. generates st.cmd + ioc.subst via ibek runtime generate2
#
# caution: validate that the diffs look good before committing changes

THIS=$(dirname $0)
cd $THIS

set -e

# pass a list of XML files as args or use all xml files in the samples dir
XMLS=${@:-$(ls *.xml)}

for x in ${XMLS}; do
  stem=$(echo "${x%.xml}" | tr '[:upper:]' '[:lower:]')
  y="${stem}.yaml"

  echo "=== $x ==="

  # step 1: XML → YAML
  echo "  xml2yaml → $y"
  builder2ibek xml2yaml "$x" --yaml "$y"

  # step 2: YAML → st.cmd + ioc.subst
  tmpdir=$(mktemp -d)
  cp "$y" "$tmpdir/ioc.yaml"

  if ibek runtime generate2 "$tmpdir" --output "$tmpdir" --no-pvi 2>/dev/null; then
    echo "  generate2 → ${stem}.st.cmd, ${stem}.ioc.subst"
    cp "$tmpdir/st.cmd" "${stem}.st.cmd"
    cp "$tmpdir/ioc.subst" "${stem}.ioc.subst"
  else
    echo "  generate2 SKIP (validation failed)"
    rm -f "${stem}.st.cmd" "${stem}.ioc.subst"
  fi

  rm -rf "$tmpdir"
done

builder2ibek db-compare ./SR03C-VA-IOC-01_expanded.db ./sr03c-va-ioc-01.db --output ./compare.diff --ignore SR03C-VA-IOC-01:
