from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from src.pipeline.process_receipt import process_receipt
from src.storage.db import init_db, upsert_receipt, list_receipts, get_receipt_by_id
import streamlit as st

from dotenv import load_dotenv
load_dotenv()

APP_ROOT = Path(__file__).resolve().parent
DATA_INBOX = APP_ROOT / "data" / "inbox"
DB_PATH = APP_ROOT / "receipt_db.sqlite3"
SCHEMA_PATH = APP_ROOT / "src" / "storage" / "schema.sql"


def _ensure_dirs() -> None:
    DATA_INBOX.mkdir(parents=True, exist_ok=True)


def _save_upload_to_inbox(uploaded_file) -> Path:
    """
    Save uploaded file into data/inbox once per explicit Run action.
    """
    _ensure_dirs()

    ext = Path(uploaded_file.name).suffix.lower()
    if ext not in [".png", ".jpg", ".jpeg", ".webp"]:
        ext = ".jpg"

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"ui_{ts}{ext}"
    out_path = DATA_INBOX / filename
    out_path.write_bytes(uploaded_file.getbuffer())
    return out_path


def _render_ocr(ocr_text: Optional[str], ocr_json: Optional[Dict[str, Any]], key_prefix: str) -> None:
    st.subheader("OCR Text")
    st.text_area(
        "ocr_text",
        value=ocr_text or "",
        height=220,
        key=f"{key_prefix}_ocr_text_area",
    )
    with st.expander("ocr_json (stored)", expanded=False):
        st.json(ocr_json or {})


def _render_du(du_json: Optional[Dict[str, Any]]) -> None:
    du_json = du_json or {}
    extracted = du_json.get("extracted") if isinstance(du_json, dict) else {}
    evidence = du_json.get("evidence") if isinstance(du_json, (dict, list)) else {}

    st.subheader("Extracted (LLM)")
    st.json(extracted or {})

    st.subheader("Evidence")
    st.json(evidence or {})

    with st.expander("DU raw payload"):
        st.json(du_json)


def main() -> None:
    st.set_page_config(page_title="Receipt OCR → Rule → LLM", layout="wide")
    st.title("Receipt Processing (OCR → Rule → LLM)")

    init_db(DB_PATH, SCHEMA_PATH)

    tab1, tab2 = st.tabs(["Upload & Process", "Saved Receipts"])

    # -------------------------
    # Tab 1: Upload & Process
    # -------------------------
    with tab1:
        st.header("Upload & Process (Single Receipt)")

        uploaded = st.file_uploader("Upload a receipt image", type=["png", "jpg", "jpeg", "webp"])

        # Avoid duplicate saves on Streamlit reruns
        if "tab1_saved_path" not in st.session_state:
            st.session_state["tab1_saved_path"] = None
        if "tab1_file_sig" not in st.session_state:
            st.session_state["tab1_file_sig"] = None

        if not uploaded:
            st.info("Upload a receipt image to begin.")
        else:
            st.subheader("Preview (not saved yet)")
            st.image(uploaded, use_container_width=True)
            st.caption(f"{uploaded.name} ({uploaded.size} bytes)")

            run = st.button("Run OCR → Rule → LLM and Save", type="primary")

            if run:
                file_sig = (uploaded.name, uploaded.size)

                if st.session_state["tab1_file_sig"] != file_sig or not st.session_state["tab1_saved_path"]:
                    saved_path = _save_upload_to_inbox(uploaded)
                    st.session_state["tab1_saved_path"] = str(saved_path)
                    st.session_state["tab1_file_sig"] = file_sig
                else:
                    saved_path = Path(st.session_state["tab1_saved_path"])

                st.divider()
                st.subheader("Saved Image (data/inbox)")
                st.image(str(saved_path), use_container_width=True)
                st.caption(f"Saved to: {saved_path}")

                with st.spinner("Processing... (OCR → Rule → LLM → DB upsert)"):
                    receipt_json = process_receipt(saved_path)

                    # ensure meta_json has source_path for display
                    meta = receipt_json.get("meta_json") or {}
                    if not isinstance(meta, dict):
                        meta = {}
                    meta.setdefault("source_path", str(saved_path))
                    receipt_json["meta_json"] = meta

                    result = upsert_receipt(receipt_json, db_path=DB_PATH)

                st.success("Saved to database")
                st.json(result)

                st.divider()
                _render_ocr(receipt_json.get("ocr_text"), receipt_json.get("ocr_json"), key_prefix="tab1_run")
                _render_du(receipt_json.get("du_json"))

    # -------------------------
    # Tab 2: Saved Receipts (DB viewer only)
    # -------------------------
    with tab2:
        st.header("Saved Receipts (DB)")

        rows = list_receipts(DB_PATH, limit=200)
        if not rows:
            st.info("No receipts in DB yet. Use 'Upload & Process' first.")
            return

        # Build a human-friendly label list
        options = []
        id_by_label: Dict[str, int] = {}
        for r in rows:
            rid = r["id"]
            merchant = r.get("merchant") or "(no merchant)"
            rdate = r.get("receipt_date") or "(no date)"
            total = r.get("total_amount")
            currency = r.get("currency") or ""
            total_str = f"{total:.2f}" if isinstance(total, (int, float)) else "?"
            label = f"#{rid} | {rdate} | {merchant} | {total_str} {currency}".strip()
            options.append(label)
            id_by_label[label] = rid

        selected = st.selectbox("Select a receipt", options, index=0, key="tab2_select_receipt")
        receipt_id = id_by_label[selected]

        rec = get_receipt_by_id(DB_PATH, receipt_id)
        if not rec:
            st.error("Receipt not found (unexpected).")
            return

        # Display image if path exists
        source_path = (rec.get("meta_json") or {}).get("source_path")
        if source_path and Path(source_path).exists():
            st.subheader("Source Image")
            st.image(source_path, use_container_width=True)
            st.caption(source_path)
        else:
            st.warning("Source image path is missing or file no longer exists.")

        st.divider()
        st.subheader("Stored Fields")
        st.json(
            {
                "id": rec.get("id"),
                "merchant": rec.get("merchant"),
                "receipt_date": rec.get("receipt_date"),
                "total_amount": rec.get("total_amount"),
                "currency": rec.get("currency"),
                "source_sha": rec.get("source_sha"),
                "source_path": source_path,
                "created_at": rec.get("created_at"),
                "updated_at": rec.get("updated_at"),
            }
        )

        st.divider()
        _render_ocr(rec.get("ocr_text"), rec.get("ocr_json"), key_prefix=f"tab2_{receipt_id}")
        _render_du(rec.get("du_json"))

        with st.expander("meta_json (stored)", expanded=False):
            st.json(rec.get("meta_json") or {})


if __name__ == "__main__":
    main()
