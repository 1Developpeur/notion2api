# Notion AI API Analysis

This document provides a comprehensive breakdown of the internal REST and streaming APIs used by Notion AI on `notion.com` / `app.notion.com`. All schemas, endpoints, and payloads were captured directly from live network traffic monitored using Chrome DevTools MCP.

---

## 1. Authentication & Common Headers

All API calls are authenticated via standard session cookies sent automatically by the browser:
*   `token_v2`: The main session token.
*   `csrf`: Cross-site request forgery prevention token.
*   `notion_user_id`: The currently active user ID.

### Common Request Headers
Every POST request to `/api/v3/*` includes these headers:
```http
content-type: application/json
x-notion-active-user-header: <user-uuid>
x-notion-space-id: <space-uuid>
notion-client-version: 23.13.20260623.1532
notion-audit-log-platform: web
```

---

## 2. Model Discovery & Configuration

### `POST /api/v3/getAvailableModels`
Fetches the registry of available models for the workspace, including display metadata, speed/intelligence ratings, and pricing/tier restrictions.

*   **Request Body:**
    ```json
    {
      "spaceId": "00000000-0000-0000-0000-000000000000"
    }
    ```

*   **Response Body (Excerpt):**
    ```json
    {
      "restrictedAccessModelsInPickerConfig": [
        {
          "codename": "acai-budino",
          "modelMessage": "Fable 5",
          "modelFamily": "anthropic",
          "disabledReason": "trial_not_allowed"
        }
      ],
      "models": [
        {
          "model": "oatmeal-cookie",
          "modelMessage": "GPT-5.2",
          "modelFamily": "openai",
          "displayGroup": "fast",
          "isDisabled": false,
          "modelCardAttributes": { "speed": 4, "intelligence": 4, "cost": 3 },
          "markdownChat": { "beta": true },
          "workflow": { "finalModelName": "oatmeal-cookie", "beta": true },
          "customAgent": { "finalModelName": "oatmeal-cookie", "beta": true }
        },
        {
          "model": "opal-quince-medium",
          "modelMessage": "GPT-5.5",
          "modelFamily": "openai",
          "displayGroup": "intelligent",
          "isDisabled": false,
          "modelCardAttributes": { "speed": 4, "intelligence": 5, "cost": 5 }
        },
        {
          "model": "almond-croissant-low",
          "modelMessage": "Sonnet 4.6",
          "modelFamily": "anthropic",
          "displayGroup": "fast",
          "isDisabled": false,
          "modelCardAttributes": { "speed": 3, "intelligence": 5, "cost": 4 }
        }
      ]
    }
    ```

### `POST /api/v3/getAiPickableModels`
Returns a flat array of all pickable internal model codenames for the workspace.

*   **Request Body:** `{}`
*   **Response Body:**
    ```json
    {
      "models": [
        "openai-gpt-4o",
        "openai-gpt-4o-mini",
        "opal-quince",
        "opal-quince-medium",
        "opal-quince-high",
        "anthropic-sonnet-3.7",
        "apple-danish",
        "vertex-gemini-3.5-flash",
        "fireworks-llama3-70b",
        "fireworks-deepseek-r1",
        "fireworks-kimi-k2.6",
        "baseten-deepseek-v4-pro",
        "baseten-glm-5.2",
        "oatmeal-cookie",
        "oatmeal-cookie-medium-thinking",
        "oatmeal-cookie-high-thinking",
        "oval-kumquat",
        "oval-kumquat-medium",
        "oval-kumquat-high",
        "oregon-grape-low",
        "oregon-grape-medium",
        "oregon-grape-high",
        "otaheite-apple-low",
        "otaheite-apple-medium",
        "otaheite-apple-high",
        "ambrosia-tart-high",
        "apricot-sorbet-x-high",
        "apricot-sorbet-max",
        "apricot-sorbet-high",
        "apricot-sorbet-medium",
        "apricot-sorbet-low",
        "acai-budino-high",
        "avocado-froyo-medium",
        "almond-croissant-low",
        "galette-medium-thinking",
        "xigua-mochi-medium",
        "xinomavro-cake"
      ]
    }
    ```

