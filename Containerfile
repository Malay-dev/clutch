# Clutch — Containerfile (Podman native)
# Multi-stage build for a lean production image

# ─── Build stage ────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build deps
RUN pip install --no-cache-dir hatchling

# Copy project metadata first (cache-friendly)
COPY pyproject.toml README.md ./
COPY src/ src/

# Build the wheel
RUN pip wheel --no-deps --wheel-dir /wheels .

# ─── Runtime stage ──────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL maintainer="Malay Kumar"
LABEL description="Clutch — The AI that won't let you miss what matters"
LABEL org.opencontainers.image.source="https://github.com/malay-kumar/clutch"

WORKDIR /app

# Install the wheel + runtime deps
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels

# Copy config (user can mount their own)
COPY clutch.yaml /app/clutch.yaml

# Data directory for SQLite
RUN mkdir -p /app/data
VOLUME ["/app/data"]

# Clutch token storage
RUN mkdir -p /root/.clutch
VOLUME ["/root/.clutch"]

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["clutch"]
CMD ["run", "--once"]
