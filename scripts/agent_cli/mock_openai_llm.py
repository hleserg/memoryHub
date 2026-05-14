#!/usr/bin/env python3
"""
Minimal OpenAI-compatible HTTP stub for coder=llamacpp (streaming SSE).

Use while the real GGUF/server trains or downloads:
  PYTHONPATH=atman_agent_cli/src:src ATMAN_LLM_URL=http://127.0.0.1:18080 \\
    python -m textual  # … or launch the TUI with LLM pointing here

Not for production security — binds loopback only by default.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def _sse_chunk(content: str) -> bytes:
    payload: dict[str, Any] = {
        "choices": [{"delta": {"content": content}, "finish_reason": None, "index": 0}],
        "created": 0,
        "id": "stub",
        "model": "mock",
        "object": "chat.completion.chunk",
    }
    line = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    return line.encode("utf-8")


class _Handler(BaseHTTPRequestHandler):
    server_version = "mock-openai-llm/0.1"
    stub_text: str = "[mock-llm] Replace with real llama-server when ready."

    def log_message(self, fmt: str, *args: object) -> None:
        """Less noisy stderr."""
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/v1/models" or path.endswith("/v1/models"):
            body = {
                "object": "list",
                "data": [{"id": "mock-model", "object": "model", "owned_by": "stub"}],
            }
            self._send_json(200, body)
            return

        if path in ("/", "/health"):
            self._send_json(
                200,
                {"status": "ok", "service": "mock_openai_llm", "hint": "/v1/chat/completions"},
            )
            return

        self._send_json(404, {"error": "not_found", "path": self.path})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not parsed.path.rstrip("/").endswith("/v1/chat/completions"):
            self._send_json(404, {"error": "not_found", "path": self.path})
            return

        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            body = {}

        messages = body.get("messages") or []
        preview = ""
        if isinstance(messages, list) and messages:
            last = messages[-1]
            if isinstance(last, dict):
                preview = str(last.get("content", ""))[:200]

        use_stream = bool(body.get("stream"))
        reply = f"{self.stub_text}\n\n[user last message excerpt]\n{preview}\n".strip()

        if not use_stream:
            full: dict[str, Any] = {
                "choices": [{"message": {"role": "assistant", "content": reply}, "index": 0}],
                "model": body.get("model") or "mock-model",
                "object": "chat.completion",
                "id": "stub-complete",
                "created": 0,
            }
            self._send_json(200, full)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        for char in reply:
            self.wfile.write(_sse_chunk(char))
        self.wfile.write(_sse_chunk(""))
        done = b"data: [DONE]\n\n"
        self.wfile.write(done)

    def _send_json(self, code: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> int:
    p = argparse.ArgumentParser(description="Mock OpenAI-compatible LLM HTTP server.")
    p.add_argument("--bind", default="127.0.0.1", help="Listen address.")
    p.add_argument("--port", type=int, default=18080, help="Listen port.")
    p.add_argument(
        "--stub-file",
        type=Path,
        help="UTF-8 file whose contents replace default stub assistant text.",
    )
    args = p.parse_args()

    if args.stub_file is not None:
        _Handler.stub_text = args.stub_file.read_text(encoding="utf-8")

    srv = ThreadingHTTPServer((args.bind, args.port), _Handler)
    msg = (
        f"mock_openai_llm listening on http://{args.bind}:{args.port}\n"
        f"Try: curl -s http://{args.bind}:{args.port}/v1/models | head\n"
        f"Set ATMAN_LLM_URL=http://{args.bind}:{args.port} for agent_cli.\n"
        "Ctrl+C to stop.\n"
    )
    print(msg, end="", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
