"""Big private projects where Inferago's help fits — found in public business and city news.

What counts: a private company opening or building something (hospital, hotel, showroom/outlets,
housing project, school, factory, warehouse) or expanding. Those projects need websites, booking
and lead CRMs, WhatsApp/AI assistants, ERP and automation, and are usually delivered with local
vendors, so a direct or informal approach can work.

What does not count: tenders, government / PSU / infrastructure contracts (roads, rail, power,
defence), stake sales, results and other market news, and IT companies (competitors).

Every lead keeps the article link and headline. Company names and connected companies are read
from the text, with the sentence they came from, and stay "unconfirmed" until the owner confirms
them. Nothing is sent automatically.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from urllib.parse import quote_plus

import feedparser
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.geo_states import state_from_text
from app.http_client import FetchError, SafeHttp
from app.models import ProjectLead
from app.normalize import html_to_text

# Checked 2026-11-22: robots.txt allows these, and each returns a valid feed.
DEFAULT_FEEDS: dict[str, str] = {
    "The Hindu · Chennai": "https://www.thehindu.com/news/cities/chennai/feeder/default.rss",
    "The Hindu · Coimbatore": "https://www.thehindu.com/news/cities/Coimbatore/feeder/default.rss",
    "The Hindu · Madurai": "https://www.thehindu.com/news/cities/Madurai/feeder/default.rss",
    "The Hindu · Tiruchi": "https://www.thehindu.com/news/cities/Tiruchirapalli/feeder/default.rss",
    "The Hindu · Tamil Nadu": "https://www.thehindu.com/news/national/tamil-nadu/feeder/default.rss",
    "The Hindu · Bengaluru": "https://www.thehindu.com/news/cities/bangalore/feeder/default.rss",
    "The Hindu · Hyderabad": "https://www.thehindu.com/news/cities/Hyderabad/feeder/default.rss",
    "The Hindu · Kochi": "https://www.thehindu.com/news/cities/Kochi/feeder/default.rss",
    "The Hindu · Business": "https://www.thehindu.com/business/feeder/default.rss",
    "BusinessLine · Companies": "https://www.thehindubusinessline.com/companies/feeder/default.rss",
    "BusinessLine · Economy": "https://www.thehindubusinessline.com/economy/feeder/default.rss",
    "ET · Hotels & restaurants": "https://economictimes.indiatimes.com/industry/services/hotels-/-restaurants/rssfeeds/13357212.cms",
    "ET · Industry": "https://economictimes.indiatimes.com/industry/rssfeeds/13352306.cms",
    "ET · Small business": "https://economictimes.indiatimes.com/small-biz/rssfeeds/5575607.cms",
    "ET Realty": "https://realty.economictimes.indiatimes.com/rss/topstories",
    "ET Health": "https://health.economictimes.indiatimes.com/rss/topstories",
    "ET Retail": "https://retail.economictimes.indiatimes.com/rss/topstories",
    "ET Hospitality": "https://hospitality.economictimes.indiatimes.com/rss/topstories",
}

_AMOUNT = r"(?:₹|rs\.?|inr|\$|usd|us\$)?\s?[\d,]+(?:\.\d+)?\s?(?:crore|cr\b|lakh|billion|bn\b|million|mn\b)"

# Something new is being opened / built / expanded.
PROJECT_PATTERNS: list[tuple[str, str]] = [
    ("new_facility", r"\b(new|greenfield|sets? up|to set up|setting up|inaugurat\w+|commission\w*|opens?|opening|launch(es|ed)?|to build|builds?|"
                     r"break(s)? ground|foundation stone|unveil\w*|starts? (work|construction))\b.{0,70}\b(plant|factory|facility|unit|campus|hospital|"
                     r"clinic|centre|center|hotel|resort|mall|park|warehouse|showrooms?|stores?|outlets?|branch(es)?|school|academy|project|township|"
                     r"tower|apartments?|villas?|restaurant|cafe|kitchen)\b"),
    ("expansion", r"\b(invest\w*|to invest|capex|expan\w+|scale up|ramp up|add(s|ing)? \d+|plans? \d+|\d+ new)\b.{0,80}"
                  r"(" + _AMOUNT + r"|outlets?|stores?|hospitals?|hotels?|showrooms?|branches|centres|centers|plants?|beds|rooms|units)"),
    ("launch", r"\b(launch(es|ed)?|enters?|forays? into|debuts?|rolls? out)\b.{0,60}\b(brand|stores?|outlets?|showrooms?|franchise|in (chennai|"
               r"coimbatore|madurai|tamil nadu|bengaluru|hyderabad|kochi|kerala|south india))\b"),
    ("partnership", r"\b(ties up|tie-up|partners with|joint venture|signs mou|inks mou)\b"),
]
TYPE_LABEL = {"new_facility": "New hospital / hotel / plant / outlet", "expansion": "Expansion", "launch": "New brand / outlets", "partnership": "Partnership"}
TYPE_POINTS = {"new_facility": 30, "expansion": 25, "launch": 25, "partnership": 10}

# Where our help fits → (pattern, sector, how we fit, services). First match wins; no match = skip.
SECTORS: list[tuple[str, str, str, list[str]]] = [
    (r"hospital|clinic|healthcare|health care|diagnostic|medical cent|eye care|dental|maternity|fertility|ivf|dialysis|pharmacy chain|wellness",
     "Healthcare", "Patient booking website, WhatsApp/AI appointment assistant, CRM for follow-ups, billing/HMS integration.",
     ["website", "ai", "crm", "integration"]),
    (r"hotel|resort|homestay|hospitality|restaurant|cafe|café|qsr|food court|cloud kitchen|bakery|sweets|banquet|convention",
     "Hospitality & food", "Booking/ordering website, guest CRM, WhatsApp concierge bot, POS/PMS integration, local SEO for each outlet.",
     ["website", "crm", "ai", "marketing"]),
    (r"showroom|stores?\b|outlets?|retail|mall|franchise|jewell|apparel|fashion|footwear|furniture|electronics|supermarket|hypermarket|d2c|brand",
     "Retail", "Store website and catalogue, loyalty CRM, billing–inventory integration, local SEO and Google listings for every outlet.",
     ["website", "crm", "integration", "marketing"]),
    (r"apartment|villa|township|residential|housing|real estate|realty|plotted|gated community|commercial space|office space|co-?working|tower",
     "Real estate", "Project website and ad landing pages, lead CRM for site visits, WhatsApp follow-up bot, booking/payment tracking.",
     ["website", "crm", "ai", "marketing"]),
    (r"\bschool\b|college|university|academy|coaching|training cent|skill cent|preschool|edtech|campus",
     "Education", "Admissions website, enquiry CRM, fee and attendance app, WhatsApp updates for students and parents.",
     ["website", "crm", "internal_apps"]),
    (r"gym|fitness|salon|spa\b|beauty",
     "Wellness", "Membership/booking website, CRM with renewals, WhatsApp reminders.", ["website", "crm", "ai"]),
    (r"plant|factory|manufactur|unit\b|facility|warehouse|logistics|cold storage|textile|garment|auto component|ev\b|battery|food processing|"
     r"packaging|foundry|machining|pharma",
     "Manufacturing & logistics", "ERP/SAP integration, production and inventory dashboards, workflow automation, supplier/dealer portal, company website.",
     ["erp", "automation", "internal_apps", "integration", "website"]),
]

# Not for us: tenders and government / infrastructure work.
TENDER_OR_GOVT = re.compile(
    r"\b(tenders?|bids?|bidding|e-?procurement|epc|l1 bidder|letter of intent|loi|awarded by|nhai|highway|expressway|railways?|"
    r"rail (line|project|yard)|metro rail|metro|airport authority|port trust|ntpc|bhel|ongc|gail|psu|state-run|state-owned|public sector|"
    r"ministry|union minister|union government|centre's|central government|govt\.?|government|chief minister|corporation of|municipal|"
    r"panchayat|smart city|defence|army|navy|air force|isro|drdo|power (supply|transmission|plant|project)|transmission|discom|mw|gw|"
    r"solar park|wind (farm|park)|dam|irrigation|ppp|amrut|jal jeevan|pmay|scheme)\b",
    re.I,
)
# Market, people and incident news.
NOISE = re.compile(
    r"\b(sensex|nifty|share price|shares (rise|fall|jump|surge|slip|drop)|stock (to buy|picks)|target price|ipo|q[1-4]|quarterly|net profit|"
    r"dividend|rating|downgrade|upgrade|resigns|appoint\w*|ceo says|obituary|dies|arrested|fraud|scam|bribe|explained|opinion|editorial|"
    r"podcast|quiz|horoscope|urges|slams|demands|should|accuses|blames|criticis\w+|protest\w*|clarify|dismissal|court|hc order|stay on|"
    r"stake|acquires|acquisition|merger|raises|funding round|valuation|layoffs?|strike|accident|fire|flood|rain)\b"
    r"|^(how|why|what|when|is|are|can|will|from)\b",
    re.I,
)
_IT_HEADLINE = re.compile(r"\b(it services|it firm|it company|software (firm|company|maker)|saas|tech firm|tech major|infotech|technologies|"
                          r"infosys|tcs|wipro|hcl ?tech|tech mahindra|cognizant|accenture|aurionpro|ltimindtree|mphasis|persistent|zoho|freshworks|"
                          r"data cent(er|re)|gcc|global capability)\b", re.I)
_COMPANY = re.compile(
    r"^(?P<co>[A-Z0-9][\w&.,'()\- ]{1,80}?)\s+(?:arm\s+|unit\s+|subsidiary\s+)?(?:to set up|sets up|setting up|to build|builds|inaugurates?|"
    r"commissions?|opens?|launches|unveils|plans|to invest|invests|signs|inks|ties up|partners|expands|to expand|announces|breaks ground|"
    r"enters|forays|adds|to add|starts)\b"
)
_STRIP = re.compile(r"^(?:[A-Z][\w-]*:\s+)")
SOUTH = {"Karnataka", "Kerala", "Andhra Pradesh", "Telangana", "Puducherry"}


@dataclass
class Match:
    project_type: str
    company: str | None
    amount: str | None
    location: str | None
    state: str | None
    sector: str
    fit: str
    services: list[str]
    score: float
    reasons: list[str] = field(default_factory=list)


def _is_it_company(company: str | None, text: str) -> bool:
    from app.prospects import _IT_NAMES

    return bool((company and (_IT_NAMES.search(company) or _IT_HEADLINE.search(company))) or _IT_HEADLINE.search(text[:300]))


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


def analyse(title: str, summary: str) -> Match | None:
    text = f"{title}. {summary}"
    head = text[:400]
    if NOISE.search(title) or TENDER_OR_GOVT.search(head):
        return None
    ptype = next((k for k, pat in PROJECT_PATTERNS if re.search(pat, title, re.I)), None) or next(
        (k for k, pat in PROJECT_PATTERNS if k != "partnership" and re.search(pat, summary[:500], re.I)), None)
    if ptype is None:
        return None
    sector = next(((name, fit, svc) for pat, name, fit, svc in SECTORS if re.search(pat, head, re.I)), None)
    if sector is None:
        return None  # nothing we can help with
    company = None
    cm = _COMPANY.match(_STRIP.sub("", title.strip()))
    if cm:
        company = cm.group("co").strip(" ,.-")[:200]
    if _is_it_company(company, text):
        return None  # IT companies are competitors
    reasons = [f"+{TYPE_POINTS[ptype]} {TYPE_LABEL[ptype].lower()}", f"fits us: {sector[0].lower()}"]
    score = float(TYPE_POINTS[ptype])
    amount = None
    m = re.search(_AMOUNT, text, re.I)
    if m and re.search(r"\d", m.group(0)):
        amount = m.group(0).strip()
        crore = _to_crore(amount)
        if crore is not None and 5 <= crore <= 500:
            score += 15
            reasons.append(f"+15 mid-size project ({amount}) — built with local vendors")
        elif crore is not None and crore < 5:
            score += 8
            reasons.append(f"+8 small project ({amount})")
        elif crore is not None and crore <= 2000:
            score += 5
            reasons.append(f"+5 large project ({amount})")
        elif crore is not None:
            score -= 10
            reasons.append(f"-10 very large ({amount}) — usually goes to big IT firms")
    location, state = state_from_text(text)
    if state == "Tamil Nadu":
        score += 25
        reasons.append(f"+25 in Tamil Nadu ({location}) — you can meet them in person")
    elif state in SOUTH:
        score += 15
        reasons.append(f"+15 in South India ({location}, {state})")
    elif state:
        score += 8
        reasons.append(f"+8 in India ({location}, {state})")
    if company:
        score += 10
        reasons.append("+10 company named in the headline")
    return Match(ptype, company, amount, location.title() if location else None, state, sector[0], sector[1], sector[2],
                 max(0.0, min(100.0, score)), reasons)


# ------------------------------------------------------------------------------------------------
# Who works with whom: companies connected to a project, read from the article text
# ------------------------------------------------------------------------------------------------
_NAME = r"(?P<co>(?:[A-Z][\w&.'-]*)(?:\s+(?:[A-Z][\w&.'-]*|&|of|and)){0,6})"
LINK_PATTERNS: list[tuple[str, str]] = [
    ("builder / contractor", r"\b(?:built|constructed|executed|being built|being constructed|to be built|to be constructed)\s+by\s+" + _NAME),
    ("designer / architect", r"\b(?:designed|planned)\s+by\s+" + _NAME),
    ("developer", r"\b(?:developed|promoted)\s+by\s+" + _NAME),
    ("operator / manager", r"\b(?:operated|managed|run)\s+by\s+" + _NAME),
    ("partner", r"\b(?:in partnership with|in collaboration with|partnered with|tied up with|joint venture with|in association with)\s+" + _NAME),
    ("supplier", r"\b(?:supplied by|equipment from|technology from|sourced from)\s+" + _NAME),
    ("contractor", r"\b(?:contractor|architects?|consultants?|EPC partner|construction partner|interiors? partner)\s*,?\s+" + _NAME),
    ("builder / contractor", _NAME + r"\s+(?:will|is to|has been chosen to)\s+(?:build|construct|execute|design|develop|supply|operate)\b"),
]
_STOP_NAMES = re.compile(r"^(The|This|It|He|She|They|We|India|Indian|Tamil Nadu|Chennai|State|Government|Centre|Minister|Mr|Ms|Dr|The Hindu|PTI|A|An)$")


def extract_links(text: str, url: str, own_company: str | None = None) -> list[dict[str, Any]]:
    """Companies connected to the project, each with the sentence it came from (unconfirmed)."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if len(sentence) > 600:
            continue
        for role, pat in LINK_PATTERNS:
            for m in re.finditer(pat, sentence):
                co = re.sub(r"\s+(of|and|&)$", "", m.group("co").strip(" ,.&"))
                if len(co) < 3 or _STOP_NAMES.match(co) or (own_company and co.lower() in own_company.lower()) or co.lower() in seen:
                    continue
                seen.add(co.lower())
                out.append({"company": co[:120], "role": role, "quote": sentence.strip()[:400], "url": url, "confirmed": None})
    return out[:10]


