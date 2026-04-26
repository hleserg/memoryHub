// api/main.go
// memoryHub API Server — entrypoint.
// Initializes config, DB, and starts Gin HTTP server.
// See ARCHITECTURE.md §4.1 API Hub (port 3000)
//
// Quick start:
//   go run api/main.go --config config/memoryhub.config.yaml
//
// Or via Makefile:
//   make run

package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/memoryhub/memoryhub/api/handlers"
	"github.com/memoryhub/memoryhub/api/middleware"
	"github.com/memoryhub/memoryhub/config"
)

func main() {
	// ── CLI flags ──────────────────────────────────────────────────────────
	configPath := flag.String("config", "config/memoryhub.config.yaml", "Path to config file")
	flag.Parse()

	// ── Load config ────────────────────────────────────────────────────────
	cfg, err := config.Load(*configPath)
	if err != nil {
		log.Fatalf("Failed to load config: %v", err)
	}

	fmt.Printf("memoryHub %s starting [%s]\n", cfg.System.Version, cfg.System.Environment)

	// ── Gin mode ───────────────────────────────────────────────────────────
	if cfg.System.Environment == "production" {
		gin.SetMode(gin.ReleaseMode)
	}

	// ── Initialize dependencies ────────────────────────────────────────────
	// TODO: Initialize SQLite connection pool
	// db, err := database.New(cfg.Storage.SQLite)

	// TODO: Initialize KuzuDB (Knowledge Graph)
	// graph, err := graph.New(cfg.KnowledgeGraph)

	// TODO: Initialize Trust Pipeline workers
	// trustPipeline, err := trust.NewPipeline(cfg.Trust, db, graph)

	// TODO: Initialize Embeddings provider (for semantic search)
	// embeddings, err := embeddings.New(cfg.Storage.Embeddings)

	// ── Build router ───────────────────────────────────────────────────────
	router := buildRouter(cfg)

	// ── Start server ───────────────────────────────────────────────────────
	addr := fmt.Sprintf("%s:%d", cfg.APIHub.Host, cfg.APIHub.Port)
	srv := &http.Server{
		Addr:         addr,
		Handler:      router,
		ReadTimeout:  30 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  120 * time.Second,
	}

	// Graceful shutdown
	go func() {
		fmt.Printf("API Hub listening on http://%s\n", addr)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("Server error: %v", err)
		}
	}()

	// Wait for interrupt signal
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	fmt.Println("Shutting down gracefully...")
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	if err := srv.Shutdown(ctx); err != nil {
		log.Printf("Shutdown error: %v", err)
	}

	fmt.Println("memoryHub stopped.")
}

// buildRouter sets up all routes with middleware.
// See ARCHITECTURE.md §4.1 "Эндпоинты API Hub" and §13 Interface specifications.
func buildRouter(cfg *config.Config) *gin.Engine {
	r := gin.New()

	// ── Global middleware ──────────────────────────────────────────────────
	r.Use(gin.Recovery())
	r.Use(middleware.Logger())    // Request/response logging
	r.Use(middleware.CORS(cfg))   // CORS headers
	r.Use(middleware.RequestID()) // Attach X-Request-ID to every request

	// ── Health (no auth required) ──────────────────────────────────────────
	// GET /v1/health — Simple liveness check
	// GET /v1/status — Full system status
	// See ARCHITECTURE.md §4.1 Endpoints
	h := handlers.NewHealthHandler(cfg)
	r.GET("/v1/health", h.Health)
	r.GET("/v1/status", h.Status)

	// ── Authenticated routes ───────────────────────────────────────────────
	// All routes below require Bearer token auth + rate limiting.
	// See ARCHITECTURE.md §4.1 Auth & Permissions Matrix
	auth := r.Group("/v1")
	auth.Use(middleware.Auth(cfg))      // Bearer token validation
	auth.Use(middleware.RateLimit(cfg)) // Per-agent rate limiting

	// Memory CRUD
	// See ARCHITECTURE.md §6 Data Flow: Agent → API Hub → Trust Pipeline
	mem := handlers.NewMemoryHandler(cfg)
	auth.POST("/memory", mem.Create)        // Write memory (goes to pending_review)
	auth.GET("/memory/search", mem.Search)  // Semantic + FTS search
	auth.GET("/memory/recent", mem.Recent)  // Recent memories
	auth.GET("/memory/:id", mem.Get)        // Get by ID
	auth.DELETE("/memory/:id", mem.Archive) // Soft-delete (marks as archived)

	// Trust Pipeline
	// See ARCHITECTURE.md §4.3 Human Review Interface
	trust := handlers.NewTrustHandler(cfg)
	auth.GET("/review/queue", trust.Queue)            // View review queue
	auth.POST("/review/:id/approve", trust.Approve)   // Approve a record
	auth.POST("/review/:id/reject", trust.Reject)     // Reject a record
	auth.GET("/quarantine", trust.ListQuarantine)     // View quarantine (admin)
	auth.POST("/quarantine/:id/appeal", trust.Appeal) // Appeal quarantine

	// Knowledge Graph
	// See ARCHITECTURE.md §4.2 Knowledge Graph
	graph := handlers.NewGraphHandler(cfg)
	auth.GET("/graph/entity/:name", graph.GetEntity)    // Get entity by name
	auth.POST("/graph/relations", graph.CreateRelation) // Create relation
	auth.GET("/graph/query", graph.Query)               // Cypher query (read-only)
	auth.GET("/graph/conflicts", graph.ListConflicts)   // List unresolved conflicts
	auth.GET("/graph/snapshot", graph.Snapshot)         // Point-in-time snapshot

	// Agent Metrics
	// See ARCHITECTURE.md §4.7 Agent Metrics Transport
	// auth.POST("/metrics/report", metrics.Report)
	// auth.GET("/metrics/agent/:id", metrics.AgentMetrics)
	// auth.GET("/metrics/summary", metrics.Summary)
	// auth.GET("/metrics/agent/:id/feedback", metrics.AgentFeedback)
	// TODO: Implement metrics handlers (Week 7 per roadmap)

	// API Key Management (admin only)
	// See ARCHITECTURE.md §4.1 API Key Vault
	// auth.POST("/keys", keys.Create)
	// auth.GET("/keys/:id", keys.Get)
	// auth.DELETE("/keys/:id", keys.Revoke)
	// auth.GET("/agents", agents.List)
	// auth.GET("/agents/:id/metrics", agents.Metrics)
	// TODO: Implement key management handlers (Week 1 per roadmap)

	return r
}
