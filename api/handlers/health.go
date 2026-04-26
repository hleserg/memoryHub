// api/handlers/health.go
// Health check and system status endpoints.
// See ARCHITECTURE.md §4.8 Health Monitoring & Alerting
//
// Endpoints:
//   GET /v1/health  — Simple liveness probe (no auth)
//   GET /v1/status  — Full system status with component health

package handlers

import (
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/memoryhub/memoryhub/config"
)

// HealthHandler provides health and status endpoints.
type HealthHandler struct {
	cfg       *config.Config
	startedAt time.Time
	// TODO: inject all component health probes
}

func NewHealthHandler(cfg *config.Config) *HealthHandler {
	return &HealthHandler{
		cfg:       cfg,
		startedAt: time.Now(),
	}
}

// ComponentStatus represents health state of a single component.
// See ARCHITECTURE.md §4.8 "Component Health Status"
type ComponentStatus struct {
	Status  string         `json:"status"` // healthy | degraded | unhealthy | unknown
	Details map[string]any `json:"details,omitempty"`
	Message string         `json:"message,omitempty"`
}

// SystemStatus is the full system status response.
// See ARCHITECTURE.md §4.8 Dashboard mockup.
type SystemStatus struct {
	OverallHealth string                     `json:"overall_health"`
	Version       string                     `json:"version"`
	Environment   string                     `json:"environment"`
	UptimeSeconds int64                      `json:"uptime_seconds"`
	Timestamp     time.Time                  `json:"timestamp"`
	Components    map[string]ComponentStatus `json:"components"`
}

// Health handles GET /v1/health
// Simple liveness probe — returns 200 if process is alive.
// Used by Docker healthcheck and load balancers.
//
// Example:
//
//	curl http://localhost:3000/v1/health
//	→ {"status":"healthy","version":"1.0.0"}
func (h *HealthHandler) Health(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"status":  "healthy",
		"version": h.cfg.System.Version,
	})
}

// Status handles GET /v1/status
// Full system status with per-component health.
// See ARCHITECTURE.md §4.8 for complete status schema.
//
// Example:
//
//	curl http://localhost:3000/v1/status
func (h *HealthHandler) Status(c *gin.Context) {
	uptime := int64(time.Since(h.startedAt).Seconds())

	// TODO: Run actual health checks for each component
	// TODO: Aggregate to overall_health (worst of all components)
	// TODO: Include metrics: queue depth, disk usage, last backup age, etc.

	status := SystemStatus{
		OverallHealth: "healthy",
		Version:       h.cfg.System.Version,
		Environment:   h.cfg.System.Environment,
		UptimeSeconds: uptime,
		Timestamp:     time.Now(),
		Components: map[string]ComponentStatus{
			"api_hub": {
				Status:  "healthy",
				Message: "TODO: real health check",
			},
			"knowledge_graph": {
				Status:  "unknown",
				Message: "TODO: KuzuDB probe",
			},
			"trust_pipeline": {
				Status:  "unknown",
				Message: "TODO: queue depth check",
				Details: map[string]any{
					"queue_depth": 0, // TODO: real value
					"backlog":     0,
				},
			},
			"memory_store": {
				Status:  "unknown",
				Message: "TODO: SQLite connectivity check",
			},
			"mcp_server": {
				Status:  "unknown",
				Message: "TODO: MCP server probe",
			},
			"dr_system": {
				Status:  "unknown",
				Message: "TODO: last backup age check",
			},
		},
	}

	// Set HTTP status based on overall health
	httpStatus := http.StatusOK
	if status.OverallHealth == "unhealthy" {
		httpStatus = http.StatusServiceUnavailable
	} else if status.OverallHealth == "degraded" {
		httpStatus = http.StatusOK // Still return 200 for degraded (system works)
	}

	c.JSON(httpStatus, status)
}
