# Notion2API MCP Prompt Pack

This directory contains reusable prompt artifacts for the Notion2API MCP server and the Sanity Cloud AI Portal integration.

These are prompts, not tools and not output templates. Each file tells an AI agent how to operate, diagnose, or validate a Notion2API MCP workflow. The `index.json` file gives each prompt a stable ID and intended usage.

## Files

- `n2api-mcp-operator.prompt.md` — default operating prompt for safe Notion2API MCP use.
- `n2api-mcp-tool-router.prompt.md` — routes user intent to read/write/debug/admin MCP actions.
- `n2api-mcp-output-schema-writer.prompt.md` — writes/updates MCP tool output-schema guidance.
- `n2api-provider-debugger.prompt.md` — diagnoses provider/API failures, including 502/503/empty-content issues.
- `n2api-notion-content-sync.prompt.md` — safely creates/updates Notion pages and databases.
- `n2api-regression-validation.prompt.md` — validates fixes with repeatable checks.
- `n2api-security-redaction.prompt.md` — redaction and secret-handling prompt for logs, configs, and reports.

## Usage

Use these prompts as named prompt resources in an MCP server, portal prompt registry, or assistant workflow. Do not merge them into tool definitions. Tools execute actions; these prompts instruct the model how to use those actions safely and consistently.
