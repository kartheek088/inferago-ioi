"""Generic RSS/Atom connector for feeds the owner is permitted to consume.

Config: {"feed_url": "...", "require_term_match": false, "title_must_match": "<regex, optional>"}
Incremental: entries published at or before the cursor timestamp are skipped.
"""

import calendar
import re
from collections.abc import Iterator

import feedparser

from app.connectors.base import CollectContext, CollectedItem, from_unix
from app.normalize import canonical_url, content_hash, html_to_text


class RSSConnector:
    key = "rss"

    def collect(self, ctx: CollectContext) -> Iterator[CollectedItem]:
        feed_url = ctx.config.get("feed_url")
        if not feed_url:
            raise ValueError("RSS source has no feed_url configured")
        res = ctx.http.get(feed_url)
        parsed = feedparser.parse(res.content)
        if parsed.bozo and not parsed.entries:
            raise ValueError(f"Feed could not be parsed: {parsed.get('bozo_exception')}")
        since = float(ctx.cursor.get("since_ts") or 0)
        newest = since
        terms = [t.lower() for t in ctx.query_terms] if ctx.config.get("require_term_match") else []
        count = 0
        for e in parsed.entries:
            ts_struct = e.get("published_parsed") or e.get("updated_parsed")
            ts = calendar.timegm(ts_struct) if ts_struct else None
            if ts is not None and ts <= since:
                continue
            title = html_to_text(e.get("title"))
            body_html = ""
            if e.get("content"):
                body_html = " ".join(c.get("value", "") for c in e["content"])
            body = html_to_text(body_html or e.get("summary") or e.get("description") or "")
            if terms and not any(re.search(re.escape(t), f"{title} {body}", re.I) for t in terms):
                continue
            title_re = ctx.config.get("title_must_match")
            if title_re and not re.search(title_re, title, re.I):
                continue  # e.g. forum categories mixing buyer and seller posts
            link = e.get("link")
            ext = e.get("id") or canonical_url(link) or content_hash(title, body)
            if ts is not None:
                newest = max(newest, ts)
            yield CollectedItem(
                external_id=str(ext)[:300],
                url=link,
                title=title[:500] or None,
                content=body or title,
                author=e.get("author"),
                published_at=from_unix(ts),
                raw={"feed": feed_url, "entry_id": e.get("id"), "link": link, "tags": [t.get("term") for t in e.get("tags", [])]},
            )
            count += 1
            if count >= ctx.max_items:
                break
        ctx.cursor["since_ts"] = newest
