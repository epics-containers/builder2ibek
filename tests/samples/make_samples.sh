# regenerate the tests results files
#
# For each sample XML this script:
#   1. converts XML → YAML via builder2ibek xml2yaml, into an instance folder
#      pinned to the runtime image, so that a pattern-only sample vendors its
#      runtime patterns (written to <stem>.patterns and <stem>.runtime-lock.yaml)
#   2. generates st.cmd + ioc.subst via ibek runtime generate2
#
# caution: validate that the diffs look good before committing changes

THIS=$(dirname $0)
cd $THIS
REPO=$(cd ../.. && pwd)

set -e

# Vendor offline, as the tests do (see offline_patterns in tests/conftest.py):
# patterns from the library submodules, base schemas from a copy of the
# committed cache, with the network fetch sent to a dead proxy.
schema_cache=$(mktemp -d)
cp -r ../schema-cache/. "$schema_cache"
export IBEK_SCHEMA_CACHE=$schema_cache
export IBEK_PATTERN_LIBRARIES="ibek-runtime-streamdevice=$REPO/ibek-runtime-streamdevice,ibek-runtime-support=$REPO/ibek-runtime-support"
export HTTPS_PROXY=http://127.0.0.1:9 https_proxy=http://127.0.0.1:9
unset NO_PROXY no_proxy
image=$(python3 -c "import re,sys; print(re.search(r'DEFAULT_RUNTIME_IMAGE = \"(.*)\"', open(sys.argv[1]).read())[1])" "$REPO/src/builder2ibek/vendor_patterns.py")

# pass a list of XML files as args or use all xml files in the samples dir
XMLS=${@:-$(ls *.xml)}

# samples that generate2 rejected; reported at the end so that one bad sample
# does not stop the rest being regenerated
failed=""

for x in ${XMLS}; do
  stem=$(echo "${x%.xml}" | tr '[:upper:]' '[:lower:]')
  y="${stem}.yaml"

  echo "=== $x ==="

  # step 1: XML → YAML, in an instance folder of its own so that the files a
  # converter writes next to the ioc.yaml go to config/<stem>/, not among the
  # samples, and vendored patterns go to the instance
  tmpdir=$(mktemp -d)
  instance="$tmpdir/instance"
  mkdir -p "$instance/config"
  printf 'ioc-instance:\n  image: %s\n' "$image" > "$instance/values.yaml"
  echo "  xml2yaml → $y"
  builder2ibek xml2yaml "$x" --yaml "$instance/config/ioc.yaml" \
    --patterns-out "$tmpdir/patterns"
  cp "$instance/config/ioc.yaml" "$y"
  rm -f "${stem}.patterns" "${stem}.runtime-lock.yaml"
  if [ -s "$tmpdir/patterns" ]; then
    echo "  patterns → ${stem}.patterns, ${stem}.runtime-lock.yaml"
    cp "$tmpdir/patterns" "${stem}.patterns"
    # record the source as vendoring from GitHub does (canonical_lock in conftest)
    sed -e "s#source: $REPO/#source: github.com/epics-containers/#" \
      "$instance/runtime-lock.yaml" > "${stem}.runtime-lock.yaml"
  fi
  vendored=""
  [ -f "$instance/runtime-lock.yaml" ] && vendored=$(sed -n 's#^      config/##p' "$instance/runtime-lock.yaml" | cut -d: -f1)
  rm -rf "config/${stem}"
  for side in "$instance/config"/*; do
    name=$(basename "$side")
    [ "$name" = "ioc.yaml" ] && continue
    echo "$vendored" | grep -qxF "$name" && continue
    mkdir -p "config/${stem}"
    echo "  side file → config/${stem}/$name"
    cp "$side" "config/${stem}/"
  done

  # step 2: YAML → st.cmd + ioc.subst

  if ibek runtime generate2 "$instance/config" --output "$tmpdir/runtime" --no-pvi 2>/dev/null; then
    echo "  generate2 → ${stem}.st.cmd, ${stem}.ioc.subst"
    # ibek leaves a trailing blank line on generated files; strip it so the
    # pre-commit end-of-file-fixer doesn't show phantom diffs.
    printf '%s\n' "$(cat "$tmpdir/runtime/st.cmd")" > "${stem}.st.cmd"
    printf '%s\n' "$(cat "$tmpdir/runtime/ioc.subst")" > "${stem}.ioc.subst"
  else
    echo " ERROR SKIPPING !!! generate2 SKIP (validation failed)"
    rm -f "${stem}.st.cmd" "${stem}.ioc.subst"
    failed="$failed $stem"
  fi

  rm -rf "$tmpdir"
done

rm -rf "$schema_cache"

builder2ibek db-compare ./SR03C-VA-IOC-01_expanded.db ./sr03c-va-ioc-01.db --output ./compare.diff --ignore SR03C-VA-IOC-01:

if [ -n "$failed" ]; then
  echo "ERROR: generate2 failed, outputs removed for:$failed"
  exit 1
fi
