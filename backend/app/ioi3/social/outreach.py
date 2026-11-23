"""The outreach draft for a social seller.

A one-person boutique or home bakery is not a company with a procurement process, so the message is
written differently from the B2B one: short, specific about what was actually seen on their public
page, honest that it may not be useful, one free thing offered, and a clear way to say no.

IOI never sends anything. The owner copies the text and messages them.
"""

from __future__ import annotations

from typing import Any

from app.ioi3.models import Company
from app.ioi3.social import categories as cat
from app.ioi3.social import platforms as plat

# What to offer for free per category — something useful in ten minutes, not a sales demo.
FREE_FIRST = {
    cat.FASHION: "a ready-made order form for your sizes and colours that you can share in your bio",
    cat.GIFTS: "a ready-made custom-order form that captures the personalisation and the deadline",
    cat.BAKERY: "a ready-made pre-order form with the delivery date and advance payment on it",
    cat.MEALS: "a simple subscriber list that shows each day's delivery count",
    cat.OTHER: "a ready-made order form you can share in your bio",
}

OPENER = {
    cat.FASHION: "your boutique",
    cat.GIFTS: "your custom gift work",
    cat.BAKERY: "your baking",
    cat.MEALS: "your tiffin service",
    cat.OTHER: "your work",
}


def _hook(c: Company) -> str:
    """One specific, checkable thing we actually saw — never a flattering guess."""
    confirmed = [a for a in c.social_activity if a.review_status == "confirmed" and a.published_at]
    if confirmed:
        a = max(confirmed, key=lambda x: x.published_at)
        return f"I saw your post from {a.published_at:%d %b} — {a.statement.lower()}."
    workflow = [f for f in c.facts if f.kind == "workflow" and f.state == "source_verified" and f.excerpt]
    if workflow:
        return f"I noticed you mention {workflow[0].statement.lower()}."
    acts = [a for a in c.social_activity if a.review_status != "rejected"]
    if acts:
        return f"I came across {c.name} and had a look at what you post."
    return f"I came across {c.name} while looking at small Chennai businesses selling online."


def draft(c: Company, sender_name: str = "", sender_link: str = "") -> dict[str, Any]:
    p = c.social
    category = (p.product_category if p else None) or cat.OTHER
    sol = c.solution or {}
    confirmed_problem = next((f.statement for f in c.facts
                              if f.kind == "problem" and f.state == "buyer_confirmed"), None)
    me = f"I'm {sender_name}" if sender_name else "I run a small software practice"
    free = FREE_FIRST.get(category, FREE_FIRST[cat.OTHER])
    channels = set((p.order_channels if p else []) or [])

    if confirmed_problem:
        middle = (f"You mentioned {confirmed_problem.rstrip('.').lower()}. I can set up something small that fixes "
                  f"just that — not a big system.")
    elif {"dm", "whatsapp"} & channels:
        middle = ("If orders come to you through DMs and WhatsApp, the thing that usually helps first is one list of "
                  "what is pending and what is paid — so nothing gets missed when it is busy.")
    else:
        improvement = sol.get("improvement") or "one place to see pending orders and payments"
        middle = f"The thing that usually helps sellers your size is {improvement[0].lower() + improvement[1:]}"

    msg = (f"Hi {c.name},\n\n"
           f"{me} here in Chennai — Inferago Tech Services, registered as an MSME. {_hook(c)}\n\n"
           f"{middle}\n\n"
           f"I'd be happy to make you {free}, free, so you can see whether it actually saves you time. "
           f"No cost and no obligation — if it is not useful, that's completely fine.\n\n"
           f"Would that be worth a try? If you'd rather not, just reply 'no' and I won't message again."
           + (f"\n\nAbout me: {sender_link}" if sender_link else "")
           + (f"\n\n— {sender_name}" if sender_name else ""))

    primary = next((a for a in c.social_accounts if a.is_primary), None)
    where = (f"{plat.PLATFORM_LABEL[primary.platform]} DM to @{primary.handle}" if primary
             and primary.platform != plat.WHATSAPP else None)
    wa = next((x.value for x in c.contacts if x.kind == "phone" and "WhatsApp" in (x.label or "")), None)
    route = f"WhatsApp {wa}" if wa else (where or "whatever public contact they published")

    return {
        "message": c.outreach_draft or msg,
        "edited": bool(c.outreach_draft),
        "contact_role": "The owner — these businesses are usually run by one person",
        "suggested_route": route,
        "questions": sol.get("confirm_with_buyer") or [],
        "notice": ("IOI never sends messages. Copy the text and message them yourself. "
                   "A public WhatsApp number is a contact route, not permission for bulk messages — "
                   "message once, and stop if they say no."),
        "free_offer": free,
    }
