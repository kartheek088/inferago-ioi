"""Selective research: broad collection → cheap filtering → ranking → deep research for the most
promising candidates → human review.

Budgets (settings.research_budget) limit requests per task, AI calls, tokens, wall time, depth
and candidate priority. Results are stored and re-research is skipped when inputs are unchanged.
"""

import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.openrouter import AIResearchBrief, AIUnavailable, get_ai
from app.contacts import CONTACT_LINK_RE, VENDOR_LINK_RE, FoundContact, extract_contacts, find_links, mailto_links
from app.db import utcnow
from app.documents import extract_html
from app.enums import Category, OpportunityStatus, ResearchStatus
from app.evaluation import evaluate_opportunity
from app.http_client import FetchError, SafeHttp
from app.models import Contact, Evidence, Opportunity, Organisation, ResearchTask
from app.normalize import content_hash, domain_of, normalize_org_name, truncate
from app.relationships import find_relationships, link_same_buyer, record_found
from app.settings_store import get_setting, log_activity

ACTIVE_STATUSES = (OpportunityStatus.NEW.value, OpportunityStatus.SHORTLISTED.value, OpportunityStatus.RESEARCHING.value)


@dataclass
class BatchReport:
    shortlisted: int = 0
    researched: int = 0
    skipped_unchanged: int = 0
    failed: int = 0
    stopped_reason: str | None = None
    task_ids: list[int] = field(default_factory=list)


def shortlist(db: Session, target: int, min_priority: float) -> list[Opportunity]:
    """Cheap filter + rank: top-N active opportunities above the minimum priority."""
    opps = db.scalars(
        select(Opportunity)
        .where(
            Opportunity.status.in_(ACTIVE_STATUSES),
            Opportunity.merged_into_id.is_(None),
            Opportunity.priority >= min_priority,
            Opportunity.category.not_in([Category.IRRELEVANT.value, Category.UNKNOWN.value]),
        )
        .order_by(Opportunity.priority.desc(), Opportunity.published_at.desc())
        .limit(target)
    ).all()
    for o in opps:
        if o.status == OpportunityStatus.NEW.value:
            o.status = OpportunityStatus.SHORTLISTED.value
    db.flush()
    return list(opps)


def _input_hash(opp: Opportunity, org: Organisation | None) -> str:
    return content_hash(opp.content_hash, org.website if org else None, org.domain if org else None)


def research_opportunity(db: Session, opp: Opportunity, *, request_budget: int = 6, http: SafeHttp | None = None, use_ai: bool = True, force: bool = False) -> ResearchTask:
    org = db.get(Organisation, opp.organisation_id) if opp.organisation_id else None
    ihash = _input_hash(opp, org)
    if not force:
        prev = db.scalar(select(ResearchTask).where(
            ResearchTask.opportunity_id == opp.id, ResearchTask.status == ResearchStatus.DONE.value, ResearchTask.input_hash == ihash
        ).limit(1))
        if prev:
            return prev
    task = ResearchTask(opportunity_id=opp.id, status=ResearchStatus.IN_PROGRESS.value, priority=opp.priority or 0,
                        request_budget=request_budget, input_hash=ihash, started_at=utcnow())
    db.add(task)
    opp.research_status = ResearchStatus.IN_PROGRESS.value
    db.flush()

    own_http = http is None
    http = http or SafeHttp(rate_limit_per_minute=20)
    findings: dict[str, Any] = {"steps": [], "contacts_found": 0, "relationships_found": 0, "domain_verified": False}
    try:
        if org and org.website:
            _research_site(db, opp, org, http, request_budget, findings)
        else:
            findings["steps"].append("No organisation website identified; the public thread/post is the only contact route.")
        task.requests_used = http.requests_made
        link_same_buyer(db, opp)
        task.brief = _template_brief(db, opp, org, findings)
        if use_ai:
            ai = get_ai(db)
            if ai:
                try:
                    res = ai.complete_json(
                        "research_brief",
                        "Write a concise, factual research brief for a sales lead reviewer. Only use facts present in the data.",
                        f"Opportunity: {opp.title}\n\n{truncate(opp.description, 6000)}\n\nFindings:\n{task.brief}",
                        AIResearchBrief, max_tokens=700,
                    )
                    task.brief = f"{res.brief}\n\nOpen questions:\n" + "\n".join(f"- {q}" for q in res.open_questions) + f"\n\n---\nDeterministic findings:\n{task.brief}"
                    task.ai_calls_used, task.tokens_used = ai.calls, ai.tokens
                except AIUnavailable as exc:
                    findings["steps"].append(f"AI brief unavailable, used deterministic brief ({exc})")
        task.findings = findings
        task.status = ResearchStatus.DONE.value
        opp.research_status = ResearchStatus.DONE.value
        if opp.status in (OpportunityStatus.NEW.value, OpportunityStatus.SHORTLISTED.value):
            opp.status = OpportunityStatus.RESEARCHING.value
    except Exception as exc:  # noqa: BLE001 - recorded on the task
        task.status, task.error = ResearchStatus.FAILED.value, f"{type(exc).__name__}: {exc}"
        opp.research_status = ResearchStatus.FAILED.value
        task.findings = findings
    finally:
        task.completed_at = utcnow()
        if own_http:
            http.close()
    evaluate_opportunity(db, opp)
    log_activity(db, "opportunity", opp.id, "researched", {"task_id": task.id, "status": task.status})
    db.flush()
    return task


