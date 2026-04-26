// api/models/memory.go
// Memory record data model.
// See ARCHITECTURE.md §4.3 Trust Pipeline (status machine),
// §6 Data Flow, §13 MemoryWriteInput / MemorySearchInput interfaces.

package models

import "time"

// MemoryStatus represents Trust Pipeline states.
// State machine: pending_review → auto_verification → shared | needs_human_review | quarantine
// See ARCHITECTURE.md §4.3 State Machine diagram
type MemoryStatus string

const (
	StatusPendingReview    MemoryStatus = "pending_review"
	StatusAwaitingVerify   MemoryStatus = "awaiting_verify"
	StatusShared           MemoryStatus = "shared"
	StatusNeedsHumanReview MemoryStatus = "needs_human_review"
	StatusQuarantine       MemoryStatus = "quarantine"
	StatusDeprecated       MemoryStatus = "deprecated"
	StatusArchived         MemoryStatus = "archived"
)

// Memory is the primary data structure for a memory record.
// Stored in memories table. See db/migrations/001_init.sql.
type Memory struct {
	ID                string   `json:"id" db:"id"`
	Content           string   `json:"content" db:"content"`
	Tags              []string `json:"tags" db:"tags"` // Stored as JSON in SQLite
	SourceAgent       string   `json:"source_agent" db:"source_agent"`
	ConfidenceClaimed float64  `json:"confidence_claimed" db:"confidence_claimed"`
	ConfidenceActual  *float64 `json:"confidence_actual,omitempty" db:"confidence_actual"`

	// Trust Pipeline fields
	Status             MemoryStatus           `json:"status" db:"status"`
	VerificationScore  *float64               `json:"verification_score,omitempty" db:"verification_score"`
	VerificationScores *VerificationBreakdown `json:"verification_scores,omitempty"` // Stored as JSON
	VerifiedAt         *time.Time             `json:"verified_at,omitempty" db:"verified_at"`
	VerifiedBy         *string                `json:"verified_by,omitempty" db:"verified_by"`
	ReviewComment      *string                `json:"review_comment,omitempty" db:"review_comment"`
	ReviewerID         *string                `json:"reviewer_id,omitempty" db:"reviewer_id"`

	// Integrity
	Checksum    string `json:"checksum" db:"checksum"`
	IntegrityOK bool   `json:"integrity_ok" db:"integrity_ok"`

	// Knowledge Graph linkage
	EntitiesExtracted bool     `json:"entities_extracted" db:"entities_extracted"`
	GraphNodeIDs      []string `json:"graph_node_ids,omitempty"` // Stored as JSON

	// Lifecycle
	CreatedAt time.Time  `json:"created_at" db:"created_at"`
	UpdatedAt time.Time  `json:"updated_at" db:"updated_at"`
	ExpiresAt *time.Time `json:"expires_at,omitempty" db:"expires_at"`

	// Relations
	SupersedesID   *string `json:"supersedes_id,omitempty" db:"supersedes_id"`
	SupersededByID *string `json:"superseded_by_id,omitempty" db:"superseded_by_id"`

	// Conflict tracking
	HasConflict bool     `json:"has_conflict" db:"has_conflict"`
	ConflictIDs []string `json:"conflict_ids,omitempty"` // Stored as JSON
}

// VerificationBreakdown shows per-checker scores from Verification Engine.
// See ARCHITECTURE.md §4.3 ⑤ Confidence Scorer formula:
//
//	final_score = fact_check*0.30 + anomaly*0.20 + credibility*0.30 + conflict*0.20
type VerificationBreakdown struct {
	FactChecker       float64 `json:"fact_checker"`
	AnomalyDetector   float64 `json:"anomaly_detector"`
	SourceCredibility float64 `json:"source_credibility"`
	ConflictScanner   float64 `json:"conflict_scanner"`
	FinalScore        float64 `json:"final_score"`
}

// ─────────────────────────────────────────────────────────────────────────
// API Request/Response types
// See ARCHITECTURE.md §13 Interfaces between components
// ─────────────────────────────────────────────────────────────────────────

// MemoryWriteRequest is the API payload for POST /v1/memory.
// See ARCHITECTURE.md §13 MemoryWriteInput interface.
type MemoryWriteRequest struct {
	Content    string         `json:"content" binding:"required,min=1,max=50000"`
	Tags       []string       `json:"tags"`                             // Max 20 tags
	Source     string         `json:"source" binding:"required"`        // Agent identifier
	Confidence float64        `json:"confidence" binding:"min=0,max=1"` // 0.0-1.0, default 0.5
	Relations  []RelationHint `json:"relations,omitempty"`              // Hints for Knowledge Graph
}

// RelationHint suggests a relation to create in Knowledge Graph.
type RelationHint struct {
	Entity string `json:"entity"`
	Type   string `json:"type"` // RelationType from ARCHITECTURE.md §4.2
}

// MemorySearchRequest is the query params for GET /v1/memory/search.
// See ARCHITECTURE.md §13 MemorySearchInput interface.
type MemorySearchRequest struct {
	Q             string   `form:"q" binding:"required,min=1,max=1000"`
	Limit         int      `form:"limit"` // 1-50, default 10
	Tags          []string `form:"tags"`
	MinConfidence float64  `form:"min_confidence"` // 0.0-1.0
	Since         string   `form:"since"`          // ISO8601 timestamp
	IncludeGraph  bool     `form:"include_graph"`  // Enrich with KG context
}

// MemoryResponse is the API response for a single memory record.
type MemoryResponse struct {
	*Memory
	// TODO: Add computed fields (e.g. related entities from KG)
}

// MemoryListResponse is the paginated list response.
type MemoryListResponse struct {
	Items  []MemoryResponse `json:"items"`
	Total  int              `json:"total"`
	Limit  int              `json:"limit"`
	Offset int              `json:"offset"`
}
