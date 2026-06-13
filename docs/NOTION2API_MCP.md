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

## Security note

Do not publish this server directly to the public internet unless you add proper MCP-side authentication. Prefer Secure MCP Tunnel for private local use.
