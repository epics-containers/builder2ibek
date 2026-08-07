#!/bin/bash
# Print the set of support modules an ioc-* image ships, read from its Dockerfile.
#
# This is gate 2's reference set. The Dockerfile is the truth today; when the
# build-time management work lands in ioc-streamdevice the truth moves to that
# repo's lock file and this script must follow it.
#
# usage: image-modules.sh [<ioc-repo-checkout>]     (default /workspaces/ioc-streamdevice)
#
# Rules:
#   * a module is installed by a `RUN ansible.sh <name>` line
#   * `ansible.sh <name> --tags ...` is a PARTIAL run - a build-stage tool
#     (`vdct`), not a support module. Excluded.
#   * `ansible.sh ioc` is the generic IOC's own source. Excluded.
#   * if ARG DEVELOPER points at another ioc-* image, that image's modules are
#     also present and this script says so rather than guessing.
set -euo pipefail

REPO=${1:-/workspaces/ioc-streamdevice}
DF=$REPO/Dockerfile
[ -f "$DF" ] || { echo "no Dockerfile at $DF" >&2; exit 1; }

grep -E '^[[:space:]]*RUN[[:space:]]+ansible\.sh[[:space:]]' "$DF" |
    sed -E 's/^[[:space:]]*RUN[[:space:]]+ansible\.sh[[:space:]]+//' |
    while read -r name rest; do
        case "$rest" in *--tags*) continue ;; esac
        [ "$name" = ioc ] && continue
        echo "$name"
    done | sort -u

# Warn if the developer base is itself a generic IOC: its modules are inherited
# and must be unioned in by hand (its Dockerfile is in its own repo).
if grep -qE '^[[:space:]]*ARG[[:space:]]+DEVELOPER=.*ioc-[a-z]' "$DF"; then
    echo "WARNING: DEVELOPER base is an ioc-* image - union in its module set too" >&2
    grep -E '^[[:space:]]*ARG[[:space:]]+DEVELOPER=' "$DF" >&2
fi
