from app.mcp_server import _extract_chat_content, _extract_responses_text, create_server


def test_extract_chat_content_from_openai_shape():
    data = {"choices": [{"message": {"content": "hello"}}]}
    assert _extract_chat_content(data) == "hello"


def test_extract_responses_text_from_output_text():
    data = {"output_text": "hello responses"}
    assert _extract_responses_text(data) == "hello responses"


def test_create_server_registers_tools():
    server = create_server(
        base_url="http://127.0.0.1:8000",
        api_key=None,
        timeout=1,
        host="127.0.0.1",
        port=8130,
        mcp_path="/mcp",
    )
    assert server is not None
