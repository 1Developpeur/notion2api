from unittest.mock import MagicMock, patch

from app.conversation import build_standard_transcript
from app.notion_client import NOTION_CLIENT_VERSION, NotionOpusAPI


def test_default_client_version_matches_captured_protocol():
    assert NOTION_CLIENT_VERSION == "23.13.20260623.1532"


def test_workflow_request_uses_patch_protocol_v2():
    client = NotionOpusAPI(
        {
            "user_id": "user-1",
            "space_id": "space-1",
            "token_v2": "token",
        }
    )
    response = MagicMock(status_code=200)
    client._scraper = MagicMock()
    client._scraper.post.return_value = response

    profile = {
        "precreate_thread": False,
        "create_thread": False,
        "is_partial_transcript": True,
        "include_debug_overrides": False,
    }
    transcript = [
        {
            "id": "config-1",
            "type": "config",
            "value": {"type": "workflow", "model": "gpt-5.5"},
        }
    ]

    with (
        patch.object(client, "_resolve_request_profile", return_value=profile),
        patch.object(client, "_build_cookie_header", return_value=""),
        patch("app.notion_client.cloudscraper.create_scraper", return_value=client._scraper),
        patch("app.notion_client.parse_stream", return_value=iter([
            {"type": "content", "text": "ok"},
            {"type": "stream_complete"},
        ])),
    ):
        assert list(
            client.stream_response(
                transcript,
                thread_id="thread-1",
                persist_remote_chat=True,
            )
        ) == [{"type": "content", "text": "ok"}]

    request = client._scraper.post.call_args.kwargs
    assert request["headers"]["Accept"] == "application/x-ndjson"
    assert request["json"]["asPatchResponse"] is True
    assert request["json"]["patchResponseVersion"] == 2
    assert request["json"]["createdSource"] == "workflows"


def test_standard_transcript_injects_timezone_and_instruction_page():
    transcript = build_standard_transcript(
        [{"role": "user", "content": "hello"}],
        "gpt-5.5",
        {
            "user_id": "user-1",
            "space_id": "space-1",
            "timezone": "America/Chicago",
            "context_page_id": "37abf4af-15b3-80ba-bd7d-ff1a5bb018ca",
        },
    )

    context = next(item for item in transcript if item["type"] == "context")
    assert context["value"]["timezone"] == "America/Chicago"
    assert (
        context["value"]["context_page_id"]
        == "37abf4af-15b3-80ba-bd7d-ff1a5bb018ca"
    )
