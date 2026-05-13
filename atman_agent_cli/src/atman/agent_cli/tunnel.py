"""
atman/agent_cli/tunnel.py
Cloudflare Tunnel + GitHub self-hosted runner automation.

What gets automated:
  1. Check / install cloudflared binary
  2. Start tunnel → get public URL
  3. Register GitHub webhook via API
  4. Download + configure GitHub Actions self-hosted runner
  5. Start runner as background process

Two tunnel modes:
  QUICK  — `cloudflared tunnel --url ...` → temporary *.trycloudflare.com URL
             No account needed. URL changes on restart. Good for testing.
  NAMED  — `cloudflared tunnel create atman-agent` → permanent URL
             Requires Cloudflare account + API token + domain.

For most solo developers QUICK mode is enough.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import requests

# ── Constants ──────────────────────────────────────────────────────────────────

CLOUDFLARED_INSTALL = {
    "Linux":  "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
    "Darwin": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz",
    "Windows": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
}

RUNNER_DOWNLOAD = {
    "Linux":  "https://github.com/actions/runner/releases/download/v2.317.0/actions-runner-linux-x64-2.317.0.tar.gz",
    "Darwin": "https://github.com/actions/runner/releases/download/v2.317.0/actions-runner-osx-x64-2.317.0.tar.gz",
}

GITHUB_API = "https://api.github.com"
WEBHOOK_PATH = "/webhook"
RUNNER_DIR = Path.home() / ".atman" / "gh-runner"
CLOUDFLARED_BIN = Path.home() / ".atman" / "bin" / "cloudflared"
TUNNEL_STATE_FILE = Path.home() / ".atman" / "tunnel_state.json"


# ── State ─────────────────────────────────────────────────────────────────────

@dataclass
class TunnelState:
    mode: str = ""               # "quick" | "named"
    tunnel_url: str = ""         # public URL e.g. https://abc.trycloudflare.com
    tunnel_name: str = ""        # for named tunnels
    webhook_id: int = 0          # GitHub webhook ID
    runner_registered: bool = False
    runner_name: str = ""
    last_started: str = ""
    webhook_port: int = 9876

    def save(self) -> None:
        TUNNEL_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        TUNNEL_STATE_FILE.write_text(json.dumps(self.__dict__, indent=2))

    @classmethod
    def load(cls) -> "TunnelState":
        if TUNNEL_STATE_FILE.exists():
            try:
                return cls(**json.loads(TUNNEL_STATE_FILE.read_text()))
            except Exception:
                pass
        return cls()


# ── Log callback type ──────────────────────────────────────────────────────────

Log = Callable[[str, str], None]   # fn(message, level) level = info|ok|warn|error


def _noop(msg: str, level: str = "info") -> None:
    pass


# ── Cloudflared ────────────────────────────────────────────────────────────────

def is_cloudflared_installed() -> bool:
    return bool(shutil.which("cloudflared")) or CLOUDFLARED_BIN.exists()


def cloudflared_path() -> str:
    system_cf = shutil.which("cloudflared")
    if system_cf:
        return system_cf
    if CLOUDFLARED_BIN.exists():
        return str(CLOUDFLARED_BIN)
    return "cloudflared"


def install_cloudflared(log: Log = _noop) -> bool:
    """Download cloudflared binary to ~/.atman/bin/. Returns True on success."""
    system = platform.system()
    url = CLOUDFLARED_INSTALL.get(system)
    if not url:
        log(f"Unsupported OS: {system}. Install cloudflared manually: https://developers.cloudflare.com/cloudflared/get-started/", "error")
        return False

    bin_dir = Path.home() / ".atman" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    dest = bin_dir / ("cloudflared.exe" if system == "Windows" else "cloudflared")

    log(f"Downloading cloudflared for {system}...", "info")
    try:
        r = requests.get(url, timeout=60, stream=True)
        r.raise_for_status()

        if url.endswith(".tgz"):
            import tarfile, io
            with tarfile.open(fileobj=io.BytesIO(r.content)) as tf:
                tf.extract("cloudflared", path=bin_dir)
        else:
            dest.write_bytes(r.content)

        dest.chmod(0o755)
        log(f"cloudflared installed → {dest}", "ok")
        return True
    except Exception as e:
        log(f"Download failed: {e}", "error")
        return False


class QuickTunnel:
    """
    Starts `cloudflared tunnel --url http://localhost:PORT`.
    Gives a temporary *.trycloudflare.com URL. No account needed.
    URL changes every restart — re-registers GitHub webhook automatically.
    """

    def __init__(self, port: int = 9876, log: Log = _noop) -> None:
        self.port = port
        self.log = log
        self._proc: subprocess.Popen | None = None
        self._url: str = ""
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    def start(self) -> str | None:
        """Start tunnel. Blocks until URL is available (max 30s). Returns URL or None."""
        if not is_cloudflared_installed():
            self.log("cloudflared not found — installing...", "info")
            if not install_cloudflared(self.log):
                return None

        cmd = [cloudflared_path(), "tunnel", "--url", f"http://localhost:{self.port}", "--no-autoupdate"]
        self.log(f"Starting cloudflare quick tunnel on port {self.port}...", "info")

        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        self._thread = threading.Thread(target=self._watch_output, daemon=True)
        self._thread.start()

        # Wait for URL to appear in logs (up to 30s)
        if self._ready.wait(timeout=30):
            self.log(f"Tunnel ready: {self._url}", "ok")
            return self._url
        else:
            self.log("Tunnel timeout — cloudflared may have failed to start", "error")
            return None

    def _watch_output(self) -> None:
        url_pattern = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
        for line in self._proc.stdout:
            line = line.strip()
            if line:
                self.log(f"[cloudflared] {line}", "info")
            match = url_pattern.search(line)
            if match:
                self._url = match.group()
                self._ready.set()

    def stop(self) -> None:
        if self._proc:
            self._proc.terminate()
            self._proc = None
        self._url = ""

    @property
    def url(self) -> str:
        return self._url

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None


# ── GitHub Webhook ─────────────────────────────────────────────────────────────

def register_github_webhook(
    tunnel_url: str,
    github_token: str,
    repo: str,
    webhook_port: int = 9876,
    log: Log = _noop,
) -> int | None:
    """
    Register (or update) GitHub webhook pointing to the tunnel.
    Returns webhook ID or None on failure.
    """
    webhook_url = f"{tunnel_url}{WEBHOOK_PATH}"
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
    }
    payload = {
        "name": "web",
        "active": True,
        "events": ["pull_request", "check_run"],
        "config": {
            "url": webhook_url,
            "content_type": "json",
            "insecure_ssl": "0",
        },
    }

    log(f"Registering webhook → {webhook_url}", "info")

    # Check existing webhooks
    try:
        r = requests.get(f"{GITHUB_API}/repos/{repo}/hooks", headers=headers, timeout=15)
        existing = r.json() if r.status_code == 200 else []
        for hook in existing:
            if "atman" in hook.get("config", {}).get("url", "").lower() or \
               "trycloudflare" in hook.get("config", {}).get("url", "").lower():
                # Update existing
                r2 = requests.patch(
                    f"{GITHUB_API}/repos/{repo}/hooks/{hook['id']}",
                    headers=headers, json=payload, timeout=15,
                )
                if r2.status_code == 200:
                    log(f"Webhook #{hook['id']} updated → {webhook_url}", "ok")
                    return hook["id"]
    except Exception:
        pass

    # Create new
    try:
        r = requests.post(
            f"{GITHUB_API}/repos/{repo}/hooks",
            headers=headers, json=payload, timeout=15,
        )
        if r.status_code == 201:
            hook_id = r.json()["id"]
            log(f"Webhook #{hook_id} created → {webhook_url}", "ok")
            return hook_id
        else:
            log(f"Webhook creation failed: {r.status_code} {r.text[:200]}", "error")
            return None
    except Exception as e:
        log(f"Webhook error: {e}", "error")
        return None


def delete_github_webhook(
    webhook_id: int,
    github_token: str,
    repo: str,
    log: Log = _noop,
) -> bool:
    headers = {"Authorization": f"Bearer {github_token}", "Accept": "application/vnd.github+json"}
    try:
        r = requests.delete(
            f"{GITHUB_API}/repos/{repo}/hooks/{webhook_id}",
            headers=headers, timeout=15,
        )
        if r.status_code == 204:
            log(f"Webhook #{webhook_id} deleted", "ok")
            return True
        log(f"Delete webhook failed: {r.status_code}", "warn")
        return False
    except Exception as e:
        log(f"Error: {e}", "error")
        return False


# ── GitHub self-hosted runner ──────────────────────────────────────────────────

def get_runner_registration_token(
    github_token: str,
    repo: str,
    log: Log = _noop,
) -> str | None:
    """Get a short-lived runner registration token from GitHub API."""
    headers = {"Authorization": f"Bearer {github_token}", "Accept": "application/vnd.github+json"}
    try:
        r = requests.post(
            f"{GITHUB_API}/repos/{repo}/actions/runners/registration-token",
            headers=headers, timeout=15,
        )
        if r.status_code == 201:
            token = r.json()["token"]
            log("Runner registration token obtained", "ok")
            return token
        log(f"Failed to get runner token: {r.status_code} {r.text[:200]}", "error")
        return None
    except Exception as e:
        log(f"Error: {e}", "error")
        return None


def install_runner(log: Log = _noop) -> bool:
    """Download and extract GitHub Actions runner to ~/.atman/gh-runner/."""
    system = platform.system()
    url = RUNNER_DOWNLOAD.get(system)
    if not url:
        log(f"Unsupported OS for runner: {system}", "error")
        return False

    if RUNNER_DIR.exists() and (RUNNER_DIR / "run.sh").exists():
        log("Runner already installed", "ok")
        return True

    RUNNER_DIR.mkdir(parents=True, exist_ok=True)
    log(f"Downloading GitHub Actions runner for {system}...", "info")

    try:
        r = requests.get(url, timeout=120, stream=True)
        r.raise_for_status()

        import tarfile, io
        with tarfile.open(fileobj=io.BytesIO(r.content), mode="r:gz") as tf:
            tf.extractall(RUNNER_DIR)

        log(f"Runner extracted → {RUNNER_DIR}", "ok")
        return True
    except Exception as e:
        log(f"Runner download failed: {e}", "error")
        return False


def configure_runner(
    registration_token: str,
    repo: str,
    runner_name: str = "atman-agent",
    labels: str = "atman,self-hosted,gpu",
    log: Log = _noop,
) -> bool:
    """Run ./config.sh to register runner with GitHub."""
    config_sh = RUNNER_DIR / "config.sh"
    if not config_sh.exists():
        log("Runner not installed (run install_runner first)", "error")
        return False

    repo_url = f"https://github.com/{repo}"
    cmd = [
        str(config_sh),
        "--url", repo_url,
        "--token", registration_token,
        "--name", runner_name,
        "--labels", labels,
        "--unattended",
        "--replace",
    ]
    log(f"Configuring runner '{runner_name}' for {repo_url}...", "info")
    try:
        result = subprocess.run(cmd, cwd=RUNNER_DIR, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            log(f"Runner '{runner_name}' configured", "ok")
            return True
        log(f"Runner config failed:\n{result.stderr[:500]}", "error")
        return False
    except Exception as e:
        log(f"Error: {e}", "error")
        return False


_runner_proc: subprocess.Popen | None = None


def start_runner(log: Log = _noop) -> bool:
    """Start ./run.sh as a background daemon process."""
    global _runner_proc
    run_sh = RUNNER_DIR / "run.sh"
    if not run_sh.exists():
        log("run.sh not found — configure runner first", "error")
        return False

    if _runner_proc and _runner_proc.poll() is None:
        log("Runner already running", "ok")
        return True

    log("Starting GitHub Actions runner...", "info")
    _runner_proc = subprocess.Popen(
        [str(run_sh)],
        cwd=RUNNER_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    # Watch output in background
    def watch():
        for line in _runner_proc.stdout:
            log(f"[runner] {line.strip()}", "info")
    threading.Thread(target=watch, daemon=True).start()

    time.sleep(3)
    if _runner_proc.poll() is None:
        log(f"Runner started (PID {_runner_proc.pid})", "ok")
        return True
    log("Runner exited immediately — check configuration", "error")
    return False


def stop_runner() -> None:
    global _runner_proc
    if _runner_proc and _runner_proc.poll() is None:
        _runner_proc.terminate()
        _runner_proc = None


def runner_is_running() -> bool:
    return _runner_proc is not None and _runner_proc.poll() is None


def list_registered_runners(github_token: str, repo: str) -> list[dict]:
    headers = {"Authorization": f"Bearer {github_token}", "Accept": "application/vnd.github+json"}
    try:
        r = requests.get(f"{GITHUB_API}/repos/{repo}/actions/runners", headers=headers, timeout=15)
        return r.json().get("runners", []) if r.status_code == 200 else []
    except Exception:
        return []


# ── CI workflow file ───────────────────────────────────────────────────────────

CI_REVIEW_WORKFLOW = """\
# .github/workflows/ai-review.yml
# Auto-generated by Atman Agent CLI
# Runs AI code review on every PR using local self-hosted runner

