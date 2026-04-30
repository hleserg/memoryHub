# Pattern: Strategic Review

**Category**: Governance  
**Complexity**: Medium  
**Impact**: High

## Context

AI agents are excellent at implementing specific, well-defined tasks. They can write code, create tests, follow patterns, and complete work packages autonomously. However, agents have inherent limitations:

- **Local optimization bias**: Focus deeply on assigned task, may miss system-level implications
- **Limited context window**: Can't hold entire system architecture in working memory
- **No strategic judgment**: Excel at "how" but need guidance on "whether" and "why"
- **Consistency drift**: Different agents may make conflicting architectural choices

Traditional code review focuses on tactical correctness (does this code work?). Agent-produced code usually passes tactical review but needs strategic oversight.

## Problem

How do you maintain:
1. System-level architectural coherence across multiple agent contributions
2. Consistent design philosophy when agents work independently
3. Balance between agent autonomy and human control
4. Prevention of "locally optimal but globally suboptimal" changes

Without drowning in micro-management or creating review bottlenecks?

## Solution

Implement two-level review process: **Tactical Review** (lightweight, frequent) and **Strategic Review** (heavyweight, periodic).

### Tactical Review (Every PR)

**Focus**: Correctness and compliance

**Questions**:
- ✅ Does the code work as intended?
- ✅ Are tests adequate?
- ✅ Does it follow project standards?
- ✅ Is scope appropriate?
- ✅ Is documentation updated?

**Who**: Can be another agent, automated tools, or junior reviewer

**Time**: Minutes to hours

**Approval**: Required for merge

### Strategic Review (Periodic)

**Focus**: Architecture and coherence

**Questions**:
- 🎯 Does this fit the overall system vision?
- 🎯 Are we building the right abstractions?
- 🎯 Will this be maintainable 6 months from now?
- 🎯 Does this create tech debt or pay it down?
- 🎯 Are different components staying aligned?
- 🎯 Should we course-correct?

**Who**: Human architect, tech lead, or domain expert

**Time**: Hours to days

**Cadence**: Weekly, per-milestone, or per-major-feature

## Detailed Strategic Review Process

### 1. Prepare Review Context

**Gather Information**:
```markdown
## Review Scope
Period: [date range]
Components affected: [list]
PRs included: #123, #124, #125

## Changes Summary
- Component A: [brief description]
- Component B: [brief description]

## Architectural Goals (from design docs)
- [Goal 1]
- [Goal 2]

## Known Risks/Concerns
- [Concern 1]
- [Concern 2]
```

**Documents to Review**:
- Architecture design docs
- Recent merged PRs
- Open discussions/ADRs
- System diagrams

### 2. Review Dimensions

#### Architecture Alignment
- Do implementations match the intended architecture?
- Are abstraction boundaries being respected?
- Is there unintended coupling being introduced?

**Red Flags**:
- Core domain logic depending on infrastructure details
- Blurring of "adapter" and "core" boundaries
- Inconsistent terminology across components

#### System Coherence
- Do different components use compatible patterns?
- Is there a consistent design philosophy?
- Do naming conventions align?

**Red Flags**:
- Same concept with different names in different components
- Conflicting approaches to same problem
- Different agents solving identical problems differently

#### Maintainability
- Will future developers understand this?
- Is complexity justified?
- Are we creating patterns that scale?

**Red Flags**:
- Clever solutions with high cognitive load
- Inconsistent error handling
- Hidden dependencies
- Insufficient documentation of "why"

#### Technical Debt
- Are we accumulating debt consciously?
- Is debt documented and tracked?
- Do we have a paydown plan?

**Red Flags**:
- TODOs without issues/tracking
- Workarounds without explanation
- Temporary solutions becoming permanent

### 3. Review Output

**Document Findings**:
```markdown
## Strategic Review: [Date]

### Reviewed Work
- [Summary of period/components]

### Strengths
- [What's working well]
- [Good patterns to continue]

### Concerns
1. **[Concern Title]**
   - Issue: [description]
   - Impact: [why it matters]
   - Recommendation: [what to do]

### Action Items
- [ ] Issue #XXX: [specific corrective work]
- [ ] Update standard: [what to clarify]
- [ ] Architecture decision needed: [what to decide]

### Course Corrections
- [Any changes to development direction]
- [Updated priorities]
```

**Communication**:
- Share with all agents (add to documentation if applicable)
- Create follow-up issues for corrective work
- Update standards/ADRs as needed

## Implementation Guide

### Phase 1: Establish Baseline

1. **Document architecture vision**
   - Create architecture docs
   - Define key boundaries
   - Establish terminology

2. **Set review cadence**
   - Weekly for active development
   - Per-milestone for stable projects
   - Ad-hoc for major features

