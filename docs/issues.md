# Issues & Troubleshooting

Runtime errors are displayed in the Web UI as structured error cards that include an error code, cause, and suggested action.

## 503 — Too Many Requests

This usually means the upstream Notion account is rate-limited.

Recommended actions:

1. Wait briefly and retry.
2. Configure multiple accounts to spread requests.
3. Check whether one account is expired, restricted, or repeatedly failing.
4. Review server logs for `NOTION_429`, `upstream_rate_limit`, or account cooldown messages.

## Authentication failures

If requests return `NOTION_401` or `NOTION_403`, refresh the browser-assisted login session with the local login helper and restart the API service.

## Attachment upload is disabled

Attachments are disabled unless explicitly enabled. Keep local-path access restricted to a safe root, and do not expose local-path attachments on a public host without an API key.