def _fetch(http: SafeHttp, url: str, budget: int, findings: dict) -> tuple[bytes | None, str | None]:
    if http.requests_made >= budget:
        findings["steps"].append(f"Request budget ({budget}) reached before {url}")
        return None, None
    try:
        res = http.get(url)
        if "html" not in res.content_type and not res.content.lstrip().startswith(b"<"):
            findings["steps"].append(f"Skipped non-HTML {url}")
            return None, None
        return res.content, res.url
    except FetchError as exc:
        findings["steps"].append(f"Could not fetch {url}: {exc}")
        return None, None


def _record_contacts(db: Session, opp: Opportunity, org: Organisation, html: bytes, text: str, page_url: str, contact_type_page: str | None, findings: dict) -> None:
    found = extract_contacts(text, page_url, official_domain=org.domain)
    for e in mailto_links(html):
        if org.domain and (e.endswith("@" + org.domain) or e.endswith("." + org.domain)):
            if not any(f.value == e for f in found):
                found.append(FoundContact("official_email", e))
    if contact_type_page:
        found.append(FoundContact(contact_type_page, page_url))
    for f in found:
        existing = db.scalars(select(Contact).where(Contact.organisation_id == org.id, Contact.contact_type == f.contact_type, Contact.value == f.value)).all()
        if existing:
            for c in existing:
                if not c.verified:
                    # Seen earlier (e.g. in a public post); now confirmed on the official site.
                    c.notes = ((c.notes or "") + f" First seen at {c.source_url}.").strip()
                    c.source_url, c.verified = page_url, True
                    c.verification_method, c.verification_date = "published_on_official_site", utcnow()
                    findings["contacts_found"] += 1
            continue
        db.add(Contact(
            organisation_id=org.id, opportunity_id=opp.id, contact_type=f.contact_type, value=f.value[:500],
            source_url=page_url, verified=True, verification_method="published_on_official_site", verification_date=utcnow(),
        ))
        findings["contacts_found"] += 1
    db.flush()


def _research_site(db: Session, opp: Opportunity, org: Organisation, http: SafeHttp, budget: int, findings: dict) -> None:
    home_url = org.website if org.website.startswith("http") else f"https://{org.website}"
    html, final_url = _fetch(http, home_url, budget, findings)
    if not html:
        return
    title, text = extract_html(html)
    findings["steps"].append(f"Fetched homepage {final_url} ({title or 'no title'})")
    final_dom = domain_of(final_url)
    norm = normalize_org_name(org.name)
    tokens = [t for t in norm.split() if len(t) > 2]
    hay = f"{title or ''} {text[:3000]}".lower()
    if final_dom == org.domain and tokens and all(t in hay for t in tokens):
        dup = db.scalar(select(Organisation.id).where(Organisation.domain == org.domain, Organisation.domain_verified.is_(True), Organisation.id != org.id))
        if not dup:
            org.domain_verified = True
            findings["domain_verified"] = True
            findings["steps"].append(f"Domain {org.domain} verified: organisation name appears on the site")
    elif final_dom != org.domain:
        findings["steps"].append(f"Homepage redirected to a different domain ({final_dom}); domain not verified")
    if not org.description:
        meta = re.search(rb'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']{10,400})', html, re.I)
        org.description = meta.group(1).decode("utf-8", "replace") if meta else truncate(text, 400)
    db.add(Evidence(organisation_id=org.id, opportunity_id=opp.id, evidence_type="page", url=final_url, excerpt=truncate(text, 3000)))
    _record_contacts(db, opp, org, html, text, final_url, None, findings)
    findings["relationships_found"] += record_found(db, org, final_url, find_relationships(text))

    for url in find_links(html, final_url, CONTACT_LINK_RE, limit=1):
        chtml, curl = _fetch(http, url, budget, findings)
        if chtml:
            _, ctext = extract_html(chtml)
            findings["steps"].append(f"Fetched contact page {curl}")
            _record_contacts(db, opp, org, chtml, ctext, curl, "contact_page", findings)
    for url in find_links(html, final_url, VENDOR_LINK_RE, limit=1):
        vhtml, vurl = _fetch(http, url, budget, findings)
        if vhtml:
            _, vtext = extract_html(vhtml)
            findings["steps"].append(f"Fetched vendor/partner page {vurl}")
            if re.search(r"vendor|supplier|partner|register|empanel", vtext, re.I):
                _record_contacts(db, opp, org, vhtml, vtext, vurl, "vendor_onboarding_page", findings)
                if re.search(r"(become|apply|register)[^.]{0,40}(vendor|supplier|partner)", vtext, re.I):
                    org.accepts_external_vendors = True
                    findings["steps"].append("Vendor/partner page invites applications → external vendors accepted")
            db.add(Evidence(organisation_id=org.id, opportunity_id=opp.id, evidence_type="page", url=vurl, excerpt=truncate(vtext, 3000)))
            findings["relationships_found"] += record_found(db, org, vurl, find_relationships(vtext))
    db.flush()


