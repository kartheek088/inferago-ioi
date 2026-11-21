"""Big projects from public business news: who just won a contract, is building a plant, or expanding.

Those companies often need outside help to deliver (software, dashboards, websites, CRM,
automation, ERP integration). The owner can approach them as a vendor or delivery partner.

Sources: public RSS feeds whose robots.txt allows reading (checked by SafeHttp on every fetch).
Every lead keeps the article link and headline. The company name is read from the headline and
is labelled as such; nothing else (contacts, budgets) is guessed. Nothing is sent automatically.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from urllib.parse import quote_plus

import feedparser
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.http_client import FetchError, SafeHttp
from app.models import ProjectLead
from app.normalize import html_to_text

# Checked 2026-11-22: robots.txt allows these, and each returns a valid feed.
DEFAULT_FEEDS: dict[str, str] = {
    "BusinessLine · Companies": "https://www.thehindubusinessline.com/companies/feeder/default.rss",
    "BusinessLine · Economy": "https://www.thehindubusinessline.com/economy/feeder/default.rss",
    "The Hindu · Business": "https://www.thehindu.com/business/feeder/default.rss",
    "The Hindu · Tamil Nadu": "https://www.thehindu.com/news/national/tamil-nadu/feeder/default.rss",
    "ET Infra": "https://infra.economictimes.indiatimes.com/rss/topstories",
    "ET · Industry": "https://economictimes.indiatimes.com/industry/rssfeeds/13352306.cms",
    "ET · Small business": "https://economictimes.indiatimes.com/small-biz/rssfeeds/5575607.cms",
}

_AMOUNT = r"(?:₹|rs\.?|inr|\$|usd|us\$)?\s?[\d,]+(?:\.\d+)?\s?(?:crore|cr\b|lakh|billion|bn\b|million|mn\b)"
PROJECT_PATTERNS: list[tuple[str, str]] = [
    ("contract_won", r"\b(bags?|bagged|wins?|won|secures?|secured|bags orders?|awarded|receives?|received|gets?|lands?|clinch(es|ed)?)\b.{0,60}\b(orders?|contracts?|projects?|tenders?|deals?|mandates?)\b"),
    ("contract_won", r"\b(awards?|awarded)\b.{0,40}\b(contract|project|order)\b.{0,10}\bto\b"),
    ("new_facility", r"\b(new|greenfield|brownfield|sets? up|to set up|setting up|inaugurat\w+|commission\w*|opens?|launch(es|ed)?|to build|builds?|break(s)? ground|foundation stone)\b.{0,60}\b(plant|factory|facility|unit|campus|hospital|hotel|mall|park|warehouse|data cent(er|re)|office|hub|terminal|port|airport|metro|plants|units|showrooms?|stores?|outlets?|branches)\b"),
    ("investment", r"\b(invest\w*|to invest|capex|expan\w+|scale up|ramp up)\b.{0,80}" + _AMOUNT),
    ("investment", _AMOUNT + r".{0,60}\b(investment|expansion|capex|project|plant|facility)\b"),
    ("mou", r"\bmou\b|memorandum of understanding|\bties up\b|\bpartners with\b|\bjoint venture\b"),
]
# Headlines that are about markets, people or policy rather than a project someone must deliver.
NOISE = re.compile(
    r"\b(sensex|nifty|share price|shares (rise|fall|jump|surge|slip|drop)|stock (to buy|picks)|target price|ipo (opens|subscribed|gmp)|"
    r"q[1-4] (results|net|profit)|quarterly (results|profit)|net profit|dividend|rating|downgrade|upgrade|resigns|appoint\w*|ceo says|"
    r"obituary|dies|arrested|fraud|scam|explained|opinion|editorial|podcast|quiz|horoscope|"
    r"urges|slams|demands|should|accuses|blames|criticis\w+|protest\w*|clarify|dismissal|court|hc order|stay on)\b"
    r"|^(how|why|what|when|is|are|can|will|from)\b",
    re.I,
)
TYPE_LABEL = {"contract_won": "Won a contract / order", "new_facility": "New plant / facility", "investment": "Investment / expansion", "mou": "MoU / partnership"}
TYPE_SERVICES = {
    "contract_won": ["integration", "automation", "internal_apps", "backend"],
    "new_facility": ["erp", "crm", "website", "automation", "internal_apps"],
    "investment": ["erp", "crm", "automation", "website", "ai"],
    "mou": ["integration", "backend", "api"],
}
TYPE_POINTS = {"contract_won": 30, "new_facility": 30, "investment": 25, "mou": 10}

TN_PLACES = ["tamil nadu", "chennai", "coimbatore", "madurai", "tiruchirappalli", "trichy", "salem", "tirunelveli", "erode", "vellore",
             "hosur", "tiruppur", "thanjavur", "kanchipuram", "sriperumbudur", "thoothukudi", "tuticorin", "krishnagiri", "ranipet",
             "chengalpattu", "oragadam", "puducherry", "karur", "dindigul", "nagercoil", "cuddalore"]
INDIA_PLACES = ["bengaluru", "bangalore", "hyderabad", "mumbai", "delhi", "pune", "kolkata", "ahmedabad", "kochi", "kerala", "karnataka",
                "andhra pradesh", "telangana", "maharashtra", "gujarat", "noida", "gurugram", "visakhapatnam", "nagpur", "lucknow", "jaipur", "odisha"]
_COMPANY = re.compile(
    r"^(?P<co>[A-Z0-9][\w&.,'()\- ]{1,80}?)\s+(?:arm\s+|unit\s+|subsidiary\s+)?(?:bags?|bagged|wins?|won|secures?|secured|receives?|gets?|lands?|"
    r"to set up|sets up|setting up|to build|builds|inaugurates?|commissions?|opens?|launches|plans|to invest|invests|signs|inks|ties up|partners|"
    r"expands|to expand|announces|clinches|awards|breaks ground)\b"
)
_STRIP = re.compile(r"^(?:[A-Z][\w-]*:\s+)")  # "Exclusive: ..." prefixes


@dataclass
class Match:
    project_type: str
    company: str | None
    amount: str | None
    location: str | None
    score: float
    reasons: list[str]


def analyse(title: str, summary: str) -> Match | None:
    text = f"{title}. {summary}"
    if NOISE.search(title):
        return None
    ptype = None
    for kind, pat in PROJECT_PATTERNS:
        if re.search(pat, title, re.I):
            ptype = kind
            break
    if ptype is None:
        for kind, pat in PROJECT_PATTERNS:
            if kind != "mou" and re.search(pat, summary[:600], re.I):
                ptype = kind
                break
    if ptype is None:
        return None
    reasons = [f"+{TYPE_POINTS[ptype]} {TYPE_LABEL[ptype].lower()}"]
    score = float(TYPE_POINTS[ptype])
    amount = None
    m = re.search(_AMOUNT, text, re.I)
    if m and re.search(r"\d", m.group(0)):
        amount = m.group(0).strip()
        crore = _to_crore(amount)
        if crore is not None and crore >= 1000:
            score += 25
            reasons.append(f"+25 very large project ({amount})")
        elif crore is not None and crore >= 100:
            score += 18
            reasons.append(f"+18 large project ({amount})")
        else:
            score += 8
            reasons.append(f"+8 amount stated ({amount})")
    low = text.lower()
    location = next((p.title() for p in TN_PLACES if re.search(rf"\b{re.escape(p)}\b", low)), None)
    if location:
        score += 25
        reasons.append(f"+25 in Tamil Nadu area ({location}) — easy to meet in person")
    else:
        location = next((p.title() for p in INDIA_PLACES if re.search(rf"\b{re.escape(p)}\b", low)), None)
        if location:
            score += 10
            reasons.append(f"+10 in India ({location})")
    company = None
    clean = _STRIP.sub("", title.strip())
    winner = re.search(r"\bawards?\b.{0,60}?\b(?:contract|order|project)\b.{0,10}?\bto\s+(?P<co>[A-Z][\w&.'\- ]{1,60}?)(?=\s+(?:for|in|at|worth|of)\b|[,:]|$)", clean)
    cm = _COMPANY.match(clean)
    if winner:  # "X awards contract to Y": Y is the one delivering, so Y is who we approach
        company = winner.group("co").strip(" ,.-")[:200]
    elif cm:
        company = cm.group("co").strip(" ,.-")[:200]
    if company and _is_it_company(company, text):
        return None  # IT / software firms are competitors, not clients
        score += 10
        reasons.append("+10 company named in the headline")
    return Match(ptype, company, amount, location, min(100.0, score), reasons)


_IT_HEADLINE = re.compile(r"\b(it services|it firm|it company|software (firm|company|maker)|saas|tech firm|tech major|infotech|technologies|"
                          r"infosys|tcs|wipro|hcl ?tech|tech mahindra|cognizant|accenture|aurionpro|ltimindtree|mphasis|persistent|zoho|freshworks)\b", re.I)


def _is_it_company(company: str, text: str) -> bool:
    from app.prospects import _IT_NAMES

    return bool(_IT_NAMES.search(company) or _IT_HEADLINE.search(company) or _IT_HEADLINE.search(text[:300]))


def _to_crore(amount: str) -> float | None:
    num = re.search(r"[\d,]+(?:\.\d+)?", amount)
    if not num:
        return None
    v = float(num.group(0).replace(",", ""))
    a = amount.lower()
    if "lakh" in a:
        return v / 100
    if "billion" in a or re.search(r"\bbn\b", a):
        return v * (8300 if ("$" in a or "usd" in a) else 100)
    if "million" in a or re.search(r"\bmn\b", a):
        return v * (8.3 if ("$" in a or "usd" in a) else 0.1)
    return v  # crore


def fetch_feed(http: SafeHttp, url: str) -> list[dict[str, Any]]:
    res = http.get(url)
    parsed = feedparser.parse(res.content)
    if parsed.bozo and not parsed.entries:
        raise FetchError(f"Feed could not be read: {parsed.get('bozo_exception')}")
    items = []
    for e in parsed.entries:
        ts = e.get("published_parsed") or e.get("updated_parsed")
        items.append({
            "title": html_to_text(e.get("title") or "").strip(),
            "summary": html_to_text(e.get("summary") or e.get("description") or "").strip(),
            "link": e.get("link"),
            "published_ts": calendar.timegm(ts) if ts else None,
        })
    return items


def run_project_search(db: Session, feeds: dict[str, str] | None = None, http: SafeHttp | None = None, max_age_days: int = 21) -> dict[str, Any]:
    from datetime import UTC, datetime

    own = http is None
    http = http or SafeHttp(rate_limit_per_minute=20)
    feeds = feeds or DEFAULT_FEEDS
    stats = {"feeds_ok": 0, "feeds_failed": [], "articles": 0, "new": 0, "matched": 0}
    cutoff = utcnow() - timedelta(days=max_age_days)
    try:
        for name, url in feeds.items():
            try:
                items = fetch_feed(http, url)
            except FetchError as exc:
                stats["feeds_failed"].append(f"{name}: {str(exc)[:150]}")
                continue
            stats["feeds_ok"] += 1
            for it in items:
                stats["articles"] += 1
                link = it["link"]
                if not link or not it["title"]:
                    continue
                published = datetime.fromtimestamp(it["published_ts"], UTC).replace(tzinfo=None) if it["published_ts"] else None
                if published and published < cutoff:
                    continue
                m = analyse(it["title"], it["summary"])
                if not m:
                    continue
                stats["matched"] += 1
                if db.scalar(select(ProjectLead.id).where(ProjectLead.url == link)):
                    continue
                db.add(ProjectLead(
                    url=link[:2048], title=it["title"][:500], summary=it["summary"][:2000] or None, feed=name,
                    published_at=published, company=m.company, project_type=m.project_type, amount_text=m.amount,
                    location=m.location, services=TYPE_SERVICES[m.project_type], score=m.score, score_reasons=m.reasons,
                    status="new",
                ))
                stats["new"] += 1
            db.commit()
    finally:
        if own:
            http.close()
    return stats


def approach(lead: ProjectLead) -> dict[str, Any]:
    """Draft for approaching the company as a vendor. Nothing is sent."""
    who = lead.company or "your team"
    what = {
        "contract_won": "winning this contract",
        "new_facility": "the new facility",
        "investment": "the expansion",
        "mou": "the new partnership",
    }[lead.project_type]
    msg = (
        f"Hello {who},\n\n"
        f"Congratulations on {what}" + (f" ({lead.amount_text})" if lead.amount_text else "") + ". "
        "Projects like this usually create extra software and digital work: dashboards and reporting, workflow automation, "
        "integrations between systems, ERP/CRM setup, and websites or portals.\n\n"
        "Inferago Tech Services (Tamil Nadu) can take on part of that as a delivery partner or vendor, so your core team "
        "stays focused on the project.\n\nWould you be open to a short call with whoever handles IT or vendor onboarding?\n\n"
        "Thank you,\nInferago Tech Services"
    )
    q = quote_plus(f"{lead.company} official website contact") if lead.company else None
    return {
        "message": msg,
        "links": {
            "article": lead.url,
            "find_company": f"https://www.google.com/search?q={q}" if q else None,
            "linkedin_search": f"https://www.linkedin.com/search/results/companies/?keywords={quote_plus(lead.company)}" if lead.company else None,
        },
        "how_to": [
            "Open the article and confirm the company and project.",
            "Find the company's official website and its vendor / supplier registration or procurement contact.",
            "Look for the project head or IT head; a warm intro through LinkedIn usually works best.",
            "Send the draft yourself after editing it. Nothing is sent by IOI.",
        ],
        "note": "Company name was read from the headline — check it in the article before contacting.",
    }
