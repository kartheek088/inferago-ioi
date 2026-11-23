"""Social Commerce Intelligence (acquisition channel `social_commerce`).

A pipeline for Chennai businesses that sell through Instagram, Facebook and WhatsApp Business.
It is independent of the B2B equipment-service / wholesale-distribution pipeline: its own campaign,
discovery jobs, categories, geography rules, qualification engine (S0-S3) and research agent.

What it shares with B2B, deliberately: company identity, public contacts, evidence, outreach
approval, the sales pipeline and payments. Approved social leads become deals in the same tables.

Nothing here scrapes a private profile, a DM, a WhatsApp chat, a follower list or anything behind a
login or CAPTCHA. Sources that need access IOI does not have are reported unavailable, not faked.
"""
