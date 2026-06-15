#!/usr/bin/env bash
# Pre-flight: create the host-side terminal-config dir before the
# container starts. Docker/podman create missing bind sources as
# root-owned directories, which then fight the user's UID on the host —
# easier to just mkdir as the host user first. install.sh's
# link_terminal_config creates the .claude/.claude.json children
# inside it on first run.
set -euo pipefail

mkdir -p "$HOME/.config/terminal-config"
