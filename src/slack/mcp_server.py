"""Read-only, person-centered Slack discovery through MCP."""
from datetime import datetime, timedelta, timezone
import re
from src.slack.collector import _get

def list_conversations():
    rows, cursor = [], ""
    while True:
        args = {"types": "public_channel,private_channel,im,mpim", "limit": 200}
        if cursor:
            args["cursor"] = cursor
        data = _get("conversations.list", args)
        rows.extend(data.get("channels", []))
        cursor = data.get("response_metadata", {}).get("next_cursor", "")
        if not cursor:
            return rows

def collect_context(person_id: str, days: int = 90):
    if not person_id.startswith("U") or not 1 <= days <= 90:
        raise ValueError("Invalid person ID or lookback window")
    oldest = str(int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp()))
    records, warnings, matched = {}, [], []
    for channel in list_conversations():
        if channel.get("is_member") is False:
            continue
        channel_id = channel["id"]
        cursor = ""
        selected = False
        for _ in range(20):
            params = {"channel": channel_id, "oldest": oldest, "limit": 200}
            if cursor:
                params["cursor"] = cursor
            try:
                page = _get("conversations.history", params)
            except RuntimeError as exc:
                warnings.append(str(exc))
                break
            for root in page.get("messages", []):
                thread = [root]
                if root.get("reply_count"):
                    try:
                        thread = _get("conversations.replies", {"channel": channel_id, "ts": root["ts"], "limit": 200}).get("messages", [root])
                    except RuntimeError as exc:
                        warnings.append(str(exc))
                if any(m.get("user") == person_id or "<@" + person_id + ">" in m.get("text", "") for m in thread):
                    selected = True
                    for m in thread:
                        if m.get("user"):
                            records[channel_id + ":" + m["ts"]] = {"source_id": channel_id + ":" + m["ts"], "conversation_id": channel_id, "conversation_type": "unknown", "parent_ts": None if m["ts"] == root["ts"] else root["ts"], "slack_ts": m["ts"], "slack_author_id": m["user"], "raw_text": m.get("text", "")}
            cursor = page.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                break
        if selected:
            matched.append(channel.get("name", channel_id))
    people = []
    for uid in sorted({r["slack_author_id"] for r in records.values()}):
        try:
            user = _get("users.info", {"user": uid}).get("user", {})
            name = user.get("real_name") or user.get("name") or uid
        except RuntimeError:
            name = uid
        people.append({"slack_id": uid, "name": name})
    return {"people": people, "records": sorted(records.values(), key=lambda r: float(r["slack_ts"])), "metadata": {"matched_channels": matched, "warnings": warnings}}

def collect_work_context(work_id: str, threads: list[dict], days: int = 90):
    """Read only the Work's explicit DB evidence threads, including paginated replies."""
    if work_id != "WORK-00020" or not 1 <= days <= 90 or not threads:
        raise ValueError("Only WORK-00020 with explicit evidence threads is supported")
    roots = set()
    for thread in threads:
        channel, ts = thread.get("channel_id", ""), thread.get("thread_ts", "")
        if not re.fullmatch(r"[CDG][A-Z0-9]+", channel) or not re.fullmatch(r"[0-9]+\.[0-9]+", ts):
            raise ValueError("Invalid Slack evidence thread")
        roots.add((channel, ts))
    oldest = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
    records, users = {}, set()
    for channel, root_ts in sorted(roots):
        cursor, seen = "", set()
        for _ in range(100):
            params = {"channel": channel, "ts": root_ts, "limit": 100}
            if cursor:
                params["cursor"] = cursor
            page = _get("conversations.replies", params)
            for message in page.get("messages", []):
                ts, author = message.get("ts"), message.get("user")
                if not ts or not author or float(ts) < oldest:
                    continue
                if message.get("thread_ts", root_ts) != root_ts:
                    raise ValueError("Slack returned a message outside the evidence thread")
                text = message.get("text", "")
                users.add(author)
                users.update(re.findall(r"<@(U[A-Z0-9]+)(?:\|[^>]+)?>", text))
                source = channel + ":" + ts
                records[source] = {"source_id": source, "conversation_id": channel,
                    "conversation_type": "im" if channel.startswith("D") else "channel",
                    "parent_ts": None if ts == root_ts else root_ts,
                    "slack_ts": ts, "slack_author_id": author, "raw_text": text,
                    "edited": message.get("edited")}
            cursor = page.get("response_metadata", {}).get("next_cursor", "").strip()
            if not cursor:
                if page.get("has_more"):
                    raise RuntimeError("Slack thread pagination is incomplete")
                break
            if cursor in seen:
                raise RuntimeError("Slack thread pagination repeated a cursor")
            seen.add(cursor)
        else:
            raise RuntimeError("Slack thread exceeds collection limit; no partial sync saved")
    people = []
    for uid in sorted(users):
        user = _get("users.info", {"user": uid}).get("user", {})
        profile = user.get("profile") or {}
        name = user.get("real_name") or profile.get("real_name") or user.get("name")
        if not name:
            raise RuntimeError("Slack user display name is unavailable")
        people.append({"slack_id": uid, "name": name})
    return {"work_id": work_id, "people": people,
            "records": sorted(records.values(), key=lambda row: float(row["slack_ts"])),
            "metadata": {"days": days, "oldest_ts": oldest, "thread_count": len(roots),
                         "matched_channels": sorted({channel for channel, _ in roots}), "warnings": []}}


def make_server():
    from mcp.server.fastmcp import FastMCP
    server = FastMCP("Slack Handover")
    @server.tool()
    def discover_slack_conversations() -> list[dict]:
        """Find conversations visible to authenticated user."""
        return [{"id": c["id"], "name": c.get("name", "(DM)")} for c in list_conversations()]
    @server.tool()
    def collect_slack_person_work(person_id: str, days: int = 90) -> dict:
        """Collect a person's messages and full threads from all visible conversations."""
        return collect_context(person_id, days)
    @server.tool()
    def collect_slack_work_threads(work_id: str, threads: list[dict], days: int = 90) -> dict:
        """Collect only a Work's explicit evidence threads within the last 90 days."""
        return collect_work_context(work_id, threads, days)
    return server

if __name__ == "__main__":
    make_server().run(transport="stdio")
