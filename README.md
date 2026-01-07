# OCR + Rule + LLM Receipt Understanding

**Date:** 2026.01  

## Goal
Build a **local-first receipt understanding system** that:
- Extracts structured fields from receipt images using **OCR → Rules → LLM**
- Preserves **raw LLM outputs and evidence** without post-fabrication
- Stores results in a lightweight **SQLite database**
- Provides a **transparent Streamlit UI** for inspection and debugging
- Works fully **offline except for local LLM (Ollama)**

This project focuses on **correctness, debuggability, and explainability** rather than aggressive automation.


## What This Project Focuses On

- End-to-end receipt processing pipeline:  
  **Image → OCR → Rule candidates → LLM extraction**
- Explicit separation of concerns:
  - OCR: text acquisition only
  - Rules: candidate narrowing
  - LLM: semantic extraction
- **No hallucinated evidence**
  - Evidence is shown *only if the LLM explicitly provides it*
- Transparent UI for:
  - OCR text
  - Extracted fields
  - Raw LLM (DU) output
- Simple, inspectable storage using SQLite (no ORM)


## Tech Stack

### Core
- **Language:** Python 3.10+
- **UI:** Streamlit
- **OCR:** PaddleOCR (local, singleton)
- **Database:** SQLite

### Understanding Layer
- **Rule-based candidates:** regex + heuristics
- **LLM:** Ollama (local inference via HTTP)


## Key Features

- Upload receipt images via UI
- OCR text extraction with confidence scores
- Rule-based candidate generation (merchant, date, total, currency)
- LLM-based extraction with **raw evidence**
- Best-effort fallback using rule candidates (clearly separated)
- Persistent storage of:
  - OCR text
  - OCR JSON
  - LLM output (raw)
  - Metadata (hash, timestamps, errors)
- Zero cloud dependency (except optional local LLM)


## Application Flow

1. Upload a receipt image  
2. Run OCR (PaddleOCR, singleton)  
3. Generate rule candidates  
4. Call local LLM (Ollama)  
5. Store results in SQLite  
6. Inspect everything via UI  



## Repository Structure

```text
ocr-du-llm-receipt/
├── .env
├── app.py                     # Streamlit UI
├── requirements.txt
├── receipt_db.sqlite3         # SQLite DB (local)
├── data/
│   └── inbox/                 # Uploaded receipt images
└── src/
    ├── pipeline/
    │   ├── ocr.py             # PaddleOCR wrapper
    │   ├── du_rules.py        # Rule-based candidates
    │   ├── du_llm.py          # Ollama LLM extraction
    │   └── process_receipt.py # End-to-end pipeline
    ├── storage/
    │   ├── db.py              # SQLite helpers
    │   └── schema.sql
    └── utils/
        ├── files.py
        └── timeutils.py
```

## How to Run

### 1. Create a virtual environment and install dependencies
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Install and run Ollama (local LLM server)
- download Ollama from https://ollama.com/download
- launch Ollama.app
- pull the test model: 
```bash
ollama pull llama3.2:3b
ollama run llama3.2:3b
```

### 3. Configure LLM environment (.env)
- create a `.env` file in the project root as below

```env
# Ollama settings
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b
OCR_LANG=en
```

### 4. Run the Streamlit app
```bash
streamlit run app.py
```
<img width="855" height="329" alt="image" src="https://github.com/user-attachments/assets/4e2b6af9-b64a-45af-9565-60f344eb3e98" />

