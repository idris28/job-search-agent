"""Claude (Anthropic API) provider for the same tasks as the OpenAI one."""

from __future__ import annotations

from .llm import BaseLLM, T

# Server-side refusal fallback: if Claude declines a request on policy grounds, the API
# re-runs it on a suitable fallback model inside the same call.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ClaudeLLM(BaseLLM):
    def __init__(self, api_key: str, model: str, *, effort: str | None = None, client=None):
        super().__init__()
        if client is None:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key, max_retries=4)
        self.client = client
        self.model = model
        self.effort = effort

    def _common(self, instructions: str, user_input: str) -> dict:
        extra = {"output_config": {"effort": self.effort}} if self.effort else {}
        return dict(
            **extra,
            model=self.model,
            max_tokens=16000,
            system=instructions,
            messages=[{"role": "user", "content": user_input}],
            betas=[_FALLBACK_BETA],
            fallbacks="default",
        )

    def _count(self, resp) -> None:
        u = getattr(resp, "usage", None)
        if u is not None:
            self._add_tokens((u.input_tokens or 0) + (u.output_tokens or 0))

    @staticmethod
    def _check(resp) -> None:
        if resp.stop_reason == "refusal":
            cat = getattr(resp.stop_details, "category", None) if resp.stop_details else None
            raise RuntimeError(f"Claude declined the request (category: {cat})")
        if resp.stop_reason == "max_tokens":
            raise RuntimeError("Claude response hit max_tokens before finishing")

    def _parse(self, instructions: str, user_input: str, schema: type[T]) -> T:
        resp = self.client.beta.messages.parse(
            **self._common(instructions, user_input),
            output_format=schema,
        )
        self._count(resp)
        self._check(resp)
        if resp.parsed_output is None:
            raise RuntimeError("Claude returned no parsable output")
        return resp.parsed_output

    def _text(self, instructions: str, user_input: str) -> str:
        resp = self.client.beta.messages.create(
            **self._common(instructions, user_input),
        )
        self._count(resp)
        self._check(resp)
        return "".join(b.text for b in resp.content if b.type == "text").strip()
