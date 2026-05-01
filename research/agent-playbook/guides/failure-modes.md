# Common Agent Failure Modes

**Purpose**: Recognize and prevent typical issues that arise when AI agents work autonomously on software projects.

## Overview

AI agents are powerful but have predictable failure modes. Recognizing these patterns early allows you to:
- Intervene before problems compound
- Adjust task structure to prevent recurrence
- Improve standards and documentation
- Set better expectations

This guide catalogs real-world failure modes with detection and prevention strategies.

## Category 1: Context and Scope Issues

### 1.1 Context Loss (Lost in the Woods)

**Symptoms**:
- Agent starts optimizing local details, losing sight of original goal
- Makes changes to files outside the scope of the task
- Refactors code that wasn't part of the issue
- Implements features not requested

**Example**:
```
Task: Fix bug where user logout doesn't clear session
Agent: Fixed logout, then refactored entire auth module, added new features, 
       changed database schema, updated 15 unrelated files
```

**Why This Happens**:
- Agent explores codebase and finds "opportunities for improvement"
- No clear scope boundaries in task description
- Agent optimizes locally without system-level constraints

**Detection**:
- PR touches many more files than expected
- Commit history shows "feature creep"
- Agent mentions "also fixed" or "while I was there"

**Prevention**:
✅ **Explicit scope boundaries in issues**
```markdown
## In Scope
- Fix logout endpoint
- Clear session on logout

## Out of Scope
- Auth system refactoring
- Login functionality
- Session storage mechanism
```

✅ **Remind agents to stay focused**
```markdown
Note: This is a targeted bug fix. Please do not refactor unrelated code.
```

✅ **Review PR size early**: If unexpectedly large, ask agent to explain

### 1.2 Tunnel Vision (Missing the Forest)

**Symptoms**:
- Agent implements technically correct solution that breaks overall system
- Ignores architecture boundaries
- Makes changes that work in isolation but fail integration
- Optimizes one component at expense of others

**Example**:
```
Task: Improve database query performance
Agent: Rewrites query to be very fast, but breaks caching layer that 
       depended on specific query structure, overall system slower
```

**Why This Happens**:
- Agent can't hold entire system architecture in working memory
- Focuses on explicit task, misses implicit constraints
- No clear documentation of system invariants

**Detection**:
- Integration tests fail that passed before
- Other components start behaving unexpectedly
- Performance improves locally but degrades globally

**Prevention**:
✅ **Document system constraints in issues**
```markdown
## System Context
- This query is used by caching layer in cache.py
- Current query structure is expected by report generator
- Changes must maintain backward compatibility
```

✅ **Strategic review**: Regular system-level review catches drift

✅ **Integration tests**: Run full test suite, not just unit tests

### 1.3 Assumption Spiral

**Symptoms**:
- Agent makes reasonable but incorrect assumption
- Builds on that assumption, creating complex solution
- Delivers working code that solves wrong problem
- "It works perfectly, but it's not what we needed"

**Example**:
```
Task: Add user export feature
Agent assumption: "Export" means generate PDF report
Reality: User wanted CSV export for data migration
Result: Beautiful PDF generator, but not useful for task at hand
```

**Why This Happens**:
- Ambiguous task description
- Multiple valid interpretations
- Agent picks one and commits without verification

**Detection**:
- PR description reveals misunderstanding
- Demo shows working but unexpected implementation
- Agent's explanation doesn't match your intent

**Prevention**:
✅ **Explicit format/examples in issues**
```markdown
## User Export Feature
Create endpoint that generates CSV file with user data.

Example output format:
id,email,name,created
1,user@example.com,John Doe,2026-01-15
```

✅ **Acceptance criteria with specifics**
```markdown
- [ ] Returns CSV file (not PDF or JSON)
- [ ] Includes columns: id, email, name, created
- [ ] File downloads with content-type: text/csv
```

## Category 2: Implementation Quality Issues

### 2.1 Over-Engineering

**Symptoms**:
- Solution is far more complex than needed
- Adds abstractions, frameworks, or patterns not used elsewhere
- "Future-proofs" for scenarios that may never happen
- Code is correct but needlessly complicated

**Example**:
```
Task: Add configuration option for theme (light/dark)
Agent: Implements full plugin system, theme marketplace, 
       dynamic theme loading, theme compilation pipeline...
```

**Why This Happens**:
- Agent trained on complex enterprise codebases
- Tries to apply "best practices" without context
- No guidance on project's complexity/simplicity preference

**Detection**:
- Simple task results in large PR
- Many new files, abstractions, interfaces
- Agent explains "extensible architecture"

**Prevention**:
✅ **YAGNI principle in standards**
```markdown
## Complexity Guidelines
- Prefer simple solutions
- Don't add abstractions until third use case
- Match complexity of surrounding code
```

