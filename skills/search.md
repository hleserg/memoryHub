# memoryHub Search Skill — Advanced Search Operations
# See ARCHITECTURE.md §4.6 Skills System, §4.5 MCP Tools memory_search

## Search Strategies

memoryHub uses hybrid search:
1. **Semantic search** — embedding similarity (finds related concepts)
2. **Full-text search** — FTS5 BM25 (finds exact terms)
3. **Knowledge Graph enrichment** — adds relational context

Results are merged and ranked by combined score.

---

## Basic Search

```bash
curl "${MEMORYHUB_BASE_URL}/v1/memory/search?q=<query>" \
  -H "Authorization: Bearer ${MEMORYHUB_API_KEY}"
```

## Search with all filters

```bash
curl "${MEMORYHUB_BASE_URL}/v1/memory/search?\
q=coffee+morning+preference\
&limit=10\
&tags=preference&tags=sergey\
&min_confidence=0.7\
&since=2026-01-01T00:00:00Z\
&include_graph=true" \
  -H "Authorization: Bearer ${MEMORYHUB_API_KEY}"
```

## Search via MCP

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "memory_search",
    "arguments": {
      "q": "Sergey preferences coffee morning",
      "limit": 5,
      "min_confidence": 0.7,
      "include_graph": true
    }
  }
}
```

## Response format

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
      "status": "shared",
      "graph_context": {
        "entities": ["Sergey", "dark roast coffee"],
        "relations": [{"from": "Sergey", "type": "HAS_PROPERTY", "to": "dark roast coffee"}]
      }
    }
  ],
  "total": 1,
  "limit": 5,
  "offset": 0
}
```

## Tips

- Use natural language queries — semantic search handles synonyms
- Add `include_graph=true` when you need context about entities, not just facts
- Filter by `tags` to narrow scope (e.g., `tags=decision` for past decisions)
- Use `min_confidence=0.8` to get only high-confidence memories
- Use `since` for recent context (last session, last week)

## TODO

- [ ] Faceted search (group by tag, agent, date)
- [ ] Fuzzy matching for typos
- [ ] Cross-lingual search (ru/en)
- [ ] Export search results as Cypher
