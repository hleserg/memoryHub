// api/middleware/logging.go
// Request/response logging and request ID middleware.
// See ARCHITECTURE.md §2 P4 "Observability First"

package middleware

import (
	"fmt"
	"log"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
)

// Logger returns a request/response logging middleware.
// Logs: method, path, status, latency, agent_id, request_id.
// TODO: Switch to structured JSON logging in production (log_format=json).
func Logger() gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		path := c.Request.URL.Path
		rawQuery := c.Request.URL.RawQuery

		c.Next()

		latency := time.Since(start)
		statusCode := c.Writer.Status()
		agentID := "-"
		if agent := GetAgent(c); agent != nil {
			agentID = agent.ID
		}
		requestID, _ := c.Get(ContextKeyRequestID)

		if rawQuery != "" {
			path = path + "?" + rawQuery
		}

		// TODO: Replace with structured logger (zap or slog)
		log.Printf("[%d] %s %s | %v | agent=%s | req=%v",
			statusCode,
			c.Request.Method,
			path,
			latency,
			agentID,
			requestID,
		)

		// TODO: Emit metrics (request count, latency histogram) to Health Monitoring
		// TODO: Log to audit_log for read operations if configured
	}
}

// RequestID attaches a unique X-Request-ID to every request.
// Used for distributed tracing and audit correlation.
func RequestID() gin.HandlerFunc {
	return func(c *gin.Context) {
		// Check if client sent X-Request-ID (pass-through)
		requestID := c.GetHeader("X-Request-ID")
		if requestID == "" {
			requestID = uuid.New().String()
		}

		c.Set(ContextKeyRequestID, requestID)
		c.Header("X-Request-ID", requestID)

		c.Next()
	}
}

// CORS returns CORS headers middleware.
// See ARCHITECTURE.md §4.1 config api_hub.cors
func CORS(cfg interface{ GetCORSOrigins() []string }) gin.HandlerFunc {
	return func(c *gin.Context) {
		// TODO: Implement proper CORS with config-based origins
		// For now, allow configured origins
		c.Header("Access-Control-Allow-Origin", "*") // TODO: restrict to cfg origins
		c.Header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
		c.Header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Request-ID")
		c.Header("Access-Control-Expose-Headers", "X-Request-ID, X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset, Retry-After")

		if c.Request.Method == "OPTIONS" {
			c.AbortWithStatus(204)
			return
		}

		c.Next()
	}
}

// GetRequestID retrieves the request ID from gin.Context.
func GetRequestID(c *gin.Context) string {
	v, _ := c.Get(ContextKeyRequestID)
	id, _ := v.(string)
	return id
}

// FormatDuration formats a duration for logging.
func FormatDuration(d time.Duration) string {
	if d < time.Millisecond {
		return fmt.Sprintf("%dµs", d.Microseconds())
	}
	return fmt.Sprintf("%dms", d.Milliseconds())
}
