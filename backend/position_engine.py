from __future__ import annotations

from pathlib import Path

from analytics import (
    asset_category,
    classify_concept,
    clean_asset_name,
    display_asset_name,
    infer_ticker,
    is_public_investable_asset,
    parse_amount_range,
    public_trade_quality,
)
from db import connect


def asset_key(asset_name: str | None, ticker: str | None = None) -> str:
    ticker_value = str(ticker or "").strip().upper() or infer_ticker(asset_name, ticker)
    if ticker_value:
        return f"TICKER:{ticker_value.upper()}"
    return f"NAME:{clean_asset_name(asset_name).upper()}"


def _date_score(value: str | None) -> int:
    text = str(value or "")
    parts = text.split("/")
    if len(parts) == 3:
        month, day, year = parts
        if len(year) == 2:
            year = "20" + year
        try:
            return int(year) * 10000 + int(month) * 100 + int(day)
        except ValueError:
            return 0
    return 0


def latest_trump_annual_filing_id(conn) -> int | None:
    row = conn.execute(
        """
        SELECT id
        FROM filings
        WHERE person_name = 'Trump, Donald J' AND filing_type = '278e'
        ORDER BY filed_at DESC, id DESC
        LIMIT 1
        """
    ).fetchone()
    return row["id"] if row else None


def baseline_positions(conn) -> list[dict]:
    filing_id = latest_trump_annual_filing_id(conn)
    if not filing_id:
        return []
    rows = [dict(row) for row in conn.execute(
        """
        SELECT id, person_name, asset_name, ticker, value_range, income_type, income_range,
               source_page, confidence, review_state
        FROM parsed_holdings
        WHERE filing_id = ?
          AND review_state IN ('parsed', 'approved')
        """,
        (filing_id,),
    )]
    clean_rows = []
    for row in rows:
        row["asset_name"] = clean_asset_name(row.get("asset_name"))
        row["ticker"] = infer_ticker(row["asset_name"], row.get("ticker"))
        row["asset_name"] = display_asset_name(row["asset_name"], row.get("ticker"))
        row["asset_category"] = asset_category(row["asset_name"], row.get("ticker"))
        if not is_public_investable_asset(row["asset_name"], row.get("ticker")):
            continue
        amount = parse_amount_range(row.get("value_range"))
        if not amount["valid"]:
            continue
        row["value_midpoint"] = amount["mid"]
        row["value_low"] = amount["low"]
        row["value_high"] = amount["high"]
        row["asset_key"] = asset_key(row["asset_name"], row.get("ticker"))
        clean_rows.append(row)
    return clean_rows


def trade_events(conn, annual_only: bool = False) -> list[dict]:
    clauses = [
        "pt.person_name = 'Trump, Donald J'",
        "pt.review_state IN ('parsed', 'approved')",
    ]
    if annual_only:
        clauses.append("f.filing_type = '278e'")
    sql = f"""
        SELECT pt.*, f.filing_type
        FROM parsed_transactions pt
        JOIN filings f ON f.id = pt.filing_id
        WHERE {' AND '.join(clauses)}
    """
    rows = [dict(row) for row in conn.execute(sql)]
    clean_rows = []
    for row in rows:
        ok, reasons = public_trade_quality(row)
        if not ok:
            continue
        row["asset_name"] = clean_asset_name(row.get("asset_name"))
        row["ticker"] = infer_ticker(row["asset_name"], row.get("ticker"))
        row["asset_name"] = display_asset_name(row["asset_name"], row.get("ticker"))
        row["asset_category"] = asset_category(row["asset_name"], row.get("ticker"))
        row["concept"] = classify_concept(row["asset_name"])
        row["asset_key"] = asset_key(row["asset_name"], row.get("ticker"))
        amount = parse_amount_range(row.get("amount_range"))
        row["amount_midpoint"] = amount["mid"]
        row["date_score"] = _date_score(row.get("transaction_date"))
        clean_rows.append(row)
    clean_rows.sort(key=lambda row: (row["date_score"], row.get("id") or 0), reverse=True)
    return clean_rows


