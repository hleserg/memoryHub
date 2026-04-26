-- db/migrations/001_init.sql
-- Initial schema: memories, agents, audit_log
-- See ARCHITECTURE.md §4.1 (API Hub), §4.3 (Trust Pipeline), §14 (Security/Audit)
--
-- Run: sqlite3 ./data/memoryhub.sqlite < db/migrations/001_init.sql
-- Or via: make db-migrate

-- ─────────────────────────────────────────────────────────────────────────
-- AGENTS
-- Tracks all registered AI agents using memoryHub.
-- trust_level matches API Hub rate limit tiers.
-- See ARCHITECTURE.md §4.1 Auth & Permissions Matrix
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agents (
    id                  TEXT PRIMARY KEY,               -- UUID
    name                TEXT NOT NULL UNIQUE,           -- Human-readable name (e.g. "alfred")
    description         TEXT,
    trust_level         TEXT NOT NULL DEFAULT 'registered', -- anonymous|registered|verified|trusted
    permissions         TEXT NOT NULL DEFAULT '["read","write"]', -- JSON array
    credibility_score   REAL NOT NULL DEFAULT 0.5,     -- 0.0-1.0, see §4.7 Credibility
    api_key_hash        TEXT,                           -- HMAC of actual key (key stored separately)
    rate_limit_override TEXT,                           -- JSON, overrides tier defaults if set
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at        TEXT,
    expires_at          TEXT,                           -- NULL = no expiry
    is_active           INTEGER NOT NULL DEFAULT 1      -- 0 = deactivated
);

CREATE INDEX IF NOT EXISTS idx_agents_name ON agents(name);
CREATE INDEX IF NOT EXISTS idx_agents_trust_level ON agents(trust_level);
CREATE INDEX IF NOT EXISTS idx_agents_is_active ON agents(is_active);

-- ─────────────────────────────────────────────────────────────────────────
-- MEMORIES
-- The primary memory store. All records go through Trust Pipeline.
-- Status state machine: pending_review → (auto_verification) →
--   shared | needs_human_review | quarantine → deprecated → archived
-- See ARCHITECTURE.md §4.3 Trust Pipeline, §6 Data Flow
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS memories (
    id                  TEXT PRIMARY KEY,               -- UUID
    content             TEXT NOT NULL,                  -- The memory content (max 50,000 chars)
    tags                TEXT NOT NULL DEFAULT '[]',     -- JSON array of tags
    source_agent        TEXT NOT NULL,                  -- Agent ID that wrote this
    confidence_claimed  REAL NOT NULL DEFAULT 0.5,      -- Confidence claimed by agent (0.0-1.0)
    confidence_actual   REAL,                           -- Confidence after verification
    
    -- Trust Pipeline status
    -- See ARCHITECTURE.md §4.3 State Machine
    status              TEXT NOT NULL DEFAULT 'pending_review',
    -- Values: pending_review | awaiting_verify | shared | needs_human_review |
    --         quarantine | deprecated | archived
    
    -- Verification details
    verification_score  REAL,                           -- Final score from Verification Engine
    verification_scores TEXT,                           -- JSON: per-checker scores
    verified_at         TEXT,
    verified_by         TEXT,                           -- Agent ID or "auto"
    
    -- Human review
    review_comment      TEXT,
    reviewer_id         TEXT,
    
    -- Integrity (see §4.4 Memory Corruption Protection)
    checksum            TEXT,                           -- HMAC-SHA256 of content
    integrity_ok        INTEGER NOT NULL DEFAULT 1,
    
    -- Knowledge Graph linkage
    entities_extracted  INTEGER NOT NULL DEFAULT 0,     -- 0 = not yet processed
    graph_node_ids      TEXT,                           -- JSON array of KuzuDB node IDs
    
    -- Lifecycle
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at          TEXT,                           -- NULL = no expiry
    
    -- Relations
    supersedes_id       TEXT REFERENCES memories(id),  -- This record supersedes another
    superseded_by_id    TEXT REFERENCES memories(id),  -- This record was superseded
    
    -- Conflict tracking
    has_conflict        INTEGER NOT NULL DEFAULT 0,
    conflict_ids        TEXT,                           -- JSON array of conflicting memory IDs
    
    FOREIGN KEY (source_agent) REFERENCES agents(id)
);

CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status);
CREATE INDEX IF NOT EXISTS idx_memories_source_agent ON memories(source_agent);
CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories(created_at);
CREATE INDEX IF NOT EXISTS idx_memories_confidence ON memories(confidence_actual);
CREATE INDEX IF NOT EXISTS idx_memories_tags ON memories(tags);   -- Used for tag filtering (JSON contains)
CREATE INDEX IF NOT EXISTS idx_memories_has_conflict ON memories(has_conflict);

