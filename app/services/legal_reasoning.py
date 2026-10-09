"""Advanced Legal Reasoning Services (P3-REAS-01, P3-TEMPORAL, P3-OBLE-01, P3-RISK).

Implements:
1. ConflictDetector (P3-REAS-01): Discovers contradictory provisions (e.g. 30 vs 45 days)
   without picking a winner. Labels as 'Potential inconsistency detected...'.
2. TemporalReasoner (P3-TEMPORAL): Extracts deadlines, relative dates, notice windows,
   cure periods, and structured temporal facts.
3. ObligationExtractor (P3-OBLE-01): Structured Party -> Modality -> Action -> Deadline -> Condition.
4. RiskAnalyzer (P3-RISK): Analytical observation of one-sided terms, uncapped liabilities,
   and unusual obligations with strict disclaimer that it is not legal advice.
"""
import re
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class ConflictItem(BaseModel):
    issue_type: str  # "notice_period", "payment_terms", "termination_period", "liability_cap"
    description: str
    provision_a: Dict[str, Any]
    provision_b: Dict[str, Any]
    contradiction_nature: str  # "direct_contradiction", "conditional_difference", "apparent_inconsistency"


class TemporalEvent(BaseModel):
    event_type: str  # "TERMINATION_NOTICE", "PAYMENT_DUE", "CURE_PERIOD", "RENEWAL_WINDOW"
    party: Optional[str] = None
    deadline_text: str  # "within thirty (30) days", "at least 60 days prior to expiration"
    days_numerical: Optional[int] = None
    condition: Optional[str] = None
    section: Optional[str] = None
    page: Optional[int] = None


class ObligationItem(BaseModel):
    party: str
    modality: str  # "shall", "must", "will", "agrees to", "may", "prohibited from"
    action: str
    deadline: Optional[str] = None
    condition: Optional[str] = None
    obligation_type: str  # "obligation", "permission", "prohibition", "discretionary_right"
    citation: Optional[Dict[str, Any]] = None


class RiskObservation(BaseModel):
    observation_type: str  # "one_sided_termination", "uncapped_liability", "broad_indemnity", "unusual_notice"
    title: str
    evidence_snippet: str
    potential_issue: str
    section: Optional[str] = None
    page: Optional[int] = None


class ConflictDetector:
    """Discovers and describes potential contradictions across retrieved evidence."""

    NOTICE_PERIOD_RE = re.compile(
        r'(?:(\d+)|(?:thirty|forty-five|sixty|ninety|ten|fifteen|twenty))\s*(?:\((\d+)\))?\s*(?:days?|business\s+days?)\b',
        re.IGNORECASE
    )

    WORD_TO_NUM = {
        "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30,
        "forty-five": 45, "sixty": 60, "ninety": 90
    }

    def detect_conflicts(self, evidence_items: List[Any]) -> List[ConflictItem]:
        conflicts: List[ConflictItem] = []
        notice_provisions = []

        for item in evidence_items:
            text = getattr(item, "text", "")
            sec = getattr(item, "section", "")
            page = getattr(item, "page_number", 1)

            # Check for notice periods in termination or dispute or fees
            t_lower = text.lower()
            if any(k in t_lower for k in ["notice", "terminate", "payment", "cure"]):
                # Classify the type of notice to avoid flagging distinct business processes (e.g. renewal vs termination)
                category = "general"
                if "renewal" in t_lower or "expiration" in t_lower:
                    category = "renewal"
                elif "terminate" in t_lower or "termination" in t_lower:
                    category = "termination"
                elif "payment" in t_lower or "invoice" in t_lower or "fees" in t_lower:
                    category = "payment"
                elif "cure" in t_lower or "breach" in t_lower:
                    category = "cure"

                for m in self.NOTICE_PERIOD_RE.finditer(text):
                    num_str = m.group(2) or m.group(1)
                    val = None
                    if num_str:
                        val = int(num_str) if num_str.isdigit() else self.WORD_TO_NUM.get(num_str.lower())
                    else:
                        full = m.group(0).lower()
                        for word, n in self.WORD_TO_NUM.items():
                            if word in full:
                                val = n
                                break
                    if val:
                        notice_provisions.append({
                            "days": val,
                            "section": sec,
                            "page": page,
                            "category": category,
                            "snippet": text[:200]
                        })

        # Check for disparate numbers across distinct sections within the same or overlapping category
        for i in range(len(notice_provisions)):
            for j in range(i + 1, len(notice_provisions)):
                a = notice_provisions[i]
                b = notice_provisions[j]
                if a["section"] != b["section"] and a["days"] != b["days"]:
                    # Contradiction requires same category, or one being general notice
                    is_same_topic = (
                        a["category"] == b["category"] or
                        a["category"] == "general" or
                        b["category"] == "general"
                    )
                    if is_same_topic:
                        conflicts.append(
                            ConflictItem(
                                issue_type="notice_period",
                                description=f"Potential inconsistency detected between Section '{a['section']}' ({a['days']} days) and Section '{b['section']}' ({b['days']} days).",
                                provision_a=a,
                                provision_b=b,
                                contradiction_nature="apparent_inconsistency"
                            )
                        )

        return conflicts