name: AI Code Review

on:
  pull_request:
    types: [opened, synchronize, reopened]

jobs:
  ai-review:
    runs-on: [self-hosted, atman]
    timeout-minutes: 10

    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          fetch-depth: 0   # need full history for diff

      - name: Run Atman AI Review
        run: |
          cd {repo_path}
          uv run atman-agent review --pr ${{{{ github.event.pull_request.number }}}}
        env:
          GITHUB_TOKEN: ${{{{ secrets.GITHUB_TOKEN }}}}
          ATMAN_LLM_URL: http://localhost:8080
          COHERE_API_KEY: ${{{{ secrets.COHERE_API_KEY }}}}
          ANTHROPIC_API_KEY: ${{{{ secrets.ANTHROPIC_API_KEY }}}}
"""


def write_ci_workflow(repo_path: Path, log: Log = _noop) -> bool:
    """Write GitHub Actions workflow file to .github/workflows/."""
    workflows_dir = repo_path / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    dest = workflows_dir / "ai-review.yml"

    content = CI_REVIEW_WORKFLOW.format(repo_path=str(repo_path))
    dest.write_text(content)
    log(f"CI workflow written → {dest}", "ok")
    return True


# ── Full setup orchestration ───────────────────────────────────────────────────

class SetupOrchestrator:
    """
    Runs the full setup sequence with progress callbacks.
    Each step reports status via log callback.
    """

    def __init__(
        self,
        github_token: str,
        repo: str,
        repo_path: Path,
        webhook_port: int = 9876,
        log: Log = _noop,
    ) -> None:
        self.github_token = github_token
        self.repo = repo
        self.repo_path = repo_path
        self.webhook_port = webhook_port
        self.log = log
        self.state = TunnelState.load()
        self._quick_tunnel = QuickTunnel(port=webhook_port, log=log)

    def start_tunnel(self) -> bool:
        url = self._quick_tunnel.start()
        if not url:
            return False
        self.state.tunnel_url = url
        self.state.mode = "quick"
        self.state.webhook_port = self.webhook_port
        self.state.last_started = datetime.now().isoformat()
        self.state.save()
        return True

    def register_webhook(self) -> bool:
        if not self.state.tunnel_url:
            self.log("Start tunnel first", "error")
            return False
        wid = register_github_webhook(
            self.state.tunnel_url, self.github_token, self.repo,
            self.webhook_port, self.log,
        )
        if wid:
            self.state.webhook_id = wid
            self.state.save()
            return True
        return False

    def setup_runner(self, runner_name: str = "atman-agent") -> bool:
        if not install_runner(self.log):
            return False
        token = get_runner_registration_token(self.github_token, self.repo, self.log)
        if not token:
            return False
        if not configure_runner(token, self.repo, runner_name, log=self.log):
            return False
        if not start_runner(self.log):
            return False
        self.state.runner_registered = True
        self.state.runner_name = runner_name
        self.state.save()
        return True

    def write_workflow(self) -> bool:
        return write_ci_workflow(self.repo_path, self.log)

    def stop(self) -> None:
        self._quick_tunnel.stop()
        stop_runner()

    @property
    def tunnel_running(self) -> bool:
        return self._quick_tunnel.running

    @property
    def tunnel_url(self) -> str:
        return self._quick_tunnel.url or self.state.tunnel_url
