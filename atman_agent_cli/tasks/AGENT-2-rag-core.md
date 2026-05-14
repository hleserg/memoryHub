# AGENT-2 — RAG core: hybrid search + chunking + index

## Контекст

Файл уже написан: `atman_agent_cli/src/atman/agent_cli/rag.py` (~321 строка).
`RAGIndex` существует: dense-only search через BGE-M3, bge-reranker, incremental update.

**Порядок изменений важен — каждый шаг зависит от предыдущего:**
1. TASK-2.4 — расширить `Chunk` (все остальные от этого зависят)
2. TASK-2.6 — tree-sitter chunking
3. TASK-2.1 — hybrid search (sparse + ColBERT)
4. TASK-2.7 — symbol index
5. TASK-2.3 — QueryFusion
6. TASK-2.5 — `check_staleness()` + wire-up в новом `sync.py`

---

## TASK-2.4 — Sentence Window + расширение Chunk

**Изменить dataclass `Chunk`** — добавить поля (не удалять существующие):

```python
@dataclass
class Chunk:
    path: str
    content: str          # мелкий чанк для поиска
    start_line: int
    chunk_index: int
    file_hash: str
    # --- новые поля ---
    window_content: str = ""   # расширенное окно ±N строк для инъекции в LLM
    window_start: int = 0
    window_end: int = 0
    metadata: dict = field(default_factory=dict)
    # metadata keys: language, type (function/class/...), name

    @property
    def id(self) -> str:
        return f"{self.path}::{self.chunk_index}"
    # ... остальные методы без изменений
```

**Добавить в `RAGIndex`** — хранить строки файлов для быстрого расширения:

```python
class RAGIndex:
    def __init__(self, cfg):
        # ... существующий __init__ ...
        self.window_lines: int = getattr(cfg, 'rag_window_lines', 10)
        self._file_lines_cache: dict[str, list[str]] = {}  # path → lines

    def _get_file_lines(self, path: str) -> list[str]:
        if path not in self._file_lines_cache:
            try:
                full = (self.cfg.repo_path / path) if not path.startswith('/') else Path(path)
                self._file_lines_cache[path] = Path(full).read_text(errors='ignore').splitlines()
            except Exception:
                self._file_lines_cache[path] = []
        return self._file_lines_cache[path]

    def _expand_to_window(self, path: str, start_line: int, end_line: int) -> tuple[str, int, int]:
        """Возвращает (window_content, window_start, window_end)."""
        lines = self._get_file_lines(path)
        w_start = max(0, start_line - self.window_lines)
        w_end = min(len(lines), end_line + self.window_lines)
        return '\n'.join(lines[w_start:w_end]), w_start, w_end
```

**Обновить `_chunk_text`** — при создании чанков добавлять `window_content`:

В методе `build()` и `update()` при создании `Chunk(...)` — добавить вычисление window:
```python
end_line = start_line + chunk_text.count('\n')
window_content, w_start, w_end = self._expand_to_window(rel, start_line - 1, end_line)
chunk = Chunk(
    path=rel, content=chunk_text, start_line=start_line,
    chunk_index=j, file_hash=h,
    window_content=window_content, window_start=w_start, window_end=w_end,
)
```

**Auto-Merging:** Если ≥3 чанка из одного файла попали в top-K → заменить на один большой чанк:
```python
def _merge_chunks_from_same_file(self, chunks: list[Chunk]) -> list[Chunk]:
    from collections import defaultdict
    by_file: dict[str, list[Chunk]] = defaultdict(list)
    for c in chunks:
        by_file[c.path].append(c)

    result = []
    for path, file_chunks in by_file.items():
        if len(file_chunks) >= 3:
            lines = self._get_file_lines(path)
            min_line = min(c.window_start for c in file_chunks)
            max_line = max(c.window_end for c in file_chunks)
            merged_content = '\n'.join(lines[min_line:max_line])
            merged = Chunk(
                path=path, content=merged_content, start_line=min_line,
                chunk_index=0, file_hash=file_chunks[0].file_hash,
                window_content=merged_content, window_start=min_line, window_end=max_line,
            )
            result.append(merged)
        else:
            result.extend(file_chunks)
    return result
```
Вызывать в `search()` перед rerank.

