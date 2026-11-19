# Scoring

`backend/app/scoring.py`. Three **separate** 100-point algorithms. Every component returns
`value`, `max`, `known` and an `explanation`; the UI shows all of them.

- `known=false` → data missing; scores 0 but is **not** a negative finding.
- `known=true, value=0` → a negative finding (e.g. research ran and found no contact route).
- `raw_total` = sum of components. `effective_total` = 0 when project eligibility is
  `not_eligible` (mandatory disqualification overrides scores — including chain potential).

## Direct client (Pipeline A)

| Component | Max | Rule |
|---|---|---|
| service_fit | 25 | 1 approved service matched → 15, 2 → 20, 3+ → 25 |
| buying_signal | 30 | ≥2 strong → 30; 1 strong → 24 (+3 per moderate, cap 30); moderate only → 15; weak only → 6; none → 0 |
| business_scope | 15 | budget stated +6, description > 300 chars +4, timeline/deliverables +5 |
| verified_contact_route | 10 | verified route 10; unverified/platform route 4; researched & none 0 (known); not researched 0 (unknown) |
| external_vendor_likelihood | 10 | ≥2 positive indicators 10, 1 → 6 (−3 if also negatives); only negatives 2; none unknown |
| evidence_confidence | 10 | 1 item 4 / 2+ items 6; +3 if ≤30 days old (+1 if ≤90); +1 if classification ≥ 0.7 |

## Vendor / subcontracting (Pipeline B)

| Component | Max | Rule |
|---|---|---|
| external_partner_acceptance | 20 | evidence vendors accepted / vendor-type category 20; open public procurement 15; evidence not accepted 0; else unknown |
| technical_fit | 20 | 1 service 12, 2 → 16, 3+ → 20 |
| eligibility | 25 | eligible 25, potentially 15, partner route 10, unclear 5, not eligible 0, unknown → unknown |
| active_project_evidence | 15 | tender/procurement, or explicit request in subcontracting/direct category, or future deadline → 15; programme only 5 |
| onboarding_accessibility | 10 | vendor onboarding page found 10; verified contact only 5 |
| commercial_suitability | 10 | budget +4, domestic India +3, remote possible +3 |

## Opportunity chain potential (Pipeline C)

| Component | Max | Rule |
|---|---|---|
| verified_partner_programme | 30 | ≥1 **confirmed** partner-programme/implementation-partner relationship → 30. Hypotheses score 0. |
| recurring_project_demand | 25 | org has ≥3 opportunities 25, 2 → 15, 1 → unknown |
| relevant_customer_relationships | 20 | confirmed customer/vendor/contract relationships: 1 → 10, 2 → 15, 3+ → 20 |
| repeat_work_potential | 15 | confirmed repeat/related link 15; ongoing/maintenance/retainer wording 8 |
| authorised_introduction_route | 10 | confirmed referral route 10 |

## Priority (ranking)

`priority = effective score of the pipeline's primary algorithm (A→direct, B→vendor, C→chain)
+ geography bonus`. Bonus applies only to explicitly stated geography (default: Tamil Nadu +15,
India +8 — Settings). Irrelevant or disqualified → 0. Priority is for ranking only; it is not one
of the three scores.
