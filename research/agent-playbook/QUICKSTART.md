# Quick Start Guide

Get started with agent-driven development in 15 minutes.

## Overview

This guide will help you set up your project for AI agent collaboration using the patterns from this playbook.

## Step 1: Create AGENTS.md (5 minutes)

Create `AGENTS.md` in your repository root using [this template](templates/AGENTS.md).

**Minimum viable content**:
````markdown
# AGENTS.md

## Overview
[Your project name] — [one-line description]

## Current Stage
[Prototype / Development / Production]

## Repository Structure
- `src/` — [description]
- `docs/` — [description]

## How to Build and Test
```bash
npm install  # or your build command
npm test     # or your test command
```

## Key Documents
- Standards: DEVELOPMENT_STANDARD.md
````

**Time check**: You should have a basic AGENTS.md now.

## Step 2: Create Issue Template (5 minutes)

Create `.github/ISSUE_TEMPLATE/feature_request.md` using [this template](templates/issue-templates/feature_request.md).

**Key sections to customize**:
- Remove instruction comments
- Adjust DoD checklist for your project
- Add project-specific labels if needed

**Test it**: Create a test issue using your template. Does it have all the context an agent would need?

## Step 3: Create PR Template (3 minutes)

Create `.github/pull_request_template.md` using [this template](templates/pr-template.md).

**Customize**:
- Adjust DoD checklist to match your project
- Add/remove sections based on your needs

## Step 4: First Agent Task (2 minutes)

Create your first agent-ready issue:

```markdown
# Issue: [Your First Task]

## Context
[Why this task exists]

## Task
[Clear, specific work to be done]

## Scope
### In Scope
- [Specific item 1]
- [Specific item 2]

### Out of Scope
- [What NOT to do]

## Definition of Done
- [ ] [Criterion 1]
- [ ] [Criterion 2]
- [ ] Tests pass
- [ ] Demo provided

## References
- See AGENTS.md for build/test commands
```

Tag an agent: `@agent Please implement this according to the specification above.`

## What You've Accomplished

✅ **Agent context**: Agents know about your project (AGENTS.md)  
✅ **Task structure**: Issues provide complete context  
✅ **Review structure**: PRs have consistent format  
✅ **Clear expectations**: DoD prevents ambiguity  

## Next Steps

### If things go well:
- Read [Agent Rules Structure](patterns/01-agent-rules-structure.md) for deeper understanding
- Add DEVELOPMENT_STANDARD.md when you need consistent terminology (use [template](templates/DEVELOPMENT_STANDARD.md))

### If you have multiple agents working in parallel:
- Read [Environment Isolation](patterns/04-environment-isolation.md)
- Read [Context Handoff](patterns/05-context-handoff.md)
- Consider work packages for larger features

### If agent work needs improvement:
- Read [Common Failure Modes](guides/failure-modes.md) to recognize issues early
- Implement [Strategic Review](patterns/03-strategic-review.md) process

## Common First-Time Issues

### Issue: Agent asks too many clarifying questions
**Solution**: Add more context to issue template. Examples are especially helpful.

### Issue: Agent goes out of scope
**Solution**: Make scope boundaries more explicit. Add "Out of Scope" section to every issue.

### Issue: PR doesn't meet expectations
**Solution**: Add specific DoD checklist items to issue. What does "done" really mean for this task?

### Issue: Multiple agents have inconsistent code
**Solution**: Time to create DEVELOPMENT_STANDARD.md with canonical terminology and patterns.

## Advanced Setup (Optional)

### Add Development Standard
When you notice terminology conflicts or pattern inconsistencies:
1. Copy [DEVELOPMENT_STANDARD.md template](templates/DEVELOPMENT_STANDARD.md)
2. Define key terms agents keep mixing up
3. Document architectural boundaries
4. Reference in all issues: "Follow standards in DEVELOPMENT_STANDARD.md"

### Set Up Environment Isolation
For parallel agent work:
1. Read [Environment Isolation pattern](patterns/04-environment-isolation.md)
2. Choose approach (Docker/worktrees/namespaces)
3. Document setup in AGENTS.md
4. Test with two agents working simultaneously

### Implement Strategic Review
For system coherence:
1. Schedule weekly review session
2. Use [Strategic Review pattern](patterns/03-strategic-review.md)
3. Document findings and create follow-up issues
4. Update standards based on learnings

## Getting Help

- **Pattern catalog**: See [README.md](README.md) for all patterns
- **Templates**: Check `templates/` directory
- **Examples**: Each pattern has real-world examples

## Measuring Success

After first few tasks with agents:

**Good signs**:
- ✅ Agents deliver work matching expectations first try
- ✅ Less back-and-forth in PR reviews
- ✅ Consistent code across different agents
- ✅ Can work with multiple agents in parallel

**Areas to improve**:
- ❌ Frequent scope creep → Make scope boundaries clearer
- ❌ Missing tests/docs → Add to DoD checklist
- ❌ Terminology conflicts → Create DEVELOPMENT_STANDARD.md
- ❌ Architecture violations → Document boundaries explicitly

## Iteration

The patterns in this playbook emerged from real projects. Your project will have unique needs:

1. **Start minimal**: AGENTS.md + issue template
2. **Add as needed**: Standards, patterns, processes
3. **Document learnings**: Update templates based on what works
4. **Share back**: If you discover new patterns, contribute!

---

**Time to value**: Most projects see improvement after 2-3 agent tasks with structured issues.

**Next read**: [Agent Rules Structure](patterns/01-agent-rules-structure.md) for deeper dive into documentation strategy.
