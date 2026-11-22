"""Dedicated utilities for FHIR text extraction, narrative stripping, chunking, and score conversion."""

from datetime import datetime, timezone
import html
import json
import re
from typing import Any, Dict, List, Optional, Tuple, Union

TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
PUNCT_SPACE_RE = re.compile(r"\s+([,.:;!?])")


def strip_html_tags(html_str: Optional[str]) -> str:
    """Cleanly strip HTML/XML tags and decode entities from narrative text."""
    if not html_str:
        return ""
    text_without_tags = TAG_RE.sub(" ", html_str)
    unescaped = html.unescape(text_without_tags)
    clean_spacing = WHITESPACE_RE.sub(" ", unescaped).strip()
    return PUNCT_SPACE_RE.sub(r"\1", clean_spacing)


def _flatten_json_to_text(obj: Any, max_depth: int = 3, current_depth: int = 0) -> List[str]:
    """Recursively flatten JSON structure into a compact sequence of key-value descriptors."""
    if current_depth > max_depth or obj is None:
        return []

    tokens: List[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("id", "meta", "resourceType", "reference", "system", "url"):
                continue
            if isinstance(v, (str, int, float, bool)):
                tokens.append(f"{k}: {v}")
            elif isinstance(v, (dict, list)):
                nested = _flatten_json_to_text(v, max_depth, current_depth + 1)
                tokens.extend(nested)
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (str, int, float, bool)):
                tokens.append(str(item))
            elif isinstance(item, (dict, list)):
                tokens.extend(_flatten_json_to_text(item, max_depth, current_depth + 1))
    return tokens


