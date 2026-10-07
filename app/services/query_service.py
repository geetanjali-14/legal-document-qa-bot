import re
from typing import List, Tuple, Set, Optional
from app.models.document import DocumentChunk


def decompose_query(query: str) -> List[str]:
    """
    Deterministically decomposes compound queries into distinct information requirements
    (sub-questions), while leaving single/simple queries untouched.
    """
    cleaned = query.strip()
    if not cleaned:
        return [query]

    # 1. Multiple question marks e.g. "What is X? What is Y?"
    q_parts = [p.strip() for p in re.split(r'\?+', cleaned) if p.strip()]
    if len(q_parts) > 1:
        return [p + '?' if not p.endswith('?') else p for p in q_parts]

    text = cleaned.rstrip('? \t\n')

    # 2. Semicolon-separated sub-clauses
    semi_parts = [p.strip() for p in text.split(';') if p.strip()]
    if len(semi_parts) > 1:
        return [p + '?' for p in semi_parts]

    # 3. Explicit multiple clauses where each clause begins with an interrogative starter:
    # e.g., "What is X and what is Y" or "What is X, and who can Y" or "What is X and which court Y"
    pattern = r'(?:,\s*and\s+|\s+and\s+)(?=(?:what|which|who|whom|whose|why)\b)'
    full_q_split = re.split(pattern, text, flags=re.IGNORECASE)
    if len(full_q_split) > 1:
        return [p.strip() + '?' for p in full_q_split if p.strip()]

    # 4. Oxford-comma or 3+ item conjunction lists:
    # e.g., "What is the termination notice period, severance amount, and governing court?"
    if ',' in text:
        starter_match = re.match(
            r'^(what\s+is\s+(?:the\s+)?|what\s+are\s+(?:the\s+)?|which\s+is\s+(?:the\s+)?)',
            text,
            flags=re.IGNORECASE
        )
        if starter_match:
            prefix = starter_match.group(1).strip()
            remainder = text[starter_match.end():].strip()
            parts = re.split(r',\s*(?:and\s+)?|\s+and\s+', remainder, flags=re.IGNORECASE)
            parts = [p.strip() for p in parts if p.strip()]
            if len(parts) >= 3:
                decomposed = []
                for p in parts:
                    p_clean = re.sub(r'^(the|a|an)\s+', '', p, flags=re.IGNORECASE).strip()
                    decomposed.append(f'{prefix} {p_clean}?')
                return decomposed

    return [query]


def clean_subquery_topic(sub_query: str) -> str:
    """
    Extracts a concise, readable subject/topic from a sub-question for unsupported reporting.
    e.g. "what is the severance payment amount?" -> "Severance payment amount"
    """
    cleaned = sub_query.strip().rstrip('?.! ')
    cleaned = re.sub(
        r'^(what\s+is\s+(?:the\s+)?|what\s+are\s+(?:the\s+)?|which\s+(?:is\s+(?:the\s+)?|court\s+(?:has\s+)?)?|who\s+(?:can\s+)?|where\s+(?:must\s+)?|how\s+)',
        '',
        cleaned,
        flags=re.IGNORECASE
    ).strip()
    return cleaned[:1].upper() + cleaned[1:] if cleaned else "Requested information"