---

## 3. Chat Inference & Streaming

### `POST /api/v3/runInferenceTranscript`
The main streaming AI chat endpoint. It consumes the complete conversation transcript (modeled as block operations) and streams back updates in NDJSON format.

*   **Request Headers (Additional):**
    ```http
    accept: application/x-ndjson
    ```

*   **Request Body Schema:**
    ```json
    {
      "traceId": "88888888-8888-8888-8888-888888888888",
      "spaceId": "00000000-0000-0000-0000-000000000000",
      "threadId": "77777777-7777-7777-7777-777777777777",
      "createThread": false,
      "generateTitle": false,
      "saveAllThreadOperations": true,
      "setUnreadState": true,
      "createdSource": "workflows",
      "threadType": "workflow",
      "isPartialTranscript": true,
      "asPatchResponse": true,
      "patchResponseVersion": 2,
      "transcript": [
        {
          "id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
          "type": "config",
          "value": {
            "type": "workflow",
            "model": "baseten-glm-5.2",
            "searchScopes": [{"type": "notion"}, {"type": "github"}],
            "useWebSearch": true
          }
        },
        {
          "id": "ffffffff-ffff-ffff-ffff-ffffffffffff",
          "type": "context",
          "value": {
            "timezone": "America/Chicago",
            "userName": "John Doe",
            "userId": "22222222-2222-2222-2222-222222222222",
            "context_page_id": "55555555-5555-5555-5555-555555555555"
          }
        },
        {
          "id": "12345678-1234-1234-1234-123456789012",
          "type": "updated-config",
          "value": {
            "model": "almond-croissant-low"
          }
        },
        {
          "id": "23456789-2345-2345-2345-234567890123",
          "type": "user",
          "value": [["what is the operating mode rule?"]],
          "userId": "22222222-2222-2222-2222-222222222222",
          "createdAt": "2026-06-23T16:25:56.745-05:00"
        }
      ]
    }
    ```

*   **Response Format (NDJSON):**
    The server streams lines of JSON, using a patch-based approach to construct thinking blocks, message content, and performance stats:
    ```json
    {"type":"patch-start","data":{"s":[{"id":"...","type":"agent-turn-full-record-map"}]},"version":1}
    {"type":"patch","v":[{"o":"a","p":"/s/-","v":{"id":"...","type":"agent-inference","value":[{"type":"thinking","content":"The user is asking...","modelProvider":"anthropic","notionModelName":"almond-croissant-low"}]}}]}
    {"type":"patch","v":[{"o":"x","p":"/s/1/value/0/content","v":" token chunk"}]}
    {"type":"patch","v":[{"o":"a","p":"/s/1/finishedAt","v":1782249965672},{"o":"a","p":"/s/1/inputTokens","v":5577},{"o":"a","p":"/s/1/outputTokens","v":276},{"o":"a","p":"/s/1/cachedTokensRead","v":5339},{"o":"a","p":"/s/1/model","v":"almond-croissant-low"}]}
    ```

---

## 4. Workspaces & Billing Limits

### `POST /api/v3/getAIUsageEligibilityV2`
Fetches a workspace's detailed AI credit usage and subscription limits.

*   **Request Body:** `{"spaceId": "11111111-1111-1111-1111-111111111111"}`
*   **Response Body:**
    ```json
    {
      "usage": {
        "currentServicePeriod": { "spaceUsage": 0, "userUsage": 0 },
        "lifetime": { "spaceUsage": 23, "userUsage": 23 },
        "lastSpaceUsageAtMs": 1780586568518
      },
      "limits": {
        "purchased": { "totalLimit": 0 },
        "free": { "spaceLimit": 0, "userLimit": 75 }
      },
      "basicCredits": { "spaceUsage": 23, "userUsage": 23, "userLimit": 75 }
    }
    ```

### `POST /api/v3/getAIUsageEligibility`
A simplified version of the usage check returning direct boolean eligibility status.

