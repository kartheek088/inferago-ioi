"""Hacker News connector — public read-only APIs only.

APIs used:
- Official HN API (Firebase, https://github.com/HackerNews/API): the `whoishiring` account's
  submissions, to locate the monthly threads.
- HN Search API (Algolia, https://hn.algolia.com/api): full thread trees (one request per thread)
  and keyword search.

Modes (each toggled in the source config):
1. `freelancer_thread`  — "Ask HN: Freelancer? Seeking freelancer?": only top-level comments
   starting with "SEEKING FREELANCER" (buyers). "SEEKING WORK" comments are competitors, skipped.
2. `hiring_contracts`   — "Ask HN: Who is hiring?": only top-level posts whose header line says
   contract / contractor / freelance / fractional / part-time project work.
3. `keyword_search`     — stories/comments matching the configured search terms, incremental by
   timestamp. Comments under "Who wants to be hired?" / "Seeking work" threads are skipped.
"""

import re
import time
from collections.abc import Iterator

from app.connectors.base import CollectContext, CollectedItem, from_unix
from app.normalize import extract_urls, html_to_text

ALGOLIA = "https://hn.algolia.com/api/v1"
FIREBASE = "https://hacker-news.firebaseio.com/v0"
ITEM_URL = "https://news.ycombinator.com/item?id={}"
FREELANCER_TITLE = re.compile(r"^Ask HN: Freelancer\? Seeking freelancer\?", re.I)
HIRING_TITLE = re.compile(r"^Ask HN: Who is hiring\?", re.I)
SEEKING_FREELANCER = re.compile(r"^\s*SEEKING\s+FREELANCER", re.I)
CONTRACT_HEADER = re.compile(r"\b(contract(or|ors)?|freelance(r|rs)?|fractional|consultant|project[- ]based)\b", re.I)
SKIP_STORY = re.compile(r"who wants to be hired|seeking work|freelancer\? seeking freelancer|who is hiring", re.I)
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PLATFORM_DOMAINS = {
    "news.ycombinator.com", "github.com", "gitlab.com", "docs.google.com", "drive.google.com",
    "linkedin.com", "twitter.com", "x.com", "calendly.com", "forms.gle", "notion.so", "youtube.com",
    "medium.com", "upwork.com", "bit.ly", "lever.co", "greenhouse.io", "ashbyhq.com", "workable.com",
    "wellfound.com", "angel.co", "ycombinator.com", "typeform.com", "airtable.com",
}
MAX_THREADS_SCANNED = 12
ROLE_WORDS = r"engineer|developer|designer|devops|architect|consultant|manager|lead\b|specialist|programmer"


def _header(text: str) -> str:
    return text.strip().splitlines()[0][:400] if text.strip() else ""