---

## TASK-2.6 — Tree-sitter chunking (AST-aware)

**Зависимости:** `tree-sitter>=0.21`, `tree-sitter-python`, `tree-sitter-javascript`, `tree-sitter-typescript`.

**Добавить в `RAGIndex`:**

```python
SUPPORTED_LANGS = {'.py': 'python', '.js': 'javascript', '.ts': 'typescript',
                   '.jsx': 'javascript', '.tsx': 'typescript'}
AST_NODE_TYPES = {
    'function_definition', 'class_definition', 'decorated_definition',
    'function_declaration', 'method_definition',
}

def _detect_language(self, path: Path) -> str | None:
    return SUPPORTED_LANGS.get(path.suffix.lower())

def _get_parser(self, lang: str):
    if not hasattr(self, '_parsers'):
        self._parsers = {}
    if lang not in self._parsers:
        from tree_sitter import Language, Parser
        import tree_sitter_python, tree_sitter_javascript, tree_sitter_typescript
        lang_map = {
            'python': tree_sitter_python.language(),
            'javascript': tree_sitter_javascript.language(),
            'typescript': tree_sitter_typescript.language_typescript(),
        }
        parser = Parser(Language(lang_map[lang]))
        self._parsers[lang] = parser
    return self._parsers[lang]

def _extract_node_name(self, node) -> str:
    for child in node.children:
        if child.type in ('identifier', 'name'):
            return child.text.decode('utf-8', errors='replace')
    return ''

def _chunk_by_ast(self, path: Path, content: str, rel: str) -> list[Chunk]:
    lang = self._detect_language(path)
    if not lang:
        return self._chunk_by_size_named(content, rel, path)

    try:
        parser = self._get_parser(lang)
    except Exception:
        return self._chunk_by_size_named(content, rel, path)

    tree = parser.parse(content.encode())
    h = self._file_hash(path)
    chunks = []

    for j, node in enumerate(tree.root_node.children):
        if node.type in AST_NODE_TYPES:
            chunk_content = content[node.start_byte:node.end_byte]
            start_line = node.start_point[0]
            end_line = node.end_point[0]
            window_content, w_start, w_end = self._expand_to_window(rel, start_line, end_line)
            chunks.append(Chunk(
                path=rel, content=chunk_content, start_line=start_line + 1,
                chunk_index=j, file_hash=h,
                window_content=window_content, window_start=w_start, window_end=w_end,
                metadata={
                    'language': lang,
                    'type': node.type,
                    'name': self._extract_node_name(node),
                }
            ))

    return chunks if chunks else self._chunk_by_size_named(content, rel, path)

def _chunk_by_size_named(self, content: str, rel: str, path: Path) -> list[Chunk]:
    """Существующий _chunk_text, но возвращает Chunk объекты."""
    h = self._file_hash(path)
    result = []
    for j, (chunk_text, start_line) in enumerate(self._chunk_text(content, rel)):
        end_line = start_line + chunk_text.count('\n')
        window_content, w_start, w_end = self._expand_to_window(rel, start_line - 1, end_line)
        result.append(Chunk(
            path=rel, content=chunk_text, start_line=start_line,
            chunk_index=j, file_hash=h,
            window_content=window_content, window_start=w_start, window_end=w_end,
        ))
    return result
```

**Обновить `build()` и `update()`:** заменить вызов `_chunk_text(...)` на `_chunk_by_ast(path, text, rel)`.

---

## TASK-2.1 — Гибридный поиск BGE-M3 (dense + sparse + ColBERT)

**Добавить в `AgentConfig`** (или читать из config с дефолтами в RAGIndex):
Веса `dense_weight=0.4`, `sparse_weight=0.2`, `colbert_weight=0.4` и `rag_candidates_k=40`.

**Изменить `build()` / `update()`** — сохранять все три типа эмбеддингов:

