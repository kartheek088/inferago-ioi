"""Website Recovery intelligence: is the business still operating, did it move, can we reach it, should we call.

Brief sections 6-9. Rules:
- Activity needs DATED evidence. Undated listings never count. A call where the business itself answers is direct
  evidence; otherwise two independent dated sources are needed for `active_verified`.
- Owner observations (`method=manual`) and automatic facts are stored apart and shown apart.
- Instagram / Facebook / LinkedIn / marketplaces are never fetched. The owner opens them (search links) and records
  what they saw, with the URL and date.
- Contacts are business-level. A directory mobile number or free-mail address may belong to a person, so it is
  flagged for manual review and never passes the contact gate on its own.
- Qualification gates are explicit. Nothing becomes R1 with a failed gate, and a broken website is never intent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable
from urllib.parse import quote_plus, urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal, utcnow
from app.http_client import SafeHttp
from app.ioi3 import fetch
from app.ioi3 import website_recovery as wr
from app.ioi3.models import ActivityEvidence, AlternativeSite, Company, CompanyContact, ContactReview, RawItem, WebsiteCheck

# --- vocabularies ------------------------------------------------------------------------------

EVIDENCE_KINDS: dict[str, str] = {
    "phone_call": "Phone call with the business",
    "official_social": "The business's own social page",
    "marketplace_listing": "Marketplace listing (IndiaMART, Justdial, …)",
    "official_website": "The business's own (newer) website",
    "news": "News or association listing",
    "other": "Other public source",
    "confirmed_need": "Business confirmed it needs help",
}
DIRECT_KINDS = frozenset({"phone_call", "confirmed_need"})  # dated by when it happened, no URL needed
SIGNALS = ("active", "inactive", "closed")
ACTIVITY_STATUSES = ("active_verified", "active_probable", "activity_unclear", "inactive_suspected", "closed_verified")
WINDOWS = (30, 60, 90, 180)
DEFAULT_WINDOW = 90

FREE_MAIL = frozenset({
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "yahoo.in", "hotmail.com", "outlook.com", "live.com",
    "rediffmail.com", "icloud.com", "ymail.com", "protonmail.com", "aol.com", "zoho.com", "msn.com",
})

# Screens free-text notes: contacts live in ioi_contacts with provenance, never in notes.
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(?:\+?\d[\s-]?){10,}")


def has_contact_details(text: str) -> bool:
    return bool(_EMAIL_RE.search(text) or _PHONE_RE.search(text))


# --- activity ----------------------------------------------------------------------------------

def local_today() -> date:
    """Calendar 'today' on the owner's machine. Timestamps stay UTC, but a call made on 26 Nov in Chennai is dated
    26 Nov — using the UTC date would reject today's date as "future" before 05:30 IST."""
    return date.today()


@dataclass
class Ev:
    kind: str
    signal: str
    method: str
    published_on: date | None
    observed_on: date
    source_url: str | None = None


def evidence_date(e: Ev) -> date | None:
    """The date that counts for recency: when a call happened, or when the source published it. Never a crawl date."""
    return e.observed_on if e.kind in DIRECT_KINDS else e.published_on


def _source_key(e: Ev) -> tuple[str, str]:
    host = wr.host_of(e.source_url) if e.source_url else ""
    return (e.kind, host)


def classify_activity(evs: Iterable[Ev], today: date, window_days: int = DEFAULT_WINDOW) -> tuple[str, list[str]]:
    evs = list(evs)
    cutoff = today - timedelta(days=window_days)
    dated_active = [(e, evidence_date(e)) for e in evs if e.signal == "active" and evidence_date(e)]
    recent = [(e, d) for e, d in dated_active if cutoff <= d <= today]
    latest_active = max((d for _, d in dated_active), default=None)
    closed = [e for e in evs if e.signal == "closed"]
    latest_closed = max((e.observed_on for e in closed), default=None)

    if closed and (latest_active is None or latest_closed >= latest_active):
        if any(e.method == "manual" for e in closed):
            return "closed_verified", [f"Recorded as closed on {latest_closed}"]
        return "inactive_suspected", [f"A source reported it closed ({latest_closed}); not confirmed by the owner"]

    calls = sorted((d for e, d in recent if e.kind in DIRECT_KINDS), reverse=True)
    if calls:
        return "active_verified", [f"The business itself was reached on {calls[0]}"]
    sources = {_source_key(e) for e, _ in recent}
    if len(sources) >= 2:
        return "active_verified", [f"{len(sources)} independent dated sources in the last {window_days} days"]
    if len(sources) == 1:
        return "active_probable", [f"One dated source in the last {window_days} days; a second source or a call would verify it"]
    if any(e.signal == "inactive" for e in evs):
        return "inactive_suspected", ["A source suggests the business is inactive"]
    if latest_active is not None:
        return "inactive_suspected", [f"Latest dated activity is {latest_active}, older than {window_days} days"]
    undated = [e for e in evs if e.signal == "active" and evidence_date(e) is None]
    if undated:
        return "activity_unclear", [f"{len(undated)} undated item(s) — an undated listing is not proof of current operation"]
    return "activity_unclear", ["No dated evidence yet"]


