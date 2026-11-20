"""Government e-Marketplace (GeM) public bid listing — read-only.

Source: https://bidplus.gem.gov.in/all-bids (public page, no login, no CAPTCHA; robots.txt allows
it). The page loads results from `all-bids-data` with a session CSRF token that the page itself
publishes; we fetch the page, then query the same public search endpoint the browser uses.

- Read-only: never logs in, never bids, never registers. Seller registration on GeM is the owner's job.
- Low rate (source rate limit), bounded pages per term and bounded bid-document downloads.
- Only bids whose item category matches Inferago's approved services are yielded; goods purchases
  (licences, hardware) and reverse auctions are skipped.
- Bid documents (PDF, bilingual Hindi/English) are parsed into English page text and labelled fields
  with page references. Nothing is invented: a label not found is simply absent.

Config: {"search_terms": [...], "pages_per_term": 2, "fetch_documents": true, "max_documents": 25,
         "skip_reverse_auctions": true}
"""

import json
import re
from collections.abc import Iterator
from datetime import datetime

from app import documents
from app.connectors.base import CollectContext, CollectedItem
from app.documents import DocumentError
from app.http_client import FetchError

BASE = "https://bidplus.gem.gov.in"
LIST_URL = f"{BASE}/all-bids"
DATA_URL = f"{BASE}/all-bids-data"
DOC_URL = f"{BASE}/showbidDocument/{{b_id}}"

DEFAULT_TERMS = [
    "software development", "custom software", "web application", "website development", "portal development",
    "mobile application", "api integration", "workflow automation", "erp", "dashboard", "it projects",
    "digitisation", "management system",
]

CSRF_RE = re.compile(r"csrf_bd_gem_nk['\"]?\s*:\s*['\"]([A-Za-z0-9]+)")
DEVANAGARI = re.compile(r"[ऀ-ॿ]")

# Item categories that indicate development / integration work (approved services only).
DEV_RE = re.compile(
    r"develop|custom(i[sz]ed)?\s+software|software\s+(development|services?|solution)|web\s?site|web\s+(application|portal)|"
    r"portal|mobile\s+app|application\s+(development|maintenance|support)|\bapis?\b|integration|automation|\berp\b|"
    r"dashboard|it\s+projects?|digiti[sz]|management\s+(information\s+)?system|\bmis\b|e-?office|workflow",
    re.I,
)
# Product purchases: licences, subscriptions and hardware are not software services.
GOODS_RE = re.compile(
    r"licen[cs]e|subscription|antivirus|operating\s+system|\bms\s+office|microsoft|hardware|printer|laptop|desktop|"
    r"\bserver\b|\bups\b|cctv|camera|scanner|router|switch(es)?\b|storage|firewall|monitor|projector|led\s+wall",
    re.I,
)

GEM_LABELS: dict[str, str] = {
    "bid_end": r"Bid End Date/Time\s*\n\s*(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}(?::\d{2})?)",
    "bid_opening": r"Bid Opening\s*\n?\s*Date/Time\s*\n\s*(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}(?::\d{2})?)",
    "ministry": r"Ministry/State Name\s*\n\s*([^\n]{2,150})",
    "department": r"Department Name\s*\n\s*([^\n]{2,150})",
    "organisation": r"Organisation Name\s*\n\s*([^\n]{2,150})",
    "office": r"Office Name\s*\n\s*([^\n]{2,150})",
    "quantity": r"Total Quantity\s*\n\s*([\d,]+)",
    "item_category": r"Item Category\s*\n\s*([^\n]{2,300}(?:\n(?!GeMARPTS|/)[^\n]{2,300}){0,3})",
    "turnover": r"(Minimum Average Annual Turnover[^\n]*(?:\n[^\n/]*){0,3}?\n?\s*[\d,.]+\s*Lakh\s*\(s\))",
    "experience": r"(Years of Past Experience[^\n]*(?:\n[^\n/]*){0,3}?\n?\s*\d+\s*Year\s*\(s\))",
    "mse_relaxation": r"MSE Relaxation for\s*\n?\s*Years Of Experience\s*\n?\s*and\s*\n?\s*Turnover\s*\n\s*(Yes|No)",
    "startup_relaxation": r"Startup Relaxation for\s*\n?\s*Years Of\s*\n?\s*Experience\s*\n?\s*and\s*\n?\s*Turnover\s*\n\s*(Yes|No)",
    "documents_required": r"Document required\s*\n?\s*from seller\s*\n\s*([^\n]{3,400})",
    "emd_required": r"EMD Detail\s*\n\s*/?\s*Required\s*\n\s*(Yes|No)",
    "emd_amount": r"EMD Amount\s*\n\s*([\d,]+)",
    "estimated_value": r"Estimated Bid Value\s*\n\s*([\d,]+)",
    "bid_type": r"Type of Bid\s*\n\s*([^\n]{3,60})",
    "evaluation_method": r"Evaluation Method\s*\n\s*([^\n]{3,80})",
    "buyer_email": r"Buyer Email id:\s*([\w.+-]+@[\w.-]+)",
}


