"""Smoke-test the exact collector exposed by the Slack MCP server."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.slack.mcp_server import collect_context

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("person_id")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--out", default="handover_runs/slack_mcp_context.json")
    args = parser.parse_args()
    result = collect_context(args.person_id, args.days)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Saved:", out)
    print("Messages:", len(result["records"]))
    print("People:", len(result["people"]))
    print("Matching channels:", result["metadata"]["matched_channels"])
    print("Warnings:", result["metadata"]["warnings"][:10])
    print("No LLM call. DB unchanged.")

if __name__ == "__main__":
    main()
