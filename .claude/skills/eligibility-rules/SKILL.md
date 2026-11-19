---
name: eligibility-rules
description: Change or extend IOI eligibility requirement extraction/evaluation and scoring without breaking the hard gates — use when touching eligibility.py, scoring.py or profile.py.
---

# Eligibility & scoring changes

Invariants (each has tests in `backend/tests/test_units.py` / `test_workflows.py`):
- Profile facts come only from `profile.py` + owner overrides. Never invent turnover, staff,
  certifications, projects, references or services.
- Unknown is never satisfied. Missing profile data → `failed` (cannot evidence) or `clarify`.
- Mandatory failure → outcome `not_eligible` or `partner_route`; `not_eligible` forces every
  score's `effective_total` to 0 and blocks outreach drafting. Chain potential cannot override it.
- Project and vendor-registration scopes are assessed separately.
- Every outcome carries reason, evidence, satisfied, missing, mandatory failures,
  clarifications and next action, plus the not-legal-advice disclaimer.
- Score components each report value/max/known/explanation; component maxima sum to 100.
- AI may suggest text but must not decide mandatory eligibility.

Workflow: add a regex to `RULES` (and parameter parsing in `_params_for`) → add evaluation in
`evaluate_requirement` → add unit tests for satisfied / failed / clarify → update
`docs/ELIGIBILITY.md` → `scripts/test.sh`. Bump `ENGINE_VERSION` when outcomes change.
