# Notion2API

> Notion AI to OpenAI-Compatible API Wrapper

🌐 English | [中文](./README_CN.md)

Notion2API wraps Notion AI as an OpenAI-compatible API, supporting direct use with Cherry Studio, Zotero, and other third-party clients, as well as existing frontend pages.

## Features

- **Three Operation Modes** - Lite/Standard/Heavy to meet different needs
- **OpenAI Compatible** - Standard `/v1/chat/completions` endpoint
- **Streaming Response** - SSE real-time output support
- **Thinking Panel** - Reasoning process display for all models
- **Search Feature** - Web search results display
- **Account Pool** - Multi-account load balancing and failover
- **Docker Deployment** - Ready-to-use containerized solution

---

## Mode Comparison

| Feature | Lite | Standard | Heavy |
|---------|------|----------|-------|
| **Memory** | ❌ None | ✅ Client-managed | ✅ Server-managed |
| **Database** | ❌ Not needed | ❌ Not needed | ✅ SQLite |
| **Thinking** | ❌ Not needed | ✅ Dedicated panel | ✅ Dedicated panel |
| **Search Results** | ❌ Not needed | ✅ Dedicated panel | ✅ Dedicated panel |
| **Rate Limit** | 30/min | 25/min | 20/min |
| **Use Case** | Simple Q&A | Short-mid conversations | Long-term conversations |

To switch modes: change the `APP_MODE` variable in `.env`.

---

## Quick Start

### 1. Get Notion Credentials

Run the interactive login helper:

```bash
python login.py
```

It will:
1. Launch a local Chrome window on a debug port.
2. Let you sign in to Notion in that browser.
3. Read the Notion browser session cookies via DevTools.
4. Use those cookies locally to capture `token_v2` and identify the active Notion user.
5. Validate the token against Notion.
6. Extract `space_id`, `user_id`, `space_view_id`, `user_name`, and `user_email`.
7. Prefer the active `notion_user_id` cookie when multiple users/workspaces are visible.
8. Save the result into `accounts.json` as a named profile.
9. Update `.env` with the refreshed `NOTION_ACCOUNTS` value.

The helper does not commit or store the full browser cookie jar. Browser cookies are only used during the local login flow to select the correct account/workspace. Keep generated `accounts.json` and `.env` files private; both are ignored by git because they contain credentials.

To verify the saved login later, run:

```bash
python login.py --check
```

To inspect all saved profiles, run:

```bash
python login.py --list
```

To check a specific profile, pass its name:

```bash
python login.py --check --profile work
```

If you prefer the old manual flow, you can still use `scripts/extract_notion_info.js` and fill `accounts.json` yourself.

If Chrome is unavailable or you want to paste a token directly, use:

```bash
python login.py --manual
```

The browser-assisted flow waits up to 300 seconds by default so you have time to finish signing in.

### 2. Configure Environment Variables

```bash
# Copy example config
cp .env.example .env

# If you used login.py, accounts.json is already populated.
# You can still override the account pool through .env if needed.
NOTION_ACCOUNTS='[{"profile_name":"default","token_v2":"your_token","space_id":"your_space","user_id":"your_uid","space_view_id":"your_view","user_name":"your_name","user_email":"your_email"}]'
APP_MODE=standard  # lite / standard / heavy
```

**⚠️ If using Heavy mode**:

Heavy mode requires `SILICONFLOW_API_KEY` (for conversation summary compression):
1. Visit https://siliconflow.cn to register an account (free)
2. Get your API Key
3. Add it to `.env`:
   ```bash
   SILICONFLOW_API_KEY=your_api_key_here
   APP_MODE=heavy
   ```

### 3. Start the Service

#### Docker Deployment (Recommended)

```bash
# Build and start
docker-compose build --no-cache && docker-compose up -d
# Access http://localhost:8000
```

**Note**: `accounts.json` is mounted as a volume. After modifying accounts, just `docker-compose restart` — no rebuild needed.

#### Local Run

```bash
pip install -r requirements.txt
uvicorn app.server:app --host 0.0.0.0 --port 8000
```

---

## Supported Models

| Model Name | Description |
|---|---|
| `claude-sonnet4.6` | Best balance of performance and speed! (**Most recommended**, most optimized, most reliable) |
| `claude-opus4.6` | Stronger reasoning, but not recommended for frequent use |
| `claude-opus4.7` | Latest Claude, even stronger reasoning |
| `gpt-5.5` | Latest GPT model (Beta) |
| `gemini-2.5flash` | **Native fast**, no thinking delay, highly recommended for quick tasks |
| `gemini-3.1pro` | Google's strongest reasoning model |
| `gpt-5.2` / `gpt-5.4` | OpenAI models, also great |
| `kimi-2.6` | Moonshot AI model (Beta) |

