"""Owner action checklist. Default "this week" items are seeded once (tracked in app settings)."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import ActionItem, Opportunity
from app.settings_store import get_setting, set_setting

SEED_FLAG = "actions_seeded_v1"

# (title, detail, url, programme dedupe key or None, category)
DEFAULT_ACTIONS = [
    ("Rotate the OpenRouter API key and set a spending limit",
     "The key was shared in a chat. Create a new key at openrouter.ai/keys with a monthly limit, delete the old one, update IOI_OPENROUTER_API_KEY in .env, restart.",
     "https://openrouter.ai/keys", None, "security"),
    ("Ask a CA about voluntary GST registration",
     "GST is the most common mandatory failure (tenders, Zoho, Freshworks, corporate vendor forms). When registered, set gst_registered: true in Settings → profile overrides.",
     None, None, "compliance"),
    ("Join Razorpay Partner Program (free)", "Open to individuals; KYC (PAN) only for commissions.",
     "https://razorpay.com/partners", "programme:razorpay", "partner"),
    ("Join Shopify Partner Program (free)", "Accept the partner agreement; free development stores.",
     "https://www.shopify.com/partners", "programme:shopify", "partner"),
    ("Join the n8n Expert Partner waitlist", "Closed pilot — apply early. Matches the n8n Jobs leads IOI collects.",
     "https://n8n.io/partners", "programme:n8n", "partner"),
    ("Join the Make affiliate programme", "Open to freelancers (35% for 12 months). Solution Partner later, once there is a certified team.",
     "https://www.make.com/en/affiliate", "programme:make", "partner"),
    ("Run discovery daily: Hacker News + n8n Jobs + Make", "Discover → tick the three live sources → Run. Or enable the scheduler (IOI_SCHEDULER_ENABLED=true).",
     "/discover", None, "routine"),
    ("Run a research batch and review outreach drafts", "Research Queue → Run research batch, then Outreach → approve or reject drafts. Nothing is sent automatically.",
     "/research", None, "routine"),
]


def seed_default_actions(db: Session) -> int:
    if get_setting(db, SEED_FLAG):
        return 0
    due = utcnow() + timedelta(days=7)
    for i, (title, detail, url, prog, cat) in enumerate(DEFAULT_ACTIONS):
        opp_id = db.scalar(select(Opportunity.id).where(Opportunity.dedupe_key == prog)) if prog else None
        db.add(ActionItem(title=title, detail=detail, url=url, opportunity_id=opp_id, category=cat, due_date=due, sort_order=i))
    set_setting(db, SEED_FLAG, True)
    db.commit()
    return len(DEFAULT_ACTIONS)
