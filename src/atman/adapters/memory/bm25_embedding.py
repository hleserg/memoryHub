"""
BM25EmbeddingAdapter - pure Python BM25-based sparse embeddings.

Implements BM25 text scoring as a sparse embedding using the **feature
hashing trick** so that all calls to :meth:`embed` return vectors of the
same fixed dimension. This makes individually-embedded vectors directly
comparable via :meth:`similarity`, which is the contract expected by the
``EmbeddingPort`` protocol and consumers like
:class:`PassiveMemoryInjector`.

Zero external dependencies, suitable for lightweight deployments.
"""

import hashlib
import math
import re
from collections import Counter
from typing import override

from atman.core.ports.embedding import EmbeddingPort

# Word characters in Unicode-aware mode; covers Latin, Cyrillic, Greek,
# Arabic, CJK, etc. Underscore is excluded.
_TOKEN_RE = re.compile(r"[^\W_]+", flags=re.UNICODE)


class BM25EmbeddingAdapter(EmbeddingPort):
    """
    BM25-based embedding adapter using feature hashing.

    Each token is hashed to one of ``dimension`` slots, so every call to
    :meth:`embed` returns a vector of the same fixed length. When a corpus
    has been observed via :meth:`embed_batch` or :meth:`embed_with_corpus`,
    the document-frequency statistics collected from that corpus are used
    for proper BM25 weighting on subsequent :meth:`embed` calls. Otherwise
    a TF-only weight is used.

    This is NOT a neural embedding - it's a classical IR approach
    that requires no external dependencies or model downloads.
    """

    DEFAULT_DIMENSION = 1024

    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
        dimension: int = DEFAULT_DIMENSION,
    ) -> None:
        """
        Initialize BM25 adapter.

        Args:
            k1: BM25 term frequency saturation parameter
            b: BM25 document length normalization parameter
            dimension: Fixed output vector dimension; tokens are hashed
                into this many slots so that all embeddings are
                directly comparable.
        """
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self.k1 = k1
        self.b = b
        self._dimension = dimension
        # Document frequencies, keyed by hashed slot index.
        self._doc_freqs: Counter[int] = Counter()
        self._avg_doc_len = 0.0
        self._num_docs = 0
        # Term -> slot index, populated lazily during tokenization. Useful
        # for tests / introspection; semantically just a memoization of
        # ``_term_index``.
        self._vocab: dict[str, int] = {}

    @override
    def embed(self, text: str) -> list[float]:
        """
        Generate a fixed-dimension BM25 vector for ``text``.

        If the adapter has previously seen a corpus via
        :meth:`embed_batch` or :meth:`embed_with_corpus`, IDF from that
        corpus is applied; otherwise a TF-only weight is used.
        """
        tokens = self._tokenize(text)
        return self._embed_tokens(tokens)

    def embed_with_corpus(self, text: str, corpus_docs: list[str]) -> list[float]:
        """
        Generate BM25 embedding for ``text`` using ``corpus_docs`` for IDF.

        Args:
            text: The text to embed
            corpus_docs: The corpus for IDF calculation

        Returns:
            list[float]: BM25-weighted vector of length :meth:`dimension`.
        """
        all_tokens = [self._tokenize(doc) for doc in corpus_docs]
        self._build_corpus_stats(all_tokens)
        return self._embed_tokens(self._tokenize(text))

    @override
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts using shared corpus stats."""
        all_tokens = [self._tokenize(text) for text in texts]
        self._build_corpus_stats(all_tokens)
        return [self._embed_tokens(tokens) for tokens in all_tokens]

    @override
    def dimension(self) -> int:
        """Return the (fixed) embedding dimension."""
        return self._dimension

    @override
    def model_name(self) -> str:
        """Return model identifier."""
        return f"bm25-{self._dimension}d"

    @override
    def similarity(self, vec1: list[float], vec2: list[float]) -> float:
        """Calculate cosine similarity between two sparse vectors."""
        if len(vec1) != len(vec2):
            raise ValueError("Vectors must have same dimension")

        dot_product = sum(a * b for a, b in zip(vec1, vec2, strict=True))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    def _tokenize(self, text: str) -> list[str]:
        """
        Lowercase and split into Unicode word tokens.

        Uses a Unicode-aware regex so non-Latin scripts (Cyrillic, Greek,
        CJK, …) are tokenised correctly. Tokens shorter than 3 characters
        are dropped to suppress noise from particles like English ``a`` /
        ``an`` / Russian ``я`` while still keeping useful short words such
        as ``CI`` (≥ 2 chars survives once lowercased to ``ci`` only if
        we relaxed this; current behaviour preserves the original
        > 2-char filter).
        """
        text = text.lower()
        tokens = _TOKEN_RE.findall(text)
        return [t for t in tokens if len(t) > 2]

    def _term_index(self, term: str) -> int:
        """Stable hash of ``term`` into ``[0, dimension)``."""
        cached = self._vocab.get(term)
        if cached is not None:
            return cached
        # md5 is used as a fast, well-distributed non-cryptographic hash.
        digest = hashlib.md5(term.encode("utf-8"), usedforsecurity=False).digest()
        idx = int.from_bytes(digest[:8], "big") % self._dimension
        self._vocab[term] = idx
        return idx

    def _build_corpus_stats(self, all_tokens: list[list[str]]) -> None:
        """Build corpus-wide statistics for BM25 (keyed by hashed slot)."""
        self._doc_freqs = Counter()
        total_len = 0
        for tokens in all_tokens:
            unique_indices = {self._term_index(t) for t in tokens}
            self._doc_freqs.update(unique_indices)
            total_len += len(tokens)
        self._num_docs = len(all_tokens)
        self._avg_doc_len = total_len / self._num_docs if self._num_docs > 0 else 0.0

    def _embed_tokens(self, tokens: list[str]) -> list[float]:
        """Embed a tokenised document into a fixed-dim BM25 vector."""
        term_counts = Counter(tokens)
        doc_len = len(tokens)
        vector = [0.0] * self._dimension
        use_corpus = self._num_docs > 0

        for term, count in term_counts.items():
            idx = self._term_index(term)
            if use_corpus:
                idf = self._idf_by_index(idx)
                tf = self._tf_weight(count, doc_len, self._avg_doc_len)
                vector[idx] += idf * tf
            else:
                vector[idx] += self._tf_weight(count, doc_len, doc_len)
        return vector

    def _idf_by_index(self, idx: int) -> float:
        df = self._doc_freqs.get(idx, 0)
        if df == 0:
            return 0.0
        return math.log((self._num_docs - df + 0.5) / (df + 0.5) + 1.0)

    def _idf(self, term: str) -> float:
        """Calculate IDF for a term using the most recently observed corpus."""
        return self._idf_by_index(self._term_index(term))

    def _tf_weight(self, term_freq: int, doc_len: int, avg_doc_len: float) -> float:
        """Calculate BM25 term frequency weight."""
        if avg_doc_len == 0:
            return term_freq

        norm_len = doc_len / avg_doc_len
        denominator = term_freq + self.k1 * (1 - self.b + self.b * norm_len)
        return (term_freq * (self.k1 + 1)) / denominator if denominator > 0 else 0.0
