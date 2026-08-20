import sqlite3
from pathlib import Path

from config import DB_PATH, RAW_DIR


SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS source_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_url TEXT NOT NULL,
    local_path TEXT,
    sha256 TEXT,
    fetched_at TEXT NOT NULL,
    published_at TEXT,
    document_type TEXT,
    title TEXT,
    UNIQUE(source, source_url, sha256)
);

CREATE TABLE IF NOT EXISTS filings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_document_id INTEGER NOT NULL,
    person_name TEXT,
    issuer_name TEXT,
    cik TEXT,
    filing_type TEXT NOT NULL,
    filed_at TEXT,
    accession_number TEXT,
    raw_json TEXT,
    UNIQUE(source_document_id, filing_type, accession_number),
    FOREIGN KEY(source_document_id) REFERENCES source_documents(id)
);

CREATE TABLE IF NOT EXISTS parsed_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filing_id INTEGER,
    source_document_id INTEGER NOT NULL,
    person_name TEXT,
    asset_name TEXT,
    ticker TEXT,
    transaction_type TEXT,
    transaction_date TEXT,
    filed_date TEXT,
    amount_range TEXT,
    source_page INTEGER,
    raw_text TEXT,
    confidence REAL NOT NULL DEFAULT 0.5,
    review_state TEXT NOT NULL DEFAULT 'needs_review',
    created_at TEXT NOT NULL,
    UNIQUE(source_document_id, source_page, raw_text),
    FOREIGN KEY(filing_id) REFERENCES filings(id),
    FOREIGN KEY(source_document_id) REFERENCES source_documents(id)
);

CREATE TABLE IF NOT EXISTS parsed_holdings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filing_id INTEGER,
    source_document_id INTEGER NOT NULL,
    person_name TEXT,
    section TEXT,
    account_name TEXT,
    asset_name TEXT,
    ticker TEXT,
    value_range TEXT,
    income_type TEXT,
    income_range TEXT,
    source_page INTEGER,
    raw_text TEXT,
    confidence REAL NOT NULL DEFAULT 0.5,
    review_state TEXT NOT NULL DEFAULT 'needs_review',
    created_at TEXT NOT NULL,
    UNIQUE(source_document_id, source_page, raw_text),
    FOREIGN KEY(filing_id) REFERENCES filings(id),
    FOREIGN KEY(source_document_id) REFERENCES source_documents(id)
);

CREATE TABLE IF NOT EXISTS source_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT
);

CREATE TABLE IF NOT EXISTS ticker_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE,
    ticker TEXT NOT NULL,
    display_name TEXT,
    asset_type TEXT NOT NULL DEFAULT '个股',
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def connect() -> sqlite3.Connection:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def insert_source_document(conn, item):
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO source_documents
            (source, source_url, local_path, sha256, fetched_at, published_at, document_type, title)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item["source"],
            item["source_url"],
            item.get("local_path"),
            item.get("sha256"),
            item["fetched_at"],
            item.get("published_at"),
            item.get("document_type"),
            item.get("title"),
        ),
    )
    if cur.lastrowid:
        return cur.lastrowid
    row = conn.execute(
        "SELECT id FROM source_documents WHERE source = ? AND source_url = ? AND sha256 IS ?",
        (item["source"], item["source_url"], item.get("sha256")),
    ).fetchone()
    return row["id"]


def record_health(conn, source, status, detail=""):
    conn.execute(
        "INSERT INTO source_health (source, checked_at, status, detail) VALUES (?, datetime('now'), ?, ?)",
        (source, status, detail[:2000]),
    )
