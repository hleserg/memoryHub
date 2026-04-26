// api/handlers/memory.go
// Memory CRUD endpoint handlers.
// See ARCHITECTURE.md §6 Data Flow and §13 MemoryWriteInput/MemorySearchInput interfaces.
//
// Endpoints:
//   POST   /v1/memory           — Write memory (goes through Trust Pipeline)
//   GET    /v1/memory/search    — Semantic + FTS search
//   GET    /v1/memory/recent    — Recent memories
//   GET    /v1/memory/:id       — Get by ID
//   DELETE /v1/memory/:id       — Soft-delete (archive)

package handlers

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/memoryhub/memoryhub/api/models"
	"github.com/memoryhub/memoryhub/config"
)

// MemoryHandler handles memory CRUD operations.
type MemoryHandler struct {
	cfg *config.Config
	// TODO: inject db *database.DB
	// TODO: inject trustPipeline *trust.Pipeline
	// TODO: inject embeddings *embeddings.Provider
	// TODO: inject graph *graph.Client
}

// NewMemoryHandler creates a new MemoryHandler.
func NewMemoryHandler(cfg *config.Config) *MemoryHandler {
	return &MemoryHandler{cfg: cfg}
}

// Create handles POST /v1/memory
// Accepts a new memory, queues it in Trust Pipeline.
// See ARCHITECTURE.md §6 Data Flow:
//
//	Agent → MCP Server → API Hub (auth) → Trust Pipeline (pending_review)
//
// Example:
//
//	curl -X POST http://localhost:3000/v1/memory \
//	  -H "Authorization: Bearer mhub_dev_alfred_..." \
//	  -H "Content-Type: application/json" \
//	  -d '{"content":"Sergey prefers dark roast coffee","tags":["preference"],"source":"alfred","confidence":0.85}'
func (h *MemoryHandler) Create(c *gin.Context) {
	var req models.MemoryWriteRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		status, apiErr := models.ErrBadRequest(err.Error())
		c.JSON(status, apiErr)
		return
	}

	// Validate tags count
	if len(req.Tags) > 20 {
		status, apiErr := models.ErrBadRequest("maximum 20 tags allowed")
		c.JSON(status, apiErr)
		return
	}

	// TODO: Generate UUID for memory ID
	// TODO: Compute HMAC-SHA256 checksum (see ARCHITECTURE.md §4.4 Integrity)
	// TODO: Create memory record in pending_review status
	// TODO: Enqueue to Trust Pipeline
	// TODO: If KnowledgeGraph available, schedule entity extraction
	// TODO: Update audit_log (action="memory.write", result="success")
	// TODO: Update agent last_seen_at

	// Placeholder response
	c.JSON(http.StatusAccepted, gin.H{
		"id":      "TODO: generated-uuid",
		"status":  "pending_review",
		"message": "Memory queued for verification. Check status with GET /v1/memory/{id}",
	})
}

// Search handles GET /v1/memory/search
// Performs semantic search (via embeddings) + full-text search.
// See ARCHITECTURE.md §6 Data Flow:
//
//	Agent → MCP Server → API Hub → Memory Store → Knowledge Graph → enriched results
//
// Example:
//
//	curl "http://localhost:3000/v1/memory/search?q=coffee+preference&limit=5&min_confidence=0.7" \
//	  -H "Authorization: Bearer mhub_dev_alfred_..."
func (h *MemoryHandler) Search(c *gin.Context) {
	var req models.MemorySearchRequest
	if err := c.ShouldBindQuery(&req); err != nil {
		status, apiErr := models.ErrBadRequest(err.Error())
		c.JSON(status, apiErr)
		return
	}

	// Apply defaults
	if req.Limit == 0 {
		req.Limit = h.cfg.MCPServer.Tools.MemorySearch.DefaultLimit
	}
	if req.Limit > h.cfg.MCPServer.Tools.MemorySearch.MaxLimit {
		req.Limit = h.cfg.MCPServer.Tools.MemorySearch.MaxLimit
	}

	// TODO: Generate embedding for query (semantic search)
	// TODO: Execute FTS5 query on memories_fts table
	// TODO: Merge and rank results (cosine similarity + BM25)
	// TODO: Filter by status=shared (only verified memories to agents)
	// TODO: Filter by tags if provided
	// TODO: Filter by min_confidence
	// TODO: Filter by since timestamp
	// TODO: If include_graph=true, enrich with Knowledge Graph context
	// TODO: Update audit_log (action="memory.search")

	// Placeholder response
	c.JSON(http.StatusOK, models.MemoryListResponse{
		Items:  []models.MemoryResponse{},
		Total:  0,
		Limit:  req.Limit,
		Offset: 0,
	})
}

// Recent handles GET /v1/memory/recent
// Returns the most recently created shared memories.
//
// Example:
//
//	curl "http://localhost:3000/v1/memory/recent?limit=20" \
//	  -H "Authorization: Bearer mhub_dev_alfred_..."
func (h *MemoryHandler) Recent(c *gin.Context) {
	limit := 20
	// TODO: Parse limit from query params
	// TODO: Respect MCPServer.Tools.MemoryRecall.MaxLimit

	// TODO: Query memories WHERE status='shared' ORDER BY created_at DESC LIMIT $limit
	// TODO: Update audit_log

	c.JSON(http.StatusOK, models.MemoryListResponse{
		Items:  []models.MemoryResponse{},
		Total:  0,
		Limit:  limit,
		Offset: 0,
	})
}

// Get handles GET /v1/memory/:id
// Returns a single memory record by ID.
//
// Example:
//
//	curl "http://localhost:3000/v1/memory/550e8400-e29b-41d4-a716-446655440000" \
//	  -H "Authorization: Bearer mhub_dev_alfred_..."
func (h *MemoryHandler) Get(c *gin.Context) {
	id := c.Param("id")
	if id == "" {
		status, apiErr := models.ErrBadRequest("id is required")
		c.JSON(status, apiErr)
		return
	}

	// TODO: Query memories WHERE id=$id
	// TODO: If status=quarantine and agent lacks admin_read permission → 403
	// TODO: Verify integrity checksum (if corruption_protection.checksums.verify_on_read)
	// TODO: If checksum mismatch → trigger ErrIntegrityChecksum, quarantine record
	// TODO: Update audit_log (action="memory.read")

	// Placeholder: not found
	status, apiErr := models.ErrNotFound("memory")
	c.JSON(status, apiErr)
}

// Archive handles DELETE /v1/memory/:id
// Soft-deletes a memory (marks as archived). Records are never truly deleted.
// See ARCHITECTURE.md §2 P6 "Immutability of History"
//
// Example:
//
//	curl -X DELETE "http://localhost:3000/v1/memory/550e8400-..." \
//	  -H "Authorization: Bearer mhub_dev_alfred_..."
func (h *MemoryHandler) Archive(c *gin.Context) {
	id := c.Param("id")
	if id == "" {
		status, apiErr := models.ErrBadRequest("id is required")
		c.JSON(status, apiErr)
		return
	}

	// TODO: Check agent has write permission on this record
	// TODO: Update status to 'archived' (NOT actual DELETE)
	// TODO: Update audit_log (action="memory.archive")
	// TODO: Remove from Knowledge Graph active relations (but keep entity history)

	// Placeholder
	status, apiErr := models.ErrNotFound("memory")
	c.JSON(status, apiErr)
}