def article_text(http: SafeHttp, url: str, limit: int = 8000) -> str:
    res = http.get(url)  # robots.txt and size limits enforced by SafeHttp
    paras = re.findall(r"<p[^>]*>(.*?)</p>", res.text, re.I | re.S)
    text = " ".join(html_to_text(p) for p in paras) if paras else html_to_text(res.text)
    return re.sub(r"\s+", " ", text)[:limit]


# ------------------------------------------------------------------------------------------------
# Feeds → leads
# ------------------------------------------------------------------------------------------------
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


def run_project_search(db: Session, feeds: dict[str, str] | None = None, http: SafeHttp | None = None, max_age_days: int = 21,
                       read_articles: int = 40) -> dict[str, Any]:
    from datetime import UTC, datetime

    own = http is None
    http = http or SafeHttp(rate_limit_per_minute=20)
    feeds = feeds or DEFAULT_FEEDS
    stats: dict[str, Any] = {"feeds_ok": 0, "feeds_failed": [], "articles": 0, "new": 0, "matched": 0, "links_found": 0}
    cutoff = utcnow() - timedelta(days=max_age_days)
    fresh: list[ProjectLead] = []
    seen_links: set[str] = set()
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
                if not link or not it["title"] or link in seen_links:
                    continue
                seen_links.add(link)
                published = datetime.fromtimestamp(it["published_ts"], UTC).replace(tzinfo=None) if it["published_ts"] else None
                if published and published < cutoff:
                    continue
                m = analyse(it["title"], it["summary"])
                if not m:
                    continue
                stats["matched"] += 1
                if db.scalar(select(ProjectLead.id).where(ProjectLead.url == link)):
                    continue
                lead = ProjectLead(
                    url=link[:2048], title=it["title"][:500], summary=it["summary"][:2000] or None, feed=name,
                    published_at=published, company=m.company, project_type=m.project_type, amount_text=m.amount,
                    location=m.location, state=m.state, fit=m.fit, services=m.services, score=m.score,
                    score_reasons=[*m.reasons], status="new", links=[], contact_log=[],
                )
                db.add(lead)
                fresh.append(lead)
                stats["new"] += 1
            db.commit()
        # Read the full article for the best new leads to find connected companies (builders, partners...).
        for lead in sorted(fresh, key=lambda x: -x.score)[:read_articles]:
            try:
                text = article_text(http, lead.url)
            except FetchError:
                continue
            lead.links = extract_links(f"{lead.title}. {lead.summary or ''} {text}", lead.url, lead.company)
            lead.links_checked_at = utcnow()
            stats["links_found"] += len(lead.links)
            if not lead.state:
                place, st = state_from_text(text[:3000])
                if st:
                    lead.location, lead.state = place.title(), st
            db.commit()
    finally:
        if own:
            http.close()
    return stats


