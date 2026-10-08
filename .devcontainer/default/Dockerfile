FROM python:3.14.2-slim-trixie

# Keep the recommended image small while providing the tools expected by VS
# Code and the native libraries initialized by Home Assistant's base platforms.
RUN apt-get update \
    && export DEBIAN_FRONTEND=noninteractive \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        curl \
        ffmpeg \
        git \
        libturbojpeg0 \
        openssh-client \
        sudo \
    && groupadd --gid 1000 vscode \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash vscode \
    && echo "vscode ALL=(root) NOPASSWD:ALL" > /etc/sudoers.d/vscode \
    && chmod 0440 /etc/sudoers.d/vscode \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/home/vscode/.local/bin:${PATH}"

# Some Home Assistant integration requirements do not publish Python 3.14
# wheels yet and are compiled on first use (for example pymicro-vad).
RUN apt-get update \
    && export DEBIAN_FRONTEND=noninteractive \
    && apt-get install --yes --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
