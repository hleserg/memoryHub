"""
atman/agent_cli/git.py
Git operations: branch guard, commits, PR lifecycle via GitHub API.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import requests

from .config import AgentConfig

# ── Git helpers ───────────────────────────────────────────────────────────────


def run_git(args: list[str], cwd: Path) -> tuple[int, str, str]:
    """Run a git command. Returns (returncode, stdout, stderr)."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def current_branch(repo: Path) -> str:
    _, out, _ = run_git(["branch", "--show-current"], repo)
    return out


def is_branch_merged(branch: str, repo: Path, main: str = "main") -> bool:
    """Check if branch is already merged into main."""
    _, out, _ = run_git(["branch", "--merged", main], repo)
    merged = [b.strip().lstrip("* ") for b in out.splitlines()]
    return branch in merged


def branch_exists_remote(branch: str, repo: Path) -> bool:
    code, out, _ = run_git(["ls-remote", "--heads", "origin", branch], repo)
    return code == 0 and bool(out.strip())


def has_uncommitted_changes(repo: Path) -> bool:
    _, out, _ = run_git(["status", "--porcelain"], repo)
    return bool(out)


def pull_main(repo: Path, main: str = "main") -> None:
    run_git(["checkout", main], repo)
    run_git(["pull", "origin", main], repo)


def create_branch(name: str, repo: Path) -> tuple[bool, str]:
    """Create and checkout a new branch. Returns (success, message)."""
    code, _, err = run_git(["checkout", "-b", name], repo)
    if code != 0:
        return False, err
    return True, f"Switched to new branch '{name}'"


def push_branch(branch: str, repo: Path) -> tuple[bool, str]:
    code, out, err = run_git(["push", "-u", "origin", branch], repo)
    if code != 0:
        return False, err
    return True, out


def make_branch_name(task: str) -> str:
    """Convert task description to a valid branch name."""
    slug = task.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = slug[:50].rstrip("-")
    return f"feat/{slug}"


def commit_all(message: str, repo: Path) -> tuple[bool, str]:
    run_git(["add", "-A"], repo)
    code, out, err = run_git(["commit", "-m", message], repo)
    if code != 0:
        return False, err
    return True, out


def get_diff(repo: Path, base: str = "main") -> str:
    """Get diff of current branch vs base."""
    _, out, _ = run_git(["diff", f"origin/{base}...HEAD"], repo)
    return out


def merge_base_diff(repo: Path) -> str:
    """Files changed in current branch."""
    _, out, _ = run_git(["diff", "--name-only", "origin/main...HEAD"], repo)
    return out


def resolve_conflicts_auto(repo: Path) -> tuple[bool, list[str]]:
    """
    Try to resolve merge conflicts automatically.
    Returns (fully_resolved, list_of_remaining_conflict_files).
    """
    _, out, _ = run_git(["diff", "--name-only", "--diff-filter=U"], repo)
    conflict_files = [f for f in out.splitlines() if f]
    if not conflict_files:
        return True, []
    # We can't auto-resolve — return list for LLM to handle
    return False, conflict_files


# ── Branch Guard ─────────────────────────────────────────────────────────────


class BranchGuardError(Exception):
    """Raised when a git operation violates branch protection rules."""


