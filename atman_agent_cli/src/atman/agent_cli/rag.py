"""
atman/agent_cli/rag.py
RAG: BGE-M3 indexing of the Atman repo + bge-reranker-v2-m3 reranking.
Two-stage retrieval: dense search → reranker → top-N.
"""
from __future__ import annotations

import json
import hashlib
import time
from pathlib import Path
from dataclasses import dataclass, asdict

from .config import AgentConfig

# File extensions to index
INDEXABLE_EXTENSIONS = {".py", ".md", ".toml", ".yml", ".yaml", ".txt"}
SKIP_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    ".mypy_cache", ".ruff_cache", "dist", "build", ".pytest_cache",
}
MAX_CHUNK_CHARS = 2000   # chars per chunk
CHUNK_OVERLAP = 200


@dataclass
class Chunk:
    path: str
    content: str
    start_line: int
    chunk_index: int
    file_hash: str

    @property
    def id(self) -> str:
        return f"{self.path}::{self.chunk_index}"

    def to_display(self) -> str:
        return f"{self.path} (lines {self.start_line}+)"


class RAGIndex:
    """
    Manages BGE-M3 index of the Atman codebase.
    Index stored as JSONL + numpy arrays for fast reload.
    """

    def __init__(self, cfg: AgentConfig) -> None:
        self.cfg = cfg
        self.index_path = cfg.index_path
        self._chunks: list[Chunk] = []
        self._embeddings: list[list[float]] = []
        self._embedder = None
        self._reranker = None
        self._load_models()
        self._load_index()

    def _load_models(self) -> None:
        try:
            from FlagEmbedding import BGEM3FlagModel, FlagReranker
            self._embedder = BGEM3FlagModel(
                self.cfg.embed_model,
                use_fp16=True,
            )
            self._reranker = FlagReranker(
                self.cfg.reranker_model,
                use_fp16=True,
            )
        except ImportError:
            pass  # models not available, will skip embedding

    def _file_hash(self, path: Path) -> str:
        return hashlib.md5(path.read_bytes()).hexdigest()[:8]

    def _chunk_text(self, text: str, path: str) -> list[tuple[str, int]]:
        """Split text into overlapping chunks. Returns (chunk_text, start_line)."""
        lines = text.splitlines()
        chunks = []
        current: list[str] = []
        current_chars = 0
        start_line = 1

        for i, line in enumerate(lines, 1):
            current.append(line)
            current_chars += len(line) + 1

            if current_chars >= MAX_CHUNK_CHARS:
                chunks.append(("\n".join(current), start_line))
                # overlap: keep last N chars worth of lines
                overlap_chars = 0
                overlap_lines: list[str] = []
                for l in reversed(current):
                    if overlap_chars + len(l) > CHUNK_OVERLAP:
                        break
                    overlap_lines.insert(0, l)
                    overlap_chars += len(l)
                current = overlap_lines
                current_chars = overlap_chars
                start_line = i - len(overlap_lines) + 1

        if current:
            chunks.append(("\n".join(current), start_line))

        return chunks

    def _iter_files(self, repo: Path):
        for path in repo.rglob("*"):
            if path.is_file() and path.suffix in INDEXABLE_EXTENSIONS:
                if not any(skip in path.parts for skip in SKIP_DIRS):
                    yield path

    def build(self, repo: Path, progress_callback=None) -> int:
        """Build/rebuild the full index. Returns number of chunks indexed."""
        self._chunks = []
        raw_texts: list[str] = []

        files = list(self._iter_files(repo))
        for i, path in enumerate(files):
            if progress_callback:
                progress_callback(i, len(files), str(path.relative_to(repo)))
            try:
                text = path.read_text(errors="ignore")
                h = self._file_hash(path)
                rel = str(path.relative_to(repo))
                for j, (chunk_text, start_line) in enumerate(self._chunk_text(text, rel)):
                    self._chunks.append(Chunk(
                        path=rel,
                        content=chunk_text,
                        start_line=start_line,
                        chunk_index=j,
                        file_hash=h,
                    ))
                    raw_texts.append(chunk_text)
            except Exception:
                continue

        # Embed all chunks
        if self._embedder and raw_texts:
            result = self._embedder.encode(raw_texts, batch_size=32)
            self._embeddings = result["dense_vecs"].tolist()
        else:
            self._embeddings = [[0.0]] * len(self._chunks)

        self._save_index()
        return len(self._chunks)

    def update(self, repo: Path, changed_files: list[str] | None = None) -> int:
        """
        Incremental update: only re-index changed files.
        If changed_files is None, scans all files for changes.
        """
        # Load existing index
        existing: dict[str, list[int]] = {}  # path → chunk indices
        for i, chunk in enumerate(self._chunks):
            existing.setdefault(chunk.path, []).append(i)

        updated = 0
        for path in self._iter_files(repo):
            rel = str(path.relative_to(repo))
            h = self._file_hash(path)

            # Check if changed
            existing_chunks = [self._chunks[i] for i in existing.get(rel, [])]
            if existing_chunks and existing_chunks[0].file_hash == h:
                continue  # not changed

            # Remove old chunks for this file
            indices_to_remove = set(existing.get(rel, []))
            self._chunks = [c for i, c in enumerate(self._chunks) if i not in indices_to_remove]
            self._embeddings = [e for i, e in enumerate(self._embeddings) if i not in indices_to_remove]

            # Add new chunks
            try:
                text = path.read_text(errors="ignore")
                new_chunks = []
                new_texts = []
                for j, (chunk_text, start_line) in enumerate(self._chunk_text(text, rel)):
                    new_chunks.append(Chunk(
                        path=rel, content=chunk_text,
                        start_line=start_line, chunk_index=j, file_hash=h,
                    ))
                    new_texts.append(chunk_text)

                if self._embedder and new_texts:
                    result = self._embedder.encode(new_texts, batch_size=32)
                    new_embeddings = result["dense_vecs"].tolist()
                else:
                    new_embeddings = [[0.0]] * len(new_texts)

                self._chunks.extend(new_chunks)
                self._embeddings.extend(new_embeddings)
                updated += 1
            except Exception:
                continue

        if updated:
            self._save_index()
        return updated

    def search(self, query: str, top_k: int | None = None, top_n: int | None = None) -> list[Chunk]:
        """
        Two-stage retrieval:
        1. Dense search with BGE-M3 (top_k candidates)
        2. Reranker to select top_n results
        """
        if not self._chunks:
            return []

        k = top_k or self.cfg.rag_top_k
        n = top_n or self.cfg.rag_top_n

        # Stage 1: dense retrieval
        candidates = self._dense_search(query, k)
        if not candidates:
            return []

        # Stage 2: rerank
        if self._reranker and len(candidates) > n:
            return self._rerank(query, candidates, n)

        return candidates[:n]

    def _dense_search(self, query: str, top_k: int) -> list[Chunk]:
        if not self._embedder or not self._embeddings:
            # Fallback: keyword search
            query_lower = query.lower()
            scored = [
                (sum(w in c.content.lower() for w in query_lower.split()), c)
                for c in self._chunks
            ]
            scored.sort(reverse=True)
            return [c for _, c in scored[:top_k] if _ > 0]

        # Embed query
        q_result = self._embedder.encode([query])
        q_vec = q_result["dense_vecs"][0]

        # Cosine similarity
        import numpy as np
        embeddings = np.array(self._embeddings)
        q_norm = q_vec / (np.linalg.norm(q_vec) + 1e-10)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-10
        scores = embeddings / norms @ q_norm

        top_indices = np.argsort(scores)[-top_k:][::-1]
        return [self._chunks[i] for i in top_indices]

    def _rerank(self, query: str, candidates: list[Chunk], top_n: int) -> list[Chunk]:
        pairs = [[query, c.content] for c in candidates]
        scores = self._reranker.compute_score(pairs, normalize=True)
        ranked = sorted(zip(scores, candidates), reverse=True)
        return [c for _, c in ranked[:top_n]]

    def format_context(self, chunks: list[Chunk], max_chars: int = 8000) -> str:
        """Format retrieved chunks as context for LLM."""
        parts = []
        total = 0
        for chunk in chunks:
            header = f"## {chunk.path} (line {chunk.start_line})\n"
            body = chunk.content
            if total + len(header) + len(body) > max_chars:
                break
            parts.append(header + body)
            total += len(header) + len(body)
        return "\n\n".join(parts)

    def _save_index(self) -> None:
        chunks_file = self.index_path / "chunks.jsonl"
        with open(chunks_file, "w") as f:
            for chunk in self._chunks:
                f.write(json.dumps(asdict(chunk)) + "\n")

        import numpy as np
        if self._embeddings:
            np.save(self.index_path / "embeddings.npy", np.array(self._embeddings))

        meta = {
            "chunk_count": len(self._chunks),
            "built_at": time.time(),
        }
        (self.index_path / "meta.json").write_text(json.dumps(meta))

    def _load_index(self) -> None:
        chunks_file = self.index_path / "chunks.jsonl"
        embeddings_file = self.index_path / "embeddings.npy"

        if not chunks_file.exists():
            return

        self._chunks = []
        for line in chunks_file.read_text().splitlines():
            if line.strip():
                try:
                    self._chunks.append(Chunk(**json.loads(line)))
                except Exception:
                    continue

        if embeddings_file.exists():
            try:
                import numpy as np
                self._embeddings = np.load(embeddings_file).tolist()
            except Exception:
                self._embeddings = []

    @property
    def stats(self) -> dict:
        meta_file = self.index_path / "meta.json"
        built_at = None
        if meta_file.exists():
            try:
                built_at = json.loads(meta_file.read_text()).get("built_at")
            except Exception:
                pass
        return {
            "chunks": len(self._chunks),
            "files": len(set(c.path for c in self._chunks)),
            "has_embeddings": bool(self._embeddings),
            "built_at": built_at,
            "models_loaded": self._embedder is not None,
        }
