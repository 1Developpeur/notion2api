import json

from app import mcp_server
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



def test_attachment_manifest_redacts_inline_data():
    manifest = mcp_server._attachment_manifest_from_payload({
        "attachments": [
            {
                "name": "sample.pdf",
                "content_type": "application/pdf",
                "size_bytes": 12,
                "source": "mcp_file",
                "data": "data:application/pdf;base64,JVBERi0xLjQ=",
            }
        ]
    })
    assert manifest == [
        {
            "name": "sample.pdf",
            "content_type": "application/pdf",
            "source": "mcp_file",
            "size_bytes": 12,
        }
    ]
    dumped = json.dumps(manifest)
    assert "JVBER" not in dumped
    assert "data:application/pdf" not in dumped


def test_atomic_write_json_retries_replace_failure(tmp_path, monkeypatch):
    path = tmp_path / "jobs.json"
    real_replace = mcp_server.os.replace
    calls = {"count": 0}

    def flaky_replace(src, dst):
        calls["count"] += 1
        if calls["count"] == 1:
            raise PermissionError("locked")
        return real_replace(src, dst)

    monkeypatch.setattr(mcp_server.os, "replace", flaky_replace)
    mcp_server._atomic_write_json(path, {"jobs": {"a": {"updated_at": 1}}})
    assert calls["count"] == 2
    assert json.loads(path.read_text(encoding="utf-8"))["jobs"]["a"]["updated_at"] == 1


def test_load_chat_job_state_recovers_valid_tmp_file(tmp_path):
    path = tmp_path / ".notion2api_mcp_chat_jobs.json"
    path.write_text(json.dumps({"jobs": {"old": {"request_id": "old", "updated_at": 1}}}), encoding="utf-8")
    tmp = path.with_name(f"{path.name}.abc.tmp")
    tmp.write_text(
        json.dumps({
            "jobs": {
                "old": {"request_id": "old", "updated_at": 2},
                "new": {"request_id": "new", "updated_at": 3},
            }
        }),
        encoding="utf-8",
    )

    state = mcp_server._load_chat_job_state(path)
    assert sorted(state["jobs"]) == ["new", "old"]
    assert state["jobs"]["old"]["updated_at"] == 2
    assert json.loads(path.read_text(encoding="utf-8"))["jobs"]["new"]["updated_at"] == 3
