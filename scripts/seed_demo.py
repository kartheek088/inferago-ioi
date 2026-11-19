"""Load (or remove) clearly labelled DEMONSTRATION fixtures.

Demo records are flagged `is_demo=True`, titled "[DEMO] …", use the reserved `.example`
domain, and are shown with a DEMO badge in the UI. They are never real leads.

    cd backend && uv run python ../scripts/seed_demo.py           # load
    cd backend && uv run python ../scripts/seed_demo.py --remove  # remove
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import delete, select  # noqa: E402

from app.connectors.base import CollectedItem  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Opportunity, Organisation, Source  # noqa: E402
from app.pipeline import ingest_item  # noqa: E402
from app.source_registry import seed_sources  # noqa: E402

DEMO = [
    ("demo:1", "[DEMO] SEEKING FREELANCER | Demo Logistics | Chennai, Tamil Nadu",
     "SEEKING FREELANCER | Demo Logistics | Chennai, Tamil Nadu | Remote OK\nWe need a backend developer to build a REST API "
     "integration between our warehouse system and our ERP, and automate dispatch workflows. Budget Rs 3,00,000. Timeline 8 weeks.",
     "Demo Logistics", "https://demo-logistics.example"),
    ("demo:2", "[DEMO] Vendor registration open for IT service providers — Demo Manufacturing",
     "Demo Manufacturing invites vendor registration for software integration and process digitisation services. "
     "Vendors must have GST registration. Udyam-registered MSEs are welcome.",
     "Demo Manufacturing", "https://demo-manufacturing.example"),
    ("demo:3", "[DEMO] Looking for an implementation partner — Demo Health (US only)",
     "Demo Health is looking for an implementation partner for workflow automation. Remote (US only). Must be based in the US.",
     "Demo Health", "https://demo-health.example"),
]


def main() -> None:
    with SessionLocal() as db:
        seed_sources(db)
        if "--remove" in sys.argv:
            n = db.execute(delete(Opportunity).where(Opportunity.is_demo.is_(True))).rowcount
            db.execute(delete(Organisation).where(Organisation.is_demo.is_(True)))
            db.commit()
            print(f"Removed {n} demo opportunities")
            return
        src = db.scalar(select(Source).where(Source.key == "manual_url"))
        for ext, title, text, org, site in DEMO:
            out = ingest_item(db, src, None, CollectedItem(external_id=ext, url=f"{site}/post", title=title, content=text, org_name=org, org_website=site), is_demo=True, actor="demo-seed")
            print(ext, out.status, out.opportunity_id)
        db.commit()


if __name__ == "__main__":
    main()
