"""Website Recovery: low-impact health checks of a business's OWN website.

Rules (CLAUDE.md, brief sections 5 and 15):
- Only the company's own URL is requested, through SafeHttp (SSRF guard, robots.txt, rate limit, size cap).
- One GET per check. No port scans, directory guesses, logins, CAPTCHA/WAF evasion or retry loops.
- A single observation never confirms an outage. A hard failure becomes `unhealthy_confirmed` only when the
  same failure is seen again at least `min_confirm_hours` later.
- Bot challenges, 403/429, our own network timeouts and policy blocks are never reported as outages.
- Only classifications, status codes and short error text are stored. Page HTML is never persisted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal, utcnow
from app.http_client import BlockedURLError, FetchError, RobotsDisallowedError, SafeHttp
from app.ioi3 import fetch
from app.ioi3.models import B2B, Company, WebsiteCheck

MAX_PER_RUN = 25

# Overall statuses shown to the owner (brief section 5).
STATUSES = (
    "healthy", "unhealthy_confirmed", "unhealthy_suspected", "redirected_to_active_site",
    "migrated_to_storefront", "access_restricted", "network_failure", "unknown",
)
# Specific failures seen in one check (kept as `observed_class`).
OBSERVED_FAILURES = (
    "not_found", "server_error", "domain_expired_or_unresolved", "tls_problem", "placeholder_or_parked",
)
HARD_FAILURES = frozenset(OBSERVED_FAILURES)

# Directory and social hosts are not a company's own website: never checked as one.
NOT_OWN_SITE = (
    "instagram.com", "facebook.com", "fb.com", "wa.me", "whatsapp.com", "linktr.ee", "youtube.com",
    "linkedin.com", "justdial.com", "indiamart.com", "sulekha.com", "google.com", "maps.app.goo.gl",
)
# Hosts that mean the business moved its commerce to a marketplace or hosted store.
STOREFRONT_HOSTS = (
    "indiamart.com", "justdial.com", "myshopify.com", "shopify.com", "dukaan.in", "mydukaan.io",
    "wixsite.com", "squarespace.com", "wordpress.com", "instamojo.com",
)

# Bot-challenge detection. Real validation (2026-11-26) showed working sites with a captcha on their contact form
# ("captcha" in a CSS class or a WordPress plugin path), so generic words count only on a near-empty page, while
# these challenge-page signatures count anywhere.
CHALLENGE_MARKS = ("cf-chl", "checking your browser", "attention required! | cloudflare", "<title>just a moment",
                   "lsrecaptcha", "ddos-guard")
WEAK_CHALLENGE_MARKS = ("captcha", "access denied", "ddos protection")
CHALLENGE_PAGE_MAX_TEXT = 600

# Public DNS-over-HTTPS resolvers, used only after a local DNS failure, to tell "the domain is gone" from
# "our DNS is broken". Only the business's domain name is sent.
DOH_RESOLVERS = (("cloudflare", "https://cloudflare-dns.com/dns-query"), ("google", "https://dns.google/resolve"))
PLACEHOLDER_MARKS = ("this domain is for sale", "buy this domain", "domain parking", "parked free", "sedo.com",
                     "hugedomains", "default web site page", "welcome to nginx", "apache2 ubuntu default page",
                     "plesk default page", "web server's default page", "it works!")
SUSPENDED_MARKS = ("account suspended", "this account has been suspended", "website suspended", "site suspended")
UNDER_CONSTRUCTION_MARKS = ("under construction", "coming soon")
MAINTENANCE_MARKS = ("under maintenance", "scheduled maintenance", "temporarily unavailable")
SOFT_404_MARKS = ("page not found", "404 not found", "oops! that page can't be found")

_SCRIPT = re.compile(r"<(script|style)\b.*?</\1>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


@dataclass
class Observation:
    """What one request showed. `html` is kept in memory only, never stored."""

    url: str
    dns: str = "ok"  # ok | unresolved | policy_blocked
    http_status: int | None = None
    final_url: str | None = None
    error_kind: str | None = None  # timeout | refused | tls | robots | other
    error_text: str | None = None
    html: str = ""  # lowercased raw HTML, first 64 KB, in memory only
    body: str = ""  # lowercased visible text, in memory only
    independent_dns: dict[str, str] = field(default_factory=dict)  # resolver -> nxdomain | resolves | no_answer | error
    checked_at: datetime = field(default_factory=utcnow)


@dataclass
class Verdict:
    status: str
    observed_class: str | None = None
    confidence: str = "low"
    reasons: list[str] = field(default_factory=list)
    tls_result: str | None = None


def host_of(url: str) -> str:
    h = (urlsplit(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def is_own_site(url: str) -> bool:
    h = host_of(url)
    return bool(h) and not any(h == d or h.endswith("." + d) for d in NOT_OWN_SITE)


def normalise_url(website: str) -> str:
    w = website.strip()
    return w if w.lower().startswith(("http://", "https://")) else f"https://{w}"


def _has(text: str, marks: tuple[str, ...]) -> bool:
    return any(m in text for m in marks)


def _hard(observed: str, reasons: list[str], confidence: str) -> Verdict:
    # Every hard failure starts as suspected. Only a repeat confirms it (see `confirm`).
    return Verdict("unhealthy_suspected", observed, confidence, reasons)


def classify(obs: Observation) -> Verdict:
    """Deterministic classification of one observation. No I/O, no DB."""
    if obs.dns == "policy_blocked":
        return Verdict("unknown", None, "low", ["Address refused by the safety policy; this says nothing about the website"])
    if obs.error_kind == "robots":
        return Verdict("access_restricted", None, "high", ["robots.txt disallows an automated check of this page"])
    if obs.error_kind == "timeout":
        return Verdict("network_failure", None, "low", ["Timed out. Could be our connection or the site; not counted as a website failure"])
    if obs.error_kind == "tls":
        return Verdict("unhealthy_suspected", "tls_problem", "medium", ["TLS/certificate problem on HTTPS"], tls_result="problem")
    if obs.dns == "unresolved":
        ind = obs.independent_dns
        resolves = [r for r, v in ind.items() if v == "resolves"]
        if resolves:
            return Verdict("network_failure", None, "medium",
                           [f"Did not resolve here but resolves via {', '.join(resolves)}: a local DNS problem, not a website failure"])
        nx = [r for r, v in ind.items() if v == "nxdomain"]
        if len(nx) >= 2:
            return _hard("domain_expired_or_unresolved",
                         [f"Domain does not exist (NXDOMAIN) here and at {len(nx)} independent public resolvers ({', '.join(nx)})"], "medium")
        return _hard("domain_expired_or_unresolved",
                     ["Domain did not resolve from this machine; independent resolvers could not confirm it"], "low")
    if obs.error_kind == "refused":
        return _hard("server_error", ["Connection refused by the server"], "medium")
    if obs.error_kind == "other":
        return Verdict("unknown", None, "low", [f"Could not verify: {obs.error_text or 'unclassified network error'}"])

    code = obs.http_status
    if code is None:
        return Verdict("unknown", None, "low", ["No HTTP status recorded"])
    tls_ok = "ok" if obs.url.lower().startswith("https://") else None
    challenge = _has(obs.html, CHALLENGE_MARKS) or (
        len(obs.body) < CHALLENGE_PAGE_MAX_TEXT and _has(obs.html, WEAK_CHALLENGE_MARKS))
    if code in (403, 429) or challenge:
        what = f"HTTP {code}" if code in (403, 429) else f"Bot-challenge page (HTTP {code})"
        return Verdict("access_restricted", None, "high",
                       [f"{what}: access restricted, not evidence of an outage"], tls_result=tls_ok)
    if code in (404, 410):
        return _hard("not_found", [f"HTTP {code}"], "medium")
    if code >= 500:
        return _hard("server_error", [f"HTTP {code}"], "medium")
    if code >= 400:
        return Verdict("unknown", None, "low", [f"HTTP {code}: could not verify"])

    if _has(obs.html, PLACEHOLDER_MARKS):
        return _hard("placeholder_or_parked", ["Hosting, parking or default server page is shown"], "medium")
    if _has(obs.html, SUSPENDED_MARKS):
        return _hard("placeholder_or_parked", ["Account suspended notice is shown"], "medium")
    if _has(obs.html, UNDER_CONSTRUCTION_MARKS) and len(obs.body) < 600:
        return _hard("placeholder_or_parked", ["Under-construction page is shown"], "low")
    if _has(obs.html, MAINTENANCE_MARKS) and len(obs.body) < 600:
        return Verdict("unknown", None, "low", ["Maintenance page; recheck later"], tls_result=tls_ok)

    if obs.final_url and host_of(obs.final_url) and host_of(obs.final_url) != host_of(obs.url):
        dest = host_of(obs.final_url)
        if any(dest == s or dest.endswith("." + s) or s in dest for s in STOREFRONT_HOSTS):
            return Verdict("migrated_to_storefront", None, "high", [f"Redirects to a storefront ({dest})"], tls_result=tls_ok)
        return Verdict("redirected_to_active_site", None, "medium",
                       [f"Redirects to another domain ({dest}); confirm it belongs to the business"], tls_result=tls_ok)

    if _has(obs.html, SOFT_404_MARKS) and len(obs.body) < 1500:
        return _hard("not_found", ["Soft 404: 'page not found' text on a 200 response"], "low")
    if len(obs.body) < 200:
        return Verdict("unknown", None, "low", ["Blank or near-empty page; could not verify"], tls_result=tls_ok)
    return Verdict("healthy", None, "high", [f"Business content served (HTTP {code})"], tls_result=tls_ok)


def confirm(v: Verdict, prior_seen_at: datetime | None, now: datetime, min_confirm_hours: float) -> Verdict:
    """Promote a suspected hard failure to confirmed only when the same failure was seen earlier, far enough back."""
    if v.status != "unhealthy_suspected" or v.observed_class is None:
        return v
    if prior_seen_at is not None and now - prior_seen_at >= timedelta(hours=min_confirm_hours):
        v.status = "unhealthy_confirmed"
        v.confidence = "high"
        v.reasons.append(f"Same failure seen again after at least {min_confirm_hours:g}h")
    else:
        v.reasons.append(f"Needs a repeat check at least {min_confirm_hours:g}h later before it is confirmed")
    return v


def _visible(html: str) -> str:
    return _WS.sub(" ", _TAG.sub(" ", _SCRIPT.sub(" ", html))).strip().lower()


def independent_dns(host: str, http: SafeHttp) -> dict[str, str]:
    """Ask public DNS-over-HTTPS resolvers about `host` (A record). Read-only, one query each."""
    out: dict[str, str] = {}
    for name, endpoint in DOH_RESOLVERS:
        try:
            res = http.get(endpoint, check_robots=False, headers={"accept": "application/dns-json"},
                           params={"name": host, "type": "A"})
            data = res.json()
            status = data.get("Status")
            if status == 3:
                out[name] = "nxdomain"
            elif status == 0 and data.get("Answer"):
                out[name] = "resolves"
            else:
                out[name] = "no_answer"
        except Exception:  # an unreachable resolver is simply no evidence either way
            out[name] = "error"
    return out


def probe(url: str, http: SafeHttp, *, check_independent_dns: bool = True) -> Observation:
    """One GET through SafeHttp (plus public DNS lookups only after a local DNS failure). No DB access."""
    obs = Observation(url=url)
    try:
        res = http._get_raw(url, check_robots=True)
    except RobotsDisallowedError as exc:
        obs.error_kind, obs.error_text = "robots", str(exc)[:300]
        return obs
    except BlockedURLError as exc:
        msg = str(exc)
        low = msg.lower()
        obs.error_text = msg[:300]
        if "could not resolve" in low or "did not resolve" in low:
            obs.dns = "unresolved"
            host = urlsplit(url).hostname
            if check_independent_dns and host:
                obs.independent_dns = independent_dns(host, http)
        else:
            obs.dns = "policy_blocked"
        return obs
    except FetchError as exc:
        msg = str(exc)
        low = msg.lower()
        obs.error_text = msg[:300]
        if "timeout" in low or "took longer" in low:
            obs.error_kind = "timeout"
        elif "certificate" in low or "ssl" in low:
            obs.error_kind = "tls"
        elif "connection refused" in low or "connection attempts failed" in low:
            obs.error_kind = "refused"
        else:
            obs.error_kind = "other"
        return obs
    obs.http_status = res.status_code
    obs.final_url = res.url
    raw = res.content[:65536].decode("utf-8", "replace") if res.content else ""
    obs.html = raw.lower()
    obs.body = _visible(raw)
    return obs


def _latest_ids():
    """Id of each company's most recent check (ids increase with time)."""
    return select(func.max(WebsiteCheck.id)).group_by(WebsiteCheck.company_id)


