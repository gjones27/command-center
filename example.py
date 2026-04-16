"""
Waterway Guide Media — Content Engine Demo

Demonstrates the full pipeline: real USGS/NOAA data → brand-constrained
Claude generation → platform-ready draft.

Set ANTHROPIC_API_KEY in your environment before running.

Usage:
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY=sk-ant-...
    python example.py
"""

import os
from dotenv import load_dotenv

load_dotenv()

from content_engine import generate, ContentBrief

# ─── Example 1: River safety content (Instagram) ─────────────────────────────
# USGS gauge 03500000 = Nantahala River at Wesser, NC
# A real gauge on one of the most paddled whitewater rivers in the Southeast

print("=" * 60)
print("EXAMPLE 1: River safety — Instagram caption")
print("=" * 60)

safety_brief = ContentBrief(
    waterway="Nantahala River, Wesser NC",
    platform="instagram",
    pillar="safety",
    content_type="caption",
    context=(
        "Late spring, flows elevated after a wet week in the watershed. "
        "Focus on Nantahala Falls rapid at the take-out — the key hazard "
        "at higher flows. Target audience: intermediate paddlers planning "
        "a first Nantahala trip."
    ),
    usgs_site_id="03500000",  # Nantahala River at Wesser, NC
)

draft = generate(safety_brief)

print("\n--- GENERATED CONTENT ---\n")
print(draft.content)
print("\n--- DATA SOURCES CALLED ---")
print(draft.data_source_summary)
print("\n--- TOKEN USAGE ---")
print(draft.token_report)

# ─── Example 2: Coastal route guide (TikTok) ────────────────────────────────
# NOAA station 8723170 = Miami Beach, FL
# Demonstrates tide-grounded content for coastal paddling

print("\n\n" + "=" * 60)
print("EXAMPLE 2: Coastal route guide — TikTok script")
print("=" * 60)

coastal_brief = ContentBrief(
    waterway="Biscayne Bay, Miami FL",
    platform="tiktok",
    pillar="route_guides",
    content_type="reel_script",
    context=(
        "Early morning kayak route from Matheson Hammock to Chicken Key. "
        "~5 miles round trip, suitable for intermediate flatwater paddlers. "
        "The tidal timing matters — heading out on the outgoing tide, "
        "returning on the incoming. Show how to read the tide chart."
    ),
    noaa_station_id="8723170",  # Miami Beach, FL
)

draft2 = generate(coastal_brief)

print("\n--- GENERATED CONTENT ---\n")
print(draft2.content)
print("\n--- DATA SOURCES CALLED ---")
print(draft2.data_source_summary)
print("\n--- TOKEN USAGE ---")
print(draft2.token_report)
print()

# ─── Example 3: Gear review (YouTube description) ────────────────────────────

print("\n" + "=" * 60)
print("EXAMPLE 3: Gear review — YouTube description")
print("=" * 60)

gear_brief = ContentBrief(
    waterway="Class III-IV rivers, Southeast US",
    platform="youtube",
    pillar="gear",
    content_type="description",
    context=(
        "Review of a mid-range whitewater kayak helmet (Shred Ready Standard). "
        "Tested on the Ocoee, Chattooga Section IV, and Gauley at various flows. "
        "Compare to Sweet Protection Rocker MIPS at same price point. "
        "Be direct about what this helmet does well and where it falls short."
    ),
    # No gauge data needed for gear reviews
)

draft3 = generate(gear_brief)

print("\n--- GENERATED CONTENT ---\n")
print(draft3.content)
print("\n--- TOKEN USAGE ---")
print(draft3.token_report)