def extract_searchable_text_from_fhir_resource(resource: Dict[str, Any]) -> str:
    """Extract clinical text from a FHIR R4 resource sensibly, with compact JSON fallback.

    Extracts:
    - Narrative text (text.div) with HTML stripped
    - Concept text and displays (code.text, coding.display)
    - Clinical observations and values (valueString, valueQuantity, interpretation)
    - Clinical conclusions, notes, and impressions
    - DocumentReference attachments and summaries
    - Falls back to compact JSON flattening if clinical text fields are absent.
    """
    if not isinstance(resource, dict):
        return ""

    parts: List[str] = []
    res_type = resource.get("resourceType", "")

    text_obj = resource.get("text")
    if isinstance(text_obj, dict):
        narrative = strip_html_tags(text_obj.get("div"))
        if narrative:
            parts.append(narrative)

    for code_field in ("code", "clinicalStatus", "verificationStatus", "category", "type", "reasonCode", "medicationCodeableConcept"):
        val = resource.get(code_field)
        if isinstance(val, dict):
            if val.get("text"):
                parts.append(str(val["text"]))
            for coding in val.get("coding", []):
                if isinstance(coding, dict):
                    disp = coding.get("display")
                    cd = coding.get("code")
                    if disp and cd:
                        parts.append(f"{disp} ({cd})")
                    elif disp:
                        parts.append(str(disp))
                    elif cd:
                        parts.append(f"Code: {cd}")
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    if item.get("text"):
                        parts.append(str(item["text"]))
                    for coding in item.get("coding", []):
                        if isinstance(coding, dict):
                            disp = coding.get("display")
                            cd = coding.get("code")
                            if disp and cd:
                                parts.append(f"{disp} ({cd})")
                            elif disp:
                                parts.append(str(disp))
                            elif cd:
                                parts.append(f"Code: {cd}")

    if "valueQuantity" in resource and isinstance(resource["valueQuantity"], dict):
        vq = resource["valueQuantity"]
        v_num = vq.get("value")
        v_unit = vq.get("unit") or vq.get("code") or ""
        if v_num is not None:
            parts.append(f"Value: {v_num} {v_unit}".strip())

    if "valueString" in resource and resource["valueString"]:
        parts.append(f"Value: {resource['valueString']}")

    if "valueCodeableConcept" in resource and isinstance(resource["valueCodeableConcept"], dict):
        vcc = resource["valueCodeableConcept"]
        if vcc.get("text"):
            parts.append(str(vcc["text"]))
        for coding in vcc.get("coding", []):
            if isinstance(coding, dict) and coding.get("display"):
                parts.append(str(coding["display"]))

    if "interpretation" in resource:
        interp = resource["interpretation"]
        if isinstance(interp, list):
            for it in interp:
                if isinstance(it, dict):
                    if it.get("text"):
                        parts.append(f"Interpretation: {it['text']}")
                    for c in it.get("coding", []):
                        if isinstance(c, dict) and c.get("display"):
                            parts.append(f"Interpretation: {c['display']}")

    if "component" in resource and isinstance(resource["component"], list):
        for comp in resource["component"]:
            if isinstance(comp, dict):
                comp_parts = []
                c_code = comp.get("code", {})
                if isinstance(c_code, dict):
                    if c_code.get("text"):
                        comp_parts.append(str(c_code["text"]))
                    for cd in c_code.get("coding", []):
                        if isinstance(cd, dict):
                            disp = cd.get("display")
                            c_val = cd.get("code")
                            if disp and c_val:
                                comp_parts.append(f"{disp} ({c_val})")
                            elif disp:
                                comp_parts.append(str(disp))
                            elif c_val:
                                comp_parts.append(f"Code: {c_val}")
                if "valueQuantity" in comp and isinstance(comp["valueQuantity"], dict):
                    cvq = comp["valueQuantity"]
                    cv_num = cvq.get("value")
                    cv_unit = cvq.get("unit") or cvq.get("code") or ""
                    if cv_num is not None:
                        comp_parts.append(f"{cv_num} {cv_unit}".strip())
                elif "valueString" in comp:
                    comp_parts.append(str(comp["valueString"]))
                if comp_parts:
                    parts.append(": ".join(comp_parts))

    if "conclusion" in resource and resource["conclusion"]:
        parts.append(f"Conclusion: {resource['conclusion']}")

    notes = resource.get("note", [])
    if isinstance(notes, list):
        for n in notes:
            if isinstance(n, dict) and n.get("text"):
                parts.append(f"Note: {n['text']}")
            elif isinstance(n, str):
                parts.append(f"Note: {n}")
    elif isinstance(notes, str):
        parts.append(f"Note: {notes}")

    if "description" in resource and resource["description"]:
        parts.append(f"Description: {resource['description']}")

    content_list = resource.get("content", [])
    if isinstance(content_list, list):
        for content_item in content_list:
            if isinstance(content_item, dict):
                att = content_item.get("attachment", {})
                if isinstance(att, dict):
                    if att.get("title"):
                        parts.append(str(att["title"]))
                    if att.get("data") and att.get("contentType") in ("text/plain", "text/markdown"):
                        try:
                            import base64
                            raw_b64 = att["data"][:4000]
                            decoded = base64.b64decode(raw_b64).decode("utf-8", errors="ignore")
                            if decoded.strip():
                                parts.append(decoded[:2000].strip())
                        except Exception:
                            pass

    if not parts:
        flattened = _flatten_json_to_text(resource)
        if flattened:
            parts.extend(flattened)

    combined = " | ".join(p.strip() for p in parts if p.strip())
    if combined and res_type:
        return f"{res_type}: {combined}"
    return combined


def chunk_text(text: str, chunk_size: int = 256, chunk_overlap: int = 32) -> List[str]:
    """Chunk a long clinical text into overlapping segments of approximately chunk_size tokens.

    Args:
        text: The source string to chunk.
        chunk_size: Target token/word count per chunk (default ~256).
        chunk_overlap: Number of overlapping tokens between successive chunks (default ~32).

    Returns:
        List of non-empty chunk strings.
    """
    clean_text = WHITESPACE_RE.sub(" ", text).strip()
    if not clean_text:
        return []

    words = clean_text.split(" ")
    if len(words) <= chunk_size:
        return [clean_text]

    step = max(1, chunk_size - chunk_overlap)
    chunks: List[str] = []

    for i in range(0, len(words), step):
        chunk_words = words[i : i + chunk_size]
        chunk_str = " ".join(chunk_words).strip()
        if chunk_str:
            chunks.append(chunk_str)
        if i + chunk_size >= len(words):
            break

    return chunks


