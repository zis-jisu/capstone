"""Minimal GPT-5.6 Luna Responses API client.

This module only handles transport. Stage-specific prompts and schemas live elsewhere.
Never hard-code API keys.
"""
import json
import os
import urllib.error
import urllib.request

OPENAI_URL = "https://api.openai.com/v1/responses"
MODEL = "gpt-6-luna"


def call_structured(*, system_prompt, user_payload, json_schema, api_key=None, max_output_tokens=4000):
    key = (api_key or os.environ.get("OPENAI_API_KEY", "")).strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    payload = {
        "model": MODEL,
        "store": False,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "pipeline_output",
                "strict": True,
                "schema": json_schema,
            }
        },
        "max_output_tokens": max_output_tokens,
    }

    request = urllib.request.Request(
        OPENAI_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read(4096).decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API error {exc.code}: {detail}") from None
    finally:
        request.remove_header("Authorization")

    output_text = "".join(
        part.get("text", "")
        for item in result.get("output", [])
        for part in item.get("content", [])
        if part.get("type") == "output_text"
    )
    if not output_text:
        raise RuntimeError("No output_text returned.")

    return json.loads(output_text), {
        "response_id": result.get("id"),
        "model": result.get("model"),
        "usage": result.get("usage"),
    }
