FROM node:22-bookworm

# Install system dependencies
RUN apt-get update && apt-get install -y \
  git \
  curl \
  jq \
  ripgrep \
  fd-find \
  && rm -rf /var/lib/apt/lists/*

# Install GitHub CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
  | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
  && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
  | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
  && apt-get update && apt-get install -y gh \
  && rm -rf /var/lib/apt/lists/*

# Python toolchain for this project. This is a Python codebase (FastAPI +
# SQLAlchemy + Celery) managed with uv (pyproject.toml + uv.lock); the Node base
# image only carries the Sandcastle/Codex harness. uv provisions a managed
# CPython 3.13 (bookworm only ships 3.11; the host runs 3.13), so `uv sync` /
# `uv run pytest` work in a clean container. Installed into /usr/local/bin for
# all users.
RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh

# Build-args for UID/GID alignment: sandcastle docker build-image
# defaults these to the host user's UID/GID so image-built files
# and bind-mounted files share an owner without runtime chown.
ARG AGENT_UID=1000
ARG AGENT_GID=1000

# Rename the base image's "node" user to "agent" and align UID/GID.
RUN groupmod -o -g $AGENT_GID node && usermod -o -u $AGENT_UID -g $AGENT_GID -d /home/agent -m -l agent node

USER ${AGENT_UID}:${AGENT_GID}

WORKDIR /home/agent

# Add the agent's ~/.local/bin to PATH so the Claude Code CLI installed below
# resolves for the merge-phase agent.
ENV PATH="/home/agent/.local/bin:${PATH}"

# Pre-provision uv's managed CPython 3.13 into the image (inside pyproject's
# requires-python). The per-sandbox `uv sync` hook in agents.mts otherwise
# re-downloads and unpacks the interpreter on every container start.
RUN uv python install 3.13

# Warm uv's cache with the project's locked dependencies. The workspace is
# bind-mounted at runtime, so a .venv built here would be shadowed — but the uv
# cache survives, so the per-sandbox `uv sync` hook installs from cache instead
# of downloading every wheel (notably litellm's large transitive tree). Rebuild
# the image (npm run sandcastle:build-image) after changing uv.lock.
COPY --chown=agent:agent pyproject.toml uv.lock /home/agent/prime/
RUN cd /home/agent/prime \
  && uv sync --frozen --python 3.13 \
  && rm -rf /home/agent/prime

# Codex and Claude Code install their latest release, which Docker's layer
# cache then freezes. They come last so that a new TOOLS_REFRESH value
# (npm run sandcastle:refresh-tools) rebuilds only these layers; Python and
# the warmed uv cache above stay cached.
ARG TOOLS_REFRESH=0

# Install Codex CLI as root, then switch back to the agent user.
USER root
RUN npm install -g @openai/codex
USER ${AGENT_UID}:${AGENT_GID}

# Install Claude Code CLI as the agent user so it lands in the agent's
# ~/.local/bin (installing as root would put it in /root, invisible to agent).
RUN curl -fsSL https://claude.ai/install.sh | bash

# In worktree sandbox mode, Sandcastle bind-mounts the git worktree at /home/agent/workspace
# and overrides the working directory to /home/agent/workspace at container start.
# Structure your Dockerfile so that /home/agent/workspace can serve as the project root.
ENTRYPOINT ["sleep", "infinity"]
