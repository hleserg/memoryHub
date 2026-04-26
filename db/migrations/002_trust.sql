-- db/migrations/002_trust.sql
-- Trust Pipeline tables: pending_review queue, trust_scores, human review queue
-- See ARCHITECTURE.md §4.3 Trust Pipeline and §7 Trust Pipeline Flow

-- ─────────────────────────────────────────────────────────────────────────
-- PENDING REVIEW QUEUE
-- Staging area for all incoming agent writes.
-- Every write goes through here before being promoted to memories table.
-- See ARCHITECTURE.md §4.3 "pending_review (staging area)"
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pending_review (
    id              TEXT PRIMARY KEY,           -- UUID (same as memories.id after creation)
    memory_id       TEXT NOT NULL REFERENCES memories(id),
    queued_at       TEXT NOT NULL DEFAULT (datetime('now')),
    priority        INTEGER NOT NULL DEFAULT 5, -- 1=highest, 10=lowest
    
    -- Verification state
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_attempt    TEXT,
    next_attempt    TEXT,                       -- For retry scheduling
    
    -- Result
    status          TEXT NOT NULL DEFAULT 'waiting', -- waiting | processing | done | failed
    worker_id       TEXT,                       -- Which worker picked it up
    
    UNIQUE(memory_id)
);

CREATE INDEX IF NOT EXISTS idx_pending_review_status ON pending_review(status);
CREATE INDEX IF NOT EXISTS idx_pending_review_queued_at ON pending_review(queued_at);
CREATE INDEX IF NOT EXISTS idx_pending_review_priority ON pending_review(priority);
CREATE INDEX IF NOT EXISTS idx_pending_review_next_attempt ON pending_review(next_attempt);

-- ─────────────────────────────────────────────────────────────────────────
-- TRUST SCORES
-- Per-agent historical trust data used by Verification Engine.
-- Updated after each approved/rejected memory record.
-- See ARCHITECTURE.md §4.3 ③ Source Credibility
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS trust_scores (
    id                      TEXT PRIMARY KEY,   -- UUID
    agent_id                TEXT NOT NULL REFERENCES agents(id) UNIQUE,
    
    -- Credibility computation
    total_written           INTEGER NOT NULL DEFAULT 0,
    total_approved          INTEGER NOT NULL DEFAULT 0,
    total_rejected          INTEGER NOT NULL DEFAULT 0,
    total_quarantined       INTEGER NOT NULL DEFAULT 0,
    total_human_reviewed    INTEGER NOT NULL DEFAULT 0,
    
    -- Rolling averages
    avg_claimed_confidence  REAL,               -- What agent claims
    avg_actual_confidence   REAL,               -- What verification assigns
    confidence_calibration  REAL,               -- How well calibrated (|claimed - actual|)
    
    -- Computed score
    credibility_score       REAL NOT NULL DEFAULT 0.5,
    score_updated_at        TEXT NOT NULL DEFAULT (datetime('now')),
    
    -- History (last 30 days sliding window as JSON)
    daily_stats             TEXT,               -- JSON: [{date, written, approved, rejected}]
    
    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_trust_scores_agent_id ON trust_scores(agent_id);
CREATE INDEX IF NOT EXISTS idx_trust_scores_credibility ON trust_scores(credibility_score);

-- ─────────────────────────────────────────────────────────────────────────
-- HUMAN REVIEW QUEUE
-- Items that need manual review (score between thresholds).
-- See ARCHITECTURE.md §4.3 Human Review Interface
-- POST /v1/review/:id/approve or /reject
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS human_review_queue (
    id              TEXT PRIMARY KEY,           -- UUID
    memory_id       TEXT NOT NULL REFERENCES memories(id),
    
    -- Why it's here
    reason          TEXT NOT NULL,              -- Human-readable reason
    verification_details TEXT,                  -- JSON: full verification breakdown
    
    -- Assignment
    assigned_to     TEXT,                       -- Reviewer agent_id or NULL (any admin)
    assigned_at     TEXT,
    
    -- Status
    status          TEXT NOT NULL DEFAULT 'pending', -- pending | reviewing | approved | rejected | escalated
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    
    -- Escalation
    escalates_at    TEXT NOT NULL,              -- When to escalate if no action
    escalated       INTEGER NOT NULL DEFAULT 0,
    
    -- Decision
    decided_at      TEXT,
    decided_by      TEXT,                       -- Reviewer agent_id
    decision        TEXT,                       -- "approved" | "rejected"
    decision_comment TEXT,
    
    UNIQUE(memory_id)
);

CREATE INDEX IF NOT EXISTS idx_human_review_status ON human_review_queue(status);
CREATE INDEX IF NOT EXISTS idx_human_review_created_at ON human_review_queue(created_at);
CREATE INDEX IF NOT EXISTS idx_human_review_escalates_at ON human_review_queue(escalates_at);
CREATE INDEX IF NOT EXISTS idx_human_review_assigned_to ON human_review_queue(assigned_to);

-- ─────────────────────────────────────────────────────────────────────────
-- QUARANTINE
-- Isolated storage for suspicious/failed records.
-- See ARCHITECTURE.md §4.4 Quarantine System
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS quarantine (
    id              TEXT PRIMARY KEY,           -- UUID
    memory_id       TEXT NOT NULL REFERENCES memories(id),
    
    reason          TEXT NOT NULL,
    severity        TEXT NOT NULL DEFAULT 'medium', -- low | medium | high | critical
    quarantined_at  TEXT NOT NULL DEFAULT (datetime('now')),
    quarantined_by  TEXT NOT NULL,              -- Agent ID or "system"
    expires_at      TEXT NOT NULL,              -- Auto-archive after N days
    
    -- Review tracking
    review_count    INTEGER NOT NULL DEFAULT 0,
    last_reviewed   TEXT,
    appealed        INTEGER NOT NULL DEFAULT 0,
    appeal_by       TEXT,
    appeal_reason   TEXT,
    
    -- Resolution
    resolved        INTEGER NOT NULL DEFAULT 0,
    resolved_at     TEXT,
    resolved_by     TEXT,
    resolution      TEXT,                       -- "restored" | "archived" | "deleted"
    
    UNIQUE(memory_id)
);

CREATE INDEX IF NOT EXISTS idx_quarantine_severity ON quarantine(severity);
CREATE INDEX IF NOT EXISTS idx_quarantine_expires_at ON quarantine(expires_at);
CREATE INDEX IF NOT EXISTS idx_quarantine_resolved ON quarantine(resolved);

-- Update schema version
INSERT OR IGNORE INTO schema_migrations (version, description) VALUES
    ('002', 'Trust Pipeline: pending_review, trust_scores, human_review_queue, quarantine');
