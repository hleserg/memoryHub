// api/middleware/ratelimit.go
// Per-agent rate limiting middleware using sliding window algorithm.
// See ARCHITECTURE.md §4.1 Rate Limiter
//
// Tiers (from config):
//   anonymous:  5 write / 20 read RPM
//   registered: 30 write / 120 read RPM
//   verified:   100 write / 500 read RPM
//   trusted:    500 write / 2000 read RPM
//
// On exceed: 429 Too Many Requests with Retry-After header.

package middleware

import (
	"net/http"
	"strconv"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/memoryhub/memoryhub/api/models"
	"github.com/memoryhub/memoryhub/config"
)

// RateLimit returns the per-agent rate limiting middleware.
// Implements sliding window algorithm as specified in ARCHITECTURE.md §4.1.
// See config rate_limit.strategy: "sliding"
func RateLimit(cfg *config.Config) gin.HandlerFunc {
	limiter := newSlidingWindowLimiter(cfg)

	return func(c *gin.Context) {
		agent := GetAgent(c)
		if agent == nil {
			// No agent = anonymous tier
			// TODO: Rate limit by IP for anonymous requests
			c.Next()
			return
		}

		isWrite := isWriteOperation(c)
		allowed, retryAfter := limiter.Allow(agent, isWrite)

		// Add rate limit headers (if config.api_hub.rate_limit.headers.expose = true)
		if cfg.APIHub.RateLimit.Headers.Expose {
			tier := limiter.getTier(agent, isWrite)
			c.Header("X-RateLimit-Limit", strconv.Itoa(tier))
			c.Header("X-RateLimit-Remaining", strconv.Itoa(limiter.Remaining(agent, isWrite)))
			c.Header("X-RateLimit-Reset", strconv.FormatInt(time.Now().Add(time.Duration(cfg.APIHub.RateLimit.WindowMS)*time.Millisecond).Unix(), 10))
		}

		if !allowed {
			c.Header("Retry-After", strconv.Itoa(retryAfter))
			status, apiErr := models.ErrTooManyRequests(retryAfter)
			c.AbortWithStatusJSON(status, apiErr)
			return
		}

		c.Next()
	}
}

// isWriteOperation determines if the request is a write (vs read).
// Used to apply the correct rate limit tier.
func isWriteOperation(c *gin.Context) bool {
	method := c.Request.Method
	return method == http.MethodPost ||
		method == http.MethodPut ||
		method == http.MethodPatch ||
		method == http.MethodDelete
}

// ─────────────────────────────────────────────────────────────────────────
// Sliding Window Rate Limiter
// ─────────────────────────────────────────────────────────────────────────

// slidingWindowLimiter implements per-agent sliding window rate limiting.
// TODO: Replace in-memory store with Redis for multi-process deployments.
type slidingWindowLimiter struct {
	cfg     *config.Config
	mu      sync.RWMutex
	windows map[string]*agentWindow // keyed by agent_id:type (read|write)
}

type agentWindow struct {
	requests []time.Time // timestamps of recent requests
}

func newSlidingWindowLimiter(cfg *config.Config) *slidingWindowLimiter {
	return &slidingWindowLimiter{
		cfg:     cfg,
		windows: make(map[string]*agentWindow),
	}
}

// Allow checks if the agent is within rate limits and records the request.
// Returns (allowed bool, retryAfterSeconds int).
func (l *slidingWindowLimiter) Allow(agent *models.Agent, isWrite bool) (bool, int) {
	l.mu.Lock()
	defer l.mu.Unlock()

	key := agent.ID + ":write"
	if !isWrite {
		key = agent.ID + ":read"
	}

	window, ok := l.windows[key]
	if !ok {
		window = &agentWindow{}
		l.windows[key] = window
	}

	now := time.Now()
	windowDuration := time.Duration(l.cfg.APIHub.RateLimit.WindowMS) * time.Millisecond

	// Remove requests outside the sliding window
	cutoff := now.Add(-windowDuration)
	valid := window.requests[:0]
	for _, t := range window.requests {
		if t.After(cutoff) {
			valid = append(valid, t)
		}
	}
	window.requests = valid

	// Get limit for this agent's tier
	limit := l.getLimit(agent, isWrite)
	if limit == -1 {
		// Unlimited (trusted tier with bulk_ops_hour=-1 equivalent)
		window.requests = append(window.requests, now)
		return true, 0
	}

	if len(window.requests) >= limit {
		// Calculate retry-after
		oldest := window.requests[0]
		retryAt := oldest.Add(windowDuration)
		retryAfter := int(time.Until(retryAt).Seconds()) + 1
		if retryAfter < 1 {
			retryAfter = 1
		}
		return false, retryAfter
	}

	window.requests = append(window.requests, now)
	return true, 0
}

// Remaining returns how many requests remain in the current window.
func (l *slidingWindowLimiter) Remaining(agent *models.Agent, isWrite bool) int {
	l.mu.RLock()
	defer l.mu.RUnlock()

	limit := l.getLimit(agent, isWrite)
	if limit == -1 {
		return 9999
	}

	key := agent.ID + ":write"
	if !isWrite {
		key = agent.ID + ":read"
	}

	window, ok := l.windows[key]
	if !ok {
		return limit
	}

	remaining := limit - len(window.requests)
	if remaining < 0 {
		remaining = 0
	}
	return remaining
}

// getLimit returns the RPM limit for the agent based on trust tier.
func (l *slidingWindowLimiter) getLimit(agent *models.Agent, isWrite bool) int {
	tiers := l.cfg.APIHub.RateLimit.Tiers
	tier, ok := tiers[string(agent.TrustLevel)]
	if !ok {
		// Fallback to anonymous
		tier = tiers["anonymous"]
	}

	if isWrite {
		return tier.WriteRPM
	}
	return tier.ReadRPM
}

// getTier returns the max RPM for header reporting.
func (l *slidingWindowLimiter) getTier(agent *models.Agent, isWrite bool) int {
	return l.getLimit(agent, isWrite)
}
