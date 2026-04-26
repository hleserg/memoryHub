// mcp/resources.go
// MCP Resources — named resources that agents can read directly.
// See ARCHITECTURE.md §4.5 "MCP Resources"
//
// Available resources:
//   memoryhub://memories/{id}           — A specific memory record
//   memoryhub://graph/entity/{name}     — An entity from Knowledge Graph
//   memoryhub://graph/path/{a}/{b}      — Shortest path between two entities
//   memoryhub://stats/agent/{id}        — Agent statistics

package mcp

import (
	"encoding/json"
	"fmt"
	"strings"
)

// ResourceDefinition describes an MCP resource.
type ResourceDefinition struct {
	URI         string `json:"uri"`
	Name        string `json:"name"`
	Description string `json:"description"`
	MimeType    string `json:"mimeType"`
}

// GetResourceDefinitions returns the list of available resource URI templates.
func GetResourceDefinitions() map[string]any {
	resources := []ResourceDefinition{
		{
			URI:         "memoryhub://memories/{id}",
			Name:        "Memory Record",
			Description: "A single verified memory record by UUID",
			MimeType:    "application/json",
		},
		{
			URI:         "memoryhub://graph/entity/{name}",
			Name:        "Knowledge Graph Entity",
			Description: "An entity node from the Knowledge Graph with its relations",
			MimeType:    "application/json",
		},
		{
			URI:         "memoryhub://graph/path/{a}/{b}",
			Name:        "Graph Path",
			Description: "Shortest path between two entities in the Knowledge Graph",
			MimeType:    "application/json",
		},
		{
			URI:         "memoryhub://stats/agent/{id}",
			Name:        "Agent Statistics",
			Description: "Credibility score and activity metrics for an agent",
			MimeType:    "application/json",
		},
	}

	return map[string]any{"resources": resources}
}

// ResourceReadParams is the params for resources/read.
type ResourceReadParams struct {
	URI string `json:"uri"`
}

// ReadResource resolves a resource URI and returns its content.
func ReadResource(rawParams json.RawMessage) (any, *RPCError) {
	var params ResourceReadParams
	if err := json.Unmarshal(rawParams, &params); err != nil {
		return nil, &RPCError{Code: RPCInvalidParams, Message: "Invalid params"}
	}

	uri := params.URI
	switch {
	case strings.HasPrefix(uri, "memoryhub://memories/"):
		id := strings.TrimPrefix(uri, "memoryhub://memories/")
		return readMemory(id)

	case strings.HasPrefix(uri, "memoryhub://graph/entity/"):
		name := strings.TrimPrefix(uri, "memoryhub://graph/entity/")
		return readGraphEntity(name)

	case strings.HasPrefix(uri, "memoryhub://graph/path/"):
		path := strings.TrimPrefix(uri, "memoryhub://graph/path/")
		parts := strings.SplitN(path, "/", 2)
		if len(parts) != 2 {
			return nil, &RPCError{Code: RPCInvalidParams, Message: "URI format: memoryhub://graph/path/{a}/{b}"}
		}
		return readGraphPath(parts[0], parts[1])

	case strings.HasPrefix(uri, "memoryhub://stats/agent/"):
		agentID := strings.TrimPrefix(uri, "memoryhub://stats/agent/")
		return readAgentStats(agentID)

	default:
		return nil, &RPCError{Code: RPCMethodNotFound, Message: "Unknown resource URI: " + uri}
	}
}

func readMemory(id string) (any, *RPCError) {
	// TODO: Call API Hub: GET /v1/memory/{id}
	// TODO: Return memory as JSON content block
	result := fmt.Sprintf(`{"id":"%s","message":"TODO: readMemory not implemented"}`, id)
	return map[string]any{
		"contents": []map[string]any{
			{"uri": "memoryhub://memories/" + id, "mimeType": "application/json", "text": result},
		},
	}, nil
}

func readGraphEntity(name string) (any, *RPCError) {
	// TODO: Call API Hub: GET /v1/graph/entity/{name}
	result := fmt.Sprintf(`{"name":"%s","message":"TODO: readGraphEntity not implemented"}`, name)
	return map[string]any{
		"contents": []map[string]any{
			{"uri": "memoryhub://graph/entity/" + name, "mimeType": "application/json", "text": result},
		},
	}, nil
}

func readGraphPath(a, b string) (any, *RPCError) {
	// TODO: Call KuzuDB:
	//   MATCH path = shortestPath((a:Entity {name: $a})-[*]-(b:Entity {name: $b}))
	//   RETURN path
	result := fmt.Sprintf(`{"from":"%s","to":"%s","message":"TODO: readGraphPath not implemented"}`, a, b)
	return map[string]any{
		"contents": []map[string]any{
			{"uri": "memoryhub://graph/path/" + a + "/" + b, "mimeType": "application/json", "text": result},
		},
	}, nil
}

func readAgentStats(agentID string) (any, *RPCError) {
	// TODO: Call API Hub: GET /v1/metrics/agent/{id}
	result := fmt.Sprintf(`{"agent_id":"%s","message":"TODO: readAgentStats not implemented"}`, agentID)
	return map[string]any{
		"contents": []map[string]any{
			{"uri": "memoryhub://stats/agent/" + agentID, "mimeType": "application/json", "text": result},
		},
	}, nil
}
