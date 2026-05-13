"""atman/agent_cli/rag.py — BGE-M3 hybrid retrieval (dense, sparse, ColBERT), AST chunking, symbols.

Two-stage retrieval may apply local Flag Reranker and/or ProviderRouter Cohere reranking when configured.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from .config import AgentConfig

if TYPE_CHECKING:
    from .providers import ProviderRouter

INDEXABLE_EXTENSIONS = {
    ".py",
    ".md",
    ".toml",
    ".yml",
    ".yaml",
    ".txt",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
}
SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".pytest_cache",
}
MAX_CHUNK_CHARS = 2000
CHUNK_OVERLAP = 200
SPARSE_WEIGHTS_FILE = "sparse_weights.jsonl"
COLBERT_VECS_FILE = "colbert_vecs.npy"
SYMBOL_INDEX_FILE = "symbol_index.json"

SUPPORTED_LANGS = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
}
AST_NODES = frozenset(
    {
        "function_definition",
        "class_definition",
        "decorated_definition",
        "function_declaration",
        "method_definition",
    }
)


@dataclass
class Chunk:
    path: str
    content: str
    start_line: int
    chunk_index: int
    file_hash: str
    window_content: str = ""
    window_start: int = 0
    window_end: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.path}::{self.chunk_index}"

    def to_display(self) -> str:
        return f"{self.path} (lines {self.start_line}+)"


class RAGIndex:
    """On-disk hybrid code index."""

    def __init__(self, cfg: AgentConfig, planner: ProviderRouter | None = None) -> None:
        self.cfg = cfg
        self.index_path = cfg.index_path
        self.planner = planner
        self._chunks: list[Chunk] = []
        self._embeddings: list[list[float]] = []
        self._sparse_weights: list[dict[str, float]] = []
        self._colbert_vecs: list[np.ndarray[Any, Any] | None] = []
        self._symbol_index: dict[str, list[dict[str, Any]]] = {}
        self.window_lines = int(getattr(cfg, "rag_window_lines", 10))
        self._line_cache: dict[str, list[str]] = {}
        self._parsers: dict[str, Any] = {}
        self._embedder = None
        self._reranker = None
        self._load_models()
        self._load_index()

    @property
    def router(self) -> ProviderRouter | None:
        return self.planner

    def _load_models(self) -> None:
        try:
            from FlagEmbedding import BGEM3FlagModel, FlagReranker

            self._embedder = BGEM3FlagModel(self.cfg.embed_model, use_fp16=True)
            self._reranker = FlagReranker(self.cfg.reranker_model, use_fp16=True)
        except ImportError:
            pass

    def clear_line_cache(self) -> None:
        self._line_cache.clear()

    def _file_hash(self, path: Path) -> str:
        return hashlib.md5(path.read_bytes()).hexdigest()[:8]

    def _file_lines(self, rel_path: str) -> list[str]:
        if rel_path not in self._line_cache:
            try:
                p = Path(rel_path) if rel_path.startswith("/") else self.cfg.repo_path / rel_path
                self._line_cache[rel_path] = p.read_text(
                    encoding="utf-8", errors="ignore"
                ).splitlines()
            except OSError:
                self._line_cache[rel_path] = []
        return self._line_cache[rel_path]

    def _window(self, rel: str, ln0_start: int, ln0_exc_end: int) -> tuple[str, int, int]:
        lines_list = self._file_lines(rel)
        w0 = max(0, ln0_start - self.window_lines)
        w1 = min(len(lines_list), ln0_exc_end + self.window_lines)
        return "\n".join(lines_list[w0:w1]), w0, w1

    def _chunk_text_overlap(self, text: str) -> list[tuple[str, int]]:
        lines_list = text.splitlines()
        out: list[tuple[str, int]] = []
        current: list[str] = []
        cur_n = 0
        sl = 1
        for i, ln_txt in enumerate(lines_list, start=1):
            current.append(ln_txt)
            cur_n += len(ln_txt) + 1
            if cur_n >= MAX_CHUNK_CHARS:
                out.append(("\n".join(current), sl))
                ochars = 0
                overlap_buf: list[str] = []
                for ol_txt in reversed(current):
                    if ochars + len(ol_txt) > CHUNK_OVERLAP:
                        break
                    overlap_buf.insert(0, ol_txt)
                    ochars += len(ol_txt)
                current = overlap_buf
                cur_n = ochars
                sl = i - len(overlap_buf) + 1
        if current:
            out.append(("\n".join(current), sl))
        return out

    def _detect_lang(self, path: Path) -> str | None:
        return SUPPORTED_LANGS.get(path.suffix.lower())

    def _parser_for(self, lang: str) -> Any:
        if lang not in self._parsers:
            import tree_sitter_javascript as _tsjs
            import tree_sitter_python as _tspy
            import tree_sitter_typescript as _tsts
            from tree_sitter import Language, Parser

            lang_blob = {
                "python": _tspy.language(),
                "javascript": _tsjs.language(),
                "typescript": _tsts.language_typescript(),
            }
            self._parsers[lang] = Parser(Language(lang_blob[lang]))
        return self._parsers[lang]

    def _ast_name(self, node: Any) -> str:
        for ch in node.children:
            if ch.type in ("identifier", "name"):
                blob: bytes = ch.text
                return blob.decode("utf-8", errors="replace")
        return ""

    def _chunks_by_ast(self, path: Path, text_u: str, rel: str) -> list[Chunk]:
        lang_code = self._detect_lang(path)
        if not lang_code:
            return self._chunks_by_size_only(path, text_u, rel)
        try:
            pr = self._parser_for(lang_code)
        except Exception:
            return self._chunks_by_size_only(path, text_u, rel)
        tr = pr.parse(text_u.encode("utf-8", errors="ignore"))
        fh = self._file_hash(path)
        acc: list[Chunk] = []
        kid = 0
        rn = tr.root_node
        children_nodes = list(rn.children) if rn else []
        for nd in children_nodes:
            if nd.type not in AST_NODES:
                continue
            chunk_body = text_u[nd.start_byte : nd.end_byte]
            s0 = nd.start_point[0]
            e_ex = nd.end_point[0] + 1
            wtxt, ws, we = self._window(rel, s0, e_ex)
            nm = self._ast_name(nd)
            acc.append(
                Chunk(
                    path=rel,
                    content=chunk_body,
                    start_line=s0 + 1,
                    chunk_index=kid,
                    file_hash=fh,
                    window_content=wtxt,
                    window_start=ws,
                    window_end=we,
                    metadata={"language": lang_code, "type": nd.type, "name": nm},
                )
            )
            kid += 1
        return acc if acc else self._chunks_by_size_only(path, text_u, rel)

    def _chunks_by_size_only(self, path: Path, text_u: str, rel: str) -> list[Chunk]:
        fh = self._file_hash(path)
        res: list[Chunk] = []
        for jdx, (c_txt, ln1) in enumerate(self._chunk_text_overlap(text_u)):
            exc_end = ln1 + c_txt.count("\n")
            wtxt, ws, we = self._window(rel, ln1 - 1, exc_end)
            res.append(
                Chunk(
                    path=rel,
                    content=c_txt,
                    start_line=ln1,
                    chunk_index=jdx,
                    file_hash=fh,
                    window_content=wtxt,
                    window_start=ws,
                    window_end=we,
                )
            )
        return res

    def _merge_file_groups(self, chs: list[Chunk]) -> list[Chunk]:
        by_p: dict[str, list[Chunk]] = defaultdict(list)
        for c in chs:
            by_p[c.path].append(c)
        merged: list[Chunk] = []
        for fp, grp in by_p.items():
            if len(grp) >= 3:
                L = self._file_lines(fp)
                mn = min(x.window_start for x in grp)
                mx = max(x.window_end for x in grp)
                big_txt = "\n".join(L[mn:mx])
                merged.append(
                    Chunk(
                        path=fp,
                        content=big_txt,
                        start_line=mn + 1,
                        chunk_index=0,
                        file_hash=grp[0].file_hash,
                        window_content=big_txt,
                        window_start=mn,
                        window_end=mx,
                        metadata=dict(grp[0].metadata),
                    )
                )
            else:
                merged.extend(grp)
        return merged

    def _iter_paths(self, repo: Path):
        for p in repo.rglob("*"):
            if not p.is_file():
                continue
            suf_l = p.suffix.lower()
            if suf_l in INDEXABLE_EXTENSIONS and not any(sd in p.parts for sd in SKIP_DIRS):
                yield p

    def _encode_multi(
        self, texts_list: list[str]
    ) -> tuple[list[list[float]], list[dict[str, float]], list[np.ndarray[Any, Any] | None]]:
        n_t = len(texts_list)
        if not self._embedder or n_t == 0:
            return [[0.0] for _ in range(n_t)], [{} for _ in range(n_t)], [None for _ in range(n_t)]
        try:
            raw_o = self._embedder.encode(
                texts_list,
                return_dense=True,
                return_sparse=True,
                return_colbert_vecs=True,
                batch_size=12,
            )
            dvec = raw_o["dense_vecs"].tolist()
            lexical = raw_o.get("lexical_weights", [])
            c_raw = raw_o.get("colbert_vecs", [])
            sp_lst: list[dict[str, float]] = []
            for item in lexical:
                if isinstance(item, dict):
                    sp_lst.append({str(k): float(v) for k, v in item.items()})
                else:
                    sp_lst.append({})
            cv_lst: list[np.ndarray[Any, Any] | None] = []
            for row in c_raw:
                cv_lst.append(None if row is None else np.asarray(row, dtype=np.float32))
            return dvec, sp_lst, cv_lst
        except (AttributeError, KeyError, TypeError, ValueError):
            d_simple = self._embedder.encode(texts_list, batch_size=32)["dense_vecs"].tolist()
            return d_simple, [{} for _ in range(n_t)], [None for _ in range(n_t)]

    def _path_index(self) -> dict[str, list[int]]:
        m: dict[str, list[int]] = defaultdict(list)
        for idx_c, ck in enumerate(self._chunks):
            m[ck.path].append(idx_c)
        return dict(m)

    def _align_parallel(self) -> None:
        n_c = len(self._chunks)
        while len(self._embeddings) < n_c:
            self._embeddings.append([0.0])
        while len(self._sparse_weights) < n_c:
            self._sparse_weights.append({})
        while len(self._colbert_vecs) < n_c:
            self._colbert_vecs.append(None)
        self._embeddings = self._embeddings[:n_c]
        self._sparse_weights = self._sparse_weights[:n_c]
        self._colbert_vecs = self._colbert_vecs[:n_c]

    def build(self, repo: Path, progress_callback=None) -> int:
        self.clear_line_cache()
        self._chunks = []
        self._sparse_weights = []
        self._colbert_vecs = []
        acc_txt: list[str] = []
        file_list = list(self._iter_paths(repo))
        for idx_f, fp in enumerate(file_list):
            if progress_callback:
                progress_callback(idx_f, len(file_list), str(fp.relative_to(repo)))
            try:
                blob = fp.read_text(encoding="utf-8", errors="ignore")
                rel_s = str(fp.relative_to(repo))
                for ck in self._chunks_by_ast(fp, blob, rel_s):
                    self._chunks.append(ck)
                    acc_txt.append(ck.content)
            except OSError:
                continue
        if acc_txt:
            d_e, sp_e, cv_e = self._encode_multi(acc_txt)
            self._embeddings = d_e
            self._sparse_weights = sp_e
            self._colbert_vecs = cv_e
        else:
            self._embeddings = []
        self._persist_symbols()
        self._persist_disk()
        return len(self._chunks)

    def update(self, repo: Path, changed_files: list[str] | None = None) -> int:
        self.clear_line_cache()
        pmap: dict[str, list[int]] = defaultdict(list)
        for i_c, ch in enumerate(self._chunks):
            pmap[ch.path].append(i_c)
        pmap = dict(pmap)
        n_upd = 0
        for fp in self._iter_paths(repo):
            rel_s = str(fp.relative_to(repo))
            if changed_files is not None and rel_s not in changed_files:
                continue
            h_now = self._file_hash(fp)
            old_li = [self._chunks[ix] for ix in pmap.get(rel_s, [])]
            if old_li and old_li[0].file_hash == h_now:
                continue
            drop_ix = set(pmap.get(rel_s, []))
            if drop_ix:
                keep = [j for j in range(len(self._chunks)) if j not in drop_ix]
                n_emb, n_sp, n_cb = (
                    len(self._embeddings),
                    len(self._sparse_weights),
                    len(self._colbert_vecs),
                )
                self._chunks = [self._chunks[j] for j in keep]
                self._embeddings = [self._embeddings[j] for j in keep if j < n_emb]
                self._sparse_weights = [self._sparse_weights[j] for j in keep if j < n_sp]
                self._colbert_vecs = [self._colbert_vecs[j] for j in keep if j < n_cb]
            pmap = self._path_index()
            try:
                blob = fp.read_text(encoding="utf-8", errors="ignore")
                new_ch = self._chunks_by_ast(fp, blob, rel_s)
                n_tx = [c.content for c in new_ch]
                d_e, sp_e, cv_e = self._encode_multi(n_tx)
                self._chunks.extend(new_ch)
                self._embeddings.extend(d_e)
                self._sparse_weights.extend(sp_e)
                self._colbert_vecs.extend(cv_e)
                n_upd += 1
            except OSError:
                continue
            pmap = self._path_index()
        if n_upd > 0:
            self._align_parallel()
            self._persist_symbols()
            self._persist_disk()
        return n_upd

    def check_staleness(self) -> bool:
        meta_obj = self.index_path / "meta.json"
        if not meta_obj.exists():
            return True
        try:
            t_build = float(json.loads(meta_obj.read_text(encoding="utf-8")).get("built_at", 0))
            limit_h = float(getattr(self.cfg, "rag_stale_hours", 4.0))
            return (time.time() - t_build) / 3600 > limit_h
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return True

    def symbol_search(self, nm: str) -> list[Chunk]:
        ans: list[Chunk] = []
        for hit in self._symbol_index.get(nm, []):
            for ch in self._chunks:
                if ch.path == hit["path"] and ch.start_line == hit["line"]:
                    ans.append(ch)
                    break
        return ans

    def _llm_queries(self, q_orig: str, need: int = 3) -> list[str]:
        if not self.planner:
            return []
        pr = (
            f"Generate {need} different search queries for a code search engine "
            f"to find relevant code for: {q_orig}\n"
            "Return only queries, one per line, no numbering."
        )
        out_raw = self.planner.analyze(pr)
        lines_out = [x.strip() for x in out_raw.strip().split("\n") if x.strip()]
        return lines_out[:need]

    def search_fusion(self, query_txt: str, top_k_arg: int | None = None) -> list[Chunk]:
        cap_n = top_k_arg or self.cfg.rag_top_n
        ql = [query_txt, *self._llm_queries(query_txt)]
        score_b: dict[str, float] = {}
        cmap: dict[str, Chunk] = {}
        for one_q in ql:
            for rnk, (ch_i, _) in enumerate(self._hybrid_rank(one_q, top_k_need=20)):
                cid_k = ch_i.id
                score_b[cid_k] = score_b.get(cid_k, 0.0) + 1.0 / (60.0 + float(rnk))
                cmap[cid_k] = ch_i
        top_ids = sorted(score_b.keys(), key=lambda kk: score_b[kk], reverse=True)[:cap_n]
        return [cmap[i] for i in top_ids]

    def _kw_fallback(self, q_txt: str, k_lim: int) -> list[Chunk]:
        qs = q_txt.lower().split()
        if not qs:
            return self._chunks[:k_lim]
        scores_n: list[tuple[int, Chunk]] = []
        for ch in self._chunks:
            low_txt = ch.content.lower()
            scores_n.append((sum(1 for w in qs if w in low_txt), ch))
        scores_n.sort(key=lambda t_row: t_row[0], reverse=True)
        return [c_sel for scr, c_sel in scores_n[:k_lim] if scr > 0]

    def _sparse_dot(self, q_w: dict[str, float]) -> np.ndarray[Any, Any]:
        res_v = np.zeros(len(self._chunks), dtype=np.float64)
        if not q_w:
            return res_v
        for i_i in range(min(len(self._chunks), len(self._sparse_weights))):
            row_sp = self._sparse_weights[i_i]
            for tok_k, qw_v in q_w.items():
                if tok_k in row_sp:
                    res_v[i_i] += float(qw_v) * float(row_sp[tok_k])
        return res_v

    def _colbert_qd(self, q_mat: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
        res_v = np.zeros(len(self._chunks), dtype=np.float64)
        if q_mat.size == 0:
            return res_v
        qq = np.asarray(q_mat, dtype=np.float64)
        if qq.ndim == 1:
            qq = qq.reshape(1, -1)
        for i_i, cv_r in enumerate(self._colbert_vecs):
            if i_i >= len(self._chunks) or cv_r is None or cv_r.size == 0:
                continue
            ca = np.asarray(cv_r, dtype=np.float64)
            if ca.ndim == 1:
                ca = ca.reshape(1, -1)
            try:
                sim_m = qq @ ca.T
                res_v[i_i] = float(np.max(sim_m, axis=1).sum())
            except ValueError:
                continue
        return res_v

    def _hybrid_rank(self, q_txt: str, top_k_need: int = 40) -> list[tuple[Chunk, float]]:
        if not self._embedder or not self._embeddings:
            return [(x, 0.0) for x in self._kw_fallback(q_txt, top_k_need)]

        nz = len(self._chunks)
        emb_mat = np.asarray(self._embeddings, dtype=np.float64)

        try:
            q_pack = self._embedder.encode(
                [q_txt], return_dense=True, return_sparse=True, return_colbert_vecs=True
            )
            q_den = np.asarray(q_pack["dense_vecs"][0], dtype=np.float64)
            lex0 = q_pack.get("lexical_weights", [{}])[0]
            q_sp = lex0 if isinstance(lex0, dict) else {}
            q_cb_mat = np.asarray(q_pack.get("colbert_vecs", [[]])[0], dtype=np.float64)

            q_unit = q_den / (np.linalg.norm(q_den) + 1e-10)
            row_norm = np.linalg.norm(emb_mat, axis=1, keepdims=True) + 1e-10
            dense_lin = (emb_mat / row_norm @ q_unit).reshape(-1)
            sparse_lin = self._sparse_dot(q_sp)
            cbert_lin = self._colbert_qd(q_cb_mat) if q_cb_mat.size > 0 else np.zeros(nz)
        except (AttributeError, KeyError, TypeError, ValueError):
            q_simple = self._embedder.encode([q_txt])
            qv_den = np.asarray(q_simple["dense_vecs"][0], dtype=np.float64)
            qu = qv_den / (np.linalg.norm(qv_den) + 1e-10)
            row_norm = np.linalg.norm(emb_mat, axis=1, keepdims=True) + 1e-10
            dense_lin = (emb_mat / row_norm @ qu).reshape(-1)
            sparse_lin = np.zeros(nz)
            cbert_lin = np.zeros(nz)

        if dense_lin.shape[0] < nz:
            dense_lin = np.concatenate([dense_lin, np.zeros(nz - dense_lin.shape[0])])
        elif dense_lin.shape[0] > nz:
            dense_lin = dense_lin[:nz]

        w_den = float(getattr(self.cfg, "rag_dense_weight", 0.4))
        w_sp = float(getattr(self.cfg, "rag_sparse_weight", 0.2))
        w_cb = float(getattr(self.cfg, "rag_colbert_weight", 0.4))
        use_sp = sparse_lin if len(self._sparse_weights) == nz else np.zeros(nz)
        use_cb = cbert_lin if len(self._colbert_vecs) == nz else np.zeros(nz)
        mx_sp = float(np.max(use_sp)) if use_sp.size else 0.0
        mx_cb = float(np.max(use_cb)) if use_cb.size else 0.0
        sp_norm = use_sp / (mx_sp + 1e-10) if mx_sp > 0 else use_sp
        cb_norm = use_cb / (mx_cb + 1e-10) if mx_cb > 0 else use_cb
        fused_lin = w_den * dense_lin + w_sp * sp_norm + w_cb * cb_norm

        take_k = min(top_k_need, fused_lin.shape[0])
        ord_ix = np.argsort(fused_lin)[-take_k:][::-1]
        return [(self._chunks[jj], float(fused_lin[jj])) for jj in ord_ix]

    def search(
        self, query_txt: str, top_k_arg: int | None = None, top_n_arg: int | None = None
    ) -> list[Chunk]:
        if not self._chunks:
            return []
        kk = top_k_arg or int(getattr(self.cfg, "rag_candidates_k", self.cfg.rag_top_k))
        nn = top_n_arg or self.cfg.rag_top_n
        toks_li = query_txt.split()
        sym_hits = self.symbol_search(toks_li[0]) if toks_li else []
        cand_hybrid = [c for c, _ in self._hybrid_rank(query_txt, top_k_need=kk)]
        seen_ids: set[str] = set()
        ordered: list[Chunk] = []
        for ck in sym_hits + cand_hybrid:
            if ck.id not in seen_ids:
                seen_ids.add(ck.id)
                ordered.append(ck)
        ordered = self._merge_file_groups(ordered)
        if not ordered:
            return []
        use_cohere = bool(self.planner and self.planner.cfg.reranker == "cohere")
        if len(ordered) > nn and (self._reranker or use_cohere):
            return self._rerank_pass(query_txt, ordered, nn)
        return ordered[:nn]

    def _rerank_pass(self, q_txt: str, cand_li: list[Chunk], nn: int) -> list[Chunk]:
        if self.planner and self.planner.cfg.reranker == "cohere":
            sc_list = self.planner.rerank(q_txt, [c.content for c in cand_li], nn)
            pr = sorted(zip(sc_list, cand_li, strict=True), reverse=True)[:nn]
            return [c for _, c in pr]
        if self._reranker:
            prs = [[q_txt, c.content] for c in cand_li]
            sc_list = self._reranker.compute_score(prs, normalize=True)
            pr = sorted(zip(sc_list, cand_li, strict=True), reverse=True)[:nn]
            return [c for _, c in pr]
        return cand_li[:nn]

    def format_context(self, ch_li: list[Chunk], mx_chr: int = 8000) -> str:
        parts_out: list[str] = []
        tot_n = 0
        for ch in ch_li:
            hdr_txt = f"## {ch.path} (line {ch.start_line})\n"
            body_txt = ch.window_content or ch.content
            if tot_n + len(hdr_txt) + len(body_txt) > mx_chr:
                break
            parts_out.append(hdr_txt + body_txt)
            tot_n += len(hdr_txt) + len(body_txt)
        return "\n\n".join(parts_out)

    def _persist_symbols(self) -> None:
        sym_mp: dict[str, list[dict[str, Any]]] = {}
        for ch_i in self._chunks:
            name_v = ch_i.metadata.get("name")
            if not name_v:
                continue
            sym_mp.setdefault(str(name_v), []).append(
                {
                    "path": ch_i.path,
                    "line": ch_i.start_line,
                    "type": ch_i.metadata.get("type", "unknown"),
                }
            )
        self._symbol_index = sym_mp
        (self.index_path / SYMBOL_INDEX_FILE).write_text(
            json.dumps(sym_mp, ensure_ascii=False), encoding="utf-8"
        )

    def _load_symbols_disk(self) -> None:
        p_sym = self.index_path / SYMBOL_INDEX_FILE
        if not p_sym.exists():
            self._symbol_index = {}
            return
        try:
            self._symbol_index = json.loads(p_sym.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._symbol_index = {}

    def _persist_disk(self) -> None:
        ch_path = self.index_path / "chunks.jsonl"
        with ch_path.open("w", encoding="utf-8") as fh:
            for ck in self._chunks:
                fh.write(json.dumps(asdict(ck), ensure_ascii=False) + "\n")
        sp_file = self.index_path / SPARSE_WEIGHTS_FILE
        with sp_file.open("w", encoding="utf-8") as fh:
            for sp_row in self._sparse_weights:
                fh.write(json.dumps(sp_row, ensure_ascii=False) + "\n")

        has_cb = any(x is not None for x in self._colbert_vecs)
        if has_cb:
            pack_li: list[np.ndarray[Any, Any]] = []
            for cv_cell in self._colbert_vecs:
                if cv_cell is None:
                    pack_li.append(np.zeros((0, 1), dtype=np.float16))
                else:
                    pack_li.append(np.asarray(cv_cell, dtype=np.float16))
            np.save(
                self.index_path / COLBERT_VECS_FILE,
                np.asarray(pack_li, dtype=object),
                allow_pickle=True,
            )

        if self._embeddings:
            np.save(
                self.index_path / "embeddings.npy",
                np.asarray(self._embeddings, dtype=np.float32),
            )

        (self.index_path / "meta.json").write_text(
            json.dumps({"chunk_count": len(self._chunks), "built_at": time.time()}),
            encoding="utf-8",
        )

    def _load_index(self) -> None:
        jl_path = self.index_path / "chunks.jsonl"
        np_emb = self.index_path / "embeddings.npy"
        self._chunks = []
        self._sparse_weights = []
        self._colbert_vecs = []
        self._symbol_index = {}
        if not jl_path.exists():
            self._embeddings = []
            return

        for ln_row in jl_path.read_text(encoding="utf-8").splitlines():
            if not ln_row.strip():
                continue
            try:
                d_ob = json.loads(ln_row)
                for dk, dv in (
                    ("window_content", ""),
                    ("window_start", 0),
                    ("window_end", 0),
                    ("metadata", {}),
                ):
                    d_ob.setdefault(dk, dv)
                self._chunks.append(Chunk(**d_ob))
            except (TypeError, KeyError, ValueError, json.JSONDecodeError):
                continue

        if np_emb.exists():
            try:
                self._embeddings = np.load(np_emb).tolist()
            except OSError:
                self._embeddings = []
        else:
            self._embeddings = []

        sp_disk = self.index_path / SPARSE_WEIGHTS_FILE
        if sp_disk.exists():
            for ln_s in sp_disk.read_text(encoding="utf-8").splitlines():
                if ln_s.strip():
                    try:
                        self._sparse_weights.append(json.loads(ln_s))
                    except json.JSONDecodeError:
                        self._sparse_weights.append({})
        else:
            self._sparse_weights = [{} for _ in self._chunks]

        nl = len(self._chunks)
        self._colbert_vecs = [None] * nl
        cb_path = self.index_path / COLBERT_VECS_FILE
        if cb_path.exists():
            try:
                blob_arr = np.load(cb_path, allow_pickle=True)
                unpacked = blob_arr.item() if blob_arr.shape == () else blob_arr
                if isinstance(unpacked, np.ndarray) and unpacked.dtype == object:
                    for kk in range(min(nl, unpacked.shape[0])):
                        val_c = unpacked[kk]
                        self._colbert_vecs[kk] = (
                            None if val_c is None else np.asarray(val_c, dtype=np.float32)
                        )
            except OSError:
                self._colbert_vecs = [None] * nl

        self._align_parallel()
        self._load_symbols_disk()

    @property
    def stats(self) -> dict[str, Any]:
        mf = self.index_path / "meta.json"
        bt = None
        if mf.exists():
            try:
                bt = json.loads(mf.read_text(encoding="utf-8")).get("built_at")
            except (OSError, json.JSONDecodeError):
                bt = None
        return {
            "chunks": len(self._chunks),
            "files": len({z.path for z in self._chunks}),
            "has_embeddings": bool(self._embeddings),
            "built_at": bt,
            "models_loaded": self._embedder is not None,
        }
