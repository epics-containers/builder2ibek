#!/usr/bin/env bash
# Pre-flight: create the host-side terminal-config dir before the
# container starts. Docker/podman create missing bind sources as
# root-owned directories, which then fight the user's UID on the host —
# easier to just mkdir as the host user first. install.sh's
# link_terminal_config creates the .claude/.claude.json children
# inside it on first run.
set -euo pipefail

mkdir -p "$HOME/.config/terminal-config"

# A read-only view of /dls_sw for the container. A readonly bind of
# an autofs root is not recursive on the RHEL8 kernel: submounts that autofs
# adds later arrive rw. bindfs -r refuses writes in its own daemon, and its
# lookups on the host trigger autofs, so the whole tree is visible and none
# of it is writable. devcontainer.json binds it back at /dls_sw.
# /dls is not mounted: it holds user data that Claude is not cleared to read.
# The bindfs daemon outlives the container; a later start reuses it.
if ! command -v bindfs >/dev/null; then
    echo "ERROR: bindfs is not installed on this host. It is required to" >&2
    echo "mount /dls_sw read-only into the container." >&2
    echo "Install it with: sudo yum install bindfs" >&2
    exit 1
fi

# Under the per-user runtime dir (tmpfs, gone at logout or reboot) rather than
# ~/.cache, which cleanup and disk-usage tools walk and delete from.
if [[ -z ${XDG_RUNTIME_DIR:-} ]]; then
    echo "ERROR: XDG_RUNTIME_DIR is not set; it holds the read-only view" >&2
    echo "of /dls_sw for the container." >&2
    exit 1
fi
ro_root="$XDG_RUNTIME_DIR/dls-ro"
for src in /dls_sw; do
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
    # bindfs always has the kernel check mode bits (default_permissions) and
    # does not pass NFS ACLs through, so ACL-granted visit directories would
    # read as Permission denied. --perms=a+rX shows everything as readable;
    # the daemon then reads as this user and the NFS server applies the ACLs.
    bindfs -r --no-allow-other --perms=a+rX "$src" "$mnt"
done
