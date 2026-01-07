import json
from pathlib import Path
from typing import Any, Dict, Optional

from src.pipeline.ocr import extract_lines
from src.pipeline.du_llm import run_du_llm
from src.pipeline.du_rules import build_rule_candidates
from src.utils.files import sha256_file
from src.utils.timeutils import now_iso_utc


def _as_dict(x: Any) -> Dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _as_list(x: Any) -> list:
    return x if isinstance(x, list) else []


def _top_candidate_value(candidates: Dict[str, Any], key: str) -> Any:
    """
    candidates expected like:
      {"date": [{"value": "...", ...}, ...], "currency": [{"value": "USD", ...}], ...}
    but we also tolerate list of plain values.
    """
    arr = _as_list(candidates.get(key))
    if not arr:
        return None
    c0 = arr[0]
    if isinstance(c0, dict) and "value" in c0:
        return c0.get("value")
    return c0


def process_receipt(path: str | Path) -> Dict[str, Any]:
    """
    Flat receipt_json for DB upsert:
      merchant, receipt_date, total_amount, currency,
      ocr_text, ocr_json, du_json, meta_json

    Policy:
    - Keep du_json RAW as returned by LLM (no normalization, no guessing evidence).
    - extracted used for top-level fields must be a dict; if not, treat as empty dict.
    - Never crash pipeline: record du_error in meta_json on DU failure.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(str(path))

    started_at = now_iso_utc()
    source_sha = sha256_file(path)

    # 1) OCR
    ocr_lines = extract_lines(path)
    line_texts = [getattr(l, "text", "") for l in ocr_lines]
    ocr_text = "\n".join([t for t in line_texts if t]).strip()

    # Stable OCR JSON
    ocr_json = {
        "lines": [
            {
                "text": getattr(l, "text", ""),
                "confidence": float(getattr(l, "confidence", getattr(l, "conf", 0.0))),
            }
            for l in ocr_lines
        ],
        "text": ocr_text,
    }

    # 2) Rules
    rule_candidates = _as_dict(build_rule_candidates(ocr_text))

    # 3) DU (LLM) — keep RAW, never crash pipeline
    du_error: Optional[str] = None
    du_json: Dict[str, Any] = {"extracted": {}, "evidence": {}}  # default minimal

    try:
        # Pass OCR lines so model can cite indices (even if it sometimes doesn't)
        du_json = run_du_llm(ocr_text, rule_candidates, ocr_lines=line_texts)
    except Exception as e:
        # FAIL FAST — do NOT continue
        raise RuntimeError(f"LLM processing failed: {e}") from e

    # du_json must be dict
    if not isinstance(du_json, dict):
        raise RuntimeError("LLM returned non-dict output (invalid DU payload).")

    # extracted must be dict
    extracted = du_json.get("extracted")
    if not isinstance(extracted, dict):
        raise RuntimeError("LLM output missing 'extracted' dict.")

    # 4) Fallbacks (only for extracted fields, NOT evidence)
    if not extracted.get("date"):
        extracted["date"] = _top_candidate_value(rule_candidates, "date")

    if not extracted.get("currency"):
        extracted["currency"] = _top_candidate_value(rule_candidates, "currency")

    if not extracted.get("merchant"):
        extracted["merchant"] = _top_candidate_value(rule_candidates, "merchant")

    if extracted.get("total") is None:
        extracted["total"] = _top_candidate_value(rule_candidates, "total")

    # Write back extracted (so du_json stays consistent with fallbacks)
    du_json["extracted"] = extracted

    # 5) Final receipt_json (flat)
    receipt_json: Dict[str, Any] = {
        "merchant": extracted.get("merchant"),
        "receipt_date": extracted.get("date"),
        "total_amount": extracted.get("total"),
        "currency": extracted.get("currency"),
        "ocr_text": ocr_text,
        "ocr_json": ocr_json,
        "du_json": du_json,  # ✅ RAW evidence preserved (dict or list)
        "meta_json": {
            "source_path": str(path),
            "source_sha": source_sha,
            "started_at": started_at,
            "processed_at": now_iso_utc(),
            "ocr_line_count": len(ocr_lines),
            "du_error": du_error,
            "rule_candidates": rule_candidates,
        },
    }

    # Ensure serializability
    json.dumps(receipt_json, ensure_ascii=False)
    return receipt_json
