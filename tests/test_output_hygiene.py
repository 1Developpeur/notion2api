from app.output_hygiene import (
    build_hygiene_metadata,
    clean_visible_output,
    detect_visible_output_contamination,
    finalize_visible_output,
    is_hidden_content_type,
    strip_thinking_blocks,
)


def test_strip_thinking_blocks_removes_complete_and_unclosed_markup():
    assert (
        strip_thinking_blocks("<think>hidden</think>\n\nVisible answer")
        == "Visible answer"
    )
    assert strip_thinking_blocks("<think>hidden only") == ""


def test_clean_visible_output_is_idempotent():
    dirty = "<l### Overall assessment\n\nBody"
    once = clean_visible_output(dirty)
    twice = clean_visible_output(once)
    assert once == twice
    assert once.startswith("### Overall assessment")


def test_legitimate_openers_are_not_flagged_or_mutated():
    samples = [
        "User wants a refund policy summary. Here it is: full refund within 30 days.",
        "Let me walk you through the steps to complete the form.",
        "I need to reset my password, can you help?",
    ]
    for raw in samples:
        assert detect_visible_output_contamination(raw) is False
        assert clean_visible_output(raw) == raw


def test_true_reasoning_leak_still_trims_to_answer_boundary():
    raw = (
        "user is trying to apply a template and I need to verify statutes."
        "### Threshold framing\n\nThis is the answer."
    )
    assert detect_visible_output_contamination(raw) is True
    assert clean_visible_output(raw) == "### Threshold framing\n\nThis is the answer."


def test_finalize_visible_output_returns_metadata():
    raw = "<think>hidden</think>\n\nVisible answer."
    cleaned, hygiene = finalize_visible_output(raw)
    assert cleaned == "Visible answer."
    assert hygiene["hidden_thinking_removed"] is True
    assert hygiene["visible_contamination_detected"] is False
    assert hygiene["retry_recommended"] is False


def test_build_hygiene_metadata_marks_contamination_for_retry():
    raw = "Sonnet 5owever the issue remains."
    cleaned = clean_visible_output(raw)
    hygiene = build_hygiene_metadata(raw, cleaned)
    assert hygiene["visible_contamination_detected"] is True
    assert hygiene["retry_recommended"] is True


def test_is_hidden_content_type_matches_transport_reasoning_types():
    assert is_hidden_content_type("thinking") is True
    assert is_hidden_content_type("redacted-thinking") is True
    assert is_hidden_content_type("text") is False
