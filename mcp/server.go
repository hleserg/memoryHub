// mcp/server.go
// MCP (Model Context Protocol) Server skeleton.
// Implements JSON-RPC 2.0 over HTTP + Server-Sent Events.
// Any MCP-compatible agent (Claude, OpenAI, Gemini, etc.) can connect.
// See ARCHITECTURE.md §4.5 MCP Server (port 3100)
//
// Protocol version: 2025-03-26
// Spec: https://modelcontextprotocol.io/
//
// TODO (Week 4 per roadmap): Implement full MCP server.

package mcp

import (
	"encoding/json"
	"fmt"
	"net/http"

	"github.com/memoryhub/memoryhub/config"
)

// Server is the MCP server.
// Exposes memoryHub capabilities to AI agents via the MCP protocol.
type Server struct {
	cfg *config.Config
	// TODO: inject api client (to call API Hub internally)
	// TODO: inject session manager (track connected agents)
}

// NewServer creates a new MCP server.
func NewServer(cfg *config.Config) *Server {
	return &Server{cfg: cfg}
}

// Start starts the MCP server.
// See ARCHITECTURE.md §4.5 for MCP interaction example (JSON-RPC).
func (s *Server) Start() error {
	mux := http.NewServeMux()

	// JSON-RPC endpoint
	mux.HandleFunc("/rpc", s.handleRPC)
	// SSE stream for notifications
	mux.HandleFunc("/events", s.handleEvents)
	// MCP discovery endpoint
	mux.HandleFunc("/", s.handleDiscovery)

	addr := fmt.Sprintf("%s:%d", s.cfg.MCPServer.Host, s.cfg.MCPServer.Port)
	fmt.Printf("MCP Server listening on http://%s\n", addr)

	// TODO: Add graceful shutdown
	return http.ListenAndServe(addr, mux)
}

// ─────────────────────────────────────────────────────────────────────────
// JSON-RPC 2.0 Types
// ─────────────────────────────────────────────────────────────────────────

// JSONRPCRequest is an incoming JSON-RPC 2.0 request.
type JSONRPCRequest struct {
	JSONRPC string          `json:"jsonrpc"` // Must be "2.0"
	ID      any             `json:"id"`      // string | number | null
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params,omitempty"`
}

// JSONRPCResponse is a JSON-RPC 2.0 response.
type JSONRPCResponse struct {
	JSONRPC string    `json:"jsonrpc"` // "2.0"
	ID      any       `json:"id"`
	Result  any       `json:"result,omitempty"`
	Error   *RPCError `json:"error,omitempty"`
}

// RPCError is a JSON-RPC 2.0 error object.
type RPCError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
	Data    any    `json:"data,omitempty"`
}

// Standard JSON-RPC error codes
const (
	RPCParseError     = -32700
	RPCInvalidRequest = -32600
	RPCMethodNotFound = -32601
	RPCInvalidParams  = -32602
	RPCInternalError  = -32603
)

// handleRPC processes JSON-RPC 2.0 requests.
// Routes to the appropriate MCP method handler.
// See ARCHITECTURE.md §4.5 MCP Tools and JSON-RPC example.
func (s *Server) handleRPC(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "POST required", http.StatusMethodNotAllowed)
		return
	}

	var req JSONRPCRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		s.writeError(w, nil, RPCParseError, "Parse error")
		return
	}

	if req.JSONRPC != "2.0" {
		s.writeError(w, req.ID, RPCInvalidRequest, "jsonrpc must be '2.0'")
		return
	}

	// TODO: Authenticate agent via API key in header
	// Authorization: Bearer mhub_...

	// Route to method handler
	var result any
	var rpcErr *RPCError

	switch req.Method {
	case "initialize":
		result, rpcErr = s.handleInitialize(req.Params)
	case "tools/list":
		result, rpcErr = s.handleToolsList()
	case "tools/call":
		result, rpcErr = s.handleToolCall(req.Params)
	case "resources/list":
		result, rpcErr = s.handleResourcesList()
	case "resources/read":
		result, rpcErr = s.handleResourceRead(req.Params)
	case "prompts/list":
		result, rpcErr = s.handlePromptsList()
	case "prompts/get":
		result, rpcErr = s.handlePromptGet(req.Params)
	default:
		rpcErr = &RPCError{Code: RPCMethodNotFound, Message: "Method not found: " + req.Method}
	}

	resp := &JSONRPCResponse{
		JSONRPC: "2.0",
		ID:      req.ID,
		Result:  result,
		Error:   rpcErr,
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
}

