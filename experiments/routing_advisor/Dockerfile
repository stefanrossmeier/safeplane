FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml /app/pyproject.toml
COPY src /app/src
RUN pip install --no-cache-dir .

COPY data /app/data
COPY docs /app/docs

ENTRYPOINT ["safeplane-routing-advisor"]
