import re
from typing import Optional, List, Dict, Any


def extract_user_query(text: str) -> str:
    """
    Strips Slack user mentions (e.g. <@U12345678>) and leading/trailing whitespace.
    """
    if not text:
        return ""
    # Strip Slack user mentions like <@U0123ABCD>, <@U_BOT123>, or <@W12345678|legalbot>
    cleaned = re.sub(r"<@[A-Za-z0-9_]+(?:\|[^>]+)?>", "", text)
    # Strip subteam mentions <!subteam^ID|handle>
    cleaned = re.sub(r"<!subteam\^[A-Za-z0-9_]+(?:\|[^>]+)?>", "", cleaned)
    # Strip special broadcast mentions <!here>, <!channel>, <!everyone>
    cleaned = re.sub(r"<!(?:here|channel|everyone)>", "", cleaned)
    return cleaned.strip()


def parse_select_command(text: str) -> Optional[str]:
    """
    Detects commands like:
      - select doc_12345
      - use doc_12345
      - document doc_12345
      - set doc doc_12345
    Returns the document ID if matched, else None.
    """
    cleaned = extract_user_query(text)
    match = re.search(r"^(?:select|use|set\s+document|set\s+doc|document|doc)\s+([a-zA-Z0-9_.\-]+)$", cleaned, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def is_list_docs_command(text: str) -> bool:
    """Detects commands asking to list available documents."""
    cleaned = extract_user_query(text).lower()
    return cleaned in ("list docs", "list documents", "show docs", "show documents", "documents", "docs", "list")


def is_clear_context_command(text: str) -> bool:
    """Detects commands to clear the active document/conversation session."""
    cleaned = extract_user_query(text).lower()
    return cleaned in ("clear", "reset", "reset context", "clear context", "new session", "start over")


def is_help_command(text: str) -> bool:
    """Detects commands asking for help or instructions."""
    cleaned = extract_user_query(text).lower()
    return cleaned in ("help", "commands", "start", "info")


def markdown_to_slack(text: str) -> str:
    """
    Converts standard Markdown formatting to Slack-compatible mrkdwn:
    - Unescapes literal backslashes before asterisks or formatting symbols (e.g. \\* -> *)
    - Converts standard Markdown bold (**bold**) to Slack bold (*bold*)
    - Converts bullet list items (* item or - item) at line starts to clean Slack bullets (• item)
    """
    if not text:
        return ""

    # 1. Unescape backslashes before markdown symbols
    cleaned = re.sub(r"\\([*_~`•\-])", r"\1", text)

    # 2. Convert standard markdown bold (**bold**) to Slack single asterisk (*bold*)
    # Be careful not to replace triple asterisks incorrectly
    cleaned = re.sub(r"\*\*\*(.+?)\*\*\*", r"*\1*", cleaned)
    cleaned = re.sub(r"\*\*(.+?)\*\*", r"*\1*", cleaned)

    # 3. Convert markdown list bullets (* item or - item) at line beginnings to bullet symbol
    cleaned = re.sub(r"(?m)^(\s*)[\*\-]\s+", r"\1• ", cleaned)

    return cleaned


def format_slack_answer(
    answer: str,
    sources: Optional[List[Dict[str, Any]]] = None,
    document_id: Optional[str] = None,
    show_document_context: bool = False
) -> str:
    """
    Formats the assistant's answer for Slack:
    - Converts Markdown bold and list bullets into Slack mrkdwn
    - Preserves answers
    - Appends citations (page numbers, section titles, clause numbers)
    - Hides document ID from ordinary responses unless show_document_context=True
    - Truncates safely if exceeding Slack's message limits
    """
    clean_answer = markdown_to_slack(answer.strip())
    parts = [clean_answer]

    if sources:
        citations = []
        for s in sources:
            page = s.get("page_number", 1)
            section = s.get("section") or s.get("section_title") or "General"
            # Strip zero-width chars and clean whitespace from section title
            section = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", section).strip()
            section = " ".join(section.split())
            clause = s.get("clause_number")
            cite_str = f"• *Page {page}* — {section}"
            if clause:
                cite_str += f" (Clause {clause})"
            if cite_str not in citations:
                citations.append(cite_str)

        if citations:
            parts.append("\n*Sources & References:*\n" + "\n".join(citations[:5]))

    if document_id and show_document_context:
        parts.append(f"\n_Document Context: `{document_id}`_")

    formatted = "\n\n".join(parts)
    # Ensure within Slack safe block limit (~3900 chars to avoid block truncation)
    if len(formatted) > 3900:
        formatted = formatted[:3850] + "\n\n_... [Response truncated due to length]_"
    return formatted


def format_help_message() -> str:
    """Returns friendly guidance for Slack users."""
    return (
        "*Legal Document QA Bot — Quick Guide*\n\n"
        "Here is what you can do:\n"
        "• *Ask questions*: Mention me with your question (e.g. `@LegalBot What is the termination notice period?`)\n"
        "• *Select a document*: Type `select <document_id>` or `use <document_id>`\n"
        "• *List documents*: Type `list docs` to see all processed documents\n"
        "• *Upload PDF*: Attach a PDF file to a message or DM to automatically index it\n"
        "• *Reset context*: Type `clear` or `reset` to start a fresh conversation session\n"
        "• *Help*: Type `help` to see this message again\n"
    )
