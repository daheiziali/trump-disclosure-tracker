from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber
from pypdf import PdfReader

from db import connect, init_db, record_health


VALUE_RE = re.compile(
    r"(Over\s+\$[\d,]+(?:,\d{3})*|\$[\d,]+(?:,\d{3})*\s*(?:-|to)\s*\$?[\d,]+(?:,\d{3})*|None \(or less than \$1,001\))",
    re.I,
)
INCOME_RE = re.compile(
    r"(None \(or less than \$201\)|\$[\d,]+(?:,\d{3})*\s*(?:-|to)\s*\$?[\d,]+(?:,\d{3})*|\$[\d,]+(?:,\d{3})*)",
    re.I,
)
ROW_RE = re.compile(r"^\s*(\d{1,5}(?:\.\d+)?)\s+(.+)")
TICKER_RE = re.compile(r"\(([A-Z][A-Z0-9.\-]{0,7})\)")
INCOME_TYPE_WORDS = (
    "DIVIDEND",
    "INTEREST",
    "Capital Gains",
    "Dividend/Capital Gains",
    "Rent or Royalties",
    "Royalty",
    "Validator rewards",
)
TX_TYPE_RE = re.compile(r"^(purchase|sale|exchange)$", re.I)
TX_DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
TX_AMOUNT_RE = re.compile(r"^(Over\s+)?\$[\d,]+(?:\s*-\s*\$?[\d,]+)?$", re.I)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(text: str) -> str:
    return (
        text.replace("\u00a0", " ")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("NIA", "N/A")
    )


def _income_type_between(text: str, start: int, end: int) -> str | None:
    mid = text[start:end]
    for word in INCOME_TYPE_WORDS:
        if re.search(re.escape(word), mid, re.I):
            return word
    return None


def _parse_holding_line(line: str, page_num: int, account_name: str | None) -> dict | None:
    line = _clean(re.sub(r"\s+", " ", line)).strip()
    match = ROW_RE.match(line)
    if not match:
        return None
    body = match.group(2).strip()
    value_match = VALUE_RE.search(body)
    if not value_match:
        return None
    asset = body[: value_match.start()].strip(" -")
    asset = re.sub(r"\s+(N/A|Yes|No|y)$", "", asset, flags=re.I).strip()
    if not asset or asset.upper() in {"N/A", "NO"}:
        return None
    tail = body[value_match.end() :].strip()
    income_range = None
    income_type = None
    income_match = INCOME_RE.search(tail)
    if income_match:
        income_range = income_match.group(1)
        income_type = _income_type_between(tail, 0, income_match.start())
    ticker_matches = TICKER_RE.findall(asset)
    confidence = 0.7
    if income_match:
        confidence += 0.1
    if re.search(r"\bN/A\b|\bYes\b|\bNo\b", body):
        confidence += 0.08
    if account_name:
        confidence += 0.04
    return {
        "section": "Part 6",
        "account_name": account_name,
        "asset_name": asset,
        "ticker": ticker_matches[-1] if ticker_matches else None,
        "value_range": re.sub(r"\s+", " ", value_match.group(1)),
        "income_type": income_type,
        "income_range": re.sub(r"\s+", " ", income_range) if income_range else None,
        "source_page": page_num,
        "raw_text": line,
        "confidence": min(confidence, 0.96),
    }


def parse_annual_pdf(path: Path) -> list[dict]:
    reader = PdfReader(str(path))
    records = []
    in_part6 = False
    account_name = None
    for page_num, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if "Part 7: Transactions" in text or "Part 8: Liabilities" in text:
            in_part6 = False
        if "Part 6: Other Assets and Income" in text:
            in_part6 = True
        if not in_part6:
            continue
        lines = [_clean(line.strip()) for line in text.splitlines() if line.strip()]
        chunks = []
        current = ""
        for line in lines:
            if re.match(r"^INVESTMENT ACCOUNT #\d+", line):
                if current:
                    chunks.append(current)
                    current = ""
                account_name = line
                continue
            if ROW_RE.match(line):
                if current:
                    chunks.append(current)
                current = line
                continue
            if current and not line.startswith(("Instructions for", "Note:", "# Description", "Filer's Name")):
                current += " " + line
        if current:
            chunks.append(current)
        for chunk in chunks:
            parsed = _parse_holding_line(chunk, page_num, account_name)
            if parsed:
                records.append(parsed)
    return records


def _parse_transaction_row(row: list[str | None], page_num: int, account_name: str | None) -> dict | None:
    cells = [re.sub(r"\s+", " ", _clean(str(cell or ""))).strip() for cell in row]
    if len(cells) < 5:
        return None
    number, asset, tx_type, tx_date, amount = cells[:5]
    if not re.fullmatch(r"\d{1,5}", number or ""):
        if asset.upper().startswith("INVESTMENT ACCOUNT"):
            return {"_account": asset}
        return None
    if not asset or not TX_TYPE_RE.match(tx_type or ""):
        return None
    if not TX_DATE_RE.match(tx_date or ""):
        return None
    if not TX_AMOUNT_RE.match(amount or ""):
        return None
    asset = re.sub(r"\s+-\s*$", "", asset).strip()
    ticker_matches = TICKER_RE.findall(asset)
    raw_text = " | ".join([number, asset, tx_type, tx_date, amount])
    confidence = 0.94
    if account_name:
        confidence += 0.02
    return {
        "section": "Part 7",
        "account_name": account_name,
        "asset_name": asset,
        "ticker": ticker_matches[-1] if ticker_matches else None,
        "transaction_type": "Purchase" if tx_type.lower() == "purchase" else tx_type.title(),
        "transaction_date": tx_date,
        "amount_range": amount,
        "source_page": page_num,
        "raw_text": raw_text,
        "confidence": min(confidence, 0.98),
    }