*   **Response Body:**
    ```json
    {
      "isEligible": true,
      "type": "userAllowance",
      "spaceUsage": 23,
      "userUsage": 23,
      "userLimit": 75,
      "researchModeUsage": 1
    }
    ```

---

## 5. Integrations & Connectors

### `POST /api/v3/listAIConnectors`
Lists all active third-party integrations (e.g., Slack, Gmail, Google Drive) and exposes licensing blocks.

*   **Request Body:** `{"spaceId": "11111111-1111-1111-1111-111111111111"}`
*   **Response Body:**
    ```json
    {
      "connectedConnectors": [
        {
          "id": "notion-mail",
          "thirdPartyId": "33333333-3333-3333-3333-333333333333",
          "details": {
            "connectionDetails": {
              "status": "completed",
              "external_source_name": "john.doe@example.com",
              "progress": 100
            }
          }
        }
      ],
      "unavailableConnectors": [
        {
          "id": "slack",
          "reasons": [
            {
              "reason": "INSUFFICIENT_SUBSCRIPTION",
              "upsell": { "type": "product", "product": "business" }
            }
          ]
        }
      ]
    }
    ```

---

## 6. Navigation & Chat History

### `POST /api/v3/getRecentPageVisits`
Fetches pages recently visited by the user to populate the "Give context" list.

*   **Request Body:**
    ```json
    {
      "spaceId": "11111111-1111-1111-1111-111111111111",
      "userId": "33333333-3333-3333-3333-333333333333",
      "limit": 50,
      "beforeTimestamp": 1782249334431,
      "sinceTimestamp": 1773609334431
    }
    ```

*   **Response Body:**
    ```json
    {
      "pages": [
        {
          "id": "2fd40fcc-646d-8114-9c59-e78be2784697",
          "name": "Read Me",
          "visitedAt": 1780807990630
        }
      ]
    }
    ```

### `POST /api/v3/getChatTranscriptSessionHistoryForUser`
Retrieves previous chat sessions.

*   **Request Body:** `{"spaceId": "00000000-0000-0000-0000-000000000000"}`
*   **Response Body:**
    ```json
    {
      "chatSessionIds": [],
      "recordMap": { "__version__": 3 },
      "serverAssistantVersion": 16
    }
    ```

---

## 7. Operating Modes & Plan Only Mode

### Plan Only Mode
When "Plan Only Mode" is active, toggled, or cancelled in the chat UI, the client records this state inside the persistent `transcript` array of `POST /api/v3/runInferenceTranscript` as a `plan-mode` block.

*   **Active (Planning):**
    ```json
    {
      "id": "76527293-efad-4f61-b913-5f53722540f0",
      "type": "plan-mode",
      "value": {
        "state": "planning"
      }
    }
    ```
*   **Normal / Cancelled:**
    ```json
    {
      "id": "c9cb089c-e85f-4fb3-aad3-89247e465fb6",
      "type": "plan-mode",
      "value": {
        "state": "cancelled"
      }
    }
    ```

### Four-Mode Custom Protocol
The workspace's custom four-mode protocol (Review, Draft, Apply, Repair) is a business logic implementation driven by the custom instructions page. It does not map to explicit API-level endpoints; instead, the backend LLM reads these operating constraints from the instructions page content and restricts its own execution paths accordingly.

---

## 8. Custom Instructions Page & Context Injection

### Instructions Page Setup
Notion AI allows setting a workspace page to act as the primary instructions file that influences all AI behaviors. At the API level, the client does not send the actual instruction text in the request. Instead, it passes a `context_page_id` inside the `context` transcript block.

*   **API Representation (`runInferenceTranscript`):**
    ```json
    {
      "id": "ffffffff-ffff-ffff-ffff-ffffffffffff",
      "type": "context",
      "value": {
        "timezone": "America/Chicago",
        "userName": "John Doe",
        "userId": "22222222-2222-2222-2222-222222222222",
        "context_page_id": "55555555-5555-5555-5555-555555555555"
      }
    }
    ```

