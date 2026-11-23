"""What to offer a social seller — cheapest effective option first.

The order of preference is deliberate and matches how little disruption each step causes:

  1. Improve the process they already have (no software at all).
  2. Configure software they already pay for.
  3. A shareable order form / light tracker they open on a phone.
  4. Connect what they already use.
  5. Build a small custom module.

Two standing rules:
- A website is never replaced by default, and Inferago never asks for a domain transfer for a
  workflow project. A separate mobile-friendly tool sits alongside whatever they already have.
- No official Instagram / WhatsApp / Facebook integration is ever promised. Those need approved
  Meta API access with specific permissions. Until that is confirmed for a given client, the offer
  is a link the seller shares themselves.
"""

from __future__ import annotations

from app.ioi3.social.categories import (
    BAKERY,
    CATEGORY_COMPLEXITY,
    COMPLEXITY,
    FASHION,
    GIFTS,
    MARKETPLACE_LED,
    MEALS,
    OTHER,
    SOCIAL_FULL_ECOM,
)

HIERARCHY = {
    1: "Improve the existing process",
    2: "Configure software they already use",
    3: "A shareable order form they can use on a phone",
    4: "Connect the tools they already use",
    5: "Build a small custom module",
}

NO_API_PROMISE = ("Shared as a link the seller posts or sends themselves. No automatic Instagram or WhatsApp "
                  "integration is promised: that needs approved Meta API access, which has to be arranged and "
                  "confirmed for each business first.")

# Public product categories a social seller may already be paying for. Checked before offering to build.
EXISTING_NOTE = ("General overview from public product pages. Check the vendor's current features and pricing "
                 "before advising a seller.")
EXISTING_OPTIONS = [
    {"name": "Dukaan", "url": "https://mydukaan.io/", "category": "Online store builder for small Indian sellers",
     "solves": "A catalogue and order list with payments, set up from a phone.",
     "burden": "Monthly plan for the useful features; custom/made-to-order work still tracked by hand.",
     "inferago_role": "Set it up properly for them, then add only the step it does not cover."},
    {"name": "Instamojo", "url": "https://www.instamojo.com/", "category": "Payment links and simple store",
     "solves": "Collecting advances and payments through a shareable link.",
     "burden": "Per-transaction fee; no production or delivery-status tracking.",
     "inferago_role": "Keep it for payments and track the order status beside it."},
    {"name": "Google Forms + Sheets", "url": "https://workspace.google.com/products/forms/",
     "category": "Free form and spreadsheet",
     "solves": "Collecting order details in one place instead of chat messages. Free.",
     "burden": "No order status, no reminders, and the sheet gets messy as volume grows.",
     "inferago_role": "The honest first step for a seller with few orders — start here, build later if it is outgrown."},
    {"name": "Zoho Inventory", "url": "https://www.zoho.com/inventory/", "category": "Inventory and order management",
     "solves": "Stock, orders and shipments for sellers with real volume.",
     "burden": "Subscription, setup and training; heavier than most single-person sellers need.",
     "inferago_role": "Configure it, or advise against it when it is more than they need."},
    {"name": "WhatsApp Business app", "url": "https://business.whatsapp.com/",
     "category": "Free business messaging with a catalogue",
     "solves": "A product catalogue, quick replies and labels inside WhatsApp itself. Free.",
     "burden": "Labels are not an order list; nothing is reportable and nothing is shared with a helper.",
     "inferago_role": "Keep WhatsApp as the front door; log the orders somewhere they can be counted."},
    {"name": "Shopify", "url": "https://www.shopify.com/", "category": "Full e-commerce platform",
     "solves": "A complete online shop with checkout, shipping and apps.",
     "burden": "Monthly cost plus app costs; far more than a seller taking a few custom orders a day needs.",
     "inferago_role": "Only for sellers who want a full shop. Otherwise it is the expensive answer."},
]


def existing_first(tools: list[str], category: str | None) -> dict:
    """Existing software to consider before building anything."""
    already = sorted({t for t in tools})
    return {"note": EXISTING_NOTE, "already_using": already, "options": EXISTING_OPTIONS,
            "advice": ("They already use " + ", ".join(already) + " — configure or extend that before building anything new."
                       if already else "No order/inventory software was named on their public pages.")}