```python
# При индексировании:
output = self._embedder.encode(
    [chunk.content for chunk in new_chunks],
    return_dense=True, return_sparse=True, return_colbert_vecs=True,
    batch_size=12,
)
# Сохранять:
# embeddings.npy        — dense (уже есть)
# sparse_weights.jsonl  — list[dict] lexical weights
# colbert_vecs.npy      — float16 multi-vectors (padded/stored as ragged)
```

**Добавить вспомогательные методы:**

```python
def _sparse_score(self, query_weights: dict) -> 'np.ndarray':
    """Dot product между lexical_weights запроса и индексными sparse весами."""
    import numpy as np
    scores = np.zeros(len(self._chunks))
    for token, q_weight in query_weights.items():
        for i, chunk_weights in enumerate(self._sparse_weights):
            if token in chunk_weights:
                scores[i] += q_weight * chunk_weights[token]
    return scores

def _colbert_score(self, query_vecs: 'np.ndarray') -> 'np.ndarray':
    """MaxSim: для каждого токена запроса — max cos sim со всеми токенами чанка."""
    import numpy as np
    scores = np.zeros(len(self._chunks))
    for i, chunk_vecs in enumerate(self._colbert_vecs):
        if chunk_vecs is None or len(chunk_vecs) == 0:
            continue
        chunk_arr = np.array(chunk_vecs)
        # (Q_tokens, D_tokens) similarity matrix
        sims = query_vecs @ chunk_arr.T  # assumes normalized
        scores[i] = float(sims.max(axis=1).sum())
    return scores
```

**Добавить `_hybrid_search`** (заменяет `_dense_search` как основной метод):

```python
def _hybrid_search(self, query: str, top_k: int = 40) -> list[tuple[Chunk, float]]:
    if not self._embedder or not self._embeddings:
        return [(c, 0.0) for c in self._keyword_search(query, top_k)]

    import numpy as np
    q_out = self._embedder.encode(
        [query], return_dense=True, return_sparse=True, return_colbert_vecs=True
    )
    q_dense = q_out['dense_vecs'][0]
    q_sparse = q_out['lexical_weights'][0]
    q_colbert = q_out['colbert_vecs'][0]

    emb_matrix = np.array(self._embeddings)
    q_norm = q_dense / (np.linalg.norm(q_dense) + 1e-10)
    norms = np.linalg.norm(emb_matrix, axis=1, keepdims=True) + 1e-10
    dense_scores = (emb_matrix / norms) @ q_norm

    sparse_scores = self._sparse_score(q_sparse)
    colbert_scores = self._colbert_score(np.array(q_colbert))

    dw = getattr(self.cfg, 'rag_dense_weight', 0.4)
    sw = getattr(self.cfg, 'rag_sparse_weight', 0.2)
    cw = getattr(self.cfg, 'rag_colbert_weight', 0.4)
    final = dw * dense_scores + sw * sparse_scores + cw * colbert_scores

    top_indices = np.argsort(final)[-top_k:][::-1]
    return [(self._chunks[i], float(final[i])) for i in top_indices]
```

**Обновить `search()`** — использовать `_hybrid_search` вместо `_dense_search`:
```python
def search(self, query: str, top_k=None, top_n=None) -> list[Chunk]:
    k = top_k or getattr(self.cfg, 'rag_candidates_k', self.cfg.rag_top_k)
    n = top_n or self.cfg.rag_top_n

    candidates_with_scores = self._hybrid_search(query, top_k=k)
    candidates = [c for c, _ in candidates_with_scores]
    candidates = self._merge_chunks_from_same_file(candidates)

    if self._reranker and len(candidates) > n:
        return self._rerank(query, candidates, n)
    return candidates[:n]
```

**Обновить `_save_index` / `_load_index`** — добавить сохранение/загрузку sparse и colbert данных.

---

## TASK-2.7 — Символьный индекс