class TemporalReasoner:
    """Extracts structured timeline, deadline, and temporal rules."""

    TEMPORAL_PATTERNS = [
        (re.compile(r'within\s+(\d+|\w+)\s+(?:days?|months?|years?)\s+(?:of|after|from)\s+([^,\.;]+)', re.I), "DEADLINE"),
        (re.compile(r'at\s+least\s+(\d+|\w+)\s+(?:days?|months?)\s+(?:prior\s+to|before)\s+([^,\.;]+)', re.I), "NOTICE_WINDOW"),
        (re.compile(r'effective\s+date\s*(?:is|shall\s+be)?\s*([A-Za-z]+\s+\d{1,2},\s*\d{4}|\d{4}-\d{2}-\d{2})', re.I), "EFFECTIVE_DATE"),
        (re.compile(r'(?:cure|remedy)\s+period\s+of\s+(\d+|\w+)\s+(?:days?|business\s+days?)', re.I), "CURE_PERIOD"),
    ]

    def extract_temporal_events(self, text: str, section: Optional[str] = None, page: Optional[int] = None) -> List[TemporalEvent]:
        events: List[TemporalEvent] = []
        for pat, ev_type in self.TEMPORAL_PATTERNS:
            for m in pat.finditer(text):
                full_m = m.group(0)
                num = None
                if m.group(1).isdigit():
                    num = int(m.group(1))
                cond = m.group(2) if len(m.groups()) > 1 else None

                events.append(
                    TemporalEvent(
                        event_type=ev_type,
                        deadline_text=full_m,
                        days_numerical=num,
                        condition=cond.strip() if cond else None,
                        section=section,
                        page=page
                    )
                )
        return events


class ObligationExtractor:
    """Extracts structured legal obligations and modalities."""

    # Modal verbs
    MODAL_RE = re.compile(
        r'\b(shall\s+not|may\s+not|shall|must|will|agrees?\s+to|is\s+required\s+to|may)\s+([a-z][a-z0-9\s,\'/-]{5,100}?)(?=[,\.;]|\bif\b|\bunless\b|\bprovided\b|$)',
        re.IGNORECASE
    )

    def extract_obligations(self, text: str, section: Optional[str] = None, page: Optional[int] = None) -> List[ObligationItem]:
        obligations: List[ObligationItem] = []
        sentences = [s.strip() for s in re.split(r'[.;]\s+', text) if len(s.strip()) > 15]

        for s in sentences:
            m = self.MODAL_RE.search(s)
            if m:
                mod = m.group(1).lower()
                action = m.group(2).strip()

                # Infer party from sentence subject
                party = "Party"
                for p_candidate in ["Client", "Vendor", "Supplier", "Customer", "Company", "Licensee", "Licensor", "Disclosing Party", "Receiving Party", "Either party"]:
                    if p_candidate.lower() in s.lower():
                        party = p_candidate
                        break

                if "not" in mod:
                    ob_type = "prohibition"
                elif mod == "may":
                    ob_type = "permission"
                else:
                    ob_type = "obligation"

                obligations.append(
                    ObligationItem(
                        party=party,
                        modality=mod,
                        action=action,
                        obligation_type=ob_type,
                        citation={"section": section, "page": page} if section or page else None
                    )
                )
        return obligations


class RiskAnalyzer:
    """Analytical detector for one-sided clauses, uncapped liability, and restrictive terms."""

    def analyze_risks(self, evidence_items: List[Any]) -> List[RiskObservation]:
        observations: List[RiskObservation] = []

        for item in evidence_items:
            text = getattr(item, "text", "")
            sec = getattr(item, "section", "")
            page = getattr(item, "page_number", 1)
            t_lower = text.lower()

            # 1. Uncapped liability or indemnity exceptions
            if "limitation of liability" in t_lower or "liability cap" in t_lower:
                if "indemnification" in t_lower and ("shall not apply" in t_lower or "unlimited" in t_lower or "except for" in t_lower):
                    observations.append(
                        RiskObservation(
                            observation_type="uncapped_liability",
                            title="Indemnification Carve-out from Liability Cap",
                            evidence_snippet=text[:250],
                            potential_issue="The limitation of liability excludes indemnification claims, leaving indemnification potentially uncapped.",
                            section=sec,
                            page=page
                        )
                    )

            # 2. Unilateral termination
            if "termination" in t_lower and ("at its sole discretion" in t_lower or "without cause" in t_lower):
                if not any(k in t_lower for k in ["mutual", "either party"]):
                    observations.append(
                        RiskObservation(
                            observation_type="one_sided_termination",
                            title="Unilateral Discretionary Termination",
                            evidence_snippet=text[:250],
                            potential_issue="Termination without cause may be exercisable solely by one party.",
                            section=sec,
                            page=page
                        )
                    )

            # 3. Disproportionate notice periods (> 60 days)
            if "notice" in t_lower and any(k in t_lower for k in ["90 days", "ninety (90) days", "120 days"]):
                observations.append(
                    RiskObservation(
                        observation_type="unusual_notice",
                        title="Extended Notice Requirement",
                        evidence_snippet=text[:250],
                        potential_issue="Notice window requires 90+ days advance communication, which is longer than typical commercial baselines.",
                        section=sec,
                        page=page
                    )
                )

        return observations
