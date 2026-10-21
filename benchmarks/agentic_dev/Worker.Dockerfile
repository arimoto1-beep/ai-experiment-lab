FROM python:3.12-slim

RUN pip install --no-cache-dir pytest==8.4.2 \
    && useradd --uid 1000 --create-home --shell /usr/sbin/nologin lab \
    && mkdir /ipc && chown lab:lab /ipc
COPY mcp_worker.py /opt/ai-lab/mcp_worker.py
USER lab
ENV HOME=/home/lab
WORKDIR /work
CMD ["python", "/opt/ai-lab/mcp_worker.py"]