def parse_datetime_to_timestamp(
    date_val: Union[str, datetime, int, float],
    is_end_of_day: bool = False,
) -> Optional[int]:
    """Parse various ISO 8601 date representations or datetimes into an integer Unix timestamp.

    If is_end_of_day is True and a date-only string is provided (e.g. '2024-12-31'),
    the timestamp is adjusted to the end of that day (23:59:59 UTC).
    """
    if isinstance(date_val, (int, float)):
        return int(date_val)
    if isinstance(date_val, datetime):
        if date_val.tzinfo is None:
            date_val = date_val.replace(tzinfo=timezone.utc)
        return int(date_val.timestamp())

    if isinstance(date_val, str):
        val = date_val.strip()
        if not val:
            return None
        try:
            if val.endswith("Z"):
                val = val[:-1] + "+00:00"
            dt = datetime.fromisoformat(val)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if is_end_of_day and len(date_val.strip()) == 10 and dt.hour == 0 and dt.minute == 0 and dt.second == 0:
                dt = dt.replace(hour=23, minute=59, second=59)
            return int(dt.timestamp())
        except (ValueError, TypeError):
            try:
                parts = [int(p) for p in val.split("-")[:3]]
                if len(parts) == 3:
                    hour = 23 if is_end_of_day else 0
                    minute = 59 if is_end_of_day else 0
                    second = 59 if is_end_of_day else 0
                    dt = datetime(parts[0], parts[1], parts[2], hour, minute, second, tzinfo=timezone.utc)
                    return int(dt.timestamp())
            except Exception:
                pass
    return None


def extract_resource_date(
    resource: Dict[str, Any], fallback_timestamp: Optional[int] = None
) -> int:
    """Extract clinical date from FHIR resource fields and return as integer Unix timestamp.

    Searches effectiveDateTime, recordedDate, onsetDateTime, period.start, issued, created, etc.
    """
    date_candidates = [
        resource.get("effectiveDateTime"),
        resource.get("recordedDate"),
        resource.get("onsetDateTime"),
        resource.get("issued"),
        resource.get("date"),
        resource.get("created"),
        resource.get("performedDateTime"),
        resource.get("authoredOn"),
    ]

    for period_key in ("period", "effectivePeriod", "performedPeriod"):
        period_obj = resource.get(period_key)
        if isinstance(period_obj, dict) and period_obj.get("start"):
            date_candidates.append(period_obj["start"])

    meta = resource.get("meta")
    if isinstance(meta, dict) and meta.get("lastUpdated"):
        date_candidates.append(meta["lastUpdated"])

    for cand in date_candidates:
        if cand:
            ts = parse_datetime_to_timestamp(cand)
            if ts is not None:
                return ts

    if fallback_timestamp is not None:
        return int(fallback_timestamp)
    return int(datetime.now(timezone.utc).timestamp())


def format_timestamp_to_iso(ts: Union[int, float, datetime, str]) -> str:
    """Convert Unix timestamp or datetime into standard ISO 8601 UTC string (ending in 'Z')."""
    if isinstance(ts, str):
        parsed = parse_datetime_to_timestamp(ts)
        if parsed is not None:
            ts = parsed
        else:
            return ts

    if isinstance(ts, (int, float)):
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    elif isinstance(ts, datetime):
        dt = ts if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc)
    else:
        dt = datetime.now(timezone.utc)

    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def distance_to_score(distance: float) -> float:
    """Convert ChromaDB cosine distance (in [0, 2]) to relevance similarity score in [0, 1].

    Formula: score = 1.0 - distance, bounded to [0.0, 1.0].
    Identical vectors (distance ~ 0) yield score 1.0.
    A distance of 0.17 yields score 0.83.
    """
    try:
        dist = float(distance)
        score = 1.0 - dist
        return round(max(0.0, min(1.0, score)), 4)
    except (TypeError, ValueError):
        return 0.0


def build_chroma_filters(
    resource_type: Optional[str] = None,
    patient_id: Optional[str] = None,
    date_from_ts: Optional[int] = None,
    date_to_ts: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Build ChromaDB metadata filter dictionary using native pre-filtering expressions.

    Returns:
        None if no filters apply, a single clause dict, or a {'$and': [...]} compound query.
    """
    clauses: List[Dict[str, Any]] = []

    if resource_type and resource_type.strip():
        clauses.append({"resource_type": resource_type.strip()})

    if patient_id and patient_id.strip():
        clauses.append({"patient_id": patient_id.strip()})

    if date_from_ts is not None:
        clauses.append({"date": {"$gte": int(date_from_ts)}})

    if date_to_ts is not None:
        clauses.append({"date": {"$lte": int(date_to_ts)}})

    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}
