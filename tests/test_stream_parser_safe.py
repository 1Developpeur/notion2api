import json

import pytest

from app import stream_parser_safe
from app.api.chat import _create_lite_stream_generator, _create_standard_stream_generator
from app.stream_parser import parse_stream


class DummyResponse:
    def __init__(self, lines=None):
        self._lines = lines or []

    def iter_lines(self, decode_unicode=True):
        del decode_unicode
        yield from self._lines


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


def test_parser_emits_completion_only_for_finished_at_patch():
    response = DummyResponse([
        json.dumps({
            "type": "patch",
            "v": [
                {"o": "x", "p": "/s/1/value/0/content", "v": "answer"},
                {"o": "a", "p": "/s/1/finishedAt", "v": 1782249965672},
            ],
        })
    ])

    events = list(parse_stream(response))

    assert {
        "type": "stream_complete",
        "finished_at": 1782249965672,
        "segment_index": 1,
    } in events


def _broken_items():
    yield {"type": "content", "text": "partial"}
    raise RuntimeError("upstream stream broke")


@pytest.mark.parametrize(
    "factory",
    [_create_lite_stream_generator, _create_standard_stream_generator],
)
def test_interrupted_proxy_stream_does_not_emit_done(factory):
    source = _broken_items()
    first_item = next(source)
    proxy_stream = factory("chatcmpl-test", "test-model", first_item, source)

    first_chunk = next(proxy_stream)
    assert "partial" in first_chunk

    with pytest.raises(RuntimeError, match="upstream stream broke"):
        next(proxy_stream)


@pytest.mark.parametrize(
    "factory",
    [_create_lite_stream_generator, _create_standard_stream_generator],
)
def test_successful_proxy_stream_emits_done(factory):
    source = iter([{"type": "content", "text": "complete"}])
    first_item = next(source)

    chunks = list(factory("chatcmpl-test", "test-model", first_item, source))

    assert chunks[-1] == "data: [DONE]\n\n"
    assert '"finish_reason": "stop"' in chunks[-2]
