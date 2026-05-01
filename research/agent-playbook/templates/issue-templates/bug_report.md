# Bug Report Template

> **Instructions**: Copy to `.github/ISSUE_TEMPLATE/bug_report.md`

---
name: Bug Report
about: Report a defect or unexpected behavior
title: "[Bug] "
labels: bug
assignees: ''
---

## Description

[Clear, concise description of the bug. What is happening that shouldn't be?]

## Expected Behavior

[What SHOULD happen?]

## Actual Behavior

[What is ACTUALLY happening?]

## Steps to Reproduce

> Provide specific, ordered steps so agent can reproduce the issue.

1. [First step]
2. [Second step]
3. [Third step]
4. [Observe error/unexpected behavior]

## Environment

> Help narrow down the issue.

- **Version/Commit**: [version number or commit hash]
- **OS**: [e.g., macOS 13, Ubuntu 22.04, Windows 11]
- **Browser** (if applicable): [e.g., Chrome 120, Firefox 121]
- **Runtime**: [e.g., Node 20.11, Python 3.12]
- **Other relevant details**: [database version, API version, etc.]

## Evidence

> Logs, screenshots, error messages. The more evidence, the easier to diagnose.

### Error Messages
```
[Paste error messages, stack traces, or console output here]
```

### Screenshots
[If applicable, add screenshots showing the problem]

### Logs
```
[Relevant log entries]
```

### Network Requests (if applicable)
```
[Request/response details if bug relates to API]
```

## Impact

- [ ] Blocker (prevents usage, no workaround)
- [ ] Critical (major functionality broken)
- [ ] Moderate (workaround exists)
- [ ] Minor (cosmetic or edge case)

## Frequency

- [ ] Always (100% reproduction rate)
- [ ] Often (>50% of the time)
- [ ] Sometimes (reproducible but inconsistent)
- [ ] Rare (hard to reproduce)

## Workaround

> If you've found a temporary workaround, describe it.

[Describe workaround, or write "None known"]

## Root Cause (If Known)

> If you've investigated and have a hypothesis, share it.

[Your analysis, or leave blank for agent to investigate]

## Scope for Fix

> Help agent focus on the specific bug without over-reaching.

### In Scope
- Fix the described bug
- Add regression test to prevent recurrence
- [Other specific items]

### Out of Scope
- [Related but separate issues - create separate issues for these]
- [Refactoring unrelated code]

## Definition of Done

- [ ] Bug no longer occurs when following reproduction steps
- [ ] Regression test added that fails before fix, passes after
- [ ] No new bugs introduced (all existing tests still pass)
- [ ] Root cause identified and documented
- [ ] Fix verified in same environment where bug occurred
- [ ] Related documentation updated if bug revealed doc error

## Related Issues

> Link to similar bugs or related work.

- Duplicate of: #[number]
- Related to: #[number]
- Blocks: #[number]

## Additional Context

[Any other information that might be relevant: when bug started appearing, recent changes, similar issues in the past, etc.]

---

**For Agents**: 
1. First verify you can reproduce the bug using the steps above
2. Add instrumentation/logging to understand root cause
3. Fix the root cause, not just symptoms
4. Add test that would fail without your fix
5. Verify fix in same environment as bug report
