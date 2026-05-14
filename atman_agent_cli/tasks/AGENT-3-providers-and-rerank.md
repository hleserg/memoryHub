# AGENT-3 — Providers: config fields + update_llm_url + Cohere citations

## Контекст

Файлы уже написаны:
- `atman_agent_cli/src/atman/agent_cli/providers.py` (~429 строк) — `ProviderRouter` с полным набором методов
- `atman_agent_cli/src/atman/agent_cli/config.py` (~117 строк) — `AgentConfig` с полями

**Только добавить/изменить — не переписывать файлы.**

AGENT-2 расширяет `RAGIndex` — при wire-up в TASK-2.9 используй метод `_hybrid_search`.

---

## TASK-1.4 — Добавить RAG-веса и missing поля в config.py

**В `AgentConfig`** — добавить после существующих RAG-полей (`rag_top_k`, `rag_top_n`):

```python
# RAG hybrid weights
rag_dense_weight: float = field(
    default_factory=lambda: float(os.getenv('ATMAN_RAG_DENSE_WEIGHT', '0.4'))
)
rag_sparse_weight: float = field(
    default_factory=lambda: float(os.getenv('ATMAN_RAG_SPARSE_WEIGHT', '0.2'))
)
rag_colbert_weight: float = field(
    default_factory=lambda: float(os.getenv('ATMAN_RAG_COLBERT_WEIGHT', '0.4'))
)
rag_candidates_k: int = field(
    default_factory=lambda: int(os.getenv('ATMAN_RAG_CANDIDATES_K', '40'))
)
rag_final_k: int = field(
    default_factory=lambda: int(os.getenv('ATMAN_RAG_FINAL_K', '6'))
)
rag_window_lines: int = field(
    default_factory=lambda: int(os.getenv('ATMAN_RAG_WINDOW_LINES', '10'))
)
rag_stale_hours: float = field(
    default_factory=lambda: float(os.getenv('ATMAN_RAG_STALE_HOURS', '4'))
)
cohere_rerank_model: str = 'rerank-multilingual-v3.0'
```

**Добавить в `PERSIST_KEYS`** в `save_settings()`:
```python
'rag_dense_weight', 'rag_sparse_weight', 'rag_colbert_weight',
'rag_candidates_k', 'rag_final_k', 'rag_window_lines', 'rag_stale_hours',
'cohere_rerank_model',
```

---

## TASK-1.4 (providers) — update_llm_url + get_sidebar_info

`ProviderRouter.__init__` уже принимает `llm_url`. Добавить методы:

```python
class ProviderRouter:
    # ... существующий код без изменений ...

    def update_llm_url(self, new_url: str) -> None:
        """Обновить URL llama.cpp без рестарта."""
        self.llm_url = new_url
        # Сохранить в settings если cfg — AgentConfig
        if hasattr(self, '_agent_cfg'):
            self._agent_cfg.llm_url = new_url
            self._agent_cfg.save_settings()

    def get_sidebar_info(self) -> dict:
        """Для отображения в sidebar TUI."""
        host = self.llm_url.split('/')[2] if '/' in self.llm_url else self.llm_url
        return {
            'coder':    f"{self.cfg.coder} @ {host}",
            'planner':  self.cfg.planner,
            'embedder': self.cfg.embedder,
            'reranker': self.cfg.reranker,
        }
```

**CLI Integration Notes (для AGENT-7):**
> `/config set llm_url http://...` → `router.update_llm_url(url)` → обновить sidebar.

---

## TASK-2.8 — Cohere grounded citations

**Добавить в `ProviderRouter`:**

```python
def plan_with_documents(
    self,
    user_message: str,
    rag_chunks: list,  # объекты Chunk с .id, .window_content, .path, .start_line
) -> tuple[str, list[dict]]:
    """
    Возвращает (ответ, citations).
    citations: [{"source": "path:line", "text": "..."}]
    """
    if self.cfg.planner != 'cohere':
        # Fallback: вставить чанки в контекст
        context = "\n\n".join(
            f"[{c.path}:{c.start_line}]\n{getattr(c, 'window_content', c.content)}"
            for c in rag_chunks
        )
        full_message = f"{context}\n\n{user_message}"
        return self._route_planner(full_message), []

    try:
        co = _get_cohere_client(self.secrets.cohere_api_key)
        response = co.chat(
            model="command-a-03-2025",
            message=user_message,
            documents=[
                {
                    "id": str(i),
                    "data": {
                        "text": getattr(c, 'window_content', c.content),
                        "source": f"{c.path}:{c.start_line}",
                        "type": getattr(c, 'metadata', {}).get('type', 'code'),
                    }
                }
                for i, c in enumerate(rag_chunks)
            ],
            preamble=self.SYSTEM_PLANNER,
        )

        citations = []
        for citation in (response.citations or []):
            for doc_id in citation.document_ids:
                try:
                    idx = int(doc_id)
                    if idx < len(rag_chunks):
                        c = rag_chunks[idx]
                        citations.append({
                            "source": f"{c.path}:{c.start_line}",
                            "text": response.text[citation.start:citation.end],
                        })
                except (ValueError, AttributeError):
                    continue

        return response.text, citations

    except Exception as e:
        return f"[Cohere error: {e}]", []
```

**CLI Integration Notes (для AGENT-7):**
> В plan mode: `text, citations = router.plan_with_documents(msg, rag_chunks)`.
> После ответа показать: `📎 Sources: git.py:12, executor.py:87`.

---

## TASK-2.9 — Rerank wire-up (уже реализован в rag.py)

`RAGIndex` уже имеет `_rerank()` с локальным `FlagReranker`.
`ProviderRouter.rerank()` возвращает `list[float]` (scores).

**Дополнительно** — если нужно использовать `ProviderRouter.rerank` вместо встроенного:
Добавить в `RAGIndex.__init__`: `self.router: ProviderRouter | None = None` (optional).

В `_rerank()` — проверять router:
```python
def _rerank(self, query: str, candidates: list[Chunk], top_n: int) -> list[Chunk]:
    if self.router and self.router.cfg.reranker == 'cohere':
        passages = [c.content for c in candidates]
        scores = self.router.rerank(query, passages, top_n)
        ranked = sorted(zip(scores, candidates), reverse=True)
        return [c for _, c in ranked[:top_n]]

    # Существующий код с FlagReranker:
    if self._reranker:
        pairs = [[query, c.content] for c in candidates]
        scores = self._reranker.compute_score(pairs, normalize=True)
        ranked = sorted(zip(scores, candidates), reverse=True)
        return [c for _, c in ranked[:top_n]]

    return candidates[:top_n]
```
