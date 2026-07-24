FROM python:3.12-slim

ARG SAFEPLANE_UID=10001
ARG SAFEPLANE_GID=10001

WORKDIR /app
COPY tests/fixtures/github-mock/server.py /app/server.py

RUN addgroup --system --gid "${SAFEPLANE_GID}" safeplane \
    && adduser --system --uid "${SAFEPLANE_UID}" --ingroup safeplane --home /nonexistent --no-create-home safeplane

ENV HOME=/tmp/safeplane-home
USER ${SAFEPLANE_UID}:${SAFEPLANE_GID}

EXPOSE 8080
CMD ["python", "-u", "/app/server.py"]
