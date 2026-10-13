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
# SQLAlchemy + Celery) managed with pip and requirements files; the Node base
# image only carries the Sandcastle/Codex harness. uv provisions a managed
# CPython 3.13 (bookworm only ships 3.11; the host runs 3.13) and installs the
# project's dependencies fast from its cache. Installed into /usr/local/bin
# for all users.
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

# The project's virtualenv lives OUTSIDE the workspace: the workspace is a
# bind-mounted git worktree, so a .venv built into the image there would be
# shadowed at runtime. With VIRTUAL_ENV set and the venv on PATH, `pytest`
# and `uv pip install` address this venv from any directory.
ENV VIRTUAL_ENV=/home/agent/venv
ENV PATH="/home/agent/venv/bin:/home/agent/.local/bin:${PATH}"

# Pre-provision uv's managed CPython 3.13 and create the venv from it.
RUN uv python install 3.13 && uv venv --python 3.13 "$VIRTUAL_ENV"

# Install the project's dev/test dependencies into the venv. The per-sandbox
# hook in agents.mts re-runs the same install, which is a quick no-op when
# nothing changed and otherwise only pulls the delta. Rebuild the image
# (npm run sandcastle:build-image) after larger changes to requirements*.txt
# so the first sandbox of a run does not download them cold.
COPY --chown=agent:agent pyproject.toml requirements.txt requirements-dev.txt /home/agent/prime/
RUN cd /home/agent/prime \
  && uv pip install -r requirements-dev.txt \
  && rm -rf /home/agent/prime

# Codex and Claude Code install their latest release, which Docker's layer
# cache then freezes. They come last so that a new TOOLS_REFRESH value
# (npm run sandcastle:refresh-tools) rebuilds only these layers; Python and
# the installed dependencies above stay cached.
ARG TOOLS_REFRESH=0

# Install Codex CLI as root, then switch back to the agent user.
USER root
RUN npm install -g @openai/codex
USER ${AGENT_UID}:${AGENT_GID}

# Install Claude Code CLI as the agent user so it lands in the agent's
# ~/.local/bin (installing as root would put it in /root, invisible to agent).
RUN curl -fsSL https://claude.ai/install.sh | bash

# Login shells re-read /etc/profile, which resets PATH and drops the venv set
# via ENV above. The agent CLIs may open such shells; the profile files put
# the venv back in front so `pytest` resolves there too.
RUN printf '\nexport VIRTUAL_ENV=/home/agent/venv\nexport PATH="/home/agent/venv/bin:$PATH"\n' | tee -a /home/agent/.profile >> /home/agent/.bashrc

# In worktree sandbox mode, Sandcastle bind-mounts the git worktree at /home/agent/workspace
# and overrides the working directory to /home/agent/workspace at container start.
# Structure your Dockerfile so that /home/agent/workspace can serve as the project root.
ENTRYPOINT ["sleep", "infinity"]
