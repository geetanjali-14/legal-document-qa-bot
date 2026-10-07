from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class SectionNode(BaseModel):
    section_id: str
    title: str
    level: int  # 1 = Article/Part, 2 = Section, 3 = Clause, 4 = Sub-clause
    parent_id: Optional[str] = None
    page_start: int
    page_end: int
    breadcrumb: List[str] = Field(default_factory=list)
    raw_header: str
    char_start: int = 0
    char_end: int = 0
    subsections: List["SectionNode"] = Field(default_factory=list)
    text_content: Optional[str] = None


class CrossReference(BaseModel):
    target_ref: str  # e.g., "12.4", "Article 8", "Clause 8.2(b)"
    source_section_id: Optional[str] = None
    source_page: int
    context_sentence: str
    ref_type: str = "cross_reference"  # "subject_to", "pursuant_to", "except_as_provided", "as_described"


class LegalDefinition(BaseModel):
    term: str  # e.g., "Confidential Information"
    definition: str
    section_id: Optional[str] = None
    page_number: int
    raw_snippet: str


class DocumentStructure(BaseModel):
    document_id: str
    content_hash: str
    nodes: List[SectionNode] = Field(default_factory=list)
    definitions: Dict[str, LegalDefinition] = Field(default_factory=dict)
    cross_references: List[CrossReference] = Field(default_factory=list)
    flat_sections: Dict[str, SectionNode] = Field(default_factory=dict)  # keyed by normalized section_id


class StructureResult(BaseModel):
    document_id: str
    total_sections: int
    table_of_contents: List[Dict[str, Any]] = Field(default_factory=list)
    matched_section: Optional[Dict[str, Any]] = None
    referenced_target: Optional[Dict[str, Any]] = None
    latency_ms: float = 0.0


class ComparisonRow(BaseModel):
    topic: str
    status: str  # "same", "different", "present_only_in_a", "present_only_in_b", "insufficient_evidence"
    doc_a_evidence: str
    doc_a_citation: Optional[Dict[str, Any]] = None
    doc_b_evidence: str
    doc_b_citation: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None


class MultiDocComparisonResult(BaseModel):
    doc_a_id: str
    doc_b_id: str
    doc_a_name: str
    doc_b_name: str
    topics: List[str]
    rows: List[ComparisonRow] = Field(default_factory=list)
    summary: str
    latency_ms: float = 0.0

