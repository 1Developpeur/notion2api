---
id: n2api.mcp.output_schema_writer
kind: prompt
target: notion2api-mcp
version: 1
purpose: Generate or repair MCP tool output schemas for Notion2API operations.
---

# Notion2API MCP Output Schema Writer Prompt

You are writing MCP output schemas for Notion2API tools. The goal is to make each tool's result predictable for ChatGPT, OpenCode, Sanity Cloud AI Portal, and other MCP clients.

## Rules

1. Output schemas describe returned data only. Do not place API keys, authentication logic, or runtime configuration in an output schema.
2. Use stable top-level fields: `ok`, `operation`, `result`, `error`, `diagnostics`, and `metadata` when applicable.
3. For successful operations, include enough identifiers to let a client link follow-up actions without exposing secrets.
4. For failed operations, include a structured `error` object with `code`, `message`, `type`, `retryable`, and `suggestion`.
5. For Notion objects, preserve common fields: `id`, `object`, `url`, `created_time`, `last_edited_time`, `parent`, `properties`, and `archived` when available.
6. Avoid `additionalProperties: true` unless the Notion API object is intentionally pass-through.
7. Use arrays for collection results and include pagination fields when relevant.

## Preferred result shape

```json
{
  "ok": true,
  "operation": "notion.operation_name",
  "result": {},
  "diagnostics": [],
  "metadata": {
    "request_id": null,
    "duration_ms": null,
    "source": "notion2api"
  }
}
```

## Failure shape

```json
{
  "ok": false,
  "operation": "notion.operation_name",
  "result": null,
  "error": {
    "code": "NOTION_EMPTY",
    "type": "upstream_empty_response",
    "message": "Notion returned empty content.",
    "retryable": true,
    "suggestion": "Retry the request or reduce payload size."
  },
  "diagnostics": []
}
```

## Output

Return a JSON Schema plus a short explanation of changed fields and client compatibility notes.
