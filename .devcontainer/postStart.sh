#!/bin/bash
set -euo pipefail

# Wipe any credential helpers and SSH URL rewrites injected by VS Code's
# Dev Containers extension when it copies the host gitconfig. An empty-string
# value resets the helper list so only an explicit PAT via `just gh-auth`
# can authenticate to remotes.
git config --global credential.helper ''
git config --global --unset-all url.ssh://git@github.com/.insteadOf 2>/dev/null || true

# If gh CLI has cached credentials (survive container rebuild), re-register
# its git credential helper so HTTPS remotes authenticate automatically.
if gh auth status &>/dev/null; then
    gh auth setup-git
fi
