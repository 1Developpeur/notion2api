# Attachment Upload Implementation Plan

## Purpose

Add real file-upload and multimodal attachment support to the Python `notion2api` service by adapting the proven attachment-staging pattern from `GALIAIS/Notion2API` into this repository's FastAPI architecture.

This is an implementation plan only. It does not change runtime behavior.

## Current repo baseline

The current Python fork already has partial OpenAI-compatible attachment surface area:

- `app/schemas.py`
  - `ChatCompletionRequest.attachments` exists.
  - Top-level `attachments` are normalized into OpenAI-style content parts and merged into the last user message.
  - `ChatMessage.content` is typed as `Any`, so structured content arrays are already accepted at the schema layer.
- `app/api/chat.py`
  - Chat request handling still prepares prompts as text.
  - Lite, Standard, and Heavy modes pass text transcript payloads into `NotionOpusAPI.stream_response(...)`.
- `app/api/responses.py`
  - Responses API currently converts input to text and discards non-text attachment parts.
  - Top-level `attachments` are not forwarded into the chat shim.
- `app/notion_client.py`
  - `NotionOpusAPI.stream_response(...)` sends transcript JSON to `https://www.notion.so/api/v3/runInferenceTranscript`.
  - It can create/delete Notion AI threads, but it does not stage files, enqueue attachment processing, or insert attachment transcript steps.

## Target behavior

Support attachments in both APIs:

- `POST /v1/chat/completions`
- `POST /v1/responses`

Accepted input forms:

```json
{
  "model": "claude-sonnet4.6",
  "messages": [
    {
      "role": "user",
      "content": [
        { "type": "text", "text": "Summarize this PDF." },
        {
          "type": "input_file",
          "filename": "order.pdf",
          "mime_type": "application/pdf",
          "file_data": "data:application/pdf;base64,..."
        }
      ]
    }
  ]
}
```

```json
{
  "model": "claude-sonnet4.6",
  "messages": [{ "role": "user", "content": "Analyze this file." }],
  "attachments": [
    {
      "name": "records.csv",
      "content_type": "text/csv",
      "url": "https://example.test/records.csv"
    }
  ]
}
```

Supported source types:

- `inline_data`: base64 or `data:` URL payloads.
- `remote_url`: HTTPS/HTTP URLs, subject to SSRF protection.
- `local_path`: disabled by default; optional for trusted local deployments only.

Supported MIME types:

- `application/pdf`
- `text/csv`
- `image/png`
- `image/jpeg`
- `image/gif`
- `image/webp`
- `image/heic`

## Non-goals for first implementation

Do not build a full OpenAI `/v1/files` object store in the first pass.

Do not persist attachment bytes in SQLite.

Do not allow unrestricted local file paths or unrestricted remote URL fetching.

Do not add arbitrary binary upload support beyond the Notion-supported file types listed above.

## Architecture

Create a dedicated attachment package so upload logic does not sprawl across chat handlers.

Proposed files:

```text
app/attachments/__init__.py
app/attachments/models.py
app/attachments/normalizer.py
app/attachments/security.py
app/attachments/loader.py
app/attachments/notion_upload.py
app/attachments/errors.py
tests/test_attachment_normalizer.py
tests/test_attachment_security.py
tests/test_attachment_loader.py
tests/test_notion_attachment_upload.py
```

### `app/attachments/models.py`

Define normalized attachment models.

```python
from dataclasses import dataclass, field
from typing import Any, Literal

AttachmentSource = Literal["inline_data", "remote_url", "local_path"]

@dataclass(slots=True)
class InputAttachment:
    name: str = ""
    content_type: str = ""
    source: AttachmentSource | str = ""
    url: str = ""
    path: str = ""
    data: bytes = b""

@dataclass(slots=True)
class UploadedAttachment:
    name: str
    content_type: str
    size_bytes: int
    source: str
    file_id: str = ""
    thread_mounted: bool = False
    attachment_url: str = ""
    signed_get_url: str = ""
    task_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
```

### `app/attachments/normalizer.py`

Responsibilities:

- Parse OpenAI-style chat content arrays.
- Parse Responses API `input` arrays.
- Parse top-level `attachments`.
- Separate visible text from attachment descriptors.
- Preserve unknown content parts where safe, but do not silently treat unsupported binary objects as text.

