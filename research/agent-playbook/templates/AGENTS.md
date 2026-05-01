# AGENTS.md Template

> **Instructions for use**: Copy this template to your repository root. Fill in the sections with your project-specific information. Delete these instruction lines when done.

## Overview

[Brief description of your project — 2-3 sentences about what it does and why it exists]

## Current Stage

[Choose one: Prototype / Active Development / Production / Maintenance]

**What this means**:
- [Explain implications — e.g., "Prototype: Documentation only, no runnable code yet" or "Production: All changes require tests and careful review"]

## Repository Structure

> List key directories and their purposes. Help agents navigate your codebase quickly.

- `[path/]` — [purpose]
- `[path/]` — [purpose]
- `[path/]` — [purpose]

**Key Documents**:
- Architecture: `[path to architecture docs]`
- Standards: `[path to development standards]`
- [Other important docs]

## Technology Stack

> List languages, frameworks, and key technologies agents will work with.

**Language(s)**: [e.g., Python 3.12+, TypeScript 5.x]

**Key Dependencies**:
- [Framework]: [version] — [what it's used for]
- [Library]: [version] — [what it's used for]

**Tools**:
- Package manager: [e.g., npm, uv, poetry]
- Build system: [e.g., webpack, hatchling]
- Test framework: [e.g., pytest, jest]

## How to Build, Test, and Run

> Provide exact commands. If no build system yet, say so explicitly.

### Development Setup
```bash
[Installation commands]
# e.g., npm install, pip install -r requirements.txt, etc.
```

### Running Tests
```bash
[Test commands]
# e.g., npm test, pytest, etc.
```

### Building
```bash
[Build commands]
# e.g., npm run build, python -m build, etc.
```

### Running Locally
```bash
[Run commands]
# e.g., npm start, python -m app, etc.
```

> If any of these don't exist yet:
```markdown
### Not Applicable Yet
- No build system (documentation only)
- No test framework (will be added in phase 2)
- [etc.]
```

## Linting and Code Quality

> If you have linters, formatters, or code quality tools, specify here.

```bash
# Linting
[lint command]

# Formatting
[format command]

# Type checking
[type check command]
```

**Auto-fix on save**: [Yes/No, configuration details if applicable]

## Working with This Project

> Provide agent-specific guidance.

### General Guidelines
- Always read issue descriptions completely before starting
- Follow patterns established in existing code
- Ask questions in PR/issue comments if truly blocked
- Stay within scope defined in issues

### Documentation Language
- Primary documentation language: [English / other]
- Code comments: [English / other]
- Commit messages: [English / other]
- [Any bilingual support notes]

### Commit Conventions
- [e.g., Conventional Commits, or "descriptive messages"]
- [Branch naming: e.g., `feature/name`, `fix/name`, `agent/name`]

### Before Submitting PR
- [ ] All tests pass
- [ ] Documentation updated
- [ ] Follows project standards (see DEVELOPMENT_STANDARD.md)
- [ ] Includes demo/evidence of working changes
- [ ] No debug code or TODOs left in

## Special Considerations

> Any project-specific quirks, constraints, or important notes.

- [e.g., "No external dependencies without approval"]
- [e.g., "All database changes require migration scripts"]
- [e.g., "UI changes must be tested in Chrome and Firefox"]
- [e.g., "Performance-sensitive: benchmark before/after"]

## Need Help?

> Where agents can find more information or ask questions.

- **Standards and conventions**: See `DEVELOPMENT_STANDARD.md`
- **Architecture decisions**: See `docs/architecture/` and ADRs
- **Stuck?**: Comment on your PR or issue, include:
  - What you tried
  - What didn't work
  - Relevant error messages

## Environment Variables

> If your project uses environment configuration, document it.

**Required**:
- `[VAR_NAME]`: [Description, example value]

**Optional**:
- `[VAR_NAME]`: [Description, default value]

**Setup**:
```bash
cp .env.example .env
# Edit .env with your values
```

## Deployment

> If agents might deploy or create deployment artifacts, document here.

**Deployment target**: [e.g., Docker, cloud platform, static hosting]

**Deployment command**:
```bash
[deployment command]
```

**Environment-specific notes**:
- Development: [details]
- Staging: [details]
- Production: [details]

---

**Last Updated**: [YYYY-MM-DD]  
**Maintained By**: [Name/Team]