-- Full-text search index for memory content
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    id UNINDEXED,
    content,
    tags,
    source_agent UNINDEXED,
    content=memories,
    content_rowid=rowid
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS memories_fts_insert AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, id, content, tags, source_agent)
    VALUES (new.rowid, new.id, new.content, new.tags, new.source_agent);
END;

CREATE TRIGGER IF NOT EXISTS memories_fts_update AFTER UPDATE ON memories BEGIN
    DELETE FROM memories_fts WHERE rowid = old.rowid;
    INSERT INTO memories_fts(rowid, id, content, tags, source_agent)
    VALUES (new.rowid, new.id, new.content, new.tags, new.source_agent);
END;

CREATE TRIGGER IF NOT EXISTS memories_fts_delete AFTER DELETE ON memories BEGIN
    DELETE FROM memories_fts WHERE rowid = old.rowid;
END;

-- ─────────────────────────────────────────────────────────────────────────
-- AUDIT LOG
-- Immutable log of all significant actions.
-- No UPDATE or DELETE allowed — only INSERT.
-- See ARCHITECTURE.md §14 Security/Audit Log
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
    id          TEXT PRIMARY KEY,               -- UUID
    timestamp   TEXT NOT NULL DEFAULT (datetime('now')),
    agent_id    TEXT NOT NULL,                  -- Who did it
    action      TEXT NOT NULL,                  -- "memory.write" | "memory.read" | "key.create" | etc.
    resource_id TEXT,                           -- What was affected (memory ID, agent ID, etc.)
    result      TEXT NOT NULL,                  -- "success" | "denied" | "error"
    ip_address  TEXT,
    request_id  TEXT,                           -- For distributed tracing
    details     TEXT                            -- JSON: additional context
);

CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_agent_id ON audit_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_resource_id ON audit_log(resource_id);

-- Prevent UPDATE and DELETE on audit_log (immutability)
CREATE TRIGGER IF NOT EXISTS audit_log_no_update BEFORE UPDATE ON audit_log BEGIN
    SELECT RAISE(ABORT, 'audit_log is immutable — no updates allowed');
END;

CREATE TRIGGER IF NOT EXISTS audit_log_no_delete BEFORE DELETE ON audit_log BEGIN
    SELECT RAISE(ABORT, 'audit_log is immutable — no deletes allowed');
END;

-- ─────────────────────────────────────────────────────────────────────────
-- API KEYS
-- Actual keys are stored hashed. Raw key shown only once at creation.
-- Key format: mhub_<env>_<agent_prefix>_<random_32bytes_base58>
-- See ARCHITECTURE.md §4.1 API Key Vault
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS api_keys (
    id              TEXT PRIMARY KEY,           -- UUID
    agent_id        TEXT NOT NULL REFERENCES agents(id),
    key_hash        TEXT NOT NULL UNIQUE,       -- HMAC-SHA256 of the raw key
    key_prefix      TEXT NOT NULL,              -- First 16 chars for identification (mhub_prod_alfred_)
    name            TEXT,                       -- Human label for this key
    permissions     TEXT NOT NULL DEFAULT '["read","write"]', -- JSON array
    last_used_at    TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at      TEXT,                       -- NULL = no expiry
    is_active       INTEGER NOT NULL DEFAULT 1,
    revoke_reason   TEXT
);

CREATE INDEX IF NOT EXISTS idx_api_keys_agent_id ON api_keys(agent_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_is_active ON api_keys(is_active);

-- ─────────────────────────────────────────────────────────────────────────
-- SCHEMA VERSION
-- Track applied migrations.
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    applied_at  TEXT NOT NULL DEFAULT (datetime('now')),
    description TEXT
);

INSERT OR IGNORE INTO schema_migrations (version, description) VALUES
    ('001', 'Initial schema: memories, agents, api_keys, audit_log');

-- ─────────────────────────────────────────────────────────────────────────
-- SEED DATA (development only)
-- Remove or gate behind environment check in production.
-- ─────────────────────────────────────────────────────────────────────────
-- TODO: Add seed data for development environment
-- INSERT INTO agents (id, name, trust_level, permissions) VALUES
--     ('00000000-0000-0000-0000-000000000001', 'admin', 'trusted', '["read","write","admin_read","admin_write"]'),
--     ('00000000-0000-0000-0000-000000000002', 'alfred', 'trusted', '["read","write","verify"]');
