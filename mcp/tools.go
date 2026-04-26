// mcp/tools.go
// MCP Tool definitions and dispatch.
// These are the tools available to AI agents via MCP protocol.
// See ARCHITECTURE.md §4.5 "MCP Tools (доступные агентам)"
//
// Available tools:
//   memory_search  — Semantic + FTS search
//   memory_write   — Write to Trust Pipeline
//   memory_recall  — Get recent memories
//   graph_query    — Read-only Cypher queries
//   graph_relate   — Create entity relations
//   memory_status  — System health and stats

package mcp

import (
	"encoding/json"
	"fmt"
)

// ToolDefinition describes an MCP tool (sent in tools/list response).
type ToolDefinition struct {
	Name        string     `json:"name"`
	Description string     `json:"description"`
	InputSchema JSONSchema `json:"inputSchema"`
}

// JSONSchema is a simplified JSON Schema for tool input validation.
type JSONSchema struct {
	Type       string                    `json:"type"`
	Properties map[string]SchemaProperty `json:"properties"`
	Required   []string                  `json:"required,omitempty"`
}

// SchemaProperty describes one property in a JSON Schema.
type SchemaProperty struct {
	Type        string   `json:"type"`
	Description string   `json:"description"`
	Default     any      `json:"default,omitempty"`
	Minimum     *float64 `json:"minimum,omitempty"`
	Maximum     *float64 `json:"maximum,omitempty"`
	MaxLength   *int     `json:"maxLength,omitempty"`
	Items       *struct {
		Type string `json:"type"`
	} `json:"items,omitempty"`
}

// GetToolDefinitions returns all available MCP tools.
// See ARCHITECTURE.md §4.5 for full tool specs including params.
func GetToolDefinitions() map[string]any {
	min0 := 0.0
	max1 := 1.0
	max1000 := 1000

	tools := []ToolDefinition{
		{
			Name:        "memory_search",
			Description: "Search memories by semantic query. Returns verified (shared) memories ranked by relevance.",
			InputSchema: JSONSchema{
				Type: "object",
				Properties: map[string]SchemaProperty{
					"q":     {Type: "string", Description: "Search query (max 1000 chars)", MaxLength: &max1000},
					"limit": {Type: "integer", Description: "Max results (1-50, default 10)", Default: 10},
					"tags": {Type: "array", Description: "Filter by tags", Items: &struct {
						Type string `json:"type"`
					}{Type: "string"}},
					"min_confidence": {Type: "number", Description: "Minimum confidence (0.0-1.0)", Minimum: &min0, Maximum: &max1, Default: 0.0},
					"since":          {Type: "string", Description: "Only memories after this ISO8601 timestamp"},
					"include_graph":  {Type: "boolean", Description: "Enrich results with Knowledge Graph context", Default: false},
				},
				Required: []string{"q"},
			},
		},
		{
			Name:        "memory_write",
			Description: "Write a new memory. Goes through Trust Pipeline before becoming shared.",
			InputSchema: JSONSchema{
				Type: "object",
				Properties: map[string]SchemaProperty{
					"content": {Type: "string", Description: "Memory content (max 50,000 chars)"},
					"tags": {Type: "array", Description: "Tags (max 20)", Items: &struct {
						Type string `json:"type"`
					}{Type: "string"}},
					"source":     {Type: "string", Description: "Agent identifier writing this memory"},
					"confidence": {Type: "number", Description: "Agent's confidence in this fact (0.0-1.0)", Minimum: &min0, Maximum: &max1, Default: 0.5},
				},
				Required: []string{"content", "source"},
			},
		},
		{
			Name:        "memory_recall",
			Description: "Get recent shared memories, newest first.",
			InputSchema: JSONSchema{
				Type: "object",
				Properties: map[string]SchemaProperty{
					"limit": {Type: "integer", Description: "Max results (1-100, default 20)", Default: 20},
					"since": {Type: "string", Description: "Only memories after this ISO8601 timestamp"},
				},
			},
		},
		{
			Name:        "graph_query",
			Description: "Execute a read-only Cypher query against the Knowledge Graph.",
			InputSchema: JSONSchema{
				Type: "object",
				Properties: map[string]SchemaProperty{
					"cypher": {Type: "string", Description: "Cypher query (read-only: MATCH/RETURN only)"},
					"limit":  {Type: "integer", Description: "Max results (default 50, max 500)", Default: 50},
				},
				Required: []string{"cypher"},
			},
		},
		{
			Name:        "graph_relate",
			Description: "Create a typed relation between two entities in the Knowledge Graph.",
			InputSchema: JSONSchema{
				Type: "object",
				Properties: map[string]SchemaProperty{
					"from_entity": {Type: "string", Description: "Source entity name or ID"},
					"to_entity":   {Type: "string", Description: "Target entity name or ID"},
					"relation":    {Type: "string", Description: "Relation type: IS_A|HAS_PROPERTY|RELATED_TO|LOCATED_IN|HAPPENED_AT|CAUSED_BY|PRECEDED_BY|CONTRADICTS|SUPPORTS|PART_OF|KNOWS|WORKS_ON"},
					"confidence":  {Type: "number", Description: "Confidence in this relation (0.0-1.0)", Minimum: &min0, Maximum: &max1, Default: 0.5},
					"evidence": {Type: "array", Description: "Memory record IDs as evidence", Items: &struct {
						Type string `json:"type"`
					}{Type: "string"}},
				},
				Required: []string{"from_entity", "to_entity", "relation"},
			},
		},
		{
			Name:        "memory_status",
			Description: "Get system health summary and memory statistics.",
			InputSchema: JSONSchema{
				Type:       "object",
				Properties: map[string]SchemaProperty{},
			},
		},
	}

	return map[string]any{"tools": tools}
}

