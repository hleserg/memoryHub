# memoryHub Skill — OpenClaw Integration

> OpenClaw skill for memory operations via memoryHub API.  
> See ARCHITECTURE.md §4.6 Skills System for full context.

## Configuration

Set these environment variables (or use `docker/.env`):

```bash
export MEMORYHUB_API_URL="http://localhost:3000/v1"
export MEMORYHUB_API_KEY="mhub_prod_alfred_..."
```

Or in OpenClaw config:
```yaml
skills:
  memoryhub:
    api_url: "http://localhost:3000/v1"
    api_key: "${MEMORYHUB_API_KEY}"
```

---

## Core Operations

### Search Memory

Find relevant memories by semantic query.

```bash
curl -s "${MEMORYHUB_API_URL}/memory/search?q={QUERY}&limit={LIMIT}&min_confidence={MIN_CONFIDENCE}" \
  -H "Authorization: Bearer ${MEMORYHUB_API_KEY}" \
  | jq '.items[] | {content, confidence_actual, tags, created_at}'
```

**Parameters:**
- `q` — search query (required)
- `limit` — max results, 1–50 (default: 10)
- `min_confidence` — 0.0–1.0 (default: 0.0)
- `tags` — comma-separated tag filter
- `since` — ISO8601 timestamp (only records after)
- `include_graph=true` — enrich with Knowledge Graph context

**Example:**
```bash
curl -s "${MEMORYHUB_API_URL}/memory/search?q=Sergey+preferences&limit=5&min_confidence=0.7" \
  -H "Authorization: Bearer ${MEMORYHUB_API_KEY}"
```

---

### Write Memory

Submit a new memory (enters Trust Pipeline for verification).

```bash
curl -s -X POST "${MEMORYHUB_API_URL}/memory" \
  -H "Authorization: Bearer ${MEMORYHUB_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "{CONTENT}",
    "tags": ["{TAG1}", "{TAG2}"],
    "source": "{AGENT_ID}",
    "confidence": {CONFIDENCE}
  }'
```

**Response:** `{"id": "mem_...", "status": "pending_review"}`

**Note:** Memory is not immediately available — it goes through verification  
(~30 seconds for auto-approved, longer if human review needed).  
See ARCHITECTURE.md §4.3 Trust Pipeline Flow.

---

### Recall Recent Memories

Get the most recently verified memories.

```bash
curl -s "${MEMORYHUB_API_URL}/memory/recent?limit=20" \
  -H "Authorization: Bearer ${MEMORYHUB_API_KEY}" \
  | jq '.items[] | {content, source_agent, created_at}'
```

---

### Get Specific Memory

```bash
curl -s "${MEMORYHUB_API_URL}/memory/{MEMORY_ID}" \
  -H "Authorization: Bearer ${MEMORYHUB_API_KEY}"
```

---

## Knowledge Graph Operations

### Find Entity

Get an entity and its relations from the Knowledge Graph.

```bash
curl -s "${MEMORYHUB_API_URL}/graph/entity/{ENTITY_NAME}" \
  -H "Authorization: Bearer ${MEMORYHUB_API_KEY}" \
  | jq '{entity: .entity, relations: .relations}'
```

**Example:**
```bash
curl -s "${MEMORYHUB_API_URL}/graph/entity/Sergey" \
  -H "Authorization: Bearer ${MEMORYHUB_API_KEY}"
```

---

### Create Relation

Link two entities in the Knowledge Graph.

```bash
curl -s -X POST "${MEMORYHUB_API_URL}/graph/relations" \
  -H "Authorization: Bearer ${MEMORYHUB_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "from_entity": "{FROM}",
    "to_entity": "{TO}",
    "type": "{RELATION_TYPE}",
    "confidence": {CONFIDENCE},
    "evidence": ["{MEMORY_ID}"]
  }'
```

**Valid relation types** (ARCHITECTURE.md §4.2):
`IS_A | HAS_PROPERTY | RELATED_TO | LOCATED_IN | HAPPENED_AT | CAUSED_BY | PRECEDED_BY | CONTRADICTS | SUPPORTS | PART_OF | KNOWS | WORKS_ON`

---

### Graph Query (Cypher, read-only)

```bash
curl -s -X GET "${MEMORYHUB_API_URL}/graph/query" \
  -H "Authorization: Bearer ${MEMORYHUB_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "cypher": "MATCH (a:Entity {name: \"Sergey\"})-[r]-(e) RETURN a, r, e LIMIT 20",
    "limit": 20
  }'
```

---

## Trust Pipeline Operations

### View Review Queue

```bash
curl -s "${MEMORYHUB_API_URL}/review/queue" \
  -H "Authorization: Bearer ${MEMORYHUB_API_KEY}" \
  | jq '{total: .total, oldest_hours: .oldest_item_hours}'
```

### Approve a Record

```bash
curl -s -X POST "${MEMORYHUB_API_URL}/review/{REVIEW_ID}/approve" \
  -H "Authorization: Bearer ${MEMORYHUB_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"reviewer_id": "{YOUR_AGENT_ID}", "comment": "{COMMENT}"}'
```

### Reject a Record

```bash
curl -s -X POST "${MEMORYHUB_API_URL}/review/{REVIEW_ID}/reject" \
  -H "Authorization: Bearer ${MEMORYHUB_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"reviewer_id": "{YOUR_AGENT_ID}", "reason": "{REASON}"}'
```

### View Quarantine (admin)

```bash
curl -s "${MEMORYHUB_API_URL}/quarantine" \
  -H "Authorization: Bearer ${MEMORYHUB_API_KEY}" \
  | jq '{total: .total}'
```

---

## Health & Status

```bash
# Quick health check (no auth)
curl -s http://localhost:3000/v1/health

# Full status (admin)
curl -s "${MEMORYHUB_API_URL}/status" \
  -H "Authorization: Bearer ${MEMORYHUB_API_KEY}" \
  | jq '.overall_health'
```

---

## Error Reference

| HTTP Code | Meaning | Action |
|-----------|---------|--------|
| 400 | Bad request | Check request body |
| 401 | Invalid API key | Check `MEMORYHUB_API_KEY` |
| 403 | Insufficient permissions | Request elevated key |
| 429 | Rate limit exceeded | Check `Retry-After` header and wait |
| 503 | Service degraded | Check `/v1/health` |

**Custom error codes** (ARCHITECTURE.md §12):
- `MH-001` — Trust Pipeline overflow
- `MH-002` — Integrity checksum failure
- `MH-003` — Knowledge Graph unreachable
- `MH-004` — Quarantine capacity exceeded
- `MH-005` — Backup verification failed

---

## MCP Integration

memoryHub also exposes a Model Context Protocol server at port 3100.  
See ARCHITECTURE.md §4.5 MCP Server for JSON-RPC interface.

Configure in your MCP client:
```json
{
  "mcpServers": {
    "memoryhub": {
      "url": "http://localhost:3100",
      "apiKey": "${MEMORYHUB_API_KEY}"
    }
  }
}
```

Available MCP tools: `memory_search`, `memory_write`, `memory_recall`,  
`graph_query`, `graph_relate`, `memory_status`.
