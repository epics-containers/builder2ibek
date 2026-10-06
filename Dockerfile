# The devcontainer should use the developer target and run as root with podman
# or docker with user namespaces.
#
# epics-containers/epics-base's own `developer` stage is built FROM DLS's
# ubuntu-devcontainer (oh-my-zsh, gh/glab/lazygit/just, terminal-config wiring,
# uv), then adds a real EPICS base + pvxs build under /epics and msi at
# $EPICS_BASE/bin/<arch>/msi -- which update-schema, the test suite and the
# vdct-conversion skill's validation steps already assume exists at the
# default EPICS_ROOT=/epics. Using it directly means nothing from
# ubuntu-devcontainer needs to be re-added here.
#
# This pins to the LTS Ubuntu ("noble") that epics-base's published image was
# built against, not DLS's newer `resolute` -- there is no published
# epics-base-developer image built on `resolute` today. See
# https://github.com/epics-containers/epics-base/blob/main/Dockerfile
#
# To bump: check published tags with
#   curl -sL "https://ghcr.io/token?scope=repository:epics-containers/epics-base-developer:pull" \
#     | grep -o '"token":"[^"]*"' | cut -d'"' -f4 | xargs -I{} \
#     curl -sL -H "Authorization: Bearer {}" \
#     https://ghcr.io/v2/epics-containers/epics-base-developer/tags/list
FROM ghcr.io/epics-containers/epics-base-developer:7.0.10ec5 AS developer

# Add any system dependencies for the developer/build environment here
# RUN apt-get update -y && apt-get install -y --no-install-recommends \
#     graphviz \
#     && apt-get dist-clean