3. **Create review template**
   - Standardize review format
   - Make reproducible

### Phase 2: Execute Reviews

1. **Schedule regular sessions**
   - Block time on calendar
   - Don't skip (drift accumulates)

2. **Gather context efficiently**
   - Use GitHub filters for PR lists
   - Automated summaries if possible
   - Focus on significant changes

3. **Document and share findings**
   - Always write it down
   - Make visible to agents
   - Update standards proactively

### Phase 3: Close the Loop

1. **Track corrective actions**
   - Create issues for problems
   - Assign to appropriate agents
   - Follow up on completion

2. **Measure effectiveness**
   - Fewer architectural issues over time?
   - Faster convergence to patterns?
   - Less rework needed?

3. **Evolve the process**
   - Adjust cadence based on needs
   - Refine review questions
   - Improve documentation

## Anti-Patterns

❌ **Micro-managing in the name of strategy**
- Don't review every line of code strategically
- Trust tactical review for most decisions
- Focus on patterns, not instances

❌ **Infrequent reviews**
- Letting drift accumulate for months
- Waiting until "everything is done"
- ✅ Fix: Regular cadence, even if brief

❌ **Review without action**
- Identifying problems but not fixing them
- Not updating standards based on findings
- ✅ Fix: Always create follow-up issues

❌ **Implicit standards**
- Expecting agents to infer architectural principles
- Not documenting review findings
- ✅ Fix: Make everything explicit in docs

❌ **Review theater**
- Going through motions without deep thought
- Approving everything to avoid conflict
- ✅ Fix: Take it seriously; it's the most important human role

## Benefits

✅ **Prevents drift**: Catches architectural issues early  
✅ **Maintains coherence**: System stays aligned despite parallel work  
✅ **Enables autonomy**: Agents work freely within guardrails  
✅ **Builds quality**: Proactive rather than reactive  
✅ **Scales**: One reviewer can oversee many agents  

## Real-World Example

**Project**: 7-component agent architecture

**Setup**:
- 9 work packages assigned to agents
- Each agent working autonomously
- Weekly strategic review

**Week 3 Review Findings**:

**Problem Identified**: Three agents used different terms for same concept
- Component A: "memory_item"
- Component B: "fact_record"  
- Component C: "memory_entry"

**Impact**: Future integration would be confusing, components wouldn't align

**Action Taken**:
1. Updated DEVELOPMENT_STANDARD.md with canonical term: "FactRecord"
2. Created issues for each agent to refactor their code
3. Added "forbidden synonyms" section to prevent recurrence

**Result**: All components now use consistent terminology, integration is straightforward

## Review Questions Checklist

Use this during strategic reviews:

### Architecture
- [ ] Are abstraction boundaries being respected?
- [ ] Is coupling minimal and intentional?
- [ ] Do components have clear responsibilities?
- [ ] Are we building the right interfaces?

### Standards
- [ ] Is terminology consistent across components?
- [ ] Are naming conventions being followed?
- [ ] Are architectural patterns being reused?
- [ ] Are forbidden mixings being avoided?

### Quality
- [ ] Is complexity justified?
- [ ] Is code self-documenting?
- [ ] Are error paths considered?
- [ ] Is testing adequate?

### Sustainability
- [ ] Will this be maintainable?
- [ ] Is technical debt tracked?
- [ ] Are decisions documented?
- [ ] Can new developers understand this?

### Progress
- [ ] Are we on track architecturally?
- [ ] Do we need to course-correct?
- [ ] Should priorities change?
- [ ] Are agents blocked on decisions?

## Variations

### Lightweight (Solo + One Agent)
- Monthly review of significant changes
- Focus on preventing bad patterns from solidifying
- Informal documentation

### Standard (Small Team + Multiple Agents)
- Weekly or bi-weekly reviews
- Documented findings shared with team
- Follow-up issues for corrections

### Rigorous (Large Project + Many Agents)
- Multiple review levels (component, system, cross-cutting)
- Dedicated architect role
- Formal ADR process
- Automated architectural fitness functions

## Related Patterns

- [Agent Rules Structure](01-agent-rules-structure.md) — Standards that reviews validate
- [Issue-to-PR Workflow](02-issue-to-pr-workflow.md) — Tactical review process
- [Common Failure Modes](../guides/failure-modes.md) — What to watch for

## Tools

- **GitHub PR Views**: Filter PRs by time period, component, agent
- **Architecture Diagrams**: Visual coherence checking
- **ADR Tools**: Decision documentation
- **Linting**: Automated standards checking
- **Dependency Graphs**: Coupling analysis

---

**Status**: Stable  
**Last Updated**: 2026-04-30