def _split_header(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\s\|\s|\|", _header(text)) if p.strip()]


def first_website(text: str) -> str | None:
    for u in extract_urls(text):
        m = re.match(r"https?://([^/:?#]+)", u)
        host = re.sub(r"^www\.", "", m.group(1).lower()) if m else ""
        if host and not any(host == d or host.endswith("." + d) for d in PLATFORM_DOMAINS):
            return u
    return None


def parse_seeking_freelancer(text: str) -> tuple[str | None, str | None]:
    """'SEEKING FREELANCER | Company | Location | ...' → (org_name, website)."""
    parts = _split_header(text)
    org = None
    if len(parts) >= 2 and SEEKING_FREELANCER.match(parts[0]):
        cand = parts[1]
        if 2 <= len(cand) <= 80 and not re.search(r"remote|onsite|on-site|contract|freelanc|\$|hour|part[- ]time|full[- ]time|" + ROLE_WORDS, cand, re.I):
            org = cand
    return org, first_website(text)


def parse_hiring_post(text: str) -> tuple[str | None, str | None]:
    """'Company | Role | Location | ...' → (org_name, website)."""
    if SEEKING_FREELANCER.match(text):
        return parse_seeking_freelancer(text)
    parts = _split_header(text)
    org = None
    if len(parts) >= 2 and 2 <= len(parts[0]) <= 80 and not re.search(r"https?://", parts[0]):
        org = re.sub(r"\s*\(.*?\)\s*$", "", parts[0]).strip() or None
    return org, first_website(text)


def _contact_routes(text: str, item_url: str) -> list[tuple[str, str, str, bool, str]]:
    routes = [("platform_thread", item_url, item_url, False, "reply_on_public_thread")]
    for email in dict.fromkeys(EMAIL_RE.findall(text)):
        routes.append(("official_email", email, item_url, False, "published_by_poster_in_post"))
    return routes


class HackerNewsConnector:
    key = "hackernews"

    def collect(self, ctx: CollectContext) -> Iterator[CollectedItem]:
        produced = 0
        threads = None
        modes = [
            ("freelancer_thread", FREELANCER_TITLE, self._freelancer_items),
            ("hiring_contracts", HIRING_TITLE, self._hiring_items),
        ]
        for flag, title_re, extractor in modes:
            if not ctx.config.get(flag, True):
                continue
            if threads is None:
                threads = self._monthly_threads(ctx)
            story_id = next((sid for sid, title in threads if title_re.match(title)), None)
            if story_id is None:
                ctx.log(f"{flag}: no current thread found")
                continue
            for item in self._thread_items(ctx, story_id, flag, extractor):
                yield item
                produced += 1
                if produced >= ctx.max_items:
                    return
        if ctx.config.get("keyword_search", True) and ctx.query_terms:
            yield from self._keyword_search(ctx, ctx.max_items - produced)

    # -- monthly threads -----------------------------------------------------------------------
    def _monthly_threads(self, ctx: CollectContext) -> list[tuple[int, str]]:
        """Latest whoishiring threads, newest first, as (id, title). Official Firebase API."""
        user = ctx.http.get(f"{FIREBASE}/user/whoishiring.json", check_robots=False).json() or {}
        out: list[tuple[int, str]] = []
        for sid in (user.get("submitted") or [])[:MAX_THREADS_SCANNED]:
            item = ctx.http.get(f"{FIREBASE}/item/{sid}.json", check_robots=False).json() or {}
            if item.get("type") == "story" and item.get("title"):
                out.append((int(sid), item["title"]))
        if not any(FREELANCER_TITLE.match(t) for _, t in out):
            # The freelancer thread has sometimes been posted by other accounts; find it via search.
            res = ctx.http.get(f"{ALGOLIA}/search_by_date", params={"query": "Freelancer? Seeking freelancer?", "tags": "story", "hitsPerPage": 10}, check_robots=False).json()
            hits = sorted((h for h in res.get("hits", []) if FREELANCER_TITLE.match(h.get("title") or "")), key=lambda h: (h.get("created_at_i") or 0, h.get("num_comments") or 0), reverse=True)
            if hits:
                out.append((int(hits[0]["objectID"]), hits[0]["title"]))
        return out

    def _thread_items(self, ctx: CollectContext, story_id: int, flag: str, extractor) -> Iterator[CollectedItem]:
        tree = ctx.http.get(f"{ALGOLIA}/items/{story_id}", check_robots=False).json() or {}
        title = tree.get("title") or ""
        children = tree.get("children") or []
        ctx.log(f"{flag}: thread {story_id} '{title}' with {len(children)} top-level comments")
        kept = 0
        for child in children:
            text = html_to_text(child.get("text"))
            if not text:
                continue
            item = extractor(child, text, story_id, title)
            if item:
                kept += 1
                yield item
        ctx.log(f"{flag}: {kept} matching post(s)")

    def _base_item(self, child: dict, text: str, story_id: int, thread_title: str, org: str | None, website: str | None, mode: str) -> CollectedItem:
        cid = child.get("id")
        url = ITEM_URL.format(cid)
        return CollectedItem(
            external_id=f"item:{cid}", url=url, title=_header(text)[:300], content=text, author=child.get("author"),
            published_at=from_unix(child.get("created_at_i")),
            raw={"id": cid, "story_id": story_id, "thread_title": thread_title, "mode": mode, "author": child.get("author")},
            org_name=org, org_website=website, contact_routes=_contact_routes(text, url),
        )

    def _freelancer_items(self, child, text, story_id, title):
        if not SEEKING_FREELANCER.match(text):
            return None
        org, website = parse_seeking_freelancer(text)
        return self._base_item(child, text, story_id, title, org, website, "freelancer_thread")

    def _hiring_items(self, child, text, story_id, title):
        if not CONTRACT_HEADER.search(_header(text)):
            return None
        org, website = parse_hiring_post(text)
        return self._base_item(child, text, story_id, title, org, website, "hiring_contracts")

    # -- keyword search ------------------------------------------------------------------------
    def _keyword_search(self, ctx: CollectContext, budget: int) -> Iterator[CollectedItem]:
        if budget <= 0:
            return
        lookback_days = int(ctx.config.get("lookback_days", 30))
        since = int(ctx.cursor.get("keyword_since") or (time.time() - lookback_days * 86400))
        newest = since
        per_term = max(5, min(50, int(ctx.config.get("hits_per_term", 20))))
        emitted = 0
        for term in ctx.query_terms:
            res = ctx.http.get(
                f"{ALGOLIA}/search_by_date",
                params={"query": f'"{term}"', "tags": "(story,comment)", "numericFilters": f"created_at_i>{since}", "hitsPerPage": per_term},
                check_robots=False,
            ).json()
            for h in res.get("hits", []):
                story_title = h.get("story_title") or ""
                if SKIP_STORY.search(story_title):
                    continue
                text = html_to_text(h.get("comment_text") or h.get("story_text") or "")
                title = h.get("title") or (f"Comment on: {story_title}" if story_title else None)
                if not text and not title:
                    continue
                oid = h["objectID"]
                url = ITEM_URL.format(oid)
                created = h.get("created_at_i") or 0
                newest = max(newest, created)
                yield CollectedItem(
                    external_id=f"item:{oid}", url=url, title=(title or text[:120])[:300], content=text or (title or ""),
                    author=h.get("author"), published_at=from_unix(created),
                    raw={"hit": {k: h.get(k) for k in ("objectID", "title", "story_title", "story_id", "url", "author", "created_at_i")}, "term": term, "mode": "keyword_search"},
                    org_website=h.get("url") or None, contact_routes=_contact_routes(text, url),
                )
                emitted += 1
                if emitted >= budget:
                    # Keep the cursor: remaining hits are fetched next run (dedupe is idempotent).
                    ctx.log(f"keyword_search: stopped at item budget ({budget})")
                    return
        ctx.cursor["keyword_since"] = newest
