# Security Policy

Atman is in active prototyping. We still take vulnerability reports seriously and will work with reporters to understand impact and ship fixes when appropriate.

## Supported Versions

Security fixes are applied on a **best-effort** basis to the **current development line**. We do not guarantee long-term support for older tags or pre-release snapshots.

| Version / line | Supported for security fixes |
| -------------- | ---------------------------- |
| Latest `main`  | Yes                          |
| Latest published release matching `pyproject.toml` (e.g. **0.1.x**) | Yes, when a release exists and the issue applies |
| Older tags / forks / local experiments | No (upgrade to latest) |

When in doubt, reproduce on **`main`** before reporting.

## Reporting a Vulnerability

**Please do not** open a public GitHub issue for an unfixed security vulnerability. That reduces the time we have to fix it and can put users at risk.

### Preferred channels

1. **GitHub** — use **Security → Report a vulnerability** for this repository (private advisory), if the feature is enabled for the repo.
2. **Email** — send details to [hello@atmanai.dev](mailto:hello@atmanai.dev) with the subject line starting with **`[SECURITY] Atman`**.

### What to include

- Short description of the issue and its impact (confidentiality / integrity / availability).
- Steps to reproduce, affected components (e.g. CLI, file adapters, parsing paths), and version or commit SHA if known.
- Whether you plan to publish or present the finding later (coordinated disclosure helps everyone).

### What to expect

- **Acknowledgment:** we aim to reply within **a few business days**; small-team delays are possible.
- **Investigation:** we may ask follow-up questions. Duplicate or invalid reports will be closed with a brief explanation.
- **Resolution:** if we confirm a vulnerability, we will work on a fix, prepare a release or advisory as appropriate, and credit you in the advisory or release notes **if you want to be named**.
- **Declined / informational:** we will explain why (e.g. out of scope, requires local compromise already, documentation-only hardening).

We respect responsible disclosure: please give us a reasonable window to release a fix before public details, unless the issue is already public or actively exploited.

## Scope notes

- Atman is designed for **local / file-based** workflows without mandatory network services; some classes of “server” vulnerabilities may not apply. Reports about **unsafe handling of untrusted paths, files, or serialized data** are still in scope.
- Dependency advisories (e.g. in `pydantic`, `rich`) are usually handled by **upgrading dependencies**; reports are welcome if you believe our minimum pins or usage pattern leaves users exposed.

## Non-security bugs

For regular bugs and feature requests, use **GitHub Issues** (public), following [`CONTRIBUTING.md`](CONTRIBUTING.md).
