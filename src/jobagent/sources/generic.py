"""Any careers/search page, browsed with Browserbase and read by the LLM."""

from __future__ import annotations

from ..config import ConfigError, SourceConfig
from ..models import JobPosting
from .base import Source, SourceContext, guess_remote_type


class GenericSource(Source):
    needs_browser = True

    @classmethod
    def validate(cls, cfg: SourceConfig) -> None:
        if not cfg.urls:
            raise ConfigError(f"Source '{cfg.name}' (generic) needs at least one entry in 'urls'")

    def fetch(self, ctx: SourceContext) -> list[JobPosting]:
        seen: dict[str, JobPosting] = {}
        for list_url in self.cfg.urls:
            page = ctx.browser.fetch(list_url)
            found = ctx.llm.extract_listings(page.text, page.links, page.url).listings
            ctx.log(f"{self.cfg.name}: {len(found)} listings on {list_url}")
            valid_hrefs = {l["href"] for l in page.links}
            for item in found:
                # Guard against hallucinated URLs: must be a link that was on the page.
                if item.url not in valid_hrefs or item.url in seen:
                    continue
                seen[item.url] = JobPosting(
                    title=item.title.strip(),
                    company=self.cfg.company or item.company or self.cfg.name,
                    url=item.url,
                    location=item.location,
                    remote_type=guess_remote_type(item.location, item.title),
                )

        # Visit detail pages for full descriptions (bounded, to control cost and time).
        for i, job in enumerate(seen.values()):
            if i >= self.cfg.max_detail_pages:
                break
            try:
                detail = ctx.browser.fetch(job.url, wait_ms=1500)
                job.description = detail.text[:20000]
                job.remote_type = (job.remote_type if job.remote_type != "unknown"
                                   else guess_remote_type(detail.text[:3000]))
            except Exception as e:  # noqa: BLE001
                ctx.log(f"{self.cfg.name}: detail fetch failed for {job.url}: {e}")
        return list(seen.values())
