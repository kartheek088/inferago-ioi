"""Researching a social seller from what is publicly readable, plus what the owner saw themselves.

What IOI can read automatically: the seller's own website, a published catalogue or order-form page,
and public market/exhibitor or business-feature pages. All of it through SafeHttp (SSRF guard,
robots.txt, size and time limits, per-host rate limit) and the shared page cache.

What IOI cannot read: Instagram and Facebook profiles. Those are served only to signed-in clients and
their robots.txt restricts automated access, so there is no code path that fetches them. Instead the
seller's page is marked "open it yourself" and `record_observation` lets the owner store what they
saw — their words, with the date they saw it. That is slower but it is the honest route.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app import chennai, lead_rules
from app.db import utcnow
from app.http_client import FetchError, SafeHttp
from app.ioi3.fetch import RETRY_AFTER, CachedHttp, Stats, classify_error, is_network_outage, with_retry
from app.ioi3.models import Campaign, Company
from app.ioi3.social import categories as cat
from app.ioi3.social import core
from app.ioi3.social import geo as geomod
from app.ioi3.social import platforms as plat
from app.normalize import html_to_text

MAX_PAGES = 4
MAX_PAGES_DEEP = 7

# Pages worth reading on a small seller's own site.
_WANTED = re.compile(r"(about|shop|order|catalog|catalogue|product|menu|price|contact|faq|deliver|policy|custom)", re.I)

# Some hosts (Google Sites, Notion, Facebook's "business" pages) redirect an anonymous visitor to a
# sign-in screen and return HTTP 200. That page is not the seller's content: reading it would record
# the login provider's text and contact details as if the business had published them.
_AUTH_HOSTS = ("accounts.google.com", "login.microsoftonline.com", "login.live.com", "appleid.apple.com",
               "auth0.com", "okta.com", "login.yahoo.com", "signin.aws.amazon.com")
_AUTH_PATH = re.compile(r"/(?:signin|sign-in|login|log-in|auth|accounts)(?:/|$|\?)", re.I)
_AUTH_TEXT = re.compile(r"\b(sign in to continue|to continue to|use your google account|"
                        r"enter your (?:email|password)|forgot (?:email|password)\?|create account)\b", re.I)


def login_wall(final_url: str, text: str) -> str | None:
    """A plain reason if this response is a sign-in screen rather than the seller's page."""
    from urllib.parse import urlsplit

    host = (urlsplit(final_url).hostname or "").lower().removeprefix("www.")
    if host.endswith(_AUTH_HOSTS):
        return f"the page redirected to a sign-in screen on {host}"
    if _AUTH_PATH.search(urlsplit(final_url).path) and _AUTH_TEXT.search(text[:3000]):
        return "the page is a sign-in screen"
    if len(text.strip()) < 1200 and len(_AUTH_TEXT.findall(text[:3000])) >= 2:
        return "the page asks visitors to sign in before showing anything"
    return None

# Hypotheses, clearly labelled as such — never presented as a known problem.
HYPOTHESES = {
    cat.FASHION: [("variant_tracking", "May benefit from one list of orders with size and colour, instead of scrolling DMs")],
    cat.GIFTS: [("spec_capture", "May benefit from capturing the customisation and reference photo with the order")],
    cat.BAKERY: [("date_capacity", "May benefit from a per-day view of what has to be made and delivered")],
    cat.MEALS: [("subscription_count", "May benefit from a daily delivery count and a record of who paused")],
    cat.OTHER: [("order_list", "May benefit from a single list of pending orders and their payment status")],
}


def readable_targets(c: Company) -> list[str]:
    """Public URLs IOI may fetch for this seller, most useful first."""
    out: list[str] = []
    if c.website:
        out.append(c.website if c.website.startswith("http") else f"https://{c.website}")
    for a in c.social_accounts:
        if a.catalogue_url:
            out.append(a.catalogue_url)
        if plat.FETCHABLE.get(a.platform) and a.url not in out:
            out.append(a.url)
    seen: set[str] = set()
    return [u for u in out if not (u in seen or seen.add(u))]