// handleDiscovery returns MCP server capabilities.
// Called by MCP clients during discovery.
func (s *Server) handleDiscovery(w http.ResponseWriter, r *http.Request) {
	// TODO: Return proper MCP discovery response per protocol spec
	capabilities := map[string]any{
		"name":     "memoryHub",
		"version":  s.cfg.System.Version,
		"protocol": s.cfg.MCPServer.Protocol.Version,
		"capabilities": map[string]bool{
			"tools":     true,
			"resources": true,
			"prompts":   true,
		},
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(capabilities)
}

// handleEvents serves Server-Sent Events stream for agent notifications.
// See ARCHITECTURE.md §4.5 (streaming protocol).
func (s *Server) handleEvents(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")

	// TODO: Authenticate agent
	// TODO: Create SSE session in session manager
	// TODO: Stream events: health updates, memory approved notifications, conflict alerts

	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "SSE not supported", http.StatusInternalServerError)
		return
	}

	// TODO: Replace with real event loop
	fmt.Fprintf(w, "data: {\"type\":\"connected\",\"message\":\"TODO: implement SSE\"}\n\n")
	flusher.Flush()

	// Wait for client disconnect
	<-r.Context().Done()
}

// ─────────────────────────────────────────────────────────────────────────
// MCP Method Handlers
// See mcp/tools.go for tool implementations
// ─────────────────────────────────────────────────────────────────────────

func (s *Server) handleInitialize(params json.RawMessage) (any, *RPCError) {
	// TODO: Parse client capabilities
	// TODO: Register agent session
	// TODO: Return server capabilities
	return map[string]any{
		"protocolVersion": s.cfg.MCPServer.Protocol.Version,
		"serverInfo": map[string]string{
			"name":    "memoryHub",
			"version": s.cfg.System.Version,
		},
		"capabilities": map[string]any{
			"tools":     map[string]bool{"listChanged": false},
			"resources": map[string]bool{"subscribe": true},
			"prompts":   map[string]bool{"listChanged": false},
		},
	}, nil
}

func (s *Server) handleToolsList() (any, *RPCError) {
	// See mcp/tools.go for tool definitions
	return GetToolDefinitions(), nil
}

func (s *Server) handleToolCall(params json.RawMessage) (any, *RPCError) {
	// See mcp/tools.go for tool call routing
	return ExecuteTool(params)
}

func (s *Server) handleResourcesList() (any, *RPCError) {
	// See mcp/resources.go
	return GetResourceDefinitions(), nil
}

func (s *Server) handleResourceRead(params json.RawMessage) (any, *RPCError) {
	// See mcp/resources.go
	return ReadResource(params)
}

func (s *Server) handlePromptsList() (any, *RPCError) {
	// TODO: Return available prompts
	return map[string]any{"prompts": []any{}}, nil
}

func (s *Server) handlePromptGet(params json.RawMessage) (any, *RPCError) {
	// TODO: Return prompt template
	return nil, &RPCError{Code: RPCMethodNotFound, Message: "TODO: prompts not implemented"}
}

func (s *Server) writeError(w http.ResponseWriter, id any, code int, message string) {
	resp := &JSONRPCResponse{
		JSONRPC: "2.0",
		ID:      id,
		Error:   &RPCError{Code: code, Message: message},
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
}