✅ **Scope limitation**
```markdown
## Implementation Notes
Keep it simple. A single config variable is fine. No need for plugin system.
```

### 2.2 Incomplete Error Handling

**Symptoms**:
- Happy path works perfectly
- Edge cases crash or behave unexpectedly
- No validation of inputs
- Generic error messages

**Example**:
```python
def divide(a, b):
    return a / b  # No check for b == 0

def get_user(user_id):
    return db.query(User).filter(id=user_id).first()  # No check if None
```

**Why This Happens**:
- Agent focuses on primary use case
- Error handling not explicitly in DoD
- Tests don't cover edge cases

**Detection**:
- Code review reveals missing checks
- No error handling visible
- Tests only cover happy path

**Prevention**:
✅ **Explicit DoD requirement**
```markdown
- [ ] Input validation (null, empty, invalid)
- [ ] Error cases handled gracefully
- [ ] Helpful error messages
- [ ] Tests include edge cases
```

✅ **Standards document error handling patterns**
```markdown
## Error Handling
- Validate all inputs
- Return descriptive errors
- Use project's error types
- Log errors appropriately
```

### 2.3 Test Theater

**Symptoms**:
- Tests exist but don't actually test anything meaningful
- Tests pass but code is broken
- 100% coverage of trivial code, 0% of critical logic
- Tests tightly coupled to implementation

**Example**:
```python
def test_user_creation():
    user = create_user("test")
    assert user is not None  # Always passes, even if user is wrong
    
def test_calculation():
    result = complex_calculation(input_data)
    assert True  # Literally always passes
```

**Why This Happens**:
- Agent knows tests are required
- Doesn't understand what makes a good test
- Focuses on coverage percentage, not test quality

**Detection**:
- Tests don't fail when code is broken
- Assertions are trivial (assert True, assert not None)
- No negative test cases

**Prevention**:
✅ **Test quality in DoD**
```markdown
- [ ] Tests verify correct behavior (not just "no crash")
- [ ] Tests include negative cases (invalid inputs)
- [ ] Tests would fail if bug is introduced
```

✅ **Provide test examples in standards**
```python
# Good test
def test_division_by_zero():
    with pytest.raises(ValueError, match="Cannot divide by zero"):
        divide(10, 0)

# Bad test
def test_division():
    result = divide(10, 2)
    assert result  # Passes even if result is wrong!
```

## Category 3: Process and Coordination Issues

### 3.1 Debug Loop Trap

**Symptoms**:
- Agent tries fix → tests fail → tries another fix → tests fail → repeat
- Multiple commits with "fix tests" or "try alternative approach"
- No clear progress, just iterations
- Agent doesn't identify root cause

**Example**:
```
Commit 1: "Implement feature"
Commit 2: "Fix test failures"
Commit 3: "Try different approach"
Commit 4: "Fix tests again"
Commit 5: "Revert and try alternative"
...
```

**Why This Happens**:
- Agent doesn't have good debugging strategy
- Guesses rather than investigates
- No instrumentation or logging to understand issue

**Detection**:
- Many commits with no progress
- PR comments show confusion
- Tests still failing in final version

**Intervention**:
✅ **Stop and diagnose**
```markdown
I see you're stuck in a loop. Please:
1. Add detailed logging to understand what's happening
2. Document what you've tried and why it didn't work
3. Identify the root cause before trying more fixes
```

✅ **Use debug subagent** (if available)
```markdown
Let's use the debug agent to identify root cause with instrumentation.
```

**Prevention**:
✅ **Include debugging guidance in AGENTS.md**
```markdown
## When Stuck
1. Add logging to understand behavior
2. Create minimal reproduction case
3. Form hypothesis about root cause
4. Test hypothesis before implementing fix
```

### 3.2 Parallel Work Conflicts

**Symptoms**:
- Agent A and Agent B modify same files
- Merge conflicts that are non-trivial
- Incompatible design decisions
- Integration breaks even though individual PRs worked

**Example**:
```
Agent A: Refactors auth.py to use JWT
Agent B: Simultaneously adds OAuth to auth.py
Result: Merge conflict, incompatible auth mechanisms
```

**Why This Happens**:
- Insufficient coordination
- Unclear ownership boundaries
- No integration planning

**Detection**:
- Git merge conflicts
- CI failures after merge
- Incompatible assumptions

**Prevention**:
✅ **Clear ownership** (see [Environment Isolation](../patterns/04-environment-isolation.md))
```markdown
## Active Work
- Agent A: auth/ directory (JWT implementation)
- Agent B: oauth/ directory (OAuth provider)
- Integration: Week 3 (after both complete)
```

✅ **Interface contracts**
```markdown
## Shared Interface
Both agents must implement this interface:
[interface specification]
```

