#!/bin/bash
set -euo pipefail

# Install Python dependencies and pre-commit hooks
uv venv --clear
hash -r
uv sync
pre-commit install --install-hooks

# Initialise only the submodules that are not checked out yet -- `git submodule
# status` prefixes those with '-'. A blanket `git submodule update --init` would
# silently move an already checked out submodule back to the pinned commit,
# losing whatever the developer had there.
if [ -f .gitmodules ]; then
    # Capture the status first: a failure inside <( ) is not caught by set -e,
    # so a broken `git submodule status` would silently read as "nothing to do".
    submodule_status=$(git submodule status)
    readarray -t uninitialised < <(printf '%s\n' "${submodule_status}" | awk '/^-/ {print $2}')
    for submodule in "${uninitialised[@]}"; do
        echo "Initialising submodule ${submodule}"
        # ibek-support-dls is on Diamond's internal GitLab, which is unreachable
        # from outside DLS, so warn rather than fail the whole container create.
        git submodule update --init -- "${submodule}" ||
            echo "WARNING: could not initialise ${submodule}, continuing without it"
    done
fi

# Populate $EPICS_ROOT/ibek-defs (defaults to /epics/ibek-defs) with links to the
# support yaml from both submodules. `ibek runtime generate2` resolves entity
# models from that folder and from the IOC config folder -- it never reads
# ibek-support*/ directly, so without this every entity fails validation.
./update-schema
