import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.server import app
from app.config import API_KEY
from app.schemas import ChatCompletionRequest
from app.notion_client import NotionOpusAPI

class PersistRemoteChatTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.__enter__()
        self.auth_headers = {}
        if API_KEY:
            self.auth_headers = {"Authorization": f"Bearer {API_KEY}"}

    def tearDown(self):
        try:
            self.client.__exit__(None, None, None)
        except Exception:
            pass

    def test_schema_accepts_metadata(self):
        """Verify ChatCompletionRequest parses and validates metadata field."""
        data = {
            "model": "gpt-5.5",
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {
                "persist_remote_chat": True,
                "some_other_flag": "test"
            }
        }
        req = ChatCompletionRequest(**data)
        self.assertIsNotNone(req.metadata)
        self.assertEqual(req.metadata.get("persist_remote_chat"), True)
        self.assertEqual(req.metadata.get("some_other_flag"), "test")

    def test_stream_response_persistence_override_true(self):
        """Verify stream_response overrides settings to persist when persist_remote_chat=True."""
        client_mock = NotionOpusAPI({"user_id": "u1", "space_id": "s1", "token_v2": "t1"})
        
        # Patch dependencies that require network/cookies to avoid network calls
        with patch.object(client_mock, "_to_notion_transcript", return_value=[{"type": "config", "value": {"type": "workflow"}}]), \
             patch.object(client_mock, "_resolve_thread_type", return_value="workflow"), \
             patch.object(client_mock, "_with_thread_type", side_effect=lambda transcript, thread_type: transcript) as mock_with_type, \
             patch.object(client_mock, "_resolve_request_profile", return_value={"precreate_thread": True, "create_thread": True, "is_partial_transcript": False, "include_debug_overrides": False}), \
             patch.object(client_mock, "_build_cookie_header", return_value=""), \
             patch.object(client_mock, "_scraper", MagicMock()) as mock_scraper:
            
            mock_response = MagicMock()
            mock_response.status_code = 200
            def mock_parse_stream(res):
                yield {"type": "content", "text": "hello"}
                yield {"type": "stream_complete"}

            with patch("app.notion_client.parse_stream", side_effect=mock_parse_stream), patch(
                "app.notion_client.cloudscraper.create_scraper",
                return_value=mock_scraper,
            ):
                mock_scraper.post.return_value = mock_response
                
                gen = client_mock.stream_response(
                    transcript=[{"role": "user", "content": "hi"}],
                    thread_id="test-thread-id",
                    persist_remote_chat=True,
                )
                list(gen)
                mock_with_type.assert_not_called()

                with patch.object(client_mock, "delete_thread") as mock_delete:
                    gen = client_mock.stream_response(
                        transcript=[{"role": "user", "content": "hi"}],
                        thread_id="test-thread-id",
                        persist_remote_chat=True,
                    )
                    list(gen)
                    mock_delete.assert_not_called()

    def test_stream_response_computer_use_keeps_workflow_with_attachments(self):
        """Repo AI computer-use reviews keep workflow threads even with ZIP attachments."""
        client_mock = NotionOpusAPI({"user_id": "u1", "space_id": "s1", "token_v2": "t1"})
        transcript = [{"type": "config", "value": {"type": "workflow", "model": "gpt-5.5"}}]

        with patch.object(client_mock, "_to_notion_transcript", return_value=transcript), \
             patch.object(client_mock, "_resolve_thread_type", return_value="workflow"), \
             patch.object(client_mock, "_with_thread_type", side_effect=lambda t, tt: t) as mock_with_type, \
             patch.object(client_mock, "_resolve_request_profile", return_value={"precreate_thread": False, "create_thread": True, "is_partial_transcript": False, "include_debug_overrides": False}), \
             patch.object(client_mock, "_build_cookie_header", return_value=""), \
             patch.object(client_mock, "delete_thread") as mock_delete, \
             patch.object(client_mock, "_scraper", MagicMock()) as mock_scraper, \
             patch("app.notion_client.NotionAttachmentUploader") as uploader_cls:
            from app.attachments.models import UploadedAttachment
            uploaded = UploadedAttachment(
                name="source.zip",
                content_type="application/x-zip-compressed",
                size_bytes=123,
                source="local_path",
                file_id="file-1",
                attachment_url="attachment:file-1:block-1",
            )
            uploader = uploader_cls.return_value
            uploader.upload_attachments.return_value = ([uploaded], "thread-zip")
            mock_response = MagicMock()
            mock_response.status_code = 200
            with patch("app.notion_client.parse_stream", return_value=iter([
                {"type": "content", "text": "ok"},
                {"type": "stream_complete"},
            ])), patch(
                "app.notion_client.cloudscraper.create_scraper",
                return_value=mock_scraper,
            ):
                mock_scraper.post.return_value = mock_response
                list(client_mock.stream_response(
                    transcript,
                    thread_id="thread-zip",
                    attachments=[object()],
                    persist_remote_chat=True,
                    computer_use_review=True,
                ))

        mock_with_type.assert_not_called()
        payload = mock_scraper.post.call_args.kwargs["json"]
        self.assertEqual(payload["threadType"], "workflow")
        self.assertTrue(payload["createThread"])
        self.assertFalse(payload["isPartialTranscript"])
        self.assertEqual(payload["createdSource"], "ai_module")
        config = next(step for step in payload["transcript"] if step.get("type") == "config")
        self.assertTrue(config["value"]["enableComputer"])
        self.assertTrue(config["value"]["enableScriptAgent"])
        file_step = next(step for step in payload["transcript"] if step.get("type") == "computer-file")
        self.assertEqual(file_step["fileName"], "source.zip")
        self.assertEqual(file_step["metadata"]["fileSize"], 123)
        self.assertEqual(file_step["metadata"]["attachmentSource"], "user_upload")
        followup = payload["transcript"][-1]
        self.assertEqual(followup["type"], "user")
        self.assertIn("Do not wait for a manual response", followup["value"][0][0])
        uploader.upload_attachments.assert_called_once()
        self.assertTrue(uploader.upload_attachments.call_args.kwargs["create_thread"])
        mock_delete.assert_not_called()

    def test_stream_response_persistence_override_false(self):
        """Verify stream_response overrides settings to delete when persist_remote_chat=False."""
        client_mock = NotionOpusAPI({"user_id": "u1", "space_id": "s1", "token_v2": "t1"})
        
        # Patch dependencies
        with patch.object(client_mock, "_to_notion_transcript", return_value=[]), \
             patch.object(client_mock, "_resolve_thread_type", return_value="markdown-chat"), \
             patch.object(client_mock, "_resolve_request_profile", return_value={"precreate_thread": True, "create_thread": True, "is_partial_transcript": False, "include_debug_overrides": False}), \
             patch.object(client_mock, "_build_cookie_header", return_value=""), \
             patch.object(client_mock, "delete_thread") as mock_delete, \
             patch.object(client_mock, "_scraper", MagicMock()) as mock_scraper:
            
            mock_response = MagicMock()
            mock_response.status_code = 200
            def mock_parse_stream(res):
                yield {"type": "content", "text": "hello"}
                yield {"type": "stream_complete"}

            with patch("app.notion_client.parse_stream", side_effect=mock_parse_stream), patch(
                "app.notion_client.cloudscraper.create_scraper",
                return_value=mock_scraper,
            ):
                mock_scraper.post.return_value = mock_response
                
                gen = client_mock.stream_response(
                    transcript=[{"role": "user", "content": "hi"}],
                    thread_id="test-thread-id",
                    persist_remote_chat=False
                )
                list(gen)
                # Should delete thread after stream since persist_remote_chat is False
                mock_delete.assert_called_once_with("test-thread-id")

    def test_route_forwards_persist_remote_chat(self):
        """Verify completions route extracts metadata and forwards persist_remote_chat to stream_response."""
        payload = {
            "model": "claude-sonnet4.6",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": False,
            "chat_title": "RepoAI AID - repo - task - abc123",
            "metadata": {
                "persist_remote_chat": True
            }
        }
        
        with patch("app.notion_client.NotionOpusAPI.stream_response") as mock_stream:
            mock_stream.return_value = iter([{"type": "final_content", "text": "ok"}])
            resp = self.client.post("/v1/chat/completions", json=payload, headers=self.auth_headers)
            
            self.assertIn(resp.status_code, (200, 503))
            mock_stream.assert_called()
            # Verify it was called with persist_remote_chat=True
            _, kwargs = mock_stream.call_args
            self.assertEqual(kwargs.get("persist_remote_chat"), True)
            self.assertEqual(kwargs.get("thread_title"), "RepoAI AID - repo - task - abc123")


if __name__ == '__main__':
    unittest.main()

