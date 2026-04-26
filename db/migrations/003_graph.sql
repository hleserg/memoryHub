-- db/migrations/003_graph.sql
-- Knowledge Graph support tables (SQLite side).
-- Note: The actual graph is stored in KuzuDB (see graph/ package).
-- These tables track entity metadata and conflict records in SQLite
-- for fast lookup and audit purposes.
-- See ARCHITECTURE.md §4.2 Knowledge Graph

-- ─────────────────────────────────────────────────────────────────────────
-- ENTITIES (SQLite mirror)
-- Primary graph lives in KuzuDB. This table provides fast SQL queries
-- and cross-references with memory records.
-- See ARCHITECTURE.md §4.2 "Сущности (Nodes)"
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS entities (
    id              TEXT PRIMARY KEY,               -- UUID (matches KuzuDB node ID)
    name            TEXT NOT NULL,
    type            TEXT NOT NULL,                  -- person|place|concept|event|thing|agent
    aliases         TEXT NOT NULL DEFAULT '[]',     -- JSON array
    description     TEXT,
    confidence      REAL NOT NULL DEFAULT 0.5,
    source_agent    TEXT NOT NULL REFERENCES agents(id),
    tags            TEXT NOT NULL DEFAULT '[]',     -- JSON array
    
    -- KuzuDB reference
    kuzu_node_id    TEXT UNIQUE,                    -- Native KuzuDB node identifier
    
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
CREATE INDEX IF NOT EXISTS idx_entities_source_agent ON entities(source_agent);

-- Full-text search for entity names and descriptions
CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(
    id UNINDEXED,
    name,
    aliases,
    description,
    content=entities,
    content_rowid=rowid
);

-- ─────────────────────────────────────────────────────────────────────────
-- RELATIONS (SQLite mirror)
-- Edge metadata for SQL queries. Actual traversal via KuzuDB Cypher.
-- See ARCHITECTURE.md §4.2 "Отношения (Edges)"
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS relations (
    id              TEXT PRIMARY KEY,               -- UUID
    from_entity_id  TEXT NOT NULL REFERENCES entities(id),
    to_entity_id    TEXT NOT NULL REFERENCES entities(id),
    type            TEXT NOT NULL,
    -- Types: IS_A|HAS_PROPERTY|RELATED_TO|LOCATED_IN|HAPPENED_AT|
    --        CAUSED_BY|PRECEDED_BY|CONTRADICTS|SUPPORTS|PART_OF|
    --        KNOWS|WORKS_ON
    -- See ARCHITECTURE.md §4.2 RelationType
    
    strength        REAL NOT NULL DEFAULT 0.5,      -- 0.0-1.0
    valid_from      TEXT NOT NULL DEFAULT (datetime('now')),
    valid_until     TEXT,                           -- NULL = currently valid
    confidence      REAL NOT NULL DEFAULT 0.5,
    source_agent    TEXT NOT NULL REFERENCES agents(id),
    evidence        TEXT NOT NULL DEFAULT '[]',     -- JSON: memory record IDs
    
    -- KuzuDB reference
    kuzu_edge_id    TEXT UNIQUE,
    
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_relations_from ON relations(from_entity_id);
CREATE INDEX IF NOT EXISTS idx_relations_to ON relations(to_entity_id);
CREATE INDEX IF NOT EXISTS idx_relations_type ON relations(type);
CREATE INDEX IF NOT EXISTS idx_relations_valid_until ON relations(valid_until);

-- ─────────────────────────────────────────────────────────────────────────
-- CONFLICTS
-- Records of detected contradictions in the Knowledge Graph.
-- See ARCHITECTURE.md §4.2 Conflict Detection
-- Conflict types:
--   DIRECT_CONTRADICTION | TEMPORAL_CONFLICT |
--   PROPERTY_CONFLICT    | LOGICAL_INCONSISTENCY
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conflicts (
    id                  TEXT PRIMARY KEY,           -- UUID
    type                TEXT NOT NULL,              -- ConflictType enum
    
    -- The two conflicting items
    item_a_id           TEXT NOT NULL,              -- Memory ID or Entity ID
    item_a_type         TEXT NOT NULL,              -- "memory" | "entity" | "relation"
    item_b_id           TEXT NOT NULL,
    item_b_type         TEXT NOT NULL,
    
    description         TEXT NOT NULL,              -- Human-readable explanation
    severity            TEXT NOT NULL DEFAULT 'medium', -- low | medium | high | critical
    
    -- Detection
    detected_at         TEXT NOT NULL DEFAULT (datetime('now')),
    detected_by         TEXT NOT NULL,              -- "system" | agent_id
    
    -- Resolution
    resolved            INTEGER NOT NULL DEFAULT 0,
    resolved_at         TEXT,
    resolved_by         TEXT,
    resolution_type     TEXT,                       -- "item_a_correct" | "item_b_correct" | "both_deprecated" | "merged"
    resolution_notes    TEXT,
    
    -- Escalation
    escalated           INTEGER NOT NULL DEFAULT 0,
    escalated_at        TEXT
);

CREATE INDEX IF NOT EXISTS idx_conflicts_resolved ON conflicts(resolved);
CREATE INDEX IF NOT EXISTS idx_conflicts_severity ON conflicts(severity);
CREATE INDEX IF NOT EXISTS idx_conflicts_detected_at ON conflicts(detected_at);
CREATE INDEX IF NOT EXISTS idx_conflicts_item_a ON conflicts(item_a_id);
CREATE INDEX IF NOT EXISTS idx_conflicts_item_b ON conflicts(item_b_id);

-- ─────────────────────────────────────────────────────────────────────────
-- GRAPH SNAPSHOTS (Temporal Graph support)
-- Periodic exports of graph state for point-in-time queries.
-- See ARCHITECTURE.md §4.2 Temporal Graph
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS graph_snapshots (
    id              TEXT PRIMARY KEY,
    snapshot_at     TEXT NOT NULL,
    entity_count    INTEGER NOT NULL DEFAULT 0,
    relation_count  INTEGER NOT NULL DEFAULT 0,
    kuzu_path       TEXT,                           -- Path to KuzuDB snapshot file
    cypher_export   TEXT,                           -- Inline Cypher export (small snapshots)
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_graph_snapshots_at ON graph_snapshots(snapshot_at);

-- ─────────────────────────────────────────────────────────────────────────
-- MEMORY <-> ENTITY mapping
-- Many-to-many: one memory can mention many entities, one entity in many memories
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS memory_entities (
    memory_id   TEXT NOT NULL REFERENCES memories(id),
    entity_id   TEXT NOT NULL REFERENCES entities(id),
    mentioned   INTEGER NOT NULL DEFAULT 1,         -- Times mentioned in this memory
    PRIMARY KEY (memory_id, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_memory_entities_memory ON memory_entities(memory_id);
CREATE INDEX IF NOT EXISTS idx_memory_entities_entity ON memory_entities(entity_id);

-- Update schema version
INSERT OR IGNORE INTO schema_migrations (version, description) VALUES
    ('003', 'Knowledge Graph: entities, relations, conflicts, graph_snapshots, memory_entities');
