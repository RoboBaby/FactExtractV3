"""HeidelTime microservice for temporal expression normalization."""

import subprocess
import os
import tempfile
import re
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

app = FastAPI(title="TimEx Service", version="1.0.0")

# HeidelTime jar path
HEIDELTIME_JAR = os.environ.get("HEIDELTIME_JAR", "/srv/heideltime/heideltime-standalone.jar")
HEIDELTIME_CONFIG = os.environ.get("HEIDELTIME_CONFIG", "/srv/heideltime/config/config.props")


class ParseRequest(BaseModel):
    text: str
    dct: str  # Document creation time in ISO format
    type: str = "NEWS"  # NEWS, NARRATIVES, COLLOQUIAL, SCIENTIFIC
    lang: str = "ENGLISH"


class TimeX(BaseModel):
    type: str  # DATE, TIME, DURATION, SET
    value: str  # Normalized value
    text: str  # Original text
    start: int  # Start offset
    end: int  # End offset


class ParseResponse(BaseModel):
    timexes: List[TimeX]


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.post("/parse", response_model=ParseResponse)
def parse(request: ParseRequest):
    """
    Parse temporal expressions using HeidelTime.

    Returns normalized time expressions.
    """
    if not request.text.strip():
        return ParseResponse(timexes=[])

    # Check if HeidelTime is available
    if os.path.exists(HEIDELTIME_JAR):
        return parse_with_heideltime(request)
    else:
        # Fall back to regex-based parsing
        return parse_with_regex(request)


def parse_with_heideltime(request: ParseRequest) -> ParseResponse:
    """Parse using HeidelTime jar."""
    try:
        # Write text to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(request.text)
            input_file = f.name

        # Run HeidelTime
        cmd = [
            "java", "-jar", HEIDELTIME_JAR,
            "-c", HEIDELTIME_CONFIG,
            "-t", request.type,
            "-l", request.lang,
            "-dct", request.dct,
            input_file
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        # Clean up
        os.unlink(input_file)

        if result.returncode != 0:
            raise Exception(f"HeidelTime failed: {result.stderr}")

        # Parse TimeML output
        timexes = parse_timeml(result.stdout, request.text)
        return ParseResponse(timexes=timexes)

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="HeidelTime timeout")
    except Exception as e:
        # Fall back to regex
        return parse_with_regex(request)


def parse_timeml(timeml: str, original_text: str) -> List[TimeX]:
    """Parse TimeML output to extract TIMEX3 tags."""
    timexes = []

    # Pattern for TIMEX3 tags
    pattern = r'<TIMEX3[^>]*type="([^"]*)"[^>]*value="([^"]*)"[^>]*>([^<]*)</TIMEX3>'

    for match in re.finditer(pattern, timeml):
        timex_type = match.group(1)
        value = match.group(2)
        text = match.group(3)

        # Find offset in original text
        start = original_text.find(text)
        end = start + len(text) if start >= 0 else -1

        timexes.append(TimeX(
            type=timex_type,
            value=value,
            text=text,
            start=start,
            end=end
        ))

    return timexes


def parse_with_regex(request: ParseRequest) -> ParseResponse:
    """Fallback regex-based temporal parsing."""
    timexes = []
    text = request.text

    # Date patterns
    date_patterns = [
        # ISO dates
        (r'\b(\d{4}-\d{2}-\d{2})\b', 'DATE'),
        # Written dates
        (r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b', 'DATE'),
        # Relative dates
        (r'\b(today|tomorrow|yesterday)\b', 'DATE'),
        (r'\b(last|next|this)\s+(week|month|year)\b', 'DATE'),
    ]

    # Time patterns
    time_patterns = [
        (r'\b(\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AP]M)?)\b', 'TIME'),
        (r'\b(noon|midnight)\b', 'TIME'),
    ]

    # Duration patterns
    duration_patterns = [
        (r'\b(\d+)\s*(seconds?|minutes?|hours?|days?|weeks?|months?|years?)\b', 'DURATION'),
    ]

    all_patterns = date_patterns + time_patterns + duration_patterns

    for pattern, timex_type in all_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            matched_text = match.group(0)
            start = match.start()
            end = match.end()

            # Simple normalization
            value = normalize_temporal(matched_text, timex_type, request.dct)

            timexes.append(TimeX(
                type=timex_type,
                value=value,
                text=matched_text,
                start=start,
                end=end
            ))

    return ParseResponse(timexes=timexes)


def normalize_temporal(text: str, timex_type: str, dct: str) -> str:
    """Simple temporal normalization."""
    text_lower = text.lower()

    if timex_type == "DATE":
        if "today" in text_lower:
            return dct[:10]  # Just the date part
        elif "tomorrow" in text_lower:
            # Would need date math
            return "FUTURE_REF"
        elif "yesterday" in text_lower:
            return "PAST_REF"
        else:
            # Return as-is for now
            return text

    elif timex_type == "TIME":
        if "noon" in text_lower:
            return "T12:00"
        elif "midnight" in text_lower:
            return "T00:00"
        else:
            return text

    elif timex_type == "DURATION":
        # Simple duration parsing
        match = re.search(r'(\d+)\s*(\w+)', text)
        if match:
            num = match.group(1)
            unit = match.group(2)[0].upper()  # First letter
            return f"P{num}{unit}"

    return text


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
