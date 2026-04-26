// api/middleware/auth.go
// Bearer token authentication middleware.
// See ARCHITECTURE.md §4.1 API Key Vault and Auth & Permissions Matrix.
//
// All authenticated routes require:
//   Authorization: Bearer mhub_<env>_<agent_prefix>_<token>
//
// The middleware:
//   1. Extracts Bearer token from Authorization header
//   2. Hashes it and looks up in api_keys table
//   3. Validates expiry and active status
//   4. Attaches agent info to gin.Context for downstream handlers

package middleware

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/memoryhub/memoryhub/api/models"
	"github.com/memoryhub/memoryhub/config"
)

// Context keys for values attached by middleware.
const (
	ContextKeyAgent     = "agent"      // *models.Agent
	ContextKeyRequestID = "request_id" // string
)

// Auth returns the Bearer token authentication middleware.
// See ARCHITECTURE.md §4.1 Auth & Permissions Matrix for permission definitions.
func Auth(cfg *config.Config) gin.HandlerFunc {
	return func(c *gin.Context) {
		token, ok := extractBearerToken(c)
		if !ok {
			status, apiErr := models.ErrUnauthorized()
			c.AbortWithStatusJSON(status, apiErr)
			return
		}

		// TODO: Hash token with HMAC-SHA256
		// tokenHash := hmac.Hash(token, cfg.Keys.SystemKey)

		// TODO: Look up api_keys WHERE key_hash=$tokenHash AND is_active=1
		// TODO: Check expires_at (if set)
		// TODO: Load associated agent from agents table
		// TODO: Attach agent to context: c.Set(ContextKeyAgent, agent)
		// TODO: Update agents.last_seen_at (async, non-blocking)

		// TODO: Remove this placeholder — it allows all requests
		// This is a SKELETON — implement before any production use
		mockAgent := &models.Agent{
			ID:               "dev-agent",
			Name:             "dev",
			TrustLevel:       models.TrustLevelTrusted,
			Permissions:      []models.Permission{models.PermRead, models.PermWrite},
			CredibilityScore: 0.5,
			IsActive:         true,
		}
		c.Set(ContextKeyAgent, mockAgent)

		// Log token prefix for audit (never log full token)
		prefix := token
		if len(token) > 16 {
			prefix = token[:16] + "..."
		}
		_ = prefix // TODO: Add to audit context

		c.Next()
	}
}

// extractBearerToken parses "Authorization: Bearer <token>" header.
func extractBearerToken(c *gin.Context) (string, bool) {
	header := c.GetHeader("Authorization")
	if header == "" {
		return "", false
	}

	parts := strings.SplitN(header, " ", 2)
	if len(parts) != 2 || !strings.EqualFold(parts[0], "bearer") {
		return "", false
	}

	token := strings.TrimSpace(parts[1])
	if token == "" {
		return "", false
	}

	return token, true
}

// RequirePermission returns a middleware that checks for a specific permission.
// Use this on routes that need granular access control.
//
// Example:
//
//	auth.DELETE("/memory/:id", middleware.RequirePermission(models.PermAdminWrite), mem.Archive)
func RequirePermission(perm models.Permission) gin.HandlerFunc {
	return func(c *gin.Context) {
		agent, exists := c.Get(ContextKeyAgent)
		if !exists {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "not authenticated"})
			return
		}

		a, ok := agent.(*models.Agent)
		if !ok {
			c.AbortWithStatusJSON(http.StatusInternalServerError, gin.H{"error": "invalid agent context"})
			return
		}

		for _, p := range a.Permissions {
			if p == perm {
				c.Next()
				return
			}
		}

		status, apiErr := models.ErrForbidden("permission required: " + string(perm))
		c.AbortWithStatusJSON(status, apiErr)
	}
}

// GetAgent retrieves the authenticated agent from gin.Context.
// Returns nil if not authenticated (use after Auth middleware).
func GetAgent(c *gin.Context) *models.Agent {
	v, exists := c.Get(ContextKeyAgent)
	if !exists {
		return nil
	}
	agent, _ := v.(*models.Agent)
	return agent
}
