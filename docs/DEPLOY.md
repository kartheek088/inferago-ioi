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

## Option A — phone + laptop via Tailscale (set up)

Tailscale gives a private network between your own devices; nothing is exposed to the internet.

```bash
scripts/install-service.sh     # builds the UI, runs IOI as a systemd user service on 127.0.0.1:8000 (no sudo)
scripts/tailscale-setup.sh     # installs Tailscale, logs in (browser), publishes IOI over HTTPS to your tailnet (sudo)
scripts/device-link.sh         # prints a one-time link + QR code per device
```

- `.env` must contain `IOI_API_TOKEN` (generated already). Requests via Tailscale are proxied, so
  the token is always required.
- The device link is `https://<laptop>.<tailnet>.ts.net/#token=…`. The token is in the URL fragment,
  which browsers never send to the server; the app saves it in that browser and removes it from the
  address bar. Treat the link like a password.
- Phone: install the Tailscale app, sign in with the same account, open the link (scan the QR).
- The laptop must be on (and awake) for the phone to reach it.
- Service control: `systemctl --user status|restart|stop ioi`, logs `journalctl --user -u ioi -f`.
  After pulling new code: `scripts/install-service.sh` (rebuilds UI and restarts).
- Revoke access: change `IOI_API_TOKEN` in `.env`, `systemctl --user restart ioi`, re-run `device-link.sh`.
- Stop sharing: `tailscale serve reset`.

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
