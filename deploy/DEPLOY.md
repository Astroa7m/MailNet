# Deploying MailNet

Images are built on a workstation and pulled on the server. The server has ~1 GB
of RAM and cannot build the frontend without running itself out of memory and
disk, which is how it once locked up hard enough to refuse SSH.

## One time, before the first deploy of this release

### 1. Rotate the Azure client secret

The MCP server used to print decrypted Microsoft tokens, including refresh
tokens, to stdout on every Outlook call, and container logs were uncapped. Treat
every Microsoft token issued before this release as exposed.

In the Azure portal, under the app registration, create a new client secret,
then update `AZURE_SECRET_VALUE` in the server `.env`. Outlook users reconnect
their account once. Delete the old secret after the new one is confirmed working.

### 2. Add the two new secrets to the server `.env`

Both features fail closed without these. Attachments stop resolving and every
scheduled send is refused, so the values must be present before the stack comes
up.

```
INTERNAL_API_SECRET=<generate: python -c "import secrets;print(secrets.token_urlsafe(32))">
SCHEDULER_SECRET=<generate: python -c "import secrets;print(secrets.token_urlsafe(32))">
```

`INTERNAL_API_SECRET` lets the MCP server read attachment payloads now that the
route is scoped to its owner's session, and `SCHEDULER_SECRET` authenticates the
API to the scheduler, whose routes previously accepted any caller's claimed user
id. The api, scheduler, and mcp services all read the same `.env`, so one entry
each is enough.

### 2b. Avoid `$` in any `.env` value

Compose expands `$NAME` inside `.env` values and silently substitutes a blank
string, so a secret containing a dollar sign reaches the container shorter than
it is in the file. `CHAINLIT_AUTH_SECRET` is already affected locally, losing 10
characters. It is harmless today because Chainlit is only mounted when
`UI_PROVIDER=chainlit`, which is not how this deploys, but any future secret with
a `$` in it would be quietly weakened the same way.

Generate secrets with `python -c "import secrets;print(secrets.token_urlsafe(32))"`,
which emits only `A-Za-z0-9_-`, or escape a literal dollar sign as `$$`. Check a
value actually arrived intact with:

```
docker-compose exec api python -c "import os;print(len(os.getenv('SESSION_SECRET','')))"
```

### 3. Truncate the existing container logs

They hold live credentials from before the fix.

```
sudo find /var/lib/docker/containers -name '*-json.log' -exec truncate -s 0 {} +
```

### 4. Purge the legacy scheduled job

One job predates the ownership fix. It is owned by the literal `tester-user-001`
and carries Fernet-encrypted OAuth tokens in its kwargs. It now fails safely,
raising "no usable mail credentials" and recording the failure, but it should not
sit in the database.

```
mongosh "$MONGO_URI" --eval 'db.schedules.deleteMany({ "job_state.kwargs.user_id": "tester-user-001" })'
```

If the encoded job state does not match that path, list the collection first and
delete by `_id`.

### 5. Confirm Atlas network access

Under Network Access, `0.0.0.0/0` should be gone, leaving only the server's
elastic IP.

## Every deploy

Build and push from the workstation, never on the server:

```
docker build -f app/Dockerfile -t astroa7m/mailnet-api:latest .
docker tag astroa7m/mailnet-api:latest astroa7m/mailnet-scheduler:latest
docker build -t astroa7m/mailnet-mcp:latest ./mcp-server
docker build --build-arg NEXT_PUBLIC_API_URL=https://getmailnet.com \
  -t astroa7m/mailnet-frontend:latest ./frontend

for i in api scheduler mcp frontend; do docker push astroa7m/mailnet-$i:latest; done
```

`NEXT_PUBLIC_API_URL` is baked into the client bundle at build time, so the
server's runtime environment cannot correct it. Building without that argument
produces an image that points the browser at `http://localhost:8002` and fails
for every visitor.

On the server:

```
cd ~/MailNet
git pull
docker-compose pull
docker-compose down
docker-compose up -d --no-build
```

`--no-build` matters: without it compose rebuilds from source on the box.

## When nginx changes

`deploy/nginx.conf` is the authoritative copy. Apply it with:

```
sudo cp deploy/nginx.conf /etc/nginx/sites-available/mailnet
sudo nginx -t && sudo systemctl reload nginx
```

Every backend route needs a matching `location` entry. Anything missing falls
through to Next.js and returns a 404 that looks like a frontend bug, which is how
`/tester-request` once shipped broken.

## Verifying a deploy

```
curl -sS -o /dev/null -w '%{http_code}\n' https://getmailnet.com/
curl -sS -o /dev/null -w '%{http_code}\n' https://getmailnet.com/terms
curl -sS -o /dev/null -w '%{http_code}\n' https://getmailnet.com/privacy
curl -sS -o /dev/null -w '%{http_code}\n' https://getmailnet.com/attachment/does-not-exist   # expect 404
curl -sS -o /dev/null -w '%{http_code}\n' https://getmailnet.com/tz                          # expect 401
curl -sSI https://getmailnet.com/ | grep -i 'strict-transport\|x-content-type\|x-frame'
docker-compose logs --tail=30 scheduler
```

Signed in, confirm the Settings > Scheduled tab lists pending emails, that
scheduling one produces an approval card naming the recipient and time, and that
reopening an old thread renders the inbox list rather than "Could not parse email
results."