// ─────────────────────────────────────────────────────────────────────────
// Tool Call Dispatch
// See ARCHITECTURE.md §4.5 JSON-RPC example
// ─────────────────────────────────────────────────────────────────────────

// ToolCallParams is the params.arguments from tools/call JSON-RPC request.
type ToolCallParams struct {
	Name      string         `json:"name"`
	Arguments map[string]any `json:"arguments"`
}

// ContentBlock is the MCP content format for tool responses.
// See MCP spec: result.content[].type = "text"
type ContentBlock struct {
	Type string `json:"type"`
	Text string `json:"text"`
}

// ExecuteTool dispatches a tool call to the appropriate handler.
// Returns (result, error) in JSON-RPC format.
func ExecuteTool(rawParams json.RawMessage) (any, *RPCError) {
	var params ToolCallParams
	if err := json.Unmarshal(rawParams, &params); err != nil {
		return nil, &RPCError{Code: RPCInvalidParams, Message: "Invalid tool call params"}
	}

	switch params.Name {
	case "memory_search":
		return toolMemorySearch(params.Arguments)
	case "memory_write":
		return toolMemoryWrite(params.Arguments)
	case "memory_recall":
		return toolMemoryRecall(params.Arguments)
	case "graph_query":
		return toolGraphQuery(params.Arguments)
	case "graph_relate":
		return toolGraphRelate(params.Arguments)
	case "memory_status":
		return toolMemoryStatus(params.Arguments)
	default:
		return nil, &RPCError{Code: RPCMethodNotFound, Message: "Unknown tool: " + params.Name}
	}
}

// ─────────────────────────────────────────────────────────────────────────
// Individual tool implementations
// ─────────────────────────────────────────────────────────────────────────

func toolMemorySearch(args map[string]any) (any, *RPCError) {
	q, ok := args["q"].(string)
	if !ok || q == "" {
		return nil, &RPCError{Code: RPCInvalidParams, Message: "q is required"}
	}

	// TODO: Call API Hub: GET /v1/memory/search?q={q}&limit={limit}&...
	// TODO: Format results as JSON string in ContentBlock
	result := fmt.Sprintf(`[{"message":"TODO: search for '%s' not implemented"}]`, q)
	return map[string]any{
		"content": []ContentBlock{{Type: "text", Text: result}},
	}, nil
}

func toolMemoryWrite(args map[string]any) (any, *RPCError) {
	content, ok := args["content"].(string)
	if !ok || content == "" {
		return nil, &RPCError{Code: RPCInvalidParams, Message: "content is required"}
	}
	source, ok := args["source"].(string)
	if !ok || source == "" {
		return nil, &RPCError{Code: RPCInvalidParams, Message: "source is required"}
	}

	// TODO: Call API Hub: POST /v1/memory
	// TODO: Return memory ID and initial status
	result := `{"id":"TODO","status":"pending_review","message":"TODO: memory_write not implemented"}`
	return map[string]any{
		"content": []ContentBlock{{Type: "text", Text: result}},
	}, nil
}

func toolMemoryRecall(args map[string]any) (any, *RPCError) {
	// TODO: Call API Hub: GET /v1/memory/recent?limit={limit}
	result := `{"items":[],"message":"TODO: memory_recall not implemented"}`
	return map[string]any{
		"content": []ContentBlock{{Type: "text", Text: result}},
	}, nil
}

func toolGraphQuery(args map[string]any) (any, *RPCError) {
	cypher, ok := args["cypher"].(string)
	if !ok || cypher == "" {
		return nil, &RPCError{Code: RPCInvalidParams, Message: "cypher is required"}
	}

	// TODO: Validate read-only
	// TODO: Call API Hub: GET /v1/graph/query?cypher={cypher}
	result := fmt.Sprintf(`{"message":"TODO: graph_query for '%s' not implemented"}`, cypher)
	return map[string]any{
		"content": []ContentBlock{{Type: "text", Text: result}},
	}, nil
}

func toolGraphRelate(args map[string]any) (any, *RPCError) {
	// TODO: Validate from_entity, to_entity, relation params
	// TODO: Call API Hub: POST /v1/graph/relations
	result := `{"message":"TODO: graph_relate not implemented"}`
	return map[string]any{
		"content": []ContentBlock{{Type: "text", Text: result}},
	}, nil
}

func toolMemoryStatus(args map[string]any) (any, *RPCError) {
	// TODO: Call API Hub: GET /v1/status
	result := `{"status":"TODO: memory_status not implemented"}`
	return map[string]any{
		"content": []ContentBlock{{Type: "text", Text: result}},
	}, nil
}
