"""
atman/agent_cli/webhook.py
Tiny webhook server for GitHub events.
Listens for pull_request (merged) and push (to main).
Triggers MainWatcher.sync() — no LLM, just records the event.

Setup in GitHub:
  Settings → Webhooks → Add webhook
  Payload URL: http://<your-ip>:<port>/webhook
  Content type: application/json
  Secret: set ATMAN_WEBHOOK_SECRET env var
  Events: Pull requests, Pushes

Or expose via ngrok for local dev:
  ngrok http 9876
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .main_watcher import MainWatcher

log = logging.getLogger("atman.webhook")


class WebhookHandler(BaseHTTPRequestHandler):
    """Handle incoming GitHub webhook events."""

    watcher: "MainWatcher"
    secret: str = ""
    main_branch: str = "main"

    def log_message(self, format, *args) -> None:
        log.debug(f"Webhook: {format % args}")

    def do_POST(self) -> None:
        if self.path != "/webhook":
            self._respond(404, "Not found")
            return

        # Read body
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        # Verify signature if secret is configured
        if self.secret:
            sig_header = self.headers.get("X-Hub-Signature-256", "")
            expected = "sha256=" + hmac.new(
                self.secret.encode(), body, hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(sig_header, expected):
                log.warning("Webhook signature mismatch")
                self._respond(401, "Unauthorized")
                return

        # Parse event
        event_type = self.headers.get("X-GitHub-Event", "")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self._respond(400, "Invalid JSON")
            return

        self._respond(200, "OK")  # respond fast, process async

        # Handle in background thread so webhook doesn't timeout
        threading.Thread(
            target=self._handle_event,
            args=(event_type, payload),
            daemon=True,
        ).start()

    def _respond(self, code: int, message: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(message.encode())

    def _handle_event(self, event_type: str, payload: dict) -> None:
        try:
            if event_type == "pull_request":
                self._handle_pr(payload)
            elif event_type == "push":
                self._handle_push(payload)
        except Exception as e:
            log.error(f"Webhook handler error: {e}")

    def _handle_pr(self, payload: dict) -> None:
        action = payload.get("action")
        pr = payload.get("pull_request", {})

        if action != "closed" or not pr.get("merged"):
            return  # only care about merges

        base = pr.get("base", {}).get("ref", "")
        if base != self.main_branch:
            return  # merge to non-main, ignore

        pr_number = pr.get("number")
        pr_title = pr.get("title", "")
        merger = pr.get("merged_by", {}).get("login", "unknown")

        log.info(f"PR #{pr_number} merged to {self.main_branch} by {merger}: {pr_title}")

        # Determine source: if merged_by is a bot/agent → self_merge, else external
        source = "self_merge" if merger in ("github-actions[bot]", "atman-agent") \
                 else "external_merge"

        self.watcher.sync(
            source=source,
            pr_number=pr_number,
            pr_title=pr_title,
        )

    def _handle_push(self, payload: dict) -> None:
        ref = payload.get("ref", "")
        if ref != f"refs/heads/{self.main_branch}":
            return  # not a push to main

        # Direct push to main (not via PR) — record it
        commits = payload.get("commits", [])
        pusher = payload.get("pusher", {}).get("name", "unknown")
        log.info(f"Direct push to {self.main_branch} by {pusher}: {len(commits)} commit(s)")

        self.watcher.sync(source="external_merge")


class WebhookServer:
    """
    Wrapper around HTTPServer for GitHub webhooks.
    Runs in daemon thread alongside the agent CLI.
    """

    def __init__(
        self,
        watcher: "MainWatcher",
        port: int = 9876,
        secret: str = "",
        main_branch: str = "main",
    ) -> None:
        self.port = port
        self._watcher = watcher

        # Inject watcher and config into handler class
        class ConfiguredHandler(WebhookHandler):
            pass

        ConfiguredHandler.watcher = watcher
        ConfiguredHandler.secret = secret
        ConfiguredHandler.main_branch = main_branch

        self._server = HTTPServer(("0.0.0.0", port), ConfiguredHandler)
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start webhook server in daemon thread."""
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="webhook-server",
        )
        self._thread.start()
        log.info(f"Webhook server listening on port {self.port}")
        log.info(f"Set GitHub webhook URL: http://<your-ip>:{self.port}/webhook")

    def stop(self) -> None:
        self._server.shutdown()
