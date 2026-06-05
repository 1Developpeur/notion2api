from app.conversation import build_standard_transcript


def test_standard_transcript_answers_latest_user_turn():
    transcript = build_standard_transcript(
        [
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "second question"},
        ],
        "gemini-2.5flash",
        {"user_id": "user-1", "space_id": "space-1"},
    )

    message_blocks = [block for block in transcript if block["type"] != "config" and block["type"] != "context"]

    assert [block["type"] for block in message_blocks] == ["user"]
    prompt = message_blocks[0]["value"][0][0]
    assert "[Previous conversation context]" in prompt
    assert "user: first question" in prompt
    assert "assistant: first answer" in prompt
    assert "[Current user request]" in prompt
    assert prompt.endswith("second question")