```python
# Добавить в RAGIndex:

SYMBOL_INDEX_PATH_NAME = "symbol_index.json"

def _build_symbol_index(self) -> None:
    """Строит {name: [{path, line, type}]} по metadata чанков."""
    import json
    index: dict[str, list[dict]] = {}
    for chunk in self._chunks:
        name = chunk.metadata.get('name')
        if name:
            index.setdefault(name, []).append({
                'path': chunk.path,
                'line': chunk.start_line,
                'type': chunk.metadata.get('type', 'unknown'),
            })
    self._symbol_index = index
    (self.index_path / SYMBOL_INDEX_PATH_NAME).write_text(
        json.dumps(index, ensure_ascii=False), encoding='utf-8'
    )

def _load_symbol_index(self) -> None:
    import json
    path = self.index_path / SYMBOL_INDEX_PATH_NAME
    if path.exists():
        try:
            self._symbol_index = json.loads(path.read_text())
        except Exception:
            self._symbol_index = {}
    else:
        self._symbol_index = {}

def symbol_search(self, name: str) -> list[Chunk]:
    """O(1) поиск по имени функции/класса."""
    entries = self._symbol_index.get(name, [])
    results = []
    for e in entries:
        # Найти чанк в индексе
        for chunk in self._chunks:
            if chunk.path == e['path'] and chunk.start_line == e['line']:
                results.append(chunk)
                break
    return results
```

Вызвать `_build_symbol_index()` в конце `build()` и `update()`.
Вызвать `_load_symbol_index()` в `_load_index()`.

**В `search()`** — сначала символьный поиск, потом гибридный, дедуплицировать по `chunk.id`:
```python
def search(self, query: str, ...):
    symbol_results = self.symbol_search(query.split()[0]) if query.split() else []
    hybrid_results = ...  # как выше
    seen = set()
    merged = []
    for c in symbol_results + hybrid_results:
        if c.id not in seen:
            seen.add(c.id)
            merged.append(c)
    # rerank merged[:k]
```

---

## TASK-2.3 — QueryFusion (multi-query expansion)

**Добавить в `RAGIndex`** (плanner передаётся при инициализации или как параметр):

```python
class RAGIndex:
    def __init__(self, cfg, planner=None):
        # ... существующий __init__ ...
        self.planner = planner  # ProviderRouter или None

    def _expand_query(self, query: str, n: int = 3) -> list[str]:
        if not self.planner:
            return []
        prompt = (
            f"Generate {n} different search queries for a code search engine "
            f"to find relevant code for: {query}\n"
            "Return only queries, one per line, no numbering."
        )
        response = self.planner.analyze(prompt)
        return [q.strip() for q in response.strip().split('\n') if q.strip()][:n]

    def search_fusion(self, query: str, top_k: int | None = None) -> list[Chunk]:
        """Hybrid search + Reciprocal Rank Fusion. Для plan mode и /ask."""
        n = top_k or self.cfg.rag_top_n
        queries = [query] + self._expand_query(query, n=3)

        rrf_scores: dict[str, float] = {}
        chunk_map: dict[str, Chunk] = {}

        for q in queries:
            results = self._hybrid_search(q, top_k=20)
            for rank, (chunk, _) in enumerate(results):
                rrf_scores[chunk.id] = rrf_scores.get(chunk.id, 0) + 1 / (60 + rank)
                chunk_map[chunk.id] = chunk

        top_ids = sorted(rrf_scores, key=rrf_scores.get, reverse=True)[:n]  # type: ignore[arg-type]
        return [chunk_map[cid] for cid in top_ids]
```

`search_fusion` — для plan mode и `/ask`.
`search` (обычный) — для agent mode (быстрее).

---

## TASK-2.5 — check_staleness + sync wire-up

**Добавить в `RAGIndex`:**

```python
def check_staleness(self) -> bool:
    """True если индекс старше rag_stale_hours (дефолт 4)."""
    import time
    meta_file = self.index_path / "meta.json"
    if not meta_file.exists():
        return True
    try:
        import json
        built_at = json.loads(meta_file.read_text()).get("built_at", 0)
        stale_hours = getattr(self.cfg, 'rag_stale_hours', 4.0)
        return (time.time() - built_at) / 3600 > stale_hours
    except Exception:
        return True
```

**`sync.py` не существует** — его нужно создать или добавить wire-up в cli.py.
При старте: если `rag.check_staleness()` → показать предупреждение в чате.
