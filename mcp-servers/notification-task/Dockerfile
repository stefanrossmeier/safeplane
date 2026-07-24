FROM python:3.11-slim

ARG SAFEPLANE_UID=10001
ARG SAFEPLANE_GID=10001

WORKDIR /app

COPY mcp-servers/notification-task/pyproject.toml /app/pyproject.toml
COPY mcp-servers/notification-task/src /app/src
COPY services/harness/src /app/harness-src

ENV PYTHONPATH="/app/src:/app/harness-src" \
    HOME=/tmp/safeplane-home

RUN pip install --no-cache-dir . \
    && addgroup --system --gid "${SAFEPLANE_GID}" safeplane \
    && adduser --system --uid "${SAFEPLANE_UID}" --ingroup safeplane --home /nonexistent --no-create-home safeplane

USER ${SAFEPLANE_UID}:${SAFEPLANE_GID}

CMD ["notification-task-mcp"]