*   **Instruction Set Mechanics:**
    1. The client identifies which page is configured as the workspace instruction page.
    2. During chat or workflow execution, the client appends a `type: "context"` block containing the page's block UUID in the `context_page_id` field.
    3. The Notion AI backend resolves this `context_page_id` on the server, fetches the document's structured blocks, and prepends or injects them as a system prompt / system instruction block before executing the inference.

---

## 9. Message Lifecycle & Transaction Precedence

When a user submits a message in the chat UI, the client executes a strict, ordered sequence of calls to save the message blocks in the workspace database before requesting inference:

```
[User Presses Enter]
       ↓
1. GET /exp/ping (Experimentation Ping)
       ↓
2. POST /api/v3/saveTransactionsFanout (Create Message Blocks)
       ↓
3. POST /api/v3/syncRecordValuesSpaceInitial (Sync Blocks)
       ↓
4. POST /api/v3/runInferenceTranscript (Fire AI Streaming Inference)
```

### Step 1: Experimentation Ping (`GET /exp/ping`)
Fires right before the transaction, verifying connectivity and checking/refreshing experiment flags.

### Step 2: Database Persistence (`POST /api/v3/saveTransactionsFanout`)
Before inference runs, the user's input must be persisted in Notion's document model. The client submits a transaction containing multiple block operations:
*   **Operation 1:** Creates a `thread_message` block of `type: "context"` (containing client timezone, active user credentials, and `context_page_id`).
*   **Operation 2:** Creates a `thread_message` block of `type: "user"` containing the text value.
*   **Operation 3:** Appends both block IDs to the parent `thread`'s `messages` array using the `listAfterMulti` command.
*   **Operation 4:** Updates the parent `thread`'s `updated_time`.

*   **Transaction Payload Schema:**
    ```json
    {
      "requestId": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
      "transactions": [
        {
          "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
          "spaceId": "00000000-0000-0000-0000-000000000000",
          "debug": { "userAction": "WorkflowActions.addStepsToExistingThreadAndRun" },
          "operations": [
            {
              "pointer": { "table": "thread_message", "id": "cccccccc-cccc-cccc-cccc-cccccccccccc", "spaceId": "00000000-0000-0000-0000-000000000000" },
              "path": [],
              "command": "set",
              "args": {
                "id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                "version": 1,
                "step": {
                  "id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                  "type": "context",
                  "value": { "timezone": "America/Chicago", "userName": "John Doe", "userId": "22222222-2222-2222-2222-222222222222", "context_page_id": "55555555-5555-5555-5555-555555555555" }
                },
                "parent_id": "77777777-7777-7777-7777-777777777777",
                "parent_table": "thread"
              }
            },
            {
              "pointer": { "table": "thread_message", "id": "dddddddd-dddd-dddd-dddd-dddddddddddd", "spaceId": "00000000-0000-0000-0000-000000000000" },
              "path": [],
              "command": "set",
              "args": {
                "id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
                "version": 1,
                "step": {
                  "id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
                  "type": "user",
                  "value": [["what page is open?"]],
                  "userId": "22222222-2222-2222-2222-222222222222",
                  "createdAt": "2026-06-23T16:26:28.747-05:00"
                },
                "parent_id": "77777777-7777-7777-7777-777777777777",
                "parent_table": "thread"
              }
            },
            {
              "pointer": { "table": "thread", "id": "77777777-7777-7777-7777-777777777777", "spaceId": "00000000-0000-0000-0000-000000000000" },
              "path": ["messages"],
              "command": "listAfterMulti",
              "args": { "ids": ["cccccccc-cccc-cccc-cccc-cccccccccccc", "dddddddd-dddd-dddd-dddd-dddddddddddd"] }
            }
          ]
        }
      ]
    }
    ```

### Step 3: Record Sync (`POST /api/v3/syncRecordValuesSpaceInitial`)
Ensures server-side space caches have processed the transaction.

### Step 4: Inference Trigger (`POST /api/v3/runInferenceTranscript`)
Called immediately after, passing the identical transaction IDs in the `transcript` array so the AI engine can read the conversation history and stream back the NDJSON token patches.
