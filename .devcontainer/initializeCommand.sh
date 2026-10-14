#!/usr/bin/env bash
# Pre-flight: create the host-side terminal-config dir before the
# container starts. Docker/podman create missing bind sources as
# root-owned directories, which then fight the user's UID on the host —
# easier to just mkdir as the host user first. install.sh's
# link_terminal_config creates the .claude/.claude.json children
# inside it on first run.
set -euo pipefail

mkdir -p "$HOME/.config/terminal-config"

# Read-only views of /dls and /dls_sw for the container. A readonly bind of
# an autofs root is not recursive on the RHEL8 kernel: submounts that autofs
# adds later arrive rw. bindfs -r refuses writes in its own daemon, and its
# lookups on the host trigger autofs, so the whole tree is visible and none
# of it is writable. devcontainer.json binds these back at /dls and /dls_sw.
# The bindfs daemons outlive the container; a later start reuses them.
if ! command -v bindfs >/dev/null; then
    echo "ERROR: bindfs is not installed on this host. It is required to" >&2
    echo "mount /dls and /dls_sw read-only into the container." >&2
    echo "Install it with: sudo yum install bindfs" >&2
    exit 1
fi

ro_root="$HOME/.cache/dls-ro"
for src in /dls /dls_sw; do
    mnt="$ro_root/${src#/}"
    mkdir -p "$mnt"
    if mountpoint -q "$mnt"; then
        # reuse only a live, read-only bindfs of $src; a dead daemon leaves
        # "Transport endpoint is not connected"
        read -r m_src m_type m_opts < <(findmnt -n -o SOURCE,FSTYPE,OPTIONS --mountpoint "$mnt")
        if [[ $m_src == "$src" && $m_type == fuse* && ,$m_opts, == *,ro,* ]] &&
            ls "$mnt" >/dev/null 2>&1; then
            continue
        fi
        fusermount -u "$mnt"
    fi
    # bindfs adds allow_other by default, which fusermount refuses unless
    # /etc/fuse.conf has user_allow_other. Not needed under rootless podman:
    # container root maps to this UID, which owns the mount.
    bindfs -r --no-allow-other "$src" "$mnt"
done
