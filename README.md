# Inferago Opportunity Intelligence (IOI) 3.0

An internal sales workspace for **Inferago Tech Services**. It finds **Chennai** businesses in two industries:

- **Equipment Sales & Service**: medical, lab, industrial, electrical and commercial equipment companies that install, repair and maintain.
- **Wholesale Distribution**: B2B distributors with repeat orders, stock and dispatch.

IOI checks each business against real sources and shows which facts are verified and which are guesses. It
prepares an outreach message for you to approve and then tracks the sale through to the payment you actually receive.

IOI **never contacts anyone by itself**. You copy the message and contact the business yourself.

---

## 1. Install

You need:

| | Version | Get it |
|---|---|---|
| Python | 3.11 or newer | https://www.python.org/downloads/ (Ubuntu: `sudo apt install python3 python3-venv`) |
| Node.js | 18 or newer | https://nodejs.org/ |
| uv (optional, faster) | any | https://docs.astral.sh/uv/ |

Then download the project folder. Nothing else needs to be installed by hand: the start script installs
the rest the first time it runs, which takes a few minutes.

## 2. Start

**Linux / macOS**

```bash
./start.sh
```

**Windows (PowerShell)**

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

The script checks Python and Node, installs packages if needed, updates the database safely, builds the
web app if anything changed, and starts IOI in the background. It prints the address to open.

> The Windows script was written for this release but has not been tested on a Windows machine yet.

## 3. Open the app

Open **http://127.0.0.1:8000** in your browser. The first time, a five-step setup wizard asks you to:

1. Confirm your business profile.
2. Confirm Chennai and the two industries.
3. Check which discovery sources are ready.
4. Optionally connect AI.
5. Optionally run a small first discovery.

If IOI is set to accept connections from other devices (`IOI_HOST=0.0.0.0` in `.env`), those devices are
asked for the access token (`IOI_API_TOKEN` in `.env`). The computer IOI runs on doesn't need it.

## 4. Sources (where businesses come from)

| Source | What it does | Cost |
|---|---|---|
| **Business directory** (Overture Maps open data) | Finds businesses: name, category, address, phone, website. Read from a local file. | Free |
| **Company websites** | Checks a few public pages per company: Chennai address, services, AMC/technicians, contacts, dated news. robots.txt is respected. | Free |
| **Chennai business news** (RSS from The Hindu, BusinessLine, ET) | Finds dated expansion, new-facility and technology news and matches it to companies. | Free |
| **CSV import** | Lists you are allowed to use, such as exhibitor or association lists. | Free |
| **Add business** | Anything you found yourself, such as a LinkedIn post or an IndiaMART page, with its link. | Free |
| **AI** (optional) | Deep research only, within your per-run limit. Every statement it keeps must be quoted word-for-word from the company's site. | Your OpenRouter/Anthropic account |

The directory file must be downloaded once (about 350 MB, 10–40 minutes): **Settings → Advanced →
Business directory file → Download**. Source health is shown in **Settings → Advanced**. A source is marked
"working" only after a real successful retrieval.

IOI does **not** read Google Maps, LinkedIn, JustDial or IndiaMART automatically, because their terms don't
allow it. Add those finds with **Prospects → Add business**.

To enable AI, put `IOI_OPENROUTER_API_KEY` and `IOI_OPENROUTER_MODEL` (or `IOI_ANTHROPIC_API_KEY`) in `.env`
and restart. Keys stay in `.env` and are never shown in the app.

## 5. Find businesses

Go to **Discover** and click **Start Discovery**. Choose a depth:

- **Quick**: directory only. Checks location and industry; visits no websites.
- **Balanced** (recommended): also reads news and researches the most promising websites.
- **Deep**: reads more pages per site and uses AI if it's configured.

You can watch each stage as it runs and leave the page meanwhile. **Stop** finishes the current item and
keeps everything already done. **Retry** reruns a run that failed or was interrupted, or only the sources that failed.