# --- contacts ----------------------------------------------------------------------------------

def _national_digits(value: str) -> str:
    d = re.sub(r"\D", "", value)
    if len(d) == 12 and d.startswith("91"):
        return d[2:]
    if len(d) == 11 and d.startswith("0"):
        return d[1:]
    return d


def contact_view(c: CompanyContact, decision: str | None = None) -> dict[str, Any]:
    """Business-level contact route with a review flag. Nothing here is a person-level lookup.

    `decision` is the owner's review (approved | rejected). Approval clears a review flag; rejection always blocks.
    """
    review: str | None = None
    kind_label = c.kind
    if c.kind == "phone":
        n = _national_digits(c.value)
        mobile = len(n) == 10 and n[0] in "6789"
        if n.startswith("1800"):
            kind_label = "toll-free business line"
        elif mobile:
            kind_label = "mobile"
            if not c.official:
                review = "Mobile number from a directory — it may be a person's own number. Check before use."
        else:
            kind_label = "office landline"
        if len(n) < 10:
            review = "Number looks incomplete"
    elif c.kind == "email":
        domain = c.value.rsplit("@", 1)[-1].lower()
        if domain in FREE_MAIL and not c.official:
            kind_label = "free email address"
            review = "Free email address from a directory — it may be personal. Check before use."
        else:
            kind_label = "business email"
    elif c.kind == "contact_form":
        kind_label = "contact form"
    flagged = review is not None
    if decision == "approved":
        review = None
    elif decision == "rejected":
        review = "You marked this as not to be used"
    return {
        "id": c.id, "kind": c.kind, "kind_label": kind_label, "value": c.value, "label": c.label,
        "route": "official" if c.official else "directory", "source_url": c.source_url,
        "observed_at": c.observed_at.isoformat() if c.observed_at else None,
        "needs_review": review, "usable": review is None, "reviewable": flagged or decision is not None,
        "review": decision,
    }


# --- scope (owner setting) ---------------------------------------------------------------------

SCOPE_KEY = "recovery_scope"
UNCATEGORISED = "uncategorised"


def get_scope(db: Session) -> dict[str, Any]:
    from app.settings_store import get_setting

    s = get_setting(db, SCOPE_KEY) or {}
    w = s.get("window_days", DEFAULT_WINDOW)
    return {"categories": s.get("categories"), "window_days": w if w in WINDOWS else DEFAULT_WINDOW}


def category_of(c: Company) -> str:
    return c.directory_category or UNCATEGORISED


def in_scope(c: Company, scope: dict[str, Any], industries: Iterable[str]) -> tuple[bool, str]:
    if c.industry not in set(industries):
        return False, f"Industry '{c.industry or 'unclassified'}' is outside the campaign"
    cats = scope.get("categories")
    if cats is not None and category_of(c) not in cats:
        return False, f"'{category_of(c).replace('_', ' ')}' is not a target business type (Settings on this page)"
    return True, f"Target business type: {category_of(c).replace('_', ' ')}"


# --- qualification -----------------------------------------------------------------------------

FEASIBILITY = {
    "domain_expired_or_unresolved": "Domain has lapsed: re-register it if the business still owns it, or move to a new domain. Ownership must be checked first.",
    "tls_problem": "Certificate renewal or HTTPS configuration.",
    "server_error": "Hosting / server diagnosis, then restore.",
    "not_found": "Restore the site files or fix the hosting configuration.",
    "placeholder_or_parked": "Restore the site or the hosting account; check who controls the domain.",
}

# Dashboard buckets (brief section 15).
BUCKET_OF = {"R0": "high_priority", "R1": "high_priority", "R2": "needs_verification"}


