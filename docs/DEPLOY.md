# Running locally vs hosting

## Default: fully local

- Data lives in `backend/data/ioi.db` (SQLite) and `backend/data/uploads/` on your machine.
- The server binds to `127.0.0.1`; with no `IOI_API_TOKEN` it only answers requests from this machine.
- The only outbound traffic is to the sources you run (Hacker News, n8n/Make forums, pages you
  import) and to OpenRouter when AI is enabled.
- Limitation: the laptop must be on for discovery / the scheduler to run.

Single-process mode (no Vite needed): `cd frontend && npm run build`, then
`cd backend && uv run python -m app.main` and open http://127.0.0.1:8000 — the backend serves the
built UI and the API on one port.

## Option A — access from your phone/other laptop privately (recommended next step)

Use [Tailscale](https://tailscale.com) (free for personal use): only devices signed into your
Tailscale account can reach it; nothing is exposed to the public internet.

1. Install Tailscale on the laptop and phone, sign in to the same account.
2. Set a token in `.env` (required — proxied requests are never treated as local):
   `IOI_API_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")`
3. Build the UI once: `cd frontend && npm run build`; start: `cd backend && uv run python -m app.main`.
4. `tailscale serve --bg 8000` → open the printed `https://<laptop>.<tailnet>.ts.net` URL on your phone.
5. In the UI → Settings, paste the token (stored only in that browser).

## Option B — always-on server (VPS)

Suitable when you want scheduled discovery 24/7 without the laptop. Any small Linux VM
(1 vCPU / 1–2 GB RAM) is enough. Avoid hosts with ephemeral disks (SQLite needs persistent storage).

```bash
# on the server (Ubuntu)
git clone <your private repo> inferago-ioi && cd inferago-ioi
scripts/setup.sh && (cd frontend && npm run build)
# .env: IOI_API_TOKEN=<long random>, IOI_HOST=127.0.0.1, IOI_SCHEDULER_ENABLED=true, OpenRouter vars
```

`/etc/systemd/system/ioi.service`:
```ini
[Unit]
Description=Inferago IOI
After=network-online.target

[Service]
WorkingDirectory=/home/ioi/inferago-ioi/backend
ExecStart=/home/ioi/.local/bin/uv run python -m app.main
Restart=on-failure
User=ioi

[Install]
WantedBy=multi-user.target
```

HTTPS with Caddy (`/etc/caddy/Caddyfile`), keeping the app on 127.0.0.1:
```
ioi.yourdomain.in {
    reverse_proxy 127.0.0.1:8000
}
```

Security checklist before exposing it:
- `IOI_API_TOKEN` set (long, random). Without it, requests arriving through a proxy are refused (403).
- HTTPS only (Caddy does this automatically); firewall allows only 80/443 (+ SSH).
- Keep the repository private; `.env` is git-ignored — copy it to the server manually.
- Single shared token, no per-user accounts (fine for you alone; not for a team).
- Back up `backend/data/` daily (`sqlite3 backend/data/ioi.db ".backup /backups/ioi-$(date +%F).db"`).
- Set `IOI_CORS_ORIGINS=https://ioi.yourdomain.in` if you ever serve the UI from a different origin.
