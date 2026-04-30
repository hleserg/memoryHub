# Definition of Done for AI Agents

**Purpose**: Establish clear, measurable completion criteria for agent work to ensure consistent quality and prevent "almost done" ambiguity.

## Why This Matters

AI agents excel at implementation but may have different interpretations of "complete" than humans expect. Without explicit criteria:
- Agents may skip tests, documentation, or edge cases
- Incomplete work gets submitted for review
- Review cycles increase due to missing elements
- Integration issues emerge from untested combinations

Clear Definition of Done (DoD) creates alignment between what agent delivers and what humans need.

## Universal DoD Template

Every agent task should meet these baseline criteria:

```markdown
## Definition of Done
- [ ] **Scope adherence**: Implementation matches issue description exactly
- [ ] **Code complete**: No TODOs, placeholders, or stub implementations
- [ ] **Tests pass**: All existing tests still pass
- [ ] **New tests added**: Changes covered by appropriate tests
- [ ] **Documentation updated**: README, API docs, architecture docs reflect changes
- [ ] **Standards compliant**: Follows project coding standards and naming conventions
- [ ] **Error handling**: Edge cases and error paths considered
- [ ] **No breaking changes**: Or explicitly documented and approved
- [ ] **Demo included**: Evidence that changes work (screenshots, logs, test output)
- [ ] **Clean commit**: No debug code, commented-out sections, or temporary hacks
```

## Component-Specific DoD

Extend the universal template based on task type:

### Feature Implementation

```markdown
- [ ] Happy path works end-to-end
- [ ] Edge cases handled (null/empty/invalid inputs)
- [ ] Error messages are helpful and consistent
- [ ] Performance acceptable (no obvious bottlenecks)
- [ ] Security considerations addressed (input validation, auth, etc.)
- [ ] Feature flag added if needed
- [ ] User-facing documentation updated
- [ ] Backwards compatibility maintained or migration provided
```

### Bug Fix

```markdown
- [ ] Root cause identified and documented
- [ ] Fix addresses root cause, not just symptoms
- [ ] Regression test added to prevent recurrence
- [ ] Related bugs checked (same root cause elsewhere?)
- [ ] Fix verified in environment where bug occurred
- [ ] No side effects in unrelated functionality
```

### Refactoring

```markdown
- [ ] Behavior unchanged (tests prove equivalence)
- [ ] Code complexity reduced (measurable improvement)
- [ ] All call sites updated
- [ ] Deprecation warnings added if breaking old API
- [ ] Performance impact measured (no regression)
- [ ] Documentation explains why refactoring was needed
```

### Documentation

```markdown
- [ ] Accurate (matches current implementation)
- [ ] Complete (covers all important cases)
- [ ] Clear (readable by target audience)
- [ ] Examples provided (working code samples)
- [ ] Links validated (no broken references)
- [ ] Typos corrected
- [ ] Formatting correct (renders properly)
```

### Infrastructure/DevOps

```markdown
- [ ] Works on clean environment (tested from scratch)
- [ ] Idempotent (can run multiple times safely)
- [ ] Error messages guide user to resolution
- [ ] Rollback procedure documented and tested
- [ ] Monitoring/alerting configured if applicable
- [ ] Secrets handled securely (no hardcoded credentials)
- [ ] Resource usage acceptable (CPU, memory, disk)
```

### API Changes

```markdown
- [ ] OpenAPI/Swagger spec updated
- [ ] Request/response examples provided
- [ ] Error responses documented
- [ ] Versioning strategy followed
- [ ] Client library updated if exists
- [ ] Breaking changes communicated and approved
- [ ] Migration guide provided for breaking changes
```

## Testing Requirements by Project Stage

Adjust testing expectations based on project maturity:

### Prototype Stage
```markdown
- [ ] Core functionality demonstrated (manual test acceptable)
- [ ] Major bugs not present
- [ ] Code readable and follows basic structure
```

### Development Stage
```markdown
- [ ] Unit tests for business logic
- [ ] Integration tests for key paths
- [ ] Manual testing of UI changes
- [ ] No known critical bugs
```

### Production Stage
```markdown
- [ ] Comprehensive unit test coverage (>80%)
- [ ] Integration tests for all critical paths
- [ ] E2E tests for user-facing features
- [ ] Performance tests if relevant
- [ ] Security review completed
- [ ] Monitoring/alerting in place
```

## Demo Requirements

Every non-trivial change needs evidence that it works. Format depends on change type:

### Code Changes
- **Unit test output**: Show tests passing
  ```
  ✓ calculates_total_correctly
  ✓ handles_empty_cart
  ✓ applies_discount_when_eligible
  
  Tests: 48 passed, 48 total
  ```

- **Integration test output**: Show system behavior
  ```
  ✓ user_can_checkout
  ✓ payment_processes_successfully
  ✓ confirmation_email_sent
  ```

### UI Changes
- **Screenshot(s)**: Before/after if fixing, or just final state
- **Screen recording**: For interactive features or complex flows
- **Browser console**: No errors in console

### API Changes
- **Curl examples**: Show requests and responses
  ```bash
  curl -X POST /api/users \
    -H "Content-Type: application/json" \
    -d '{"name": "Test User"}'
  
  Response: {"id": 123, "name": "Test User", "created": "2026-04-30T10:00:00Z"}
  ```

### Infrastructure Changes
- **Command output**: Show successful execution
  ```bash
  $ docker-compose up -d
  Creating network "app_default" with the default driver
  Creating app_db_1 ... done
  Creating app_web_1 ... done
  
  $ docker-compose ps
  Name              State    Ports
  app_db_1    Up      5432/tcp
  app_web_1   Up      0.0.0.0:3000->3000/tcp
  ```