def _template_brief(db: Session, opp: Opportunity, org: Organisation | None, findings: dict) -> str:
    contacts = db.scalars(select(Contact).where(Contact.opportunity_id == opp.id)).all()
    lines = [
        f"Opportunity: {opp.title}",
        f"Category: {opp.category} (confidence {opp.classification_confidence}); pipeline {opp.pipeline}",
        f"Organisation: {org.name if org else 'not identified'}" + (f" — {org.website}" + (" (domain verified)" if org.domain_verified else " (domain not verified)") if org and org.website else ""),
        f"Geography: {opp.country or 'unknown'}" + (f", {opp.region}" if opp.region else "") + (f" — {opp.geography_basis}" if opp.geography_basis else ""),
        f"Services matched: {', '.join(opp.services_matched or []) or 'none'}",
        f"Budget: {opp.budget_text or 'not stated'}",
        f"Eligibility (project): {opp.eligibility_outcome or 'not assessed'}",
        "Contact routes: " + ("; ".join(f"{c.contact_type}: {c.value} ({'verified' if c.verified else 'unverified'}, source {c.source_url})" for c in contacts) or "none found"),
        "Research steps:",
        *[f"- {s}" for s in findings.get("steps", [])],
    ]
    return "\n".join(lines)


def run_research_batch(db: Session, *, http_client: httpx.Client | None = None, resolver=None, limit: int | None = None) -> BatchReport:
    budget = get_setting(db, "research_budget")
    report = BatchReport()
    candidates = shortlist(db, int(budget["shortlist_target"]), float(budget["min_priority_for_research"]))
    report.shortlisted = len(candidates)
    deep_target = min(limit or int(budget["deep_research_target"]), int(budget["deep_research_target"]))
    started = time.monotonic()
    ai_calls = tokens = 0
    for opp in candidates:
        if report.researched >= deep_target:
            report.stopped_reason = "deep_research_target reached"
            break
        if time.monotonic() - started > float(budget["max_seconds_per_batch"]):
            report.stopped_reason = "time budget reached"
            break
        use_ai = ai_calls < int(budget["max_ai_calls_per_batch"]) and tokens < int(budget["max_tokens_per_batch"])
        kwargs = {"rate_limit_per_minute": 20}
        if resolver:
            kwargs["resolver"] = resolver
        http = SafeHttp(http_client, **kwargs)
        prev_done = db.scalar(select(ResearchTask.id).where(ResearchTask.opportunity_id == opp.id, ResearchTask.status == ResearchStatus.DONE.value).limit(1))
        task = research_opportunity(db, opp, request_budget=int(budget["max_requests_per_task"]), http=http, use_ai=use_ai)
        if prev_done == task.id:
            report.skipped_unchanged += 1
        elif task.status == ResearchStatus.DONE.value:
            report.researched += 1
            ai_calls += task.ai_calls_used
            tokens += task.tokens_used
        else:
            report.failed += 1
        report.task_ids.append(task.id)
        db.commit()
    db.commit()
    return report
