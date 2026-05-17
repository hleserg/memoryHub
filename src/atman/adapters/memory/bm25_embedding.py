"""
BM25EmbeddingAdapter - pure Python BM25-based sparse embeddings.

Implements BM25 text scoring as a form of sparse embedding.
Zero external dependencies, suitable for lightweight deployments.
"""

import hashlib
import math
import re
from collections import Counter

from typing_extensions import override

from atman.core.ports.embedding import EmbeddingPort

DEFAULT_DIMENSION = 1024


class BM25EmbeddingAdapter(EmbeddingPort):
    """
    BM25-based embedding adapter.

    Uses BM25 scoring with a fixed vocabulary derived from text.
    Produces sparse vector representations suitable for lexical similarity.

    This is NOT a neural embedding - it's a classical IR approach
    that requires no external dependencies or model downloads.
    """

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
            dimension: Fixed output vector dimension. Tokens are mapped to
                buckets via a deterministic hash so that vectors produced by
                independent ``embed()`` calls are directly comparable via
                ``similarity()``.  ``embed_with_corpus()`` keeps using a
                vocabulary-derived dimension for backward compatibility.
        """
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self.k1 = k1
        self.b = b
        self._fixed_dimension = dimension
        self._vocab: dict[str, int] = {}
        self._doc_freqs: Counter = Counter()
        self._avg_doc_len = 0.0
        self._num_docs = 0
        self._dimension = dimension

    @override
    def embed(self, text: str) -> list[float]:
        """
        Generate BM25-weighted term vector for ``text``.

        Vectors are produced into a **fixed** ``dimension`` by hashing each
        token into a bucket (``hashing trick``).  This makes vectors from two
        independent ``embed()`` calls directly comparable via
        ``similarity()`` — the previous implementation rebuilt a per-call
        vocabulary, which violated the ``EmbeddingPort`` contract because
        every call returned a vector of a different length.

        For single-text embedding we have no corpus statistics, so the
        weight degenerates to BM25's TF component (with ``avg_doc_len``
        equal to the document's own length).  For corpus-aware weighting
        use ``embed_with_corpus`` or ``embed_batch``.
        """
        tokens = self._tokenize(text)
        if not tokens:
            return [0.0] * self._fixed_dimension

        term_counts = Counter(tokens)
        doc_len = len(tokens)

        vector = [0.0] * self._fixed_dimension
        for term, count in term_counts.items():
            idx = self._hash_bucket(term)
            # Without corpus stats, fall back to BM25's TF component only
            # (avg_doc_len == doc_len so the length-normalisation term
            # vanishes).
            vector[idx] += self._tf_weight(count, doc_len, doc_len)

        return vector

    def embed_with_corpus(self, text: str, corpus_docs: list[str]) -> list[float]:
        """
        Generate BM25 embedding using corpus statistics.

        Args:
            text: The text to embed
            corpus_docs: The corpus for IDF calculation

        Returns:
            list[float]: BM25-weighted vector
        """
        # Build corpus statistics
        all_tokens = [self._tokenize(doc) for doc in corpus_docs]
        self._build_corpus_stats(all_tokens)

        # Embed the target text
        tokens = self._tokenize(text)
        term_counts = Counter(tokens)
        doc_len = len(tokens)

        vector = [0.0] * self._dimension
        for term, count in term_counts.items():
            if term in self._vocab:
                idx = self._vocab[term]
                idf = self._idf(term)
                tf = self._tf_weight(count, doc_len, self._avg_doc_len)
                vector[idx] = idf * tf

        return vector

    @override
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts using shared corpus stats.

        Returns vectors of the configured ``dimension`` (the same dimension
        ``embed()`` uses), so vectors from ``embed`` and ``embed_batch``
        are mutually comparable via ``similarity()``.
        """
        if not texts:
            return []

        all_tokens = [self._tokenize(text) for text in texts]
        self._build_corpus_doc_freqs(all_tokens)
        return [self._embed_hashed_with_stats(tokens) for tokens in all_tokens]

    @override
    def dimension(self) -> int:
        """Return the fixed embedding dimension."""
        return self._fixed_dimension

    @override
    def model_name(self) -> str:
        """Return model identifier."""
        return f"bm25-{self._dimension}d"

    @override
    def similarity(self, vec1: list[float], vec2: list[float]) -> float:
        """Calculate cosine similarity between two sparse vectors.

        Raises ValueError when the two vectors have different dimensions.
        The most common cause is mixing the output of ``embed()``/``embed_batch()``
        (fixed hashing-trick dimension) with ``embed_with_corpus()`` (variable
        vocabulary-derived dimension) — never combine those two families.
        """
        if len(vec1) != len(vec2):
            raise ValueError(
                f"BM25 vector dimension mismatch: {len(vec1)} vs {len(vec2)}. "
                "Do not mix embed()/embed_batch() and embed_with_corpus() vectors."
            )

        dot_product = sum(a * b for a, b in zip(vec1, vec2, strict=True))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    def _hash_bucket(self, token: str) -> int:
        """Map a token to a stable bucket index in ``[0, dimension)``.

        Uses MD5 truncated to 4 bytes as a fast, deterministic, non-random
        hash (Python's built-in ``hash()`` is randomised per process and
        therefore unsuitable for vectors that must be comparable across
        processes or persisted).  MD5 is *not* used here for security; we
        rely only on the function's uniform distribution.
        """
        digest = hashlib.md5(token.encode("utf-8"), usedforsecurity=False).digest()
        return int.from_bytes(digest[:4], "little") % self._fixed_dimension

    def _build_corpus_doc_freqs(self, all_tokens: list[list[str]]) -> None:
        """Build document-frequency statistics for IDF without disturbing
        ``self._vocab``/``self._dimension`` (which are kept consistent with
        the hashing-trick output dimension).
        """
        self._doc_freqs = Counter()
        total_len = 0
        for tokens in all_tokens:
            self._doc_freqs.update(set(tokens))
            total_len += len(tokens)
        self._num_docs = len(all_tokens)
        self._avg_doc_len = total_len / self._num_docs if self._num_docs > 0 else 0.0

    def _embed_hashed_with_stats(self, tokens: list[str]) -> list[float]:
        """Embed pre-tokenised text using corpus IDF and the hashing trick."""
        if not tokens:
            return [0.0] * self._fixed_dimension

        term_counts = Counter(tokens)
        doc_len = len(tokens)
        vector = [0.0] * self._fixed_dimension
        for term, count in term_counts.items():
            idx = self._hash_bucket(term)
            idf = self._idf(term)
            tf = self._tf_weight(count, doc_len, self._avg_doc_len)
            vector[idx] += idf * tf
        return vector

    def _tokenize(self, text: str) -> list[str]:
        """Simple tokenization: lowercase Unicode word characters only.

        Uses ``[^\\W_]+`` so Cyrillic, CJK and other Unicode letters are kept
        alongside ASCII alphanumerics; underscores and other punctuation are
        excluded.  Short tokens (<=2 chars) are dropped as noise.
        """
        text = text.lower()
        tokens = re.findall(r"[^\W_]+", text, flags=re.UNICODE)
        return [t for t in tokens if len(t) > 2]

    def _build_corpus_stats(self, all_tokens: list[list[str]]) -> None:
        """Build corpus-wide statistics for BM25."""
        # Build vocabulary
        all_terms: set[str] = set()
        for tokens in all_tokens:
            all_terms.update(tokens)

        self._vocab = {term: idx for idx, term in enumerate(sorted(all_terms))}
        self._dimension = len(self._vocab)

        # Document frequencies
        self._doc_freqs = Counter()
        total_len = 0
        for tokens in all_tokens:
            unique_terms = set(tokens)
            self._doc_freqs.update(unique_terms)
            total_len += len(tokens)

        self._num_docs = len(all_tokens)
        self._avg_doc_len = total_len / self._num_docs if self._num_docs > 0 else 0.0

    def _embed_with_stats(self, tokens: list[str]) -> list[float]:
        """Embed tokens using existing corpus stats."""
        term_counts = Counter(tokens)
        doc_len = len(tokens)

        vector = [0.0] * self._dimension
        for term, count in term_counts.items():
            if term in self._vocab:
                idx = self._vocab[term]
                idf = self._idf(term)
                tf = self._tf_weight(count, doc_len, self._avg_doc_len)
                vector[idx] = idf * tf

        return vector

    def _idf(self, term: str) -> float:
        """Calculate IDF for a term."""
        df = self._doc_freqs.get(term, 0)
        if df == 0:
            return 0.0
        # Standard BM25 IDF with smoothing
        return math.log((self._num_docs - df + 0.5) / (df + 0.5) + 1.0)

    def _tf_weight(self, term_freq: int, doc_len: int, avg_doc_len: float) -> float:
        """Calculate BM25 term frequency weight."""
        if avg_doc_len == 0:
            return term_freq

        norm_len = doc_len / avg_doc_len
        denominator = term_freq + self.k1 * (1 - self.b + self.b * norm_len)
        return (term_freq * (self.k1 + 1)) / denominator if denominator > 0 else 0.0
