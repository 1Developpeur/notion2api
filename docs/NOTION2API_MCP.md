# Notion2API MCP server

This repo includes a thin MCP wrapper around the existing Notion2API HTTP API. The wrapper does not replace the OpenAI-compatible `/v1` API; it runs as a separate MCP server and forwards tool calls to a local Notion2API backend.

## Local run

Start Notion2API first, then run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-notion2api-mcp.ps1 -BaseUrl http://127.0.0.1:8120
```

Default MCP endpoint:

```text
http://127.0.0.1:8130/mcp
```

For the repo's default Notion2API port, use:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-notion2api-mcp.ps1 -BaseUrl http://127.0.0.1:8000
```

## ChatGPT connection

ChatGPT custom connectors expect an MCP endpoint. For local development, expose the local endpoint through OpenAI Secure MCP Tunnel or another HTTPS tunnel, then create a ChatGPT connector pointing at the tunnel-backed `/mcp` endpoint.

## Environment variables

| Variable | Purpose | Default |
| --- | --- | --- |
| `MCP_NOTION2API_BASE_URL` | Backend Notion2API base URL | `http://127.0.0.1:8000` |
| `MCP_NOTION2API_API_KEY` | Bearer token sent to Notion2API | falls back to `NOTION2API_API_KEY` or `API_KEY` |
| `MCP_NOTION2API_TIMEOUT` | Backend request timeout in seconds | `180` |
| `MCP_HOST` | MCP listen host | `127.0.0.1` |
| `MCP_PORT` | MCP listen port | `8130` |
| `MCP_PATH` | Streamable HTTP MCP path | `/mcp` |
| `MCP_TRANSPORT` | `streamable-http`, `stdio`, or `sse` | `streamable-http` |

## Tools

- `notion2api_health`
- `notion2api_list_models`
- `notion2api_chat`
- `notion2api_chat_completion`
- `notion2api_responses`

## File attachments and ZIP uploads

The chat tools support file attachments through their `attachments` argument:

- `notion2api_chat(..., attachments=[...])`
- `notion2api_chat_completion(..., attachments=[...])`
- `notion2api_responses(..., attachments=[...])`

Each attachment is converted into the OpenAI-compatible Notion2API HTTP shape and forwarded to `/v1/chat/completions` or `/v1/responses`:

```json
[
  {
    "name": "source.zip",
    "content_type": "application/x-zip-compressed",
    "path": "X:\\Code\\.ai-runs\\<run-id>\\source.zip"
  }
]
```

For local-path attachments, the backend must be started with attachment support enabled and a restricted local root:

```powershell
$env:ENABLE_ATTACHMENTS = 'true'
$env:ALLOW_LOCAL_ATTACHMENT_PATHS = 'true'
$env:ATTACHMENT_LOCAL_ROOT = 'X:\Code\.ai-runs'
$env:ATTACHMENT_ALLOWED_MIME_TYPES = 'application/pdf,application/zip,application/x-zip-compressed,text/csv,image/png,image/jpeg,image/gif,image/webp,image/heic'
```

ZIP files require a Notion-specific upload descriptor override. Even if a caller supplies `application/zip`, Notion2API normalizes ZIP descriptors to `application/x-zip-compressed` and includes `allowUnsupportedTypes: true` when calling `getUploadFileUrlForAssistantChatTranscriptUpload`. Without both fields, Notion rejects the descriptor with `ValidationError: File type not allowed`.

MCP proof flow:

1. Call `notion2api_chat` or `notion2api_chat_completion` with `persist_remote_chat=true`.
2. Pass the ZIP under `attachments`.
3. Notion2API stages the bytes with the assistant-chat upload endpoint.
4. The chat request is sent to `runInferenceTranscript` and the remote thread is preserved.
5. Verify via Notion chat history sync or the visible Notion AI sidebar.

Important limitation: this proves that Notion accepts and persists the ZIP attachment workflow. Current Notion AI models may still answer that they cannot inspect ZIP contents. Treat ZIP upload success and model-level ZIP comprehension as separate behaviors.

## Security note

Do not publish this server directly to the public internet unless you add proper MCP-side authentication. Prefer Secure MCP Tunnel for private local use.
