# Operations

## Daily workflow

1. **Discover** → run Hacker News (and any enabled RSS feeds). Import tender PDFs/DOCX you
   downloaded from TN e-Procurement / CPPP / GeM. Paste interesting public URLs.
2. **Opportunities** → sort by priority; filter by pipeline, country, eligibility.
3. **Research Queue** → *Run research batch* (shortlists top 50 above min priority, deep-researches
   up to 20 within budgets) or research one opportunity from its page.
4. Review **Eligibility** (clarification questions) and **Opportunity Chains** (confirm/reject
   hypotheses — only confirmed relationships score).
5. **Outreach** → generate draft → edit → submit → approve (your name is recorded) → send it
   yourself → *Mark sent manually* (creates a follow-up).
6. **Follow-ups** → create call tasks (needs an approved draft), record outcomes; follow-ups are
   generated automatically per outcome.

## Scheduler (opt-in)

```bash
IOI_SCHEDULER_ENABLED=true   # in .env, then restart backend
```
On the Sources page tick **enabled** and **scheduled**. Jobs run every
`collection_frequency_minutes` (min 15) with `max_instances=1`, `coalesce=True`. A run is skipped
if another run for the same source is in progress; runs stuck > 2 h are marked failed. Shutdown
(Ctrl+C) stops the scheduler and waits for running jobs. Scheduled state: Settings → Runtime.

## Monitoring

- Sources page: last checked / last success / failure status / consecutive failures; per-run logs.
- Overview: recent runs, enabled source health.
- `GET /api/activity` — audit trail of every change and approval.
- `ai_usage_logs` table — AI calls, tokens, cost, latency, errors.

## Backups

SQLite file: `backend/data/ioi.db` (+ `-wal`/`-shm` while running). Back up with the server
stopped, or use `sqlite3 backend/data/ioi.db ".backup backup.db"`. Uploaded documents live in
`backend/data/uploads/`.

## Resetting

Stop the backend, delete `backend/data/ioi.db*`, start again (migrations + source seeding run on
start). Demo fixtures: `scripts/seed_demo.py [--remove]`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| 403 from API | You are not on loopback and no token is configured — set `IOI_API_TOKEN`. |
| 401 from API | Enter the token in UI → Settings. |
| Run `skipped` | Another run for that source is in progress. |
| Reddit can't be enabled | Set all three `IOI_REDDIT_*` variables and restart. |
| Document "needs manual review" | Scanned PDF — read it manually and add requirements on the opportunity's Eligibility tab. |
