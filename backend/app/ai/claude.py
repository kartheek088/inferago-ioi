"""Claude (Anthropic API) provider via the official `anthropic` SDK.

Used for every AI task when IOI_ANTHROPIC_API_KEY is set; otherwise the OpenRouter adapter (or no AI)
is used. Same contract as `OpenRouterClient.complete_json`: returns a Pydantic-validated object or
raises `AIUnavailable`, so every caller keeps its deterministic fallback.

- Structured output via `messages.parse(output_format=<Pydantic model>)`.
- Server-side refusal fallbacks enabled (`fallbacks="default"`); a remaining refusal → AIUnavailable.
- Collected text is passed as untrusted data inside <data> tags under the same system guard.
- Every call is logged to `ai_usage_logs` (tokens, latency, errors).
"""

import time
from typing import TypeVar

import anthropic
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai.openrouter import SYSTEM_GUARD, AIUnavailable
from app.config import get_settings
from app.models import AIUsageLog

T = TypeVar("T", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


def make_client(api_key: str) -> anthropic.Anthropic:
    """Factory (tests replace it). The SDK retries 429/5xx/connection errors itself."""
    return anthropic.Anthropic(api_key=api_key, max_retries=2, timeout=300.0)


class ClaudeClient:
    provider = "claude"

    def __init__(self, db: Session, client: anthropic.Anthropic | None = None) -> None:
        self.s = get_settings()
        if not self.s.claude_enabled:
            raise AIUnavailable("Claude disabled: set IOI_ANTHROPIC_API_KEY")
        self.db = db
        self.client = client or make_client(self.s.anthropic_api_key)
        self.calls = 0
        self.tokens = 0

    @property
    def model_name(self) -> str:
        return self.s.anthropic_model

    def complete_json(self, task: str, instruction: str, data: str, schema: type[T], *, max_tokens: int = 800) -> T:
        started = time.monotonic()
        try:
            res = self.client.beta.messages.parse(
                model=self.s.anthropic_model,
                # Room for adaptive thinking on top of the JSON answer.
                max_tokens=max(16000, max_tokens),
                betas=[FALLBACK_BETA],
                fallbacks="default",
                output_config={"effort": self.s.anthropic_effort},
                system=SYSTEM_GUARD,
                messages=[{"role": "user", "content": f"{instruction}\n\n<data>\n{data[:60000]}\n</data>"}],
                output_format=schema,
            )
        except anthropic.APIStatusError as exc:
            self._log(task, False, None, started, f"HTTP {exc.status_code}: {exc.message[:200]}")
            raise AIUnavailable(f"Claude call failed for {task}: HTTP {exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:
            self._log(task, False, None, started, f"Connection error: {exc}")
            raise AIUnavailable(f"Claude unreachable for {task}") from exc
        self.record_usage(task, res, started)
        if res.stop_reason == "refusal":
            raise AIUnavailable(f"Claude declined {task}")
        if res.stop_reason == "max_tokens" or res.parsed_output is None:
            raise AIUnavailable(f"Claude returned no valid {schema.__name__} for {task}")
        return res.parsed_output

    def record_usage(self, task: str, res, started: float, ok: bool | None = None) -> None:
        usage = getattr(res, "usage", None)
        pt = getattr(usage, "input_tokens", None)
        ct = getattr(usage, "output_tokens", None)
        self.calls += 1
        self.tokens += (pt or 0) + (ct or 0)
        success = ok if ok is not None else res.stop_reason not in ("refusal", "max_tokens")
        self._log(task, success, (pt, ct), started, None if success else f"stop_reason={res.stop_reason}", model=getattr(res, "model", None))

    def _log(self, task: str, ok: bool, tokens: tuple[int | None, int | None] | None, started: float, error: str | None, model: str | None = None) -> None:
        pt, ct = tokens or (None, None)
        self.db.add(AIUsageLog(
            task=task, model=model or self.s.anthropic_model, success=ok, prompt_tokens=pt, completion_tokens=ct,
            cost_usd=None, latency_ms=int((time.monotonic() - started) * 1000), error=error,
        ))
        self.db.flush()
