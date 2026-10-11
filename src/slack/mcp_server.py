"""Read-only, person-centered Slack discovery through MCP."""
from datetime import datetime, timedelta, timezone
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

def collect_context(person_id: str, days: int = 14):
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

def make_server():
    from mcp.server.fastmcp import FastMCP
    server = FastMCP("Slack Handover")
    @server.tool()
    def discover_slack_conversations() -> list[dict]:
        """Find conversations visible to authenticated user."""
        return [{"id": c["id"], "name": c.get("name", "(DM)")} for c in list_conversations()]
    @server.tool()
    def collect_slack_person_work(person_id: str, days: int = 14) -> dict:
        """Collect a person's messages and full threads from all visible conversations."""
        return collect_context(person_id, days)
    return server

if __name__ == "__main__":
    make_server().run(transport="stdio")
