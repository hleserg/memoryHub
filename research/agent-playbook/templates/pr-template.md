# Pull Request Template

> **Instructions**: Copy this template to `.github/pull_request_template.md` in your repository. GitHub will automatically use it for new PRs.

## Linked Issue

Closes #[issue-number]

> Replace [issue-number] with the actual issue this PR addresses. If no issue exists, create one first or explain why it's not needed.

## Summary

[Brief description of changes in 2-3 sentences]

## Changes Made

> List specific changes. Be concrete, not vague.

- [Specific change 1]
- [Specific change 2]
- [Specific change 3]

## Type of Change

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Refactoring (code restructuring without behavior change)
- [ ] Documentation update
- [ ] Other: [describe]

## Testing Performed

> Provide evidence that changes work. Screenshots, logs, test output, etc.

### Test Results
```
[Paste test output showing tests passing]
```

### Manual Testing
[Describe what you tested manually]

### Demo
[Screenshots, recordings, or other visual evidence of working changes]

> For UI changes: Include before/after screenshots
> For API changes: Include example requests/responses
> For bug fixes: Show that bug no longer occurs

## Definition of Done

> Check all that apply. If an item doesn't apply, mark [N/A] and explain.

- [ ] Code implements requirements from linked issue
- [ ] All existing tests pass
- [ ] New tests added for changes
- [ ] Documentation updated (README, API docs, architecture docs)
- [ ] Follows project coding standards (see DEVELOPMENT_STANDARD.md)
- [ ] No unintended side effects or breaking changes
- [ ] Error handling for edge cases
- [ ] No debug code, commented-out sections, or TODOs left in
- [ ] Demo/evidence provided above

## Architecture Compliance

> For non-trivial changes, confirm architectural alignment.

- [ ] Respects component boundaries (core/adapters/infra)
- [ ] Uses canonical terminology from DEVELOPMENT_STANDARD.md
- [ ] Follows established patterns in codebase
- [ ] No forbidden mixings or violations

## Breaking Changes

> If this includes breaking changes, describe them and migration path.

**Breaking changes**: [Yes/No]

[If yes, describe what breaks and how to migrate]

## Dependencies

> List any new dependencies or dependency changes.

**New dependencies added**:
- [package-name] [version] — [why needed]

**Dependencies removed**:
- [package-name] — [why removed]

**Dependencies updated**:
- [package-name] [old] → [new] — [reason]

## Performance Impact

> For performance-sensitive changes, provide measurements.

**Before**: [metric]  
**After**: [metric]  
**Impact**: [improvement/regression percentage]

[Or mark N/A if not performance-related]

## Security Considerations

> For security-relevant changes, describe impact.

- [ ] No secrets committed
- [ ] Input validation in place
- [ ] Authentication/authorization unchanged (or properly updated)
- [ ] No new security vulnerabilities introduced

[Or mark N/A if not security-related]

## Deployment Notes

> Special instructions for deploying this change, if any.

[Any special deployment steps, environment variables, migrations, etc.]

[Or mark N/A if standard deployment applies]

## Open Questions

> List any uncertainties, alternative approaches considered, or decisions reviewers should validate.

- [Question or decision point 1]
- [Question or decision point 2]

[Or mark N/A if everything is clear]

## Checklist

> Final verification before requesting review.

- [ ] PR title is clear and descriptive
- [ ] All sections above are filled out (or marked N/A)
- [ ] Commits are clean and well-organized
- [ ] Ready for review

---

**Agent**: [If created by AI agent, agent identifier]  
**Time to complete**: [Optional: rough time estimate]  
**Review needed by**: [Optional: deadline or priority]
