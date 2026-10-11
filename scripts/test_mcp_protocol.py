"""Verify real MCP stdio handshake, tool discovery, and Slack tool invocation.

Run: python scripts/test_mcp_protocol.py
Requires SLACK_TOKEN in the current terminal environment.
No LLM calls or DB writes.
"""
import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    if not os.getenv("SLACK_TOKEN"):
        raise SystemExit("SLACK_TOKEN is missing in this CMD session.")
    root = Path(__file__).resolve().parents[1]
    server = root / "src" / "slack" / "mcp_server.py"
    # -m ensures src is importable when the server runs as a child process.
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "src.slack.mcp_server"],
        cwd=str(root),
        env=dict(os.environ),
    )
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [item.name for item in tools.tools]
            print("MCP handshake: OK")
            print("Available tools:", ", ".join(names))
            assert "discover_slack_conversations" in names
            assert "collect_slack_person_work" in names
            result = await session.call_tool("discover_slack_conversations", {})
            if result.isError:
                raise RuntimeError("MCP tool returned an error: " + str(result.content))
            # Only metadata is printed. We never print message bodies or secrets.
            content = result.structuredContent
            if content is None:
                import json
                content = json.loads(result.content[0].text)
            channels = content if isinstance(content, list) else content.get("result", [])
            print("MCP tool call: OK")
            print("Discovered conversations:", len(channels))
            print("LLM calls: 0; DB writes: 0")


if __name__ == "__main__":
    asyncio.run(main())
