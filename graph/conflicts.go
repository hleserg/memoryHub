// graph/conflicts.go
// Conflict detection in the Knowledge Graph.
// Detects contradictions between memory records and graph entities.
// See ARCHITECTURE.md §4.2 Conflict Detection
//
// Conflict types:
//   DIRECT_CONTRADICTION  — A says X, B says NOT X
//   TEMPORAL_CONFLICT     — Same fact, opposite claims at same time
//   PROPERTY_CONFLICT     — Same entity, same property, different values
//   LOGICAL_INCONSISTENCY — Derived from graph traversal rules
//
// Called by:
//   - Trust Pipeline Verification Engine (④ Conflict Scanner)
//   - Memory Corruption Protection (continuous background scan)
//   - See ARCHITECTURE.md §5 Critical Path 3

package graph

import (
	"context"
	"fmt"
	"time"
)

// ConflictType categorizes detected contradictions.
// See ARCHITECTURE.md §4.2 "Conflict Detection"
type ConflictType string

const (
	ConflictDirectContradiction  ConflictType = "DIRECT_CONTRADICTION"
	ConflictTemporalConflict     ConflictType = "TEMPORAL_CONFLICT"
	ConflictPropertyConflict     ConflictType = "PROPERTY_CONFLICT"
	ConflictLogicalInconsistency ConflictType = "LOGICAL_INCONSISTENCY"
)

// ConflictRecord represents a detected contradiction.
// Stored in SQLite conflicts table (see db/migrations/003_graph.sql).
type ConflictRecord struct {
	ID          string       `json:"id"`
	Type        ConflictType `json:"type"`
	ItemAID     string       `json:"item_a_id"`
	ItemAType   string       `json:"item_a_type"` // "memory" | "entity" | "relation"
	ItemBID     string       `json:"item_b_id"`
	ItemBType   string       `json:"item_b_type"`
	Description string       `json:"description"`
	Severity    string       `json:"severity"` // low | medium | high | critical
	DetectedAt  time.Time    `json:"detected_at"`
	DetectedBy  string       `json:"detected_by"` // "system" or agent_id
	Resolved    bool         `json:"resolved"`
}

// ConflictDetector scans for contradictions in the Knowledge Graph.
type ConflictDetector struct {
	client *Client
	// TODO: inject db for reading/writing conflict records
	// TODO: inject notifier for health monitoring events
}

// NewConflictDetector creates a ConflictDetector.
func NewConflictDetector(client *Client) *ConflictDetector {
	return &ConflictDetector{client: client}
}

// ScanNewMemory checks a newly approved memory against existing knowledge.
// Called by Trust Pipeline Verification Engine (Step ④).
// Returns a conflict score (0.0=no conflicts, 1.0=direct contradiction).
// See ARCHITECTURE.md §4.3 ④ Conflict Scanner
func (d *ConflictDetector) ScanNewMemory(ctx context.Context, memoryID, content string) (float64, []ConflictRecord, error) {
	// TODO: Extract key claims from content (using entity extractor)
	// TODO: For each claim, query KuzuDB for contradicting facts:
	//   MATCH (e:Entity)-[r:CONTRADICTS]-(e2:Entity)
	//   WHERE e.name IN $mentioned_entities
	//   RETURN r
	// TODO: Check for PROPERTY_CONFLICT patterns:
	//   Same entity + same property + different values
	// TODO: Check for TEMPORAL_CONFLICT:
	//   Valid_from/valid_until overlap with contradicting claims
	//
	// Score computation:
	//   No conflicts:        1.0 (clean)
	//   Minor conflicts:     0.6-0.8
	//   Direct contradiction: 0.0-0.3

	// Placeholder: no conflicts detected
	score := 1.0 // Clean
	var conflicts []ConflictRecord

	return score, conflicts, nil
}

// RunFullScan scans all shared memories for conflicts.
// Called by Memory Corruption Protection on schedule.
// See ARCHITECTURE.md §4.4 "Continuous Fact Checker"
func (d *ConflictDetector) RunFullScan(ctx context.Context) ([]ConflictRecord, error) {
	// TODO: Batch through all shared memories
	// TODO: For each batch, run ScanBatch
	// TODO: Collect and deduplicate conflicts
	// TODO: Write new conflicts to SQLite conflicts table
	// TODO: Mark conflicting memories with has_conflict=true
	// TODO: Emit health monitoring event per conflict found
	// TODO: For DIRECT_CONTRADICTION: create CONTRADICTS edge in KuzuDB

	return nil, fmt.Errorf("TODO: RunFullScan not implemented")
}

// ScanBatch checks a batch of memories for mutual conflicts.
// Efficient batch processing to avoid N+1 queries.
func (d *ConflictDetector) ScanBatch(ctx context.Context, memoryIDs []string) ([]ConflictRecord, error) {
	// TODO: Batch Cypher query across memory entities
	return nil, fmt.Errorf("TODO: ScanBatch not implemented")
}

// ResolveConflict marks a conflict as resolved.
// Called after human review decision (approve/reject one side).
// See ARCHITECTURE.md §5 Critical Path 3
func (d *ConflictDetector) ResolveConflict(ctx context.Context, conflictID, resolverID, resolutionType, notes string) error {
	// resolution_type: "item_a_correct" | "item_b_correct" | "both_deprecated" | "merged"
	// TODO: Update conflicts table: resolved=true, resolved_by, resolution_type, notes
	// TODO: If item_a_correct: deprecate item_b
	// TODO: If item_b_correct: deprecate item_a
	// TODO: If both_deprecated: archive both
	// TODO: Remove CONTRADICTS edge from KuzuDB (conflict resolved)
	// TODO: Update has_conflict=false on resolved memories
	return fmt.Errorf("TODO: ResolveConflict not implemented")
}

// ─────────────────────────────────────────────────────────────────────────
// Drift Detection
// See ARCHITECTURE.md §4.4 "Memory Drift"
// ─────────────────────────────────────────────────────────────────────────

// DriftRecord tracks gradual fact drift over time.
type DriftRecord struct {
	EntityID    string    `json:"entity_id"`
	EntityName  string    `json:"entity_name"`
	Property    string    `json:"property"`
	EarlyValue  string    `json:"early_value"`
	RecentValue string    `json:"recent_value"`
	DriftScore  float64   `json:"drift_score"` // 0.0=no drift, 1.0=complete reversal
	DetectedAt  time.Time `json:"detected_at"`
}

// DetectDrift finds entities whose properties have gradually changed.
// Memory drift is subtle: many small changes that together form a contradiction.
// See ARCHITECTURE.md §4.4 "что детектируется: Pattern mimicry, Confidence inflation"
func (d *ConflictDetector) DetectDrift(ctx context.Context, entityName string) ([]DriftRecord, error) {
	// TODO: Get temporal history of entity properties
	// TODO: Compare first-seen values vs recent values
	// TODO: If semantic distance > threshold → DriftRecord
	return nil, fmt.Errorf("TODO: DetectDrift not implemented")
}