# ------------------------------------------------------------------------------------------------
# The four offers (§16)
# ------------------------------------------------------------------------------------------------
def _offer(name: str, level: int, improvement: str, scope: list[str], why: str, confirm: list[str]) -> dict:
    return {"offer": name, "level": level, "level_label": HIERARCHY[level], "improvement": improvement,
            "scope": scope, "why": why, "confirm_with_buyer": confirm, "delivery_note": NO_API_PROMISE}


SOCIAL_ORDERFLOW_LITE = dict(
    name="Social OrderFlow Lite", level=3,
    improvement="One shareable order form and a single list of what is pending, instead of scrolling back through DMs.",
    scope=["Order form with product, size/colour and quantity", "Customer name, number and delivery address",
           "Order status: new → confirmed → packed → dispatched", "Whether payment is received",
           "A pending-orders list on the phone"],
    why="Their posts show variants and orders arriving as messages, which is exactly what gets lost in a chat thread.",
    confirm=["How many orders do you get in a week?", "Where do orders come in — DM, WhatsApp or calls?",
             "How do you track which ones are paid and which are packed?", "Who else needs to see the list?"])

CUSTOM_ORDERFLOW = dict(
    name="Custom OrderFlow", level=3,
    improvement="Collect the customisation details and reference photo once, with the deadline and advance recorded against the order.",
    scope=["Order form that captures the customisation in the customer's own words",
           "Reference image upload", "Required-by date", "Advance received / balance due",
           "Production status: not started → in progress → ready", "Delivery or pickup details"],
    why="Personalised work goes wrong when the specification sits in a chat and the deadline is remembered, not recorded.",
    confirm=["How do customers send you their customisation details today?",
             "How often does an order get made wrong because a detail was missed?",
             "Do you take an advance, and how do you track the balance?", "How far ahead are you booked?"])

FOOD_PREORDER = dict(
    name="Pre-Order and Delivery Tracker", level=3,
    improvement="A day-by-day view of what has to be made and delivered, with each order's requirements and payment status.",
    scope=["Order form with the item, flavour/customisation and required date",
           "Delivery or pickup slot", "Advance / full payment status",
           "A daily list: what to bake today, what goes out today", "Simple capacity limit per day"],
    why="Pre-order food is scheduling work: the risk is accepting more for one date than can be made.",
    confirm=["How many orders do you take for a single day?", "How do you decide when to stop accepting for a date?",
             "How are advances collected and tracked?", "Do you deliver yourself or use a courier?"])

SUBSCRIPTION_ORDERFLOW = dict(
    name="Subscription OrderFlow", level=3,
    improvement="One place for who is subscribed, who paused, how many meals go out today and who owes for next month.",
    scope=["Subscriber list with plan and address", "Pause / resume with dates",
           "Today's delivery count and route list", "Payment due and received per subscriber",
           "Renewal reminders"],
    why="Subscription food is a daily count and a monthly collection — both are easy to get wrong from memory.",
    confirm=["How many active subscribers do you have?", "How do customers tell you they are pausing?",
             "How do you work out each day's count?", "How do you collect the monthly payment and chase what is due?"])

BY_CATEGORY = {FASHION: SOCIAL_ORDERFLOW_LITE, GIFTS: CUSTOM_ORDERFLOW, BAKERY: FOOD_PREORDER,
               MEALS: SUBSCRIPTION_ORDERFLOW, OTHER: SOCIAL_ORDERFLOW_LITE}


def recommend(*, category: str | None, complexity_keys: set[str], tools: list[str], sales_setup: str,
              confirmed_problems: list[str], order_channels: list[str], workflow_gaps: list[str]) -> dict:
    """The smallest offer that fits what is actually known. Always includes the existing-software check."""
    out = _recommend(category=category, complexity_keys=complexity_keys, tools=tools, sales_setup=sales_setup,
                     confirmed_problems=confirmed_problems, order_channels=order_channels, workflow_gaps=workflow_gaps)
    out["existing_software"] = existing_first(tools, category)
    out["known_workflow"] = _known(category, complexity_keys, order_channels, workflow_gaps)
    return out


