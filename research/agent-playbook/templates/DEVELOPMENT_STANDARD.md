# Development Standard Template

> **Instructions**: This template helps you create project-specific development standards for AI agents. Fill in sections as they become relevant — you don't need everything on day one. Delete these instruction lines when done.

# Development Standard

_Status: [Draft / Active / Deprecated]_

This document establishes terminology, patterns, and contracts for developing [Project Name]. When multiple agents work on this project, they must use consistent language, architecture boundaries, and implementation patterns.

## Purpose

This standard exists to:
- Ensure all agents use the same terminology for core concepts
- Define clear boundaries between system components
- Prevent common mixings and confusions
- Establish conventions that scale beyond single-agent work

## 1. Core Terminology

> Define domain-specific terms that agents must use consistently.

### [Concept1]

**Definition**: [Clear, unambiguous definition]

**Usage**: [When and how to use this term]

**Example**:
```[language]
# Good
[code example using correct term]

# Wrong
[code example using incorrect term]
```

**Related terms**: [Other terms this relates to, with distinctions]

### [Concept2]

[Same structure as above]

### [More concepts...]

## 2. Forbidden Mixings

> Explicitly state what NOT to conflate. Prevents common conceptual errors.

### [Concept A] ≠ [Concept B]

**Why they're different**: [Explain distinction]

**Correct usage**:
- Use [Concept A] when [context]
- Use [Concept B] when [context]

**Example of confusion**:
```[language]
# Wrong: Mixing concepts
[bad example]

# Correct: Proper separation
[good example]
```

## 3. Architecture Boundaries

> Define structural separations in your codebase.

### Core

**Contains**: [What goes in core — e.g., business logic, domain models]

