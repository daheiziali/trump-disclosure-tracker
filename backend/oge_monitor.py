from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

from config import OGE_TARGETS, RAW_DIR
from db import connect, init_db, insert_source_document, record_health
from net import fetch_bytes, save_bytes, sha256_bytes


OGE_API_URL = "https://extapps2.oge.gov/201/Presiden.nsf/API.xsp/v2/rest"
HREF_RE = re.compile(r"href=['\"]([^'\"]+)['\"]", re.I)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fetch_page(start: int, length: int = 1000) -> dict:
    url = f"{OGE_API_URL}?draw=1&start={start}&length={length}"
    data = fetch_bytes(url, timeout=45)
    return json.loads(data.decode("utf-8"))


def _matches_target(row: dict) -> bool:
    haystack = " ".join(str(row.get(k, "")) for k in ("name", "agency", "title", "type"))
    return any(re.search(rf"\b{re.escape(target)}\b", haystack, re.I) for target in OGE_TARGETS)


def _is_relevant_document(row: dict) -> bool:
    doc_type = html.unescape(str(row.get("type", "")))
    return bool(re.search(r"278 Transaction|278-T|Annual", doc_type, re.I))


def _extract_url(row: dict) -> str | None:
    raw_type = html.unescape(str(row.get("type", "")))
    match = HREF_RE.search(raw_type)
    if not match:
        return None
    return match.group(1)


def _filename_for(row: dict, url: str | None, suffix: str) -> str:
    name = re.sub(r"[^A-Za-z0-9]+", "_", str(row.get("name") or "unknown")).strip("_")
    doc_date = str(row.get("docDate") or "unknown").split("T")[0]
    if url:
        parsed_name = Path(unquote(urlparse(url).path)).name
        parsed_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", parsed_name)
    else:
        parsed_name = "metadata.json"
    return f"{doc_date}_{name}_{parsed_name}.{suffix}" if not parsed_name.endswith(f".{suffix}") else f"{doc_date}_{name}_{parsed_name}"


def scan_oge(max_pages: int | None = None) -> dict:
    init_db()
    downloaded = 0
    metadata_rows = 0
    matched = 0
    start = 0
    length = 1000
    page_count = 0
    with connect() as conn:
        try:
            while True:
                payload = _fetch_page(start, length)
                rows = payload.get("data", [])
                if not rows:
                    break
                page_count += 1
                for row in rows:
                    if not (_matches_target(row) and _is_relevant_document(row)):
                        continue
                    matched += 1
                    url = _extract_url(row)
                    title = f"{row.get('name')} - {html.unescape(str(row.get('type', '')))}"
                    if url and url.lower().endswith(".pdf"):
                        pdf = fetch_bytes(url, timeout=60)
                        local_path = RAW_DIR / "oge" / _filename_for(row, url, "pdf")
                        sha = save_bytes(local_path, pdf)
                        doc_id = insert_source_document(
                            conn,
                            {
                                "source": "oge",
                                "source_url": url,
                                "local_path": str(local_path),
                                "sha256": sha,
                                "fetched_at": _utc_now(),
                                "published_at": row.get("docDate"),
                                "document_type": "oge_pdf",
                                "title": title,
                            },
                        )
                        downloaded += 1
                    else:
                        raw = json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8")
                        local_path = RAW_DIR / "oge" / _filename_for(row, url, "json")
                        sha = save_bytes(local_path, raw)
                        doc_id = insert_source_document(
                            conn,
                            {
                                "source": "oge",
                                "source_url": url or OGE_API_URL,
                                "local_path": str(local_path),
                                "sha256": sha,
                                "fetched_at": _utc_now(),
                                "published_at": row.get("docDate"),
                                "document_type": "oge_metadata",
                                "title": title,
                            },
                        )
                        metadata_rows += 1
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO filings
                            (source_document_id, person_name, filing_type, filed_at, raw_json)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            doc_id,
                            row.get("name"),
                            "278-T" if "Transaction" in str(row.get("type")) else "278e",
                            row.get("docDate"),
                            json.dumps(row, ensure_ascii=False),
                        ),
                    )
                start += length
                total = payload.get("recordsTotal") or 0
                if start >= total:
                    break
                if max_pages and page_count >= max_pages:
                    break
            record_health(conn, "oge", "ok", f"matched={matched}; downloaded={downloaded}; metadata={metadata_rows}")
        except Exception as exc:
            record_health(conn, "oge", "error", repr(exc))
            raise
    return {"matched": matched, "downloaded": downloaded, "metadata_rows": metadata_rows, "pages": page_count}


if __name__ == "__main__":
    print(json.dumps(scan_oge(), indent=2))
