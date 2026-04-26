-- db/schema.sql
-- Full schema reference for memoryHub.
-- This is the canonical human-readable schema.
-- Migrations are applied incrementally via db/migrations/*.sql
-- See ARCHITECTURE.md §4.1 API Hub, §4.3 Trust Pipeline, §4.4 Memory Corruption Protection

-- ─────────────────────────────────────────────────────────────────────────
-- MEMORIES — Core memory records
-- See ARCHITECTURE.md §6 Data Flow, §13 MemoryWriteInput interface
-- Status machine: pending_review → awaiting_verify → shared | needs_human_review | quarantine
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS memories (
    id                   TEXT        PRIMARY KEY,           -- UUID v4
    content              TEXT        NOT NULL,              -- The actual memory content (max 50k chars)
    tags                 TEXT        NOT NULL DEFAULT '[]', -- JSON array of tag strings (max 20)
    source_agent         TEXT        NOT NULL,              -- Agent identifier that wrote this
    confidence_claimed   REAL        NOT NULL DEFAULT 0.5,  -- Confidence claimed by agent (0.0–1.0)
    confidence_actual    REAL,                              -- Confidence after verification

    -- Trust Pipeline fields (ARCHITECTURE.md §4.3)
    status               TEXT        NOT NULL DEFAULT 'pending_review',
    -- Values: pending_review | awaiting_verify | shared | needs_human_review | quarantine | deprecated | archived

    verification_score   REAL,                              -- Final score from Verification Engine
    verification_scores  TEXT,                              -- JSON: VerificationBreakdown (per-checker scores)
    verified_at          TEXT,                              -- ISO8601 timestamp of verification completion
    verified_by          TEXT,                              -- Agent or system that verified
    review_comment       TEXT,                              -- Human reviewer comment
    reviewer_id          TEXT,                              -- Human reviewer ID

    -- Integrity (ARCHITECTURE.md §4.4 Integrity Checksums)
    checksum             TEXT        NOT NULL DEFAULT '',   -- HMAC-SHA256 of content+created_at+source_agent
    integrity_ok         INTEGER     NOT NULL DEFAULT 1,    -- 1 = OK, 0 = tampered

    -- Knowledge Graph linkage (ARCHITECTURE.md §4.2)
    entities_extracted   INTEGER     NOT NULL DEFAULT 0,    -- Whether KG extraction has been done
    graph_node_ids       TEXT        NOT NULL DEFAULT '[]', -- JSON array of KuzuDB entity IDs

    -- Lifecycle timestamps
    created_at           TEXT        NOT NULL,              -- ISO8601
    updated_at           TEXT        NOT NULL,              -- ISO8601
    expires_at           TEXT,                              -- ISO8601, optional TTL

    -- Provenance chain
    supersedes_id        TEXT        REFERENCES memories(id),   -- This record supersedes an older one
    superseded_by_id     TEXT        REFERENCES memories(id),   -- Newer record supersedes this one

    -- Conflict tracking (ARCHITECTURE.md §4.4 Anomaly Detector)
    has_conflict         INTEGER     NOT NULL DEFAULT 0,    -- 1 = has unresolved conflict
    conflict_ids         TEXT        NOT NULL DEFAULT '[]', -- JSON array of conflicting memory IDs

    FOREIGN KEY (supersedes_id) REFERENCES memories(id),
    FOREIGN KEY (superseded_by_id) REFERENCES memories(id)
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_memories_status      ON memories(status);
CREATE INDEX IF NOT EXISTS idx_memories_source      ON memories(source_agent);
CREATE INDEX IF NOT EXISTS idx_memories_created_at  ON memories(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_updated_at  ON memories(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_integrity   ON memories(integrity_ok) WHERE integrity_ok = 0;
CREATE INDEX IF NOT EXISTS idx_memories_conflicts   ON memories(has_conflict) WHERE has_conflict = 1;

-- ─────────────────────────────────────────────────────────────────────────
-- AGENTS — Registered agents and their trust metadata
-- See ARCHITECTURE.md §4.1 API Key Vault, §4.7 Agent Metrics Transport
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agents (
    id                   TEXT        PRIMARY KEY,           -- Unique agent identifier (e.g. "alfred")
    name                 TEXT        NOT NULL,              -- Display name
    description          TEXT,                              -- What this agent does
    trust_level          TEXT        NOT NULL DEFAULT 'registered',
    -- Values: anonymous | registered | verified | trusted

    permissions          TEXT        NOT NULL DEFAULT '["read","write"]', -- JSON array
    -- Values: read | write | verify | admin_read | admin_write | quarantine | restore

    -- Credibility Score (ARCHITECTURE.md §4.7 Agent Feedback Loop)
    credibility_score    REAL        NOT NULL DEFAULT 0.5,  -- 0.0–1.0
    memories_written     INTEGER     NOT NULL DEFAULT 0,
    memories_approved    INTEGER     NOT NULL DEFAULT 0,
    memories_rejected    INTEGER     NOT NULL DEFAULT 0,

    -- API Key metadata (actual keys stored separately or in environment)
    api_key_prefix       TEXT,                              -- First 8 chars for identification
    api_key_hash         TEXT,                              -- bcrypt hash of full key
    key_expires_at       TEXT,                              -- ISO8601 or NULL for no expiry
    key_last_used_at     TEXT,                              -- ISO8601

    -- Lifecycle
    created_at           TEXT        NOT NULL,
    updated_at           TEXT        NOT NULL,
    last_seen_at         TEXT,                              -- Last API request
    is_active            INTEGER     NOT NULL DEFAULT 1     -- Soft disable
);

CREATE INDEX IF NOT EXISTS idx_agents_trust_level ON agents(trust_level);
CREATE INDEX IF NOT EXISTS idx_agents_active      ON agents(is_active);

-- ─────────────────────────────────────────────────────────────────────────
-- AUDIT_LOG — Immutable audit trail
-- See ARCHITECTURE.md §14 Security → Audit Log
-- INSERT ONLY — no UPDATE or DELETE operations permitted
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
    id           TEXT    PRIMARY KEY,           -- UUID v4
    timestamp    TEXT    NOT NULL,              -- ISO8601
    agent_id     TEXT    NOT NULL,              -- Who performed the action
    action       TEXT    NOT NULL,              -- e.g. "memory.write", "key.create", "review.approve"
    resource_id  TEXT,                          -- What was affected (memory ID, key ID, etc.)
    result       TEXT    NOT NULL,              -- "success" | "denied" | "error"
    ip_address   TEXT,                          -- Source IP (if available)
    request_id   TEXT,                          -- X-Request-ID for tracing
    details      TEXT                           -- JSON blob with extra context
);

CREATE INDEX IF NOT EXISTS idx_audit_timestamp  ON audit_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_agent      ON audit_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_audit_action     ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_resource   ON audit_log(resource_id);

-- ─────────────────────────────────────────────────────────────────────────
-- PENDING_REVIEW — Trust Pipeline staging area
-- See ARCHITECTURE.md §4.3 Trust Pipeline status machine
-- Records enter here immediately on write and are processed asynchronously
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pending_review (
    id              TEXT    PRIMARY KEY,           -- UUID v4 (same as memories.id)
    memory_id       TEXT    NOT NULL REFERENCES memories(id),
    queued_at       TEXT    NOT NULL,              -- When it entered the pipeline
    priority        INTEGER NOT NULL DEFAULT 5,    -- 1 (high) to 10 (low)

    -- Verification state
    attempt_count   INTEGER NOT NULL DEFAULT 0,    -- How many times verification was attempted
    last_attempt_at TEXT,                          -- ISO8601
    error_message   TEXT,                          -- Last error if verification failed

    -- Assignment for human review
    assigned_to     TEXT,                          -- Reviewer agent/user ID
    assigned_at     TEXT,                          -- ISO8601

    -- Escalation
    escalated       INTEGER NOT NULL DEFAULT 0,    -- 1 = escalated past SLA
    escalated_at    TEXT,

    FOREIGN KEY (memory_id) REFERENCES memories(id)
);

CREATE INDEX IF NOT EXISTS idx_pending_queued_at ON pending_review(queued_at);
CREATE INDEX IF NOT EXISTS idx_pending_priority  ON pending_review(priority);

-- ─────────────────────────────────────────────────────────────────────────
-- QUARANTINE — Isolated suspicious records
-- See ARCHITECTURE.md §4.4 Quarantine System
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS quarantine (
    id               TEXT    PRIMARY KEY,           -- UUID v4
    memory_id        TEXT    NOT NULL REFERENCES memories(id),
    reason           TEXT    NOT NULL,              -- Human-readable explanation
    severity         TEXT    NOT NULL DEFAULT 'medium',
    -- Values: low | medium | high | critical

    quarantined_at   TEXT    NOT NULL,
    quarantined_by   TEXT    NOT NULL,              -- Agent ID or "system"
    expires_at       TEXT    NOT NULL,              -- Auto-archive after 30d (ARCHITECTURE.md §4.4)

    review_count     INTEGER NOT NULL DEFAULT 0,
    last_reviewed_at TEXT,

    -- Appeal tracking
    appeal_text      TEXT,                          -- Appeal justification
    appeal_by        TEXT,                          -- Who appealed
    appeal_at        TEXT,

    FOREIGN KEY (memory_id) REFERENCES memories(id)
);

CREATE INDEX IF NOT EXISTS idx_quarantine_severity   ON quarantine(severity);
CREATE INDEX IF NOT EXISTS idx_quarantine_expires_at ON quarantine(expires_at);

-- ─────────────────────────────────────────────────────────────────────────
-- AGENT_METRICS — Time-series agent performance data
-- See ARCHITECTURE.md §4.7 Agent Metrics Transport
-- Hot: 7d in-memory + SQLite | Warm: 7-90d SQLite | Cold: GitHub/S3
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_metrics (
    id                       TEXT    PRIMARY KEY,
    agent_id                 TEXT    NOT NULL REFERENCES agents(id),
    timestamp                TEXT    NOT NULL,
    session_id               TEXT,

    -- Memory quality
    memories_written         INTEGER NOT NULL DEFAULT 0,
    memories_rejected        INTEGER NOT NULL DEFAULT 0,
    memories_auto_approved   INTEGER NOT NULL DEFAULT 0,
    memories_human_reviewed  INTEGER NOT NULL DEFAULT 0,
    avg_confidence_claimed   REAL,
    avg_confidence_actual    REAL,

    -- Agent self-reported quality (ARCHITECTURE.md §4.7)
    task_success_rate        REAL,
    hallucination_count      INTEGER,
    correction_count         INTEGER,
    user_satisfaction        REAL,

    -- Operational
    latency_p50_ms           INTEGER,
    latency_p95_ms           INTEGER,
    error_count              INTEGER,
    context_size_tokens      INTEGER
);

CREATE INDEX IF NOT EXISTS idx_metrics_agent_ts ON agent_metrics(agent_id, timestamp DESC);

-- ─────────────────────────────────────────────────────────────────────────
-- SYSTEM_STATE — Key-value store for internal system state
-- Used by health monitoring, DR system, and pipeline workers
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS system_state (
    key          TEXT    PRIMARY KEY,
    value        TEXT    NOT NULL,    -- JSON or plain string
    updated_at   TEXT    NOT NULL
);

-- Seed initial system state
INSERT OR IGNORE INTO system_state (key, value, updated_at)
VALUES
    ('schema_version',   '"3"',    datetime('now')),
    ('initialized_at',   '""',     datetime('now')),
    ('dr_last_backup',   'null',   datetime('now')),
    ('gh_last_snapshot', 'null',   datetime('now'));