def _known(category: str | None, keys: set[str], channels: list[str], gaps: list[str]) -> str:
    bits = []
    if keys:
        bits.append("Seen in their own posts: " + ", ".join(COMPLEXITY[k][0].lower() for k in sorted(keys) if k in COMPLEXITY))
    if channels:
        bits.append("Orders arrive via " + ", ".join(sorted(set(channels))))
    if gaps:
        bits.append(gaps[0])
    return ". ".join(bits) if bits else "Not known yet — only the profile has been seen so far."


def _recommend(*, category, complexity_keys, tools, sales_setup, confirmed_problems, order_channels, workflow_gaps) -> dict:
    # 1. The buyer told us one specific thing: fix exactly that, nothing more.
    if len(confirmed_problems) == 1:
        return _offer("Small Automation", 3,
                      f"Fix the one thing they described: {confirmed_problems[0]}",
                      ["Watch how the task is done today, with the person who does it",
                       "Automate or replace that single step", "A week of support afterwards"],
                      "They named one problem themselves, so the smallest fix is the right first project.",
                      ["How often does this happen, and how long does it take each time?",
                       "What do you use for it today?"])

    # 2. They already pay for something capable: configure it rather than sell a build.
    if tools:
        return _offer("Set up what they already have", 2,
                      f"Configure {', '.join(sorted(tools))} properly and add only the step it does not cover.",
                      [f"Review how {sorted(tools)[0]} is set up today",
                       "Fix the setup so orders and payments are recorded in it",
                       "Add only the missing step (for example made-to-order tracking)"],
                      "They are already paying for software — configuring it is cheaper for them and faster to deliver.",
                      [f"What do you use {sorted(tools)[0]} for today, and what still gets done by hand?",
                       "What does it not do that you wish it did?"])

    # 3. Nothing known about the business yet.
    if category is None and not complexity_keys:
        return {"offer": None, "level": None, "level_label": None, "improvement": None, "scope": [],
                "why": "Not enough is known about how they sell yet.", "confirm_with_buyer": [],
                "delivery_note": NO_API_PROMISE}

    # 4. Very simple operation: the honest answer is a free form, not a project.
    if len(complexity_keys) <= 1 and sales_setup != MARKETPLACE_LED:
        return _offer("Shared order form (start simple)", 1,
                      "A free form and a single list, set up with them. If they outgrow it, build from there.",
                      ["Set up a form that captures the order details they need",
                       "Show them how to work from one pending list", "Review after a few weeks"],
                      "Only limited order complexity is visible, so a paid build would not be honest yet.",
                      ["How many orders do you handle in a week?",
                       "What goes wrong most often with orders today?"])

    # 5. Already has full online checkout: do not rebuild the shop, cover what it misses.
    if sales_setup == SOCIAL_FULL_ECOM:
        return _offer("Add made-to-order tracking beside their shop", 4,
                      "Keep their existing checkout and add tracking for the custom or made-to-order work it cannot handle.",
                      ["List which orders their shop handles and which are managed by hand",
                       "Add a tracker for the manual ones", "Connect it to their existing order list if there is a way in"],
                      "Their checkout already works — replacing it would cost them money and gain nothing.",
                      ["Which orders go through the website and which come by DM or WhatsApp?",
                       "What does the website not handle well?", "Can we export or read its order list?"])

    base = BY_CATEGORY.get(category or OTHER, SOCIAL_ORDERFLOW_LITE)
    relevant = [k for k in CATEGORY_COMPLEXITY.get(category or OTHER, ()) if k in complexity_keys]
    why = base["why"]
    if relevant:
        why += " Seen on their pages: " + ", ".join(COMPLEXITY[k][0].lower() for k in relevant[:3]) + "."
    return _offer(base["name"], base["level"], base["improvement"], list(base["scope"]), why, list(base["confirm"]))
