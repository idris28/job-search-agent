"""Job source adapters.

- greenhouse / lever / ashby: public applicant-tracking-system job board APIs. These are the
  officially published feeds for company career pages, so they are fast and reliable and need
  no browser.
- generic: any careers or search-results page. Rendered in Browserbase, listings extracted by
  the LLM, then each detail page is visited to capture the full description.
"""

from __future__ import annotations

from ..config import ConfigError, SourceConfig
from .base import Source, SourceContext
from .ats import AshbySource, GreenhouseSource, LeverSource
from .generic import GenericSource

_REGISTRY: dict[str, type[Source]] = {
    "greenhouse": GreenhouseSource,
    "lever": LeverSource,
    "ashby": AshbySource,
    "generic": GenericSource,
}


def build_source(cfg: SourceConfig) -> Source:
    cls = _REGISTRY.get(cfg.kind)
    if cls is None:
        raise ConfigError(f"Unknown source kind: {cfg.kind}")
    cls.validate(cfg)
    return cls(cfg)


__all__ = ["Source", "SourceContext", "build_source"]
