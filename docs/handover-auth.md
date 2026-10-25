# LINK-ing Slack login and handover — deployed code

## Identity and storage

- `person_id` is the **same exact value** as Slack user ID (no second person ID).
- The existing `persons` table identifies users; there is **no Supabase Auth account requirement**.
- `handover_requests` stores requests and approved/rejected status only.
- `handover_assignments` is a legacy **admin Task assignment** table, not needed for this handover scenario. It is not deleted because the pre-existing admin assignments API still references it.
- No separate team-manager handover approval: only the actual owner, 김지수, can approve the WORK-00020 demo request by 원이정.

## Sign in with Slack (real identity)

Production requires a Slack application's **Sign in with Slack** OAuth / OpenID Connect settings. On Railway **linking-web** set:

- `SLACK_CLIENT_ID` (from the Slack app)
- `SLACK_CLIENT_SECRET` (keep secret, backend only)
- `SLACK_REDIRECT_URI` = `https://<YOUR-LINKING-WEB-DOMAIN>/api/demo/auth/slack/callback`
- `SLACK_WORKSPACE_TEAM_ID` (recommended: restrict to your BMW demo workspace)

Configure this same redirect URI in Slack App > OAuth & Permissions > Redirect URLs, with Sign in with Slack scopes `openid email profile`.

When all three required variables are present, the UI switches to Slack sign-in automatically; the backend checks Slack's OpenID userInfo response and ensures that the ID is registered in `persons` with Marketing team membership. A signed HttpOnly Secure cookie authenticates subsequent API requests. The backend verifies actual actor on request/approval, and hides Work/Task/Event messages until approved. The demo YubiKey touch is a visual effect, **not real cryptographic YubiKey validation**.

Until OAuth variables are configured, the existing `DEMO_USERNAME` / `DEMO_PASSWORD` site gate and local actor choice remain for presentation only. This is not secure user-specific authorization; don't present it as one.

## Known limitations

- The demo currently supports 원이정 → 김지수 and `WORK-00020`, not a generalized many-person workflow.
- Supabase existing `persons` rows must match the authenticated Slack IDs. Marketing users were verified in the database at implementation.
- There is no new required DB table beyond `handover_requests`; do not drop `handover_assignments` without removing or migrating the existing admin assignments API first.
- Existing pipeline DB tables have RLS disabled; audit them before a public production launch.
- User access is driven by a secure server-side cookie, not a user-supplied ID, only when real Slack OAuth is enabled.
