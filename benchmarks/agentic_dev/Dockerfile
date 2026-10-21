FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --uid 1000 --create-home --shell /bin/bash lab \
    && mkdir -p /home/lab/.claude /home/lab/.cache \
    && chown -R lab:lab /home/lab
USER lab
ENV HOME=/home/lab
ENV PATH=/home/lab/.local/bin:$PATH
RUN curl -fsSL https://claude.ai/install.sh | bash

COPY --chown=lab:lab mcp_bridge.py /opt/ai-lab/mcp_bridge.py

WORKDIR /work
