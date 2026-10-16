# Security review follow-ups

The 2026-10-16 white-box review produced 19 findings. 17 are fixed on `master`
(see the `fix:`/`harden` commits tagged F1 through F19). Two are deliberately
left for a session with the stack running, because they change how the api and
the MCP server authenticate to each other, and a mistake there breaks all
email. Both are LOW severity. The residual notes below record what each shipped
fix intentionally did not cover.

## Deferred (need the MCP server running to test)

### F10. Attachment fetch is not tied to the requesting user
`app/api.py` `_get_owned_attachment(file_id, user_id=None)` skips the owner
check on the internal path, and `mcp-server/mcp_launcher/server.py`
`_resolve_attachment_ids` presents only `x-internal-secret`, no user id. So a
send with any valid `file_id` fetches it regardless of who uploaded it. Low,
because ids are random UUID4s that live one hour and are shown to no one, so it
needs a second leak to be exploitable.

Plan (both repos, then rebuild the mcp image):
1. `app/common.py`: when the agent invokes `send_email`/`draft_email`/
   `reply_to_email`, pass the current `user_id` to MCP in a short-lived signed
   token header, next to the tokens it already sends.
2. `mcp-server`: forward that token on the `GET /attachment/{file_id}` call.
3. `app/api.py`: on the internal path, verify the token and call
   `_get_owned_attachment(file_id, that_user_id)` instead of `None`.
Cheaper interim: accept only ids uploaded in the current thread.

### F16. Token encryption design
`app/common.py` and `mcp-server/common/__init__.py` hold two copies of the same
Fernet code. `decrypt_payload` is called with no `ttl`, one un-versioned
`ENCRYPTION_KEY` covers OAuth tokens and users' own API keys, and MCP treats any
decryptable blob as proof of identity. Low: needs a captured blob plus a
foothold on the Docker network (mcp publishes no port).

Plan:
1. Add `ttl` ONLY to the short-lived blobs passed in MCP request headers, and
   re-encrypt on each refresh. Do NOT add ttl to the long-lived refresh tokens
   stored in Mongo, or every stored login breaks.
2. Store a key id next to each ciphertext so the key can be rotated.
3. Share one crypto module between app and mcp-server.
4. Authenticate callers to MCP with a shared-secret header, the way the
   `/attachment` route already does.

## Residuals left by the shipped fixes

- F6: sessions are still pickled by `starlette_session` 0.4.3. The password and
  network split remove the exploit preconditions; moving sessions off pickle
  (or to signed cookies) is the full fix.
- F9: `read_only` was not added to api/scheduler/frontend (only non-root +
  `cap_drop`). It needs a live check that each still starts and writes only to
  tmpfs.
- F4: uvicorn `--forwarded-allow-ips` stays `*`. The port is loopback-only and
  nginx overwrites `X-Forwarded-For`, so it is not internet-exploitable; pinning
  the docker gateway IP risks breaking real client-IP detection.
- F8: a nonce-less fallback CSP in `next.config` headers would cover skipped
  asset paths and the Next 404 page; verify header interaction on a frontend run.
- F12: own-key `/agent` users still have no daily or concurrency ceiling (only
  the 10/min burst). A per-user Redis concurrency cap is the remaining piece.
