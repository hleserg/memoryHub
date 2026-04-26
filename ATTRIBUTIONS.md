# Attributions & Dependencies

memoryHub is built on top of excellent open source projects. This document acknowledges all third-party software and gives credit to the original authors.

---

## Core Infrastructure

### PostgreSQL
- **Link:** https://www.postgresql.org/
- **License:** PostgreSQL License (BSD-like)
- **Purpose:** Primary relational database for facts, agents, audit logs
- **Version Used:** 16+

### Qdrant
- **Link:** https://github.com/qdrant/qdrant
- **License:** AGPL-3.0
- **Purpose:** Vector database for semantic search (memory embeddings)
- **Version Used:** v1.7.4+

### KuzuDB
- **Link:** https://github.com/kuzudb/kuzu
- **License:** MIT
- **Purpose:** Embedded knowledge graph (entities, relations, conflicts)
- **Version Used:** Latest embedded

### Redis
- **Link:** https://github.com/redis/redis
- **License:** SSPL (Server Side Public License)
- **Purpose:** In-memory cache for hot data, rate limiting, session storage
- **Version Used:** 7+

---

## Go Framework & Libraries

### Gin Web Framework
- **Link:** https://github.com/gin-gonic/gin
- **License:** MIT
- **Purpose:** HTTP server, routing, middleware
- **Version Used:** v1.9+

### Viper Configuration
- **Link:** https://github.com/spf13/viper
- **License:** MIT
- **Purpose:** Configuration management from YAML/JSON/ENV
- **Version Used:** v1.17+

### Logrus Logger
- **Link:** https://github.com/sirupsen/logrus
- **License:** MIT
- **Purpose:** Structured logging

### UUID Generation
- **Link:** https://github.com/google/uuid
- **License:** BSD 3-Clause
- **Purpose:** UUID v7 generation for memory IDs

### JWT Authentication (optional)
- **Link:** https://github.com/golang-jwt/jwt
- **License:** MIT
- **Purpose:** Token validation if JWT-based auth is used

### Testing & Assertions
- **Link:** https://github.com/stretchr/testify
- **License:** MIT
- **Purpose:** Unit test assertions and mocking

---

## Documentation & Community

### Contributor Covenant
- **Link:** https://www.contributor-covenant.org/
- **License:** Creative Commons Attribution 4.0 International
- **Purpose:** CODE_OF_CONDUCT.md template
- **Version Used:** v2.1

### OpenAPI/Swagger
- **Link:** https://github.com/swaggo/swag
- **License:** MIT
- **Purpose:** API documentation generation from Go code annotations (planned)

---

## Related Projects (We Build On)

### OpenClaw
- **Link:** https://github.com/openclaw/openclaw
- **License:** (Check OpenClaw repo for license)
- **Purpose:** Agent framework and execution environment
- **Our Use:** memoryHub is designed to be the memory backend for OpenClaw agents

### letheClaw
- **Link:** Internal (not published yet)
- **Purpose:** Previous iteration of memory system
- **Our Use:** memoryHub is the production successor to letheClaw with enhanced features

---

## Docker & DevOps

### Docker
- **Link:** https://www.docker.com/
- **License:** Apache 2.0 + Proprietary (community edition)
- **Purpose:** Containerization for deployment
- **Version Used:** 20.10+

### Docker Compose
- **Link:** https://github.com/docker/compose
- **License:** Apache 2.0
- **Purpose:** Multi-container orchestration for local dev
- **Version Used:** v2.0+

---

## How We Use Open Source

### Direct Dependencies (vendored or imported)
These are directly integrated into memoryHub codebase:
- All Go libraries listed above (via `go.mod`)
- Configuration from Viper
- Logging via Logrus
- HTTP server via Gin

### Infrastructure Dependencies (services)
These run as separate services or containers:
- PostgreSQL (relational store)
- Qdrant (vector search)
- Redis (cache)
- KuzuDB (knowledge graph)

### Development & Deployment Dependencies
Used during build, test, and deployment:
- Docker & Docker Compose
- GitHub Actions (CI/CD)
- Go toolchain

### Frameworks We Integrate With
- OpenClaw (our memory is a backend service)
- MCP (Model Context Protocol) — standard specification

---

## License Compatibility

memoryHub is licensed under **MIT**.

**License Review:**
- ✅ MIT dependencies → Compatible (MIT is permissive)
- ✅ Apache 2.0 → Compatible (permissive, can be used in MIT projects)
- ✅ BSD 3-Clause → Compatible (permissive)
- ⚠️ AGPL-3.0 (Qdrant) → **Important:** Qdrant is AGPL. If memoryHub is used as a service, AGPL requirements may apply. Consult legal documentation.
- ⚠️ SSPL (Redis) → **Important:** Redis SSPL applies to Redis server. Our use of Redis as an external service is compatible with MIT.
- ℹ️ Creative Commons (Contributor Covenant) → Used for documentation only, not code

**Recommendation:** If distributing memoryHub with Qdrant embedded, review AGPL compliance requirements.

---

## How to Keep This Updated

When adding new dependencies:
1. `go get <package>`
2. Check the license: `go-license` tool or manually review repo
3. Add entry here with:
   - GitHub link
   - License
   - Purpose
   - Version used

---

## Questions or Concerns?

If you find a missing attribution or license concern:
1. Open an issue with details
2. Email: [contact email when established]
3. See SECURITY.md for responsible disclosure of license issues

---

**Last updated:** 2026-04-26
