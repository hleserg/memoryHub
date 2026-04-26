# memoryHub API Reference

**Base URL:** `http://localhost:3000` (dev) | `http://192.168.1.51:3000` (prod)  
**Version:** v1  
**Auth:** Bearer token (see §Authentication)  
**See also:** `ARCHITECTURE.md §13` for interface specs, `skills/memoryhub.md` for quick reference

---

## Authentication

All authenticated endpoints require:
```
Authorization: Bearer mhub_<env>_<agent_prefix>_<token>
```

Store your key in Bitwarden — never hardcode or expose in logs.

**Key format:** `mhub_prod_alfred_4xKj9mN2pQr7sT8vWx3yZ6aB`  
**Key rotation:** Recommended every 90 days  
See `ARCHITECTURE.md §4.1 API Key Vault`

---

## Health & Status

### GET /v1/health
Simple liveness check — no auth required.

**Response:** `200 OK`
```json
{
  "status": "healthy",
  "version": "1.0.0"
}
```

Used by Docker healthcheck and load balancers.

---

### GET /v1/status
Full system status with component health.

**Response:** `200 OK`
```json
{
  "overall_health": "healthy",
  "version": "1.0.0",
  "environment": "production",
  "uptime_seconds": 3600,
  "timestamp": "2026-04-26T13:00:00Z",
  "components": {
    "api_hub":        { "status": "healthy", "details": {"req_per_sec": 12.3, "p95_ms": 84} },
    "knowledge_graph":{ "status": "healthy", "details": {"size": 45000, "queries_per_sec": 8.1} },
    "trust_pipeline": { "status": "healthy", "details": {"queue_depth": 3, "backlog": 0} },
    "mcp_server":     { "status": "healthy", "details": {"agents": 4, "sessions": 7} },
    "memory_store":   { "status": "healthy", "details": {"disk_gb": 2.1, "writes_per_min": 18} },
    "dr_system":      { "status": "healthy", "details": {"last_backup_hours_ago": 2} }
  }
}
```

Component status values: `healthy` | `degraded` | `unhealthy` | `unknown`

---

## Memory Operations

### POST /v1/memory
Write a new memory. Goes through Trust Pipeline before becoming shared.

**Auth:** required (write permission)  
**Rate limit:** depends on agent trust tier  

**Request:**
```json
{
  "content": "Sergey prefers dark roast coffee every morning",
  "tags": ["preference", "morning", "sergey"],
  "source": "alfred",
  "confidence": 0.85
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| content | string | ✅ | Memory content (max 50,000 chars) |
| tags | string[] | — | Up to 20 tags |
| source | string | ✅ | Agent identifier |
| confidence | float | — | Agent's confidence 0.0-1.0 (default 0.5) |

**Response:** `202 Accepted`
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending_review",
  "message": "Memory queued for verification. Check status with GET /v1/memory/{id}"
}
```

---

### GET /v1/memory/search
Semantic + full-text search. Returns only `shared` (verified) memories.

**Auth:** required (read permission)

**Query parameters:**

| Param | Type | Description |
|-------|------|-------------|
| q | string | Search query (required, max 1000 chars) |
| limit | int | Results 1-50 (default 10) |
| tags | string[] | Filter by tags (repeat for AND: `&tags=a&tags=b`) |
| min_confidence | float | Minimum confidence 0.0-1.0 |
| since | ISO8601 | Only memories after this timestamp |
| include_graph | bool | Enrich with Knowledge Graph context |

**Example:**
```bash
curl "http://localhost:3000/v1/memory/search?q=coffee+morning&limit=5&min_confidence=0.7" \
  -H "Authorization: Bearer mhub_dev_alfred_..."
```

**Response:** `200 OK`
```json
{
  "items": [
    {
      "id": "550e8400-...",
      "content": "Sergey prefers dark roast coffee every morning",
      "tags": ["preference", "morning", "sergey"],
      "confidence_actual": 0.928,
      "source_agent": "alfred",
      "created_at": "2026-04-20T09:00:00Z",
      "status": "shared"
    }
  ],
  "total": 1,
  "limit": 5,
  "offset": 0
}
```

---

### GET /v1/memory/recent
Return most recently created shared memories.

**Query params:** `limit` (1-100, default 20), `since` (ISO8601)

---

### GET /v1/memory/:id
Get a single memory record by UUID.

**Response:** `200 OK` (memory JSON) or `404 Not Found`

---

### DELETE /v1/memory/:id
Soft-archive a memory. Record is NOT deleted — status becomes `archived`.  
See `ARCHITECTURE.md §2 P6 Immutability of History`.

---

## Trust Pipeline

### GET /v1/review/queue
View records waiting for human review.

**Auth:** verify permission required

