import time
from typing import List, Tuple, Optional, Set, Dict
from app.models.document import DocumentChunk
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStore
from app.core.config import settings
from app.core.logging import logger
import re

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "up", "about", "into", "through", "after",
    "before", "what", "which", "who", "whom", "this", "that", "these",
    "those", "am", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "having", "do", "does", "did", "doing", "would",
    "should", "could", "ought", "i", "you", "he", "she", "it", "we", "they",
    "if", "as", "than", "so", "can", "will", "just", "under", "per",
    "occurs", "occur", "happens", "happen"
}


GENERIC_LEGAL_TERMS = {
    "client", "vendor", "party", "parties", "agreement", "contract", "section", "document"
}


class RetrievalService:
    def __init__(self, embedding_service: EmbeddingService, vector_store: VectorStore):
        self.embedding_service = embedding_service
        self.vector_store = vector_store
        self.last_retrieval_latency_ms: float = 0.0
        self.last_embedding_latency_ms: float = 0.0

    @staticmethod
    def extract_content_words(text: str) -> Set[str]:
        """Extract lowercase content words (excluding common stop words), preserving hyphenated terms."""
        words = set(re.findall(r"[a-zA-Z]{3,}(?:-[a-zA-Z]{3,})*", text.lower()))
        return words - STOPWORDS

    def is_context_relevant(self, query: str, results: List[Tuple[DocumentChunk, float]]) -> bool:
        """
        Evaluates whether retrieved results represent sufficient semantic evidence
        to answer the query, rather than incidental lexical overlap on generic terms.
        """
        if not results:
            return False

        query_words = self.extract_content_words(query)
        if not query_words:
            return True

        top_chunk, top_score = results[0]
        chunk_words = self.extract_content_words(top_chunk.text)
        if top_chunk.section:
            chunk_words.update(self.extract_content_words(top_chunk.section))

        matching_words = query_words & chunk_words
        overlap_ratio = len(matching_words) / len(query_words)
        non_generic_matches = matching_words - GENERIC_LEGAL_TERMS

        # High semantic similarity with at least one matching content word (excluding purely generic legal terms)
        if top_score >= settings.RELEVANCE_CONFIDENCE_THRESHOLD and len(non_generic_matches) >= 1:
            return True

        # Moderate semantic similarity with substantial query content word coverage
        if top_score >= settings.SIMILARITY_THRESHOLD and overlap_ratio >= settings.MIN_CONTENT_WORD_OVERLAP:
            return True

        logger.info(
            f"Semantic relevance gate rejected retrieval: top_score={top_score:.4f} "
            f"(req_score={settings.RELEVANCE_CONFIDENCE_THRESHOLD}), "
            f"overlap_ratio={overlap_ratio:.2f} ({len(matching_words)}/{len(query_words)} words: {matching_words})"
        )
        return False

    def retrieve(
        self,
        document_id: str,
        query: str,
        top_k: Optional[int] = None,
        threshold: Optional[float] = None
    ) -> List[Tuple[DocumentChunk, float]]:
        """
        Embed query and retrieve top matching document chunks with similarity scores.
        Applies semantic confidence gate to reject irrelevant retrieval results.
        Tracks retrieval latency and query embedding latency.
        """
        t_retrieval_start = time.perf_counter()
        k = top_k or settings.TOP_K
        sim_threshold = threshold if threshold is not None else settings.SIMILARITY_THRESHOLD

        logger.info(f"Retrieving for doc={document_id}, query='{query[:50]}...', top_k={k}")

        # If vocabulary-based embedding provider (e.g. TF-IDF) has not fitted this document, fit from indexed chunks
        if hasattr(self.embedding_service.provider, "fit_document"):
            doc_vecs = getattr(self.embedding_service.provider, "doc_vectorizers", {})
            if document_id not in doc_vecs:
                doc_chunks = self.vector_store.chunks_by_doc.get(document_id, [])
                if doc_chunks:
                    self.embedding_service.provider.fit_document(document_id, [c.text for c in doc_chunks])
        elif hasattr(self.embedding_service.provider, "fit_corpus") and not getattr(self.embedding_service.provider, "is_fitted", False):
            doc_chunks = self.vector_store.chunks_by_doc.get(document_id, [])
            if doc_chunks:
                self.embedding_service.provider.fit_corpus([c.text for c in doc_chunks])

        t_embed_start = time.perf_counter()
        query_vector = self.embedding_service.embed_query(query, document_id=document_id)
        self.last_embedding_latency_ms = max(0.0, (time.perf_counter() - t_embed_start) * 1000.0)

        # Candidate retrieval: retrieve broader candidate set for reranking
        candidate_k = max(k * 4, 20)
        raw_candidates = self.vector_store.search(
            document_id=document_id,
            query_vector=query_vector,
            top_k=candidate_k,
            similarity_threshold=sim_threshold
        )
        self.last_retrieval_latency_ms = max(0.0, (time.perf_counter() - t_retrieval_start) * 1000.0)

        # Apply semantic relevance gate on top candidates when using default threshold
        if threshold is None and raw_candidates:
            if not self.is_context_relevant(query, raw_candidates):
                results = []
            else:
                results = raw_candidates
        else:
            results = raw_candidates

        # Apply Reranker: Multi-factor scoring (semantic similarity + lexical/clause/section match)
        reranked_results = self.rerank_candidates(query, results)

        # Context Deduplication: remove chunks with identical text or nested overlaps
        deduped_results = self.deduplicate_chunks(reranked_results)[:k]

        logger.info(
            f"Retrieved {len(deduped_results)} chunks above threshold {sim_threshold} "
            f"(candidates={len(raw_candidates)}, deduped={len(deduped_results)}, retrieval={self.last_retrieval_latency_ms:.2f}ms, "
            f"embedding={self.last_embedding_latency_ms:.2f}ms)"
        )

        for chunk, score in deduped_results:
            logger.info(
                f"Retrieved chunk score={score:.4f}, "
                f"section={chunk.section}, page={chunk.page_number}"
            )
        return deduped_results

    @staticmethod
    def _bm25_lexical_score(query_tokens: List[str], chunk_text: str, avg_doc_len: float = 100.0, k1: float = 1.5, b: float = 0.75) -> float:
        """
        Lightweight BM25 term frequency saturation score over chunk text.
        Requires zero external libraries and provides principled lexical ranking.
        """
        if not query_tokens or not chunk_text:
            return 0.0
        doc_tokens = re.findall(r"[a-zA-Z0-9]{2,}", chunk_text.lower())
        doc_len = len(doc_tokens)
        if doc_len == 0:
            return 0.0

        # Term frequency in document
        tf_map: Dict[str, int] = {}
        for token in doc_tokens:
            tf_map[token] = tf_map.get(token, 0) + 1

        score = 0.0
        len_norm = 1.0 - b + b * (doc_len / max(1.0, avg_doc_len))
        for q_tok in query_tokens:
            tf = tf_map.get(q_tok, 0)
            if tf > 0:
                # BM25 term saturation
                score += (tf * (k1 + 1.0)) / (tf + k1 * len_norm)
        return score

    def rerank_candidates(
        self,
        query: str,
        candidates: List[Tuple[DocumentChunk, float]]
    ) -> List[Tuple[DocumentChunk, float]]:
        """
        Rerank retrieved candidates based on:
        - semantic relevance score
        - BM25-style term frequency saturation
        - exact lexical overlap of significant terms
        - clause and section match with query references
        - numbers and date mentions match
        - defined term match
        """
        if not candidates:
            return []

        query_words = self.extract_content_words(query)
        query_tokens = [w for w in query_words if w not in GENERIC_LEGAL_TERMS]
        # Extract potential clause/section references in query (e.g. "Section 15", "Clause 4.2")
        ref_matches = set(re.findall(r'(?:section|clause|article|schedule|annexure)\s+([0-9IVXLCDM\.\(\)a-z]+)', query, re.IGNORECASE))
        # Extract numbers in query (e.g., "30", "45", "5000")
        query_numbers = set(re.findall(r'\b\d+\b', query))
        # Extract quoted defined terms
        query_quotes = set(re.findall(r'["“\']([^"“”\']{2,40})["”\']', query))

        # Compute average chunk token length across candidates for BM25 normalization
        lengths = [len(c.text.split()) for c, _ in candidates]
        avg_len = sum(lengths) / max(1, len(lengths))

        scored = []
        for chunk, base_score in candidates:
            final_score = base_score
            chunk_text_lower = chunk.text.lower()

            # 1. Clause/Section identifier match boost
            chunk_sec = (chunk.section or "") + " " + (getattr(chunk, "clause_number", "") or "")
            for ref in ref_matches:
                if ref.lower() in chunk_sec.lower():
                    final_score += 0.25
                    break

            # 2. BM25 term saturation boost (normalized)
            if query_tokens:
                bm25_val = self._bm25_lexical_score(query_tokens, chunk.text, avg_doc_len=avg_len)
                # Bound bm25 boost into [0.0, 0.25]
                final_score += min(0.25, bm25_val * 0.05)

            # 3. Lexical content word overlap boost
            if query_words:
                chunk_words = self.extract_content_words(chunk.text)
                overlap = len(query_words & chunk_words) / len(query_words)
                final_score += overlap * 0.15

            # 4. Number match boost (e.g. 30 days, $5,000)
            if query_numbers:
                chunk_numbers = set(re.findall(r'\b\d+\b', chunk.text))
                matching_nums = query_numbers & chunk_numbers
                if matching_nums:
                    final_score += 0.10 * (len(matching_nums) / len(query_numbers))

            # 5. Quoted defined terms boost
            for q_term in query_quotes:
                if q_term.lower() in chunk_text_lower:
                    final_score += 0.20
                    break

            scored.append((chunk, final_score))

        # Sort descending by updated rerank score
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def deduplicate_chunks(self, results: List[Tuple[DocumentChunk, float]]) -> List[Tuple[DocumentChunk, float]]:
        """Remove duplicate or heavily subsumed chunks while preserving highest-ranking score."""
        seen_texts = set()
        deduped = []
        for chunk, score in results:
            clean = " ".join(chunk.text.split())
            if clean in seen_texts:
                continue
            # Check substantial substring overlap (>85% character length match)
            is_redundant = False
            for seen in seen_texts:
                if len(clean) > 80 and clean in seen:
                    is_redundant = True
                    break
            if not is_redundant:
                seen_texts.add(clean)
                deduped.append((chunk, score))
        return deduped