def qualify(c: Company, *, latest: WebsiteCheck | None, activity: str, alt_healthy: list[str],
            contacts: list[dict[str, Any]], scope_ok: tuple[bool, str], confirmed_need: bool) -> dict[str, Any]:
    gates: list[dict[str, Any]] = []

    def gate(key: str, label: str, passed: bool, detail: str) -> None:
        gates.append({"key": key, "label": label, "passed": passed, "detail": detail})

    status = latest.status if latest else None
    gate("identity", "Credible business identity", c.review_status != "duplicate" and not c.is_test and not c.archived,
         "Marked duplicate or archived" if c.review_status == "duplicate" or c.archived else c.name)
    gate("geography", "Chennai location confirmed", c.location_confidence == "verified",
         "Chennai address verified" if c.location_confidence == "verified"
         else "Chennai per directory only — confirm on the call (tick 'confirmed Chennai address')")
    gate("scope", "Target business type", scope_ok[0], scope_ok[1])
    gate("failure", "Website failure confirmed", status == "unhealthy_confirmed",
         {"unhealthy_confirmed": "Same failure seen on two checks ≥ 24 h apart",
          "unhealthy_suspected": "One failed check so far — the recheck confirms it"}.get(status or "", f"Website status: {status or 'not checked'}"))
    gate("operating", "Business currently operating", activity == "active_verified",
         {"active_verified": "Verified", "active_probable": "Probable — one more source or a call needed",
          "closed_verified": "Recorded as closed"}.get(activity, "Not verified — call them or check their own pages"))
    replaced = bool(alt_healthy) or status in ("redirected_to_active_site", "migrated_to_storefront")
    gate("replacement", "No working replacement site", not replaced,
         f"Working site found: {', '.join(alt_healthy)}" if alt_healthy
         else ("Old address redirects to a working site" if replaced else "None found"))
    usable = [x for x in contacts if x["usable"]]
    gate("contact", "Legitimate business contact route", bool(usable),
         f"{len(usable)} usable business contact(s)" if usable
         else ("Only contacts that need review" if contacts else "No business contact on file"))
    observed = latest.observed_class if latest else None
    gate("feasible", "Inferago can help", True, FEASIBILITY.get(observed or "", "Diagnose first, then the smallest fix"))

    friction: list[str] = ["Existing web vendor: unknown", "Who controls the domain and hosting: unknown"]
    if observed == "domain_expired_or_unresolved":
        friction.append("Domain lapsed — ownership may need recovering")

    failed = [g for g in gates if not g["passed"]]
    if not gates[0]["passed"]:
        cat, bucket, why = "R3", "excluded", "Not a credible business record"
    elif activity == "closed_verified":
        cat, bucket, why = "R3", "excluded", "Business recorded as closed"
    elif not scope_ok[0]:
        cat, bucket, why = "R3", "excluded", scope_ok[1]
    elif replaced:
        cat, bucket, why = "R3", "migrated", "Has a working website or storefront — no recovery pitch"
    elif status == "healthy":
        cat, bucket, why = "R3", "excluded", "Website is working"
    elif confirmed_need:
        cat, bucket, why = "R0", "high_priority", "The business confirmed it needs help"
    elif not failed:
        cat, bucket, why = "R1", "high_priority", "All gates pass. Buying intent is still unconfirmed — ask, don't assume"
    else:
        cat, bucket, why = "R2", "needs_verification", "Still to check: " + "; ".join(g["label"] for g in failed)
    return {"category": cat, "bucket": bucket, "summary": why, "gates": gates, "friction": friction}


def manual_check_links(c: Company) -> list[dict[str, str]]:
    """Searches the OWNER opens in their own browser. IOI never fetches these sites."""
    q = f'"{c.name}"'
    loc = " Chennai"
    return [
        {"label": "Google", "url": "https://www.google.com/search?q=" + quote_plus(q + loc)},
        {"label": "Facebook page", "url": "https://www.google.com/search?q=" + quote_plus(q + loc + " site:facebook.com")},
        {"label": "Instagram", "url": "https://www.google.com/search?q=" + quote_plus(q + " site:instagram.com")},
        {"label": "IndiaMART", "url": "https://www.google.com/search?q=" + quote_plus(q + " site:indiamart.com")},
        {"label": "Justdial", "url": "https://www.google.com/search?q=" + quote_plus(q + " site:justdial.com")},
    ]


# --- loading -----------------------------------------------------------------------------------

