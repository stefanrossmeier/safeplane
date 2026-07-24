FROM python:3.11-slim

ARG SAFEPLANE_UID=10001
ARG SAFEPLANE_GID=10001

WORKDIR /app

COPY pyproject.toml /app/pyproject.toml
COPY src /app/src

RUN pip install --no-cache-dir . \
    && addgroup --system --gid "${SAFEPLANE_GID}" safeplane \
    && adduser --system --uid "${SAFEPLANE_UID}" --ingroup safeplane --home /nonexistent --no-create-home safeplane

ENV PYTHONPATH=/app/src \
    HOME=/tmp/safeplane-home

USER ${SAFEPLANE_UID}:${SAFEPLANE_GID}

EXPOSE 8080

CMD ["uvicorn", "model_gateway.main:app", "--host", "0.0.0.0", "--port", "8080"]
