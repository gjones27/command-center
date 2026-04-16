"""
Content generator — Claude API integration.

Architecture:
  1. Brand system prompt (large, stable) → prompt-cached at ~0.1x cost on repeat runs
  2. Platform context (small, per-request) → uncached second system block
  3. Claude tools call real USGS / NOAA APIs during generation
  4. Adaptive thinking handles quality decisions (when to trust data vs flag uncertainty)

The tool use pattern is the core anti-slop mechanism: Claude cannot write
"the river is running high" if it fetched a gauge showing exactly 842 cfs.
Real data forces specificity.
"""

import json
from dataclasses import dataclass, field
from typing import Optional

import anthropic
from anthropic import beta_tool

from .brand import BRAND_SYSTEM_PROMPT, get_platform_context, get_pillar_description
from .data import (
    format_usgs_for_content,
    format_noaa_tides_for_content,
    format_noaa_conditions_for_content,
)

# ─── Tool Definitions ─────────────────────────────────────────────────────────
# These are the tools Claude gets. They wrap the data fetchers.
# @beta_tool generates the JSON schema from type hints + docstring automatically.


@beta_tool
def get_river_conditions(usgs_site_id: str) -> str:
    """Fetch real-time river conditions from the USGS National Water Information System.

    Returns current flow rate (cfs), gage height (ft), water temperature, and a
    verified citation string. Use this whenever writing about rivers, streams, creeks,
    or any inland waterway where a USGS gauge exists.

    Flow rate interpretation guides (general, will vary by watershed):
      - Below 200 cfs: typically low/bony, technical
      - 200–800 cfs: normal recreational range for most rivers
      - 800–2000 cfs: medium-high, moving fast, hydraulics developing
      - 2000+ cfs: high water, flood-stage possible, expert-only or portage

    USGS site IDs (8 digits) can be looked up at:
      https://waterdata.usgs.gov/nwis/rt

    Common site IDs for reference:
      03320000  — Green River at Munfordville, KY
      03049000  — Allegheny River at Parker, PA
      03500000  — Nantahala River at Wesser, NC
      09402000  — Colorado River near Grand Canyon, AZ
      12301933  — Clark Fork at St Regis, MT

    Args:
        usgs_site_id: 8-digit USGS site ID string (e.g., "03320000")
    """
    return format_usgs_for_content(usgs_site_id)


@beta_tool
def get_tide_predictions(noaa_station_id: str) -> str:
    """Fetch today's tide predictions from NOAA Tides and Currents (CO-OPS).

    Returns today's high and low tide times and heights in feet above MLLW.
    Use this whenever writing about coastal, bay, estuarine, or tidal waterways.

    NOAA station IDs can be found at:
      https://tidesandcurrents.noaa.gov/stations.html

    Common station IDs for reference:
      8723170  — Miami Beach, FL
      8461490  — New London, CT
      9410170  — San Diego, CA
      8638610  — Sewells Point (Hampton Roads), VA
      9447130  — Seattle, WA (Puget Sound)

    Args:
        noaa_station_id: NOAA CO-OPS station ID string (e.g., "8723170")
    """
    return format_noaa_tides_for_content(noaa_station_id)


@beta_tool
def get_marine_conditions(noaa_station_id: str) -> str:
    """Fetch current observed water temperature and wind from NOAA CO-OPS.

    Returns water temp (°F), wind speed (knots), wind direction, and air temp
    when available. Not all stations have all sensors — the function returns
    whatever data is available.

    Use this for coastal or bay content where water temperature and wind
    are relevant (gear recommendations, safety, seasonal context).

    NOAA station IDs: https://tidesandcurrents.noaa.gov/stations.html

    Args:
        noaa_station_id: NOAA CO-OPS station ID string
    """
    return format_noaa_conditions_for_content(noaa_station_id)


# ─── Result dataclass ─────────────────────────────────────────────────────────

@dataclass
class GenerationResult:
    """Output from a single content generation run."""

    # The generated content (platform-ready text)
    content: str

    # Which data tools were called and with what inputs
    data_calls: list[dict] = field(default_factory=list)

    # Token usage for cost tracking
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    # Whether thinking was used
    thinking_used: bool = False

    @property
    def cache_hit_rate(self) -> float:
        """Fraction of input tokens served from cache (0–1)."""
        total_input = self.input_tokens + self.cache_read_tokens + self.cache_write_tokens
        if total_input == 0:
            return 0.0
        return self.cache_read_tokens / total_input

    @property
    def cost_summary(self) -> str:
        """Human-readable cost breakdown."""
        lines = [
            f"Input tokens:       {self.input_tokens:,}",
            f"Output tokens:      {self.output_tokens:,}",
            f"Cache reads:        {self.cache_read_tokens:,} ({self.cache_hit_rate:.0%} of input)",
            f"Cache writes:       {self.cache_write_tokens:,}",
        ]
        return "\n".join(lines)


# ─── Generator ────────────────────────────────────────────────────────────────

