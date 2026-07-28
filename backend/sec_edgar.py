import json
from datetime import datetime, timezone

from config import RAW_DIR, SEC_COMPANIES
from db import connect, init_db, insert_source_document, record_health
from net import fetch_bytes, save_bytes


SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_company_submissions(label: str, cik: str) -> dict:
    url = SEC_SUBMISSIONS_URL.format(cik=cik.zfill(10))
    data = fetch_bytes(url)
    sha = save_bytes(RAW_DIR / "sec" / f"{label}_{cik}.json", data)
    payload = json.loads(data.decode("utf-8"))
    return {"url": url, "sha": sha, "payload": payload}


def ingest_sec_submissions() -> dict:
    init_db()
    inserted = 0
    seen = 0
    with connect() as conn:
        for label, cik in SEC_COMPANIES.items():
            try:
                result = fetch_company_submissions(label, cik)
                doc_id = insert_source_document(
                    conn,
                    {
                        "source": "sec_edgar",
                        "source_url": result["url"],
                        "local_path": str(RAW_DIR / "sec" / f"{label}_{cik}.json"),
                        "sha256": result["sha"],
                        "fetched_at": _utc_now(),
                        "document_type": "sec_submissions_json",
                        "title": f"SEC submissions for {label}",
                    },
                )
                recent = result["payload"].get("filings", {}).get("recent", {})
                forms = recent.get("form", [])
                filing_dates = recent.get("filingDate", [])
                accession_numbers = recent.get("accessionNumber", [])
                primary_docs = recent.get("primaryDocument", [])
                issuer = result["payload"].get("name")
                for idx, form in enumerate(forms):
                    if form not in {"3", "4", "5", "SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A", "8-K", "10-K"}:
                        continue
                    seen += 1
                    accession = accession_numbers[idx] if idx < len(accession_numbers) else None
                    raw = {
                        "form": form,
                        "filingDate": filing_dates[idx] if idx < len(filing_dates) else None,
                        "accessionNumber": accession,
                        "primaryDocument": primary_docs[idx] if idx < len(primary_docs) else None,
                    }
                    cur = conn.execute(
                        """
                        INSERT OR IGNORE INTO filings
                            (source_document_id, issuer_name, cik, filing_type, filed_at, accession_number, raw_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            doc_id,
                            issuer,
                            cik.zfill(10),
                            form,
                            raw["filingDate"],
                            accession,
                            json.dumps(raw, ensure_ascii=False),
                        ),
                    )
                    inserted += cur.rowcount
                record_health(conn, "sec_edgar", "ok", f"{label}: {seen} relevant filings seen")
            except Exception as exc:
                record_health(conn, "sec_edgar", "error", repr(exc))
                raise
    return {"seen": seen, "inserted": inserted}


if __name__ == "__main__":
    print(json.dumps(ingest_sec_submissions(), indent=2))

