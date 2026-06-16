---
id: n2api.mcp.tool_router
kind: prompt
target: notion2api-mcp
version: 1
purpose: Route user intent to the correct Notion2API MCP action family.
---

# Notion2API MCP Tool Router Prompt

Classify the user's request before selecting tools. Do not call write tools when a read-only answer is sufficient.

## Intent classes

- `read`: retrieve pages, blocks, databases, comments, users, or search results.
- `write`: create pages, append blocks, create databases, upload files, or add comments.
- `update`: modify page properties, block text, database schema, or record values.
- `debug`: inspect Notion2API health, errors, provider responses, retries, or logs.
- `schema`: produce MCP tool output schemas, operation schemas, or API payload examples.
- `admin`: configure allowed operations, blocked operations, parents, model routing, or portal registration.
- `export`: convert Notion content to Markdown, JSON, report, spreadsheet, or other artifact.

## Routing rules

1. If the request includes words like `create`, `save`, `store`, `append`, or `add to Notion`, classify as `write` unless the user is only asking for a draft.
2. If the request asks `what does this say`, `find`, `summarize`, or `look up`, classify as `read`.
3. If the request mentions errors, 502, 503, timeout, empty content, provider failure, model response loss, or OAuth callback, classify as `debug`.
4. If the request says `output schema`, `tool schema`, `JSON schema`, or `MCP schema`, classify as `schema`.
5. If the request changes server behavior, environment, routing, or portal inclusion, classify as `admin`.

## Output

Return the chosen intent, the minimum safe action set, required inputs, and blocked/destructive actions that need explicit confirmation.
