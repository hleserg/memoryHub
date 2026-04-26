# Makefile — memoryHub build automation
# See ARCHITECTURE.md §11 Roadmap for build context
# Usage: make <target>
#   make dev          — Run in development mode with live reload
#   make build        — Build production binary
#   make test         — Run all tests
#   make lint         — Run linter
#   make docker-up    — Start all services via Docker Compose
#   make docker-down  — Stop all services
#   make migrate      — Run DB migrations

BINARY     := memoryhub
BUILD_DIR  := ./build
CONFIG     := config/memoryhub.config.yaml
MAIN       := ./api/main.go

# Go tooling
GOFLAGS    := -v
LDFLAGS    := -ldflags="-s -w -X main.version=$(shell git describe --tags --always --dirty 2>/dev/null || echo dev)"

# Docker
COMPOSE    := docker compose
COMPOSE_FILE := docker-compose.yml

.PHONY: all dev build test lint clean docker-up docker-down migrate fmt vet tidy setup help

## Default target
all: lint test build

## help — Show this help message
help:
	@echo "memoryHub — available targets:"
	@grep -E '^## ' $(MAKEFILE_LIST) | sed 's/## /  /'

## dev — Run API server in development mode (hot reload via air if available)
dev:
	@echo "→ Starting memoryHub in development mode..."
	@if command -v air > /dev/null 2>&1; then \
		air -c .air.toml; \
	else \
		go run $(MAIN) --config $(CONFIG); \
	fi

## run — Run without hot reload
run:
	go run $(MAIN) --config $(CONFIG)

## build — Build production binary
build:
	@echo "→ Building $(BINARY)..."
	@mkdir -p $(BUILD_DIR)
	go build $(GOFLAGS) $(LDFLAGS) -o $(BUILD_DIR)/$(BINARY) $(MAIN)
	@echo "✓ Binary: $(BUILD_DIR)/$(BINARY)"

## test — Run all tests
test:
	@echo "→ Running tests..."
	go test ./... -race -timeout 60s -coverprofile=coverage.out
	@go tool cover -func=coverage.out | tail -1

## test-short — Run tests without integration (fast)
test-short:
	go test ./... -short -timeout 30s

## lint — Run golangci-lint
lint:
	@echo "→ Running linter..."
	@if command -v golangci-lint > /dev/null 2>&1; then \
		golangci-lint run ./...; \
	else \
		echo "  golangci-lint not installed. Run: go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest"; \
		go vet ./...; \
	fi

## fmt — Format all Go files
fmt:
	@echo "→ Formatting..."
	gofmt -w -s .
	@echo "✓ Done"

## vet — Run go vet
vet:
	go vet ./...

## tidy — Tidy go modules
tidy:
	go mod tidy

## clean — Remove build artifacts
clean:
	@echo "→ Cleaning..."
	rm -rf $(BUILD_DIR) coverage.out
	@echo "✓ Done"

## docker-up — Start all services (API, SQLite, Redis, KuzuDB)
docker-up:
	@echo "→ Starting Docker services..."
	$(COMPOSE) -f $(COMPOSE_FILE) up -d
	@echo "✓ Services started. API: http://localhost:3000 | Dashboard: http://localhost:3200"

## docker-down — Stop all services
docker-down:
	@echo "→ Stopping Docker services..."
	$(COMPOSE) -f $(COMPOSE_FILE) down
	@echo "✓ Services stopped"

## docker-logs — Tail container logs
docker-logs:
	$(COMPOSE) -f $(COMPOSE_FILE) logs -f

## docker-build — Rebuild Docker image
docker-build:
	$(COMPOSE) -f $(COMPOSE_FILE) build --no-cache

## migrate — Run all DB migrations in order
migrate:
	@echo "→ Running migrations..."
	@for f in db/migrations/*.sql; do \
		echo "  Applying $$f..."; \
		sqlite3 $${MEMORYHUB_DATA_DIR:-./data}/memoryhub.sqlite < $$f || exit 1; \
	done
	@echo "✓ Migrations complete"

## setup — Initialize project for first run (create dirs, copy config, run migrations)
setup:
	@echo "→ Running setup..."
	bash scripts/setup.sh
	@echo "✓ Setup complete. Run 'make dev' to start."

## ci — Full CI pipeline (used in GitHub Actions)
ci: tidy fmt vet lint test build
