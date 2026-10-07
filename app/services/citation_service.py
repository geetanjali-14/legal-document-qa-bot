from typing import List, Tuple
from app.models.document import DocumentChunk
from app.models.chat import Citation


class CitationService:
    @staticmethod
    def create_citations(retrieved_chunks: List[Tuple[DocumentChunk, float]]) -> List[Citation]:
        """
        Build verifiable citations from retrieved chunks.
        Extracts document name, page number, section name, and concise snippet.
        """
        citations: List[Citation] = []
        seen_chunks = set()

        for chunk, score in retrieved_chunks:
            if chunk.chunk_id in seen_chunks:
                continue
            seen_chunks.add(chunk.chunk_id)

            # Produce clean snippet of up to 250 characters
            snippet = chunk.text.strip().replace("\n", " ")
            if len(snippet) > 250:
                snippet = snippet[:247] + "..."

            citations.append(
                Citation(
                    document_id=chunk.document_id,
                    document_name=chunk.document_name,
                    page_number=chunk.page_number,
                    section=chunk.section or "General",
                    chunk_id=chunk.chunk_id,
                    snippet=snippet,
                    relevance_score=round(float(score), 4)
                )
            )

        return citations
