"""Notion-side attachment staging client (mockable, minimal staging flow).

This module implements a layered uploader that talks to a Notion-style
upstream via a pluggable client. Network interactions are delegated to the
provided `notion_client` where possible so tests can mock the client easily.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.attachments.loader import load_attachment_data
from app.attachments.models import InputAttachment, LoadedAttachment, UploadedAttachment


class NotionAttachmentUploader:
    def __init__(self, notion_client: Any, poll_interval: float = 0.1, poll_timeout: float = 30.0) -> None:
        self.notion = notion_client
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout

    def upload_attachments(
        self,
        *,
        thread_id: str,
        attachments: List[InputAttachment],
        create_thread: bool = False,
    ) -> Tuple[List[UploadedAttachment], str]:
        uploaded: List[UploadedAttachment] = []
        # For each normalized attachment, load bytes and stage
        for att in attachments:
            loaded = load_attachment_data(att)
            descriptor = self.get_upload_descriptor(thread_id=thread_id, attachment=att, loaded=loaded, create_thread=create_thread)
            self.do_multipart_upload(descriptor, loaded)
            file_id = self.extract_attachment_file_id(descriptor) or descriptor.get("file_id") or str(uuid.uuid4())
            task_id = self.enqueue_attachment_processing(file_id=file_id, thread_id=thread_id)
            result = self.wait_attachment_task(task_id)
            if not result.get("success"):
                raise RuntimeError(f"Attachment processing failed for task {task_id}")
            signed_url = self.get_signed_attachment_url(file_id)
            uploaded.append(
                UploadedAttachment(
                    name=loaded.name,
                    content_type=loaded.content_type,
                    size_bytes=loaded.size_bytes,
                    source=loaded.source,
                    file_id=file_id,
                    thread_mounted=True,
                    attachment_url=descriptor.get("attachment_url", ""),
                    signed_get_url=signed_url or "",
                    task_id=task_id,
                    metadata=descriptor.get("metadata", {}),
                )
            )

        return uploaded, thread_id

    # The following methods delegate to the notion client when available so tests can mock them.
    def get_upload_descriptor(self, *, thread_id: str, attachment: InputAttachment, loaded: LoadedAttachment, create_thread: bool) -> Dict[str, Any]:
        if hasattr(self.notion, "request_upload_descriptor"):
            return self.notion.request_upload_descriptor(
                name=loaded.name,
                content_type=loaded.content_type,
                size=loaded.size_bytes,
                thread_id=thread_id,
                create_thread=create_thread,
            )
        # Fallback / test-friendly descriptor
        return {
            "upload_url": "",
            "fields": {},
            "file_id": str(uuid.uuid4()),
            "attachment_url": "",
        }

    def do_multipart_upload(self, descriptor: Dict[str, Any], loaded: LoadedAttachment) -> None:
        # Prefer notion client helper
        if hasattr(self.notion, "perform_multipart_upload"):
            return self.notion.perform_multipart_upload(descriptor=descriptor, name=loaded.name, data=loaded.data, content_type=loaded.content_type)

        # Otherwise try to use requests directly if descriptor contains upload_url
        upload_url = descriptor.get("upload_url")
        fields = descriptor.get("fields") or {}
        if not upload_url:
            # Nothing to do for mock descriptor
            return
        import requests

        files = {"file": (loaded.name, loaded.data, loaded.content_type)}
        resp = requests.post(upload_url, data=fields, files=files, timeout=60)
        if resp.status_code < 200 or resp.status_code >= 300:
            raise RuntimeError(f"Multipart upload failed with HTTP {resp.status_code}")

    def extract_attachment_file_id(self, descriptor: Dict[str, Any]) -> Optional[str]:
        return descriptor.get("file_id") or (descriptor.get("file") or {}).get("id")

    def enqueue_attachment_processing(self, *, file_id: str, thread_id: str) -> str:
        if hasattr(self.notion, "enqueue_attachment_processing"):
            return self.notion.enqueue_attachment_processing(file_id=file_id, thread_id=thread_id)
        # fallback: synchronous no-op
        return str(uuid.uuid4())

    def wait_attachment_task(self, task_id: str) -> Dict[str, Any]:
        # Poll notion client for task status
        start = time.time()
        while True:
            if hasattr(self.notion, "get_task_status"):
                status = self.notion.get_task_status(task_id)
            else:
                status = {"status": "completed", "success": True}
            if isinstance(status, dict) and status.get("status") in {"completed", "failed"}:
                return {"success": bool(status.get("success", status.get("status") == "completed")), "status": status.get("status")}
            if time.time() - start > self.poll_timeout:
                raise TimeoutError("Attachment task polling timed out")
            time.sleep(self.poll_interval)

    def get_signed_attachment_url(self, file_id: str) -> str:
        if hasattr(self.notion, "get_signed_read_url"):
            return self.notion.get_signed_read_url(file_id)
        return ""