def inferred_positions(limit: int = 500) -> list[dict]:
    with connect() as conn:
        baselines = baseline_positions(conn)
        trades = trade_events(conn, annual_only=False)
    grouped: dict[str, dict] = {}
    for base in baselines:
        key = base["asset_key"]
        item = grouped.setdefault(key, {
            "asset_key": key,
            "asset_name": base["asset_name"],
            "ticker": base.get("ticker"),
            "asset_category": base.get("asset_category"),
            "concept": classify_concept(base["asset_name"]),
            "baseline_count": 0,
            "baseline_midpoint": 0,
            "baseline_low": 0,
            "baseline_high": 0,
            "purchase_midpoint": 0,
            "sale_midpoint": 0,
            "transaction_count": 0,
            "last_trade_type": None,
            "last_trade_date": None,
            "last_trade_amount_range": None,
        })
        item["baseline_count"] += 1
        item["baseline_midpoint"] += base["value_midpoint"]
        item["baseline_low"] += base["value_low"]
        item["baseline_high"] += base["value_high"]
    for trade in trades:
        key = trade["asset_key"]
        item = grouped.setdefault(key, {
            "asset_key": key,
            "asset_name": trade["asset_name"],
            "ticker": trade.get("ticker"),
            "asset_category": trade.get("asset_category"),
            "concept": trade.get("concept"),
            "baseline_count": 0,
            "baseline_midpoint": 0,
            "baseline_low": 0,
            "baseline_high": 0,
            "purchase_midpoint": 0,
            "sale_midpoint": 0,
            "transaction_count": 0,
            "last_trade_type": None,
            "last_trade_date": None,
            "last_trade_amount_range": None,
            "last_date_score": 0,
        })
        tx_type = str(trade.get("transaction_type") or "").lower()
        if "sale" in tx_type:
            item["sale_midpoint"] += trade["amount_midpoint"]
        elif "purchase" in tx_type:
            item["purchase_midpoint"] += trade["amount_midpoint"]
        item["transaction_count"] += 1
        if trade["date_score"] >= item.get("last_date_score", 0):
            item["last_date_score"] = trade["date_score"]
            item["last_trade_type"] = trade.get("transaction_type")
            item["last_trade_date"] = trade.get("transaction_date")
            item["last_trade_amount_range"] = trade.get("amount_range")
    result = []
    for item in grouped.values():
        baseline = item["baseline_midpoint"]
        purchases = item["purchase_midpoint"]
        sales = item["sale_midpoint"]
        if baseline and not sales and not purchases:
            status = "确认持有"
            confidence = "高"
        elif baseline and purchases > sales:
            status = "增持或仍持有"
            confidence = "中高"
        elif baseline and sales and sales >= max(item["baseline_low"], 1) and purchases == 0:
            status = "疑似清仓或大幅减持"
            confidence = "低"
        elif baseline and sales:
            status = "减持或清仓不确定"
            confidence = "中"
        elif purchases and sales:
            status = "有买有卖，状态不明"
            confidence = "低"
        elif purchases:
            status = "可能持有"
            confidence = "中"
        elif sales:
            status = "后续交易确认卖出"
            confidence = "低"
        else:
            status = "状态不明"
            confidence = "低"
        item["inferred_status"] = status
        item["confidence_label"] = confidence
        item["net_midpoint"] = baseline + purchases - sales
        result.append(item)
    result.sort(
        key=lambda row: (
            row["baseline_midpoint"] + row["purchase_midpoint"] + row["sale_midpoint"],
            row["transaction_count"],
        ),
        reverse=True,
    )
    return result[:limit]


def parse_report(local_dir: str | Path | None = None) -> dict:
    with connect() as conn:
        rows = [dict(row) for row in conn.execute(
            """
            SELECT sd.id, sd.sha256, sd.local_path, sd.title, sd.published_at,
                   f.person_name, f.filing_type,
                   (SELECT COUNT(*) FROM parsed_transactions pt WHERE pt.source_document_id = sd.id) AS transaction_rows,
                   (SELECT COUNT(*) FROM parsed_holdings ph WHERE ph.source_document_id = sd.id) AS holding_rows
            FROM source_documents sd
            JOIN filings f ON f.source_document_id = sd.id
            WHERE f.person_name = 'Trump, Donald J'
            ORDER BY f.filed_at DESC, sd.id DESC
            """
        )]
    local_hashes = {}
    if local_dir:
        base = Path(local_dir)
        for path in sorted(base.glob("*.pdf")):
            import hashlib

            h = hashlib.sha256()
            with path.open("rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
            local_hashes[h.hexdigest()] = str(path)
    for row in rows:
        row["local_match"] = local_hashes.get(row["sha256"])
        row["parse_status"] = "ok"
        if row["filing_type"] == "278-T" and row["transaction_rows"] == 0:
            row["parse_status"] = "needs_parser_review"
        if row["filing_type"] == "278e" and row["holding_rows"] == 0 and row["transaction_rows"] == 0:
            row["parse_status"] = "needs_parser_review"
    return {
        "documents": rows,
        "local_unmatched": [
            {"sha256": sha, "path": path}
            for sha, path in local_hashes.items()
            if sha not in {row["sha256"] for row in rows}
        ],
    }
