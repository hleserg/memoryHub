# Pattern: Context Handoff

**Category**: Coordination  
**Complexity**: Medium  
**Impact**: Medium

## Context

AI agents are stateless between sessions. Unlike human developers who accumulate project knowledge over time, agents start fresh each time they're invoked. This creates challenges:

- **Knowledge loss**: Previous agent's understanding doesn't transfer
- **Repeated discovery**: New agent wastes time relearning the codebase
- **Inconsistent decisions**: Different agents may make conflicting choices
- **Integration issues**: Agent doesn't know what other agents are doing

This is especially problematic when:
- Multiple agents work on related components
- One agent takes over work from another
- Long-running projects span multiple agent sessions
- Complex architecture requires system-level understanding

## Problem

How do you:
1. Transfer context efficiently between agents (or agent sessions)
2. Preserve architectural decisions and rationale
3. Prevent redundant exploration of the codebase
4. Ensure consistent understanding across agents
5. Minimize "context loading" overhead

Without creating massive documents that agents can't effectively process?

## Solution

Implement **structured, layered context documents** that agents can reference on-demand, rather than frontloading everything.

### Context Layers

```
Layer 0: Quick Start (AGENTS.md)
    ↓
Layer 1: Standards (DEVELOPMENT_STANDARD.md)
    ↓
Layer 2: Architecture (ARCHITECTURE.md, ADRs)
    ↓
Layer 3: Component Context (per-module docs)
    ↓
Layer 4: Current State (work-in-progress docs)
```

Agents load only the layers relevant to their task.

## Implementation

### Layer 0: Quick Start (AGENTS.md)

**Purpose**: Minimum viable context to start work

**Contents**:
- What is this project
- Current stage (prototype, development, production)
- How to build/test/run
- Where to find more information

**Size**: 1-2 pages

**Example**:
```markdown
# AGENTS.md

## Project
[Name] — [one-line description]

## Current Stage
Prototype — documentation only, no code yet

## Key Documents
- Architecture: `docs/ARCHITECTURE.md`
- Standards: `docs/DEVELOPMENT_STANDARD.md`
- Work Packages: `docs/work-packages/`

## How to Work
1. Read issue description completely
2. Check relevant work package spec if exists
3. Follow standards in DEVELOPMENT_STANDARD.md
4. Create PR with tests and demo
```

### Layer 1: Standards (DEVELOPMENT_STANDARD.md)

**Purpose**: Canonical terminology and patterns

**Contents**:
- Domain glossary
- Naming conventions
- Architecture boundaries
- Forbidden patterns
- Definition of done

**Size**: 5-20 pages

**Reference Pattern**: Agents read specific sections on-demand
```markdown
"For naming conventions, see DEVELOPMENT_STANDARD.md § 8"
```

### Layer 2: Architecture (ARCHITECTURE.md, ADRs)

**Purpose**: System design and decisions

**Contents**:
- Component overview
- Data flow
- Integration points
- Key decisions (ADRs)
- Technology choices

**Size**: 10-50 pages

**Organization**:
```markdown
# ARCHITECTURE.md

## Overview
[High-level architecture]

## Components
- [Component A](./components/A.md)
- [Component B](./components/B.md)

## Decisions
- [ADR-001: Storage Layer](./adr/001-storage.md)
- [ADR-002: API Design](./adr/002-api.md)
```

**Reference Pattern**: Link to specific ADRs in issues
```markdown
"Follow the adapter pattern defined in ADR-003"
```

### Layer 3: Component Context

**Purpose**: Detailed component-specific information

**Contents** (per component):
- Responsibility and boundaries
- Public interfaces
- Dependencies
- Implementation notes
- Testing strategy

**Location**: `docs/components/[component-name].md` or README in component directory

**Example**:
```markdown
# Component: Order Service

## Responsibility
Process and manage customer orders through their lifecycle.

## Public Interface
- `create_order(order_data: OrderData) -> Order`
- `query_orders(query: OrderQuery) -> List[Order]`
- `update_order_status(order_id: str, status: OrderStatus) -> Order`

## Dependencies
- Core: `models.Order`, `models.OrderStatus`
- Adapter: `PaymentGateway` (for payment processing)
- Adapter: `InventoryBackend` (for stock management)

## Key Constraints
- Orders are immutable once confirmed
- Status transitions must follow defined workflow
- Must preserve complete audit trail

## Testing
- Unit tests: `tests/order_service_test.py`
- Integration: Uses `MockPaymentGateway` for tests
```

