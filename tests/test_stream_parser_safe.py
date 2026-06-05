from app import stream_parser_safe


class DummyResponse:
    pass


def test_buffered_thinking_is_not_promoted_after_final_content(monkeypatch):
    def fake_parse_stream(_response):
        yield {"type": "thinking", "text": "The user is asking for a greeting."}
        yield {"type": "final_content", "text": "Hello.", "source_type": "agent-inference"}

    monkeypatch.setattr(stream_parser_safe, "_parse_stream", fake_parse_stream)

    assert list(stream_parser_safe.parse_stream(DummyResponse())) == [
        {"type": "final_content", "text": "Hello.", "source_type": "agent-inference"}
    ]


def test_buffered_thinking_fallback_remains_for_legacy_answer_segments(monkeypatch):
    def fake_parse_stream(_response):
        yield {"type": "thinking", "text": "Legacy answer-only agent-inference text."}

    monkeypatch.setattr(stream_parser_safe, "_parse_stream", fake_parse_stream)

    assert list(stream_parser_safe.parse_stream(DummyResponse())) == [
        {"type": "content", "text": "Legacy answer-only agent-inference text."}
    ]
