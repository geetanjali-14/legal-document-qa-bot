import time
import re
from typing import List, Tuple, Optional, Set, Dict
from rank_bm25 import BM25Okapi
from app.models.document import DocumentChunk
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStore
from app.core.config import settings
from app.core.logging import logger

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
    "client", "vendor", "party", "parties", "agreement", "contract", "section", "document",
    "service", "services", "provision", "provisions"
}


class RetrievalService:
    """
    Hybrid Retrieval Service combining Dense Retrieval (Qdrant) and
    BM25 Lexical Retrieval with Reciprocal Rank Fusion (RRF).
    """
    def __init__(self, embedding_service: EmbeddingService, vector_store: VectorStore):
        self.embedding_service = embedding_service
        self.vector_store = vector_store
        self.last_retrieval_latency_ms: float = 0.0
        self.last_embedding_latency_ms: float = 0.0
        # BM25 index cache per document: doc_id -> (BM25Okapi, List[DocumentChunk])
        self._bm25_indices: Dict[str, Tuple[BM25Okapi, List[DocumentChunk]]] = {}

    @staticmethod
    def stem_term(t: str) -> str:
        """Lightweight legal term stemming for inflection-tolerant matching."""
        t = t.lower()
        for s in ('ation', 'ations', 'ated', 'ate', 'ing', 'ed', 'es', 's', 'e'):
            if len(t) > len(s) + 2 and t.endswith(s):
                return t[:-len(s)]
        return t

    @classmethod
    def extract_content_words(cls, text: str) -> Set[str]:
        """Extract lowercase content words (excluding common stop words), preserving hyphenated terms."""
        words = set(re.findall(r"[a-zA-Z0-9]{2,}(?:-[a-zA-Z0-9]+)*", text.lower()))
        return words - STOPWORDS

    @classmethod
    def extract_stemmed_words(cls, text: str) -> Set[str]:
        """Extract stemmed content words for inflectional matching."""
        return {cls.stem_term(w) for w in cls.extract_content_words(text)}

    @classmethod
    def tokenize(cls, text: str) -> List[str]:
        """Tokenize text into stemmed lowercase words and identifiers."""
        raw_tokens = re.findall(r"[a-zA-Z0-9]+(?:-[a-zA-Z0-9]+)*", text.lower())
        tokens = []
        for t in raw_tokens:
            tokens.append(t)
            st = cls.stem_term(t)
            if st != t:
                tokens.append(st)
        return tokens

    def _get_or_build_bm25(self, document_id: str) -> Optional[Tuple[BM25Okapi, List[DocumentChunk]]]:
        """Returns or constructs a BM25 index for the specified document chunks."""
        chunks_by_doc = getattr(self.vector_store, "chunks_by_doc", None)
        if chunks_by_doc is None:
            return None
        chunks = chunks_by_doc.get(document_id, [])
        if not chunks:
            return None

        # Check if cache is still fresh
        if document_id in self._bm25_indices:
            cached_index, cached_chunks = self._bm25_indices[document_id]
            if len(cached_chunks) == len(chunks):
                return cached_index, cached_chunks

        tokenized_corpus = []
        for c in chunks:
            # Enrich chunk representation with section title and clause number for BM25 matching
            sec_enrichment = f"{c.section or ''} {getattr(c, 'clause_number', '') or ''} {getattr(c, 'section_number', '') or ''}"
            full_chunk_text = f"{sec_enrichment} {c.text}"
            tokenized_corpus.append(self.tokenize(full_chunk_text))

        bm25 = BM25Okapi(tokenized_corpus)
        self._bm25_indices[document_id] = (bm25, chunks)
        return bm25, chunks

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

        top_score = results[0][1]
        # 1. Reject if top_score is below absolute minimum similarity threshold
        if top_score < settings.SIMILARITY_THRESHOLD:
            return False

        # If query is a broad overview or whole-document question, top semantic chunks are valid context
        q_lower = query.lower()
        if any(p in q_lower for p in ["what is in this", "what is this document", "overview", "summary", "summarize", "about"]):
            return True

        query_stems = self.extract_stemmed_words(query)
        generic_stems = {self.stem_term(g) for g in GENERIC_LEGAL_TERMS}

        # Check evidence across top 3 retrieved candidate chunks
        for cand_chunk, cand_score in results[:3]:
            chunk_words = self.extract_content_words(cand_chunk.text)
            if cand_chunk.section:
                chunk_words.update(self.extract_content_words(cand_chunk.section))

            matching_words = query_words & chunk_words
            overlap_ratio = len(matching_words) / len(query_words)
            non_generic_matches = matching_words - GENERIC_LEGAL_TERMS

            chunk_stems = {self.stem_term(w) for w in chunk_words}
            matching_stems = query_stems & chunk_stems
            stem_non_generic = matching_stems - generic_stems

            if cand_score >= settings.RELEVANCE_CONFIDENCE_THRESHOLD and (non_generic_matches or stem_non_generic):
                return True
            if cand_score >= settings.SIMILARITY_THRESHOLD and overlap_ratio >= settings.MIN_CONTENT_WORD_OVERLAP:
                return True
            stem_overlap = len(matching_stems) / max(1, len(query_stems))
            if cand_score >= settings.SIMILARITY_THRESHOLD and stem_overlap >= settings.MIN_CONTENT_WORD_OVERLAP:
                return True

        logger.info(
            f"Semantic relevance gate rejected retrieval for query '{query}': top_score={top_score:.4f} "
            f"(req_score={settings.RELEVANCE_CONFIDENCE_THRESHOLD})"
        )
        return False

    def retrieve_bm25(self, document_id: str, query: str, top_k: int = 20) -> List[Tuple[DocumentChunk, float]]:
        """Executes BM25 keyword search across document chunks."""
        bm25_data = self._get_or_build_bm25(document_id)
        if not bm25_data:
            return []
        bm25, chunks = bm25_data
        tokens = self.tokenize(query)
        if not tokens:
            return []

        scores = bm25.get_scores(tokens)
        scored_pairs = [(chunks[i], float(scores[i])) for i in range(len(chunks)) if scores[i] > 0]
        scored_pairs.sort(key=lambda x: x[1], reverse=True)
        return scored_pairs[:top_k]

    def reciprocal_rank_fusion(
        self,
        dense_results: List[Tuple[DocumentChunk, float]],
        bm25_results: List[Tuple[DocumentChunk, float]],
        k_constant: int = 60
    ) -> List[Tuple[DocumentChunk, float]]:
        """
        Reciprocal Rank Fusion (RRF):
        RRF_score(d) = sum_{m in models} (1 / (k + rank_m(d)))
        """
        scores: Dict[str, float] = {}
        chunk_map: Dict[str, DocumentChunk] = {}

        for rank, (chunk, _) in enumerate(dense_results, start=1):
            cid = chunk.chunk_id or str(rank)
            chunk_map[cid] = chunk
            scores[cid] = scores.get(cid, 0.0) + (1.0 / (k_constant + rank))

        for rank, (chunk, _) in enumerate(bm25_results, start=1):
            cid = chunk.chunk_id or str(rank)
            chunk_map[cid] = chunk
            scores[cid] = scores.get(cid, 0.0) + (1.0 / (k_constant + rank))

        ranked = [(chunk_map[cid], scores[cid]) for cid in scores]
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked

    def retrieve(
        self,
        document_id: str,
        query: str,
        top_k: Optional[int] = None,
        threshold: Optional[float] = None
    ) -> List[Tuple[DocumentChunk, float]]:
        """
        Hybrid retrieval combining Dense Vector Search + BM25 Lexical Search via RRF.
        Logs detailed diagnostic step-by-step telemetry.
        """
        t_retrieval_start = time.perf_counter()
        k = top_k or settings.TOP_K
        sim_threshold = threshold if threshold is not None else settings.SIMILARITY_THRESHOLD

        logger.info(f"[Retrieval] Query: '{query[:80]}...' | doc_id={document_id} | top_k={k}")

        # If vocabulary-based embedding provider (e.g. TF-IDF) has not fitted this document, fit from indexed chunks
        if hasattr(self.embedding_service.provider, "fit_document"):
            doc_vecs = getattr(self.embedding_service.provider, "doc_vectorizers", {})
            if document_id not in doc_vecs:
                chunks_by_doc = getattr(self.vector_store, "chunks_by_doc", {})
                doc_chunks = chunks_by_doc.get(document_id, [])
                if doc_chunks:
                    self.embedding_service.provider.fit_document(document_id, [c.text for c in doc_chunks])
        elif hasattr(self.embedding_service.provider, "fit_corpus") and not getattr(self.embedding_service.provider, "is_fitted", False):
            chunks_by_doc = getattr(self.vector_store, "chunks_by_doc", {})
            doc_chunks = chunks_by_doc.get(document_id, [])
            if doc_chunks:
                self.embedding_service.provider.fit_corpus([c.text for c in doc_chunks])

        # 1. Dense retrieval
        t_embed_start = time.perf_counter()
        query_vector = self.embedding_service.embed_query(query, document_id=document_id)
        self.last_embedding_latency_ms = max(0.0, (time.perf_counter() - t_embed_start) * 1000.0)

        candidate_k = max(k * 4, 20)
        dense_candidates = self.vector_store.search(
            document_id=document_id,
            query_vector=query_vector,
            top_k=candidate_k,
            similarity_threshold=sim_threshold
        )
        logger.debug(f"[Retrieval Dense] Found {len(dense_candidates)} candidates")

        # 2. BM25 retrieval
        bm25_candidates = self.retrieve_bm25(document_id=document_id, query=query, top_k=candidate_k)
        logger.debug(f"[Retrieval BM25] Found {len(bm25_candidates)} candidates")

        # 3. Reciprocal Rank Fusion
        dense_scores_map = {c.chunk_id: score for c, score in dense_candidates if c.chunk_id}
        if bm25_candidates:
            fused_candidates = self.reciprocal_rank_fusion(dense_candidates, bm25_candidates, k_constant=60)
            # Map original dense similarity score back onto fused candidates when available
            # (or fallback to normalized RRF score) for downstream confidence threshold evaluation
            fused_with_sim = []
            max_rrf = fused_candidates[0][1] if fused_candidates else 1.0
            for c, rrf_score in fused_candidates:
                if c.chunk_id in dense_scores_map:
                    eff_score = dense_scores_map[c.chunk_id]
                elif not dense_candidates:
                    # When dense retrieval is unavailable/mismatched, normalize top BM25 ranks
                    eff_score = min(0.85, (rrf_score / max_rrf) * 0.75) if max_rrf > 0 else rrf_score
                else:
                    eff_score = rrf_score
                fused_with_sim.append((c, eff_score))
            fused_candidates = fused_with_sim
        else:
            fused_candidates = dense_candidates

        self.last_retrieval_latency_ms = max(0.0, (time.perf_counter() - t_retrieval_start) * 1000.0)

        # Log top RRF results
        for r_idx, (c, score) in enumerate(fused_candidates[:5], start=1):
            logger.info(f"[Retrieval Candidate #{r_idx}] score={score:.5f} | sec='{c.section}' | page={c.page_number} | id={c.chunk_id}")

        # Check semantic relevance gate on dense candidates (which have raw similarity scores in [0, 1])
        if threshold is None and dense_candidates:
            if not self.is_context_relevant(query, dense_candidates):
                logger.info(f"[Retrieval Gate] Query '{query}' deemed not relevant to top retrieved candidates.")
                return []
        elif threshold is None and not dense_candidates and not bm25_candidates:
            return []

        # Deduplicate and return top_k
        deduped = self.deduplicate_chunks(fused_candidates)[:k]

        logger.info(
            f"[Retrieval Final] Selected {len(deduped)} chunks for context "
            f"(dense={len(dense_candidates)}, bm25={len(bm25_candidates)}, "
            f"latency={self.last_retrieval_latency_ms:.2f}ms)"
        )
        return deduped

    def rerank_candidates(
        self,
        query: str,
        candidates: List[Tuple[DocumentChunk, float]]
    ) -> List[Tuple[DocumentChunk, float]]:
        """
        Rerank retrieved candidates based on:
        - semantic / fused relevance score
        - exact lexical overlap of significant terms
        - clause and section match with query references
        """
        if not candidates:
            return []

        query_words = self.extract_content_words(query)
        ref_matches = set(re.findall(r'(?:section|clause|article|schedule|annexure)\s+([0-9IVXLCDM\.\(\)a-z]+)', query, re.IGNORECASE))

        scored = []
        for chunk, base_score in candidates:
            final_score = base_score

            chunk_sec = (chunk.section or "") + " " + (getattr(chunk, "clause_number", "") or "")
            for ref in ref_matches:
                if ref.lower() in chunk_sec.lower():
                    final_score += 0.25
                    break

            if query_words:
                chunk_words = self.extract_content_words(chunk.text)
                overlap = len(query_words & chunk_words) / len(query_words)
                final_score += overlap * 0.15

            scored.append((chunk, final_score))

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
            is_redundant = False
            for seen in seen_texts:
                if len(clean) > 80 and clean in seen:
                    is_redundant = True
                    break
            if not is_redundant:
                seen_texts.add(clean)
                deduped.append((chunk, score))
        return deduped
