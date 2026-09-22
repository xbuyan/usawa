"""
Knowledge-base retrieval for the assistant.

The approach: score every KB document against the user's question with a
TF-IDF-weighted overlap of tag terms and content terms, then hand the top
documents to Claude as grounding context. TF-IDF rather than raw keyword
matching so a word that appears in every document (e.g. "guidance")
doesn't dominate the score, and common-in-question terms count for less
than distinctive ones.

Why not embeddings/pgvector: no vector store is available in this
deployment, and keyword retrieval over a small, tightly-edited corpus is
accurate because the corpus is small and the tags encode the synonyms HR
users actually type. The retrieval interface below (retrieve(question) ->
list of {doc_id, title, score, content}) is deliberately the seam to swap
in pgvector embeddings when the corpus grows past what TF-IDF handles
well (~hundreds of documents, at which point semantic matching starts
beating curated synonyms anyway). Scaling note for that day: keep this
module's public function signature, compute embeddings offline, store
them in Postgres with pgvector, and ANN-index them — the chatbot code
shouldn't need to change.

Never raises: retrieval failure degrades to an empty result, which the
chatbot reports honestly ("no vetted guidance matched") rather than
sending Claude in ungrounded.
"""

import math
import re
from typing import Dict, List

from kb_documents import KB_DOCUMENTS

# Below this score, we treat retrieval as "no match" rather than sending
# the model weakly-related documents it might lean on for false authority.
MIN_SCORE = 0.05

# Tokenization: lowercase words, dropped stopwords. A tiny stopword list
# is fine here — TF-IDF already downweights frequent terms across the
# corpus, and HR questions are short.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "is",
    "are", "do", "does", "how", "what", "i", "we", "our", "my", "you",
    "your", "it", "that", "this", "with", "should", "can", "be", "have",
    "has", "at", "as", "by", "from", "about",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> List[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1]


def _doc_tokens(doc: Dict) -> List[str]:
    """Tags count multiple times (they're curated relevance signals), plus
    title and content once. This is the corpus the TF-IDF weights come from."""
    tokens = []
    for tag in doc["tags"]:
        tokens.extend([tag] * 3)
    tokens.extend(_tokenize(doc["title"]))
    tokens.extend(_tokenize(doc["content"]))
    return tokens


class KnowledgeBase:
    """Precomputed TF-IDF index over KB_DOCUMENTS. Build once per process;
    the corpus is small so this costs microseconds."""

    def __init__(self, documents: List[Dict] = None):
        self.documents = documents if documents is not None else KB_DOCUMENTS
        self._docs_by_id = {d["id"]: d for d in self.documents}
        self._df: Dict[str, int] = {}
        self._doc_tokens: List[List[str]] = []
        self._doc_len: List[int] = []
        self._doc_tag_terms: List[set] = []

        for doc in self.documents:
            tokens = _doc_tokens(doc)
            self._doc_tokens.append(tokens)
            self._doc_len.append(len(tokens) or 1)
            # Curated tag terms (plus the tags themselves, tokenized —
            # multi-word tags never match a tokenizer output as-is).
            tag_terms = set()
            for tag in doc["tags"]:
                tag_terms.update(_tokenize(tag))
            self._doc_tag_terms.append(tag_terms)
            for term in set(tokens):
                self._df[term] = self._df.get(term, 0) + 1

        self._n_docs = len(self.documents)
        self._avg_len = sum(self._doc_len) / self._n_docs if self._n_docs else 1.0

    def _idf(self, term: str) -> float:
        """Smooth IDF (BM25-style): rare terms score high; a term in every
        document scores ~0. log of (n - df + 0.5) / (df + 0.5) + 1 stays
        positive so a term present everywhere still contributes a little."""
        df = self._df.get(term, 0)
        return math.log((self._n_docs - df + 0.5) / (df + 0.5) + 1.0)

    def search(self, query: str, top_k: int = 3) -> List[Dict]:
        """Returns [{doc_id, title, score, content}], best first. Empty list
        when nothing scores above MIN_SCORE — that's the honest no-match.
        Any unusable input (None, empty, punctuation-only) is a no-match,
        never an exception: the chat endpoint depends on that contract."""
        if not query or not isinstance(query, str):
            return []
        q_tokens = _tokenize(query)
        if not q_tokens or self._n_docs == 0:
            return []

        scores = [0.0] * self._n_docs
        matched_counts = [0] * self._n_docs       # distinct query terms matched
        matched_in_tags = [False] * self._n_docs  # any match on a curated tag term

        for i, tokens in enumerate(self._doc_tokens):
            tf = {}
            for t in tokens:
                tf[t] = tf.get(t, 0) + 1
            norm = len(tokens) / self._avg_len
            for qt in set(q_tokens):
                if qt in tf:
                    scores[i] += self._idf(qt) * tf[qt] / (norm + 0.5)
                    matched_counts[i] += 1
                    if qt in self._doc_tag_terms[i]:
                        matched_in_tags[i] = True

        # Match-qualification: a single incidental content word ("who",
        # "final") must NOT manufacture grounding — require at least two
        # distinct matched terms, OR one match on a curated tag term (which
        # keeps legitimate one-word queries like "interviews" working).
        def _qualifies(i: int) -> bool:
            if matched_counts[i] >= 2:
                return True
            return matched_counts[i] == 1 and matched_in_tags[i]

        ranked = sorted(
            ((score, idx) for score, idx in zip(scores, range(self._n_docs))
             if score > MIN_SCORE and _qualifies(idx)),
            reverse=True,
        )
        return [
            {
                "doc_id": self.documents[idx]["id"],
                "title": self.documents[idx]["title"],
                "score": round(score, 4),
                "content": self.documents[idx]["content"],
            }
            for score, idx in ranked[:top_k]
        ]


_kb_singleton = None


def get_kb() -> KnowledgeBase:
    """One index per process. Rebuilt only in tests (via reset_kb)."""
    global _kb_singleton
    if _kb_singleton is None:
        _kb_singleton = KnowledgeBase()
    return _kb_singleton


def reset_kb() -> None:
    global _kb_singleton
    _kb_singleton = None


def retrieve(question: str, top_k: int = 3) -> List[Dict]:
    """Public seam — chatbot.py and tests call this, never the class directly."""
    return get_kb().search(question, top_k=top_k)
