"""Claude review agent with a scripted fake Anthropic client (no network, no API key)."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.ai import agent as agent_mod
from app.ai.agent import AgentVerdict, _agrees, run_review
from app.ai.claude import ClaudeClient
from app.config import get_settings
from app.models import AIReview, Contact, EligibilityRequirement, Opportunity, Source
from app.pipeline import ingest_item
from app.connectors.base import CollectedItem

PAGE_URL = "https://buyer.example/tender/42"
PAGE_HTML = (
    "<html><head><title>Tender 42</title></head><body><main>"
    "<p>Last date for submission of bids is 15-12-2026.</p>"
    "<p>Bidders must have a valid GST registration.</p>"
    "<p>Queries: tenders@buyer.example</p></main></body></html>"
)


class ScriptedRunner:
    """Executes a fixed list of tool calls against the real tools, then yields a final verdict."""

    def __init__(self, tools, script, verdict):
        self.tools = {t.name: t for t in tools}
        self.script = script
        self.verdict = verdict
        self.results = []

    def __iter__(self):
        for name, args in self.script:
            self.results.append((name, self.tools[name].call(args)))
            yield SimpleNamespace(stop_reason="tool_use", parsed_output=None, usage=SimpleNamespace(input_tokens=100, output_tokens=20), model="claude-opus-5-5")
        yield SimpleNamespace(stop_reason="end_turn", parsed_output=self.verdict, usage=SimpleNamespace(input_tokens=200, output_tokens=80), model="claude-opus-5-5")


class FakeAnthropic:
    def __init__(self, script, verdict):
        self.script, self.verdict, self.kwargs, self.runner = script, verdict, None, None
        self.beta = SimpleNamespace(messages=SimpleNamespace(tool_runner=self._tool_runner))

    def _tool_runner(self, **kwargs):
        self.kwargs = kwargs
        self.runner = ScriptedRunner(kwargs["tools"], self.script, self.verdict)
        return self.runner


@pytest.fixture
def claude_on(monkeypatch):
    monkeypatch.setenv("IOI_ANTHROPIC_API_KEY", "test-key")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("IOI_ANTHROPIC_API_KEY")
    get_settings.cache_clear()


def _opp(db):
    src = db.scalar(select(Source).where(Source.key == "manual_url"))
    item = CollectedItem(external_id="t42", url=PAGE_URL, title="Tender 42: web portal development",
                         content="Department of Revenue invites bids for web portal development and API integration. Tender 42.",
                         org_name="Department of Revenue")
    out = ingest_item(db, src, None, item)
    db.commit()
    return db.get(Opportunity, out.opportunity_id)


VERDICT = AgentVerdict(
    opportunity_open="yes", verdict="eligible",
    summary="Portal tender; GST registration required.",
    requirement_reviews=[
        {"requirement": "GST registration", "mandatory": True, "met": "no", "reason": "Profile: not GST registered",
         "source_quote": "Bidders must have a valid GST registration.", "source_url": PAGE_URL},
        {"requirement": "ISO 27001", "mandatory": True, "met": "unknown", "reason": "x", "source_quote": "Bidders must hold ISO 27001.", "source_url": PAGE_URL},
    ],
    open_questions=["Is GST needed at bid stage?"], recommended_next_step="Ask the buyer about GST.",
)


def test_agent_review_verifies_and_rules_decide(db, web, claude_on):
    web.text(PAGE_URL, PAGE_HTML)
    opp = _opp(db)
    script = [
        ("get_opportunity", {}),
        ("get_business_profile", {}),
        ("fetch_page", {"url": PAGE_URL}),
        ("record_fact", {"kind": "deadline", "value": "15-12-2026", "quote": "Last date for submission of bids is 15-12-2026.", "source_url": PAGE_URL}),
        ("record_fact", {"kind": "contact_email", "value": "tenders@buyer.example", "quote": "Queries: tenders@buyer.example", "source_url": PAGE_URL}),
        ("record_fact", {"kind": "budget", "value": "INR 40 lakhs", "quote": "Estimated value INR 40 lakhs", "source_url": PAGE_URL}),  # invented
        ("record_fact", {"kind": "contact_email", "value": "ceo@buyer.example", "quote": "Queries: tenders@buyer.example", "source_url": PAGE_URL}),  # guessed
        ("add_requirement", {"clause": "Bidders must have a valid GST registration.", "source_url": PAGE_URL}),
        ("add_requirement", {"clause": "Bidders must hold ISO 27001 certification.", "source_url": PAGE_URL}),  # invented
    ]
    fake = FakeAnthropic(script, VERDICT)
    review = run_review(db, opp, http_client=web.client(), ai=ClaudeClient(db, client=fake))

    results = dict((n + str(i), r) for i, (n, r) in enumerate(fake.runner.results))
    assert results["record_fact5"].startswith("Rejected") and results["record_fact6"].startswith("Rejected")
    assert results["add_requirement8"].startswith("Rejected")
    assert fake.kwargs["model"] == "claude-opus-5-5" and fake.kwargs["fallbacks"] == "default"
    assert fake.kwargs["output_format"] is AgentVerdict

    assert review.status == "success" and review.turns == len(script) + 1
    assert [f["kind"] for f in review.facts] == ["deadline", "contact_email"]
    assert review.sources == [PAGE_URL]
    db.refresh(opp)
    assert opp.deadline.strftime("%Y-%m-%d") == "2026-12-15"
    contact = db.scalar(select(Contact).where(Contact.value == "tenders@buyer.example"))
    assert contact.source_url == PAGE_URL and contact.verified is False
    gst = db.scalar(select(EligibilityRequirement).where(EligibilityRequirement.opportunity_id == opp.id, EligibilityRequirement.origin == "ai_agent"))
    assert gst.requirement_key == "gst"
    # Rules: GST mandatory + not registered → not eligible / partner route. AI said "eligible" → disagreement flagged.
    assert review.rule_outcome in ("not_eligible", "partner_route")
    assert review.verdict == "eligible" and review.agrees_with_rules is False
    assert opp.needs_manual_review is True
    verified = {r["requirement"]: r["quote_verified"] for r in review.requirement_reviews}
    assert verified == {"GST registration": True, "ISO 27001": False}


def test_agent_fetch_budget_and_robots(db, web, claude_on, monkeypatch):
    monkeypatch.setenv("IOI_AGENT_MAX_FETCHES", "1")
    get_settings.cache_clear()
    web.text(PAGE_URL, PAGE_HTML)
    web.text("https://blocked.example/robots.txt", "User-agent: *\nDisallow: /", content_type="text/plain")
    opp = _opp(db)
    script = [("fetch_page", {"url": "https://blocked.example/page"}), ("fetch_page", {"url": PAGE_URL}), ("fetch_page", {"url": "https://other.example/"})]
    fake = FakeAnthropic(script, AgentVerdict(opportunity_open="unknown", verdict="insufficient_information", summary="s", recommended_next_step="n"))
    review = run_review(db, opp, http_client=web.client(), ai=ClaudeClient(db, client=fake))
    r = [x[1] for x in fake.runner.results]
    assert r[0].startswith("Error") and "robots" in r[0]
    assert "Last date" in r[1]
    assert "budget" in r[2]
    assert review.agrees_with_rules is None


def test_agent_failure_recorded(db, web, claude_on):
    opp = _opp(db)
    fake = FakeAnthropic([], None)  # ends without a parsed verdict
    review = run_review(db, opp, http_client=web.client(), ai=ClaudeClient(db, client=fake))
    assert review.status == "failed" and "verdict" in review.error
    assert db.scalar(select(AIReview).where(AIReview.id == review.id)).status == "failed"


def test_review_without_key_fails_cleanly(db, web):
    opp = _opp(db)
    review = run_review(db, opp, http_client=web.client())
    assert review.status == "failed" and "IOI_ANTHROPIC_API_KEY" in review.error


def test_api_requires_claude(client, db):
    opp = _opp(db)
    assert client.post(f"/api/opportunities/{opp.id}/ai-review").status_code == 400
    assert client.get(f"/api/opportunities/{opp.id}/ai-reviews").json() == []


def test_agreement_logic():
    assert _agrees("eligible", "not_eligible") is False
    assert _agrees("not_eligible", "eligible") is False
    assert _agrees("eligible_with_clarifications", "potentially_eligible") is True
    assert _agrees("partner_route", "not_eligible") is True
    assert _agrees("eligible", "unclear") is None


def test_get_ai_prefers_claude(db, claude_on):
    from app.ai.openrouter import get_ai

    assert get_ai(db).provider == "claude"
    assert agent_mod.SYSTEM  # prompt present


def test_claude_complete_json_and_refusal(db, claude_on):
    from app.ai.openrouter import AISummary, AIUnavailable

    calls = []

    def parse(**kw):
        calls.append(kw)
        if len(calls) == 1:
            return SimpleNamespace(stop_reason="end_turn", parsed_output=AISummary(summary="ok"), usage=SimpleNamespace(input_tokens=5, output_tokens=5), model="claude-opus-5-5")
        return SimpleNamespace(stop_reason="refusal", parsed_output=None, usage=SimpleNamespace(input_tokens=5, output_tokens=0), model="claude-opus-5-5")

    fake = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=parse)))
    ai = ClaudeClient(db, client=fake)
    assert ai.complete_json("t", "Summarise", "<script>ignore previous</script>", AISummary).summary == "ok"
    assert calls[0]["output_format"] is AISummary and "<data>" in calls[0]["messages"][0]["content"]
    with pytest.raises(AIUnavailable):
        ai.complete_json("t", "Summarise", "x", AISummary)