Recognized attachment descriptors:

- `type: image_url`
- `type: input_image`
- `type: file`
- `type: input_file`
- `type: attachment`
- objects with hints such as `url`, `file_url`, `file_data`, `data`, `path`, or `image_url`

Required functions:

```python
def normalize_chat_messages(messages: list[dict], top_level_attachments: list | None) -> tuple[list[dict], list[InputAttachment]]:
    """Return text-preserving messages plus normalized attachments."""


def normalize_responses_input(input_value: Any, top_level_attachments: list | None) -> tuple[list[dict], list[InputAttachment]]:
    """Return chat-compatible messages plus normalized attachments."""
```

Implementation notes:

- Continue allowing plain text messages.
- If the final user message contains only attachments and no text, synthesize: `Analyze the uploaded attachment.`
- Do not stringify attachment descriptors into user prompt text.
- Strip attachment objects from prompt-only transcript messages after they are extracted, unless keeping them is needed for compatibility metadata.

### `app/attachments/security.py`

Responsibilities:

- Enforce MIME allowlist.
- Enforce byte limits.
- Enforce attachment count limits.
- Block SSRF for remote URLs.
- Gate local file path ingestion behind an explicit local-only environment flag.

Environment variables:

```text
ENABLE_ATTACHMENTS=true
MAX_ATTACHMENTS_PER_REQUEST=5
MAX_ATTACHMENT_BYTES=20971520
ALLOW_REMOTE_ATTACHMENT_URLS=true
ALLOW_LOCAL_ATTACHMENT_PATHS=false
ATTACHMENT_DOWNLOAD_TIMEOUT_SECONDS=20
ATTACHMENT_ALLOWED_MIME_TYPES=application/pdf,text/csv,image/png,image/jpeg,image/gif,image/webp,image/heic
```

Remote URL rules:

- Allow only `http` and `https` schemes.
- Resolve DNS before download.
- Reject loopback, private, link-local, multicast, reserved, and unspecified addresses.
- Re-check every redirect target.
- Cap redirects.
- Reject URLs with embedded credentials.
- Reject non-default ports unless explicitly enabled.
- Stream download with a hard byte cap.

Local path rules:

- Disabled by default.
- If enabled, resolve with `Path(...).resolve()`.
- Optionally require all local paths to stay under `ATTACHMENT_LOCAL_ROOT`.
- Never expose local-path support in hosted/public deployment mode.

### `app/attachments/loader.py`

Responsibilities:

- Convert an `InputAttachment` into bytes, final filename, and final MIME type.
- Infer MIME from explicit content type, response header, filename extension, or light sniffing.
- Use streaming downloads for remote URLs.
- Reject payloads over the configured size limit.

Required function:

```python
def load_attachment_data(client, attachment: InputAttachment) -> tuple[bytes, str, str]:
    """Return data, filename, content_type."""
```

Implementation notes:

- Reuse `requests` or the existing `cloudscraper` client where appropriate, but remote user URL downloads should not inherit Notion cookies.
- Do not use Notion-authenticated headers for arbitrary remote attachment URLs.
- For inline data, support both `data:mime/type;base64,...` and raw base64.

### `app/attachments/notion_upload.py`

Responsibilities:

- Stage attachment bytes into Notion's assistant-chat upload mechanism.
- Return `UploadedAttachment` objects that can be injected into the Notion transcript and run-inference payload.

Required Notion operations:

1. `getUploadFileUrlForAssistantChatTranscriptUpload`
2. multipart POST to `signedUploadPostUrl`
3. wait for thread mount
4. `enqueueTask` with `eventName: processAgentAttachment`
5. poll `getTasks`
6. optionally call `getSignedFileUrls`

Required methods:

```python
class NotionAttachmentUploader:
    def __init__(self, notion_client: "NotionOpusAPI") -> None: ...

    def upload_attachments(
        self,
        *,
        thread_id: str,
        attachments: list[InputAttachment],
        create_thread: bool,
    ) -> tuple[list[UploadedAttachment], str]: ...

    def get_upload_descriptor(...): ...
    def do_multipart_upload(...): ...
    def enqueue_attachment_processing(...): ...
    def wait_attachment_task(...): ...
    def wait_thread_attachment_mounted(...): ...
    def get_signed_attachment_url(...): ...
```

