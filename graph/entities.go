// graph/entities.go
// Entity extraction from memory content.
// When a memory is approved and promoted to shared status, this module
// extracts named entities and adds them to the Knowledge Graph.
// See ARCHITECTURE.md §5 Critical Path 1:
//   Trust Pipeline (approved) → Knowledge Graph (extract entities/relations) → shared
//
// TODO (Week 3 per roadmap): Implement entity extraction.

package graph

import (
	"context"
	"fmt"
)

// EntityExtractor extracts named entities from text content.
// Strategy options (configure via embeddings.provider):
//   - "local": regex + heuristics (fast, limited)
//   - "llm": use LLM to extract entities (accurate, slower)
//   - "spacy": via subprocess call to Python spaCy
type EntityExtractor struct {
	client   *Client
	strategy string // "local" | "llm" | "spacy"
	// TODO: inject embeddings client for semantic entity linking
}

// NewEntityExtractor creates a new extractor.
func NewEntityExtractor(client *Client, strategy string) *EntityExtractor {
	return &EntityExtractor{
		client:   client,
		strategy: strategy,
	}
}

// ExtractedEntity is the result of entity extraction from text.
type ExtractedEntity struct {
	Name        string   `json:"name"`
	Type        string   `json:"type"` // person|place|concept|event|thing|agent
	Aliases     []string `json:"aliases"`
	Description string   `json:"description"` // Snippet from source text
	Confidence  float64  `json:"confidence"`
	Mentions    []string `json:"mentions"` // Text spans where entity was found
}

// ExtractEntities analyzes memory content and returns detected entities.
// Called asynchronously after a memory is approved.
// See ARCHITECTURE.md §5 Data Flow diagram.
func (e *EntityExtractor) ExtractEntities(ctx context.Context, content string) ([]ExtractedEntity, error) {
	switch e.strategy {
	case "local":
		return e.extractLocal(content)
	case "llm":
		return e.extractLLM(ctx, content)
	case "spacy":
		return e.extractSpacy(ctx, content)
	default:
		return nil, fmt.Errorf("unknown extraction strategy: %s", e.strategy)
	}
}

// extractLocal uses regex and heuristics for entity extraction.
// Fast but limited — good for bootstrapping.
func (e *EntityExtractor) extractLocal(content string) ([]ExtractedEntity, error) {
	// TODO: Implement basic NER:
	// 1. Capitalized words → potential person/place names
	// 2. Known patterns: dates, URLs, emails, IPs → specific types
	// 3. Known entity dictionary lookups
	// 4. Confidence: 0.3-0.5 (low, heuristic-based)

	var entities []ExtractedEntity
	// TODO: regex-based extraction

	return entities, nil
}

// extractLLM uses an LLM to extract entities with high accuracy.
// Slower but produces structured, typed entities.
func (e *EntityExtractor) extractLLM(ctx context.Context, content string) ([]ExtractedEntity, error) {
	// TODO: Call embeddings/LLM API with extraction prompt:
	// "Extract named entities from the following text. Return JSON array with:
	//  name, type (person|place|concept|event|thing|agent), confidence (0-1)"
	// TODO: Parse JSON response into []ExtractedEntity
	return nil, fmt.Errorf("TODO: LLM entity extraction not implemented")
}

// extractSpacy calls Python spaCy via subprocess for production NER.
func (e *EntityExtractor) extractSpacy(ctx context.Context, content string) ([]ExtractedEntity, error) {
	// TODO: Call spaCy subprocess or HTTP service
	// TODO: Map spaCy entity types to memoryHub EntityType
	return nil, fmt.Errorf("TODO: spaCy entity extraction not implemented")
}

// ProcessMemory is the main entry point called by Trust Pipeline.
// Extracts entities from an approved memory and upserts them into KuzuDB.
// Also creates SUPPORTS relations between memory and entities.
func (e *EntityExtractor) ProcessMemory(ctx context.Context, memoryID, content, sourceAgent string) error {
	entities, err := e.ExtractEntities(ctx, content)
	if err != nil {
		// Non-fatal: log and continue. Entity extraction failure doesn't block memory.
		fmt.Printf("Entity extraction failed for memory %s: %v\n", memoryID, err)
		return nil
	}

	for _, extracted := range entities {
		entity := &Entity{
			ID:          "", // TODO: generate UUID
			Name:        extracted.Name,
			Type:        extracted.Type,
			Aliases:     extracted.Aliases,
			Description: extracted.Description,
			Confidence:  extracted.Confidence,
			SourceAgent: sourceAgent,
		}

		// Upsert entity (create if new, update confidence if exists)
		if err := e.client.UpsertEntity(ctx, entity); err != nil {
			fmt.Printf("Failed to upsert entity %s: %v\n", entity.Name, err)
			continue
		}

		// TODO: Create SUPPORTS relation: entity supports this memory
		// TODO: Create relations between co-mentioned entities (RelationType.RELATED_TO)
		// TODO: Update SQLite memory_entities mapping table
	}

	// TODO: Mark memory.entities_extracted = true in SQLite

	return nil
}
