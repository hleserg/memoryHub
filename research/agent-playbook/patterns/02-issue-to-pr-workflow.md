# Pattern: Issue-to-PR Workflow

**Category**: Process  
**Complexity**: Low  
**Impact**: High

## Context

You want to delegate development tasks to AI agents but:
- You don't have direct real-time access to agent execution
- You need to maintain oversight and control
- Multiple agents might work in parallel
- You want clear audit trail and review process

Traditional workflows assume developers have IDE access, can ask questions synchronously, and participate in code review discussions. Agent workflows need asynchronous, structured communication.

## Problem

How do you:
1. Assign work to agents without direct communication
2. Provide sufficient context for autonomous completion
3. Review agent work systematically
4. Maintain visibility into what agents are doing
5. Prevent agents from making out-of-scope changes

## Solution

Use GitHub/GitLab as the primary interface for agent task management, with structured issue templates and clear PR expectations.

### Workflow Overview

```
User creates issue → Agent picks up → Agent creates PR → User reviews → Merge or iterate
```

### Detailed Flow

#### 1. Issue Creation (Human)

**Template Structure**:
```markdown
## Context
[Why this work is needed - business/technical motivation]

## Task
[Specific work to be done - actionable and clear]

## Scope
[What's in scope and explicitly what's NOT in scope]

## Definition of Done
- [ ] Specific criterion 1
- [ ] Specific criterion 2
- [ ] Tests pass
- [ ] Documentation updated

## References
- Related issues: #123
- Architecture docs: [link]
- Design decisions: [ADR link]
```

**Key Principles**:
- **Self-contained**: All necessary context in issue body
- **Explicit scope**: Clear boundaries prevent scope creep
- **Measurable success**: Checklist makes completion objective
- **No ambiguity**: Agents should not need to guess intent

#### 2. Agent Assignment

**Option A: Mention**
```
@agent Please implement this according to the specification above.
```

**Option B: Label**
```
Add label: agent-ready
Configure automation to notify agents of new issues
```

#### 3. Agent Execution (Autonomous)

Agent should:
1. **Read the issue carefully** — understand scope and DoD
2. **Check referenced documents** — load relevant context
3. **Create feature branch** — e.g., `agent/feature-name`
4. **Implement changes** — following project standards
5. **Create PR** — linking back to issue
6. **Self-review** — check against Definition of Done
7. **Add demo/evidence** — screenshots, test outputs, etc.

**Agent should NOT**:
- Ask clarifying questions (unless truly blocked)
- Make changes outside stated scope
- Leave work incomplete without explanation
- Skip tests or documentation

#### 4. Pull Request (Agent)

**PR Description Template**:
```markdown
## Closes
Closes #[issue-number]

## Changes Made
- [Specific change 1]
- [Specific change 2]

## Testing
[How changes were tested - output, screenshots, etc.]

## Notes
[Any decisions, trade-offs, or context for reviewers]

## Definition of Done
- [x] Item 1
- [x] Item 2
```

**Critical Elements**:
- Links to originating issue
- Clear description of what changed (not just "implemented feature")
- Evidence of testing
- Explicit DoD checklist verification

#### 5. Review (Human)

**Review Checklist**:
- [ ] Scope adherence — Did agent stay within bounds?
- [ ] Architecture compliance — Follows project standards?
- [ ] System coherence — Does it fit the bigger picture?
- [ ] Test coverage — Adequate for the changes?
- [ ] Documentation — Updated appropriately?
- [ ] No hidden surprises — Unexpected changes explained?

**Review Types**:

**Tactical Review** (always):
- Code correctness
- Test coverage
- Standards compliance

**Strategic Review** (periodic):
- System-level coherence
- Architecture alignment
- Long-term maintainability

See: [Strategic Review Pattern](03-strategic-review.md)

#### 6. Iteration or Merge

**If changes needed**:
```markdown
Please address the following:
1. [Specific issue]
2. [Specific issue]

Reference: [explain why or link to standard]
```

**If approved**:
```bash
Merge PR
Close issue (usually automatic)
```

## Implementation Guide

### Phase 1: Basic Setup

1. **Create issue templates**
   - Feature request
   - Bug report
   - Documentation update

2. **Create PR template**
   - Enforce structured format
   - Include DoD checklist

3. **Document workflow**
   - Add to AGENTS.md or CONTRIBUTING.md
   - Train team on expectations

### Phase 2: Process Refinement

1. **Add automation**
   - Auto-label PRs based on branch name
   - Auto-link issues to PRs
   - Notify relevant stakeholders

2. **Establish SLAs**
   - Agent should respond within X hours
   - Reviews happen within Y hours
   - Clear escalation path

3. **Metrics tracking**
   - Time to first PR
   - Review cycles per PR
   - Scope adherence rate

### Phase 3: Scale

1. **Parallel work coordination**
   - Clear ownership in issues
   - Component boundaries defined
   - Integration testing strategy

2. **Cross-agent patterns**
   - Shared context documents
   - Standard interfaces
   - Communication protocols

## Anti-Patterns

❌ **Vague issues**: "Make the system better"
- ✅ Fix: Specific, measurable tasks

❌ **Missing context**: Assuming agent knows project history
- ✅ Fix: Self-contained issues with references

❌ **Scope creep**: Agent fixes "everything nearby"
- ✅ Fix: Explicit scope boundaries in issue

❌ **No DoD**: Open-ended completion criteria
- ✅ Fix: Clear checklist of what "done" means

❌ **Review as surprise**: Agent didn't know expectations
- ✅ Fix: Standards documented, referenced in issues

❌ **Blocking on questions**: Agent waits for human response
- ✅ Fix: Provide all needed context upfront, or empower agent to make reasonable assumptions

## Benefits

✅ **Asynchronous**: No real-time coordination needed  
✅ **Auditable**: Full history of decisions and changes  
✅ **Scalable**: Works with multiple agents in parallel  
✅ **Familiar**: Uses standard GitHub/GitLab workflows  
✅ **Controllable**: Human approval gates at key points  

## Real-World Example

**Project**: Multi-component architecture with 9 work packages

**Challenge**: Owner manages via GitHub only, no direct agent access

**Solution**:
1. Each work package became an issue with detailed spec
2. Agent assigned via @mention
3. Agent created PR with implementation + tests + demo
4. Owner reviewed for:
   - Scope adherence (did agent solve stated problem?)
   - Architecture fit (does it align with system design?)
   - Standard compliance (uses canonical terminology?)
5. Iteration happened via PR comments
6. Merge after approval

**Results**:
- 7 components developed in parallel
- Clear audit trail of all decisions
- Minimal scope creep
- Human focuses on strategy, not implementation

## Variations

### Lightweight (Solo Developer)
- Skip templates, use ad-hoc issues
- Verbal communication acceptable
- Merge directly without formal review

### Standard (Small Team)
- Issue templates enforced
- PR template required
- One approval required

### Rigorous (Large/Critical Projects)
- Formal issue specification process
- Multiple review stages
- Automated compliance checking
- Required demo/testing evidence

## Related Patterns

- [Agent Rules Structure](01-agent-rules-structure.md) — Standards referenced in issues
- [Strategic Review](03-strategic-review.md) — Review process details
- [Definition of Done](../guides/definition-of-done.md) — What to include in DoD checklists

## Tools

- **GitHub Issues & PRs**: Core workflow
- **GitHub Actions**: Automation for labeling, linking, notifications
- **Linear/Jira**: Alternative issue tracking (with GitHub sync)
- **PR templates**: Enforce structure
- **Issue templates**: Enforce completeness

---

**Status**: Stable  
**Last Updated**: 2026-04-30