### Performance Improvements
- **Benchmarks**: Before and after numbers
  ```
  Before: 2,340ms avg response time
  After:  312ms avg response time
  Improvement: 86.7% faster
  ```

## How to Communicate DoD to Agents

### In Issue Templates

```markdown
## Task
[description of work]

## Definition of Done
- [ ] [specific criterion 1]
- [ ] [specific criterion 2]
- [ ] Tests pass and new tests added
- [ ] Documentation updated
- [ ] Demo/evidence provided in PR
```

### In AGENTS.md

```markdown
## Definition of Done

Every PR must meet these criteria:
- Code complete with no TODOs
- All tests pass
- New tests added for changes
- Documentation updated
- Demo evidence in PR description
- Follows standards in DEVELOPMENT_STANDARD.md
```

### In PR Template

```markdown
## Definition of Done
- [ ] Scope matches issue description
- [ ] Tests pass
- [ ] New tests added
- [ ] Documentation updated
- [ ] Demo/evidence provided below
- [ ] No breaking changes (or documented and approved)
```

## Handling Exceptions

Sometimes DoD criteria don't all apply. Be explicit:

### Example 1: Docs-Only Change
```markdown
## Definition of Done
- [x] Documentation accurate
- [x] Examples working
- [x] Links validated
- [N/A] Tests (documentation change only)
- [N/A] Demo (change is in docs themselves)
```

### Example 2: Experimental Prototype
```markdown
## Definition of Done
- [x] Core concept demonstrated
- [x] Basic functionality working
- [PARTIAL] Tests (unit tests only, integration deferred)
- [DEFERRED] Documentation (will document if experiment succeeds)

Note: This is an experimental feature. Full DoD will apply if promoted to production.
```

### Example 3: Urgent Hotfix
```markdown
## Definition of Done
- [x] Critical bug fixed
- [x] Regression test added
- [x] Deployed and verified in production
- [DEFERRED] Full test suite (added to issue #456)
- [DEFERRED] Documentation update (added to issue #457)

Justification: Production outage, immediate fix required. Follow-up work tracked.
```

**Important**: Always document why criteria are skipped and track follow-up work.

## DoD Anti-Patterns

❌ **Vague criteria**: "Code should be good quality"
- ✅ Fix: "Code follows naming conventions in DEVELOPMENT_STANDARD.md § 8"

❌ **Aspirational goals**: "100% test coverage"
- ✅ Fix: "Critical paths tested, coverage >80%"

❌ **Implicit expectations**: "Agent should know to update docs"
- ✅ Fix: Explicit checklist item

❌ **Moving goalposts**: Adding criteria after agent starts work
- ✅ Fix: Define DoD in issue before assignment

❌ **Checkbox theater**: Checking boxes without actually meeting criteria
- ✅ Fix: Review process validates DoD, not just checkmarks

## Measuring DoD Compliance

Track these metrics to improve DoD effectiveness:

### Per-PR Metrics
- **DoD completeness**: How many items checked vs total
- **First-time pass rate**: PRs that meet DoD without iteration
- **Common gaps**: Which DoD items are frequently missed

### Over Time
- **Trend**: Is first-time pass rate improving?
- **Patterns**: Do certain task types have lower compliance?
- **Agent learning**: Does same agent improve over time?

### Action Items
- **Update DoD**: If criteria are consistently missed, make more explicit
- **Update templates**: Add commonly missed items to templates
- **Improve standards**: If confusion is systematic, clarify documentation

## Example: Complete DoD in Issue

```markdown
# Issue: Implement User Authentication

## Task
Add JWT-based authentication to the API.

## Scope
- Login endpoint (email/password)
- Token generation and validation
- Middleware to protect authenticated routes
- NOT in scope: password reset, OAuth, MFA

## Definition of Done

### Core Functionality
- [ ] POST /auth/login accepts email and password
- [ ] Returns JWT token on successful authentication
- [ ] Returns 401 with clear error on invalid credentials
- [ ] Auth middleware validates tokens on protected routes
- [ ] Tokens expire after 24 hours

### Quality
- [ ] Unit tests for auth service (login, token generation, validation)
- [ ] Integration tests for login endpoint
- [ ] Integration tests for protected route access (with/without token)
- [ ] All existing tests still pass
- [ ] Error handling for edge cases (expired token, malformed token, etc.)

### Documentation
- [ ] API documentation updated with new endpoint
- [ ] Authentication section added to README
- [ ] Environment variables documented (JWT_SECRET, etc.)
- [ ] Example requests/responses provided

### Standards Compliance
- [ ] Follows error response format in DEVELOPMENT_STANDARD.md § 12
- [ ] Uses canonical naming (user_id, not uid)
- [ ] Passwords hashed with bcrypt (as per security standards)
- [ ] Secrets from environment, never hardcoded

### Demo
- [ ] Screenshot of successful login (request + response)
- [ ] Screenshot of rejected login (wrong password)
- [ ] Screenshot of accessing protected route with token
- [ ] Screenshot of rejected access without token
- [ ] Test output showing all tests passing

## References
- Security standards: `docs/security-guidelines.md`
- API conventions: `DEVELOPMENT_STANDARD.md § 12`
- Existing user model: `src/models/user.py`
```

## Related Patterns

- [Issue-to-PR Workflow](../patterns/02-issue-to-pr-workflow.md) — DoD is key part of issue structure
- [Strategic Review](../patterns/03-strategic-review.md) — Validates DoD is appropriate and complete

---

**Status**: Stable  
**Last Updated**: 2026-04-30
