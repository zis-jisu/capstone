# Slack Backend -> Frontend API

The team's existing backend lives in `src/`, and this adapter makes it callable by a browser frontend. This prototype uses server-held secrets and a demo-only bearer token.

## Quickstart (Windows CMD)

From `C:\Users\nicol\capstone-slack`:

```cmd
pip install -r requirements-api.txt
set SLACK_TOKEN=<Slack user OAuth token>
set OPENAI_API_KEY=<OpenAI API key>
set SUPABASE_URL=<Supabase project URL>
set SUPABASE_KEY=<backend-only Supabase key>
set API_ACCESS_TOKEN=<long random local dev token>
set FRONTEND_ORIGINS=http://localhost:3000,http://localhost:5173
python -m uvicorn src.frontend_api:app --host 127.0.0.1 --port 8000
```

Never commit credentials to GitHub. Do not embed `SUPABASE_KEY`, `SLACK_TOKEN` or `OPENAI_API_KEY` in frontend code. `API_ACCESS_TOKEN` is for local development only: browsers cannot keep long-lived bearer secrets private. Production deployment requires session auth and authorization restricting person/work visibility.

## Endpoints

| Verb | Path | Result |
|---|---|---|
| GET | `/api/health` | Server process health (no DB query) |
| GET | `/api/persons` | People from Supabase |
| GET | `/api/works` | Work list and associated Task counts |
| GET | `/api/works/{work_id}` | Work, Tasks, evidence Events (timeline), relations, Persons |
| POST | `/api/sync` | Start asynchronous Slack collection -> Event -> Task -> Work -> DB save -> Graph export |
| GET | `/api/sync/{job_id}` | Progress, success counts, or failure stage |

All endpoints except `/api/health` require `Authorization: Bearer <API_ACCESS_TOKEN>`.

POST payload: `{ "person_id": "U0C22C8M742", "days": 14 }`.

`POST /api/sync` returns HTTP 202 and `job_id`; poll `GET /api/sync/{job_id}`. Once completed, refresh `/api/works`. Only one sync job runs at a time. Artifacts are saved locally under `handover_runs/<job_id>/` (gitignored). The API uses the same source modules that produced the verified Supabase graph.

### Demo limitations / integration cautions

- Sync calls the shared MCP server's `collect_context` function **directly**. `mcp_server.py` additionally exposes this as an MCP tool, but the HTTP adapter does not use an MCP protocol client session.
- `GET /api/works/{work_id}` returns current DB-derived values, not an LLM-generated handover narrative. It provides Events for frontend timeline rendering.
- Graph JSON is written on the backend; there is no Graph ML inference endpoint in this package.
- REST DB writes are not transactional. A failed job after the save stage may have partially written data. Examine `handover_runs/<job_id>/` and the DB before retrying. Existing Event IDs from a different source mapping may produce duplicates.
- Job status is kept in process memory, so it is not persistent across restarts; run one Uvicorn worker for this demo.
- HTTP API is a prototype; do not expose it to the internet without production authentication/authorization, rate limits, and background job persistence.
