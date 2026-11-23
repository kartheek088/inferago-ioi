"""Solution-fit comparison: what existing software already does, so Inferago recommends the smallest change.

Deliberately general. Each entry describes a product category at the level stated on its public product page and links
there; it makes no claims about specific features, limits or prices (those change — check the vendor's page). Used to
answer "configure or integrate before building" (Phase 9). Built from public information only.
"""

from __future__ import annotations

from app.lead_rules import EQUIPMENT, WHOLESALE

NOTE = "General overview from public product pages. Check the vendor's current features and pricing before advising a client."

CATALOGUE = [
    {"name": "Tally (TallyPrime)", "url": "https://tallysolutions.com/", "category": "Accounting, GST billing and inventory",
     "industries": [EQUIPMENT, WHOLESALE],
     "solves": "Billing, accounts and stock records — widely used by Indian small businesses.",
     "burden": "Not designed around field technicians or dealer self-service ordering.",
     "inferago_role": "Integrate: push orders / service invoices into Tally instead of re-typing them."},
    {"name": "Zoho FSM", "url": "https://www.zoho.com/fsm/", "category": "Field service management (SaaS)", "industries": [EQUIPMENT],
     "solves": "Work orders, technician scheduling and service records as a packaged product.",
     "burden": "Subscription per user, setup and data migration, and staff training; may be more than a small team needs.",
     "inferago_role": "Configure it for them, or build a lighter ServiceFlow if their process is simple."},
    {"name": "Zoho Inventory", "url": "https://www.zoho.com/inventory/", "category": "Inventory and order management (SaaS)", "industries": [WHOLESALE],
     "solves": "Stock, sales orders and shipments in one system.",
     "burden": "Subscription, migration of item masters, and changing how the team takes orders.",
     "inferago_role": "Configure and connect it to their accounting, or add a small dealer-order front end."},
    {"name": "Vyapar", "url": "https://vyaparapp.in/", "category": "Billing and inventory app for small businesses", "industries": [WHOLESALE],
     "solves": "GST billing and basic stock on mobile/desktop.",
     "burden": "Built for counter billing; dealer ordering and dispatch tracking may need separate tools.",
     "inferago_role": "Add the missing step (order intake / dispatch status) around what they already use."},
    {"name": "Odoo", "url": "https://www.odoo.com/", "category": "Modular ERP (open source + hosted)", "industries": [EQUIPMENT, WHOLESALE],
     "solves": "Apps for inventory, sales, field service, helpdesk and more.",
     "burden": "Broad system — implementation effort, hosting and training grow with each module.",
     "inferago_role": "Only for buyers who want a full ERP; otherwise a small targeted module is cheaper to adopt."},
    {"name": "Google AppSheet", "url": "https://about.appsheet.com/", "category": "No-code apps on top of spreadsheets",
     "industries": [EQUIPMENT, WHOLESALE],
     "solves": "Simple mobile forms and lists built from Google Sheets/Excel data.",
     "burden": "Needs someone to build and maintain it; integrations and permissions get complex as needs grow.",
     "inferago_role": "Quick pilot: turn their existing spreadsheet into a technician/order app before any custom build."},
    {"name": "WhatsApp Business", "url": "https://business.whatsapp.com/", "category": "Customer messaging", "industries": [EQUIPMENT, WHOLESALE],
     "solves": "Where many Chennai buyers already receive orders and service requests.",
     "burden": "Requests stay scattered across chats; no tracking or reporting by itself.",
     "inferago_role": "Keep WhatsApp as the front door and log requests/orders into one tracker (with consent and opt-out)."},
]


def alternatives(industry: str | None, tools: set[str]) -> dict:
    items = [x for x in CATALOGUE if industry in x["industries"]]
    uses = [x["name"] for x in items if any(t in x["name"].lower() for t in tools)]
    return {"note": NOTE, "already_mentioned": uses, "options": items}