def to_ev(e: ActivityEvidence) -> Ev:
    return Ev(e.kind, e.signal, e.method, e.published_on, e.observed_on, e.source_url)


def evidence_by_company(db: Session, ids: list[int]) -> dict[int, list[ActivityEvidence]]:
    out: dict[int, list[ActivityEvidence]] = {}
    if ids:
        for e in db.scalars(select(ActivityEvidence).where(ActivityEvidence.company_id.in_(ids))
                            .order_by(ActivityEvidence.observed_on.desc(), ActivityEvidence.id.desc())):
            out.setdefault(e.company_id, []).append(e)
    return out


def alts_by_company(db: Session, ids: list[int]) -> dict[int, list[AlternativeSite]]:
    out: dict[int, list[AlternativeSite]] = {}
    if ids:
        for a in db.scalars(select(AlternativeSite).where(AlternativeSite.company_id.in_(ids))):
            out.setdefault(a.company_id, []).append(a)
    return out


def reviews_for(db: Session, contact_ids: list[int]) -> dict[int, str]:
    if not contact_ids:
        return {}
    return dict(db.execute(select(ContactReview.contact_id, ContactReview.decision)
                           .where(ContactReview.contact_id.in_(contact_ids))).all())


def assess(c: Company, latest: WebsiteCheck | None, evs: list[ActivityEvidence], alts: list[AlternativeSite],
           scope: dict[str, Any], industries: Iterable[str], today: date | None = None,
           reviews: dict[int, str] | None = None) -> dict[str, Any]:
    today = today or local_today()
    reviews = reviews or {}
    activity, activity_reasons = classify_activity([to_ev(e) for e in evs], today, scope["window_days"])
    contacts = [contact_view(x, reviews.get(x.id)) for x in c.contacts]
    q = qualify(c, latest=latest, activity=activity, alt_healthy=[a.url for a in alts if a.status == "healthy"],
                contacts=contacts, scope_ok=in_scope(c, scope, industries),
                confirmed_need=any(e.kind == "confirmed_need" for e in evs))
    return {"activity": activity, "activity_reasons": activity_reasons, "contacts": contacts, **q}


# --- newer-website discovery (automatic, free, one GET per candidate) -----------------------------

MAX_ALT_CANDIDATES = 3


def alt_candidates(db: Session, c: Company) -> list[tuple[str, str]]:
    main = wr.host_of(wr.normalise_url(c.website)) if c.website else ""
    seen: dict[str, str] = {}

    def add(host: str, via: str) -> None:
        host = host.lower().strip().strip(".")
        if host.startswith("www."):
            host = host[4:]
        if not host or "." not in host or host == main or host in FREE_MAIL or host in seen:
            return
        if not wr.is_own_site(f"https://{host}/"):
            return
        seen[host] = via

    for x in c.contacts:
        if x.kind == "email" and "@" in x.value:
            add(x.value.rsplit("@", 1)[-1], "email_domain")
    for raw in db.scalars(select(RawItem).where(RawItem.company_id == c.id)):
        p = raw.payload or {}
        for w in p.get("websites") or []:
            if isinstance(w, str) and wr.is_own_site(wr.normalise_url(w)):
                add(wr.host_of(wr.normalise_url(w)), "directory_listing")
        for e in p.get("emails") or []:
            if isinstance(e, str) and "@" in e:
                add(e.rsplit("@", 1)[-1], "email_domain")
    return [(f"https://{h}/", via) for h, via in list(seen.items())[:MAX_ALT_CANDIDATES]]


def find_alternatives(company_id: int, http: SafeHttp) -> list[dict[str, Any]]:
    """Health-check each candidate newer site. No transaction is open during the requests."""
    with SessionLocal() as s:
        c = s.get(Company, company_id)
        if c is None:
            return []
        candidates = alt_candidates(s, c)
    results: list[dict[str, Any]] = []
    for url, via in candidates:
        v = wr.classify(wr.probe(url, http))
        status = "healthy" if v.status in ("healthy", "redirected_to_active_site", "migrated_to_storefront") else v.status
        reason = (v.reasons or [""])[0][:300]

        def _write(s: Session, url=url, via=via, status=status, reason=reason) -> None:
            row = s.scalar(select(AlternativeSite).where(AlternativeSite.company_id == company_id, AlternativeSite.url == url))
            if row is None:
                s.add(AlternativeSite(company_id=company_id, url=url, found_via=via, status=status, reason=reason,
                                      checked_at=utcnow()))
            else:
                row.status, row.reason, row.found_via, row.checked_at = status, reason, via, utcnow()

        fetch.short_write(_write)
        results.append({"url": url, "found_via": via, "status": status, "reason": reason})
    return results