def candidates(db: Session, *, company_ids: list[int] | None, limit: int, force: bool, recheck_hours: float,
               now: datetime, min_confirm_hours: float = 24) -> tuple[list[tuple[int, str]], int]:
    """Companies with an own website that are due a check. Returns (todo, skipped_recently_checked).

    Order: suspected failures that are due their confirming recheck first, then never-checked sites, then the rest.
    """
    q = select(Company.id, Company.website).where(Company.channel == B2B, Company.website.is_not(None))
    if company_ids:
        q = q.where(Company.id.in_(company_ids))
    rows = [(cid, normalise_url(w)) for cid, w in db.execute(q.order_by(Company.id)).all() if w and is_own_site(normalise_url(w))]
    latest = {c.company_id: c for c in db.scalars(select(WebsiteCheck).where(WebsiteCheck.id.in_(_latest_ids())))}

    def rank(item: tuple[int, str]) -> int:
        chk = latest.get(item[0])
        if chk is None:
            return 1
        if chk.status == "unhealthy_suspected" and now - chk.checked_at >= timedelta(hours=min_confirm_hours):
            return 0
        return 2

    todo: list[tuple[int, str]] = []
    skipped = 0
    for cid, url in sorted(rows, key=rank):  # stable: keeps id order inside each group
        chk = latest.get(cid)
        if not force and chk is not None and now - chk.checked_at < timedelta(hours=recheck_hours):
            skipped += 1
            continue
        if len(todo) < limit:
            todo.append((cid, url))
    return todo, skipped


