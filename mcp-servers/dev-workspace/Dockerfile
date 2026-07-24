FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends git patch \
    && rm -rf /var/lib/apt/lists/*

COPY mcp-servers/dev-workspace/pyproject.toml /app/pyproject.toml
COPY mcp-servers/dev-workspace/src /app/src
COPY services/harness/src /app/harness-src
COPY workflows/developer/workflow.yaml /app/workflows/developer/workflow.yaml

ENV PYTHONPATH="/app/src:/app/harness-src"

RUN pip install --no-cache-dir -e /app \
    && addgroup --system --gid 10001 safeplane \
    && adduser --system --uid 10001 --ingroup safeplane --home /nonexistent --no-create-home safeplane \
    && mkdir -p /run/safeplane-dev-check \
    && chown 10001:10001 /run/safeplane-dev-check

USER 10001:10001

CMD ["uvicorn", "dev_workspace_mcp.main:app", "--host", "0.0.0.0", "--port", "8080"]
