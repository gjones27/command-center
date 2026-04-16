"""
Real-time waterway data fetchers.

These functions pull from authoritative public APIs:
  • USGS National Water Information System — river flow, gage height
  • NOAA CO-OPS (Tides and Currents) — tides, water temp, wind

Data from these sources is what separates authoritative waterway content
from generic AI slop. Every piece of content should cite a real gauge or
station number so readers can verify conditions themselves.

Both APIs are free and require no authentication for basic data access.
"""

import json
from datetime import datetime
from typing import Any

import httpx

# ─── USGS National Water Information System ──────────────────────────────────
# Docs: https://waterservices.usgs.gov/rest/IV-Service.html
# Real-time values endpoint: instantaneous values (IV)

USGS_IV_URL = "https://waterservices.usgs.gov/nwis/iv/"

# USGS parameter codes
PARAM_DISCHARGE = "00060"    # Streamflow / discharge in ft³/s (cfs)
PARAM_GAGE_HEIGHT = "00065"  # Gage height in feet
PARAM_WATER_TEMP = "00010"   # Water temperature in °C


def fetch_usgs_conditions(site_id: str) -> dict[str, Any]:
    """
    Fetch real-time river conditions from USGS gauge.

    Returns flow rate (cfs), gage height (ft), and source citation.
    Site IDs can be looked up at https://waterdata.usgs.gov/nwis/rt

    Args:
        site_id: 8-digit USGS site ID (e.g. "03320000")
    """
    params = {
        "sites": site_id,
        "parameterCd": f"{PARAM_DISCHARGE},{PARAM_GAGE_HEIGHT},{PARAM_WATER_TEMP}",
        "format": "json",
        "period": "PT2H",  # last 2 hours of readings
    }

    try:
        response = httpx.get(USGS_IV_URL, params=params, timeout=15.0)
        response.raise_for_status()
        raw = response.json()
    except httpx.HTTPError as e:
        return {"error": f"USGS API request failed: {e}"}
    except Exception as e:
        return {"error": f"Unexpected error fetching USGS data: {e}"}

    result: dict[str, Any] = {
        "site_id": site_id,
        "source": "USGS National Water Information System",
        "citation": f"USGS gauge #{site_id} — verify at waterdata.usgs.gov/nwis/uv?site_no={site_id}",
        "readings": {},
    }

    time_series = raw.get("value", {}).get("timeSeries", [])

    if not time_series:
        result["error"] = f"No data returned for USGS site {site_id}. Verify the site ID."
        return result

    for series in time_series:
        # Site name (first series only)
        if "site_name" not in result:
            result["site_name"] = (
                series.get("sourceInfo", {}).get("siteName", "Unknown site")
            )

        var_code_list = series.get("variable", {}).get("variableCode", [{}])
        var_code = var_code_list[0].get("value", "") if var_code_list else ""
        var_name = series.get("variable", {}).get("variableName", "")
        unit = series.get("variable", {}).get("unit", {}).get("unitCode", "")

        values_outer = series.get("values", [{}])
        value_list = values_outer[0].get("value", []) if values_outer else []

        if not value_list:
            continue

        latest = value_list[-1]
        raw_value = latest.get("value", "")
        timestamp = latest.get("dateTime", "")

        # Skip "No data" sentinel values that USGS uses
        if raw_value in ("", "-999999", "Ice"):
            continue

        try:
            numeric_value = float(raw_value)
        except (ValueError, TypeError):
            continue

        if var_code == PARAM_DISCHARGE:
            result["readings"]["flow_cfs"] = round(numeric_value, 1)
            result["readings"]["flow_timestamp"] = timestamp
            result["readings"]["flow_unit"] = "cfs"
        elif var_code == PARAM_GAGE_HEIGHT:
            result["readings"]["gage_height_ft"] = round(numeric_value, 2)
            result["readings"]["height_timestamp"] = timestamp
        elif var_code == PARAM_WATER_TEMP:
            # USGS reports in Celsius; convert to Fahrenheit for US audiences
            temp_f = round((numeric_value * 9 / 5) + 32, 1)
            result["readings"]["water_temp_f"] = temp_f
            result["readings"]["water_temp_c"] = round(numeric_value, 1)

    if not result["readings"]:
        result["warning"] = (
            "Site found but no numeric readings retrieved. "
            "Sensor may be offline or parameter codes unavailable at this site."
        )

    return result