### Layer 4: Current State

**Purpose**: Work-in-progress context and coordination

**Contents**:
- Active branches and owners
- Integration status
- Known issues/blockers
- Temporary decisions
- Cross-component TODOs

**Location**: `docs/CURRENT_STATE.md` or project board

**Example**:
```markdown
# Current State (Updated: 2026-04-30)

## Active Work

### Agent 1: Memory Adapter
- Branch: `agent/memory-adapter`
- Status: PR open, awaiting review
- Blocks: None

### Agent 2: Experience Store
- Branch: `agent/experience-store`
- Status: Implementation phase
- Blocks: Needs MemoryBackend interface (Agent 1)

## Integration Notes
- Agent 1 and Agent 2 will integrate via `MemoryBackend` interface
- Target integration: Next week
- Test plan: See `docs/integration-test-plan.md`

## Known Issues
- [ ] Term "memory_record" vs "fact" inconsistency — to be resolved in standards
```

**Update Cadence**: Daily or per-PR

## Context Handoff Patterns

### Pattern 1: Sequential Work (Same Component)

**Scenario**: Agent B continues what Agent A started

**Handoff Document**:
```markdown
# Handoff: Order Service Component

## What's Complete
- [x] Core data models
- [x] In-memory storage backend
- [x] Unit tests for models

## What's Incomplete
- [ ] Database persistence layer
- [ ] Query optimization
- [ ] Integration tests

## Key Decisions Made
- Orders are immutable after confirmation (see ADR-007)
- Using schema_version for all records
- Status transitions follow state machine pattern

## Known Issues
- Performance degrades with >10k orders (optimization planned)
- Database backend needs transaction support

## Next Steps
1. Implement DatabaseBackend (see `storage/db_backend.py` stub)
2. Add integration tests with both backends
3. Performance test with 100k orders

## Context Documents
- Architecture: `docs/ARCHITECTURE.md § Order Service`
- Standards: `DEVELOPMENT_STANDARD.md § Storage Boundaries`
- Related PR: #123
```

### Pattern 2: Parallel Work (Different Components)

**Scenario**: Agents A and B work on components that must integrate

**Coordination Document**:
```markdown
# Integration: Payment Gateway ↔ Order Service

## Shared Interface
```python
class PaymentGateway(ABC):
    @abstractmethod
    def process_payment(self, payment: PaymentRequest) -> PaymentResult:
        pass
    
    @abstractmethod
    def refund_payment(self, transaction_id: str) -> RefundResult:
        pass
```

## Contract
- Payment Gateway (Agent 1) provides implementation
- Order Service (Agent 2) uses interface
- Integration point: `core/ports/payment_gateway.py`

## Assumptions
- Both agents use the canonical data models in `core/models/`
- Payments follow the Payment API spec in `core/payment_api.py`
- Error handling: raises `PaymentGatewayError` subclasses

## Integration Test Plan
1. Payment Gateway completes first
2. Order Service tests against mock gateway
3. Integration test uses real Payment Gateway
4. See: `tests/integration/payment_order_test.py`

## Status
- [ ] Interface defined (blocked on API specification)
- [ ] Payment Gateway implementation (Agent 1, in progress)
- [ ] Order Service implementation (Agent 2, in progress)
- [ ] Integration test (after both complete)
```

### Pattern 3: Agent Restarting Work

**Scenario**: Same agent, new session, continuing previous work

**Self-Handoff** (at end of session):
```markdown
# Session Summary: 2026-04-30

## Completed This Session
- Implemented DatabaseBackend class
- Added basic CRUD operations
- Started test suite

## Current State
- Code: `storage/db_backend.py` (85% complete)
- Tests: `tests/storage/db_backend_test.py` (40% complete)
- Branch: `agent/db-backend`

## Next Session TODO
1. Finish test coverage (especially error cases)
2. Implement transaction support with rollback
3. Add connection pooling for performance
4. Performance test

## Open Questions
- Should we use SQLAlchemy ORM or raw SQL?
  (Leaning toward ORM for maintainability)
- Connection pool size configuration?
  (Maybe start with 10, make configurable?)

## Context to Reload
- Storage boundaries: DEVELOPMENT_STANDARD.md § 11
- Transaction patterns: ADR-009
- Similar implementation: `storage/in_memory_backend.py`
```

