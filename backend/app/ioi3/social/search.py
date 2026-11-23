"""Finding publicly indexed seller profiles through an authorised search API (§8A).

Only a real search API is used. IOI does not fetch a search engine's own result pages, because that
is what their robots.txt forbids and it would break the moment the markup changed.

Two providers are supported, both of which have a free tier:
  brave       — IOI_SEARCH_PROVIDER=brave,      IOI_SEARCH_API_KEY=...
  google_cse  — IOI_SEARCH_PROVIDER=google_cse, IOI_SEARCH_API_KEY=..., IOI_SEARCH_CX=...

With neither configured, `availability()` says so in plain language and discovery falls back to the
sources that do work (adding a profile by hand, an authorised list, public market pages).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import quote_plus

from app.config import get_settings
from app.http_client import FetchError, SafeHttp
from app.ioi3.social import categories as cat
from app.ioi3.social import platforms as plat

BRAVE = "brave"
GOOGLE_CSE = "google_cse"
PROVIDERS = (BRAVE, GOOGLE_CSE)

# Search phrases per category. Each is a plain public-web query; none targets a private page.
QUERIES: dict[str, list[str]] = {
    cat.FASHION: [
        'site:instagram.com Chennai boutique "DM to order"',
        'Chennai instagram clothing boutique online order',
        'Chennai online boutique ethnic wear instagram',
    ],
    cat.GIFTS: [
        'site:instagram.com Chennai "customised gifts"',
        'Chennai customised gift business instagram',
        'Chennai personalised gifts hampers order',
    ],
    cat.BAKERY: [
        'site:instagram.com Chennai home bakery "pre order"',
        'Chennai home baker custom cake order whatsapp',
        'Chennai cake preorder instagram home bakery',
    ],
    cat.MEALS: [
        'Chennai tiffin subscription whatsapp order',
        'Chennai homemade meal subscription service',
        'Chennai tiffin service monthly plan instagram',
    ],
    cat.OTHER: [
        'site:instagram.com Chennai handmade jewellery business',
        'Chennai handmade products small business instagram',
    ],
}


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str
    query: str


@dataclass
class Availability:
    ready: bool
    provider: str | None
    message: str


def availability() -> Availability:
    s = get_settings()
    provider = (s.search_provider or "").strip().lower() or None
    if provider is None:
        return Availability(False, None,
                            "No search API is configured. Set IOI_SEARCH_PROVIDER (brave or google_cse) and "
                            "IOI_SEARCH_API_KEY in .env to search the public web. Until then, add sellers by "
                            "hand or import a list — those always work.")
    if provider not in PROVIDERS:
        return Availability(False, provider,
                            f"IOI_SEARCH_PROVIDER='{provider}' is not supported. Use 'brave' or 'google_cse'.")
    if not s.search_api_key:
        return Availability(False, provider, f"IOI_SEARCH_PROVIDER is set to {provider} but IOI_SEARCH_API_KEY is empty.")
    if provider == GOOGLE_CSE and not s.search_cx:
        return Availability(False, provider, "Google Programmable Search also needs IOI_SEARCH_CX (the engine id).")
    return Availability(True, provider, f"Public web search is configured ({provider}).")


def queries_for(categories: list[str], extra: list[str] | None = None, limit: int | None = None) -> list[str]:
    out: list[str] = []
    for c in categories:
        out += QUERIES.get(c, [])
    out += [q for q in (extra or []) if q.strip()]
    seen: set[str] = set()
    uniq = [q for q in out if not (q in seen or seen.add(q))]
    return uniq[: limit or get_settings().search_max_queries_per_run]


def _brave(http: SafeHttp, key: str, query: str, count: int) -> list[dict]:
    url = f"https://api.search.brave.com/res/v1/web/search?q={quote_plus(query)}&count={min(count, 20)}&country=in"
    res = http._get_raw(url, check_robots=False,
                        headers={"Accept": "application/json", "X-Subscription-Token": key})
    if res.status_code != 200:
        raise FetchError(f"Brave Search returned HTTP {res.status_code}")
    return (json.loads(res.content or b"{}").get("web") or {}).get("results") or []


def _google(http: SafeHttp, key: str, cx: str, query: str, count: int) -> list[dict]:
    url = (f"https://www.googleapis.com/customsearch/v1?key={quote_plus(key)}&cx={quote_plus(cx)}"
           f"&q={quote_plus(query)}&num={min(count, 10)}&gl=in")
    res = http._get_raw(url, check_robots=False, headers={"Accept": "application/json"})
    if res.status_code != 200:
        raise FetchError(f"Google Programmable Search returned HTTP {res.status_code}")
    return json.loads(res.content or b"{}").get("items") or []


def run(http: SafeHttp, query: str, *, count: int = 10) -> list[SearchHit]:
    """One search. Raises FetchError on a provider problem, RuntimeError when not configured."""
    av = availability()
    if not av.ready:
        raise RuntimeError(f"needs_setup: {av.message}")
    s = get_settings()
    if av.provider == BRAVE:
        rows = _brave(http, s.search_api_key or "", query, count)
        return [SearchHit(r.get("title") or "", r.get("url") or "", r.get("description") or "", query)
                for r in rows if r.get("url")]
    rows = _google(http, s.search_api_key or "", s.search_cx or "", query, count)
    return [SearchHit(r.get("title") or "", r.get("link") or "", r.get("snippet") or "", query)
            for r in rows if r.get("link")]


def hit_to_candidate(hit: SearchHit) -> "object | None":
    """Turn one search result into a candidate, or None if it is not a usable seller profile."""
    from app.ioi3.social.collect import Candidate

    try:
        ref = plat.parse(hit.url)
    except plat.NotAProfile:
        return None
    if ref.platform == plat.OTHER and not plat.catalogue_hint(hit.url):
        # A random page that is not a profile or a catalogue is not worth a record.
        if not cat.classify_category(hit.title, hit.snippet).category:
            return None
    name = (hit.title or ref.handle).split("|")[0].split("•")[0].split("(")[0].strip()[:200] or ref.handle
    return Candidate(
        source_key="public_search", external_id=f"{ref.platform}:{ref.handle}"[:200], source_url=ref.url,
        name=name, links=[ref.url], description=f"{hit.title}. {hit.snippet}".strip(),
        # A search snippet is not the business stating where it operates: it only earns a weak basis.
        geo_evidence=[("hashtag", f"Search result mentions Chennai: {hit.snippet[:200]}")] if "chennai" in
        (hit.title + hit.snippet).lower() else [],
        payload={"query": hit.query, "title": hit.title, "snippet": hit.snippet})
