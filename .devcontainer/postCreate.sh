#!/bin/bash
set -euo pipefail

# Install Claude Code CLI
curl -fsSL https://claude.ai/install.sh | bash

# Install Python dependencies and pre-commit hooks
uv venv --clear
uv sync
pre-commit install --install-hooks
git submodule update --init
