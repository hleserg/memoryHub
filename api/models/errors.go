// api/models/errors.go
// Standardized error types for memoryHub API.
// See ARCHITECTURE.md §12 Error Codes

package models

import (
	"fmt"
	"net/http"
)

// APIError is the standard JSON error response body.
type APIError struct {
	Code      string `json:"code"`    // Machine-readable code (see below)
	Message   string `json:"message"` // Human-readable description
	RequestID string `json:"request_id,omitempty"`
	Details   any    `json:"details,omitempty"` // Optional extra context
}

func (e *APIError) Error() string {
	return fmt.Sprintf("[%s] %s", e.Code, e.Message)
}

// ─────────────────────────────────────────────────────────────────────────
// Standard HTTP error constructors
// See ARCHITECTURE.md §12 Error Codes (4xx/5xx)
// ─────────────────────────────────────────────────────────────────────────

func ErrBadRequest(message string) (int, *APIError) {
	return http.StatusBadRequest, &APIError{Code: "BAD_REQUEST", Message: message}
}

func ErrUnauthorized() (int, *APIError) {
	return http.StatusUnauthorized, &APIError{Code: "UNAUTHORIZED", Message: "Valid Bearer token required"}
}

func ErrForbidden(message string) (int, *APIError) {
	return http.StatusForbidden, &APIError{Code: "FORBIDDEN", Message: message}
}

func ErrNotFound(resource string) (int, *APIError) {
	return http.StatusNotFound, &APIError{Code: "NOT_FOUND", Message: fmt.Sprintf("%s not found", resource)}
}

func ErrConflict(message string) (int, *APIError) {
	return http.StatusConflict, &APIError{Code: "CONFLICT", Message: message}
}

func ErrUnprocessable(message string) (int, *APIError) {
	return http.StatusUnprocessableEntity, &APIError{Code: "UNPROCESSABLE", Message: message}
}

func ErrTooManyRequests(retryAfterSeconds int) (int, *APIError) {
	return http.StatusTooManyRequests, &APIError{
		Code:    "RATE_LIMITED",
		Message: fmt.Sprintf("Rate limit exceeded. Retry after %d seconds.", retryAfterSeconds),
		Details: map[string]int{"retry_after_seconds": retryAfterSeconds},
	}
}

func ErrInternal(message string) (int, *APIError) {
	return http.StatusInternalServerError, &APIError{Code: "INTERNAL_ERROR", Message: message}
}

func ErrServiceUnavailable(component string) (int, *APIError) {
	return http.StatusServiceUnavailable, &APIError{
		Code:    "SERVICE_UNAVAILABLE",
		Message: fmt.Sprintf("%s is temporarily unavailable. Degraded mode active.", component),
	}
}

func ErrGatewayTimeout(component string) (int, *APIError) {
	return http.StatusGatewayTimeout, &APIError{
		Code:    "GATEWAY_TIMEOUT",
		Message: fmt.Sprintf("%s did not respond in time.", component),
	}
}

// ─────────────────────────────────────────────────────────────────────────
// memoryHub-specific error codes
// See ARCHITECTURE.md §12 "Собственные коды"
// ─────────────────────────────────────────────────────────────────────────

// MH-001: Trust Pipeline overflow
func ErrTrustPipelineOverflow() (int, *APIError) {
	return http.StatusServiceUnavailable, &APIError{
		Code:    "MH-001",
		Message: "Trust Pipeline queue is full. Try again later.",
	}
}

// MH-002: Integrity checksum failure
func ErrIntegrityChecksum(memoryID string) (int, *APIError) {
	return http.StatusInternalServerError, &APIError{
		Code:    "MH-002",
		Message: "Integrity checksum failure detected. Record has been quarantined.",
		Details: map[string]string{"memory_id": memoryID},
	}
}

// MH-003: Knowledge Graph unreachable
func ErrKnowledgeGraphUnreachable() (int, *APIError) {
	return http.StatusServiceUnavailable, &APIError{
		Code:    "MH-003",
		Message: "Knowledge Graph is unavailable. Memories still stored; graph enrichment deferred.",
	}
}

// MH-004: Quarantine capacity exceeded
func ErrQuarantineCapacityExceeded() (int, *APIError) {
	return http.StatusServiceUnavailable, &APIError{
		Code:    "MH-004",
		Message: "Quarantine is at capacity. Administrative action required.",
	}
}

// MH-005: Backup verification failed
func ErrBackupVerificationFailed(snapshotID string) (int, *APIError) {
	return http.StatusInternalServerError, &APIError{
		Code:    "MH-005",
		Message: "Backup verification failed. Data may be corrupted.",
		Details: map[string]string{"snapshot_id": snapshotID},
	}
}
