"""Hierarchical Legal Document Structure Parser (P2-DOC-01, P2-TOOL-05B).

Extracts and parses:
- Hierarchical section/clause trees (Articles, Sections, Clauses, Sub-clauses)
- Page start and end tracking per section
- Defined terms registry ("Confidential Information" means ...)
- Internal cross-references ("subject to Section 12.4")
- Breadcrumbs for chunks and citations
"""
import re
from typing import List, Dict, Optional, Tuple, Any
from app.models.document import PageContent
from app.models.structure import (
    SectionNode,
    CrossReference,
    LegalDefinition,
    DocumentStructure
)
from app.core.logging import logger


class StructureParser:
    """Parser for legal hierarchy, definitions, and cross-references."""

    # Heading detection patterns
    # Article I / ARTICLE 1 / Article 1.
    ARTICLE_PATTERN = re.compile(
        r'^(?:Article|ARTICLE)\s+([0-9IVXLCDM]+)(?:[.:\-\s]+(.*))?$',
        re.IGNORECASE
    )
    # Section 1. / Section 1.2 / Section 1.2.3 / 1.2 Termination
    SECTION_PATTERN = re.compile(
        r'^(?:(?:Section|SECTION)\s+)?(\d+(?:\.\d+)*)\.?(?:\s*[:\-]\s*|\s+)(.*)$',
        re.IGNORECASE
    )
    # Clause (a), (b), (i), (ii), 8.2(b), etc.
    CLAUSE_PATTERN = re.compile(
        r'^(?:Clause\s+)?(\d+(?:\.\d+)*\([a-z0-9]+\)(?:\([a-z0-9]+\))*|\([a-z0-9]+\)(?:\([a-z0-9]+\))*)\.?\s*(.*)$',
        re.IGNORECASE
    )
    # All-caps standalone header: GENERAL PROVISIONS, MISCELLANEOUS
    ALL_CAPS_PATTERN = re.compile(
        r'^([A-Z][A-Z0-9\s,\'&/\-]{3,60})$'
    )

    # Defined terms patterns:
    # "Term" means / "Term" shall mean / "Term" refers to / 'Term' has the meaning / "Term" includes / (the "Term")
    DEF_TERM_PATTERN = re.compile(
        r'["“\']([^"“”\']{2,60})["”\']\s+(?:means|shall\s+mean|refers\s+to|has\s+the\s+meaning|is\s+defined\s+as|includes)\s+(.+?)(?:\.|$)',
        re.IGNORECASE
    )
    # Term: A definition sentence in a defined terms section
    DEF_COLON_PATTERN = re.compile(
        r'^["“\']?([A-Z][A-Za-z0-9\s]{2,50})["”\']?\s*:\s*(.+)$'
    )
    # Parenthetical definition e.g. (hereinafter referred to as "Company") or ("Effective Date")
    DEF_PAREN_PATTERN = re.compile(
        r'\((?:hereinafter\s+(?:referred\s+to\s+as\s+)?|the\s+)?["“\']([^"“”\']{2,50})["”\']\)',
        re.IGNORECASE
    )

    # Cross-reference patterns:
    # subject to Section 12.4 / pursuant to Article 7 / as described in Clause 8.2(b) / as defined in Section 1
    CROSS_REF_PATTERN = re.compile(
        r'(?:(?:subject\s+to|pursuant\s+to|in\s+accordance\s+with|except\s+as\s+provided\s+in|as\s+set\s+forth\s+in|as\s+described\s+in|as\s+defined\s+in|specified\s+in|set\s+out\s+in|under)\s+)'
        r'((?:Section|Article|Clause|Schedule|Exhibit|Annexure)\s+[0-9IVXLCDM]+(?:\.[0-9]+)*(?:\([a-z0-9]+\))*)',
        re.IGNORECASE
    )

    def parse_document(
        self,
        document_id: str,
        content_hash: str,
        pages: List[PageContent]
    ) -> DocumentStructure:
        """Parse pages into a complete DocumentStructure hierarchy."""
        nodes: List[SectionNode] = []
        flat_sections: Dict[str, SectionNode] = {}
        definitions: Dict[str, LegalDefinition] = {}
        cross_references: List[CrossReference] = []

        current_article: Optional[SectionNode] = None
        current_section: Optional[SectionNode] = None
        current_clause: Optional[SectionNode] = None

        full_doc_lines: List[Tuple[int, str]] = []  # (page_number, line)

        for page in pages:
            lines = [l.strip() for l in page.text.split("\n") if l.strip()]
            for line in lines:
                full_doc_lines.append((page.page_number, line))

        # First pass: Identify headings and construct hierarchy
        for page_num, line in full_doc_lines:
            header_match = self._classify_header(line)
            if header_match:
                level, sec_id, title = header_match
                node = SectionNode(
                    section_id=sec_id,
                    title=title or sec_id,
                    level=level,
                    page_start=page_num,
                    page_end=page_num,
                    raw_header=line,
                    breadcrumb=[],
                    subsections=[]
                )

                if level == 1:  # Article
                    node.breadcrumb = [f"Article {sec_id}: {title}" if title else f"Article {sec_id}"]
                    nodes.append(node)
                    current_article = node
                    current_section = None
                    current_clause = None
                elif level == 2:  # Section
                    if current_article:
                        node.parent_id = current_article.section_id
                        node.breadcrumb = current_article.breadcrumb + [f"Section {sec_id}: {title}"]
                        current_article.subsections.append(node)
                    else:
                        node.breadcrumb = [f"Section {sec_id}: {title}"]
                        nodes.append(node)
                    current_section = node
                    current_clause = None
                elif level >= 3:  # Clause or Sub-clause
                    parent = current_section or current_article
                    if parent:
                        node.parent_id = parent.section_id
                        node.breadcrumb = parent.breadcrumb + [f"Clause {sec_id}: {title}"]
                        parent.subsections.append(node)
                    else:
                        node.breadcrumb = [f"Clause {sec_id}: {title}"]
                        nodes.append(node)
                    current_clause = node

                # Index flat section keys (both raw ID and normalized)
                flat_sections[sec_id.lower()] = node
                flat_sections[self._normalize_section_id(sec_id)] = node
                clean_title_key = re.sub(r'[^a-z0-9]', '', (title or "").lower())
                if clean_title_key:
                    flat_sections[clean_title_key] = node
            else:
                # Update page_end on active nodes
                active_node = current_clause or current_section or current_article
                if active_node:
                    active_node.page_end = max(active_node.page_end, page_num)
                    if active_node.text_content:
                        active_node.text_content += "\n" + line
                    else:
                        active_node.text_content = line

        # If no explicit headings found, generate a fallback root section
        if not nodes:
            fallback = SectionNode(
                section_id="1.0",
                title="General Provisions",
                level=1,
                page_start=1,
                page_end=len(pages) if pages else 1,
                raw_header="General Provisions",
                breadcrumb=["General Provisions"]
            )
            nodes.append(fallback)
            flat_sections["1.0"] = fallback
            flat_sections["general"] = fallback

        # Second pass: Extract definitions, cross-references, schedules, and annexures
        tables: List[Dict[str, Any]] = []
        schedules: List[Dict[str, Any]] = []
        annexures: List[Dict[str, Any]] = []

        for page in pages:
            self._extract_definitions(page.text, page.page_number, definitions)
            self._extract_cross_references(page.text, page.page_number, cross_references)
            self._extract_schedules_annexures(page.text, page.page_number, schedules, annexures)
            self._extract_tables(page.text, page.page_number, tables)

        logger.info(
            f"Parsed structure for doc {document_id}: {len(flat_sections)} sections, "
            f"{len(definitions)} definitions, {len(cross_references)} cross-references, "
            f"{len(schedules)} schedules, {len(annexures)} annexures."
        )

        return DocumentStructure(
            document_id=document_id,
            content_hash=content_hash,
            nodes=nodes,
            definitions=definitions,
            cross_references=cross_references,
            flat_sections=flat_sections,
            tables=tables,
            schedules=schedules,
            annexures=annexures
        )

    def _classify_header(self, line: str) -> Optional[Tuple[int, str, str]]:
        """Classify a line as (level, section_id, title) or None."""
        if len(line) > 120 or len(line) < 3:
            return None

        # Check Article
        m_art = self.ARTICLE_PATTERN.match(line)
        if m_art:
            art_num = m_art.group(1).strip()
            title = (m_art.group(2) or "").strip()
            return (1, art_num, title)

        # Check Section (e.g. 1.2 Termination or Section 4 Fees)
        m_sec = self.SECTION_PATTERN.match(line)
        if m_sec:
            sec_num = m_sec.group(1).strip()
            raw_title = (m_sec.group(2) or "").strip()

            # Ignore stray non-section numbers starting lines (e.g. "30 days notice")
            if "." not in sec_num and not line.lower().startswith("section"):
                try:
                    if int(sec_num) > 20:
                        return None
                except ValueError:
                    pass

            # Extract title if followed by dot and body sentence
            dot_split = re.split(r'\.\s+', raw_title, maxsplit=1)
            if len(dot_split) == 2 and len(dot_split[0]) <= 50 and not dot_split[0].endswith("."):
                title = dot_split[0].strip()
            else:
                title = raw_title

            # Distinguish level 2 vs level 3 based on dot depth
            dot_count = sec_num.count(".")
            level = 2 if dot_count == 0 else (3 if dot_count == 1 else 4)
            return (level, sec_num, title)

        # Check Clause e.g. (a) or 8.2(b)
        m_clause = self.CLAUSE_PATTERN.match(line)
        if m_clause:
            clause_id = m_clause.group(1).strip()
            title = (m_clause.group(2) or "").strip()
            level = 3 if "(" in clause_id and clause_id.count("(") == 1 else 4
            return (level, clause_id, title)

        # Check uppercase header e.g. "CONFIDENTIALITY"
        m_caps = self.ALL_CAPS_PATTERN.match(line)
        if m_caps and not line.endswith(".") and len(line.split()) <= 6:
            words = line.strip().split()
            if len(words) >= 1 and not words[0].isdigit():
                return (1, words[0].capitalize(), line.title())

        return None

    def _normalize_section_id(self, sec_id: str) -> str:
        """Strip punctuation and whitespace for fuzzy matching."""
        return re.sub(r'[^a-z0-9]', '', sec_id.lower())

    def _extract_definitions(
        self,
        text: str,
        page_num: int,
        definitions: Dict[str, LegalDefinition]
    ) -> None:
        """Extract defined terms and their definitions."""
        for m in self.DEF_TERM_PATTERN.finditer(text):
            term = m.group(1).strip()
            definition_text = m.group(2).strip()
            clean_term = term.lower()
            if len(clean_term) >= 3 and clean_term not in definitions:
                definitions[clean_term] = LegalDefinition(
                    term=term,
                    definition=definition_text,
                    page_number=page_num,
                    raw_snippet=m.group(0)[:250]
                )

        # Also search for lines starting with 'Term: Definition'
        for line in text.split("\n"):
            m_col = self.DEF_COLON_PATTERN.match(line.strip())
            if m_col:
                term = m_col.group(1).strip()
                def_text = m_col.group(2).strip()
                clean_term = term.lower()
                if (
                    len(clean_term) >= 3
                    and len(clean_term.split()) <= 5
                    and clean_term not in definitions
                    and len(def_text) > 15
                ):
                    definitions[clean_term] = LegalDefinition(
                        term=term,
                        definition=def_text,
                        page_number=page_num,
                        raw_snippet=line[:250]
                    )

        # Also search for parenthetical definitions e.g. (the "Agreement")
        for m_par in self.DEF_PAREN_PATTERN.finditer(text):
            p_term = m_par.group(1).strip()
            clean_p = p_term.lower()
            if len(clean_p) >= 3 and clean_p not in definitions:
                start_c = max(0, m_par.start() - 60)
                end_c = min(len(text), m_par.end() + 30)
                surrounding = text[start_c:end_c].replace("\n", " ").strip()
                definitions[clean_p] = LegalDefinition(
                    term=p_term,
                    definition=f"Defined entity or concept in context: {surrounding}",
                    page_number=page_num,
                    raw_snippet=surrounding[:250]
                )

    def _extract_cross_references(
        self,
        text: str,
        page_num: int,
        cross_references: List[CrossReference]
    ) -> None:
        """Extract explicit cross-references across sections."""
        for m in self.CROSS_REF_PATTERN.finditer(text):
            target = m.group(1).strip()
            # Capture surrounding sentence context
            start_pos = max(0, m.start() - 50)
            end_pos = min(len(text), m.end() + 70)
            context = text[start_pos:end_pos].replace("\n", " ").strip()
            cross_references.append(
                CrossReference(
                    target_ref=target,
                    source_page=page_num,
                    context_sentence=context
                )
            )

    def _extract_schedules_annexures(
        self,
        text: str,
        page_num: int,
        schedules: List[Dict[str, Any]],
        annexures: List[Dict[str, Any]]
    ) -> None:
        """Detect schedule and annexure headers/references."""
        sched_pattern = re.compile(r'\b(?:Schedule|SCHEDULE)\s+([A-Z0-9]+)(?:[.:\-\s]+(.*))?', re.IGNORECASE)
        annex_pattern = re.compile(r'\b(?:Annexure|ANNEXURE|Exhibit|EXHIBIT|Appendix|APPENDIX)\s+([A-Z0-9IVX]+)(?:[.:\-\s]+(.*))?', re.IGNORECASE)
        for line in text.split("\n"):
            line_str = line.strip()
            m_s = sched_pattern.match(line_str)
            if m_s:
                schedules.append({
                    "schedule_id": m_s.group(1).strip(),
                    "title": (m_s.group(2) or "").strip() or f"Schedule {m_s.group(1).strip()}",
                    "page_number": page_num,
                    "header": line_str
                })
            m_a = annex_pattern.match(line_str)
            if m_a:
                annexures.append({
                    "annexure_id": m_a.group(1).strip(),
                    "title": (m_a.group(2) or "").strip() or f"Annexure {m_a.group(1).strip()}",
                    "page_number": page_num,
                    "header": line_str
                })

    def _extract_tables(
        self,
        text: str,
        page_num: int,
        tables: List[Dict[str, Any]]
    ) -> None:
        """Detect markdown-like or pipe/tab delimited tabular data."""
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        table_lines = []
        for line in lines:
            if "|" in line or "\t" in line or (re.search(r'\s{3,}', line) and len(re.findall(r'\s{3,}', line)) >= 2):
                table_lines.append(line)
            else:
                if len(table_lines) >= 2:
                    tables.append({
                        "page_number": page_num,
                        "row_count": len(table_lines),
                        "content": "\n".join(table_lines)
                    })
                table_lines = []
        if len(table_lines) >= 2:
            tables.append({
                "page_number": page_num,
                "row_count": len(table_lines),
                "content": "\n".join(table_lines)
            })

