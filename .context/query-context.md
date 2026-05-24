# SigMap Query Context
Generated: 2026-05-24T01:47:06.976Z

## app\api\chat_history.py
```
def status() → dict[str, Any]
async def import_har(request: Request) → dict[str, Any]  # Import a browser HAR JSON object containing Notion AI chat-h
async def sync_from_notion(request: Request) → dict[str, Any]  # Pull chat-history metadata by default; hydrate full message
async def delete_threads(request: Request) → dict[str, Any]  # Bulk-delete remote Notion chat threads and remove confirmed
async def post_delete_threads(request: Request) → dict[str, Any]  # POST fallback for clients/proxies that reject DELETE with a
def get_thread(thread_id: str) → dict[str, Any]  # Hydrate full messages for one selected archived thread
async def hydrate_thread(thread_id: str, request: Request) → dict[str, Any]  # Hydrate full messages for one selected archived thread
def debug_thread(thread_id: str) → dict[str, Any]
def export_markdown(thread_id: str) → str
GET /status  →  status()
POST /import/har  →  import_har()
POST /sync/notion  →  sync_from_notion()
POST /import/notion  →  sync_from_notion()
GET /threads  →  list_threads()
DELETE /threads  →  delete_threads()
POST /threads/delete  →  post_delete_threads()
POST /threads/bulk-delete  →  post_delete_threads()
GET /threads/{thread_id}  →  get_thread()
POST /threads/{thread_id}/hydrate  →  hydrate_thread()
GET /threads/{thread_id}/debug  →  debug_thread()
```

## app\notion_client.py
```
class NotionUpstreamError(RuntimeError)
class NotionOpusAPI
def __init__(account_config: dict)
def fetch_chat_history(limit: int, max_pages: int) → dict[str, Any]
def delete_threads(thread_ids: list[str]) → dict[str, Any]
def delete_thread(thread_id: str) → None
def stream_response(transcript: list, thread_id: str?) → Generator[dict[str, Any], None
```

## app\chat_history\extractor.py
```
def record_value(record: Any) → dict[str, Any]
def record_maps(obj: Any)
def visible_message_text(value: dict[str, Any]) → str  # Return only the text Notion shows as chat content, excluding
def visible_message_role(value: dict[str, Any]) → str | None
def extract_message_ids(value: dict[str, Any]) → list[str]  # Collect nested Notion thread-message IDs without treating co
def collect_hydration_message_ids(value: Any, depth: int) → list[str]  # Collect nested Notion thread-message IDs without treating co
def normalize_thread(thread_id: str | None, raw: dict[str, Any]) → dict[str, Any] | None
def normalize_message(message_id: str | None, raw: dict[str, Any], fallback_thread_id: str | None) → dict[str, Any] | None
def merge_records_into_bundle(bundle: dict[str, Any], obj: Any) → None
def extract_chat_bundle(obj: Any) → dict[str, Any]
def redact_secrets(value: Any, depth: int) → Any
def describe_thread_record(thread: dict[str, Any] | None, messages: list[dict[str, Any]] | None) → dict[str, Any]
```

## tests\test_chat_history_extractor.py
```
class ChatHistoryExtractorTests(unittest.TestCase)
def test_extract_message_id_field_variants() → None
def test_normalize_message_field_variants() → None
def test_merge_records_with_inline_conversation_messages() → None
def test_describe_thread_record_includes_message_raw_fields() → None
def test_normalize_message_uses_nested_data_title_as_text_fallback() → None
def test_normalize_thread_preserves_numeric_notion_timestamps() → None
def test_agent_inference_uses_visible_text_only() → None
def test_tool_result_records_are_not_visible_messages() → None
```

## app\chat_history\notion_sync.py
```
def hydrate_message_ids_from_notion(client: NotionOpusAPI, message_ids: list[str] | set[str], *, fallback_thread_id: str | None, hydrate_batch_size: int) → dict[str, Any]  # Hydrate specific Notion thread-message IDs into a chat-histo
def hydrate_thread_record_from_notion(client: NotionOpusAPI, thread_id: str) → dict[str, Any]
def hydrate_thread_from_notion(client: NotionOpusAPI, thread: dict[str, Any], *, hydrate_batch_size: int) → dict[str, Any]  # Hydrate only the messages referenced by one selected archive
def sync_chat_history_from_notion(client: NotionOpusAPI, *, limit: int, max_pages: int, hydrate: bool, hydrate_batch_size: int) → dict[str, Any]  # Read-only direct sync from Notion transcript RPCs into the l
```
