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

# samples that generate2 rejected; reported at the end so that one bad sample
# does not stop the rest being regenerated
failed=""

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
    # ibek leaves a trailing blank line on generated files; strip it so the
    # pre-commit end-of-file-fixer doesn't show phantom diffs.
    printf '%s\n' "$(cat "$tmpdir/st.cmd")" > "${stem}.st.cmd"
    printf '%s\n' "$(cat "$tmpdir/ioc.subst")" > "${stem}.ioc.subst"
  else
    echo " ERROR SKIPPING !!! generate2 SKIP (validation failed)"
    rm -f "${stem}.st.cmd" "${stem}.ioc.subst"
    failed="$failed $stem"
  fi

  rm -rf "$tmpdir"
done

builder2ibek db-compare ./SR03C-VA-IOC-01_expanded.db ./sr03c-va-ioc-01.db --output ./compare.diff --ignore SR03C-VA-IOC-01:

# Record which support module revisions these outputs were built from, so that
# bumping a submodule pin without regenerating (or regenerating against a
# checkout that is not the pin) fails with a sentence rather than a diff.
# See test_sample_pins.py.
{
  echo "# Written by make_samples.sh -- do not hand edit."
  for repo in ibek-support ibek-support-dls; do
    echo "$repo $(git -C "../../$repo" rev-parse HEAD)"
  done
} > GENERATED_AGAINST

if [ -n "$failed" ]; then
  echo "ERROR: generate2 failed, outputs removed for:$failed"
  exit 1
fi