class BranchGuard:
    """
    Enforces branch hygiene rules:
    - In main → auto-create feature branch before any work
    - In merged branch → pull main, create new branch
    """

    def __init__(self, cfg: AgentConfig) -> None:
        self.cfg = cfg
        self.repo = cfg.repo_path

    def check_and_prepare(self, task: str) -> tuple[str, list[str]]:
        """
        Ensure we're on the right branch for working.
        Returns (branch_name, list_of_messages_for_ui).
        """
        messages: list[str] = []
        branch = current_branch(self.repo)

        # Case 1: on main → create feature branch
        if branch == self.cfg.main_branch:
            new_branch = make_branch_name(task)
            messages.append(f"On {self.cfg.main_branch} — creating branch '{new_branch}'")
            pull_main(self.repo, self.cfg.main_branch)
            ok, msg = create_branch(new_branch, self.repo)
            if not ok:
                raise RuntimeError(f"Failed to create branch: {msg}")
            messages.append(f"Switched to '{new_branch}'")
            return new_branch, messages

        # Case 2: on a merged branch → go to main, pull, new branch
        if is_branch_merged(branch, self.repo, self.cfg.main_branch):
            new_branch = make_branch_name(task)
            messages.append(
                f"Branch '{branch}' is already merged — "
                f"pulling {self.cfg.main_branch} and creating '{new_branch}'"
            )
            pull_main(self.repo, self.cfg.main_branch)
            ok, msg = create_branch(new_branch, self.repo)
            if not ok:
                raise RuntimeError(f"Failed to create branch: {msg}")
            messages.append(f"Switched to '{new_branch}'")
            return new_branch, messages

        # Case 3: on a feature branch that's not merged → stay here
        messages.append(f"Continuing on branch '{branch}'")
        return branch, messages

    def safe_push(self, branch: str | None = None, remote: str = "origin") -> tuple[bool, str]:
        """
        Push with protection against pushing to the main integration branch.

        Raises BranchGuardError when attempting to push directly to ``main``/``master``
        or the configured main branch.
        """
        _ = remote  # Reserved for callers; ``push_branch`` relies on upstream defaults.
        branch = branch or current_branch(self.repo)
        if branch in (self.cfg.main_branch, "master", "main"):
            raise BranchGuardError(
                f"Direct push to '{branch}' is forbidden. "
                "Create a PR: BranchGuard.safe_push() blocked."
            )
        return push_branch(branch, self.repo)


# ── GitHub PR Manager ────────────────────────────────────────────────────────


