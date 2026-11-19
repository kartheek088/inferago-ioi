# Security & compliance

## Access control
- Binds to `127.0.0.1` by default. Without `IOI_API_TOKEN`, the API accepts **loopback clients
  only** (403 otherwise). `/api/health` is the only public endpoint.
- With `IOI_API_TOKEN`, every request needs `Authorization: Bearer <token>` (constant-time compare).
- `python -m app.main` **refuses to start** on a non-loopback host without a token.
- Requests carrying proxy headers (X-Forwarded-For, Forwarded, X-Real-IP, Tailscale headers) are never treated as local — a token is required behind any reverse proxy.
- CORS limited to the configured local frontend origins.
- Before any network deployment: set a long random token, put it behind HTTPS (reverse proxy),
  and restrict by firewall/VPN. There is a single shared token — no per-user accounts in V1.

## Outbound requests (`app/http_client.py`)
- http/https only; credentials in URLs rejected; ports limited to 80/443/8080/8443.
- Every hop (including redirects, max 3) is DNS-resolved and rejected if any address is
  private, loopback, link-local (e.g. 169.254.169.254), multicast, reserved or unspecified.
- Timeouts (15 s), streaming response-size cap (5 MB), per-host rate limiting.
- robots.txt checked before fetching web pages (APIs that are designed for programmatic use are
  exempt). 401/403 robots → disallow all.
- Known limitation: DNS is resolved for validation and again by httpx (DNS-rebinding window).
  Acceptable for a local single-user tool; pin resolved IPs before exposing to untrusted users.

## Untrusted content
- Scraped text and AI output are data only: never executed, never used as instructions.
- AI prompts wrap collected text in `<data>` tags with a system guard; outputs are validated by
  Pydantic schemas and fall back to deterministic logic on failure.
- React escapes all rendered text; external links open with `rel="noopener noreferrer nofollow"`
  and only for http(s) URLs.
- Uploaded documents: size-limited (20 MB), stored under `backend/data/uploads/` with a hashed
  name, parsed only (never executed).

## Secrets
- Read from environment / `.env` (git-ignored). `.env.example` contains no secrets.
- API keys are never stored in the database or returned by the API.

## Compliance rules enforced by design
- No CAPTCHA or paywall bypass; CAPTCHA portals (TN e-Procurement, CPPP, GeM) are manual import.
- No private-channel scraping; Discord only via an authorised bot (not implemented).
- No LinkedIn / freelance-marketplace automation.
- No automatic email, calls, tender submission, vendor registration or commitments — every
  outbound draft requires a recorded human approval, and the human sends it.
- Contacts are only public business routes with their source URL; personal webmail addresses
  found on company sites are skipped; no guessed emails.
- Personal data minimised: no user lists, no profile harvesting.
