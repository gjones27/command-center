"""
Public pipeline interface.

ContentBrief is the input spec. generate() runs the full pipeline:
  brief → fetch real data → brand-constrained generation → ContentDraft

ContentDraft carries the generated content plus metadata (data sources cited,
token costs, cache efficiency). This lets the caller log, review, or publish.
"""

from dataclasses import dataclass, field
from typing import Optional

from .generator import WaterwayContentGenerator, GenerationResult


# ─── Input / Output types ─────────────────────────────────────────────────────

@dataclass
class ContentBrief:
    """
    Everything the generator needs to produce a piece of content.

    Mandatory fields: waterway, platform, pillar, content_type
    Optional fields: provide as much context as available for better output
    """

    # What waterway / location this content is about
    waterway: str

    # Target platform: "instagram", "tiktok", "youtube", "facebook", "blog"
    # Use "instagram_reel" for Reels-specific scripts
    platform: str

    # Content pillar: "route_guides", "safety", "gear", "community", "conservation"
    pillar: str

    # What format to produce: "caption", "reel_script", "description", "blog_section"
    content_type: str

    # Free-text brief: current conditions, season, angle, news hook, etc.
    context: str = ""

    # 8-digit USGS site ID for inland/river waterways
    # Find IDs at: https://waterdata.usgs.gov/nwis/rt
    usgs_site_id: Optional[str] = None

    # NOAA CO-OPS station ID for coastal/tidal waterways
    # Find IDs at: https://tidesandcurrents.noaa.gov/stations.html
    noaa_station_id: Optional[str] = None

    # Override max output tokens (default 1600 ≈ 1200 words)
    max_tokens: int = 1600


@dataclass
class ContentDraft:
    """
    Output from a generation run.

    content:      The ready-to-review text
    brief:        Echo of the input brief for traceability
    data_calls:   Which data tools were called and with what arguments
    token_report: Human-readable cost/cache summary
    """

    content: str
    brief: ContentBrief
    data_calls: list[dict] = field(default_factory=list)

    # Cost and cache metrics
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    thinking_used: bool = False

    @property
    def token_report(self) -> str:
        total = self.input_tokens + self.cache_read_tokens + self.cache_write_tokens
        hit_rate = (self.cache_read_tokens / total * 100) if total > 0 else 0
        lines = [
            f"  Input (uncached):   {self.input_tokens:,} tokens",
            f"  Cache reads:        {self.cache_read_tokens:,} tokens ({hit_rate:.0f}% of total input)",
            f"  Cache writes:       {self.cache_write_tokens:,} tokens",
            f"  Output:             {self.output_tokens:,} tokens",
            f"  Thinking active:    {'yes' if self.thinking_used else 'no'}",
        ]
        return "\n".join(lines)

    @property
    def data_source_summary(self) -> str:
        if not self.data_calls:
            return "  No data tools called"
        lines = []
        for call in self.data_calls:
            args = ", ".join(f"{k}={v!r}" for k, v in call["input"].items())
            lines.append(f"  {call['tool']}({args})")
        return "\n".join(lines)


# ─── Main entry point ─────────────────────────────────────────────────────────

_generator: Optional[WaterwayContentGenerator] = None


def _get_generator() -> WaterwayContentGenerator:
    """Lazily initialize the generator (reuse Anthropic client across calls)."""
    global _generator
    if _generator is None:
        _generator = WaterwayContentGenerator()
    return _generator


def generate(brief: ContentBrief) -> ContentDraft:
    """
    Run the full content generation pipeline for a given brief.

    Fetches real-time data from USGS/NOAA, runs brand-constrained generation
    via Claude, and returns a ContentDraft ready for editorial review.

    Args:
        brief: ContentBrief with waterway, platform, pillar, and optional gauge IDs

    Returns:
        ContentDraft with the generated text and usage metadata

    Example:
        from content_engine import generate, ContentBrief

        draft = generate(ContentBrief(
            waterway="Nantahala River, Wesser NC",
            platform="instagram",
            pillar="safety",
            content_type="caption",
            context="Late spring runoff, river above seasonal median",
            usgs_site_id="03500000",
        ))
        print(draft.content)
    """
    gen = _get_generator()

    result: GenerationResult = gen.generate(
        waterway=brief.waterway,
        platform=brief.platform,
        pillar=brief.pillar,
        content_type=brief.content_type,
        context=brief.context,
        usgs_site_id=brief.usgs_site_id,
        noaa_station_id=brief.noaa_station_id,
        max_tokens=brief.max_tokens,
    )

    return ContentDraft(
        content=result.content,
        brief=brief,
        data_calls=result.data_calls,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cache_read_tokens=result.cache_read_tokens,
        cache_write_tokens=result.cache_write_tokens,
        thinking_used=result.thinking_used,
    )
