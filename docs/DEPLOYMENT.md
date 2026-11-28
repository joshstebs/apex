# Deploying ApexVoice outside Vercel

Vercel is unavailable for this account, so the supported targets are, in order:

1. An existing Oracle Cloud Free Tier instance (container + Cloudflare Tunnel).
2. Render (Docker service with a persistent disk).
3. Cloudflare Workers — not recommended yet; see the caveat at the end.
4. Vercel, once access is restored.

The application does not assume a specific host. `config.is_serverless_runtime()`
identifies runtimes whose filesystem is discarded between requests, and
`config.is_hosted_runtime()` covers every real deployment. Everything else is
driven by which store is configured, so a container behaves correctly.

## Storage choice: this decides whether a call can start

`try_acquire_call_slot` only admits a call when `settings.durable_storage_usable()`
is true, and `/api/health` reports the result as `durable_storage_configured`.

| Setup | Durable? | Notes |
| --- | --- | --- |
| Upstash Redis REST credentials | Yes | Required on Vercel. Recommended everywhere. |
| Turso HTTP SQLite credentials | Yes | Supported for local/container use. |
| Container + mounted volume, no Redis | Yes | SQLite at `DB_PATH` survives restarts. |
| Container with no volume | **No** | State is lost on redeploy. Health reports false. |
| Serverless with no remote store | **No** | Admission is refused by design. |

Using Upstash is still preferred even on a container: it keeps call state,
the active-call lock, budget accounting, the pause flag and the TTS audio cache
in one place, so a restart cannot strand a live call's lease.

## Oracle Cloud Free Tier

Inspect the instance before deploying; do not disturb existing applications.

```sh
ssh <instance>
nproc; free -h; df -h /; docker --version || podman --version
ss -ltnp | sort -k4        # what ports are already bound
```

ApexVoice at idle needs very little: one Python process plus one SQLite file.
Choose a free port (the examples use 8100) that nothing else has bound.

```sh
git clone https://github.com/joshstebs/apex.git ~/apexvoice && cd ~/apexvoice

docker build -t apexvoice:local .

docker run -d --name apexvoice \
  --restart unless-stopped \
  -p 127.0.0.1:8100:8000 \
  -v apexvoice-data:/data \
  --env-file /etc/apexvoice.env \
  apexvoice:local

curl -fsS http://127.0.0.1:8100/api/health
```

Bind to `127.0.0.1` and publish the app through Cloudflare Tunnel rather than
opening an inbound port. `--forwarded-allow-ips *` in the image lets
`X-Forwarded-Proto`/`Host` rebuild the public URL that webhook signatures are
verified against.

Copy `.env.example` to `/etc/apexvoice.env` (mode `600`) and fill it in. Keep
`APEX_HOSTED=1` and `APEX_ENVIRONMENT=staging` until the checks below pass.

### Cloudflare Tunnel

```sh
cloudflared tunnel login
cloudflared tunnel create apexvoice
cloudflared tunnel route dns apexvoice apex-staging.example.com
```

`~/.cloudflared/config.yml`:

```yaml
tunnel: apexvoice
credentials-file: /home/<user>/.cloudflared/<tunnel-id>.json
ingress:
  - hostname: apex-staging.example.com
    service: http://127.0.0.1:8100
  - service: http_status:404
```

```sh
sudo cloudflared service install
```

Then set `PUBLIC_URL=https://apex-staging.example.com`. That exact hostname is
what SignalWire signs, so it must match the URL configured on the number.

The tunnel gives HTTPS without opening inbound ports. It does not add
authentication: protect the admin APIs with `APEX_ADMIN_TOKEN`, and use
Cloudflare Access only if it will not block provider webhook POSTs.

## Render

`render.yaml` in this repository defines a Docker web service with a 1 GB disk
mounted at `/data`. `plan: starter` is a **paid** instance; nothing is
provisioned automatically. `autoDeploy` is off so a merge cannot silently
deploy. Free-tier Render instances sleep when idle, which is unsuitable for a
receptionist that must answer on the first ring.

## Cloudflare Workers caveat

The `port/cloudflare-workers` branch deploys with the Python Workers toolchain,
but it is not a drop-in target:

- SQLite is unavailable, so Upstash (or Turso) must be configured for any state.
- Subrequest limits and CPU limits make multi-turn audio callbacks risky.
- Exit-stream/system calls used by counterfactual checks are unsupported.

It is kept as an experiment. Prefer Oracle or Render.

## Verifying a deployment

```sh
BASE=https://apex-staging.example.com

curl -fsS $BASE/api/health            # durable_storage_configured must be true
curl -s -o /dev/null -w '%{http_code}\n' -X POST $BASE/webhooks/signalwire/voice  # 403: unsigned
```

Staging refuses live calls by design. With `APEX_ENVIRONMENT=staging` the app
answers every call attempt with a hangup message and cannot spend money. Use
`POST /api/staging/exercise` with the admin token to run the in-process
receptionist drill (no provider traffic).

Only after that, and only with explicit approval, set `RECEPTIONIST_ENABLED=true`
and `APEX_ENVIRONMENT=production`. Outbound calling stays disabled in code.