def parse_annual_transactions_pdf(path: Path) -> list[dict]:
    records = []
    with pdfplumber.open(str(path)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if "Part 8:" in text or "Part 9:" in text:
                if records:
                    break
            if "Part 7: Transactions" not in text:
                continue
            account_name = None
            for table in page.extract_tables() or []:
                for row in table:
                    parsed = _parse_transaction_row(row, page_num, account_name)
                    if not parsed:
                        continue
                    if "_account" in parsed:
                        account_name = parsed["_account"]
                        continue
                    records.append(parsed)
    return records


def ingest_annual_holdings() -> dict:
    init_db()
    parsed_count = 0
    inserted = 0
    with connect() as conn:
        docs = conn.execute(
            """
            SELECT sd.id AS source_document_id, sd.local_path, f.id AS filing_id, f.person_name
            FROM source_documents sd
            JOIN filings f ON f.source_document_id = sd.id
            WHERE sd.source = 'oge'
              AND sd.document_type = 'oge_pdf'
              AND f.filing_type = '278e'
            """
        ).fetchall()
        try:
            for doc in docs:
                local_path = Path(doc["local_path"])
                if not local_path.exists():
                    continue
                records = parse_annual_pdf(local_path)
                parsed_count += len(records)
                for rec in records:
                    review_state = "parsed" if rec["confidence"] >= 0.85 else "needs_review"
                    cur = conn.execute(
                        """
                        INSERT OR IGNORE INTO parsed_holdings
                            (filing_id, source_document_id, person_name, section, account_name,
                             asset_name, ticker, value_range, income_type, income_range,
                             source_page, raw_text, confidence, review_state, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            doc["filing_id"],
                            doc["source_document_id"],
                            doc["person_name"],
                            rec["section"],
                            rec.get("account_name"),
                            rec.get("asset_name"),
                            rec.get("ticker"),
                            rec.get("value_range"),
                            rec.get("income_type"),
                            rec.get("income_range"),
                            rec.get("source_page"),
                            rec.get("raw_text"),
                            rec.get("confidence"),
                            review_state,
                            _utc_now(),
                        ),
                    )
                    inserted += cur.rowcount
            record_health(conn, "annual_parser", "ok", f"parsed={parsed_count}; inserted={inserted}")
        except Exception as exc:
            record_health(conn, "annual_parser", "error", repr(exc))
            raise
    return {"documents": len(docs), "parsed": parsed_count, "inserted": inserted}


def ingest_annual_transactions() -> dict:
    init_db()
    parsed_count = 0
    inserted = 0
    with connect() as conn:
        docs = conn.execute(
            """
            SELECT sd.id AS source_document_id, sd.local_path, f.id AS filing_id, f.person_name, f.filed_at
            FROM source_documents sd
            JOIN filings f ON f.source_document_id = sd.id
            WHERE sd.source = 'oge'
              AND sd.document_type = 'oge_pdf'
              AND f.filing_type = '278e'
            """
        ).fetchall()
        try:
            for doc in docs:
                local_path = Path(doc["local_path"])
                if not local_path.exists():
                    continue
                records = parse_annual_transactions_pdf(local_path)
                parsed_count += len(records)
                for rec in records:
                    review_state = "parsed" if rec["confidence"] >= 0.9 else "needs_review"
                    cur = conn.execute(
                        """
                        INSERT OR IGNORE INTO parsed_transactions
                            (filing_id, source_document_id, person_name, asset_name, ticker,
                             transaction_type, transaction_date, filed_date, amount_range,
                             source_page, raw_text, confidence, review_state, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            doc["filing_id"],
                            doc["source_document_id"],
                            doc["person_name"],
                            rec.get("asset_name"),
                            rec.get("ticker"),
                            rec.get("transaction_type"),
                            rec.get("transaction_date"),
                            doc["filed_at"],
                            rec.get("amount_range"),
                            rec.get("source_page"),
                            rec.get("raw_text"),
                            rec.get("confidence"),
                            review_state,
                            _utc_now(),
                        ),
                    )
                    inserted += cur.rowcount
            record_health(conn, "annual_part7_parser", "ok", f"parsed={parsed_count}; inserted={inserted}")
        except Exception as exc:
            record_health(conn, "annual_part7_parser", "error", repr(exc))
            raise
    return {"documents": len(docs), "parsed": parsed_count, "inserted": inserted}


if __name__ == "__main__":
    print(json.dumps({
        "holdings": ingest_annual_holdings(),
        "transactions": ingest_annual_transactions(),
    }, indent=2))
