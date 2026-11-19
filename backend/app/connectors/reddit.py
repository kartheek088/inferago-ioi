"""Reddit connector — DISABLED unless official API credentials are configured.

Setup (see docs/SOURCES.md):
1. Create a "script" or "web" app at https://www.reddit.com/prefs/apps and review Reddit's
   Data API Terms and Developer Terms. Commercial use may require Reddit's approval.
2. Set IOI_REDDIT_CLIENT_ID, IOI_REDDIT_CLIENT_SECRET and IOI_REDDIT_USER_AGENT
   (format: "platform:app-id:version (by /u/yourname)").
3. Enable the "reddit" source and set config {"subreddits": ["forhire"], "title_must_match": "\\[hiring\\]"}.

Uses application-only OAuth (client credentials) and reads public subreddit listings only.
No scraping of reddit.com HTML, no private messages, no user lists.
"""

import base64
import re
from collections.abc import Iterator

from app.config import get_settings
from app.connectors.base import CollectContext, CollectedItem, ConnectorUnavailable, from_unix

SETUP = (
    "Reddit connector is credential-gated. Set IOI_REDDIT_CLIENT_ID, IOI_REDDIT_CLIENT_SECRET and "
    "IOI_REDDIT_USER_AGENT from an app registered at https://www.reddit.com/prefs/apps, after "
    "reviewing Reddit's Data API terms. See docs/SOURCES.md."
)


class RedditConnector:
    key = "reddit"

    def collect(self, ctx: CollectContext) -> Iterator[CollectedItem]:
        s = get_settings()
        if not s.reddit_configured:
            raise ConnectorUnavailable(SETUP)
        basic = base64.b64encode(f"{s.reddit_client_id}:{s.reddit_client_secret}".encode()).decode()
        token_res = ctx.http.client.post(
            "https://www.reddit.com/api/v1/access_token",
            data={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {basic}", "User-Agent": s.reddit_user_agent or ""},
        )
        ctx.http.requests_made += 1
        if token_res.status_code != 200:
            raise ConnectorUnavailable(f"Reddit token request failed: HTTP {token_res.status_code}")
        token = token_res.json().get("access_token")
        headers = {"Authorization": f"Bearer {token}", "User-Agent": s.reddit_user_agent or ""}
        pattern = ctx.config.get("title_must_match")
        count = 0
        for sub in ctx.config.get("subreddits", []):
            if not re.fullmatch(r"[A-Za-z0-9_]{2,30}", sub):
                ctx.log(f"Skipping invalid subreddit name {sub!r}")
                continue
            data = ctx.http.get(
                f"https://oauth.reddit.com/r/{sub}/new", params={"limit": min(100, ctx.max_items)}, headers=headers, check_robots=False
            ).json()
            for child in data.get("data", {}).get("children", []):
                p = child.get("data", {})
                title = p.get("title") or ""
                if pattern and not re.search(pattern, title, re.I):
                    continue
                url = "https://www.reddit.com" + (p.get("permalink") or "")
                yield CollectedItem(
                    external_id=f"t3_{p.get('id')}",
                    url=url,
                    title=title,
                    content=p.get("selftext") or title,
                    author=p.get("author"),
                    published_at=from_unix(p.get("created_utc")),
                    raw={"subreddit": sub, "id": p.get("id"), "permalink": p.get("permalink")},
                    contact_routes=[("platform_thread", url, url, False, "reply_on_public_thread")],
                )
                count += 1
                if count >= ctx.max_items:
                    return