Descriptor request shape:

```json
{
  "name": "file.pdf",
  "contentType": "application/pdf",
  "assistantChatTranscriptSessionPointer": {
    "spaceId": "<space_id>",
    "table": "thread",
    "id": "<thread_id>"
  },
  "contentLength": 12345,
  "createThread": true
}
```

Attachment-processing task shape:

```json
{
  "task": {
    "eventName": "processAgentAttachment",
    "request": {
      "url": "attachment:<file_id>:<name>",
      "spaceId": "<space_id>",
      "aiSessionPointer": {
        "spaceId": "<space_id>",
        "table": "thread",
        "id": "<thread_id>"
      },
      "source": "user_upload",
      "clientVersion": "<notion-client-version>"
    },
    "cellRouting": {
      "spaceIds": ["<space_id>"]
    }
  }
}
```

## Integration points

### 1. `app/schemas.py`

Keep the existing permissive schema, but stop relying on `ChatCompletionRequest.__init__` as the only attachment-merging layer.

Recommended changes:

- Keep `attachments` field.
- Keep structured `content: Any`.
- Move attachment extraction into `app/attachments/normalizer.py` so behavior is shared by chat and responses.
- Avoid mutating message content in `__init__` after the normalizer exists, or leave it temporarily for backward compatibility and make normalizer idempotent.

### 2. `app/api/chat.py`

Modify Lite, Standard, and Heavy paths to extract attachments before building transcript text.

Required changes:

- Call `normalize_chat_messages(...)` near the start of `create_chat_completion`.
- Pass normalized messages into `_prepare_messages`, `_prepare_messages_lite`, and `build_standard_transcript`.
- Carry `attachments` into the mode-specific handlers.
- Pass attachments into `client.stream_response(...)`.

Proposed signature changes:

```python
async def _handle_lite_request(request, req_body, attachments): ...
async def _handle_standard_request(request, req_body, attachments): ...
```

Then:

```python
stream_gen = client.stream_response(
    transcript,
    thread_id=thread_id,
    attachments=attachments,
)
```

### 3. `app/api/responses.py`

Responses API must stop flattening all input to text before attachments are seen.

Required changes:

- Preserve `input_file`, `input_image`, `file`, `image_url`, and `attachment` content parts.
- Forward top-level `attachments` into `ChatCompletionRequest`.
- Use shared normalizer logic rather than `_content_to_text` for all content.

Proposed change:

```python
chat_req = ChatCompletionRequest(
    model=model,
    messages=messages,
    stream=stream,
    temperature=payload.get("temperature"),
    conversation_id=payload.get("conversation_id"),
    attachments=payload.get("attachments"),
)
```

If Responses input itself contains attachment parts, keep those parts inside the generated `ChatMessage.content` list.

### 4. `app/notion_client.py`

Modify `NotionOpusAPI.stream_response` to accept attachments and stage them before `runInferenceTranscript`.

Proposed signature:

```python
def stream_response(
    self,
    transcript: list,
    thread_id: Optional[str] = None,
    attachments: Optional[list[InputAttachment]] = None,
) -> Generator[dict[str, Any], None, None]:
```

Required flow:

1. Resolve `thread_id` and `should_create_thread` as today.
2. If attachments exist, call `NotionAttachmentUploader.upload_attachments(...)` before calling `runInferenceTranscript`.
3. If the upload descriptor returns a `chatId`, update `thread_id` and `self.current_thread_id`.
4. Insert attachment transcript steps before the final user step.
5. Add top-level `attachments` payload entries.
6. If an attachment-created thread is already mounted, set `createThread` correctly so `runInferenceTranscript` does not create a duplicate thread.

Transcript attachment step shape:

```python
{
    "id": str(uuid.uuid4()),
    "type": "attachment",
    "fileName": uploaded.name,
    "contentType": uploaded.content_type,
    "fileUrl": uploaded.attachment_url,
    "metadata": build_attachment_step_metadata(uploaded),
}
```

Payload attachment shape:

```python
{
    "type": "attachment",
    "fileName": uploaded.name,
    "contentType": uploaded.content_type,
    "fileUrl": uploaded.attachment_url,
}
```