## 6. Review prospects

Go to **Prospects**. The tabs are:

- **Ready to Review**: passed every check. Up to your daily limit, 5 by default.
- **High-Fit**: P0 and P1.
- **Watchlist**: relevant, but needs one more check or a buying signal.
- **All Businesses**.

Open a business to see what it does, why it fits, every source with its date, and the suggested offer:
ServiceFlow, OrderFlow, Integration Fix or Small Automation. Each fact is labelled:

- **Verified**: seen in a source you can open.
- **Hypothesis**: IOI's guess, to check with the buyer.
- **Buyer confirmed**: the buyer told you.
- **Unknown**: IOI doesn't know.

Signals that IOI detects stay *unconfirmed* until you read the source and click **Confirm**.

| Category | Meaning |
|---|---|
| P0 Confirmed opportunity | Passes every check **and** has a need you confirmed, or that the buyer told you |
| P1 High-fit prospect | Passes every check and has a recent trigger, such as a new service centre or expansion |
| P2 Watchlist | Relevant, but limited evidence so far |
| P3 Excluded | Outside Chennai, wrong industry, inactive, duplicate or rejected |

The score (out of 100) only ranks businesses within a category and never overrides the checks.

## 7. Approve and contact

On a prospect, edit the message if you want, then click **Approve for Outreach**. Approval is only possible
once every check has passed.

In **Outreach**: **Copy message** → contact them yourself → **Mark as contacted** → **Record reply** →
**Schedule follow-up**. An interested buyer moves to **Sales Pipeline**, where you record proposals and payments.

Only payments you record count as collected revenue. Estimates and quotes are shown separately.

## 8. Stop

```bash
./stop.sh                     # Windows: .\stop.ps1
```

A running discovery stops gracefully, and completed work is already saved.

## 9. Back up and export

- **Settings → Data → Back up now** makes a full, integrity-checked copy in `backend/data/backups/`.
- **Settings → Data → Export prospects (CSV)**.
- **Legacy archive**: records from earlier IOI versions (about 340,000 all-India records). They are kept,
  read-only and exportable as CSV, and never loaded into the active campaign.
- **Start a new campaign** archives the current one and starts empty. Nothing is deleted.

**Restore a backup:** run `./stop.sh`, copy the backup over `backend/data/ioi.db`, delete
`backend/data/ioi.db-wal` and `ioi.db-shm` if present, then run `./start.sh`.

**Roll back the code:** `git checkout v2.5-chennai` (the Chennai version before 3.0) or `git checkout v2-final`
(the version before the Chennai refocus), then restore the matching database backup.

## 10. Troubleshooting

| Problem | Fix |
|---|---|
| "IOI server is not reachable" in the browser | Run `./start.sh`. If it still fails, read `backend/data/ioi.log`. |
| "Port 8000 is used by another program" | Change `IOI_PORT` in `.env`. |
| Discover says the business directory file is missing | Settings → Advanced → Download directory file. |
| A source shows "failing" | Settings → Advanced shows the last error. Feeds and websites sometimes block or time out; use **Retry failed sources**. |
| "Can't approve yet" | The prospect page lists the missing checks. Use **Research further**, or add the evidence yourself. |
| A company website "could not be loaded" | Some sites block automated readers or are down. Check by hand; if the address is right, use **Correct details → I checked the Chennai address here**. |
| Asked for a token | Paste `IOI_API_TOKEN` from `.env`. |

## For developers

```bash
scripts/test.sh                          # everything: backend tests, migration check, typecheck, unit tests, build, browser E2E
cd backend && uv run pytest -q           # backend only (no live network)
cd frontend && npm test                  # component tests (Vitest)
cd frontend && npm run e2e               # Playwright acceptance test on a separate server + throwaway database
scripts/dev.sh                           # backend :8000 + Vite dev server :5173 with hot reload
```

See `docs/ARCHITECTURE.md` and `docs/BUILD_STATUS.md`.
