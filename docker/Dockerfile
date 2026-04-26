# docker/Dockerfile — memoryHub Go API container
# Multi-stage build: development (with air hot-reload) and production (minimal image)
# See ARCHITECTURE.md §9 Deployment Diagram
#
# Stages:
#   base        — Shared Go tooling
#   development — Hot-reload via air (for docker compose --profile dev)
#   builder     — Compile production binary
#   production  — Minimal runtime image

# ─────────────────────────────────────────────────────────────────────────
# BASE — Go toolchain
# ─────────────────────────────────────────────────────────────────────────
FROM golang:1.22-alpine AS base

RUN apk add --no-cache \
    gcc \
    musl-dev \
    sqlite-dev \
    git \
    ca-certificates \
    wget

WORKDIR /workspace

# Copy module files first for dependency caching
COPY go.mod go.sum* ./
RUN go mod download

# ─────────────────────────────────────────────────────────────────────────
# DEVELOPMENT — Hot reload with air
# ─────────────────────────────────────────────────────────────────────────
FROM base AS development

# Install air for hot-reload (https://github.com/air-verse/air)
RUN go install github.com/air-verse/air@latest

# Note: source is mounted via docker-compose volume — not COPY'd here
# Config is mounted at /etc/memoryhub/memoryhub.config.yaml

EXPOSE 3000 3100 3200

CMD ["air", "-c", ".air.toml"]

# ─────────────────────────────────────────────────────────────────────────
# BUILDER — Compile production binary
# ─────────────────────────────────────────────────────────────────────────
FROM base AS builder

COPY . .

# CGO required for go-sqlite3
ENV CGO_ENABLED=1

RUN go build \
    -ldflags="-s -w -extldflags '-static'" \
    -o /usr/local/bin/memoryhub \
    ./api/main.go

# ─────────────────────────────────────────────────────────────────────────
# PRODUCTION — Minimal runtime image
# See ARCHITECTURE.md §9: /data/memoryhub layout
# ─────────────────────────────────────────────────────────────────────────
FROM alpine:3.19 AS production

RUN apk add --no-cache \
    ca-certificates \
    wget \
    sqlite

# Create non-root user
RUN addgroup -S memoryhub && adduser -S -G memoryhub memoryhub

# Data directories (ARCHITECTURE.md §9 Deployment Diagram)
RUN mkdir -p \
    /data/memoryhub/kuzu \
    /data/memoryhub/backups \
    /data/memoryhub/logs \
    /etc/memoryhub \
    && chown -R memoryhub:memoryhub /data/memoryhub /etc/memoryhub

COPY --from=builder /usr/local/bin/memoryhub /usr/local/bin/memoryhub
COPY scripts/setup.sh /usr/local/bin/memoryhub-setup.sh
RUN chmod +x /usr/local/bin/memoryhub-setup.sh

USER memoryhub
WORKDIR /data/memoryhub

EXPOSE 3000 3100 3200

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://localhost:3000/v1/health || exit 1

# Config path can be overridden via MEMORYHUB_CONFIG env var
ENV MEMORYHUB_CONFIG=/etc/memoryhub/memoryhub.config.yaml
ENV MEMORYHUB_DATA_DIR=/data/memoryhub

ENTRYPOINT ["/usr/local/bin/memoryhub"]
CMD ["--config", "/etc/memoryhub/memoryhub.config.yaml"]