def approach(lead: ProjectLead) -> dict[str, Any]:
    """Draft for approaching the company (or a connected vendor). Nothing is sent."""
    who = lead.company or "your team"
    what = {"new_facility": "the new project", "expansion": "the expansion", "launch": "the launch", "partnership": "the new partnership"}.get(
        lead.project_type, "the project")
    fit = lead.fit or "Websites, CRM, automation and ERP integration."
    msg = (
        f"Hello {who},\n\n"
        f"Congratulations on {what}" + (f" ({lead.amount_text})" if lead.amount_text else "") + ". "
        f"New projects like this usually need some digital work done quickly: {fit[0].lower() + fit[1:]}\n\n"
        "Inferago Tech Services (Tamil Nadu) can take this on for you, or alongside your contractors and vendors, "
        "so your team can stay focused on the opening.\n\nCould we have a short call with whoever is handling the project?\n\n"
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
            "Look at the connected companies (builder, architect, partners): they often need a digital vendor too, and can introduce you.",
            "Find the project head or owner; a warm intro through a local vendor or LinkedIn works best.",
            "Send the draft yourself after editing it. Nothing is sent by IOI.",
        ],
        "note": "Company names are read from the news text — check them in the article before contacting.",
    }


FOLLOW_UP_DAYS = {"contacted": 4, "interested": 2}


def record_contact(lead: ProjectLead, channel: str, outcome: str, note: str | None, actor: str) -> None:
    now = utcnow()
    lead.contact_log = [*(lead.contact_log or []), {"at": now.isoformat(), "channel": channel, "outcome": outcome, "note": note, "by": actor}]
    lead.last_contacted_at = now
    lead.status = outcome
    days = FOLLOW_UP_DAYS.get(outcome)
    lead.next_follow_up = now + timedelta(days=days) if days else None
