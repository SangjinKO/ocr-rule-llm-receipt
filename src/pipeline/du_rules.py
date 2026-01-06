import re
from dataclasses import dataclass
from typing import Any


@dataclass
class Candidate:
    value: str
    line_index: int
    line_text: str
    score: float = 0.0


def split_lines(ocr_text: str) -> list[str]:
    return [ln.strip() for ln in (ocr_text or "").splitlines() if ln.strip()]


def find_date_candidates(lines: list[str]) -> list[Candidate]:
    """
    Find likely receipt dates.
    Supports common formats: MM/DD/YY, MM/DD/YYYY, DD/MM/YY, YYYY-MM-DD.
    """
    patterns = [
        re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b"),        # 08/20/10
        re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"),          # 2026-01-05
        re.compile(r"\b(\d{1,2})-(\d{1,2})-(\d{2,4})\b"),        # 08-20-2010
        re.compile(r"\b(19|20)\d{2}/\d{1,2}/\d{1,2}\b"),        # YYYY/MM/DD
        re.compile(r"\b(19|20)\d{2}\.\d{1,2}\.\d{1,2}\b"),        # YYYY.MM.DD
    ]
    cands: list[Candidate] = []

    for i, ln in enumerate(lines):
        for pat in patterns:
            m = pat.search(ln)
            if not m:
                continue
            val = m.group(0)
            # score hint: dates near bottom often appear with time
            score = 0.6
            if re.search(r"\b\d{1,2}:\d{2}(:\d{2})?\b", ln):
                score += 0.2
            if i > len(lines) * 0.6:
                score += 0.1
            cands.append(Candidate(value=val, line_index=i, line_text=ln, score=score))

    # sort best-first
    cands.sort(key=lambda x: x.score, reverse=True)
    return cands[:5]


def find_total_candidates(lines: list[str]) -> list[Candidate]:
    """
    Find likely totals using keyword anchors.
    We look for lines containing TOTAL / AMOUNT DUE / BALANCE and then extract a number.
    """
    anchors = ("total", "amount due", "balance due", "grand total", "to pay")
    money_re = re.compile(r"(?<!\w)(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})|\d+(?:[.,]\d{2}))(?!\w)")
    cands: list[Candidate] = []

    for i, ln in enumerate(lines):
        low = ln.lower()
        if not any(a in low for a in anchors):
            continue

        # Extract amount from same line; otherwise check next line (common receipt layout)
        m = money_re.search(ln)
        if m:
            amt = m.group(1)
            score = 0.8
            if "total" in low:
                score += 0.1
            cands.append(Candidate(value=amt, line_index=i, line_text=ln, score=score))
            continue

        if i + 1 < len(lines):
            m2 = money_re.search(lines[i + 1])
            if m2:
                amt = m2.group(1)
                score = 0.75
                cands.append(Candidate(value=amt, line_index=i + 1, line_text=lines[i + 1], score=score))

    # Fallback: last money-like number near bottom (weak)
    if not cands:
        for i in range(len(lines) - 1, max(-1, len(lines) - 12), -1):
            m = money_re.search(lines[i])
            if m:
                cands.append(Candidate(value=m.group(1), line_index=i, line_text=lines[i], score=0.4))
                break

    cands.sort(key=lambda x: x.score, reverse=True)
    return cands[:5]


def find_currency_candidates(lines: list[str]) -> list[Candidate]:
    """
    Heuristic currency detection from symbols and common codes.
    """
    cands: list[Candidate] = []
    for i, ln in enumerate(lines):
        if "$" in ln:
            cands.append(Candidate(value="USD", line_index=i, line_text=ln, score=0.6))
        if "€" in ln:
            cands.append(Candidate(value="EUR", line_index=i, line_text=ln, score=0.6))
        if "£" in ln:
            cands.append(Candidate(value="GBP", line_index=i, line_text=ln, score=0.6))
        if re.search(r"\bUSD\b", ln):
            cands.append(Candidate(value="USD", line_index=i, line_text=ln, score=0.7))
        if re.search(r"\bEUR\b", ln):
            cands.append(Candidate(value="EUR", line_index=i, line_text=ln, score=0.7))

    cands.sort(key=lambda x: x.score, reverse=True)
    return cands[:3]


def find_merchant_candidates(lines: list[str]) -> list[Candidate]:
    """
    Merchant is often in the first ~5 lines, sometimes in all caps.
    We rank early lines that look like a store name.
    """
    cands: list[Candidate] = []
    head = lines[:8]

    for i, ln in enumerate(head):
        if len(ln) < 3:
            continue

        # Ignore "OPEN 24 HOURS", phone numbers, IDs
        if re.search(r"\b(open|hours|tel|phone|tr#|st#|tc#)\b", ln.lower()):
            continue
        if re.search(r"\(\d{3}\)\d", ln):
            continue

        score = 0.5
        if ln.isupper():
            score += 0.2
        if i == 0:
            score += 0.2
        cands.append(Candidate(value=ln, line_index=i, line_text=ln, score=score))

    cands.sort(key=lambda x: x.score, reverse=True)
    return cands[:5]


def build_rule_candidates(ocr_text: str) -> dict[str, Any]:
    """
    Main entry for rule-based candidate extraction.
    Returns a compact dict to feed into the LLM prompt.
    """
    lines = split_lines(ocr_text)

    def pack(items: list[Candidate]) -> list[dict[str, Any]]:
        return [
            {
                "value": c.value,
                "line_index": c.line_index,
                "line_text": c.line_text,
                "score": c.score,
            }
            for c in items
        ]

    return {
        "merchant": pack(find_merchant_candidates(lines)),
        "date": pack(find_date_candidates(lines)),
        "total": pack(find_total_candidates(lines)),
        "currency": pack(find_currency_candidates(lines)),
        "line_count": len(lines),
    }
