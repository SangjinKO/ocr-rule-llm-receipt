import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_DB_PATH = "receipt_db.sqlite3"


def get_conn(db_path: str | Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


def init_db(db_path: str | Path, schema_path: str | Path) -> None:
    db_path = Path(db_path)
    schema_path = Path(schema_path)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    if not schema_path.exists():
        raise FileNotFoundError(str(schema_path))

    conn = get_conn(db_path)
    try:
        sql = schema_path.read_text(encoding="utf-8")
        conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()


def _to_json_text(val: Any) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, str):
        # assume already JSON text
        return val
    return json.dumps(val, ensure_ascii=False)


def _json_load_maybe(text: Any) -> Any:
    if text is None:
        return None
    if isinstance(text, (dict, list)):
        return text
    if not isinstance(text, str):
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def upsert_receipt(receipt_json: Dict[str, Any], db_path: str | Path) -> Dict[str, Any]:
    """
    Flat receipt_json expected keys:
      merchant, receipt_date, total_amount, currency,
      ocr_text, ocr_json, du_json, meta_json
    Required for de-dup: meta_json.source_sha (or receipt_json.source_sha).
    """
    db_path = Path(db_path)

    meta = receipt_json.get("meta_json") or {}
    if not isinstance(meta, dict):
        meta = {}

    source_sha = meta.get("source_sha") or receipt_json.get("source_sha")
    if not source_sha:
        raise ValueError("Missing source_sha. Ensure process_receipt sets meta_json.source_sha.")

    source_path = meta.get("source_path") or receipt_json.get("source_path")

    merchant = receipt_json.get("merchant")
    receipt_date = receipt_json.get("receipt_date")
    total_amount = receipt_json.get("total_amount")
    currency = receipt_json.get("currency")

    ocr_text = receipt_json.get("ocr_text")
    ocr_json_text = _to_json_text(receipt_json.get("ocr_json"))
    du_json_text = _to_json_text(receipt_json.get("du_json"))
    meta_json_text = _to_json_text({**meta, **({"source_path": source_path} if source_path else {})})

    conn = get_conn(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO receipts (
              source_sha, source_path,
              merchant, receipt_date, total_amount, currency,
              ocr_text, ocr_json, du_json, meta_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_sha) DO UPDATE SET
              source_path  = COALESCE(excluded.source_path, receipts.source_path),
              merchant     = excluded.merchant,
              receipt_date = excluded.receipt_date,
              total_amount = excluded.total_amount,
              currency     = excluded.currency,
              ocr_text     = excluded.ocr_text,
              ocr_json     = excluded.ocr_json,
              du_json      = excluded.du_json,
              meta_json    = excluded.meta_json,
              updated_at   = CURRENT_TIMESTAMP
            """,
            (
                source_sha,
                source_path,
                merchant,
                receipt_date,
                total_amount,
                currency,
                ocr_text,
                ocr_json_text,
                du_json_text,
                meta_json_text,
            ),
        )
        conn.commit()

        row = conn.execute(
            "SELECT id, created_at, updated_at FROM receipts WHERE source_sha = ?",
            (source_sha,),
        ).fetchone()
        rid = int(row["id"])

        inserted_or_updated = "updated"
        if row["created_at"] == row["updated_at"]:
            inserted_or_updated = "inserted"

        return {"receipt_id": rid, "inserted_or_updated": inserted_or_updated}
    finally:
        conn.close()


def list_receipts(db_path: str | Path, limit: int = 200) -> List[Dict[str, Any]]:
    """
    Minimal list for UI dropdown. No filters, no aggregation.
    """
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            """
            SELECT id, merchant, receipt_date, total_amount, currency
            FROM receipts
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_receipt_by_id(db_path: str | Path, receipt_id: int) -> Optional[Dict[str, Any]]:
    """
    Read a receipt (including stored JSON blobs) for UI detail view.
    """
    conn = get_conn(db_path)
    try:
        r = conn.execute(
            """
            SELECT
              id, source_sha, source_path,
              merchant, receipt_date, total_amount, currency,
              ocr_text, ocr_json, du_json, meta_json,
              created_at, updated_at
            FROM receipts
            WHERE id = ?
            """,
            (receipt_id,),
        ).fetchone()
        if not r:
            return None

        d = dict(r)
        d["ocr_json"] = _json_load_maybe(d.get("ocr_json")) or {}
        d["du_json"] = _json_load_maybe(d.get("du_json")) or {}
        d["meta_json"] = _json_load_maybe(d.get("meta_json")) or {}

        # ensure meta has source_path even if stored separately
        if d.get("source_path") and isinstance(d["meta_json"], dict):
            d["meta_json"].setdefault("source_path", d["source_path"])

        return d
    finally:
        conn.close()
