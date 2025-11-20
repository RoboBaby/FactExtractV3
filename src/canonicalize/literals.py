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
_quant_parser = None
QUANTULUM_AVAILABLE = False

def _init_quantulum():
    """Lazy initialization of quantulum3 parser with error handling."""
    global _quant_parser, QUANTULUM_AVAILABLE
    if _quant_parser is not None:
        return _quant_parser
    
    try:
        from quantulum3 import parser as quant_parser
        _quant_parser = quant_parser
        QUANTULUM_AVAILABLE = True
        return quant_parser
    except ImportError:
        logger.warning("Quantulum3 not available, quantity parsing disabled")
        QUANTULUM_AVAILABLE = False
        return None
    except Exception as e:
        logger.warning(f"Quantulum3 initialization failed: {e}, using regex fallback")
        QUANTULUM_AVAILABLE = False
        return None


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


def _parse_quantities_regex(text: str, canonical_units: Dict[str, str]) -> Dict[str, Any]:
    """
    Fallback regex-based parser for common quantity patterns.
    
    Args:
        text: Text containing quantities
        canonical_units: Mapping of dimension to canonical unit
        
    Returns:
        Dict of normalized quantities by type
    """
    out = {}
    
    # Temperature patterns: "350 degrees Fahrenheit", "180 C", "100 f"
    temp_pattern = r'(\d+(?:\.\d+)?)\s*(?:degrees?\s*)?(celsius|fahrenheit|f|c|°c|°f)'
    for match in re.finditer(temp_pattern, text, re.IGNORECASE):
        value = float(match.group(1))
        unit = match.group(2).lower()
        
        # Convert to canonical unit
        target = canonical_units.get("temperature", "celsius")
        if unit in ("f", "fahrenheit", "°f"):
            # Fahrenheit to Celsius
            if target == "celsius":
                value = (value - 32) * 5 / 9
            elif target == "fahrenheit":
                pass  # Already in Fahrenheit
        elif unit in ("c", "celsius", "°c"):
            # Celsius to Fahrenheit
            if target == "fahrenheit":
                value = value * 9 / 5 + 32
            elif target == "celsius":
                pass  # Already in Celsius
        
        if "temperature" not in out:
            out["temperature"] = {
                "value": round(value, 2),
                "unit": target
            }
    
    # Length patterns: "50 millimeters", "2.5 mm", "10 cm", "5 inches"
    length_pattern = r'(\d+(?:\.\d+)?)\s*(mm|millimeters?|cm|centimeters?|m|meters?|in|inches?|ft|feet|foot)'
    for match in re.finditer(length_pattern, text, re.IGNORECASE):
        value = float(match.group(1))
        unit = match.group(2).lower()
        
        # Convert to millimeters
        target = canonical_units.get("length", "millimeter")
        if unit in ("mm", "millimeter", "millimeters"):
            pass  # Already in mm
        elif unit in ("cm", "centimeter", "centimeters"):
            value = value * 10
        elif unit in ("m", "meter", "meters"):
            value = value * 1000
        elif unit in ("in", "inch", "inches"):
            value = value * 25.4
        elif unit in ("ft", "foot", "feet"):
            value = value * 304.8
        
        if "length" not in out:
            out["length"] = {
                "value": round(value, 2),
                "unit": target
            }
    
    # Mass patterns: "500 grams", "2.5 kg", "1 pound"
    mass_pattern = r'(\d+(?:\.\d+)?)\s*(g|grams?|kg|kilograms?|lb|lbs|pounds?)'
    for match in re.finditer(mass_pattern, text, re.IGNORECASE):
        value = float(match.group(1))
        unit = match.group(2).lower()
        
        # Convert to grams
        target = canonical_units.get("mass", "gram")
        if unit in ("g", "gram", "grams"):
            pass  # Already in grams
        elif unit in ("kg", "kilogram", "kilograms"):
            value = value * 1000
        elif unit in ("lb", "lbs", "pound", "pounds"):
            value = value * 453.592
        
        if "mass" not in out:
            out["mass"] = {
                "value": round(value, 2),
                "unit": target
            }
    
    # Time patterns: "30 seconds", "5 minutes", "2 hours"
    time_pattern = r'(\d+)\s*(second|minute|hour|day|week|month|year)s?'
    for match in re.finditer(time_pattern, text, re.IGNORECASE):
        value = float(match.group(1))
        unit = match.group(2).lower()
        
        # Convert to seconds
        target = canonical_units.get("time", "second")
        if unit == "second":
            pass  # Already in seconds
        elif unit == "minute":
            value = value * 60
        elif unit == "hour":
            value = value * 3600
        elif unit == "day":
            value = value * 86400
        elif unit == "week":
            value = value * 604800
        elif unit == "month":
            value = value * 2592000  # Approximate
        elif unit == "year":
            value = value * 31536000  # Approximate
        
        if "duration" not in out:
            out["duration"] = {
                "value": round(value, 2),
                "unit": target
            }
    
    return out


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
    if canonical_units is None:
        canonical_units = {
            "temperature": "celsius",
            "length": "millimeter",
            "mass": "gram",
            "time": "second"
        }

    out = {}

    # Try quantulum3 first if available
    if PINT_AVAILABLE:
        quant_parser = _init_quantulum()
        if quant_parser:
            try:
                quantities = quant_parser.parse(text)
            except Exception as e:
                # Quantulum3 failed (serialization error, etc.)
                logger.debug(f"Quantulum3 parsing failed: {e}, using regex fallback")
                return _parse_quantities_regex(text, canonical_units)
        else:
            # Quantulum3 not available, use regex fallback
            return _parse_quantities_regex(text, canonical_units)
    else:
        # Pint not available, use regex fallback
        return _parse_quantities_regex(text, canonical_units)

    # Process quantulum3 results
    if not quantities:
        # No quantities found, try regex fallback
        return _parse_quantities_regex(text, canonical_units)

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
