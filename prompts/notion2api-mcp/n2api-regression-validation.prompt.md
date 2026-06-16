---
id: n2api.regression_validation
kind: prompt
target: notion2api-mcp
version: 1
purpose: Validate Notion2API MCP changes with repeatable checks.
---

# Notion2API Regression Validation Prompt

You are validating a Notion2API MCP fix. Validate the behavior that was broken, not just that the server starts.

## Validation checklist

1. Confirm the server health endpoint or MCP handshake succeeds.
2. Confirm model/tool listing returns expected operations.
3. Run one read-only Notion operation.
4. Run one safe write operation against a test page or configured scratch parent.
5. Confirm output schema shape matches the advertised schema.
6. Confirm error handling returns structured errors for bad input.
7. Confirm no secrets appear in logs, reports, model messages, or exported artifacts.
8. Confirm persistence behavior if the fix touches conversations, threads, or session state.
9. Confirm timeout behavior if the fix touches streaming or long-running calls.

## Result format

Return a validation matrix:

| Check | Command or action | Expected | Actual | Pass/Fail |
|---|---|---|---|---|

Then return:

- `Blocking failures`
- `Non-blocking warnings`
- `Follow-up patches`

## Safety rule

Do not delete existing conversations, Notion pages, databases, or user content as part of validation unless the user explicitly authorized cleanup.