### 3.3 Documentation Drift

**Symptoms**:
- Code changes but documentation doesn't
- Documentation exists but is wrong
- New features undocumented
- Comments contradict code

**Example**:
```python
# Returns list of active users
def get_users():
    return User.query.all()  # Actually returns all users, not just active
```

**Why This Happens**:
- Agent focuses on code, treats docs as afterthought
- DoD doesn't emphasize documentation importance
- Documentation isn't tested

**Detection**:
- Code review finds discrepancies
- Documentation doesn't match implementation
- Examples in docs don't work

**Prevention**:
✅ **Documentation in DoD**
```markdown
- [ ] README updated if behavior changed
- [ ] API docs accurate
- [ ] Examples tested and working
- [ ] Comments explain "why", not "what"
```

✅ **Validate documentation**
```markdown
Please test the examples in your documentation to ensure they work.
```

## Category 4: Architecture and Design Issues

### 4.1 Boundary Violations

**Symptoms**:
- Core domain logic depends on infrastructure
- Adapters contain business logic
- Circular dependencies
- "Just import it directly" quick fixes

**Example**:
```python
# In core domain logic
from adapters.mem0_backend import Mem0Backend  # Should use port/interface

def process_memory(data):
    backend = Mem0Backend()  # Core shouldn't know about specific adapter
    backend.store(data)
```

**Why This Happens**:
- Agent doesn't understand architecture boundaries
- "Quickest path" violates separation
- Standards not clear about ports and adapters

**Detection**:
- Import analysis shows wrong dependencies
- Core modules importing from adapters/infra
- Strategic review catches violations

**Prevention**:
✅ **Clear architecture documentation**
```markdown
## Architecture Boundaries
- Core: Domain logic, no infrastructure dependencies
- Ports: Interfaces that core uses
- Adapters: Implement ports, depend on external services
- Infra: Config, logging, startup

## Forbidden Dependencies
- Core must NOT import from adapters or infra
- Core must use ports (interfaces) only
```

✅ **Linting rules** (if possible)
```python
# .pylintrc
# Forbidden imports: core should not import from adapters
```

### 4.2 Inconsistent Patterns

**Symptoms**:
- Same problem solved differently in different places
- Agent invents new pattern instead of using existing
- Codebase becomes heterogeneous
- Every module feels like different author

**Example**:
```
Module A: Uses repositories for data access
Module B: Direct database calls
Module C: ORM everywhere
Module D: Raw SQL
```

**Why This Happens**:
- No clear patterns documented
- Different agents don't know what others did
- Agent trained on diverse codebases, picks randomly

**Detection**:
- Code review: "Why not use existing pattern?"
- Multiple ways to do same thing
- Strategic review catches divergence

**Prevention**:
✅ **Document canonical patterns**
````markdown
## Data Access Pattern
Always use repository pattern:

```python
class UserRepository:
    def find(self, user_id): ...
    def save(self, user): ...
```

See: `repositories/user_repository.py` as example
````

✅ **Point to examples in issues**
```markdown
## Implementation Notes
Follow the repository pattern used in user_repository.py
```

## Intervention Strategies

When you detect a failure mode:

### 1. Early Course Correction
```markdown
I see you're [describe pattern]. This is concerning because [impact].
Please [specific corrective action] before continuing.
```

### 2. Provide Missing Context
```markdown
It looks like you might not be aware of [constraint/pattern/decision].
See [document § section] for details on [topic].
Please revise your approach accordingly.
```

### 3. Reset and Reframe
```markdown
Let's take a step back. The core goal is [original goal].
Your current approach [describes issue].
Instead, please [simpler/clearer approach].
```

### 4. Update Standards
```markdown
This confusion suggests our documentation needs improvement.
I'll update [document] to clarify [topic] for future work.
```

## Measuring and Tracking

Track failure modes to improve:

```markdown
## Agent Issues Log

| Date | Agent | Issue | Root Cause | Prevention |
|------|-------|-------|-----------|------------|
| 2026-04-15 | Agent A | Scope creep | Vague issue | Added scope boundaries |
| 2026-04-18 | Agent B | Wrong assumption | Ambiguous task | Added examples |
| 2026-04-22 | Agent C | Boundary violation | Standards unclear | Updated DEVELOPMENT_STANDARD.md |
```

Use this data to:
- Identify recurring patterns
- Improve issue templates
- Enhance documentation
- Set better expectations

## Related Patterns

- [Agent Rules Structure](../patterns/01-agent-rules-structure.md) — Prevention through clear standards
- [Strategic Review](../patterns/03-strategic-review.md) — Detection mechanism
- [Definition of Done](definition-of-done.md) — Quality criteria

---

**Status**: Stable  
**Last Updated**: 2026-04-30
