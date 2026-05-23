import base64
import unittest
from unittest.mock import Mock

from app.attachments.models import InputAttachment
from app.attachments.notion_upload import NotionAttachmentUploader


class FakeNotionClient:
    def __init__(self):
        self.descriptors = []

    def request_upload_descriptor(self, name, content_type, size, thread_id, create_thread):
        desc = {"upload_url": f"https://upload.test/{name}", "fields": {"k": "v"}, "file_id": f"file-{name}", "attachment_url": f"https://files.test/{name}", "metadata": {"name": name}}
        self.descriptors.append((name, content_type, size, thread_id, create_thread))
        return desc

    def perform_multipart_upload(self, descriptor, name, data, content_type):
        # record that upload was called; in real code this would POST to descriptor['upload_url']
        self.last_upload = {"descriptor": descriptor, "name": name, "size": len(data), "content_type": content_type}

    def enqueue_attachment_processing(self, file_id, thread_id):
        return f"task-{file_id}"

    def get_task_status(self, task_id):
        # immediate success for tests
        return {"status": "completed", "success": True}

    def get_signed_read_url(self, file_id):
        return f"https://signed.test/{file_id}"


class NotionAttachmentUploadTests(unittest.TestCase):
    def test_upload_attachments_success(self):
        client = FakeNotionClient()
        uploader = NotionAttachmentUploader(notion_client=client, poll_interval=0.001)

        # inline base64 attachment (use allowed MIME type: text/csv)
        data_b64 = base64.b64encode(b"hello,world\n").decode()
        att = InputAttachment(name="greet.csv", content_type="text/csv", source="inline_data", data=data_b64)

        uploaded, thread = uploader.upload_attachments(thread_id="thread-1", attachments=[att], create_thread=False)

        self.assertEqual(thread, "thread-1")
        self.assertEqual(len(uploaded), 1)
        u = uploaded[0]
        self.assertTrue(u.file_id.startswith("file-"))
        self.assertTrue(u.signed_get_url.startswith("https://signed.test/"))
        # descriptor was requested with expected params
        self.assertEqual(client.descriptors[0][0], "greet.csv")
        self.assertEqual(client.last_upload["size"], len(b"hello,world\n"))

    def test_task_failure_raises(self):
        client = FakeNotionClient()
        # override get_task_status to fail
        def failing_status(task_id):
            return {"status": "failed", "success": False}

        client.get_task_status = failing_status
        uploader = NotionAttachmentUploader(notion_client=client, poll_interval=0.001)

        data_b64 = base64.b64encode(b"%PDF-1.4\n%fakepdf\n").decode()
        att = InputAttachment(name="bad.pdf", content_type="application/pdf", source="inline_data", data=data_b64)

        with self.assertRaises(RuntimeError):
            uploader.upload_attachments(thread_id="t", attachments=[att], create_thread=False)


if __name__ == "__main__":
    unittest.main()
