# ideas from https://www.docker.com/blog/containerized-python-development-part-1/

# This file is for use as a .vscode devcontainer as well as a runtime 
# container. The devcontainer should be rootful and use podman or docker 
# with user namespaces.

ARG BASE="mcr.microsoft.com/vscode/devcontainers/python:0-3.10-bullseye"
FROM ${BASE} as base

# use root to pin where the packages will install
USER root
ENV PATH=/root/.local/bin:$PATH

FROM base as developer

WORKDIR /workspace
COPY . .

# install runtime from DIST if there is one
RUN mkdir -p /root/.local && \
    if [ -d dist ] ; then \
    touch requirements.txt && \
    pip install --user -r requirements.txt dist/*.whl ; \
    fi

FROM base as runtime

COPY --from=developer /root/.local /root/.local

ENTRYPOINT ["builder2ibek"]
CMD ["--version"]
