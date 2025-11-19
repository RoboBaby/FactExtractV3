"""Time and quantity normalization."""

import re
import requests
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from src.util.logging import get_logger

logger = get_logger("canonicalize.literals")

# Initialize Pint for unit conversions
try:
    from pint import UnitRegistry
    ureg = UnitRegistry()
    PINT_AVAILABLE = True
except ImportError:
    logger.warning("Pint not available, quantity normalization disabled")
    PINT_AVAILABLE = False
    ureg = None

# Initialize quantulum3 for quantity parsing
try:
    from quantulum3 import parser as quant_parser
    QUANTULUM_AVAILABLE = True
except ImportError:
    logger.warning("Quantulum3 not available, quantity parsing disabled")
    QUANTULUM_AVAILABLE = False
    quant_parser = None


def heideltime_parse(
    endpoint: str,
    text: str,
    dct_iso: str,
    timeout: int = 20
) -> List[Dict[str, Any]]:
    """
    Parse temporal expressions using HeidelTime service.

    Args:
        endpoint: HeidelTime service endpoint URL
        text: Text to parse
        dct_iso: Document creation time in ISO format
        timeout: Request timeout in seconds

    Returns:
        List of normalized time expressions
    """
    try:
        r = requests.post(
            endpoint,
            json={
                "text": text,
                "dct": dct_iso,
                "type": "NEWS",
                "lang": "ENGLISH"
            },
            timeout=timeout
        )
        r.raise_for_status()
        return r.json().get("timexes", [])
    except requests.exceptions.RequestException as e:
        logger.warning(f"HeidelTime request failed: {e}")
        return []
    except (KeyError, ValueError) as e:
        logger.warning(f"Invalid HeidelTime response: {e}")
        return []


def normalize_quantities(text: str, canonical_units: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """
    Parse and normalize quantities from text.

    Args:
        text: Text containing quantities
        canonical_units: Mapping of dimension to canonical unit
            e.g., {"temperature": "celsius", "length": "millimeter"}

    Returns:
        Dict of normalized quantities by type
    """
    if not QUANTULUM_AVAILABLE or not PINT_AVAILABLE:
        return {}

    if canonical_units is None:
        canonical_units = {
            "temperature": "celsius",
            "length": "millimeter",
            "mass": "gram",
            "time": "second"
        }

    out = {}

    try:
        quantities = quant_parser.parse(text)
    except Exception as e:
        logger.warning(f"Quantity parsing failed: {e}")
        return out

    for q in quantities:
        try:
            if q.unit is None or q.unit.name == "dimensionless":
                continue

            # Convert to Pint quantity
            unit_name = str(q.unit.name).replace(" ", "_")
            qty = q.value * ureg(unit_name)

            # Determine dimensionality and convert to canonical unit
            dim_str = str(qty.dimensionality)

            if "[temperature]" in dim_str:
                # Temperature conversion
                target = canonical_units.get("temperature", "celsius")
                if target == "celsius":
                    q_conv = qty.to(ureg.degC)
                elif target == "fahrenheit":
                    q_conv = qty.to(ureg.degF)
                else:
                    q_conv = qty.to(ureg.kelvin)
                out["temperature"] = {
                    "value": round(float(q_conv.magnitude), 2),
                    "unit": target
                }

            elif "[length]" in dim_str:
                # Length conversion
                target = canonical_units.get("length", "millimeter")
                q_conv = qty.to(ureg(target))
                out["length"] = {
                    "value": round(float(q_conv.magnitude), 2),
                    "unit": target
                }

            elif "[mass]" in dim_str:
                # Mass conversion
                target = canonical_units.get("mass", "gram")
                q_conv = qty.to(ureg(target))
                out["mass"] = {
                    "value": round(float(q_conv.magnitude), 2),
                    "unit": target
                }

            elif "[time]" in dim_str:
                # Time conversion (not video timestamps)
                target = canonical_units.get("time", "second")
                q_conv = qty.to(ureg(target))
                out["duration"] = {
                    "value": round(float(q_conv.magnitude), 2),
                    "unit": target
                }

        except Exception as e:
            logger.debug(f"Quantity conversion failed for '{q}': {e}")
            continue

    return out


def render_timex(
    timexes: List[Dict[str, Any]],
    blob_t_start: Optional[float] = None,
    blob_t_end: Optional[float] = None,
    video_publish_time: Optional[str] = None
) -> Dict[str, Any]:
    """
    Render time expressions as qualifiers.

    Args:
        timexes: List of HeidelTime results
        blob_t_start: Blob start time in video seconds
        blob_t_end: Blob end time in video seconds
        video_publish_time: Video publish time ISO string

    Returns:
        Dict with time_abs and/or time_rel qualifiers
    """
    quals = {}

    # Add video timestamp if available
    if blob_t_start is not None or blob_t_end is not None:
        quals["time_video"] = {
            "start": blob_t_start,
            "end": blob_t_end
        }

    # Process HeidelTime results
    for timex in timexes:
        timex_type = timex.get("type", "")
        value = timex.get("value", "")

        if timex_type == "DATE" and value:
            try:
                # Parse ISO date
                if "T" in value:
                    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                else:
                    dt = datetime.fromisoformat(value)

                if "time_abs" not in quals:
                    quals["time_abs"] = {"start": dt.isoformat(), "end": None}
                else:
                    quals["time_abs"]["end"] = dt.isoformat()
            except ValueError:
                pass

        elif timex_type == "DURATION" and value:
            quals["duration_text"] = value

    return quals


def derive_dct(video_id: str, videos_cache: Optional[Dict[str, str]] = None) -> str:
    """
    Derive document creation time from video metadata.

    Args:
        video_id: Video identifier
        videos_cache: Optional cache of video_id -> publish_time

    Returns:
        ISO format datetime string
    """
    if videos_cache and video_id in videos_cache:
        return videos_cache[video_id]

    # Default to current time if not available
    return datetime.now(timezone.utc).isoformat()
