"""Public business contact-route extraction.

Only contact routes actually published on a page are recorded, with the page URL and date.
No guessed addresses (e.g. info@domain) are ever generated.
"""

import re
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.normalize import domain_of

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}\b")
PHONE_RE = re.compile(r"(?:(?:\+|00)\d{1,3}[\s.-]?)?(?:\(?\d{2,5}\)?[\s.-]?)\d{3,5}[\s.-]?\d{3,5}")
PERSONAL_EMAIL_DOMAINS = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "proton.me", "protonmail.com"}
CONTACT_LINK_RE = re.compile(r"contact|reach[- ]us|get[- ]in[- ]touch|enquir|inquir", re.I)
VENDOR_LINK_RE = re.compile(r"vendor|supplier|procurement|partner(s|ship)?[- ]?(program|with|portal)?|become[- ]a[- ]partner|empanel", re.I)


@dataclass
class FoundContact:
    contact_type: str
    value: str
    label: str | None = None


def extract_contacts(text: str, page_url: str, *, official_domain: str | None) -> list[FoundContact]:
    """Extract emails/phones published on a page.

    On an organisation's own site, only emails on that organisation's domain are kept as
    official business emails (personal webmail addresses are skipped to avoid storing
    unnecessary personal data).
    """
    out: list[FoundContact] = []
    seen: set[str] = set()
    for email in EMAIL_RE.findall(text or ""):
        e = email.lower().strip(".")
        dom = e.split("@", 1)[1]
        if e in seen or dom in PERSONAL_EMAIL_DOMAINS:
            continue
        if official_domain and not (dom == official_domain or dom.endswith("." + official_domain)):
            continue
        if re.search(r"\.(png|jpg|jpeg|gif|svg|webp)$", e):
            continue
        seen.add(e)
        out.append(FoundContact("official_email", e))
    for m in PHONE_RE.finditer(text or ""):
        raw = m.group(0).strip()
        digits = re.sub(r"\D", "", raw)
        if not (10 <= len(digits) <= 14) or digits in seen:
            continue
        # Require a phone-ish context to avoid capturing IDs/numbers.
        ctx = (text[max(0, m.start() - 30): m.start()]).lower()
        if not re.search(r"phone|tel|call|mobile|ph\b|☎|contact|\+", ctx + raw):
            continue
        seen.add(digits)
        out.append(FoundContact("published_phone", raw))
    return out


def find_links(html: bytes | str, base_url: str, pattern: re.Pattern, *, same_site: bool = True, limit: int = 3) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    base_dom = domain_of(base_url)
    out: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        label = f"{a.get_text(' ', strip=True)} {href}"
        if not pattern.search(label):
            continue
        url = urljoin(base_url, href)
        if same_site and domain_of(url) != base_dom:
            continue
        if url not in out:
            out.append(url)
        if len(out) >= limit:
            break
    return out


def mailto_links(html: bytes | str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    return list(dict.fromkeys(a["href"][7:].split("?")[0].lower() for a in soup.find_all("a", href=True) if a["href"].lower().startswith("mailto:")))
