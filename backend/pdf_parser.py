from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader

from db import connect, init_db, record_health


DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}/(?:\d{2}|\d{4})\b")
AMOUNT_RE = re.compile(
    r"(Over\s+\$[\d,.\s]+|\$[\d,.\s]+\s*[-–•]\s*\$?[\d,.\s]+)",
    re.I,
)
ROW_START_RE = re.compile(r"^\s*(\d{1,5})\s+(.+)")
ROW_NUMBER_ONLY_RE = re.compile(r"^\s*(\d{1,5})\s*$")
TYPE_RE = re.compile(
    r"\b(Purchase|Sale|Exchange|Puchase|Purchasc|Purchaso|purchsso|purchaso|nurchasc|ourchase|ourchoso|ourdulso|ourchaso|lourchase|lourchoso|lourchaso|IPurchaso|salo)\b",
    re.I,
)
TICKER_RE = re.compile(r"\(([A-Z][A-Z0-9.\-]{0,7})\)")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(text: str) -> str:
    return (
        text.replace("\u2022", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u00a0", " ")
        .replace("S1", "$1")
        .replace("s1", "$1")
        .replace("S250", "$250")
        .replace("s250", "$250")
        .replace("s100", "$100")
        .replace("sso", "$50")
        .replace("VOS", "Yes")
        .replace("ves", "Yes")
        .replace("□", "D")
    )


def _normalize_type(value: str | None) -> str | None:
    if not value:
        return None
    v = value.lower()
    if "sale" in v or "salo" in v:
        return "Sale"
    if "exchange" in v:
        return "Exchange"
    return "Purchase"


def _row_chunks(lines: list[str]) -> list[str]:
    chunks = []
    current = ""
    pending_number = None
    for raw in lines:
        line = _clean(raw.strip())
        if not line:
            continue
        if "Endnotes" in line or line.startswith("PART #") or "Part 4:" in line:
            if current:
                chunks.append(current)
                current = ""
            break
        if (
            line.startswith("# ")
            or "DESCRIPTION TYPE DATE" in line.upper()
            or "AMOUNT" == line.upper()
            or "FILER" in line.upper()
            or "OGE FORM" in line.upper()
            or "TRANSACTION" in line.upper()
            or "NOTIFICATION" in line.upper()
            or "RECEIVED OVER" in line.upper()
        ):
            continue
        number_only = ROW_NUMBER_ONLY_RE.match(line)
        row_start = ROW_START_RE.match(line)
        if number_only:
            if current:
                chunks.append(current)
            pending_number = number_only.group(1)
            current = pending_number
            continue
        if row_start:
            if current:
                chunks.append(current)
            current = line
            pending_number = None
            continue
        if pending_number:
            current = f"{pending_number} {line}"
            pending_number = None
            continue
        if current:
            current += " " + line
    if current:
        chunks.append(current)
    return chunks


def _parse_chunk(chunk: str) -> dict | None:
    date_match = DATE_RE.search(chunk)
    amount_match = AMOUNT_RE.search(chunk)
    type_match = TYPE_RE.search(chunk)
    if not date_match or not amount_match:
        return None
    before_date = chunk[: date_match.start()].strip()
    before_date = re.sub(r"^\d+\s+", "", before_date)
    tx_type = _normalize_type(type_match.group(1) if type_match else None)
    asset = before_date
    if type_match:
        asset = before_date[: type_match.start()].strip()
    asset = re.sub(r"\s+See Endnote\s*$", "", asset, flags=re.I).strip(" -")
    ticker_matches = TICKER_RE.findall(asset)
    confidence = 0.72
    if type_match:
        confidence += 0.15
    if asset:
        confidence += 0.08
    if re.search(r"nurchasc|ourchaso|Purchasc", chunk, re.I):
        confidence -= 0.2
    amount = amount_match.group(1).replace("•", "-").replace(".", ",")
    amount = re.sub(r"(?<=\d)\s+(?=\d{3}\b)", ",", amount)
    amount = re.sub(r"\s+,", ",", amount)
    amount = re.sub(r",\s+", ",", amount)
    amount = re.sub(r"\s+", " ", amount)
    amount = amount.replace("$1,000,000", "$1,000,000")
    tx_date = date_match.group(0)
    date_parts = tx_date.split("/")
    if len(date_parts[-1]) == 2:
        date_parts[-1] = "20" + date_parts[-1]
        tx_date = "/".join(date_parts)
    return {
        "asset_name": asset or None,
        "ticker": ticker_matches[-1] if ticker_matches else None,
        "transaction_type": tx_type,
        "transaction_date": tx_date,
        "amount_range": amount,
        "raw_text": re.sub(r"\s+", " ", chunk).strip(),
        "confidence": max(0.1, min(confidence, 0.98)),
    }


def parse_pdf(path: Path) -> list[dict]:
    reader = PdfReader(str(path))
    records = []
    for page_idx, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        chunks = _row_chunks(text.splitlines())
        for chunk in chunks:
            parsed = _parse_chunk(chunk)
            if parsed:
                parsed["source_page"] = page_idx
                records.append(parsed)
    return records


def ingest_oge_transactions() -> dict:
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
              AND f.filing_type = '278-T'
            """
        ).fetchall()
        try:
            for doc in docs:
                local_path = Path(doc["local_path"])
                if not local_path.exists():
                    continue
                records = parse_pdf(local_path)
                parsed_count += len(records)
                for rec in records:
                    review_state = "parsed" if rec["confidence"] >= 0.85 else "needs_review"
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
            record_health(conn, "pdf_parser", "ok", f"parsed={parsed_count}; inserted={inserted}")
        except Exception as exc:
            record_health(conn, "pdf_parser", "error", repr(exc))
            raise
    return {"documents": len(docs), "parsed": parsed_count, "inserted": inserted}


if __name__ == "__main__":
    print(json.dumps(ingest_oge_transactions(), indent=2))