class WaterwayContentGenerator:
    """
    Generates brand-compliant waterway guide content using Claude + real data.

    Usage:
        gen = WaterwayContentGenerator()
        result = gen.generate(
            waterway="Nantahala River, NC",
            platform="instagram",
            pillar="safety",
            content_type="caption",
            context="Spring runoff, flows elevated",
            usgs_site_id="03500000",
        )
        print(result.content)
    """

    def __init__(self, api_key: Optional[str] = None):
        # Reads ANTHROPIC_API_KEY from env if not passed
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self._tools = [get_river_conditions, get_tide_predictions, get_marine_conditions]

    def generate(
        self,
        waterway: str,
        platform: str,
        pillar: str,
        content_type: str,
        context: str = "",
        usgs_site_id: Optional[str] = None,
        noaa_station_id: Optional[str] = None,
        max_tokens: int = 1600,
    ) -> GenerationResult:
        """
        Generate a single piece of content.

        Args:
            waterway:       Name and location of the waterway
            platform:       Target platform key (instagram, tiktok, youtube, etc.)
            pillar:         Content pillar key (route_guides, safety, gear, community, conservation)
            content_type:   What format (caption, reel_script, description, blog_section)
            context:        Any extra briefing (recent events, current angle, topic focus)
            usgs_site_id:   8-digit USGS site ID if a river gauge is available
            noaa_station_id: NOAA CO-OPS station ID if a coastal/tidal station applies
            max_tokens:     Maximum output tokens (default 1600 = ~1200 words, safe for captions)

        Returns:
            GenerationResult with the content and usage metadata
        """
        system_blocks = self._build_system(platform)
        user_message = self._build_user_message(
            waterway=waterway,
            platform=platform,
            pillar=pillar,
            content_type=content_type,
            context=context,
            usgs_site_id=usgs_site_id,
            noaa_station_id=noaa_station_id,
        )

        all_messages: list = []
        data_calls: list[dict] = []

        runner = self.client.beta.messages.tool_runner(
            model="claude-opus-4-6",
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            system=system_blocks,
            tools=self._tools,
            messages=[{"role": "user", "content": user_message}],
        )

        final_message = None
        for message in runner:
            all_messages.append(message)
            final_message = message
            # Collect tool calls from intermediate messages
            for block in message.content:
                if hasattr(block, "type") and block.type == "tool_use":
                    data_calls.append({
                        "tool": block.name,
                        "input": block.input,
                    })

        # Extract the final text response
        content_text = ""
        thinking_used = False
        if final_message:
            for block in final_message.content:
                if hasattr(block, "type"):
                    if block.type == "text":
                        content_text = block.text
                    elif block.type == "thinking":
                        thinking_used = True

        # Gather usage from the last message
        usage = getattr(final_message, "usage", None)

        return GenerationResult(
            content=content_text,
            data_calls=data_calls,
            input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) if usage else 0,
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) if usage else 0,
            thinking_used=thinking_used,
        )

    def _build_system(self, platform: str) -> list[dict]:
        """
        Build the system prompt blocks with prompt caching.

        Block 1: The large brand system prompt — CACHED (stable across all requests)
        Block 2: Platform context — NOT cached (small, changes per platform)

        After the first request per session, Block 1 costs ~0.1x.
        """
        return [
            {
                "type": "text",
                "text": BRAND_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},  # Cache the big stable block
            },
            {
                "type": "text",
                "text": get_platform_context(platform),
                # No cache_control — this is small and changes per platform
            },
        ]

    def _build_user_message(
        self,
        waterway: str,
        platform: str,
        pillar: str,
        content_type: str,
        context: str,
        usgs_site_id: Optional[str],
        noaa_station_id: Optional[str],
    ) -> str:
        """Build the user-turn content brief for Claude."""

        pillar_description = get_pillar_description(pillar)

        lines = [
            f"Create a {content_type} for {platform}.",
            "",
            f"WATERWAY: {waterway}",
            f"CONTENT PILLAR: {pillar}",
        ]

        if pillar_description:
            lines.append(f"PILLAR GUIDANCE: {pillar_description}")

        if context:
            lines.append(f"BRIEF/CONTEXT: {context}")

        lines.extend([
            "",
            "DATA SOURCES AVAILABLE:",
        ])

        if usgs_site_id:
            lines.append(
                f"  • USGS river gauge: site ID {usgs_site_id} "
                f"— call get_river_conditions(\"{usgs_site_id}\") to fetch current data"
            )
        else:
            lines.append(
                "  • No USGS site provided. If you know the USGS site ID for this waterway, "
                "you may call get_river_conditions() with the correct ID."
            )

        if noaa_station_id:
            lines.extend([
                f"  • NOAA CO-OPS station: {noaa_station_id} "
                f"— call get_tide_predictions(\"{noaa_station_id}\") and/or "
                f"get_marine_conditions(\"{noaa_station_id}\") for conditions"
            ])
        else:
            lines.append(
                "  • No NOAA station provided. If this is a coastal/tidal waterway and you know "
                "the station ID, you may call the NOAA tools."
            )

        lines.extend([
            "",
            "INSTRUCTIONS:",
            "1. Fetch real-time data before writing. Do not skip this step.",
            "2. Ground every condition claim in the fetched data. Cite gauge/station numbers inline.",
            "3. If data is unavailable or sensors are offline, say so clearly in the content.",
            "4. Follow all brand voice guidelines: no banned phrases, no generic descriptions.",
            "5. Write for the target platform format. Hit the format specs precisely.",
            "6. End with the source citation(s) so readers can verify.",
        ])

        return "\n".join(lines)