### 5. `app/conversation.py`

Audit transcript builders:

- `build_lite_transcript`
- `build_standard_transcript`
- Heavy-mode transcript construction via `ConversationManager.get_transcript_payload(...)`

They do not need to stage files directly. They only need to receive text-cleaned messages so attachment descriptors are not serialized into the user prompt.

If attachment-only requests exist, the final user prompt should be `Analyze the uploaded attachment.`

### 6. Frontend UI

Add browser file uploads after backend JSON attachment support is complete.

Minimal implementation:

- Add file picker to `frontend/index.html`.
- Read files with `FileReader.readAsDataURL`.
- Add top-level `attachments` to the outgoing chat payload.
- Show selected file chips with name, MIME type, and size.
- Enforce the same count/size allowlist client-side, but do not rely on client-side validation for security.

Better later implementation:

- Add `POST /v1/attachments/stage` for local server staging.
- Return short-lived local attachment IDs.
- Let chat requests reference staged IDs.

Do not implement `/v1/attachments/stage` in phase one unless inline JSON bodies become too large for real usage.

## Rollout phases

### Phase 0 — Documentation and feature flag

- Add this plan.
- Add env vars to `.env.example` and README.
- Default `ENABLE_ATTACHMENTS=false` until backend tests pass.

Acceptance:

- No runtime behavior change.
- Configuration docs are present.

### Phase 1 — Normalizer and tests

- Add attachment dataclasses.
- Add normalizer for chat and responses inputs.
- Add unit tests for all supported input shapes.

Acceptance:

- Top-level `attachments` normalize consistently.
- `messages[].content[]` image/file parts normalize consistently.
- Attachment-only final user message gets fallback prompt.
- Unknown non-text parts are ignored or rejected deterministically.

### Phase 2 — Loader and security policy

- Add MIME allowlist.
- Add size/count enforcement.
- Add inline base64/data URL decoding.
- Add SSRF-protected remote URL loader.
- Add disabled-by-default local path loader.

Acceptance:

- Private IP, loopback, link-local, metadata, and localhost URLs are blocked.
- Oversized data fails before Notion upload.
- Unsupported MIME type returns OpenAI-compatible 400 error.
- Local paths fail unless explicitly enabled.

### Phase 3 — Notion upload client

- Add `NotionAttachmentUploader`.
- Add upload descriptor request.
- Add multipart upload.
- Add mount polling.
- Add processing task enqueue and polling.
- Add signed URL lookup.
- Add upload metadata logs.

Acceptance:

- Unit tests mock all Notion endpoints.
- Failed upload returns structured upstream error.
- Uploaded attachment includes file ID, attachment URL, task ID, and processing metadata.

### Phase 4 — Chat API integration

- Pass attachments through Lite mode.
- Pass attachments through Standard mode.
- Pass attachments through Heavy mode.
- Ensure conversation/thread ID persistence still works.
- Ensure Notion thread cleanup behavior still honors `NOTION_PERSIST_THREADS` and `NOTION_DELETE_EPHEMERAL_THREADS`.

Acceptance:

- `/v1/chat/completions` works with PDF, CSV, and image attachments.
- Streaming and non-streaming paths both work.
- Attachment-only prompt works.
- Failed attachment validation does not mark account pool client as failed unless the error is truly upstream/account-related.

### Phase 5 — Responses API integration

- Preserve attachment content parts from Responses API input.
- Forward top-level Responses `attachments`.
- Verify `previous_response_id` behavior does not duplicate attachments.

Acceptance:

- `/v1/responses` works with `input_file`, `input_image`, and top-level `attachments`.
- Text-only Responses behavior remains unchanged.

### Phase 6 — Frontend file picker

- Add file picker.
- Encode files as data URLs for initial local-only implementation.
- Add selected-file UI.
- Disable unsupported files before submit.

Acceptance:

- User can attach PDF/CSV/image files from the browser UI.
- Backend still performs authoritative validation.

### Phase 7 — Docs and examples

- Update README API examples.
- Add curl examples for PDF, CSV, image URL, and data URL.
- Document security defaults.
- Document local-path uploads as local-only and disabled by default.

Acceptance:

- A new user can test an attachment request with curl.
- Deployment operators can understand why remote URLs and local paths are restricted.

