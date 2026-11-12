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

# Pin the runtime pattern library and the ioc-streamdevice-runtime image as the
# tests do: clones of the library read the submodule
eval "$(python3 ../pattern_pins.py)"

# pass a list of XML files as args or use all xml files in the samples dir
XMLS=${@:-$(ls *.xml)}

# samples that generate2 rejected; reported at the end so that one bad sample
# does not stop the rest being regenerated
failed=""

for x in ${XMLS}; do
  stem=$(echo "${x%.xml}" | tr '[:upper:]' '[:lower:]')
  y="${stem}.yaml"

  echo "=== $x ==="

  # step 1: XML → YAML, into a services-repo instance of its own, as the tests
  # do, so that the runtime patterns it uses are added. The files a converter
  # writes next to the ioc.yaml go to config/<stem>/, not among the samples.
  tmpdir=$(mktemp -d)
  instance="$tmpdir/services/$stem"
  config="$instance/config"
  mkdir -p "$config"
  printf 'ioc-instance:\n  image: REPLACE_WITH_IMAGE_URI\n' > "$instance/values.yaml"
  echo "  xml2yaml → $y"
  builder2ibek xml2yaml "$x" --yaml "$config/ioc.yaml"
  cp "$config/ioc.yaml" "$y"
  rm -f "${stem}.runtime-lock.yaml"
  vendored=""
  if [ -f "$instance/runtime-lock.yaml" ]; then
    echo "  runtime patterns → ${stem}.runtime-lock.yaml"
    cp "$instance/runtime-lock.yaml" "${stem}.runtime-lock.yaml"
    vendored=$(grep -o 'config/[^:]*' "$instance/runtime-lock.yaml" | sed 's|config/||')
  fi
  rm -rf "config/${stem}"
  for side in "$config"/*; do
    name=$(basename "$side")
    [ "$name" = "ioc.yaml" ] && continue
    echo "$vendored" | grep -qx "$name" && continue
    mkdir -p "config/${stem}"
    echo "  side file → config/${stem}/$name"
    cp "$side" "config/${stem}/"
  done

  # step 2: YAML → st.cmd + ioc.subst

  if ibek runtime generate2 "$config" --output "$config" --no-pvi 2>/dev/null; then
    echo "  generate2 → ${stem}.st.cmd, ${stem}.ioc.subst"
    # ibek leaves a trailing blank line on generated files; strip it so the
    # pre-commit end-of-file-fixer doesn't show phantom diffs.
    printf '%s\n' "$(cat "$config/st.cmd")" > "${stem}.st.cmd"
    printf '%s\n' "$(cat "$config/ioc.subst")" > "${stem}.ioc.subst"
  else
    echo " ERROR SKIPPING !!! generate2 SKIP (validation failed)"
    rm -f "${stem}.st.cmd" "${stem}.ioc.subst"
    failed="$failed $stem"
  fi

  rm -rf "$tmpdir"
done

builder2ibek db-compare ./SR03C-VA-IOC-01_expanded.db ./sr03c-va-ioc-01.db --output ./compare.diff --ignore SR03C-VA-IOC-01:

if [ -n "$failed" ]; then
  echo "ERROR: generate2 failed, outputs removed for:$failed"
  exit 1
fi
