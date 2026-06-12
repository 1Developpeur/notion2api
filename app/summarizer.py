import httpx

from app.config import SILICONFLOW_API_KEY


class SummarizerUnavailableError(Exception):
    """Raised when summarizer service cannot be used."""


SILICONFLOW_ENDPOINT = "https://api.siliconflow.cn/v1/chat/completions"
MODEL_FALLBACK_CHAIN = ["Qwen/Qwen3-8B", "THUDM/glm-4-9b-chat"]

SYSTEM_PROMPT = (
    "text1~3text\n"
    "text\n\n"
    "text"
)


def is_summarizer_configured() -> bool:
    return bool(SILICONFLOW_API_KEY.strip())


def _build_user_prompt(old_summaries: list[str], user_msg: str, assistant_msg: str) -> str:
    prompt_parts = []
    if old_summaries:
        prompt_parts.append("text")
        prompt_parts.append("\n".join(old_summaries[-5:]))
        prompt_parts.append("")

    prompt_parts.append("text")
    prompt_parts.append(f"text{user_msg}")
    prompt_parts.append(f"AItext{assistant_msg}")
    prompt_parts.append("")
    prompt_parts.append("text")
    return "\n".join(prompt_parts)


async def _call_summarizer(model: str, old_summaries: list[str], user_msg: str, assistant_msg: str) -> str:
    timeout = httpx.Timeout(connect=5.0, read=20.0, write=20.0, pool=20.0)
    headers = {
        "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(old_summaries, user_msg, assistant_msg)},
        ],
        "temperature": 0.2,
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(SILICONFLOW_ENDPOINT, headers=headers, json=payload)

    if response.status_code != 200:
        raise SummarizerUnavailableError(f"Summarizer upstream returned status {response.status_code}")

    data = response.json()
    content = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    summary = str(content).strip()
    if not summary:
        raise SummarizerUnavailableError("Summarizer returned empty summary")
    return summary


async def summarize_turn(
    old_summaries: list[str],
    user_msg: str,
    assistant_msg: str,
) -> str:
    """
    text LLM text
    """
    if not is_summarizer_configured():
        raise SummarizerUnavailableError("SILICONFLOW_API_KEY is empty")

    last_error: Exception | None = None
    for model in MODEL_FALLBACK_CHAIN:
        try:
            return await _call_summarizer(model, old_summaries, user_msg, assistant_msg)
        except Exception as exc:
            last_error = exc
            continue

    raise SummarizerUnavailableError(
        f"All summarizer models failed: {last_error}"
    ) from last_error
