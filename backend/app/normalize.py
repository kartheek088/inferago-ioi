"""Deterministic normalisation used for deduplication."""

import hashlib
import html
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
    "gclid", "fbclid", "mc_cid", "mc_eid", "ref", "ref_src", "igshid", "si",
}

LEGAL_SUFFIXES = [
    "private limited", "pvt ltd", "pvt. ltd.", "pvt. ltd", "p ltd", "limited", "ltd", "llp", "llc",
    "inc", "incorporated", "corp", "corporation", "co", "company", "gmbh", "plc", "pty ltd",
    "pty", "sa", "bv", "ag", "oy", "ab",
]


def canonical_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    host = parts.hostname.lower()
    if host.startswith("www."):
        host = host[4:]
    port = parts.port
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    query = urlencode(
        sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in TRACKING_PARAMS)
    )
    return urlunsplit(("https", netloc, path, query, ""))


def domain_of(url: str | None) -> str | None:
    if not url:
        return None
    try:
        host = urlsplit(url.strip()).hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.lower()
    return host[4:] if host.startswith("www.") else host


def normalize_org_name(name: str | None) -> str:
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    changed = True
    while changed and s:
        changed = False
        for suf in LEGAL_SUFFIXES:
            suf_n = re.sub(r"[^a-z0-9 ]+", " ", suf).strip()
            if s.endswith(" " + suf_n):
                s = s[: -len(suf_n) - 1].strip()
                changed = True
    if s.startswith("the "):
        s = s[4:]
    return s


def org_names_match(a: str, b: str) -> bool:
    """Conservative: names must normalise to exactly the same string.

    Similar-looking names ("Acme Systems" vs "Acme Solutions") are NOT merged.
    """
    na, nb = normalize_org_name(a), normalize_org_name(b)
    return bool(na) and na == nb


def html_to_text(raw: str | None) -> str:
    if not raw:
        return ""
    if "<" not in raw:
        return html.unescape(raw).strip()
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    for br in soup.find_all(["br", "p", "li", "div", "tr", "h1", "h2", "h3", "h4", "pre"]):
        br.insert_before("\n")
    text = soup.get_text()
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def content_hash(*parts: str | None) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(re.sub(r"\s+", " ", (p or "")).strip().lower().encode())
        h.update(b"\x00")
    return h.hexdigest()


def truncate(text: str | None, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)


def extract_urls(text: str) -> list[str]:
    seen: list[str] = []
    for m in URL_RE.findall(text or ""):
        m = m.rstrip(".,;:!?")
        if m not in seen:
            seen.append(m)
    return seen
