# The devcontainer should use the developer target and run as root with podman
# or docker with user namespaces.
ARG PYTHON_VERSION=3.13
FROM ghcr.io/diamondlightsource/ubuntu-devcontainer:noble AS developer

# Add any system dependencies for the developer/build environment here
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    graphviz \
    && apt-get dist-clean

# Node is required by Claude Code's hook runtime
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    nodejs \
    && apt-get dist-clean

# GitHub CLI — used by Claude to authenticate to github.com via PAT
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | \
    dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && \
    chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        | tee /etc/apt/sources.list.d/github-cli.list > /dev/null && \
    apt-get update && apt-get install -y --no-install-recommends gh && \
    apt-get dist-clean

# GitLab CLI — used by Claude to authenticate to gitlab instances via PAT.
# No apt repo, so install from the upstream release tarball.
ARG GLAB_VERSION=1.92.1
RUN curl -fsSL "https://gitlab.com/gitlab-org/cli/-/releases/v${GLAB_VERSION}/downloads/glab_${GLAB_VERSION}_linux_amd64.tar.gz" \
      | tar -xz -C /tmp bin/glab && \
    install -m 0755 /tmp/bin/glab /usr/local/bin/glab && \
    rm -rf /tmp/bin
