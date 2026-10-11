"""On-demand Slack history collector.

The collector never polls in the background. Gold labels are not loaded here.
Raw text is retained for provenance, while model_text removes URLs so IDs such as
WORK-00005 embedded in links cannot leak into LLM evaluation.
"""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request


SLACK_API = "https://slack.com/api"


def _token(explicit=None):
    value = (explicit or os.environ.get("SLACK_TOKEN", "")).strip()
    if not value:
        raise RuntimeError("SLACK_TOKEN is not configured.")
    return value


def _get(method, params, token=None):
    req = urllib.request.Request(
        f"{SLACK_API}/{method}?" + urllib.parse.urlencode(params),
        headers={"Authorization": "Bearer " + _token(token)},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Slack HTTP error {exc.code}") from None

    if not data.get("ok"):
        raise RuntimeError("Slack API error: " + str(data.get("error", "unknown")))
    return data


def sanitize_for_model(text):
    text = re.sub(r"https?://\S+", "[LINK]", text or "")
    return text


_WORK_SIGNAL_RE = re.compile(
    r"(업무|자료|문서|파일|검토|확인|수정|전달|공유|요청|부탁|진행|완료|"
    r"마감|일정|회의|승인|제출|배포|회신|보고|작업|이슈|결과|업데이트|"
    r"담당|대기|보류|결정|정리|발송|수신)"
)

_SMALLTALK_ONLY_RE = re.compile(
    r"^\\s*(?:"
    r"안녕하세요|안녕하십니까|좋은\\s*아침(?:입니다|이에요|이네요)?|"
    r"감사합니다|감사해요|고맙습니다|수고하셨습니다|고생하셨습니다|"
    r"좋은\\s*(?:하루|주말)\\s*보내세요|"
    r"커피\\s*(?:드셨어요|마셨어요|드셨나요|마셨나요)|"
    r"점심\\s*(?:드셨어요|먹었어요|드셨나요|먹으셨나요)|"
    r"식사\\s*(?:하셨어요|하셨나요)|"
    r"네+|넵+|예+|ㅋㅋ+|ㅎㅎ+|ㅠ+|ㅜ+"
    r")\\s*[!?.~ㅎㅋㅠㅜ]*\\s*$"
)


def is_obvious_smalltalk_only(text):
    """Conservatively drop only messages that are clearly non-work smalltalk.

    Mixed messages are always retained so a later Event extractor can keep the
    work fact while ignoring conversational filler.
    """
    normalized = re.sub(r"<@[A-Z0-9]+>", "", text or "").strip()
    if not normalized:
        return True
    if _WORK_SIGNAL_RE.search(normalized):
        return False
    return bool(_SMALLTALK_ONLY_RE.fullmatch(normalized))


def collect_channel(channel_id, *, token=None, include_threads=True):
    messages = []
    cursor = ""

    while True:
        params = {"channel": channel_id, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        page = _get("conversations.history", params, token)
        messages.extend(page.get("messages", []))
        cursor = page.get("response_metadata", {}).get("next_cursor", "").strip()
        if not cursor:
            break

    records = []
    for message in sorted(messages, key=lambda x: float(x["ts"])):
        if is_obvious_smalltalk_only(message.get("text", "")):
            continue

        record = {
            "source_id": f"{channel_id}:{message['ts']}",
            "conversation_id": channel_id,
            "conversation_type": "unknown",
            "parent_ts": message.get("thread_ts"),
            "slack_ts": message["ts"],
            "slack_author_id": message.get("user"),
            "raw_text": message.get("text", ""),
            "model_text": sanitize_for_model(message.get("text", "")),
            "edited": message.get("edited"),
        }
        records.append(record)

        if include_threads and message.get("reply_count"):
            replies = _get(
                "conversations.replies",
                {"channel": channel_id, "ts": message["ts"], "limit": 200},
                token,
            )
            for reply in replies.get("messages", [])[1:]:
                if is_obvious_smalltalk_only(reply.get("text", "")):
                    continue
                records.append({
                    "source_id": f"{channel_id}:{reply['ts']}",
                    "conversation_id": channel_id,
                    "conversation_type": "unknown",
                    "parent_ts": message["ts"],
                    "slack_ts": reply["ts"],
                    "slack_author_id": reply.get("user"),
                    "raw_text": reply.get("text", ""),
                    "model_text": sanitize_for_model(reply.get("text", "")),
                    "edited": reply.get("edited"),
                })

    records.sort(key=lambda x: float(x["slack_ts"]))
    return {"channel_id": channel_id, "records": records}


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("channel_id")
    parser.add_argument("--out", default="collected.json")
    args = parser.parse_args()

    result = collect_channel(args.channel_id)
    Path(args.out).write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
