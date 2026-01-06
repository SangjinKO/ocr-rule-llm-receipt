import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence


@dataclass
class OCRLine:
    text: str
    confidence: float | None = None


# Process-wide singleton (one PaddleOCR instance per process)
_OCR_INSTANCE: Any = None
_OCR_LANG: Optional[str] = None


def _get_ocr_instance() -> Any:
    """
    Return a cached PaddleOCR instance (initialized once per process).
    """
    global _OCR_INSTANCE, _OCR_LANG

    lang = (os.getenv("OCR_LANG") or "en").strip() or "en"
    if _OCR_INSTANCE is not None and _OCR_LANG == lang:
        return _OCR_INSTANCE

    print(f"[ocr] initializing PaddleOCR (lang={lang})")
    from paddleocr import PaddleOCR  # type: ignore

    _OCR_INSTANCE = PaddleOCR(use_angle_cls=True, lang=lang)
    _OCR_LANG = lang
    return _OCR_INSTANCE


def _get_field(obj: Any, name: str) -> Any:
    """
    Access a field from an OCRResult-like object.
    Supports:
      - attribute access: obj.rec_texts
      - dict-like access: obj["rec_texts"]
    """
    if obj is None:
        return None

    # attribute access (OCRResult is a custom class)
    if hasattr(obj, name):
        return getattr(obj, name)

    # dict-like
    try:
        return obj[name]  # type: ignore[index]
    except Exception:
        return None


def extract_lines(image_path: str | Path) -> list[OCRLine]:
    """
    Extract text lines from PaddleOCR structured output.

    This implementation is intentionally strict and matches the observed format:
      result: list with one OCRResult per image
      OCRResult.rec_texts : list[str]
      OCRResult.rec_scores: list[float]

    If the format changes, this function returns [].
    """
    image_path = str(image_path)
    ocr = _get_ocr_instance()

    # Prefer predict() to avoid deprecation warnings, fallback to ocr().
    result: Any = None
    if hasattr(ocr, "predict"):
        try:
            result = ocr.predict(image_path)
        except Exception:
            result = None

    if result is None:
        result = ocr.ocr(image_path)  # deprecated upstream, but works as fallback

    if not isinstance(result, list) or len(result) == 0:
        return []

    page0 = result[0]

    rec_texts = _get_field(page0, "rec_texts")
    rec_scores = _get_field(page0, "rec_scores")

    if not isinstance(rec_texts, list) or not all(isinstance(t, str) for t in rec_texts):
        return []

    lines: list[OCRLine] = []

    if isinstance(rec_scores, list) and len(rec_scores) == len(rec_texts):
        for t, s in zip(rec_texts, rec_scores):
            t = t.strip()
            if not t:
                continue
            conf = float(s) if isinstance(s, (int, float)) else None
            lines.append(OCRLine(text=t, confidence=conf))
    else:
        for t in rec_texts:
            t = t.strip()
            if t:
                lines.append(OCRLine(text=t, confidence=None))

    return lines
