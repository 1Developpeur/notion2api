# MCP Prompt Registry Process

This runbook documents how to expose reusable prompts in an MCP server so clients show them in prompt UIs through `prompts/list` and retrieve them through `prompts/get`.

## Purpose

Use this process whenever a new MCP server needs reusable prompts such as operator prompts, debugging prompts, output-schema prompts, regression-validation prompts, redaction prompts, and content-sync prompts.

Prompts are not tools. Tools execute actions. Prompts provide reusable instructions that an MCP client can list, display, and inject into a model call.

## Directory layout

Use this structure inside the MCP server repository:

```text
prompts/<server-name>/
  README.md
  index.json
  <prompt-name>.prompt.md
```

Example:

```text
prompts/notion2api-mcp/
  README.md
  index.json
  n2api-mcp-operator.prompt.md
  n2api-provider-debugger.prompt.md
```

## Prompt registry metadata

`index.json` should describe the list UI shape:

```json
{
  "pack": "notion2api-mcp-prompts",
  "version": 1,
  "kind": "mcp-prompt-pack",
  "target": "notion2api-mcp",
  "namespace": "notion2api",
  "prompts": [
    {
      "name": "notion2api_provider_debugger",
      "title": "Debug Notion2API provider failures",
      "description": "Diagnose Notion2API MCP, provider, timeout, streaming, 502, 503, and empty-content failures.",
      "file": "n2api-provider-debugger.prompt.md",
      "id": "n2api.provider_debugger",
      "arguments": [
        {
          "name": "error_log",
          "description": "Redacted error text, status code, or failure report.",
          "required": false
        }
      ]
    }
  ]
}
```

Clients usually display `name`, `title`, and `description`. The MCP server uses `file` to load the body for `prompts/get`.

## FastMCP implementation pattern

For Python FastMCP servers:

1. Load `index.json` from a configurable prompt directory.
2. Load the referenced `.prompt.md` body by safe basename only.
3. Register each prompt with `server.prompt(name=..., title=..., description=...)`.
4. Return a list containing one user message with the prompt body.
5. Append invocation arguments to the prompt body under an `Invocation arguments` section.

Example:

```python
def _prompt_messages(name: str, arguments: dict[str, Any] | None = None) -> list[dict[str, str]]:
    meta = _prompt_metadata(name)
    body = _load_prompt_body(str(meta.get("file") or ""))
    rendered = body + _format_prompt_arguments(arguments or {})
    return [{"role": "user", "content": rendered}]

@server.prompt(
    name="notion2api_provider_debugger",
    title="Debug Notion2API provider failures",
    description="Diagnose Notion2API MCP/provider failures."
)
def notion2api_provider_debugger(error_log: str = "", operation: str = "") -> list[dict[str, str]]:
    return _prompt_messages(
        "notion2api_provider_debugger",
        {"error_log": error_log, "operation": operation},
    )
```

## Validation

Run these checks after adding prompts:

```powershell
python -m json.tool prompts\<server-name>\index.json > $null
python -m py_compile app\mcp_server.py
```

For FastMCP servers, instantiate the server without running the transport and check:

```python
prompts = await server.list_prompts()
assert any(p.name == "your_prompt_name" for p in prompts)
result = await server.get_prompt("your_prompt_name", {"argument": "value"})
assert result.messages
```

## Safety rules

- Never include secrets in prompt files.
- Never place tool implementation logic in prompts.
- Do not expose raw tokens, cookies, signed URLs, API keys, or private request bodies through prompt arguments.
- Use redacted examples only.
- Keep prompt files versionable and reviewable.
- Keep prompt names stable once clients depend on them.

## Future MCP server checklist

When creating any MCP server, add this checklist before considering it complete:

1. `tools/list` exposes executable capabilities.
2. `prompts/list` exposes reusable prompts.
3. `prompts/get` returns rendered prompt bodies with arguments.
4. Prompt registry metadata includes `name`, `title`, `description`, `file`, and `arguments`.
5. Output schemas are defined for tools where supported.
6. Secrets are redacted from logs, examples, and prompt bodies.
7. A validation command confirms prompt list/get behavior.
