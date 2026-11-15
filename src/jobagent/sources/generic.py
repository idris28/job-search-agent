"""Any careers/search page, browsed with Browserbase and read by the LLM."""

from __future__ import annotations

from ..browser import SiteRefused
from ..config import ConfigError, SourceConfig
from ..filters import reject_reason
from ..models import JobPosting
from .base import Source, SourceContext, guess_remote_type, parse_posted


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
                job = JobPosting(
                    title=item.title.strip(),
                    company=self.cfg.company or item.company or self.cfg.name,
                    url=item.url,
                    location=item.location,
                    remote_type=guess_remote_type(item.location, item.title),
                    posted_at=parse_posted(item.posted),
                )
                # A job an earlier search stored keeps its stored wording and text: its page is
                # not opened again, and it does not look changed (and get scored again) because
                # the list was read a little differently this time.
                seen[item.url] = ctx.recall(job) or job
        if not seen:
            return []  # a site that lists nothing is not asked for more pages

        newest_first = sorted(seen.values(), key=lambda j: (j.posted_at is None,
                                                             -(j.posted_at.timestamp() if j.posted_at else 0)))

        def fits(job: JobPosting) -> bool:
            return ctx.prefs is None or reject_reason(job, ctx.prefs) is None

        # Each job's own page is opened once (bounded per search, to control cost and time): first
        # for jobs listed now, newest first, then for jobs an earlier search listed and left unread.
        # Pages go only to jobs the rule filters would keep.
        listed = [j for j in newest_first if not j.is_read and fits(j)]
        earlier = [j for j in ctx.unread if j.url not in seen and fits(j)]
        caught_up: list[JobPosting] = []
        for job in (listed + earlier)[: self.cfg.max_detail_pages]:
            try:
                detail = ctx.browser.fetch(job.url, wait_ms=1500)
                job.description = detail.text[:20000]
                # The job's own age is near the top; lower down are other, similar postings.
                job.posted_at = job.posted_at or parse_posted(detail.text[:1500])
                job.remote_type = (job.remote_type if job.remote_type != "unknown"
                                   else guess_remote_type(detail.text[:3000]))
            except SiteRefused as e:  # asking again would only be refused again
                ctx.log(f"{self.cfg.name}: {e}. No more job pages are asked for in this search")
                break
            except Exception as e:  # noqa: BLE001
                ctx.log(f"{self.cfg.name}: detail fetch failed for {job.url}: {e}")
            if job.is_read and job.url not in seen:
                caught_up.append(job)
        left = sum(1 for j in listed + earlier if not j.is_read)
        if left:
            ctx.log(f"{self.cfg.name}: {left} jobs wait for a later search to read their page")
        return newest_first + caught_up
