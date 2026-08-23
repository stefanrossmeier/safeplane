FROM python:3.11-slim AS builder

WORKDIR /build
COPY connectors/common /build/common
COPY connectors/cli /build/cli
RUN python -m pip wheel --no-cache-dir --no-deps --wheel-dir /wheels /build/common /build/cli

FROM python:3.11-slim

ARG SAFEPLANE_UID=10001
ARG SAFEPLANE_GID=10001

RUN addgroup --system --gid "${SAFEPLANE_GID}" safeplane \
    && adduser --system --uid "${SAFEPLANE_UID}" --ingroup safeplane --home /nonexistent --no-create-home safeplane
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir /wheels/*.whl \
    && rm -rf /wheels

ENV HOME=/tmp/safeplane-home \
    PYTHONDONTWRITEBYTECODE=1

USER ${SAFEPLANE_UID}:${SAFEPLANE_GID}

ENTRYPOINT ["safeplane-cli"]
