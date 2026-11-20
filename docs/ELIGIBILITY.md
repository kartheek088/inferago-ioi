# Eligibility engine

`backend/app/eligibility.py` — deterministic, versioned (`ENGINE_VERSION`), unit-tested.
**Decision support only — not legal or tax advice.** AI never decides mandatory eligibility.

## Profile (real facts only — `backend/app/profile.py`)

Sole proprietorship · Tamil Nadu, India · Udyam/MSME registered · PAN proprietor-linked ·
**GST not registered** · no corporate project credentials · 0 dedicated employees ·
turnover **not established** · no certifications/insurance recorded · DSC not recorded.
Owner can record real changes via Settings → profile overrides (e.g. `gst_registered: true`).
Services cannot be changed there.

## Requirements

Sources of requirements: rule extraction from post/page text, tender documents (with page
references), classifier geography restrictions, and manual entry. Each has `scope`
(`project` or `vendor_registration`), `mandatory` (false when worded as preferred/desirable),
parameters and evidence.

Checked keys: country restriction, India-based providers accepted, legal entity, proprietorship
acceptance, GST, PAN, Udyam/MSME, minimum turnover, prior experience, similar-work certificates,
workforce, technical certifications, security certifications, insurance, EMD, digital signature,
registration fee, tax/invoicing, subcontracting permission, consortium permission, vendor
registration, project-specific restriction.

Notable rules:
- Unknown profile facts **never satisfy** a requirement (e.g. turnover not established → failed,
  unless an MSME exemption is mentioned → clarification).
- Individual "N years of experience" in a job/contract post → clarification (founder's personal
  experience), not a corporate-credential failure.
- Certification mentions count only with requirement wording ("must", "certified", "required"…);
  "help us reach SOC2" is work, not a requirement.
- EMD/fees/DSC/insurance → clarification questions (often obtainable / MSE-exempt).
- "Remote (US only)" → hard, mandatory restriction. "Remote (EU)" → soft, non-mandatory.

## Outcomes

| Outcome | When |
|---|---|
| `eligible` | Every identified requirement satisfied (unstated requirements remain unverified). |
| `potentially_eligible` | No mandatory failure; some satisfied; some need clarification. |
| `unclear` | Requirements exist but none could be confirmed. |
| `unknown` | No requirements identified for this scope. |
| `partner_route` | Mandatory failures are all *capacity* items (turnover, experience, GST, certifications, workforce, entity type…) and subcontracting/consortium is not explicitly prohibited. |
| `not_eligible` | Any mandatory absolute failure (country, India not accepted, project restriction) or capacity failures with subcontracting prohibited and no consortium. |

Every assessment returns: reason, evidence, satisfied, missing, mandatory failures,
clarification questions, recommended next action. Project and vendor-registration scopes are
assessed and stored separately. `not_eligible` sets every score's effective total to 0 and
blocks outreach drafting.

## AI review (advisory)

With AI configured (OpenRouter, or Claude if `IOI_ANTHROPIC_API_KEY` is set), the review agent
(`backend/app/ai/agent.py`) reads the
opportunity and its source pages, records facts only with a verbatim quote, and may submit extra
clauses — which go through `extract_requirements` and `evaluate_requirement` like any other text.
The model then gives its own verdict (`eligible`, `eligible_with_clarifications`, `partner_route`,
`not_eligible`, `insufficient_information`). That verdict is stored in `ai_reviews` next to the rule
outcome; it never changes the rule outcome or the scores. When the two disagree, the review is marked
`agrees_with_rules = false` and the opportunity is flagged `needs_manual_review`.