## Anti-Patterns

❌ **Massive monolithic context**
- Dumping entire system design into one 100-page document
- Agent must read everything before starting
- ✅ Fix: Layered, on-demand reference

❌ **Implicit knowledge**
- Assuming agents remember previous sessions
- Not documenting architectural decisions
- ✅ Fix: Write everything down, link explicitly

❌ **Stale documentation**
- Context docs not updated as work progresses
- Agent reads outdated information
- ✅ Fix: Update docs as part of PR process

❌ **Over-specification**
- Documenting trivial details
- Prescribing implementation too rigidly
- ✅ Fix: Document "what" and "why", let agent choose "how"

❌ **No single source of truth**
- Same information in multiple places
- Conflicting documentation
- ✅ Fix: One canonical location per topic, others link to it

## Benefits

✅ **Faster onboarding**: Agents start work quickly with right context  
✅ **Consistency**: All agents reference same architectural decisions  
✅ **Reduced rework**: Fewer misunderstandings and wrong assumptions  
✅ **Better integration**: Agents aware of each other's work  
✅ **Knowledge preservation**: Decisions and rationale captured  

## Implementation Guide

### Phase 1: Minimal Docs

1. Create AGENTS.md (quick start)
2. Create DEVELOPMENT_STANDARD.md (terminology)
3. Reference these in all issues

### Phase 2: Architecture Docs

1. Document high-level architecture
2. Create ADRs for key decisions
3. Add component-level docs for complex modules

### Phase 3: Active Coordination

1. Add CURRENT_STATE.md for parallel work
2. Create handoff documents between agents
3. Maintain integration plans

### Phase 4: Self-Service

1. Structure docs for easy navigation
2. Cross-link related documents
3. Add search/index if needed
4. Keep docs up-to-date automatically

## Best Practices

### For Writing Context Docs

1. **Start with TLDR**: Key points at the top
2. **Link, don't duplicate**: Reference other docs
3. **Use examples**: Show, don't just tell
4. **Keep updated**: Doc updates part of DoD
5. **Version important docs**: Track changes to architecture

### For Referencing Context

1. **Be specific**: Link to section, not just document
   - ❌ "See DEVELOPMENT_STANDARD.md"
   - ✅ "See DEVELOPMENT_STANDARD.md § 8 (Naming Conventions)"

2. **Explain why**: Context for the reference
   - ❌ "Follow ADR-003"
   - ✅ "Use the adapter pattern (ADR-003) to keep core logic independent of mem0"

3. **Provide alternatives**: For new agents
   - "If ADR-003 doesn't make sense, read ARCHITECTURE.md § Ports and Adapters first"

### For Maintaining Context

1. **Update CURRENT_STATE.md daily** during active development
2. **Create handoff docs at end of work package**
3. **Update standards when patterns emerge**
4. **Archive outdated context** to prevent confusion

## Real-World Example

**Project**: Multi-component agent architecture

**Setup**:
- 9 work packages assigned to different agents
- Components must integrate with each other
- Agents work over multiple weeks

**Context Strategy**:

1. **Foundation** (Week 1):
   - AGENTS.md with overview
   - DEVELOPMENT_STANDARD.md with terminology
   - Architecture diagram

2. **Work Packages** (Week 2-4):
   - Each work package spec includes:
     - "Prerequisites" section (read these docs first)
     - "Related Components" (integration points)
     - "Context Documents" (specific ADRs/sections)

3. **Coordination** (Ongoing):
   - CURRENT_STATE.md updated daily
   - Integration documents for cross-component work
   - Handoff docs when agent finishes a component

**Results**:
- Agents rarely asked for clarification
- Consistent terminology across all components
- Integration went smoothly (few surprises)
- New agents onboarded quickly with documented context

## Related Patterns

- [Agent Rules Structure](01-agent-rules-structure.md) — Foundation for context docs
- [Issue-to-PR Workflow](02-issue-to-pr-workflow.md) — Context referenced in issues
- [Strategic Review](03-strategic-review.md) — Validates context accuracy

## Tools

- **Documentation as Code**: Markdown in repo
- **ADR Tools**: Decision record management
- **Wiki Links**: Cross-reference between docs
- **Diagrams**: Mermaid, PlantUML for architecture
- **Auto-generated**: API docs, dependency graphs

---

**Status**: Stable  
**Last Updated**: 2026-04-30