def _prior_seen(db: Session, company_id: int, observed: str) -> datetime | None:
    return db.execute(
        select(func.max(WebsiteCheck.checked_at)).where(
            WebsiteCheck.company_id == company_id,
            WebsiteCheck.observed_class == observed,
            WebsiteCheck.status.in_(("unhealthy_suspected", "unhealthy_confirmed")),
        )
    ).scalar()


def run_checks(db: Session, *, company_ids: list[int] | None = None, limit: int = 10, force: bool = False,
               recheck_hours: float = 24, min_confirm_hours: float = 24, http: SafeHttp | None = None,
               look_for_alternatives: bool = True) -> dict:
    """Check up to `limit` own-website URLs sequentially. Each DB write is its own short transaction.

    When a site fails, its own email domain / directory record is checked for a newer working site (≤ 3 GETs).
    """
    from app.ioi3 import recovery_intel  # local import: recovery_intel builds on this module

    limit = max(1, min(int(limit), MAX_PER_RUN))
    http = http or SafeHttp(respect_robots=True, rate_limit_per_minute=20, max_bytes=2_000_000)
    now = utcnow()
    todo, skipped = candidates(db, company_ids=company_ids, limit=limit, force=force, recheck_hours=recheck_hours,
                               now=now, min_confirm_hours=min_confirm_hours)
    db.rollback()  # no transaction stays open across the network calls below
    summary: dict = {"checked": 0, "skipped_recent": skipped, "failures_detected": 0, "confirmed": 0,
                     "network_failures": 0, "blocked_by_policy": 0, "access_restricted": 0, "errors": 0,
                     "independent_dns_lookups": 0, "alternatives_checked": 0, "alternatives_working": 0, "results": []}
    for cid, url in todo:
        try:
            obs = probe(url, http)
            verdict = classify(obs)
            if verdict.observed_class:
                with SessionLocal() as s:
                    prior = _prior_seen(s, cid, verdict.observed_class)
                verdict = confirm(verdict, prior, obs.checked_at, min_confirm_hours)

            def _write(s: Session, cid=cid, obs=obs, v=verdict) -> None:
                s.add(WebsiteCheck(
                    company_id=cid, website_url=url[:2048], checked_at=obs.checked_at,
                    dns_result=obs.dns, http_status=obs.http_status,
                    final_url=obs.final_url[:2048] if obs.final_url else None,
                    tls_result=v.tls_result, error_kind=obs.error_kind, error_text=obs.error_text,
                    observed_class=v.observed_class, status=v.status, confidence=v.confidence, reasons=v.reasons[:6],
                ))

            fetch.short_write(_write)
            if look_for_alternatives and verdict.status in ("unhealthy_suspected", "unhealthy_confirmed"):
                alts = recovery_intel.find_alternatives(cid, http)
                summary["alternatives_checked"] += len(alts)
                summary["alternatives_working"] += sum(1 for a in alts if a["status"] == "healthy")
        except Exception:  # one bad site must not stop the run; the error is counted, not hidden
            summary["errors"] += 1
            continue
        summary["checked"] += 1
        s = verdict.status
        if s in ("unhealthy_suspected", "unhealthy_confirmed"):
            summary["failures_detected"] += 1
        if s == "unhealthy_confirmed":
            summary["confirmed"] += 1
        if s == "network_failure":
            summary["network_failures"] += 1
        summary["independent_dns_lookups"] += len(obs.independent_dns)
        if s == "unknown" and obs.dns == "policy_blocked":
            summary["blocked_by_policy"] += 1
        if s == "access_restricted":
            summary["access_restricted"] += 1
        summary["results"].append({"company_id": cid, "status": s, "observed_class": verdict.observed_class})
    return summary


