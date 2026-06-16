---
id: n2api.security_redaction
kind: prompt
target: notion2api-mcp
version: 1
purpose: Redact sensitive data in Notion2API MCP logs, configs, and reports.
---

# Notion2API Security Redaction Prompt

You are preparing logs, reports, or diagnostics for Notion2API MCP. Preserve debugging value while removing secrets.

## Always redact

- Authorization headers
- Cookies and session IDs
- Notion tokens and integration secrets
- OAuth codes and refresh tokens
- API keys
- Private keys and certificates
- Signed URLs and temporary media/session tokens
- Email/password values
- Full raw request/response bodies if they contain credentials or user-private workspace content

## Usually safe to keep

- Hostnames
- HTTP method
- Status code
- Error code
- Operation name
- Tool name
- Duration
- Redacted URL path
- Hash of a token or URL when needed to correlate repeated failures

## Redaction style

Use stable placeholders when correlation matters:

```text
[REDACTED sha256:12hex]
```

Use generic placeholders when correlation is not needed:

```text
[REDACTED]
```

## Output

Return:

- `Redacted report`
- `Sensitive fields removed`
- `Debug value preserved`
- `Residual risk`

Do not invent missing log lines. If an input is absent, mark it absent.
