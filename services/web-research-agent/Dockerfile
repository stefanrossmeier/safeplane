FROM python:3.12-slim

ARG SAFEPLANE_UID=10001
ARG SAFEPLANE_GID=10001

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /app/pyproject.toml
COPY src /app/src
RUN pip install --no-cache-dir . \
    && addgroup --system --gid "${SAFEPLANE_GID}" safeplane \
    && adduser --system --uid "${SAFEPLANE_UID}" --ingroup safeplane --home /nonexistent --no-create-home safeplane

ENV PYTHONPATH=/app/src \
    HOME=/tmp/safeplane-home

USER ${SAFEPLANE_UID}:${SAFEPLANE_GID}

EXPOSE 8080
CMD ["uvicorn", "web_research_agent.main:app", "--host", "0.0.0.0", "--port", "8080"]