# --- views used by the API ---------------------------------------------------------------------

BUCKETS = ("high_priority", "needs_verification", "migrated", "excluded")


def _industries(db: Session) -> list[str]:
    from app.ioi3 import core

    return list(core.active_campaign(db).industries or [])


def board(db: Session) -> list[dict[str, Any]]:
    """Every checked B2B company with its latest check and its qualification."""
    from sqlalchemy.orm import selectinload

    latest = {c.company_id: c for c in db.scalars(select(WebsiteCheck).where(WebsiteCheck.id.in_(wr._latest_ids())))}
    ids = list(latest)
    if not ids:
        return []
    companies = db.scalars(select(Company).where(Company.id.in_(ids), Company.channel == wr.B2B)
                           .options(selectinload(Company.contacts))).all()
    evs, alts = evidence_by_company(db, ids), alts_by_company(db, ids)
    scope, industries, today = get_scope(db), _industries(db), local_today()
    reviews = reviews_for(db, [x.id for c in companies for x in c.contacts])
    out = []
    for c in companies:
        chk = latest[c.id]
        a = assess(c, chk, evs.get(c.id, []), alts.get(c.id, []), scope, industries, today, reviews)
        out.append({
            "company_id": c.id, "name": c.name, "locality": c.locality, "business_type": category_of(c),
            "website": chk.website_url, "status": chk.status, "observed_class": chk.observed_class,
            "confidence": chk.confidence, "reasons": chk.reasons or [], "final_url": chk.final_url,
            "http_status": chk.http_status, "checked_at": chk.checked_at.isoformat(),
            "qualification": a["category"], "bucket": a["bucket"], "summary": a["summary"], "activity": a["activity"],
            "usable_contacts": sum(1 for x in a["contacts"] if x["usable"]),
            "alternative_found": any(x.status == "healthy" for x in alts.get(c.id, [])),
        })
    order = {"R0": 0, "R1": 1, "R2": 2, "R3": 3}
    out.sort(key=lambda r: r["checked_at"], reverse=True)  # newest first inside each category (stable sort below)
    out.sort(key=lambda r: order[r["qualification"]])
    return out


def overview(db: Session) -> dict[str, Any]:
    base = wr.overview(db)
    rows = board(db)
    buckets = {b: 0 for b in BUCKETS}
    activity = {s: 0 for s in ACTIVITY_STATUSES}
    for r in rows:
        buckets[r["bucket"]] += 1
        activity[r["activity"]] = activity.get(r["activity"], 0) + 1
    return {
        **base, **buckets,
        "r1": sum(1 for r in rows if r["qualification"] == "R1"),
        "r0": sum(1 for r in rows if r["qualification"] == "R0"),
        "activity": activity,
        "active_verified": activity["active_verified"],
        "alternatives_found": sum(1 for r in rows if r["alternative_found"]),
        "with_usable_contact": sum(1 for r in rows if r["usable_contacts"]),
        "scope": get_scope(db),
    }


def evidence_out(e: ActivityEvidence) -> dict[str, Any]:
    return {
        "id": e.id, "kind": e.kind, "kind_label": EVIDENCE_KINDS.get(e.kind, e.kind), "signal": e.signal,
        "statement": e.statement, "source_url": e.source_url,
        "published_on": e.published_on.isoformat() if e.published_on else None,
        "observed_on": e.observed_on.isoformat(), "method": e.method, "recorded_by": e.recorded_by,
        "counts_as_dated": evidence_date(to_ev(e)) is not None,
    }


