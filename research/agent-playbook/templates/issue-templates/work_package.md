# Work Package Template

> **Instructions**: Use this template when breaking large projects into parallelizable work packages for multiple agents.

---

# Work Package: [Component/Feature Name]

**Package ID**: [e.g., WP-01, WP-02]  
**Status**: [Not Started / In Progress / Under Review / Complete]  
**Assigned Agent**: [Agent identifier or "Unassigned"]  
**Dependencies**: [List other work packages this depends on, or "None"]  
**Blocks**: [List work packages waiting for this, or "None"]

## Overview

[2-3 sentence description of what this work package delivers]

## Goals

This work package is complete when:
- [Specific deliverable 1]
- [Specific deliverable 2]
- [Specific deliverable 3]

## Scope

### In Scope
- [What IS part of this package]
- [What IS part of this package]

### Explicitly Out of Scope
- [What is NOT part of this package - prevents overlap with other packages]
- [What is NOT part of this package]

## Architecture Context

### This Component's Role
[Describe where this fits in overall system architecture]

### Key Responsibilities
- [Responsibility 1]
- [Responsibility 2]

### Boundaries
**This component MUST NOT**:
- [What this component shouldn't do - preserve boundaries]
- [What this component shouldn't do]

**Integration Points**:
- Depends on: [Other components this uses]
- Used by: [Other components that will use this]
- Interfaces: [Ports, APIs, or contracts with other components]

## Technical Specification

### Data Models

```[language]
# Define key data structures/models this package introduces

class [ClassName]:
    [field]: [type]  # [description]
    [field]: [type]  # [description]
```

### Public Interface

> Define the contract other components will use

```[language]
# Core methods/functions this component exposes

def [function_name]([params]) -> [return_type]:
    """[Description of what this does]"""
    
class [ClassName]:
    def [method]([params]) -> [return_type]:
        """[Description]"""
```

### Internal Structure

> Suggested organization, not mandatory

```
[component_name]/
├── models/          # Data models
├── services/        # Business logic
├── ports/           # Interfaces to external systems
├── [other dirs]/
└── tests/           # Test files
```

## Dependencies

### External Dependencies
- [Package/library name] [version] — [why needed]

### Internal Dependencies
- [Work Package ID] — [what's needed from it]
- [Work Package ID] — [what's needed from it]

**Note**: If dependencies not yet complete, implement against mock/stub interfaces.

## Testing Requirements

### Unit Tests Required
- [ ] [Model/class name] — core functionality
- [ ] [Service/function name] — business logic
- [ ] [Component] — edge cases and error handling

### Integration Tests Required
- [ ] [Integration scenario 1]
- [ ] [Integration scenario 2]

### Test Strategy
- Use [in-memory/mock] implementation for dependencies
- Don't require external services (databases, APIs) for tests
- Provide test fixtures: [describe key test data needed]

## Definition of Done

This work package is complete when:

**Code Complete**:
- [ ] All models defined with schema versioning
- [ ] Public interface implemented
- [ ] Core business logic working
- [ ] Error handling in place

**Testing**:
- [ ] Unit tests pass (>80% coverage for core logic)
- [ ] Integration tests pass (if dependencies available)
- [ ] Runs locally without external services

**Documentation**:
- [ ] Component README with:
  - [ ] Overview and responsibilities
  - [ ] Public API documentation
  - [ ] Usage examples
  - [ ] How to run tests
- [ ] Architecture docs updated if needed

**Standards Compliance**:
- [ ] Uses canonical terminology from DEVELOPMENT_STANDARD.md
- [ ] Follows naming conventions
- [ ] Respects architecture boundaries
- [ ] Includes schema versioning

**Demo**:
- [ ] CLI/API command to demonstrate functionality
- [ ] Example usage output in PR
- [ ] Test output showing passing tests

## Implementation Notes

### Recommended Approach
[High-level implementation guidance, if any]

### Key Decisions
- **Decision**: [Important design decision]
  - **Rationale**: [Why this approach]
  - **Alternatives considered**: [What else was considered]

### Patterns to Follow
- See [existing component] for similar pattern
- Follow [pattern name] documented in DEVELOPMENT_STANDARD.md § [section]

### Common Pitfalls
- ⚠️ [Common mistake to avoid]
- ⚠️ [Another pitfall specific to this package]

## Integration Plan

### How This Will Integrate with Other Packages

**With [Work Package ID]**:
- Integration point: [Interface, shared model, etc.]
- Integration testing: [When and how to test together]

**With [Work Package ID]**:
- [Same structure]

### Integration Timeline
1. [Week/Phase 1]: [This package] standalone complete
2. [Week/Phase 2]: Integrate with [other package]
3. [Week/Phase 3]: Full system integration

## References

- Architecture doc: [link to ARCHITECTURE.md section]
- Related ADRs: [link to architectural decisions]
- Similar component: [link to existing code as example]
- Standards: DEVELOPMENT_STANDARD.md [relevant sections]

## Questions & Clarifications

> For agent to ask before/during implementation

[Leave blank for agent to fill in as questions arise]

## Progress Tracking

> Update as work progresses

**Started**: [date]  
**Last Updated**: [date]  
**Completion**: [percentage or milestone]

**Blockers**:
- [Current blocker 1]
- [Current blocker 2]

**Next Steps**:
- [ ] [Next task]
- [ ] [Next task]

---

**For Agents**: Read this entire spec before starting. Clarify questions before implementing. Stay within defined scope. Update progress section as you work.