def blocked_accounts(c: Company) -> list[dict]:
    """Accounts a person has to open themselves, with the reason stated plainly."""
    return [{"platform": a.platform, "label": plat.PLATFORM_LABEL[a.platform], "handle": a.handle, "url": a.url,
             "why": ("Instagram serves profiles only to signed-in visitors and its robots.txt restricts automated "
                     "access, so IOI never fetches it. Open the profile and use 'Record what you saw'."
                     if a.platform == plat.INSTAGRAM else
                     "Facebook serves most pages only to signed-in visitors, so IOI never fetches it. "
                     "Open the page and use 'Record what you saw'." if a.platform == plat.FACEBOOK else
                     "WhatsApp is a messaging app, not a public directory. IOI never opens chats.")}
            for a in c.social_accounts if not plat.FETCHABLE.get(a.platform)]


# ------------------------------------------------------------------------------------------------
# Network phase (no database held open)
# ------------------------------------------------------------------------------------------------
def gather(http_like, targets: list[str], *, deep: bool) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Fetch what is allowed. Returns (pages, errors); a page is (url, html, text)."""
    pages: list[tuple[str, str, str]] = []
    errors: list[str] = []
    budget = MAX_PAGES_DEEP if deep else MAX_PAGES
    queue = list(targets)
    visited: set[str] = set()
    while queue and len(pages) < budget:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        try:
            res = http_like.get(url)
        except FetchError as exc:
            errors.append(f"{url}: {exc}")
            continue
        if "html" not in (res.content_type or "html").lower():
            errors.append(f"{url}: not a web page")
            continue
        html = res.text
        text = html_to_text(html)
        wall = login_wall(res.url, text)
        if wall:
            # Never record a login provider's page as the seller's own content.
            errors.append(f"{url}: needs a sign-in — {wall}")
            continue
        pages.append((res.url, html, text))
        if len(pages) == 1:  # follow a few useful internal links from the first page only
            from urllib.parse import urljoin, urlsplit

            host = (urlsplit(res.url).hostname or "").lower()
            for href in re.findall(r"<a\b[^>]*href=[\"']([^\"'#]+)[\"']", html, re.I)[:200]:
                nxt = urljoin(res.url, href.strip())
                if (urlsplit(nxt).hostname or "").lower() == host and _WANTED.search(nxt) and nxt not in visited:
                    queue.append(nxt)
    return pages, errors


def research_seller(db: Session, c: Company, http: SafeHttp, *, deep: bool = False, use_cache: bool = True,
                    stats: Stats | None = None, ai_calls_left: int = 0) -> int:
    """Research one seller now. Returns AI calls used. Caller commits."""
    targets = readable_targets(c)
    if not targets:
        return apply_result(db, c, [], ["no_readable_pages"], deep=deep)
    db.commit()  # never hold a transaction across network I/O
    pages, errors = gather(CachedHttp(http, stats, use_cache=use_cache), targets, deep=deep)
    return apply_result(db, c, pages, errors, deep=deep, ai_calls_left=ai_calls_left)


def research_many(db: Session, sellers: list[Company], *, deep: bool = False, workers: int = 4,
                  use_cache: bool = True, ai_calls_left: int = 0, on_done: Callable[[Company], None] | None = None,
                  should_stop: Callable[[], bool] | None = None, stats: Stats | None = None) -> dict[str, Any]:
    """Research several sellers with bounded concurrency; results commit one at a time as they arrive."""
    stats = stats or Stats()
    db.commit()
    by_id = {c.id: c for c in sellers}
    todo: list[tuple[int, list[str]]] = []
    out = {"researched": 0, "failed": 0, "nothing_readable": 0, "ai_calls": 0, "cancelled": 0, "network_outage": False}
    for c in sellers:
        targets = readable_targets(c)
        if targets:
            todo.append((c.id, targets))
        else:
            with_retry(lambda c=c: _apply_commit(db, c, [], ["no_readable_pages"], deep, 0))
            out["nothing_readable"] += 1
            if on_done:
                on_done(c)
    local = threading.local()
    clients: list[SafeHttp] = []
    lock = threading.Lock()
    outage = threading.Event()
    net = {"ok": 0, "down": 0}

    def work(cid: int, targets: list[str]):
        if outage.is_set() or (should_stop and should_stop()):
            return cid, [], ["__cancelled__"]
        h = getattr(local, "http", None)
        if h is None:
            h = local.http = SafeHttp(rate_limit_per_minute=20)
            with lock:
                clients.append(h)
        pages, errors = gather(CachedHttp(h, stats, use_cache=use_cache), targets, deep=deep)
        with lock:
            if pages:
                net["ok"] += 1
            elif any(is_network_outage(e) for e in errors):
                net["down"] += 1
                if net["down"] >= 3 and net["ok"] == 0:
                    outage.set()
        return cid, pages, errors

    ex = ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="ioi3-social")
    try:
        futures = [ex.submit(work, cid, t) for cid, t in todo]
        for fut in as_completed(futures):
            cid, pages, errors = fut.result()
            if errors and errors[0] == "__cancelled__":
                out["cancelled"] += 1
                continue
            c = by_id[cid]
            left = max(0, ai_calls_left - out["ai_calls"])
            used = with_retry(lambda c=c, pages=pages, errors=errors, left=left:
                              _apply_commit(db, c, pages, errors, deep, left))
            out["ai_calls"] += used
            out["failed" if (c.social and c.social.research_error) else "researched"] += 1
            if outage.is_set():
                out["network_outage"] = True
            if on_done:
                on_done(c)
            if outage.is_set() or (should_stop and should_stop()):
                for f in futures:
                    f.cancel()
    finally:
        ex.shutdown(wait=True, cancel_futures=True)
        for h in clients:
            h.close()
    return {**out, **stats.as_dict()}


def _apply_commit(db: Session, c: Company, pages, errors, deep: bool, ai_left: int) -> int:
    try:
        used = apply_result(db, c, pages, errors, deep=deep, ai_calls_left=ai_left)
        db.commit()
        return used
    except Exception:
        db.rollback()
        raise


# ------------------------------------------------------------------------------------------------
# Database phase: turn fetched pages into labelled evidence
# ------------------------------------------------------------------------------------------------
def apply_result(db: Session, c: Company, pages: list[tuple[str, str, str]], errors: list[str], *,
                 deep: bool = False, ai_calls_left: int = 0) -> int:
    now = utcnow()
    p = core.ensure_profile(c)
    p.researched_at = now
    p.pages_checked = [u for u, _, _ in pages][:12]

    if not pages:
        if errors and errors[0] == "no_readable_pages":
            blocked = blocked_accounts(c)
            p.research_error = ("Nothing can be read automatically for this seller"
                                + (f": {blocked[0]['label']} has to be opened by a person. "
                                   "Use 'Record what you saw' after opening it." if blocked else
                                   ". Add their website or catalogue link."))
            p.research_error_kind = "permanent"
            p.research_retry_after = None
        elif errors and all("needs a sign-in" in e for e in errors):
            p.research_error = ("Their page is behind a sign-in screen, so IOI cannot read it "
                                f"({errors[0].split('needs a sign-in — ')[-1]}). Open it yourself and use "
                                "'Record what you saw', or add a different public link.")
            p.research_error_kind = "permanent"
            p.research_retry_after = None
        else:
            kind, plain = classify_error(errors[0] if errors else "unknown error")
            p.research_error = f"Their pages could not be loaded: {plain}"
            p.research_error_kind = kind
            p.research_retry_after = now + (RETRY_AFTER["outage"] if any(is_network_outage(e) for e in errors)
                                            else RETRY_AFTER[kind])
        p.research_level = p.research_level or "profile"
        core.evaluate(c, now)
        return 0

    p.research_error = p.research_error_kind = None
    p.research_retry_after = None
    text = "\n".join(t for _, _, t in pages)
    first_url = pages[0][0]
    src = "Their own website"

    # Location, from pages the business itself publishes.
    camp = db.get(Campaign, c.campaign_id)
    approved_localities = (core.campaign_settings(camp).get("approved_localities") if camp else []) or []
    ev: list[geomod.GeoEvidence] = []
    if p.geo_basis in ("owner", "profile_location") and p.geo_excerpt:
        ev.append(geomod.GeoEvidence(p.geo_basis, p.geo_excerpt, p.geo_evidence_url))
    for url, _, t in pages:
        found = chennai.find_chennai_address(t, approved_localities)
        if found:
            ev.append(geomod.GeoEvidence("official_site", found[1], url, found[1]))
        m = re.search(r"(?:deliver(?:y|ing|ies)?|serving|service\s+area|pickup|pick[- ]up)[^.\n]{0,120}", t, re.I)
        if m and re.search(r"chennai|madras", m.group(0), re.I):
            ev.append(geomod.GeoEvidence("delivery_area", m.group(0), url, m.group(0)[:300]))
    # Keep whatever the owner already recorded (never silently dropped).
    for f in c.facts:
        if f.kind == "note" and f.key == "owner_location" and f.excerpt:
            ev.append(geomod.GeoEvidence("owner", f.excerpt, f.source_url))
    if ev:
        verdict = geomod.classify(ev, approved=approved_localities)
        # Never downgrade a verified location on the strength of a page that simply did not repeat it.
        if verdict.confidence != geomod.UNCLEAR or p.geo_confidence == geomod.UNCLEAR:
            core.set_geo(c, verdict)

    # What they sell
    if not p.product_category:
        match = cat.classify_category(c.name, text[:4000])
        if match.category:
            p.product_category, p.category_reasons, p.products_excerpt = match.category, match.reasons, match.excerpt

    # Order complexity, with the words that triggered each one
    keys = set(p.complexity_keys or [])
    for url, _, t in pages:
        for f in cat.detect_complexity(t, url):
            if f.key not in keys:
                keys.add(f.key)
            core.add_fact(c, kind="workflow", key=f.key, state="source_verified", statement=f.label,
                          excerpt=f.excerpt, source_url=url, source_name=src, reliability="high")
    p.complexity_keys = sorted(keys)

    # Dated public activity
    for url, _, t in pages:
        for s in cat.detect_signals(t, url):
            pos = t.find(s.excerpt[:40])
            when = lead_rules.find_date_near(t, max(pos, 0), max(pos, 0) + len(s.excerpt)) if pos >= 0 else None
            core.add_activity(c, signal_type=s.key, statement=s.label, url=url, indicator_class=s.indicator_class,
                              excerpt=s.excerpt, published_at=when, source_name=src, reliability="medium",
                              review_status="hypothesis")
    # A dated page at all is evidence the site is maintained.
    recent = _newest_date(pages, now)
    if recent:
        core.add_activity(c, signal_type="site_dated_content", statement=f"Their site shows dated content from {recent[0]:%d %b %Y}",
                          url=recent[1], indicator_class="activity", excerpt=recent[2], published_at=recent[0],
                          source_name=src, reliability="medium", review_status="confirmed")
        c.activity = "active"
    else:
        c.activity = "likely_active" if c.activity != "active" else c.activity

    # Public business contacts published on their own pages
    emails = {m.group(0) for _, _, t in pages for m in re.finditer(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", t)}
    for e in sorted(emails)[:3]:
        if not e.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            core.add_contact(c, kind="email", value=e, source_url=first_url, official=True)
    for _, _, t in pages:
        for m in re.finditer(r"(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}\b", t):
            ph = plat.normalise_phone(m.group(0))
            if ph:
                core.add_contact(c, kind="phone", value=f"+91{ph}", source_url=first_url, official=True)
    for url, html, _ in pages:
        if re.search(r"<form\b", html, re.I) and re.search(r"order|enquir|inquir|contact|book", url + html[:20000], re.I):
            core.add_contact(c, kind="contact_form", value=url, source_url=url, official=True, label="Order/enquiry form")
            break

    # How they sell today, and what it does not cover
    setup = cat.classify_setup(platforms={a.platform for a in c.social_accounts}, website_text=text,
                               website=c.website, catalogue_url=next((a.catalogue_url for a in c.social_accounts
                                                                      if a.catalogue_url), None),
                               bio_text=next((a.bio_excerpt for a in c.social_accounts if a.bio_excerpt), None))
    p.sales_setup, p.sales_setup_reason = setup.setup, setup.reason
    p.order_channels, p.workflow_gaps, p.known_tools = setup.order_channels, setup.gaps, setup.tools
    for t_name in setup.tools:
        core.add_fact(c, kind="tools", key=t_name, state="source_verified",
                      statement=f"Their pages mention '{t_name}'", source_url=first_url, source_name=src,
                      reliability="low")

    # Hypotheses, labelled
    for key, statement in HYPOTHESES.get(p.product_category or cat.OTHER, []):
        core.add_fact(c, kind="problem", key=key, state="inferred", statement=statement, detected_by="rule")

    ai_used = 0
    if deep and ai_calls_left > 0:
        ai_used = _ai_locate(db, c, pages)

    p.research_level = "deep" if deep else "public"
    c.last_verified_at = now
    if errors:
        p.research_error = None  # some pages loaded; failures are recorded per page, not as a seller-level error
        core.add_fact(c, kind="note", key="pages_failed", state="unknown",
                      statement=f"{len(errors)} page(s) could not be read: " + "; ".join(e[:120] for e in errors[:2]),
                      source_url=first_url, source_name=src)
    c.prescore = core.prescore(c)
    core.evaluate(c, now)
    return ai_used


def _newest_date(pages: list[tuple[str, str, str]], now: datetime) -> tuple[datetime, str, str] | None:
    best: tuple[datetime, str, str] | None = None
    for url, _, t in pages:
        for rx, conv in lead_rules._DATE_RX:
            for m in rx.finditer(t):
                try:
                    d = conv(m)
                except ValueError:
                    continue
                if timedelta(0) <= now - d <= timedelta(days=548) and (best is None or d > best[0]):
                    best = (d, url, lead_rules._excerpt(t, m, 60))
    return best


def _ai_locate(db: Session, c: Company, pages: list[tuple[str, str, str]]) -> int:
    """Deep mode: AI proposes operational statements; kept only with a verbatim quote from a page."""
    from pydantic import BaseModel

    from app.ai.extraction import quote_in
    from app.ai.openrouter import get_ai

    class Item(BaseModel):
        statement: str
        quote: str

    class Out(BaseModel):
        items: list[Item] = []

    ai = get_ai(db)
    if ai is None:
        return 0
    instruction = ("From this small seller's own pages, list up to 5 concrete things about HOW they take and fulfil "
                   "orders (customisation, sizes, advance payment, deadlines, delivery, subscriptions, returns). "
                   "For each give a short statement and an exact verbatim quote from the text. Do not guess; skip "
                   "anything the text does not state. Never infer revenue, order volume or budget.")
    text = "\n".join(t for _, _, t in pages)
    try:
        out = ai.complete_json("social_workflow", instruction, text[:12000], Out, max_tokens=700)
    except Exception:  # noqa: BLE001 — AI is optional; research continues without it
        return 1
    for it in out.items[:5]:
        for url, _, page_text in pages:
            if it.quote and len(it.quote) > 15 and quote_in(it.quote, page_text):
                core.add_fact(c, kind="workflow", key="ai_workflow", state="source_verified",
                              statement=it.statement[:300], excerpt=it.quote[:600], source_url=url,
                              source_name="Their own pages (AI-located, quote checked)", detected_by="ai",
                              reliability="medium")
                break
    return 1


# ------------------------------------------------------------------------------------------------
# What the owner saw themselves (the legitimate route for Instagram / Facebook)
# ------------------------------------------------------------------------------------------------
def record_observation(db: Session, c: Company, data: dict[str, Any], actor: str = "owner") -> Company:
    """Store what a person saw on a profile IOI cannot read. Their words, with the date they saw it."""
    p = core.ensure_profile(c)
    now = utcnow()
    platform = (data.get("platform") or "").strip() or None
    acc = next((a for a in c.social_accounts if a.platform == platform), None) or \
        next((a for a in c.social_accounts if a.is_primary), None)
    url = (data.get("url") or (acc.url if acc else c.source_url))
    notes = (data.get("notes") or "").strip()
    last_post = data.get("last_post_at")
    if isinstance(last_post, str) and last_post:
        try:
            last_post = datetime.fromisoformat(last_post[:19])
        except ValueError:
            last_post = None
    elif not isinstance(last_post, datetime):
        last_post = None

    if acc is not None:
        if notes:
            acc.bio_excerpt = notes[:2000]
        if last_post:
            acc.last_post_at = last_post
        if data.get("followers") not in (None, ""):
            try:  # recorded because the profile states it; never used in scoring
                acc.followers = int(data["followers"])
            except (TypeError, ValueError):
                pass
        if data.get("account_kind") in ("business", "creator", "page", "personal"):
            acc.account_kind = data["account_kind"]
        if data.get("catalogue_url"):
            acc.catalogue_url = str(data["catalogue_url"])[:2048]
        acc.observed_at = now
        acc.reachable = "public"

    if notes:
        core.add_fact(c, kind="activity", key="owner_observation", state="source_verified",
                      statement=f"You checked their {plat.PLATFORM_LABEL.get(platform or '', 'profile')} on {now:%d %b %Y}",
                      excerpt=notes[:1500], source_url=url, source_name="Checked by you", detected_by="owner",
                      reliability="high")
        # Run the same rules over what the owner typed.
        found_keys = set(p.complexity_keys or [])
        for f in cat.detect_complexity(notes, url):
            found_keys.add(f.key)
            core.add_fact(c, kind="workflow", key=f.key, state="source_verified", statement=f.label,
                          excerpt=f.excerpt, source_url=url, source_name="Checked by you", detected_by="owner",
                          reliability="high")
        p.complexity_keys = sorted(found_keys)
        for s in cat.detect_signals(notes, url):
            core.add_activity(c, signal_type=s.key, statement=s.label, url=url, indicator_class=s.indicator_class,
                              excerpt=s.excerpt, published_at=last_post, platform=platform,
                              source_name="Checked by you", detected_by="owner", review_status="confirmed")
        if not p.product_category:
            match = cat.classify_category(c.name, notes)
            if match.category:
                p.product_category, p.category_reasons = match.category, match.reasons

    if last_post:
        core.add_activity(c, signal_type="latest_post", statement=f"Their latest post is dated {last_post:%d %b %Y}",
                          url=url, indicator_class="activity", published_at=last_post, platform=platform,
                          source_name="Checked by you", detected_by="owner", review_status="confirmed",
                          reliability="high")
        c.activity = "active" if (now - last_post).days <= 90 else c.activity

    # Location the owner confirms, with the words they saw.
    for basis in ("profile_location", "delivery_area", "pickup_point", "event_listing"):
        if data.get(basis):
            core.add_fact(c, kind="note", key="owner_location", state="source_verified",
                          statement=f"You recorded their {geomod.BASES[basis][1]}", excerpt=str(data[basis])[:300],
                          source_url=url, source_name="Checked by you", detected_by="owner")
    ev = [geomod.GeoEvidence(b, str(data[b]), url) for b in
          ("profile_location", "delivery_area", "pickup_point", "event_listing", "owner") if data.get(b)]
    if ev:
        camp = db.get(Campaign, c.campaign_id)
        approved = (core.campaign_settings(camp).get("approved_localities") if camp else []) or []
        core.set_geo(c, geomod.classify(ev, approved=approved))

    if data.get("confirmed_problem"):
        core.add_fact(c, kind="problem", key="buyer_confirmed", state="buyer_confirmed",
                      statement=str(data["confirmed_problem"])[:1000], source_url=url,
                      source_name="The seller told you", detected_by="buyer", reliability="high")

    if p.research_level == "profile":
        p.research_level = "public"
    p.researched_at = now
    p.research_error = p.research_error_kind = None
    p.research_retry_after = None
    c.last_verified_at = now
    c.prescore = core.prescore(c)
    core.evaluate(c, now)
    db.commit()
    return c