View full list: `GET http://localhost:8000/v1/models`

---

## API Usage
This project supports custom API keys with no format requirements.

### Python Example

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="optional_api_key"
)

response = client.chat.completions.create(
    model="claude-sonnet4.6",
    messages=[{"role": "user", "content": "Hello"}],
    stream=True
)

for chunk in response:
    print(chunk.choices[0].delta.content or "", end="")
```

### Use with LLM Council Plus

`llm-council-plus` supports any OpenAI-compatible endpoint. Point it at this service and use the `/v1` prefix:

1. Start Notion2API locally or on your server.
2. In `llm-council-plus`, open **LLM API Keys** → **Custom OpenAI-Compatible Endpoint**.
3. Set **Base URL** to `http://localhost:8000/v1`.
4. Set **API Key** only if `API_KEY` is enabled on this service. If `API_KEY` is unset, leave it blank.
5. Click **Connect** to verify. The app will call `GET /v1/models` for discovery and `POST /v1/chat/completions` for chat.

If you run Notion2API behind a reverse proxy, replace `http://localhost:8000` with your public origin and keep the `/v1` suffix.

---

## Web UI
(Custom design inspired by Claude style, supports Standard and Heavy modes)

Access `http://localhost:8000` to use the built-in Web UI:

- **Main Content Area** - Displays AI responses
- **Thinking Panel** - Shows reasoning process (collapsible)
- **Search Panel** - Shows search sources (collapsible)
- **Star Feature** - Bookmark valuable conversations to the top

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `APP_MODE` | Operation mode: lite/standard/heavy | `heavy` |
| `NOTION_ACCOUNTS` | Notion credentials JSON array | Required |
| `API_KEY` | Client authentication key | Optional (recommended) |
| `DB_PATH` | SQLite database path | `./data/conversations.db` |
| `HOST_PORT` | Host port | `8000` |
| `SILICONFLOW_API_KEY` | Required for Heavy mode, used for early conversation summary compression | Optional |

---

## Docker Deployment

### Using docker-compose (Recommended)

```bash
# 1. Configure environment
cp .env.example .env
nano .env

# 2. Configure accounts (see accounts.README.md)
nano accounts.json

# 3. Build and start
docker-compose build --no-cache && docker-compose up -d

# 4. View logs
docker-compose logs -f

# 5. Stop service
docker-compose down
```

### Update After Code Changes

```bash
git pull && docker-compose down && docker-compose build --no-cache && docker-compose up -d
```

### Update Accounts Only (No Rebuild Needed)

```bash
nano accounts.json
docker-compose restart
```

### Custom Port

Modify the `HOST_PORT` variable in `.env`:
```bash
HOST_PORT=8080  # Use port 8080
```

---

## FAQ

> For detailed error solutions, see [Issues & Troubleshooting](./docs/issues.md)

### 1. Thinking panel not showing?

Make sure you are using `APP_MODE=standard` or `heavy`. Lite mode does not support Thinking.

### 2. How to switch modes?

Modify `APP_MODE` in `.env`, then restart the service:
```bash
APP_MODE=standard  # Switch to standard
docker-compose restart
```

### 3. How to configure multiple accounts?
(Multiple accounts improve stability, Beta version)

`NOTION_ACCOUNTS` supports array format:
```json
[
  {"token_v2":"token1","space_id":"space1",...},
  {"token_v2":"token2","space_id":"space2",...}
]
```

---

## Compatibility Test
(Note: Due to Notion's own AI call rate, there is usually a ~3 second delay from sending a query to receiving an answer. Clients with high latency requirements, such as Immersive Translate, are not recommended.)

| Client | Status | Notes |
|--------|--------|-------|
| Cherry Studio | ✅ Full support | Recommended |
| Zotero Translation | ✅ Full support | Slightly slow, but sonnet model is accurate |
| Immersive Translate | Not recommended | Very slow |

---

## License

MIT License

---

## Star History

If this project helps you, please give it a Star ⭐

## Notes
This project was built with assistance from Claude Code and Codex.

**Heavy Mode Details**:
- Sliding window: retains the most recent **8 rounds** of conversation (16 messages) by default
- Summary compression: content beyond the window is automatically compressed into a summary
- Full archive: all history is permanently stored in the SQLite database

**Future Improvements**:
- If you need a custom sliding window size (e.g., 10 or 20 rounds), feel free to submit an Issue
- We will add environment variable configuration options based on demand

Issues and suggestions are welcome!