class PRManager:
    """Manages PR lifecycle via GitHub API."""

    def __init__(self, cfg: AgentConfig) -> None:
        self.cfg = cfg
        self.base = cfg.github_api
        self.repo = cfg.github_repo
        self.h = cfg.github_headers

    def _get(self, path: str, params: dict | None = None) -> Any:
        r = requests.get(f"{self.base}/{path}", headers=self.h, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, data: dict) -> Any:
        r = requests.post(f"{self.base}/{path}", headers=self.h, json=data, timeout=30)
        r.raise_for_status()
        return r.json()

    def _patch(self, path: str, data: dict) -> Any:
        r = requests.patch(f"{self.base}/{path}", headers=self.h, json=data, timeout=30)
        r.raise_for_status()
        return r.json()

    def _put(self, path: str, data: dict) -> Any:
        r = requests.put(f"{self.base}/{path}", headers=self.h, json=data, timeout=30)
        r.raise_for_status()
        return r.json()

    def create_pr(
        self,
        branch: str,
        title: str,
        body: str,
        base: str | None = None,
        draft: bool = False,
    ) -> dict:
        return self._post(
            f"repos/{self.repo}/pulls",
            {
                "title": title,
                "body": body,
                "head": branch,
                "base": base or self.cfg.main_branch,
                "draft": draft,
            },
        )

    def get_pr(self, pr_number: int) -> dict:
        return self._get(f"repos/{self.repo}/pulls/{pr_number}")

    def get_pr_by_branch(self, branch: str) -> dict | None:
        prs = self._get(
            f"repos/{self.repo}/pulls",
            params={"head": f"{self.repo.split('/')[0]}:{branch}", "state": "open"},
        )
        return prs[0] if prs else None

    def get_pr_status(self, pr_number: int) -> dict:
        """Returns aggregated status: CI, reviews, conflicts."""
        pr = self.get_pr(pr_number)
        sha = pr["head"]["sha"]

        # CI checks
        checks = self._get(f"repos/{self.repo}/commits/{sha}/check-runs")
        check_runs = checks.get("check_runs", [])
        completed = [c for c in check_runs if c.get("status") == "completed"]
        incomplete = [c for c in check_runs if c.get("status") != "completed"]
        if any(c.get("conclusion") in ("failure", "error") for c in completed):
            ci_status = "failing"
        elif incomplete:
            ci_status = "pending"
        elif completed and all(c.get("conclusion") == "success" for c in completed):
            ci_status = "passing"
        else:
            ci_status = "pending"
        failed_checks = [
            {"name": c["name"], "url": c["html_url"]}
            for c in check_runs
            if c.get("conclusion") in ("failure", "error")
        ]

        # Reviews
        reviews = self._get(f"repos/{self.repo}/pulls/{pr_number}/reviews")
        latest_reviews: dict[str, str] = {}
        for r in reviews:
            if r["state"] != "COMMENTED":
                latest_reviews[r["user"]["login"]] = r["state"]
        approved = all(s == "APPROVED" for s in latest_reviews.values()) and bool(latest_reviews)
        changes_requested = any(s == "CHANGES_REQUESTED" for s in latest_reviews.values())

        # Review comments (unresolved)
        comments = self._get(
            f"repos/{self.repo}/pulls/{pr_number}/comments",
            params={"per_page": 100},
        )
        unresolved_comments = [c for c in comments if not c.get("in_reply_to_id")]

        return {
            "pr": pr,
            "mergeable": pr.get("mergeable"),
            "mergeable_state": pr.get("mergeable_state"),
            "ci_status": ci_status,
            "failed_checks": failed_checks,
            "approved": approved,
            "changes_requested": changes_requested,
            "unresolved_comments": unresolved_comments,
            "reviews": latest_reviews,
        }

    def get_ci_logs(self, pr_number: int) -> list[dict]:
        """Fetch failed check run logs."""
        pr = self.get_pr(pr_number)
        sha = pr["head"]["sha"]
        checks = self._get(f"repos/{self.repo}/commits/{sha}/check-runs")
        logs = []
        for c in checks.get("check_runs", []):
            if c.get("conclusion") in ("failure", "error"):
                # Fetch job logs
                try:
                    job_id = c["id"]
                    r = requests.get(
                        f"{self.base}/repos/{self.repo}/actions/jobs/{job_id}/logs",
                        headers=self.h,
                        timeout=30,
                        allow_redirects=True,
                    )
                    logs.append({"name": c["name"], "log": r.text[-8000:]})  # last 8K
                except Exception:
                    logs.append({"name": c["name"], "log": "(log unavailable)"})
        return logs

    def post_review(
        self,
        pr_number: int,
        body: str,
        comments: list[dict],
        event: str = "COMMENT",
    ) -> dict:
        """Post a review. event: COMMENT | APPROVE | REQUEST_CHANGES."""
        pr = self.get_pr(pr_number)
        sha = pr["head"]["sha"]
        return self._post(
            f"repos/{self.repo}/pulls/{pr_number}/reviews",
            {
                "commit_id": sha,
                "body": body,
                "event": event,
                "comments": comments,
            },
        )

    def reply_to_comment(self, pr_number: int, comment_id: int, body: str) -> dict:
        return self._post(
            f"repos/{self.repo}/pulls/{pr_number}/comments",
            {
                "body": body,
                "in_reply_to": comment_id,
            },
        )

    def merge_pr(self, pr_number: int, method: str = "squash") -> dict:
        pr = self.get_pr(pr_number)
        return self._put(
            f"repos/{self.repo}/pulls/{pr_number}/merge",
            {
                "merge_method": method,
                "commit_title": pr["title"],
            },
        )

    def add_reviewer(self, pr_number: int, reviewers: list[str]) -> None:
        self._post(
            f"repos/{self.repo}/pulls/{pr_number}/requested_reviewers",
            {
                "reviewers": reviewers,
            },
        )
