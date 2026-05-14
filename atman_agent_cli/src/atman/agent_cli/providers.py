"""
atman/agent_cli/providers.py
Runtime-switchable provider router.

Coder  : llamacpp | claude-sonnet | claude-opus
Planner: cohere   | claude-sonnet | claude-opus | llamacpp
Embedder: local (BGE-M3) | cohere
Reranker: local (bge-reranker-v2-m3) | cohere

Switch at runtime via /config:
  /config coder claude-sonnet
  /config planner cohere
  /config embedder cohere
  /config reranker local

All providers lazy-load their clients on first use.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .secrets import SecretsManager

if TYPE_CHECKING:
    from .config import AgentConfig


# ── Provider IDs ──────────────────────────────────────────────────────────────

CODER_PROVIDERS = ("llamacpp", "claude-sonnet", "claude-opus")
PLANNER_PROVIDERS = ("cohere", "claude-sonnet", "claude-opus", "llamacpp")
EMBEDDER_PROVIDERS = ("local", "cohere")
RERANKER_PROVIDERS = ("local", "cohere")

CLAUDE_MODELS = {
    "claude-sonnet": "claude-sonnet-4-6",
    "claude-opus": "claude-opus-4-6",
}
COHERE_EMBED_MODEL = "embed-multilingual-v3.0"
COHERE_RERANK_MODEL = "rerank-multilingual-v3.0"


# ── Provider config (persisted to disk) ───────────────────────────────────────


@dataclass
class ProviderConfig:
    coder: str = "llamacpp"
    planner: str = "cohere"
    embedder: str = "local"
    reranker: str = "local"

    def validate(self) -> list[str]:
        errors = []
        if self.coder not in CODER_PROVIDERS:
            errors.append(f"coder '{self.coder}' unknown")
        if self.planner not in PLANNER_PROVIDERS:
            errors.append(f"planner '{self.planner}' unknown")
        if self.embedder not in EMBEDDER_PROVIDERS:
            errors.append(f"embedder '{self.embedder}' unknown")
        if self.reranker not in RERANKER_PROVIDERS:
            errors.append(f"reranker '{self.reranker}' unknown")
        return errors

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, path: Path) -> ProviderConfig:
        if path.exists():
            try:
                return cls(**json.loads(path.read_text()))
            except Exception:
                pass
        return cls()


# ── Claude streaming client ───────────────────────────────────────────────────


def _claude_stream(
    messages: list[dict],
    model: str,
    api_key: str,
    max_tokens: int = 4096,
    system: str = "",
) -> Iterator[str]:
    try:
        import anthropic
    except ImportError:
        yield "[ERROR] anthropic package not installed: pip install anthropic\n"
        return

    if not api_key:
        yield "[ERROR] ANTHROPIC_API_KEY not set. Run: /config set anthropic_api_key sk-ant-...\n"
        return

    client = anthropic.Anthropic(api_key=api_key)
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        kwargs["system"] = system

    try:
        with client.messages.stream(**kwargs) as stream:
            for text in stream.text_stream:
                yield text
    except anthropic.AuthenticationError:
        yield "[ERROR] Invalid Anthropic API key\n"
    except anthropic.RateLimitError:
        yield "[ERROR] Anthropic rate limit hit\n"
    except Exception as e:
        yield f"[ERROR] Claude API: {e}\n"


def _claude_complete(messages, model, api_key, max_tokens=4096, system="") -> str:
    return "".join(_claude_stream(messages, model, api_key, max_tokens, system))


# ── Cohere client helpers ─────────────────────────────────────────────────────


def _get_cohere_client(api_key: str):
    if not api_key:
        raise RuntimeError("COHERE_API_KEY not set. Run: /config set cohere_api_key <key>")
    try:
        import cohere

        return cohere.Client(api_key)
    except ImportError:
        raise RuntimeError("cohere package not installed: pip install cohere")


# ── Provider Router ───────────────────────────────────────────────────────────


class ProviderRouter:
    """
    Central router for all LLM/embed/rerank calls.
    Config is mutable at runtime — switching providers takes effect immediately.
    """

    SYSTEM_CODER = """You are an expert Python developer working on the Atman project.
