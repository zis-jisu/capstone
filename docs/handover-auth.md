# LINK-ing handover: verified user authentication

## Current environments

- `HANDOVER_AUTH_MODE=demo` (default): browser account switch and simulated YubiKey; **not secure**. Keep for presentation only.
- `HANDOVER_AUTH_MODE=verified`: Supabase Auth email/password login is mandatory. Backend verifies each user access token using Supabase Auth `/auth/v1/user`. The browser sends it as `X-Handover-Access-Token` because Railway Basic Auth already owns the Authorization header.
- Do not enable `verified` until Supabase Auth users have been provisioned with trusted `app_metadata` and email confirmation/login has been tested. At the time of implementation, `auth.users` had zero accounts.

## Account provisioning (performed by an administrator)

Create or invite **separate** Supabase Auth users. Set their trusted **app_metadata**, not editable user_metadata:

| Selected account | app_metadata values |
| --- | --- |
| 원이정 | `{"team":"marketing","person_id":"U0C20G9MRML","role":"employee"}` |
| 김지수 | `{"team":"marketing","person_id":"U0C22C8M742","role":"employee"}` |
| 팀장 | `{"team":"marketing","person_id":"<actual manager Slack ID>","role":"manager"}` |

Use real user-specific emails and passwords, **never a shared demo password** as the identity factor. Keep `SUPABASE_KEY` secret on Railway. No auth token or password should be written to the repository.

After account creation and successful authentication, set `HANDOVER_AUTH_MODE=verified` on the Railway `linking-web` service.

## Behavior under verified mode

1. GET `/api/demo/data` verifies the user token. A regular recipient sees only Works with an approved request addressed to their `person_id`; without approval they receive empty `works/tasks/events/edges` and no raw messages.
2. GET `/api/demo/handover-requests` returns only requests involving the authenticated user; team managers see the supported team request scope.
3. POST requests require that the authenticated user is the requester.
4. Decisions require the source person or a team manager. The asserted actor ID is checked against verified identity, except for the designated manager display identifier.
5. The simulated YubiKey is still **not** a cryptographic authentication device. Supabase Auth establishes identity, and the demonstration button records an approval.
6. Signing out clears the in-memory access token and fetched Work dataset.

## Security limitations and deployment review

- The Railway HTTP Basic demo gate is still in place as an additional website password, not personal authorization.
- `/api/demo/data` continues to serve legacy demonstration data in `demo` mode; do not treat this as production data security.
- The older Supabase public tables were found with RLS disabled; review RLS policies before exposing any sensitive data. Do not enable RLS without policies in production without evaluating impact.
- This rollout does not automatically create real user accounts or change team affiliation records.
- Before production, add automated authorization tests, a complete session refresh/revocation strategy, and resource-specific permissions for additional people and Works.
