// api/handlers/graph.go
// Knowledge Graph endpoint handlers.
// See ARCHITECTURE.md §4.2 Knowledge Graph (KuzuDB)
//
// Endpoints:
//   GET  /v1/graph/entity/:name    — Get entity by name
//   POST /v1/graph/relations       — Create relation between entities
//   GET  /v1/graph/query           — Cypher query (read-only for agents)
//   GET  /v1/graph/conflicts       — List unresolved conflicts
//   GET  /v1/graph/snapshot        — Point-in-time snapshot

package handlers

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/memoryhub/memoryhub/api/models"
	"github.com/memoryhub/memoryhub/config"
)

// GraphHandler handles Knowledge Graph operations.
type GraphHandler struct {
	cfg *config.Config
	// TODO: inject graph *graph.Client (KuzuDB wrapper)
}

func NewGraphHandler(cfg *config.Config) *GraphHandler {
	return &GraphHandler{cfg: cfg}
}

// GetEntity handles GET /v1/graph/entity/:name
// Returns an entity with its relations from the Knowledge Graph.
// See ARCHITECTURE.md §4.2 "Сущности (Nodes)"
//
// Example:
//
//	curl "http://localhost:3000/v1/graph/entity/Sergey" \
//	  -H "Authorization: Bearer mhub_dev_alfred_..."
func (h *GraphHandler) GetEntity(c *gin.Context) {
	name := c.Param("name")
	if name == "" {
		status, apiErr := models.ErrBadRequest("entity name is required")
		c.JSON(status, apiErr)
		return
	}

	// TODO: Query KuzuDB: MATCH (e:Entity {name: $name}) RETURN e
	// TODO: Fetch outgoing relations
	// TODO: Fetch incoming relations (limit depth=1 for performance)
	// TODO: Fall back to SQLite mirror if KuzuDB unavailable (graceful degradation)
	// TODO: Update audit_log (action="graph.entity.read")

	// If KuzuDB unavailable, return degraded response
	// See ARCHITECTURE.md §12 Graceful Degradation: Knowledge Graph
	status, apiErr := models.ErrKnowledgeGraphUnreachable()
	c.JSON(status, apiErr)
}

// CreateRelationRequest is the payload for creating a graph relation.
type CreateRelationRequest struct {
	FromEntity string   `json:"from" binding:"required"`
	ToEntity   string   `json:"to" binding:"required"`
	Type       string   `json:"type" binding:"required"` // RelationType enum
	Confidence float64  `json:"confidence" binding:"min=0,max=1"`
	Evidence   []string `json:"evidence"` // Memory record IDs supporting this relation
}

// CreateRelation handles POST /v1/graph/relations
// Creates a typed relation between two entities.
// See ARCHITECTURE.md §4.2 RelationType list and §13 graph_relate MCP tool.
//
// Example:
//
//	curl -X POST "http://localhost:3000/v1/graph/relations" \
//	  -H "Authorization: Bearer mhub_dev_alfred_..." \
//	  -d '{"from":"Sergey","to":"memoryHub","type":"WORKS_ON","confidence":0.9}'
func (h *GraphHandler) CreateRelation(c *gin.Context) {
	var req CreateRelationRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		status, apiErr := models.ErrBadRequest(err.Error())
		c.JSON(status, apiErr)
		return
	}

	// Validate RelationType
	// See ARCHITECTURE.md §4.2 "Типы отношений"
	validTypes := map[string]bool{
		"IS_A": true, "HAS_PROPERTY": true, "RELATED_TO": true,
		"LOCATED_IN": true, "HAPPENED_AT": true, "CAUSED_BY": true,
		"PRECEDED_BY": true, "CONTRADICTS": true, "SUPPORTS": true,
		"PART_OF": true, "KNOWS": true, "WORKS_ON": true,
	}
	if !validTypes[req.Type] {
		status, apiErr := models.ErrBadRequest("invalid relation type: " + req.Type)
		c.JSON(status, apiErr)
		return
	}

	// TODO: Resolve or create from_entity and to_entity in KuzuDB
	// TODO: Create relation edge in KuzuDB
	// TODO: Mirror relation metadata to SQLite relations table
	// TODO: Check for CONTRADICTS — if type is CONTRADICTS, create conflict record
	// TODO: Update audit_log (action="graph.relation.create")

	status, apiErr := models.ErrKnowledgeGraphUnreachable()
	c.JSON(status, apiErr)
}

// Query handles GET /v1/graph/query
// Executes a read-only Cypher query against KuzuDB.
// Agents cannot run write queries (read_only=true in config).
// See ARCHITECTURE.md §4.5 MCP Tools graph_query, §4.2 Cypher examples.
//
// Example:
//
//	curl "http://localhost:3000/v1/graph/query?cypher=MATCH+%28e%3AEntity%29+RETURN+e+LIMIT+10" \
//	  -H "Authorization: Bearer mhub_dev_alfred_..."
func (h *GraphHandler) Query(c *gin.Context) {
	cypher := c.Query("cypher")
	if cypher == "" {
		status, apiErr := models.ErrBadRequest("cypher query is required")
		c.JSON(status, apiErr)
		return
	}

	// TODO: Validate query is read-only (no CREATE, MERGE, SET, DELETE, etc.)
	// TODO: Apply max_results limit from config
	// TODO: Apply query timeout from config (mcp_server.tools.graph_query.timeout_ms)
	// TODO: Execute against KuzuDB
	// TODO: Return results as JSON

	status, apiErr := models.ErrKnowledgeGraphUnreachable()
	c.JSON(status, apiErr)
}

// ListConflicts handles GET /v1/graph/conflicts
// Returns unresolved conflicts in the Knowledge Graph.
// See ARCHITECTURE.md §4.2 Conflict Detection, §5 Critical Path 3
//
// Example:
//
//	curl "http://localhost:3000/v1/graph/conflicts?resolved=false" \
//	  -H "Authorization: Bearer mhub_dev_alfred_..."
func (h *GraphHandler) ListConflicts(c *gin.Context) {
	resolved := c.Query("resolved") == "true"

	// TODO: Query conflicts table WHERE resolved=$resolved
	// TODO: Join with memories table for item details
	// TODO: Order by severity DESC, detected_at DESC

	_ = resolved
	c.JSON(http.StatusOK, gin.H{
		"items":      []any{},
		"total":      0,
		"unresolved": 0,
	})
}

// Snapshot handles GET /v1/graph/snapshot
// Returns graph state at a specific point in time.
// See ARCHITECTURE.md §4.2 Temporal Graph
//
// Example:
//
//	curl "http://localhost:3000/v1/graph/snapshot?at=2026-04-25T03:00:00Z" \
//	  -H "Authorization: Bearer mhub_dev_alfred_..."
func (h *GraphHandler) Snapshot(c *gin.Context) {
	at := c.Query("at")
	if at == "" {
		status, apiErr := models.ErrBadRequest("at timestamp is required (ISO8601)")
		c.JSON(status, apiErr)
		return
	}

	// TODO: Parse timestamp
	// TODO: Query graph_snapshots table for nearest snapshot before 'at'
	// TODO: If exact snapshot exists, return it
	// TODO: If not, reconstruct from relations.valid_from/valid_until
	// TODO: Return as Cypher or JSON (based on Accept header)

	status, apiErr := models.ErrNotFound("graph snapshot")
	c.JSON(status, apiErr)
}
