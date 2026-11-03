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
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    bind9-dnsutils \
    ca-certificates \
    curl \
    iproute2 \
    iputils-ping \
    jq \
    netcat-openbsd \
    openssl \
    tcpdump \
    traceroute \
    unzip \
    && apt-get dist-clean

# Kubernetes CLI tools, linux/amd64 only. To upgrade one, change its version and
# take the new sha256 from the checksum file published with that release.
# kubectl stays within one minor version of the clusters. kubelogin is installed
# under the name that kubeconfigs invoke it by: kubectl oidc-login.
ARG KUBECTL_VERSION=1.36.6
ARG KUBECTL_SHA256=29818b6729dc9262b692307470d0558d027725e738be5dd47c760261868a2634
ARG HELM_VERSION=4.3.1
ARG HELM_SHA256=0403a88ae20913d11b10a2467b50087721fea7581736da6b9d3992f5357fe54b
ARG K9S_VERSION=0.51.0
ARG K9S_SHA256=c3752ad51a5a4015a113819c4eeb6e55a4d0e4b8e652494797532f6fc8161dd7
ARG STERN_VERSION=1.35.0
ARG STERN_SHA256=03729b01a8fcfab25f6ea53389bd38bc37400ff86d90cd2dcda541f248cf843e
ARG KUBELOGIN_VERSION=1.36.4
ARG KUBELOGIN_SHA256=9e8baeb4905d35a301304af2548324997add512fe94ab20e65993d167212bf85
ARG ARGOCD_VERSION=3.5.7
ARG ARGOCD_SHA256=e9b7c3f5316b8546bdd499dfb8d874e413a5e3605899a55ec2ce0b668a3e2801
ARG YQ_VERSION=4.54.1
ARG YQ_SHA256=8e34fc298390875de416e6a4afcb8cabeceb25d9aa8506c1a2f9353cf702ea5f

RUN set -eu; \
    tmp=$(mktemp -d); cd "$tmp"; \
    fetch() { curl -fsSL -o "$1" "$2"; echo "$3  $1" | sha256sum -c -; }; \
    github=https://github.com; \
    fetch kubectl "https://dl.k8s.io/release/v${KUBECTL_VERSION}/bin/linux/amd64/kubectl" "$KUBECTL_SHA256"; \
    fetch helm.tgz "https://get.helm.sh/helm-v${HELM_VERSION}-linux-amd64.tar.gz" "$HELM_SHA256"; \
    fetch k9s.tgz "$github/derailed/k9s/releases/download/v${K9S_VERSION}/k9s_Linux_amd64.tar.gz" "$K9S_SHA256"; \
    fetch stern.tgz "$github/stern/stern/releases/download/v${STERN_VERSION}/stern_${STERN_VERSION}_linux_amd64.tar.gz" "$STERN_SHA256"; \
    fetch kubelogin.zip "$github/int128/kubelogin/releases/download/v${KUBELOGIN_VERSION}/kubelogin_linux_amd64.zip" "$KUBELOGIN_SHA256"; \
    fetch argocd "$github/argoproj/argo-cd/releases/download/v${ARGOCD_VERSION}/argocd-linux-amd64" "$ARGOCD_SHA256"; \
    fetch yq "$github/mikefarah/yq/releases/download/v${YQ_VERSION}/yq_linux_amd64" "$YQ_SHA256"; \
    tar xzf helm.tgz --no-same-owner --strip-components=1 linux-amd64/helm; \
    tar xzf k9s.tgz --no-same-owner k9s; \
    tar xzf stern.tgz --no-same-owner stern; \
    unzip -q kubelogin.zip kubelogin; \
    install -m 0755 kubectl helm k9s stern argocd yq /usr/local/bin/; \
    install -m 0755 kubelogin /usr/local/bin/kubectl-oidc_login; \
    cd /; rm -rf "$tmp"
