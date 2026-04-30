# Synchronization Guide: Local Agent Master Prompt

## Purpose

This guide describes how to keep `.cursor/local-agent-master-prompt.md` synchronized with `docs/development/DEVELOPMENT_STANDARD.md` and other core documentation.

## Why Synchronization Matters

The local agent master prompt is derived from project standards. When standards change, the master prompt must be updated to ensure:
- Local agents follow current conventions
- No divergence between cloud and local agent behavior
- Consistent terminology across all development
- Up-to-date architecture boundaries

## What to Sync

### Primary Source: DEVELOPMENT_STANDARD.md

Monitor these sections for changes:

1. **Section 4: Common Vocabulary** → Update "Terminology Discipline" in master prompt
2. **Section 6: Canonical Module Names** → Update "Quick Reference" structure
3. **Section 7: Canonical Domain Object Names** → Update forbidden/allowed terms
4. **Section 10: Versioning Schemas** → Update persistent structure requirements
5. **Section 15: Governance Modes** → Update workflow rules
6. **Section 21: Definition of Done** → Update DoD checklist
7. **Section 23: Implementation Order** → Update "Priority Order"

### Secondary Sources

Also watch for significant changes in:
- `docs/architecture/SYSTEM.md` — Component definitions, protocols
- `AGENTS.md` — Repository structure, tool setup
- `MANIFEST.md` — Core philosophy (rarely changes)

## When to Sync

Trigger synchronization when:
- [ ] New domain terms added to vocabulary
- [ ] Architecture boundaries change (Core/Adapter split)
- [ ] Implementation order is revised
- [ ] New mandatory workflows introduced
- [ ] Storage boundaries change
- [ ] Definition of Done checklist updated
- [ ] New forbidden patterns identified
- [ ] Repository structure changes

**Frequency**: Check after each merge to `main` that touches `DEVELOPMENT_STANDARD.md`

## How to Sync

### Step 1: Identify Changes

```bash
# Check what changed in DEVELOPMENT_STANDARD.md
git log -p --follow docs/development/DEVELOPMENT_STANDARD.md

# Compare with last known sync
git diff <last-sync-commit> HEAD -- docs/development/DEVELOPMENT_STANDARD.md
```

### Step 2: Review Impact

Read the changed sections and ask:
- Does this affect local agent workflow?
- Does this change terminology or conventions?
- Does this add new requirements?
- Does this change architecture boundaries?

### Step 3: Update Master Prompt

Map changes from `DEVELOPMENT_STANDARD.md` to master prompt sections:

| DEVELOPMENT_STANDARD Section | Master Prompt Section |
|------------------------------|----------------------|
| §4 Common Vocabulary | §2 Terminology Discipline |
| §6 Module Names | §11 Quick Reference |
| §7 Domain Object Names | §2 Terminology Discipline |
| §12 Storage Boundaries | §3 Architecture Boundaries |
| §13 Ports | §3 Architecture Boundaries |
| §21 Definition of Done | §6 Definition of Done |
| §23 Implementation Order | §10 Priority Order |

### Step 4: Update Version & Timestamp

```markdown
> **Version**: 1.1  
> **Last Updated**: 2026-05-15  
> **Status**: Active
```

Increment version:
- **Major** (2.0): Breaking changes, complete restructure
- **Minor** (1.1): New sections, significant additions
- **Patch** (1.0.1): Clarifications, typo fixes

### Step 5: Commit

```bash
git add .cursor/local-agent-master-prompt.md
git commit -m "Update local agent master prompt (sync with DEVELOPMENT_STANDARD v<X>)"
```

## Sync Checklist

Use this checklist when performing synchronization:

- [ ] Identified what changed in `DEVELOPMENT_STANDARD.md`
- [ ] Reviewed impact on local agent workflow
- [ ] Updated affected sections in master prompt
- [ ] Verified terminology consistency
- [ ] Updated version number
- [ ] Updated timestamp
- [ ] Committed with descriptive message
- [ ] Tested: read master prompt end-to-end for coherence
- [ ] Optional: Notify team if changes affect active work

## Automated Sync (Future)

Currently, synchronization is manual. Potential automation:

1. **GitHub Action**: Trigger on `DEVELOPMENT_STANDARD.md` changes
   - Parse standard document
   - Extract vocabulary, DoD, implementation order
   - Generate diff report
   - Create PR with suggested updates

2. **Pre-merge Hook**: Flag when `DEVELOPMENT_STANDARD.md` changes without corresponding master prompt update

3. **Version Check**: Add script to verify master prompt timestamp is recent relative to standard document

**Status**: Manual process only (automation not prioritized for prototype phase)

## Conflict Resolution

If cloud agents and local agents show different behavior:

1. Check if master prompt is out of sync
2. Compare `AGENTS.md` (cloud) vs `.cursor/local-agent-master-prompt.md` (local)
3. `DEVELOPMENT_STANDARD.md` is always source of truth
4. Update both to align with standard
5. Document the divergence in issue/PR

## Example Sync Scenario

**Scenario**: New domain term "AmbientContext" added to `DEVELOPMENT_STANDARD.md` §4

**Sync Process**:

1. **Detect**: See commit adding "AmbientContext" to vocabulary
2. **Review**: Understand it's a new Core concept for background awareness
3. **Update Master Prompt**:
   - Add to §2 Terminology Discipline: "Use AmbientContext, not 'background state' or 'passive context'"
   - Add to §10 Priority Order if it's a new component
4. **Version**: Bump 1.0 → 1.1
5. **Commit**: "Update local agent master prompt (add AmbientContext term)"

## Maintenance Log

| Date | Version | Changes | Synced From |
|------|---------|---------|-------------|
| 2026-04-30 | 1.0 | Initial master prompt created | DEVELOPMENT_STANDARD.md v1.0 |

---

## Questions?

If synchronization is unclear or conflicts arise:
1. Check this guide first
2. Review both documents side-by-side
3. Ask maintainer or create discussion issue
4. When in doubt, defer to `DEVELOPMENT_STANDARD.md`

**Remember**: The goal is not perfect automation, but ensuring local agents have access to the same standards as cloud agents.
