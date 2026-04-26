// api/models/agent.go
// Agent data model.
// Agents are AI systems (Claude, custom bots, etc.) that use memoryHub.
// See ARCHITECTURE.md §4.1 API Key Vault, §4.7 Agent Metrics Transport.

package models

import "time"

// TrustLevel controls rate limits and permissions.
// See ARCHITECTURE.md §4.1 Rate Limiter tier table.
type TrustLevel string

const (
	TrustLevelAnonymous  TrustLevel = "anonymous"
	TrustLevelRegistered TrustLevel = "registered"
	TrustLevelVerified   TrustLevel = "verified"
	TrustLevelTrusted    TrustLevel = "trusted"
)

// Permission defines what an agent can do.
// See ARCHITECTURE.md §4.1 Auth & Permissions Matrix.
type Permission string

const (
	PermRead       Permission = "read"
	PermWrite      Permission = "write"
	PermVerify     Permission = "verify"
	PermAdminRead  Permission = "admin_read"
	PermAdminWrite Permission = "admin_write"
	PermQuarantine Permission = "quarantine"
	PermRestore    Permission = "restore"
)

// Agent represents an AI agent registered in memoryHub.
type Agent struct {
	ID                string            `json:"id" db:"id"`
	Name              string            `json:"name" db:"name"`
	Description       string            `json:"description,omitempty" db:"description"`
	TrustLevel        TrustLevel        `json:"trust_level" db:"trust_level"`
	Permissions       []Permission      `json:"permissions"` // Stored as JSON in SQLite
	CredibilityScore  float64           `json:"credibility_score" db:"credibility_score"`
	RateLimitOverride *RateTierOverride `json:"rate_limit_override,omitempty"`
	CreatedAt         time.Time         `json:"created_at" db:"created_at"`
	UpdatedAt         time.Time         `json:"updated_at" db:"updated_at"`
	LastSeenAt        *time.Time        `json:"last_seen_at,omitempty" db:"last_seen_at"`
	ExpiresAt         *time.Time        `json:"expires_at,omitempty" db:"expires_at"`
	IsActive          bool              `json:"is_active" db:"is_active"`
}

// RateTierOverride allows per-agent rate limit customization.
type RateTierOverride struct {
	WriteRPM    *int `json:"write_rpm,omitempty"`
	ReadRPM     *int `json:"read_rpm,omitempty"`
	BulkOpsHour *int `json:"bulk_ops_hour,omitempty"` // -1 = unlimited
}

// AgentMetricsReport is what agents POST to /v1/metrics/report.
// See ARCHITECTURE.md §4.7 "Что агенты репортируют"
type AgentMetricsReport struct {
	AgentID   string  `json:"agent_id" binding:"required"`
	Timestamp string  `json:"timestamp" binding:"required"` // ISO8601
	SessionID *string `json:"session_id,omitempty"`

	// Memory quality
	MemoriesWritten       int     `json:"memories_written"`
	MemoriesRejected      int     `json:"memories_rejected"`
	MemoriesAutoApproved  int     `json:"memories_auto_approved"`
	MemoriesHumanReviewed int     `json:"memories_human_reviewed"`
	AvgConfidenceClaimed  float64 `json:"avg_confidence_claimed"`
	AvgConfidenceActual   float64 `json:"avg_confidence_actual"`

	// Work quality
	TaskSuccessRate    float64  `json:"task_success_rate"`
	HallucinationCount int      `json:"hallucination_count"` // Self-reported
	CorrectionCount    int      `json:"correction_count"`
	UserSatisfaction   *float64 `json:"user_satisfaction,omitempty"`

	// Operational
	LatencyP50MS      int `json:"latency_p50_ms"`
	LatencyP95MS      int `json:"latency_p95_ms"`
	ErrorCount        int `json:"error_count"`
	ContextSizeTokens int `json:"context_size_tokens"`
}

// AgentFeedback is returned by GET /v1/metrics/agent/:id/feedback.
// See ARCHITECTURE.md §4.7 Agent Feedback Loop.
type AgentFeedback struct {
	AgentID  string          `json:"agent_id"`
	Period   string          `json:"period"` // e.g. "7d"
	Feedback FeedbackDetails `json:"feedback"`
}

type FeedbackDetails struct {
	AccuracyTrend      string   `json:"accuracy_trend"` // e.g. "+0.05"
	MostRejectedTopics []string `json:"most_rejected_topics"`
	CredibilityScore   float64  `json:"credibility_score"`
	Recommendations    []string `json:"recommendations"`
}