def dossier(db: Session, company_id: int) -> dict[str, Any] | None:
    health = wr.dossier(db, company_id)
    if health is None:
        return None
    c = db.get(Company, company_id)
    latest = db.scalar(select(WebsiteCheck).where(WebsiteCheck.company_id == company_id)
                       .order_by(WebsiteCheck.checked_at.desc()).limit(1))
    evs = evidence_by_company(db, [company_id]).get(company_id, [])
    alts = alts_by_company(db, [company_id]).get(company_id, [])
    scope = get_scope(db)
    a = assess(c, latest, evs, alts, scope, _industries(db), reviews=reviews_for(db, [x.id for x in c.contacts]))
    return {
        **health,
        "company": {**health["company"], "business_type": category_of(c), "industry": c.industry,
                    "location_confidence": c.location_confidence, "location_reason": c.location_reason},
        "qualification": {k: a[k] for k in ("category", "bucket", "summary", "gates", "friction")},
        "activity": {"status": a["activity"], "reasons": a["activity_reasons"], "window_days": scope["window_days"],
                     "manual": [evidence_out(e) for e in evs if e.method == "manual"],
                     "automatic": [evidence_out(e) for e in evs if e.method != "manual"]},
        "alternatives": [{"url": x.url, "found_via": x.found_via, "status": x.status, "reason": x.reason,
                          "checked_at": x.checked_at.isoformat()} for x in alts],
        "contacts": a["contacts"],
        "check_yourself": manual_check_links(c),
    }


class EvidenceError(ValueError):
    pass


def add_evidence(db: Session, company_id: int, *, kind: str, signal: str, statement: str, source_url: str | None,
                 published_on: date | None, observed_on: date | None, confirms_chennai: bool, actor: str) -> ActivityEvidence:
    c = db.get(Company, company_id)
    if c is None or c.channel != wr.B2B:
        raise LookupError("not found")
    today = local_today()
    observed_on = observed_on or today
    statement = statement.strip()
    if kind not in EVIDENCE_KINDS:
        raise EvidenceError("Unknown evidence type")
    if signal not in SIGNALS:
        raise EvidenceError("Signal must be active, inactive or closed")
    if kind == "confirmed_need" and signal != "active":
        raise EvidenceError("A confirmed need is recorded with signal 'active'")
    if observed_on > today or (published_on and published_on > today):
        raise EvidenceError("Dates cannot be in the future")
    if published_on and published_on > observed_on:
        raise EvidenceError("Published date cannot be after the date you saw it")
    if has_contact_details(statement):
        raise EvidenceError("Keep phone numbers and email addresses out of notes — contacts are stored separately with their source")
    if source_url:
        if urlsplit(source_url).scheme not in ("http", "https"):
            raise EvidenceError("Source link must be an http(s) URL")
    elif kind not in DIRECT_KINDS:
        raise EvidenceError("Add the link where you saw it")
    if confirms_chennai and kind != "phone_call":
        raise EvidenceError("A Chennai address can only be confirmed from a call with the business")
    e = ActivityEvidence(company_id=company_id, kind=kind, signal=signal, statement=statement[:500],
                         source_url=source_url[:2048] if source_url else None, published_on=published_on,
                         observed_on=observed_on, method="manual", recorded_by=actor[:80])
    db.add(e)
    if confirms_chennai:
        c.location_confidence = "verified"
        c.location_reason = f"Owner confirmed the Chennai address on a call ({observed_on.isoformat()})"
    db.commit()
    return e


def categories(db: Session) -> list[dict[str, Any]]:
    """Business types in the campaign's industries, with counts, for the owner's target-scope setting."""
    from sqlalchemy import func

    industries = _industries(db)
    rows = db.execute(select(Company.industry, Company.directory_category, func.count())
                      .where(Company.channel == wr.B2B, Company.industry.in_(industries))
                      .group_by(Company.industry, Company.directory_category)).all()
    out = [{"industry": ind, "category": cat or UNCATEGORISED, "count": n} for ind, cat, n in rows]
    return sorted(out, key=lambda r: (r["industry"] or "", -r["count"], r["category"]))


def review_contact(db: Session, contact_id: int, *, decision: str, note: str | None, actor: str) -> dict[str, Any]:
    """Record the owner's decision on a contact. Only B2B company contacts; notes are screened for contact details."""
    c = db.get(CompanyContact, contact_id)
    if c is None or c.company.channel != wr.B2B:
        raise LookupError("not found")
    if decision not in ("approved", "rejected"):
        raise EvidenceError("Decision must be approved or rejected")
    note = (note or "").strip() or None
    if note and has_contact_details(note):
        raise EvidenceError("Keep phone numbers and email addresses out of notes")
    row = db.scalar(select(ContactReview).where(ContactReview.contact_id == contact_id))
    if row is None:
        row = ContactReview(contact_id=contact_id)
        db.add(row)
    row.decision, row.note, row.reviewed_by, row.reviewed_at = decision, note[:200] if note else None, actor[:80], utcnow()
    db.commit()
    return contact_view(c, decision)
