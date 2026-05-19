from app.chat_history.extractor import extract_message_ids, merge_records_into_bundle, normalize_message


def test_extract_message_id_field_variants():
    value = {
        "messages": ["m1", {"id": "m2"}],
        "message_ids": ["m3"],
        "thread_message_ids": ["m4"],
        "messageIds": ["m5"],
        "threadMessageIds": ["m6"],
        "conversation_messages": [{"messageId": "m7"}],
        "conversationMessages": [{"uuid": "m8"}],
        "records": [{"pointer": {"id": "m9"}}],
        "items": [{"value": {"id": "m10"}}],
    }

    assert extract_message_ids(value) == [
        "m1",
        "m2",
        "m3",
        "m4",
        "m5",
        "m6",
        "m7",
        "m8",
        "m9",
        "m10",
    ]


def test_normalize_message_field_variants():
    msg = normalize_message(
        None,
        {
            "messageId": "msg-1",
            "authorRole": "assistant",
            "threadId": "thread-1",
            "markdown": "hello from markdown",
        },
    )

    assert msg["id"] == "msg-1"
    assert msg["role"] == "assistant"
    assert msg["thread_id"] == "thread-1"
    assert "hello from markdown" in msg["text"]


def test_merge_records_with_inline_conversation_messages():
    bundle = {"threads": {}, "messages": {}, "endpoint_counts": {}}
    merge_records_into_bundle(
        bundle,
        {
            "transcripts": [
                {
                    "id": "thread-1",
                    "title": "Thread One",
                    "conversationMessages": [
                        {"messageId": "msg-1", "authorRole": "user", "body": "hello"},
                        {"messageId": "msg-2", "authorRole": "assistant", "content": "world"},
                    ],
                }
            ]
        },
    )

    assert "thread-1" in bundle["threads"]
    assert bundle["threads"]["thread-1"]["message_ids"] == ["msg-1", "msg-2"]
    assert bundle["messages"]["msg-1"]["thread_id"] == "thread-1"
    assert bundle["messages"]["msg-2"]["text"] == "world"