Atman is a psychological layer for AI agents — hexagonal architecture, Python 3.11.9.
Patterns: Pydantic models, ports/adapters, strict mypy, ruff, uv.
Never mix Core and Adapter concerns. Ports in core/ports/, implementations in adapters/.
Write complete, working, typed code. Follow DEVELOPMENT_STANDARD."""

    SYSTEM_PLANNER = """You are an expert software architect helping plan implementations
for the Atman project — a psychological layer for AI agents.
Architecture: hexagonal, Python 3.11.9, Pydantic models, ports/adapters.
Give concise, actionable plans. Be specific about files and patterns to use."""

    def __init__(
        self,
        cfg: ProviderConfig,
        secrets: SecretsManager,
        llm_url: str,
        agent_cfg: AgentConfig | None = None,
    ) -> None:
        self.cfg = cfg
        self.secrets = secrets
        self.llm_url = llm_url
        self._agent_cfg = agent_cfg  # Optional reference for config persistence
        self._embedder = None  # lazy
        self._reranker = None  # lazy

    # ── Coder ─────────────────────────────────────────────────────────────────

    def code_stream(self, prompt: str, context: str = "") -> Iterator[str]:
        """Stream coding response from configured coder."""
        messages = self._build_messages(prompt, context)
        yield from self._route_coder_stream(messages)

    def code_complete(self, prompt: str, context: str = "") -> str:
        return "".join(self.code_stream(prompt, context))

    def _route_coder_stream(self, messages: list[dict]) -> Iterator[str]:
        provider = self.cfg.coder

        if provider == "llamacpp":
            yield from self._llamacpp_stream(messages)
        elif provider in ("claude-sonnet", "claude-opus"):
            yield from _claude_stream(
                messages,
                model=CLAUDE_MODELS[provider],
                api_key=self.secrets.anthropic_api_key,
                system=self.SYSTEM_CODER,
            )
        else:
            yield f"[ERROR] Unknown coder provider: {provider}\n"

    def _llamacpp_stream(self, messages: list[dict]) -> Iterator[str]:
        import json as _json

        import requests

        try:
            r = requests.post(
                f"{self.llm_url}/v1/chat/completions",
                json={
                    "messages": [{"role": "system", "content": self.SYSTEM_CODER}] + messages,
                    "max_tokens": 4096,
                    "temperature": 0.2,
                    "stream": True,
                },
                timeout=120,
                stream=True,
            )
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                line = line.decode("utf-8")
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = _json.loads(data)
                        delta = chunk["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield delta
                    except Exception:
                        continue
        except requests.exceptions.ConnectionError:
            yield (
                f"\n[ERROR] llama.cpp not reachable at {self.llm_url}\n"
                f"Start: llama-server --model <model.gguf> --port 8080 --n-gpu-layers 35\n"
                f"Or switch: /config coder claude-sonnet\n"
            )

    # ── Planner ───────────────────────────────────────────────────────────────

    def plan(self, task: str, context: str = "") -> str:
        prompt = (
            f"Create a detailed implementation plan for this Atman task:\n\n{task}"
            + (f"\n\nContext from codebase:\n{context}" if context else "")
            + "\n\nProvide: summary, files to modify/create, ordered steps, test strategy."
        )
        return self._route_planner(prompt)

    def discuss(self, message: str, history: list[dict], context: str = "") -> str:
        """Planning mode discussion with full history."""
        return self._route_planner_chat(message, history, context)

    def analyze(self, prompt: str) -> str:
        """Generic analysis (review comments, CI failures, etc.)."""
        return self._route_planner(prompt)

    def _route_planner(self, prompt: str) -> str:
        provider = self.cfg.planner

        if provider == "cohere":
            try:
                co = _get_cohere_client(self.secrets.cohere_api_key)
                resp = co.chat(
                    message=prompt,
                    model="command-r-plus",
                    preamble=self.SYSTEM_PLANNER,
                    temperature=0.3,
                )
                return resp.text
            except Exception as e:
                return f"[Cohere error: {e}]\nFalling back to local...\n" + self.code_complete(
                    prompt
                )

        elif provider in ("claude-sonnet", "claude-opus"):
            return _claude_complete(
                [{"role": "user", "content": prompt}],
                model=CLAUDE_MODELS[provider],
                api_key=self.secrets.anthropic_api_key,
                system=self.SYSTEM_PLANNER,
            )

        elif provider == "llamacpp":
            return self.code_complete(prompt)

        return f"[ERROR] Unknown planner provider: {provider}"

    def _route_planner_chat(self, message: str, history: list[dict], context: str) -> str:
        provider = self.cfg.planner

        if provider == "cohere":
            try:
                co = _get_cohere_client(self.secrets.cohere_api_key)
                chat_history = [{"role": m["role"], "message": m["content"]} for m in history[:-1]]
                resp = co.chat(
                    message=message,
                    model="command-r-plus",
                    chat_history=chat_history,
                    preamble=self.SYSTEM_PLANNER,
                    temperature=0.3,
                )
                return resp.text
            except Exception as e:
                return f"[Cohere error: {e}]"

        elif provider in ("claude-sonnet", "claude-opus"):
            messages = [{"role": m["role"], "content": m["content"]} for m in history]
            if context and messages:
                messages[-1]["content"] = (
                    f"<context>\n{context}\n</context>\n\n{messages[-1]['content']}"
                )
            return _claude_complete(
                messages,
                model=CLAUDE_MODELS[provider],
                api_key=self.secrets.anthropic_api_key,
                system=self.SYSTEM_PLANNER,
            )

        # fallback: llamacpp
        return self.code_complete(message, context)

    # ── Embedder ──────────────────────────────────────────────────────────────

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        """Embed texts using configured embedder."""
        if self.cfg.embedder == "local":
            return self._embed_local(texts)
        elif self.cfg.embedder == "cohere":
            return self._embed_cohere(texts)
        return None

    def _embed_local(self, texts: list[str]) -> list[list[float]] | None:
        if self._embedder is None:
            try:
                from FlagEmbedding import BGEM3FlagModel

                self._embedder = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
            except Exception:
                return None
        try:
            result = self._embedder.encode(texts, batch_size=32)
            return result["dense_vecs"].tolist()
        except Exception:
            return None

    def _embed_cohere(self, texts: list[str]) -> list[list[float]] | None:
        try:
            co = _get_cohere_client(self.secrets.cohere_api_key)
            resp = co.embed(
                texts=texts,
                model=COHERE_EMBED_MODEL,
                input_type="search_document",
            )
            return resp.embeddings
        except Exception:
            return None

    # ── Reranker ──────────────────────────────────────────────────────────────

    def rerank(self, query: str, passages: list[str], top_n: int) -> list[float]:
        """Rerank passages. Returns scores list (same length as passages)."""
        if self.cfg.reranker == "local":
            return self._rerank_local(query, passages)
        elif self.cfg.reranker == "cohere":
            return self._rerank_cohere(query, passages, top_n)
        return [0.0] * len(passages)

    def _rerank_local(self, query: str, passages: list[str]) -> list[float]:
        if self._reranker is None:
            try:
                from FlagEmbedding import FlagReranker

                self._reranker = FlagReranker("BAAI/bge-reranker-v2-m3", use_fp16=True)
            except Exception:
                return [0.0] * len(passages)
        try:
            pairs = [[query, p] for p in passages]
            scores = self._reranker.compute_score(pairs, normalize=True)
            return scores if isinstance(scores, list) else [scores]
        except Exception:
            return [0.0] * len(passages)

    def _rerank_cohere(self, query: str, passages: list[str], top_n: int) -> list[float]:
        try:
            co = _get_cohere_client(self.secrets.cohere_api_key)
            model = COHERE_RERANK_MODEL
            ac = getattr(self, "_agent_cfg", None)
            if ac is not None:
                override = getattr(ac, "cohere_rerank_model", None)
                if isinstance(override, str) and override.strip():
                    model = override.strip()
            resp = co.rerank(
                query=query,
                documents=passages,
                model=model,
                top_n=top_n,
            )
            scores = [0.0] * len(passages)
            for r in resp.results:
                scores[r.index] = r.relevance_score
            return scores
        except Exception:
            return [0.0] * len(passages)

    # ── Switch helpers ────────────────────────────────────────────────────────

    def switch(self, role: str, provider: str) -> tuple[bool, str]:
        """
        Switch a provider at runtime.
        Returns (success, message).
        """
        role = role.lower()
        provider = provider.lower()

        valid = {
            "coder": CODER_PROVIDERS,
            "planner": PLANNER_PROVIDERS,
            "embedder": EMBEDDER_PROVIDERS,
            "reranker": RERANKER_PROVIDERS,
        }
        if role not in valid:
            return False, f"Unknown role '{role}'. Options: {', '.join(valid)}"
        if provider not in valid[role]:
            return False, f"Unknown provider '{provider}'. Options: {', '.join(valid[role])}"

        # Check if required key is available
        if provider in ("claude-sonnet", "claude-opus") and not self.secrets.anthropic_api_key:
            return False, "ANTHROPIC_API_KEY not set. Run: /config set anthropic_api_key <key>"
        if provider == "cohere" and not self.secrets.cohere_api_key:
            return False, "COHERE_API_KEY not set. Run: /config set cohere_api_key <key>"

        setattr(self.cfg, role, provider)

        # Reset cached clients when switching embed/rerank
        if role == "embedder":
            self._embedder = None
        if role == "reranker":
            self._reranker = None

        return True, f"{role} → {provider}"

    def status_table(self) -> list[tuple[str, str, str]]:
        """Returns list of (role, current_provider, available_providers)."""
        return [
            ("coder", self.cfg.coder, " | ".join(CODER_PROVIDERS)),
            ("planner", self.cfg.planner, " | ".join(PLANNER_PROVIDERS)),
            ("embedder", self.cfg.embedder, " | ".join(EMBEDDER_PROVIDERS)),
            ("reranker", self.cfg.reranker, " | ".join(RERANKER_PROVIDERS)),
        ]

    def update_llm_url(self, new_url: str) -> None:
        """Update llama.cpp server URL without restart."""
        self.llm_url = new_url
        ac = getattr(self, "_agent_cfg", None)
        if ac is not None:
            ac.llm_url = new_url
            ac.save_settings()

    def get_sidebar_info(self) -> dict[str, str]:
        """Compact provider summary for TUI sidebars."""
        parts = self.llm_url.split("/")
        host = parts[2] if len(parts) > 2 else self.llm_url
        return {
            "coder": f"{self.cfg.coder} @ {host}",
            "planner": self.cfg.planner,
            "embedder": self.cfg.embedder,
            "reranker": self.cfg.reranker,
        }

    def plan_with_documents(
        self,
        user_message: str,
        rag_chunks: list,
    ) -> tuple[str, list[dict]]:
        """
        Planner with optional RAG chunks as grounded documents (Cohere citations).

        Returns (answer text, citations) where each citation is
        {"source": "path:line", "text": "..."}.
        """
        if self.cfg.planner != "cohere":
            context = "\n\n".join(
                f"[{c.path}:{c.start_line}]\n{getattr(c, 'window_content', c.content)}"
                for c in rag_chunks
            )
            full_message = f"{context}\n\n{user_message}"
            return self._route_planner(full_message), []

        try:
            co = _get_cohere_client(self.secrets.cohere_api_key)

            def _chunk_metadata(chunk: object) -> dict:
                md = getattr(chunk, "metadata", None)
                if isinstance(md, dict):
                    return md
                return {}

            response = co.chat(
                model="command-a-03-2025",
                message=user_message,
                documents=[
                    {
                        "id": str(i),
                        "data": {
                            "text": getattr(c, "window_content", c.content),
                            "source": f"{c.path}:{c.start_line}",
                            "type": _chunk_metadata(c).get("type", "code"),
                        },
                    }
                    for i, c in enumerate(rag_chunks)
                ],
                preamble=self.SYSTEM_PLANNER,
            )

            answer = getattr(response, "text", "") or ""

            citations: list[dict[str, str]] = []
            raw_citations = getattr(response, "citations", None) or []
            for citation in raw_citations:
                doc_ids = getattr(citation, "document_ids", None) or []
                start = getattr(citation, "start", None)
                end = getattr(citation, "end", None)
                if start is None or end is None:
                    continue
                snippet = answer[start:end]
                for doc_id in doc_ids:
                    try:
                        idx = int(doc_id)
                        if idx < len(rag_chunks):
                            chunk = rag_chunks[idx]
                            citations.append(
                                {
                                    "source": f"{chunk.path}:{chunk.start_line}",
                                    "text": snippet,
                                }
                            )
                    except (ValueError, TypeError):
                        continue

            return answer, citations

        except Exception as e:
            return f"[Cohere error: {e}]", []

    def _build_messages(self, prompt: str, context: str) -> list[dict]:
        content = f"<context>\n{context}\n</context>\n\n{prompt}" if context else prompt
        return [{"role": "user", "content": content}]