**Response:**
```json
{
  "items": [
    {
      "id": "...",
      "memory_id": "...",
      "reason": "Score 0.72 — below auto-approve threshold",
      "verification_details": {
        "fact_checker": 0.70,
        "anomaly_detector": 0.80,
        "source_credibility": 0.65,
        "conflict_scanner": 0.75,
        "final_score": 0.72
      },
      "created_at": "2026-04-26T12:00:00Z",
      "escalates_at": "2026-04-28T12:00:00Z"
    }
  ],
  "total": 1,
  "pending_escalation": 0
}
```

---

### POST /v1/review/:id/approve
Approve a review item — promotes memory to `shared`.

**Request:**
```json
{
  "reviewer_id": "alfred",
  "comment": "Verified against original source"
}
```

---

### POST /v1/review/:id/reject
Reject a review item — moves memory to `quarantine`.

**Request:**
```json
{
  "reviewer_id": "alfred",
  "reason": "Contradicts established fact #xyz"
}
```

---

### GET /v1/quarantine
View quarantined records. Requires `admin_read` permission.

**Query params:** `severity` (low|medium|high|critical), `resolved` (bool), `reason`

---

### POST /v1/quarantine/:id/appeal
Appeal a quarantine decision — moves back to `needs_human_review`.

**Request:**
```json
{
  "appeal_by": "alfred",
  "appeal_reason": "Additional context now available"
}
```

---

## Knowledge Graph

### GET /v1/graph/entity/:name
Get an entity with its relations.

**Example:** `GET /v1/graph/entity/Sergey`

**Response:**
```json
{
  "id": "...",
  "name": "Sergey",
  "type": "person",
  "confidence": 0.95,
  "relations": [
    { "type": "WORKS_ON", "to": "memoryHub", "strength": 0.9 },
    { "type": "HAS_PROPERTY", "to": "dark roast coffee preference", "strength": 0.928 }
  ]
}
```

---

### POST /v1/graph/relations
Create a typed relation between two entities.

**Request:**
```json
{
  "from": "Sergey",
  "to": "memoryHub",
  "type": "WORKS_ON",
  "confidence": 0.9,
  "evidence": ["550e8400-..."]
}
```

**Valid types:** `IS_A` | `HAS_PROPERTY` | `RELATED_TO` | `LOCATED_IN` | `HAPPENED_AT` | `CAUSED_BY` | `PRECEDED_BY` | `CONTRADICTS` | `SUPPORTS` | `PART_OF` | `KNOWS` | `WORKS_ON`

---

### GET /v1/graph/query
Execute read-only Cypher query.

**Query params:** `cypher` (required), `limit` (default 50, max 500)

**Example:**
```bash
curl "http://localhost:3000/v1/graph/query?\
cypher=MATCH+%28e%3AEntity%29+RETURN+e+LIMIT+10" \
  -H "Authorization: Bearer mhub_dev_alfred_..."
```

Write operations (CREATE, MERGE, SET, DELETE) are blocked for agents.

---

### GET /v1/graph/conflicts
List unresolved conflicts.

**Query params:** `resolved` (bool, default false)

---

### GET /v1/graph/snapshot
Point-in-time graph snapshot.

**Query params:** `at` (ISO8601, required)

---

## Error Responses

All errors return JSON:
```json
{
  "code": "RATE_LIMITED",
  "message": "Rate limit exceeded. Retry after 42 seconds.",
  "request_id": "550e8400-...",
  "details": { "retry_after_seconds": 42 }
}
```

| HTTP | Code | Meaning |
|------|------|---------|
| 400 | `BAD_REQUEST` | Invalid request params |
| 401 | `UNAUTHORIZED` | Missing or invalid Bearer token |
| 403 | `FORBIDDEN` | Permission denied |
| 404 | `NOT_FOUND` | Resource not found |
| 409 | `CONFLICT` | Data conflict |
| 422 | `UNPROCESSABLE` | Semantic validation error |
| 429 | `RATE_LIMITED` | Rate limit exceeded; check `Retry-After` header |
| 500 | `INTERNAL_ERROR` | Unexpected server error |
| 503 | `SERVICE_UNAVAILABLE` | Component in degraded mode |
| 503 | `MH-001` | Trust Pipeline queue full |
| 503 | `MH-003` | Knowledge Graph unreachable |
| 504 | `GATEWAY_TIMEOUT` | Component timeout |

---

## Rate Limit Headers

When `api_hub.rate_limit.headers.expose: true`:

```
X-RateLimit-Limit: 500
X-RateLimit-Remaining: 499
X-RateLimit-Reset: 1714140000
Retry-After: 42   (on 429 only)
```

---

## MCP Protocol

Connect via MCP at `http://localhost:3100`

Available tools: `memory_search`, `memory_write`, `memory_recall`, `graph_query`, `graph_relate`, `memory_status`

See `skills/memoryhub.md` for MCP connection config.

---

## See Also

- `ARCHITECTURE.md §13` — Interface specifications
- `skills/memoryhub.md` — Quick reference for agents
- `skills/trust.md` — Trust Pipeline management
- `docs/DEPLOYMENT.md` — Production deployment guide
- `docs/TROUBLESHOOTING.md` — Common issues and fixes
