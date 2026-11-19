"""Import researched vendor / partner programmes (Pipeline B/C) into IOI.

Each programme becomes an opportunity (category implementation_partnership / vendor_onboarding)
linked to the vendor organisation, with:
  - evidence = the official page URL + a summary of what that page says (checked 2026-11-20)
  - eligibility requirements taken ONLY from the cited page, evaluated by the deterministic engine.

Facts change — re-check the official page before applying. Idempotent: re-running updates in place.

    cd backend && uv run python ../scripts/seed_partner_programmes.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import delete, select  # noqa: E402

from app.db import SessionLocal, utcnow  # noqa: E402
from app.evaluation import evaluate_opportunity  # noqa: E402
from app.models import EligibilityRequirement, Evidence, Opportunity, Source  # noqa: E402
from app.normalize import canonical_url, content_hash  # noqa: E402
from app.pipeline import resolve_organisation  # noqa: E402
from app.source_registry import seed_sources  # noqa: E402

CHECKED = "checked 2026-11-20"


def R(key, text, mandatory=True, **params):
    return {"key": key, "text": text, "mandatory": mandatory, "parameters": params}


# (key, vendor, website, title, url, category, services, region note, summary, requirements)
PROGRAMMES = [
    ("zoho", "Zoho Corporation", "https://www.zoho.com", "Zoho Partner Program (consulting / implementation partner)",
     "https://www.zoho.com/partners/partner-tiers.html", "implementation_partnership", ["integration", "internal_apps", "automation"],
     "Zoho is headquartered in Chennai, Tamil Nadu.",
     "Free to join (application → evaluation → partner agreement → onboarding). Authorized tier: cross USD 5,000 revenue threshold, "
     "acquire required Zoho certifications and show implementation successes within six months of onboarding, otherwise status is "
     "re-evaluated. Advanced/Premium tiers are points-based. Cannot hold more than one partnership type at once. Page does not mention GST "
     "or whether individuals may join.",
     [R("technical_certifications", "Acquire required Zoho product certifications within six months of onboarding", mandatory=False),
      R("project_restriction", "Cross the USD 5,000 Zoho revenue threshold within six months of onboarding")]),
    ("odoo", "Odoo S.A.", "https://www.odoo.com", "Odoo Partnership (Learning / Ready partner, India)",
     "https://www.odoo.com/en_IN/become-a-partner", "implementation_partnership", ["integration", "internal_apps", "backend"], "",
     "India pricing: Learning partner Rs 32,245 per year with no sales/certification requirement; Ready Rs 1,61,229 with 10 new Enterprise "
     "users per year and 1 certified internal resource; Silver 75 users, 3 certified, 70% retention; Gold 300 users, 6 certified, 80% "
     "retention. Certification exam pass mark 70%.",
     [R("registration_fee", "Learning partner annual fee Rs 32,245 (Ready/Silver/Gold Rs 1,61,229)", amount_text="Rs 32,245"),
      R("technical_certifications", "Ready level needs 1 Odoo-certified internal resource (not needed for Learning)", mandatory=False),
      R("project_restriction", "Ready level needs 10 new Enterprise users sold per year (not needed for Learning)", mandatory=False)]),
    ("frappe", "Frappe Technologies", "https://frappe.io", "Frappe / ERPNext Partner Program",
     "https://docs.frappe.io/partner-guide/how-to-become-a-frappe-partner", "implementation_partnership", ["integration", "internal_apps", "backend"],
     "Indian company (Mumbai). ERPNext is open-source.",
     "No annual partnership fee (former USD 1,450 fee removed). New applicants start as Beginner (no public listing). Bronze (first listed "
     "tier) needs: an IT services business verifiable via website (proof of registered company address may be required), at least two "
     "full-time team members holding complete ERPNext or Frappe Framework certifications from Frappe School, and Frappe Cloud customers "
     "generating at least USD 100 per month.",
     [R("workforce", "At least two full-time team members holding ERPNext/Frappe Framework certifications", min_count=2),
      R("technical_certifications", "Complete ERPNext or Frappe Framework certification from Frappe School", names=["ERPNext certification"]),
      R("legal_entity", "IT services business verifiable via website; proof of registered company address may be required", mandatory=False),
      R("project_restriction", "Frappe Cloud customers generating at least USD 100 MRR")]),
    ("tally", "Tally Solutions", "https://tallysolutions.com", "Tally Marketplace — TDL solution developer",
     "https://help.tallysolutions.com/developer-reference/", "implementation_partnership", ["integration", "automation"],
     "Huge SME install base in India — Tally integrations are a common need.",
     "Developers submit interest via Tally Track (Marketplace banner); Tally reviews and grants Developer Portal upload access. Help centre "
     "lists baseline commercials of 45% developer / 35% seller partner (varies by campaign). New solutions must use the Inscribed V2 "
     "format; built with TallyPrime Developer (TDL). Registered company name must match the Tally Developer Hub account. No published "
     "certification or fee requirement found.",
     [R("vendor_registration", "Submit interest via Tally Track; Tally reviews before granting Developer Portal access")]),
    ("freshworks", "Freshworks", "https://www.freshworks.com", "Freshworks Solution Partner Program",
     "https://www.freshworks.com/company/partners/home/partner-program-faq/faqs/", "implementation_partnership", ["integration", "automation"],
     "Freshworks is headquartered in Chennai.",
     "No cost to become a Solution Partner. Tiers registered → authorised → preferred. Open to 'a legitimate business with a website' via "
     "registration form. Authorised/Preferred must sign the partnership agreement; directory listing requires Authorised.",
     [R("project_restriction", "Must be a legitimate business with a website (registration form review)")]),
    ("microsoft", "Microsoft", "https://partner.microsoft.com", "Microsoft AI Cloud Partner Program (Dynamics 365 / Power Platform / Azure)",
     "https://partner.microsoft.com/en-us/partnership", "implementation_partnership", ["integration", "automation", "internal_apps"], "",
     "Free enrolment in three steps (account + basic company information). Organisation address and legal contact required; depending "
     "on country a business registration number may be needed. Microsoft verifies email ownership and employment. Designations/tiers "
     "need further skilling and performance.",
     [R("legal_entity", "Business registration number may be required depending on country", mandatory=False)]),
    ("salesforce", "Salesforce", "https://www.salesforce.com", "Salesforce Consulting Partner Program",
     "https://www.salesforce.com/partners/consulting-partner-program/", "implementation_partnership", ["integration", "automation"], "",
     "FY27 consulting tiers (Summit/Select) weight certifications and verification. Third-party guides describe a minimum of two "
     "Salesforce certifications across the company (new partners may get time to reach it).",
     [R("technical_certifications", "Company must hold Salesforce certifications (commonly cited minimum: two)", names=["Salesforce certification"])]),
    ("hubspot", "HubSpot", "https://www.hubspot.com", "HubSpot Solutions Partner Program",
     "https://www.hubspot.com/2026-entry-and-tiers-policy-for-hubspot-solutions-partners", "implementation_partnership", ["integration", "automation"], "",
     "From 15 July 2026 all partners must buy Partner Program Membership (USD 400/month), waived if net product subscription exceeds "
     "USD 400/month after discounts. From January 2027 partners need >0 sourced points in a trailing 12 months. Onboarding and training "
     "required.",
     [R("registration_fee", "Partner Program Membership USD 400 per month (waivable above USD 400/month net subscription)"),
      R("project_restriction", "Maintain >0 sourced points in trailing 12 months (from Jan 2027)")]),
    ("n8n", "n8n", "https://n8n.io", "n8n Expert Partner Program (+ affiliate)",
     "https://n8n.io/partners", "implementation_partnership", ["automation", "integration", "api"],
     "Directly matches the n8n Jobs leads IOI collects.",
     "Expert Partner Program is a closed pilot with a waitlist, aimed at system integrators and agencies implementing n8n; admission by "
     "application and selection. Separate open affiliate programme (30% revenue share).",
     [R("project_restriction", "Closed pilot — waitlist, application and selection (agencies / system integrators)")]),
    ("make", "Make (Celonis)", "https://www.make.com", "Make Solution Partner Program (+ affiliate for freelancers)",
     "https://www.make.com/en/solution-partners", "implementation_partnership", ["automation", "integration", "api"], "",
     "Solution Partner Program is free for qualifying applicants and designed for agencies and consultants automating business "
     "processes; Silver/Gold/Platinum tiers based on projects, a team of certified individuals and customer satisfaction. Affiliate "
     "programme open to anyone including freelancers (35% commission for 12 months).",
     [R("technical_certifications", "Tiers assessed on maintaining a team of Make-certified individuals", mandatory=False),
      R("project_restriction", "Designed for agencies and consultants; project success and customer satisfaction assessed")]),
    ("zapier", "Zapier", "https://zapier.com", "Zapier Solution Partner Program",
     "https://zapier.com/l/solution-partner", "implementation_partnership", ["automation", "integration"], "",
     "For businesses offering consulting, implementation or managed services; replaced the old Experts programme. Criteria per tier are "
     "in the partner portal; applications reviewed with a response in about 21 business days; active engagement required.",
     [R("vendor_registration", "Apply via form; tier criteria published in Zapier partner portal")]),
    ("kissflow", "Kissflow", "https://kissflow.com", "Kissflow Partner Program (implementation / referral / reseller)",
     "https://kissflow.com/partners/faq/", "implementation_partnership", ["automation", "internal_apps"],
     "Kissflow is a Chennai-based low-code workflow company.",
     "Reseller, technology, implementation and referral partnerships, each with its own requirements. Partner FAQ states applicants need "
     "their own sales, pre-sales, marketing and delivery staff. Free training and certifications after onboarding.",
     [R("project_restriction", "Applicant must have own sales, pre-sales, marketing and delivery staff")]),
    ("netsuite", "Oracle NetSuite", "https://www.netsuite.com", "Oracle NetSuite Solution Provider Program",
     "https://www.netsuite.com/portal/partners.shtml", "implementation_partnership", ["integration"], "",
     "Requires demonstrated sales/implementation experience with accounting, ERP, CRM and/or ecommerce applications, dedicated staff, "
     "and onboarding training and certification. Regional minimums may apply.",
     [R("prior_experience", "Demonstrated sales/implementation credentials with accounting, ERP, CRM or ecommerce applications"),
      R("project_restriction", "Dedicated staff for the NetSuite practice")]),
    ("sap", "SAP", "https://www.sap.com", "SAP PartnerEdge — Build",
     "https://www.sap.com/partners/partner-program/build.html", "implementation_partnership", ["integration", "backend"], "",
     "Build partners need a go-to-market-ready solution, an Application Readiness Check of its architecture, an annual business plan "
     "(go-to-market, validated opportunities, pipeline) and technical staff skilled in SAP technologies. Annual programme fee per the "
     "PartnerEdge Program Guide (amount not public).",
     [R("registration_fee", "Annual PartnerEdge programme fee (amount in Program Guide)"),
      R("project_restriction", "Go-to-market-ready solution, Application Readiness Check and annual business plan required")]),
    ("uipath", "UiPath", "https://www.uipath.com", "UiPath Partner Network (Registered tier)",
     "https://www.uipath.com/become-a-partner", "implementation_partnership", ["automation"], "",
     "Registered is the entry membership (public documentation, free training, forum, marketplace); technology partner programme has a "
     "free self-service tier. Higher business-partner tiers expect company size, expertise and customers. A regional distributor may run onboarding.",
     [R("vendor_registration", "Apply to join the UiPath Partner Network; a regional distributor may handle onboarding")]),
    ("automation_anywhere", "Automation Anywhere", "https://www.automationanywhere.com", "Automation Anywhere Pinnacle Partner Program",
     "https://www.automationanywhere.com/partners/become-a-partner", "implementation_partnership", ["automation"], "",
     "Online registration and acceptance of the Pinnacle Foundational Partner Agreement. Verified Services Partner track requires training, "
     "certifications and success criteria; Authorized Sales Partner must meet accreditation within 90 days.",
     [R("technical_certifications", "Verified Services Partner track requires Automation Anywhere certifications", mandatory=False),
      R("vendor_registration", "Register online and accept the Pinnacle Foundational Partner Agreement")]),
    ("aws", "Amazon Web Services", "https://aws.amazon.com", "AWS Partner Network (Services Path)",
     "https://aws.amazon.com/partners/services-tiers/", "implementation_partnership", ["backend", "api"], "",
     "Joining APN is free via AWS Partner Central. Select tier: USD 2,500/year and (per 2022 guide) 4 AWS accredited professionals "
     "(2 technical, 2 business).",
     [R("registration_fee", "Select tier annual APN fee USD 2,500 (joining is free)", mandatory=False),
      R("workforce", "Select tier: 4 AWS accredited professionals (2 technical, 2 business)", mandatory=False, min_count=4)]),
    ("google_cloud", "Google Cloud", "https://cloud.google.com", "Google Cloud Partner Advantage (Member)",
     "https://cloud.google.com/partners/become-a-partner", "implementation_partnership", ["backend", "api"], "",
     "Entry level is Member; enrolling person must be authorised to sign the Partner Advantage agreement for the organisation. "
     "Partner and Premier levels require completing further tasks. Cost of Member tier not confirmed.",
     [R("vendor_registration", "Enrol as Member; signatory must be authorised to sign the Partner Advantage agreement")]),
    ("shopify", "Shopify", "https://www.shopify.com", "Shopify Partner Program",
     "https://help.shopify.com/en/partners/about", "implementation_partnership", ["integration", "api", "backend"], "",
     "Free; basic access on acceptance of the Shopify Partner Program Agreement. Free development stores. USD 19 one-time fee only for "
     "public App Store revenue share (not for custom/private apps). Tiers from Registered upward.",
     [R("project_restriction", "Accept the Shopify Partner Program Agreement", satisfied=True)]),
    ("razorpay", "Razorpay", "https://razorpay.com", "Razorpay Partner Program (developer / agency referral)",
     "https://razorpay.com/docs/partners/", "vendor_onboarding", ["integration", "api"], "Indian payments company.",
     "Free; open to individuals and organisations; no physical documents to register; partners can only onboard merchants in their "
     "registration country; account activation and KYC needed for commissions. Lists web developers, digital agencies and freelancers.",
     [R("legal_entity", "Open to individuals and organisations", accepted_types=["proprietorship", "company", "individual"]),
      R("pan", "KYC required for commission payouts")]),
    ("cashfree", "Cashfree Payments", "https://www.cashfree.com", "Cashfree Payments Partner Program",
     "https://docs.cashfree.com/docs/partner-program-introduction", "vendor_onboarding", ["integration", "api"], "Indian payments company.",
     "Referral programme: sign up online, Partner Dashboard, Partner KYC for activation; docs cite up to 0.25% commission per transaction paid monthly.",
     [R("pan", "Partner KYC required for account activation")]),
    ("payu", "PayU India", "https://payu.in", "PayU Partner Program",
     "https://partner.payu.in/", "vendor_onboarding", ["integration", "api"], "",
     "Referral partner programme listing developers, designers, agencies and freelancers as eligible; sign-up via partner.payu.in.",
     [R("legal_entity", "Developers, designers, agencies and freelancers eligible", accepted_types=["proprietorship", "individual", "company"])]),
    ("whatsapp_bsp", "WhatsApp BSPs (Interakt / AiSensy / Gupshup)", None, "WhatsApp Business API partner / reseller programmes (Interakt, AiSensy, Gupshup)",
     "https://www.interakt.shop/partner-program", "vendor_onboarding", ["integration", "automation", "api"],
     "Matches frequent 'WhatsApp automation' requests seen in n8n Jobs.",
     "Interakt: referral and white-label reseller tracks. AiSensy: affiliate to white-label, aimed at agencies and solution providers. "
     "Gupshup: partner portal with request review for suitability. Becoming a WhatsApp partner is normally via a BSP, not Meta directly.",
     [R("vendor_registration", "Apply to the BSP's partner programme; application reviewed for suitability")]),
    ("leadsquared", "LeadSquared", "https://www.leadsquared.com", "LeadSquared Partner Program (consulting / SI)",
     "https://www.leadsquared.com/partners/", "implementation_partnership", ["integration", "automation"], "Indian CRM (Bengaluru).",
     "Free; application reviewed by partner recruitment team. Main stated requirement: experience selling and implementing SaaS "
     "applications in a similar category. Online training and certification provided.",
     [R("prior_experience", "Demonstrated experience selling and implementing SaaS applications in a similar category")]),
    ("monday", "monday.com", "https://monday.com", "monday.com Partner Program (Authorized tier)",
     "https://monday.com/w/partners/onboarding", "implementation_partnership", ["automation", "internal_apps"], "",
     "Authorized (entry) tier: USD 0 ARR, no obligations or targets. Bronze and above need ARR / project thresholds.",
     [R("project_restriction", "Authorized tier: no ARR requirement, no obligations or targets", satisfied=True)]),
    ("airtable", "Airtable", "https://airtable.com", "Airtable Services Partner Program",
     "https://airtable.com/partners", "implementation_partnership", ["internal_apps", "automation"], "",
     "Free; partners accredited after completing assigned trainings and testing; accredited partners eligible for lead referrals and "
     "subcontracting with Airtable. Bronze/Silver/Gold tiers.",
     [R("technical_certifications", "Accreditation after Airtable trainings and testing", mandatory=False)]),
    ("bubble", "Bubble", "https://bubble.io", "Bubble Agency tiers",
     "https://bubble.io/support/en/articles/11750652-agency-tier-criteria", "implementation_partnership", ["internal_apps"], "",
     "No application: agencies reviewed monthly and tiered automatically. Bronze: USD 1–9,999 annualised value in the Bubble ecosystem "
     "and 100% Bubble-certified developers.",
     [R("technical_certifications", "Bronze requires 100% Bubble-certified developers", names=["Bubble certification"]),
      R("project_restriction", "At least USD 1 annualised value generated in the Bubble ecosystem")]),
    ("busy", "BUSY Infotech", "https://busy.in", "BUSY accounting software partner / reseller",
     "https://busy.in/become-a-partner", "vendor_onboarding", ["integration"], "Indian GST accounting software used by SMEs.",
     "Open to entrepreneurs, IT vendors, software distributors, CAs and GST practitioners; brief training session at onboarding; partner "
     "training and certification provided. No fee/margin published.",
     [R("vendor_registration", "Apply via partner form; onboarding training session")]),
    ("retool", "Retool", "https://retool.com", "Retool Agency Program",
     "https://community.retool.com/t/update-on-the-retool-agency-plan/67261", "implementation_partnership", ["internal_apps"], "",
     "Agency Program is retiring on 31 August 2027 and is not taking on new agencies; consolidating into one partner programme "
     "(criteria not published).",
     [R("project_restriction", "Agency Program not accepting new agencies", satisfied=False)]),
    ("appsmith", "Appsmith", "https://www.appsmith.com", "Appsmith Partner Program",
     "https://www.silicon.co.uk/press-release/appsmith-launches-partner-program-to-empower-businesses-to-build-business-critical-applications",
     "implementation_partnership", ["internal_apps"], "Indian-founded low-code company (Bengaluru).",
     "Launched January 2023 for freelancers, agencies, VARs, system integrators and technology companies. Eligibility criteria not published.",
     [R("legal_entity", "Network includes freelancers and agencies", accepted_types=["proprietorship", "individual", "company"])]),
]


def main() -> None:
    with SessionLocal() as db:
        seed_sources(db)
        src = db.scalar(select(Source).where(Source.key == "partner_programmes"))
        for key, vendor, site, title, url, category, services, note, summary, reqs in PROGRAMMES:
            org = resolve_organisation(db, vendor, site)
            if org:
                org.accepts_external_vendors = True
            dedupe = f"programme:{key}"
            opp = db.scalar(select(Opportunity).where(Opportunity.dedupe_key == dedupe))
            text = f"{summary}\n\n{note}".strip()
            if opp is None:
                opp = Opportunity(dedupe_key=dedupe, source_id=src.id, status="new")
                db.add(opp)
            opp.title, opp.summary, opp.description = title, summary[:400], text
            opp.category, opp.pipeline = category, "B_vendor"
            opp.classification_method, opp.classification_confidence = "manual", 1.0
            opp.classification_evidence = [f"Researched partner programme ({CHECKED}); source: {url}"]
            opp.services_matched, opp.signals_matched = services, []
            opp.organisation_id = org.id if org else None
            opp.canonical_url, opp.content_hash, opp.retrieved_at = canonical_url(url), content_hash(title, text), utcnow()
            opp.remote_ok = True
            db.flush()
            db.execute(delete(EligibilityRequirement).where(EligibilityRequirement.opportunity_id == opp.id, EligibilityRequirement.origin == "research"))
            db.execute(delete(Evidence).where(Evidence.opportunity_id == opp.id, Evidence.evidence_type == "manual"))
            ev = Evidence(opportunity_id=opp.id, organisation_id=opp.organisation_id, source_id=src.id, evidence_type="manual",
                          url=url, excerpt=f"Summary of official page ({CHECKED}): {summary}")
            db.add(ev)
            db.flush()
            for r in reqs:
                db.add(EligibilityRequirement(opportunity_id=opp.id, scope="project", requirement_key=r["key"], mandatory=r["mandatory"],
                                              text=r["text"], parameters=r["parameters"], origin="research", evidence_id=ev.id))
            db.flush()
            evaluate_opportunity(db, opp)
            print(f"{opp.eligibility_outcome:22} {opp.priority:6} {title}")
        db.commit()


if __name__ == "__main__":
    main()
