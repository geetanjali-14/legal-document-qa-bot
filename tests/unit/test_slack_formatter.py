import pytest
from app.integrations.slack_formatter import (
    extract_user_query,
    parse_select_command,
    is_list_docs_command,
    is_clear_context_command,
    is_help_command,
    format_slack_answer
)


def test_extract_user_query():
    # Single mention
    assert extract_user_query("<@U12345678> hello bot") == "hello bot"
    # Mention with label
    assert extract_user_query("<@U12345678|legalbot> what is clause 5?") == "what is clause 5?"
    # Multiple mentions
    assert extract_user_query("<@U12345678> <@U87654321> check this agreement") == "check this agreement"
    # Broadcast mentions
    assert extract_user_query("<!here> <@U123> what is the notice period?") == "what is the notice period?"
    # Empty query
    assert extract_user_query("<@U12345678>") == ""
    assert extract_user_query("   ") == ""


def test_parse_select_command():
    assert parse_select_command("select doc_12345") == "doc_12345"
    assert parse_select_command("<@U123> use doc_abc") == "doc_abc"
    assert parse_select_command("set document doc_987") == "doc_987"
    assert parse_select_command("document doc_test") == "doc_test"
    assert parse_select_command("what is clause 5 in doc_123") is None


def test_command_recognition():
    assert is_list_docs_command("list docs") is True
    assert is_list_docs_command("show documents") is True
    assert is_list_docs_command("<@U123> docs") is True
    assert is_list_docs_command("what is this doc?") is False

    assert is_clear_context_command("clear") is True
    assert is_clear_context_command("reset context") is True
    assert is_clear_context_command("new session") is True
    assert is_clear_context_command("clear the agreement clause") is False

    assert is_help_command("help") is True
    assert is_help_command("commands") is True


def test_format_slack_answer():
    answer = "The notice period is 30 days."
    sources = [
        {
            "page_number": 3,
            "section": "Clause 4",
            "clause_number": "4.1"
        }
    ]
    formatted = format_slack_answer(answer, sources=sources, document_id="doc_123")
    assert "The notice period is 30 days." in formatted
    assert "*Page 3* — Clause 4 (Clause 4.1)" in formatted
    assert "_Document Context: `doc_123`_" in formatted