# ─── NOAA CO-OPS (Tides and Currents) ────────────────────────────────────────
# Docs: https://api.tidesandcurrents.noaa.gov/api/prod/
# Station search: https://tidesandcurrents.noaa.gov/stations.html

NOAA_COOPS_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"


def fetch_noaa_tides(station_id: str) -> dict[str, Any]:
    """
    Fetch today's tide predictions from NOAA CO-OPS.

    Returns high/low tide times and heights in feet (MLLW datum).
    Station IDs can be looked up at https://tidesandcurrents.noaa.gov/stations.html

    Args:
        station_id: NOAA CO-OPS station ID (e.g. "8723170" for Miami Beach, FL)
    """
    today = datetime.now().strftime("%Y%m%d")

    params = {
        "product": "predictions",
        "application": "waterway_guide_media",
        "begin_date": today,
        "end_date": today,
        "datum": "MLLW",
        "station": station_id,
        "time_zone": "lst_ldt",   # local standard/daylight time
        "interval": "hilo",        # high/low only (cleaner for content)
        "units": "english",        # feet
        "format": "json",
    }

    try:
        response = httpx.get(NOAA_COOPS_URL, params=params, timeout=15.0)
        response.raise_for_status()
        raw = response.json()
    except httpx.HTTPError as e:
        return {"error": f"NOAA CO-OPS request failed: {e}"}
    except Exception as e:
        return {"error": f"Unexpected error fetching tide data: {e}"}

    # NOAA returns errors inline as {"error": {"message": "..."}}
    if "error" in raw:
        return {
            "error": raw["error"].get("message", "NOAA API returned an error"),
            "station_id": station_id,
        }

    predictions = raw.get("predictions", [])

    result: dict[str, Any] = {
        "station_id": station_id,
        "source": "NOAA CO-OPS Tides and Currents",
        "citation": (
            f"NOAA CO-OPS Station #{station_id} — "
            f"verify at tidesandcurrents.noaa.gov/stationhome.html?id={station_id}"
        ),
        "date": today,
        "datum": "MLLW",
        "unit": "feet",
        "tides": [],
    }

    for p in predictions:
        tide_type = "High" if p.get("type", "").upper() == "H" else "Low"
        try:
            height = round(float(p.get("v", 0)), 2)
        except (ValueError, TypeError):
            height = None

        result["tides"].append({
            "time": p.get("t", ""),
            "height_ft": height,
            "type": tide_type,
        })

    if not result["tides"]:
        result["warning"] = (
            "No tide predictions returned. Station may not have prediction data "
            "or the station ID may be invalid."
        )

    return result


def fetch_noaa_water_conditions(station_id: str) -> dict[str, Any]:
    """
    Fetch current observed water temperature and wind from NOAA CO-OPS.

    Not all stations have all sensors. Returns whatever is available.
    Station IDs: https://tidesandcurrents.noaa.gov/stations.html

    Args:
        station_id: NOAA CO-OPS station ID
    """
    today = datetime.now().strftime("%Y%m%d")

    base_params = {
        "application": "waterway_guide_media",
        "begin_date": today,
        "end_date": today,
        "station": station_id,
        "time_zone": "lst_ldt",
        "units": "english",
        "format": "json",
    }

    result: dict[str, Any] = {
        "station_id": station_id,
        "source": "NOAA CO-OPS",
        "citation": f"NOAA CO-OPS Station #{station_id}",
        "conditions": {},
    }

    # Water temperature
    try:
        resp = httpx.get(
            NOAA_COOPS_URL,
            params={**base_params, "product": "water_temperature"},
            timeout=10.0,
        )
        data = resp.json()
        if "data" in data and data["data"]:
            latest = data["data"][-1]
            temp_val = latest.get("v", "")
            if temp_val and temp_val != "":
                result["conditions"]["water_temp_f"] = round(float(temp_val), 1)
                result["conditions"]["water_temp_timestamp"] = latest.get("t", "")
    except Exception:
        pass  # Sensor not available at this station

    # Wind
    try:
        resp = httpx.get(
            NOAA_COOPS_URL,
            params={**base_params, "product": "wind"},
            timeout=10.0,
        )
        data = resp.json()
        if "data" in data and data["data"]:
            latest = data["data"][-1]
            speed = latest.get("s", "")
            direction = latest.get("dr", "")
            direction_deg = latest.get("d", "")
            if speed:
                result["conditions"]["wind_speed_knots"] = round(float(speed), 1)
                result["conditions"]["wind_direction"] = direction
                result["conditions"]["wind_direction_deg"] = direction_deg
                result["conditions"]["wind_timestamp"] = latest.get("t", "")
    except Exception:
        pass  # Sensor not available at this station

    # Air temperature
    try:
        resp = httpx.get(
            NOAA_COOPS_URL,
            params={**base_params, "product": "air_temperature"},
            timeout=10.0,
        )
        data = resp.json()
        if "data" in data and data["data"]:
            latest = data["data"][-1]
            temp_val = latest.get("v", "")
            if temp_val:
                result["conditions"]["air_temp_f"] = round(float(temp_val), 1)
    except Exception:
        pass

    if not result["conditions"]:
        result["warning"] = (
            "No sensor data returned for this station. "
            "The station may not have meteorological sensors, "
            "or the station ID may be invalid."
        )

    return result


