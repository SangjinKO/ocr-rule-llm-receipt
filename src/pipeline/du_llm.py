import json
import os
import re
import urllib.request
from typing import Any, Optional
import sys

def _ollama_chat(
    model: str,
    messages: list[dict[str, str]],
    temperature: float = 0.0,
) -> str:
    """
    Minimal Ollama chat call via HTTP.
    - OLLAMA_URL is read from env (.env); if empty, fallback to localhost.
    """
    base_url = (os.getenv("OLLAMA_URL") or "").strip() or "http://localhost:11434"

    payload = {
        "model": model,
        "messages": messages,
        "options": {"temperature": float(temperature)},
        "stream": False,
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Ollama server is not reachable at {base_url} ({e})") from e

    obj = json.loads(raw)
    return obj["message"]["content"]


def _extract_json_block(text: str) -> dict[str, Any]:
    """
    Extract the first JSON object found in model output.
    """
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        raise ValueError("No JSON object found in model output.")
    return json.loads(m.group(0))


def run_du_llm(
    ocr_text: str,
    rule_candidates: dict[str, Any],
    ocr_lines: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    Run LLM-based extraction.

    Notes:
    - We PROVIDE ocr_lines to the model so it can cite a valid 0-based line_index.
    - We DO NOT fabricate evidence. If the model doesn't provide evidence, we keep it empty/null.
    - We only normalize/validate evidence to avoid out-of-range indices and mismatched line_text.
    """
    print("[du_llm] run_du_llm called")
    model = (os.getenv("OLLAMA_MODEL") or "").strip()
    if not model:
        raise RuntimeError("OLLAMA_MODEL is not set (empty). Check your .env file.")

    if ocr_lines is None:
        # Derive a lines list so the model can cite indexes deterministically.
        ocr_lines = [ln for ln in (ocr_text or "").splitlines()]

    system = (
        "You extract structured fields from receipt OCR.\n"
        "Return ONLY valid JSON matching the required schema.\n"
        "If a field is unknown, use null.\n"
        "Evidence MUST reference ocr_lines with a 0-based line_index and exact line_text.\n"
        "If you cannot find supporting evidence in ocr_lines, set that evidence entry to nulls.\n"
        "Return JSON only (no markdown).\n"
    )

    user = {
        "ocr_lines": ocr_lines,
        "rule_candidates": rule_candidates,
        "required_schema": {
            "extracted": {
                "merchant": "string|null",
                "date": "string|null",
                "total": "number|null",
                "currency": "string|null",
            },
            "evidence": {
                "merchant": {"line_index": "int|null", "line_text": "string|null"},
                "date": {"line_index": "int|null", "line_text": "string|null"},
                "total": {"line_index": "int|null", "line_text": "string|null"},
                "currency": {"line_index": "int|null", "line_text": "string|null"},
            },
        },
        "rules": [
            "Do not invent values that are not in ocr_lines.",
            "Prefer rule_candidates only when consistent with ocr_lines.",
            "Total must be the final payable amount (not cash tendered, not change due).",
        ],
    }

    print("[du_llm] before _ollama_chat", file=sys.stderr, flush=True)
    try: 
        text = _ollama_chat(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
            ],
        )
        print("[du_llm] after _ollama_chat", file=sys.stderr, flush=True)
        print("[du_llm] RAW:", text[:500])
    except Exception as e:
        import traceback
        print("[du_llm] _ollama_chat ERROR:", repr(e), flush=True)
        traceback.print_exc()
        raise

    parsed = _extract_json_block(text)
    print("[du_llm] PARSED:", parsed)

    return parsed