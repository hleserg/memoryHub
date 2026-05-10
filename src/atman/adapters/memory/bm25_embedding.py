"""
BM25EmbeddingAdapter - pure Python BM25-based sparse embeddings.

Implements BM25 text scoring as a form of sparse embedding.
Zero external dependencies, suitable for lightweight deployments.
"""

import math
import re
from collections import Counter
from typing import override

from atman.core.ports.embedding import EmbeddingPort


class BM25EmbeddingAdapter(EmbeddingPort):
    """
    BM25-based embedding adapter.

    Uses BM25 scoring with a fixed vocabulary derived from text.
    Produces sparse vector representations suitable for lexical similarity.

    This is NOT a neural embedding - it's a classical IR approach
    that requires no external dependencies or model downloads.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        """
        Initialize BM25 adapter.

        Args:
            k1: BM25 term frequency saturation parameter
            b: BM25 document length normalization parameter
        """
        self.k1 = k1
        self.b = b
        self._vocab: dict[str, int] = {}
        self._doc_freqs: Counter = Counter()
        self._avg_doc_len = 0.0
        self._num_docs = 0
        self._dimension = 0

    @override
    def embed(self, text: str) -> list[float]:
        """
        Generate BM25-weighted term vector for text.

        Note: In BM25, each "embedding" is context-dependent on the corpus.
        For single-text embedding, we treat the text as its own corpus.
        """
        tokens = self._tokenize(text)
        term_counts = Counter(tokens)
        doc_len = len(tokens)

        # For single document, build minimal corpus stats
        vocab = list(term_counts.keys())
        self._vocab = {term: idx for idx, term in enumerate(vocab)}
        self._dimension = len(vocab)

        # Create sparse vector
        vector = [0.0] * self._dimension
        for term, count in term_counts.items():
            idx = self._vocab[term]
            # Simple TF weight as fallback when no corpus stats
            vector[idx] = self._tf_weight(count, doc_len, doc_len)

        return vector

    def embed_with_corpus(
        self, text: str, corpus_docs: list[str]
    ) -> list[float]:
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
        """Generate embeddings for multiple texts using shared corpus stats."""
        # Build shared vocabulary from all texts
        all_tokens = [self._tokenize(text) for text in texts]
        self._build_corpus_stats(all_tokens)

        return [self._embed_with_stats(tokens) for tokens in all_tokens]

    @override
    def dimension(self) -> int:
        """Return current vocabulary dimension."""
        return self._dimension

    @override
    def similarity(self, vec1: list[float], vec2: list[float]) -> float:
        """Calculate cosine similarity between two sparse vectors."""
        if len(vec1) != len(vec2):
            raise ValueError("Vectors must have same dimension")

        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    def _tokenize(self, text: str) -> list[str]:
        """Simple tokenization: lowercase, alphanumeric only."""
        text = text.lower()
        tokens = re.findall(r"[a-z0-9]+", text)
        # Filter out very short tokens
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