def overview(db: Session) -> dict:
    total_b2b = db.execute(select(func.count()).select_from(Company).where(Company.channel == B2B)).scalar() or 0
    with_site = sum(1 for cid, w in db.execute(select(Company.id, Company.website).where(
        Company.channel == B2B, Company.website.is_not(None))).all() if w and is_own_site(normalise_url(w)))
    checks_total = db.execute(select(func.count()).select_from(WebsiteCheck)).scalar() or 0
    latest_rows = db.execute(select(WebsiteCheck.status).where(WebsiteCheck.id.in_(_latest_ids()))).scalars().all()
    by_status = {s: 0 for s in STATUSES}
    for st in latest_rows:
        by_status[st] = by_status.get(st, 0) + 1
    return {
        "businesses_discovered": total_b2b,
        "with_own_website": with_site,
        "websites_checked": len(latest_rows),
        "checks_recorded": checks_total,
        "by_status": by_status,
        "failures_detected": by_status.get("unhealthy_suspected", 0) + by_status.get("unhealthy_confirmed", 0),
        "pending_confirmation": by_status.get("unhealthy_suspected", 0),
        "confirmed": by_status.get("unhealthy_confirmed", 0),
    }



def dossier(db: Session, company_id: int, limit: int = 20) -> dict | None:
    c = db.get(Company, company_id)
    if c is None or c.channel != B2B:
        return None
    hist = db.execute(select(WebsiteCheck).where(WebsiteCheck.company_id == company_id)
                      .order_by(WebsiteCheck.checked_at.desc()).limit(limit)).scalars().all()
    return {
        "company": {"id": c.id, "name": c.name, "locality": c.locality, "website": c.website},
        "checks": [{
            "checked_at": h.checked_at.isoformat(), "status": h.status, "observed_class": h.observed_class,
            "confidence": h.confidence, "dns": h.dns_result, "http_status": h.http_status,
            "final_url": h.final_url, "tls": h.tls_result, "error_kind": h.error_kind,
            "error_text": h.error_text, "reasons": h.reasons or [],
        } for h in hist],
    }