## Error handling

Return OpenAI-compatible errors.

Examples:

```json
{
  "error": {
    "message": "Unsupported attachment content type: application/x-msdownload",
    "type": "invalid_request_error",
    "param": "attachments",
    "code": "unsupported_attachment_type"
  }
}
```

```json
{
  "error": {
    "message": "Remote attachment URL resolves to a private or loopback address.",
    "type": "invalid_request_error",
    "param": "attachments.url",
    "code": "attachment_url_blocked"
  }
}
```

Use 400 for caller-side validation failures.

Use 502/503 for Notion upstream staging failures.

Use 413 for request or attachment size violations.

## Account pool interaction

Attachment validation errors should not cool down an account.

Only mark an account failed when:

- Notion returns a retriable upload-processing failure.
- Notion returns a retriable run-inference failure.
- The authenticated Notion session fails during upload or inference.

Do not mark accounts failed for:

- unsupported MIME type
- blocked URL
- local path disabled
- attachment too large
- invalid base64

## Logging

Add structured events:

```text
attachment_normalized
attachment_rejected
attachment_download_started
attachment_download_completed
attachment_upload_descriptor_received
attachment_multipart_uploaded
attachment_thread_mounted
attachment_processing_enqueued
attachment_processing_completed
attachment_processing_failed
```

Log fields:

- account key, not token
- thread ID
- trace ID where available
- attachment name
- content type
- size bytes
- source type
- task ID
- file ID

Never log raw file bytes, base64 payloads, signed upload URLs, signed GET URLs, token cookies, or full Authorization headers.

## Test matrix

### Normalizer

- plain text only
- top-level attachment only
- text plus top-level PDF
- content array with `text` + `input_file`
- content array with `input_text` + `input_image`
- generic `attachment` with URL
- attachment-only request fallback prompt
- unsupported unknown object

### Loader/security

- valid data URL PDF
- valid raw base64 CSV
- invalid base64
- oversized inline data
- remote HTTPS image
- remote URL with private IP
- remote URL redirecting to private IP
- localhost URL blocked
- local path disabled
- local path enabled under allowed root
- MIME mismatch handling

### Notion uploader

- descriptor returns `chatId`
- multipart upload success
- multipart upload failure
- mount polling success
- mount polling timeout
- enqueue task success
- task error
- task timeout
- signed URL lookup success/failure

### API integration

- chat completions non-stream PDF
- chat completions stream PDF
- chat completions image URL
- chat completions CSV data URL
- responses non-stream PDF
- responses stream image
- Heavy mode conversation continuation after attachment
- Standard/Lite ephemeral-thread cleanup after attachment

## Migration strategy

1. Land backend feature behind `ENABLE_ATTACHMENTS=false`.
2. Enable in local development only.
3. Run smoke tests against a disposable Notion workspace.
4. Enable for standard mode.
5. Enable for heavy mode after conversation/thread persistence is verified.
6. Add frontend UI after backend behavior is stable.

## Suggested implementation order

1. `models.py`
2. `normalizer.py`
3. `security.py`
4. `loader.py`
5. unit tests for 1-4
6. `notion_upload.py`
7. mocked Notion uploader tests
8. `notion_client.py` integration
9. chat route integration
10. responses route integration
11. README and `.env.example`
12. frontend file picker

## Open questions

- Should local-path ingestion be completely removed rather than feature-flagged?
- Should remote URL downloads use `requests` only, or share `cloudscraper` for sites that block normal clients?
- Should the first frontend upload path use base64 data URLs or a staged local upload endpoint?
- Should Heavy mode persist attachment metadata in SQLite conversation history?
- Should attachment requests force `workflow` thread type, or preserve the current `thread_type` resolution?

## Definition of done

The feature is complete when:

- PDF, CSV, and image attachments work through `/v1/chat/completions`.
- PDF, CSV, and image attachments work through `/v1/responses`.
- Streaming and non-streaming modes both work.
- Lite, Standard, and Heavy modes remain compatible.
- Attachment validation failures are safe and do not cool down accounts.
- Remote URL ingestion is SSRF-hardened.
- Local path ingestion is disabled by default.
- Tests cover normalizer, loader, security, Notion uploader, and route integration.
- README documents examples and security defaults.