**Must NOT depend on**: [What core can't import — e.g., specific frameworks, external services]

**Example modules**:
- `[module/path]` — [description]
- `[module/path]` — [description]

### Adapters

**Contains**: [What goes in adapters — e.g., external integrations]

**Can depend on**: [What adapters can import]

**Naming convention**: [e.g., ProviderNameAdapter, ServiceBackend]

### Infrastructure

**Contains**: [What goes in infra — e.g., config, logging, startup]

**Used by**: [What uses infrastructure code]

### Visual Representation

```
┌─────────────────────────────────┐
│         Application             │
│  ┌─────────────────────────┐   │
│  │        Core             │   │
│  │   (domain logic)        │   │
│  └─────────────────────────┘   │
│            │ uses                │
│            ↓                     │
│  ┌─────────────────────────┐   │
│  │        Ports            │   │
│  │    (interfaces)         │   │
│  └─────────────────────────┘   │
│            ↑                     │
│            │ implemented by      │
│  ┌─────────────────────────┐   │
│  │       Adapters          │   │
│  │  (external systems)     │   │
│  └─────────────────────────┘   │
└─────────────────────────────────┘
```

## 4. Naming Conventions

> Establish consistent names for common patterns.

### Modules/Packages

**Pattern**: [e.g., snake_case for Python, kebab-case for JS]

**Preferred names**:
- `[name]` — [purpose]
- `[name]` — [purpose]

**Avoid**:
- `[name]` — [why to avoid]

### Classes/Types

**Pattern**: [e.g., PascalCase]

**Canonical names**:
- `[ClassName]` — [when to use]
- `[ClassName]` — [when to use]

**Suffixes**:
- `[Suffix]` — [meaning, e.g., Service, Repository, Adapter]

### Variables

**Pattern**: [e.g., snake_case, camelCase]

**Preferred names**:
```[language]
user_id          # Good: clear and specific
user_email       # Good: explicit
created_at       # Good: standard timestamp name
```

**Avoid**:
```[language]
uid              # Bad: ambiguous
data             # Bad: too generic
temp             # Bad: unclear purpose
```

### Functions/Methods

**Pattern**: [e.g., verb_noun for actions]

**Examples**:
```[language]
def get_user(user_id)          # Good: clear action
def create_session(params)     # Good: verb + noun
def validate_email(email)      # Good: specific action

def process(data)              # Bad: vague
def do_stuff()                 # Bad: meaningless
```

## 5. Storage Boundaries

> Define what goes where in persistent storage.

### [Storage Type 1]

**Purpose**: [What this stores]

**Contains**: [Data types]

**Access pattern**: [How to read/write]

**Example**:
```[language]
[code showing typical access]
```

### [Storage Type 2]

[Same structure]

## 6. Canonical Object Names

> List the specific names agents must use for key domain objects.

When creating models, use these exact names:

```[language]
[ClassName1]      # [Description]
[ClassName2]      # [Description]
[ClassName3]      # [Description]
```

Don't introduce synonyms like `[alternative_name]` — use the canonical term.

## 7. Error Handling

> Establish patterns for errors.

### Error Types

```[language]
[BaseException]               # Base for all project errors
  ├── [SpecificError1]        # [When to use]
  ├── [SpecificError2]        # [When to use]
  └── [SpecificError3]        # [When to use]
```

### Error Response Format

**For APIs**:
```json
{
  "error": {
    "code": "[ERROR_CODE]",
    "message": "[Human-readable message]",
    "details": { /* optional context */ }
  }
}
```

**For CLI**:
```
Error: [Clear description]
Suggestion: [How to fix it]
```

### Validation

All inputs must be validated:
- [ ] Check for null/None/undefined
- [ ] Validate types
- [ ] Check ranges/lengths
- [ ] Sanitize for security

## 8. Testing Standards

### Test Organization

```
tests/
  ├── unit/            # Isolated component tests
  ├── integration/     # Multi-component tests
  └── [e2e/]          # End-to-end tests (if applicable)
```

### Required Tests

For every new feature:
- [ ] Happy path test
- [ ] Edge case tests (empty, null, max, min)
- [ ] Error case tests (invalid input, failure scenarios)

### Test Naming

```[language]
def test_[action]_[scenario]_[expected_result]():
    # Example: test_create_user_with_valid_data_succeeds()
    # Example: test_divide_by_zero_raises_value_error()
```

### Mocking

**Use mocks for**:
- External services (APIs, databases in unit tests)
- Time-dependent behavior
- Random/non-deterministic behavior

**Don't mock**:
- Your own domain logic (test it directly)
- Trivial functions

## 9. Documentation Requirements

### Code Comments

**Comment the WHY, not the WHAT**:
```[language]
# Good: Explains reasoning
# Use exponential backoff to avoid overwhelming the API
retry_with_backoff(request)

# Bad: States the obvious
# Call retry_with_backoff function
retry_with_backoff(request)
```

### README Updates

Update README when:
- [ ] Adding new features
- [ ] Changing setup/build process
- [ ] Introducing new dependencies
- [ ] Changing environment requirements

### API Documentation

For every public API:
- [ ] Description of purpose
- [ ] Parameter types and meanings
- [ ] Return type and meaning
- [ ] Possible errors
- [ ] Example usage

## 10. Git Conventions

### Branch Naming

```
[type]/[description]
```

**Types**:
- `feature/` — New functionality
- `fix/` — Bug fixes
- `refactor/` — Code restructuring
- `docs/` — Documentation only
- `agent/` — Agent work (if distinguishing from human)

**Examples**:
- `feature/user-authentication`
- `fix/session-timeout-bug`
- `agent/memory-adapter`

### Commit Messages

**Format**:
```
[type]: [short description]

[Optional longer description]
```

**Types**: feat, fix, refactor, docs, test, chore

**Examples**:
```
feat: add JWT authentication to API
fix: prevent session timeout on active users
refactor: extract auth logic into separate service
```

## 11. Definition of Done

Every task is complete only when:

- [ ] Code implements the requirements
- [ ] Tests pass (all existing + new)
- [ ] New tests added for changes
- [ ] Documentation updated
- [ ] Follows naming conventions (§ 4)
- [ ] Respects architecture boundaries (§ 3)
- [ ] Error handling in place (§ 7)
- [ ] No TODOs or debug code left in
- [ ] Demo/evidence provided

## 12. Versioning

### Schema Versioning

All persistent structures must include:
```[language]
schema_version: str  # e.g., "1.0.0"
```

When making breaking changes:
- [ ] Increment version
- [ ] Add migration
- [ ] Update documentation

### API Versioning

[If applicable]
- Versioning strategy: [e.g., URL path, header, etc.]
- Current version: [e.g., v1]
- Deprecation policy: [e.g., 6 months notice]

## 13. Security Guidelines

> Project-specific security requirements.

- [ ] Never commit secrets (API keys, passwords, tokens)
- [ ] Use environment variables for configuration
- [ ] Validate and sanitize all user inputs
- [ ] Use parameterized queries (prevent SQL injection)
- [ ] [Other security requirements]

## 14. Performance Considerations

> If performance is critical, document expectations.

- [ ] Database queries must be indexed
- [ ] API endpoints should respond in <[X]ms for [Y]% of requests
- [ ] Large data sets should be paginated
- [ ] [Other performance requirements]

## 15. Common Pitfalls

> Document common mistakes to avoid.

❌ **Don't**: [Anti-pattern]
✅ **Do**: [Correct pattern]

❌ **Don't**: [Anti-pattern]
✅ **Do**: [Correct pattern]

## 16. Questions and Clarifications

> When agents encounter something not covered here:

If you encounter a scenario not covered by this standard:
1. Make a reasonable decision following the spirit of these guidelines
2. Document your decision in PR description
3. Ask in PR comments if there's genuine ambiguity
4. We'll update this standard based on clarifications

## Appendix: Examples

> Provide complete, working examples of correct patterns.

### [Example 1: Common Task]

```[language]
[Complete code example showing correct implementation]
```

### [Example 2: Another Common Task]

```[language]
[Complete code example]
```

---

**Version**: 1.0  
**Last Updated**: [YYYY-MM-DD]  
**Status**: [Active / Draft]