# ─── CONVENIENCE FORMATTERS ──────────────────────────────────────────────────

def format_usgs_for_content(site_id: str) -> str:
    """Fetch USGS data and format as a human-readable string for Claude."""
    data = fetch_usgs_conditions(site_id)

    if "error" in data:
        return f"[USGS data unavailable for site {site_id}: {data['error']}]"

    lines = [
        f"RIVER CONDITIONS — {data.get('site_name', f'USGS Site {site_id}')}",
        f"Source: {data['citation']}",
    ]

    readings = data.get("readings", {})
    if "flow_cfs" in readings:
        lines.append(f"Flow rate: {readings['flow_cfs']:,.0f} cfs")
    if "gage_height_ft" in readings:
        lines.append(f"Gage height: {readings['gage_height_ft']} ft")
    if "water_temp_f" in readings:
        lines.append(
            f"Water temperature: {readings['water_temp_f']}°F "
            f"({readings.get('water_temp_c', '?')}°C)"
        )
    if "flow_timestamp" in readings:
        lines.append(f"Data timestamp: {readings['flow_timestamp']}")

    if "warning" in data:
        lines.append(f"Note: {data['warning']}")

    return "\n".join(lines)


def format_noaa_tides_for_content(station_id: str) -> str:
    """Fetch NOAA tide data and format as a human-readable string for Claude."""
    data = fetch_noaa_tides(station_id)

    if "error" in data:
        return f"[NOAA tide data unavailable for station {station_id}: {data['error']}]"

    lines = [
        f"TIDE PREDICTIONS — NOAA Station #{station_id}",
        f"Date: {data.get('date', 'today')} | Datum: {data.get('datum', 'MLLW')}",
        f"Source: {data['citation']}",
        "",
    ]

    tides = data.get("tides", [])
    if tides:
        lines.append("Today's tides:")
        for tide in tides:
            height_str = f"{tide['height_ft']} ft" if tide["height_ft"] is not None else "?"
            lines.append(f"  {tide['type']:4s}  {tide['time']}  {height_str}")
    else:
        lines.append("No tide predictions available.")

    if "warning" in data:
        lines.append(f"Note: {data['warning']}")

    return "\n".join(lines)


def format_noaa_conditions_for_content(station_id: str) -> str:
    """Fetch NOAA marine conditions and format as a human-readable string for Claude."""
    data = fetch_noaa_water_conditions(station_id)

    if "error" in data:
        return f"[NOAA conditions unavailable for station {station_id}: {data['error']}]"

    lines = [
        f"MARINE CONDITIONS — NOAA Station #{station_id}",
        f"Source: {data['citation']}",
    ]

    cond = data.get("conditions", {})
    if "water_temp_f" in cond:
        lines.append(f"Water temperature: {cond['water_temp_f']}°F")
    if "wind_speed_knots" in cond:
        lines.append(
            f"Wind: {cond['wind_speed_knots']} knots "
            f"from {cond.get('wind_direction', '?')}"
        )
    if "air_temp_f" in cond:
        lines.append(f"Air temperature: {cond['air_temp_f']}°F")

    if not cond:
        lines.append("No current sensor data available at this station.")

    if "warning" in data:
        lines.append(f"Note: {data['warning']}")

    return "\n".join(lines)
