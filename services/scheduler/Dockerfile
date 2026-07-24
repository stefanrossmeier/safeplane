FROM python:3.11-slim

ARG SAFEPLANE_UID=10001
ARG SAFEPLANE_GID=10001

WORKDIR /app

COPY services/scheduler/pyproject.toml /app/pyproject.toml
COPY services/scheduler/src /app/src
COPY services/harness/src /app/harness-src

ENV PYTHONPATH="/app/src:/app/harness-src" \
    HOME=/tmp/safeplane-home

RUN pip install --no-cache-dir . \
    && addgroup --system --gid "${SAFEPLANE_GID}" safeplane \
    && adduser --system --uid "${SAFEPLANE_UID}" --ingroup safeplane --home /nonexistent --no-create-home safeplane

USER ${SAFEPLANE_UID}:${SAFEPLANE_GID}

CMD ["safeplane-scheduler"]
