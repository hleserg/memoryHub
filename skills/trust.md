# memoryHub Trust Skill — Trust Pipeline Management
# See ARCHITECTURE.md §4.3 Trust Pipeline and §7 Trust Pipeline Flow
#
# Requires: verify permission (for approve/reject)
# Requires: admin_read permission (for quarantine)

## Trust Pipeline Overview

```
Agent writes → pending_review → auto-verification (~30sec) → shared
                                      ↓
                            needs_human_review ←→ quarantine
```

Score thresholds (from config):
- `≥ 0.80` → auto-approved → `shared`
- `0.60-0.79` → `needs_human_review`
- `< 0.60` → `quarantine`

---

## View Review Queue

```bash
curl "${MEMORYHUB_BASE_URL}/v1/review/queue?limit=10" \
  -H "Authorization: Bearer ${MEMORYHUB_API_KEY}"
```

## Approve a Record

```bash
curl -X POST "${MEMORYHUB_BASE_URL}/v1/review/<id>/approve" \
  -H "Authorization: Bearer ${MEMORYHUB_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "reviewer_id": "alfred",
    "comment": "Verified against original source"
  }'
```

## Reject a Record

```bash
curl -X POST "${MEMORYHUB_BASE_URL}/v1/review/<id>/reject" \
  -H "Authorization: Bearer ${MEMORYHUB_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "reviewer_id": "alfred",
    "reason": "Contradicts established fact #xyz"
  }'
```

## View Quarantine (admin only)

```bash
# All quarantined records
curl "${MEMORYHUB_BASE_URL}/v1/quarantine" \
  -H "Authorization: Bearer ${MEMORYHUB_ADMIN_KEY}"

# Filter by severity
curl "${MEMORYHUB_BASE_URL}/v1/quarantine?severity=high" \
  -H "Authorization: Bearer ${MEMORYHUB_ADMIN_KEY}"

# Integrity violations only
curl "${MEMORYHUB_BASE_URL}/v1/quarantine?reason=integrity_violation" \
  -H "Authorization: Bearer ${MEMORYHUB_ADMIN_KEY}"
```

## Appeal Quarantine Decision

```bash
curl -X POST "${MEMORYHUB_BASE_URL}/v1/quarantine/<id>/appeal" \
  -H "Authorization: Bearer ${MEMORYHUB_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "appeal_by": "alfred",
    "appeal_reason": "Additional context: this fact was later confirmed by source X"
  }'
```

## Bulk Operations (admin)

```bash
# Bulk approve all from trusted agent (use carefully)
curl -X POST "${MEMORYHUB_BASE_URL}/v1/review/bulk-approve" \
  -H "Authorization: Bearer ${MEMORYHUB_ADMIN_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "alfred",
    "since": "2026-04-25T00:00:00Z",
    "reason": "Batch review — all from trusted source"
  }'
```

## Understanding Verification Scores

Each record gets scored by 4 checkers:

| Checker | Weight | What it checks |
|---------|--------|----------------|
| Fact Checker | 30% | Agrees with existing shared memories? |
| Anomaly Detector | 20% | Normal write pattern? Normal confidence? |
| Source Credibility | 30% | Agent's historical accuracy |
| Conflict Scanner | 20% | Contradicts Knowledge Graph? |

Formula: `final = fact*0.30 + anomaly*0.20 + credibility*0.30 + conflict*0.20`

## Agent Credibility Score

Each agent has a credibility_score (0.0-1.0):
- Starts at 0.5 (new agents)
- +0.01 per approved record
- -0.05 per rejected record
- Weekly decay factor: 0.95 (old data matters less)

View your score: `curl ${MEMORYHUB_BASE_URL}/v1/metrics/agent/alfred`

## See Also

- `skills/memoryhub.md` — core memory operations
- `ARCHITECTURE.md §4.3` — full Trust Pipeline spec
- `ARCHITECTURE.md §7` — Trust Pipeline flow diagram
