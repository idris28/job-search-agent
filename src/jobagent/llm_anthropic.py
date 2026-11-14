"""Claude (Anthropic API) provider for the same tasks as the OpenAI one."""

from __future__ import annotations

from .llm import CONTACT_INSTRUCTIONS, CONTENT_RESEARCH_INSTRUCTIONS, MATCH_INSTRUCTIONS, BaseLLM, T
from .models import MatchResult

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

    def _common(self, instructions: str, user_input: str, cached_prefix: str = "") -> dict:
        extra = {"output_config": {"effort": self.effort}} if self.effort else {}
        # Prompt caching: everything up to the marked block (the instructions, then the resume or
        # template) is stored for a few minutes and re-read at a fraction of the price on the next
        # job. A prefix shorter than the model's minimum is simply not cached.
        content = ([{"type": "text", "text": cached_prefix, "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": user_input}] if cached_prefix else user_input)
        return dict(
            **extra,
            model=self.model,
            max_tokens=16000,
            system=instructions,
            messages=[{"role": "user", "content": content}],
            betas=[_FALLBACK_BETA],
            fallbacks="default",
        )

    def _count(self, resp) -> None:
        u = getattr(resp, "usage", None)
        if u is not None:
            read = getattr(u, "cache_read_input_tokens", 0) or 0
            written = getattr(u, "cache_creation_input_tokens", 0) or 0
            self._add_tokens((u.input_tokens or 0) + (u.output_tokens or 0) + read + written)
            with self._lock:
                self.cache_read_tokens += read

    @staticmethod
    def _check(resp) -> None:
        if resp.stop_reason == "refusal":
            cat = getattr(resp.stop_details, "category", None) if resp.stop_details else None
            raise RuntimeError(f"Claude declined the request (category: {cat})")
        if resp.stop_reason == "max_tokens":
            raise RuntimeError("Claude response hit max_tokens before finishing")

    def _parse(self, instructions: str, user_input: str, schema: type[T], *,
               cached_prefix: str = "") -> T:
        resp = self.client.beta.messages.parse(
            **self._common(instructions, user_input, cached_prefix),
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

    # --- batch scoring -----------------------------------------------------------------
    #
    # The Message Batches API takes the same requests, answers them later (most within the hour,
    # 24 hours at most) and charges half. A batch request cannot use the refusal fallback, so a
    # declined request comes back as a refusal and that job is simply scored another time.

    def submit_scores(self, profile: dict, prefs, jobs: list[tuple[str, object]]) -> str:
        """Send one scoring request per (custom_id, job) as a batch. Returns the batch id."""
        from anthropic import transform_schema

        fmt = {"type": "json_schema", "schema": transform_schema(MatchResult)}
        requests = []
        for custom_id, job in jobs:
            params = self._common(MATCH_INSTRUCTIONS, "JOB POSTING:\n" + job.as_prompt_text(),
                                  self._candidate(profile, prefs))
            del params["betas"], params["fallbacks"]
            params["output_config"] = {**params.get("output_config", {}), "format": fmt}
            requests.append({"custom_id": custom_id, "params": params})
        return self.client.messages.batches.create(requests=requests).id

    def batch_done(self, batch_id: str) -> bool:
        return self.client.messages.batches.retrieve(batch_id).processing_status == "ended"

    def collect_scores(self, batch_id: str) -> dict[str, MatchResult | Exception]:
        """The answers of a finished batch by custom_id: a score, or why there is none."""
        out: dict[str, MatchResult | Exception] = {}
        for item in self.client.messages.batches.results(batch_id):  # they arrive in any order
            result = item.result
            if result.type != "succeeded":
                error = getattr(getattr(result, "error", None), "error", None)
                out[item.custom_id] = RuntimeError(f"the batch request {result.type}"
                                                   + (f": {error.message}" if error is not None else ""))
                continue
            try:
                self._count(result.message)
                self._check(result.message)
                text = next(b.text for b in result.message.content if b.type == "text")
                match = MatchResult.model_validate_json(text)
                match.score = max(0, min(100, match.score))
                out[item.custom_id] = match
            except Exception as e:  # noqa: BLE001 - one unreadable answer must not lose the others
                out[item.custom_id] = e
        return out

    def research_email_content(self, roles: str, country: str,
                               max_searches: int = 4) -> str | None:
        """Claude's server-side web search for recruiter guidance; notes with source URLs."""
        user = (f"Roles: {roles}\nCountry: {country}\n"
                "Research what email content attracts recruiters for these roles here.")
        return self._searched(CONTENT_RESEARCH_INSTRUCTIONS, user, max_searches)

    def find_contact(self, company: str, location: str | None) -> dict | None:
        """Web-search the company's own site for a published application address."""
        import json
        import re

        text = self._searched(CONTACT_INSTRUCTIONS, f"Company: {company}\nJob location: {location or 'not given'}", 3)
        for blob in reversed(re.findall(r"\{[^{}]*\}", text or "")):
            try:
                found = json.loads(blob)
            except ValueError:
                continue
            if isinstance(found, dict) and "email" in found:
                return found if found.get("email") else None
        return None

    def _searched(self, instructions: str, user: str, max_searches: int) -> str | None:
        common = self._common(instructions, user)
        tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches}]
        messages = common.pop("messages")
        resp = None
        for _ in range(4):  # resume server-side pauses (pause_turn), bounded
            resp = self.client.beta.messages.create(**common, messages=messages, tools=tools)
            self._count(resp)
            if resp.stop_reason != "pause_turn":
                break
            messages = [messages[0], {"role": "assistant", "content": resp.content}]
        if resp is None or resp.stop_reason == "refusal":
            return None
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        return text or None