def clean_gem_page(text: str) -> str:
    """Drop Hindi duplicate lines and stray punctuation; keep the English labels and values."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or DEVANAGARI.search(line) or line in ("/", "(", ")", "?", ",", "-", "|"):
            continue
        out.append(line)
    return "\n".join(out)


def parse_gem_fields(pages: list[tuple[str | None, str]]) -> dict[str, tuple[str, str | None]]:
    """Return {field: (value, page_reference)} for labels found in cleaned GeM bid pages."""
    found: dict[str, tuple[str, str | None]] = {}
    for name, pat in GEM_LABELS.items():
        rx = re.compile(pat, re.I)
        for ref, text in pages:
            m = rx.search(text)
            if m:
                found[name] = (re.sub(r"\s+", " ", m.group(1)).strip(), ref)
                break
    return found


def _first(doc: dict, key: str):
    v = doc.get(key)
    if isinstance(v, list):
        return v[0] if v else None
    return v


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


def is_relevant(category_text: str) -> bool:
    if not DEV_RE.search(category_text):
        return False
    if GOODS_RE.search(category_text) and not re.search(r"develop|integration|automation|portal|web\s?site", category_text, re.I):
        return False
    return True


def requirement_pages(fields: dict[str, tuple[str, str | None]]) -> list[tuple[str | None, str]]:
    """Structured eligibility statements built only from labels found in the bid document.

    GeM bid PDFs carry pages of generic policy boilerplate that mention turnover/experience in
    every bid; feeding that to the rule engine creates false requirements. Instead each found
    label becomes one statement, keeping its page reference. The GeM seller-registration rule
    is always present (portal rule).
    """
    mse = fields.get("mse_relaxation", ("", None))[0].lower() == "yes"
    startup = fields.get("startup_relaxation", ("", None))[0].lower() == "yes"
    relax = []
    if mse:
        relax.append("MSEs")
    if startup:
        relax.append("startups")
    exempt_txt = f", exempted for {' and '.join(relax)} (GeM relaxation Yes)" if relax else ""
    out: list[tuple[str | None, str]] = [("GeM portal rule", "Bidder must be registered on GeM as a seller to bid.")]
    if "turnover" in fields:
        v, ref = fields["turnover"]
        amt = re.search(r"([\d,.]+)\s*Lakh", v)
        out.append((ref, f"Minimum average annual turnover of the bidder is INR {amt.group(1) + ' lakhs' if amt else v}{exempt_txt}."))
    if "experience" in fields:
        v, ref = fields["experience"]
        yrs = re.search(r"(\d+)\s*Year", v)
        out.append((ref, f"Past experience of {yrs.group(1) + ' years' if yrs else v} in same/similar service (similar works executed) is required{exempt_txt}."))
    if fields.get("emd_required", ("", None))[0].lower() == "yes":
        ref = fields["emd_required"][1]
        amt = fields.get("emd_amount")
        out.append((ref, f"EMD (bid security) {'of INR ' + amt[0] + ' ' if amt else ''}is required."))
    return out


class GeMConnector:
    key = "gem"

    def _csrf(self, ctx: CollectContext) -> str:
        page = ctx.http.get(LIST_URL)
        m = CSRF_RE.search(page.text)
        if not m:
            raise ValueError("GeM listing page changed: CSRF token not found (connector needs updating)")
        return m.group(1)

    def _search(self, ctx: CollectContext, csrf: str, term: str, page: int) -> list[dict]:
        payload = {
            "page": page,
            "param": {"searchBid": term, "searchType": "fullText"},
            "filter": {"bidStatusType": "ongoing_bids", "byType": "all", "highBidValue": "",
                       "byEndDate": {"from": "", "to": ""}, "sort": "Bid-Start-Date-Latest"},
        }
        res = ctx.http.post_form(
            DATA_URL, {"payload": json.dumps(payload), "csrf_bd_gem_nk": csrf},
            headers={"X-Requested-With": "XMLHttpRequest", "Referer": LIST_URL},
        )
        body = res.json()
        if body.get("code") != 200:
            raise ValueError(f"GeM search returned code {body.get('code')}")
        return (body.get("response") or {}).get("response", {}).get("docs") or []

    def _document(self, ctx: CollectContext, b_id: str) -> list[tuple[str | None, str]] | None:
        try:
            res = ctx.http.get(DOC_URL.format(b_id=b_id))
        except FetchError as exc:
            ctx.log(f"GeM bid {b_id}: document not fetched ({exc})")
            return None
        if "pdf" not in res.content_type and not res.content.startswith(b"%PDF"):
            ctx.log(f"GeM bid {b_id}: document is not a PDF ({res.content_type})")
            return None
        try:
            raw_pages = documents.extract_pdf(res.content)
        except DocumentError as exc:
            ctx.log(f"GeM bid {b_id}: unreadable PDF ({exc})")
            return None
        return [(ref, clean_gem_page(t)) for ref, t in raw_pages]

    def collect(self, ctx: CollectContext) -> Iterator[CollectedItem]:
        cfg = ctx.config
        terms = cfg.get("search_terms") or DEFAULT_TERMS
        pages_per_term = int(cfg.get("pages_per_term") or 1)
        fetch_docs = cfg.get("fetch_documents", True)
        max_docs = int(cfg.get("max_documents") or 25)
        skip_ra = cfg.get("skip_reverse_auctions", True)
        seen: list[str] = list(ctx.cursor.get("seen_bid_ids") or [])
        seen_set = set(seen)

        csrf = self._csrf(ctx)
        candidates: dict[str, dict] = {}
        skipped_goods = skipped_ra = 0
        for term in terms:
            for page in range(1, pages_per_term + 1):
                docs = self._search(ctx, csrf, term, page)
                for d in docs:
                    b_id = str(_first(d, "b_id") or d.get("id") or "")
                    if not b_id or b_id in candidates:
                        continue
                    if skip_ra and _first(d, "b_bid_type") in (2, 5):
                        skipped_ra += 1
                        continue
                    cat = " ".join(filter(None, [_first(d, "bd_category_name") or "", _first(d, "b_category_name") or ""]))
                    if not is_relevant(cat):
                        skipped_goods += 1
                        continue
                    candidates[b_id] = d
                if len(docs) < 10:
                    break
        ctx.log(f"GeM: {len(candidates)} relevant bids; skipped {skipped_goods} non-service/goods, {skipped_ra} reverse auctions")

        produced = docs_fetched = 0
        for b_id, d in candidates.items():
            if produced >= ctx.max_items:
                break
            if b_id in seen_set:
                continue  # already ingested on a previous run; skip document download
            number = _first(d, "b_bid_number") or b_id
            category = _first(d, "bd_category_name") or _first(d, "b_category_name") or ""
            ministry = _first(d, "ba_official_details_minName")
            dept = _first(d, "ba_official_details_deptName")
            start = _parse_dt(_first(d, "final_start_date_sort"))
            end = _parse_dt(_first(d, "final_end_date_sort"))
            url = DOC_URL.format(b_id=b_id)

            pages = None
            if fetch_docs and docs_fetched < max_docs:
                pages = self._document(ctx, b_id)
                docs_fetched += 1
            fields = parse_gem_fields(pages) if pages else {}
            org = (fields.get("organisation") or (None,))[0] or dept or ministry
            header = [
                f"GeM bid {number} — Government e-Marketplace (GeM), Government of India public procurement portal.",
                f"Item / service category: {category}",
                f"Buyer: {' / '.join(x for x in [ministry, dept, org if org not in (ministry, dept) else None, (fields.get('office') or (None,))[0]] if x)}",
                f"Bid start: {start:%d-%m-%Y %H:%M}" if start else "",
                f"Bid end (submission deadline): {end:%d-%m-%Y %H:%M}" if end else "",
            ]
            for k, label in [("turnover", "Turnover"), ("experience", "Experience"), ("mse_relaxation", "MSE relaxation (experience & turnover)"),
                             ("startup_relaxation", "Startup relaxation"), ("emd_required", "EMD required"), ("emd_amount", "EMD amount (INR)"),
                             ("estimated_value", "Estimated bid value (INR)"), ("documents_required", "Documents required from seller"),
                             ("bid_type", "Type of bid"), ("evaluation_method", "Evaluation method")]:
                if k in fields:
                    header.append(f"{label}: {fields[k][0]}")
            header.append("Bidding requires the seller to be registered on GeM (portal rule).")
            body = "\n".join(h for h in header if h)
            if pages:
                body += "\n\n" + "\n\n".join(t for _, t in pages if t)
            budget = fields.get("estimated_value")
            routes: list[tuple[str, str, str, bool, str]] = [("platform_thread", url, url, False, "gem_bid_clarification_via_portal")]
            if "buyer_email" in fields:
                routes.append(("official_email", fields["buyer_email"][0], url, False, "published_in_gem_bid_document"))
            item = CollectedItem(
                external_id=f"gem:{b_id}",
                url=url,
                title=f"GeM {number}: {category}"[:500],
                content=body,
                published_at=start,
                raw={"bid": {k: _first(d, k) for k in d}, "fields": {k: {"value": v, "page": p} for k, (v, p) in fields.items()}},
                org_name=org,
                evidence_type="tender",
                pages=requirement_pages(fields),
                document_name=f"{number}.pdf" if pages else None,
                contact_routes=routes,
                deadline=end,
                budget_text=f"Estimated bid value INR {budget[0]}" if budget else None,
            )
            produced += 1
            seen.append(b_id)
            seen_set.add(b_id)
            yield item
        ctx.cursor["seen_bid_ids"] = seen[-3000:]

