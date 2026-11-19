# Setup

Tested on Linux with Python 3.12, uv 0.x, Node 26 / npm. Python ≥ 3.11 and Node ≥ 18 should work.

## 1. Install

```bash
cd inferago-ioi
scripts/setup.sh
```

This copies `.env.example` → `.env` (if missing), runs `uv sync` and `alembic upgrade head` in
`backend/`, and `npm install` in `frontend/`.

## 2. Configure (`.env` in the repo root)

| Variable | Default | Notes |
|---|---|---|
| `IOI_HOST` / `IOI_PORT` | `127.0.0.1` / `8000` | Non-loopback host **requires** `IOI_API_TOKEN` (server refuses to start). |
| `IOI_API_TOKEN` | empty | If set, every API call needs `Authorization: Bearer …`. Enter it in UI → Settings. |
| `IOI_DATABASE_URL` | `sqlite:///backend/data/ioi.db` | Absolute path recommended if you move things. |
| `IOI_SCHEDULER_ENABLED` | `false` | Opt-in periodic collection (see OPERATIONS.md). |
| `IOI_OPENROUTER_API_KEY`, `IOI_OPENROUTER_MODEL` | empty | Both required to enable AI. Pick a model your account can use. |
| `IOI_REDDIT_CLIENT_ID/SECRET/USER_AGENT` | empty | All three required for the Reddit adapter. |
| `IOI_HTTP_TIMEOUT_SECONDS`, `IOI_HTTP_MAX_BYTES` | 15 / 5 MB | Outbound fetch limits. |

## 3. Run

```bash
scripts/dev.sh
# or separately:
cd backend && uv run python -m app.main      # applies migrations, then serves 127.0.0.1:8000
cd frontend && npm run dev                    # http://127.0.0.1:5173 (proxies /api)
```

Production-style frontend: `cd frontend && npm run build && npm run preview` (port 4173, proxies /api).

## 4. Verify

```bash
scripts/test.sh
curl http://127.0.0.1:8000/api/health
```

## 5. Optional demo fixtures

```bash
cd backend && uv run python ../scripts/seed_demo.py           # 3 records titled [DEMO], DEMO badge in UI
cd backend && uv run python ../scripts/seed_demo.py --remove
```

## Database migrations

```bash
cd backend
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "describe change"   # after editing models.py
uv run alembic check                                          # fails if models and migrations drift
```
