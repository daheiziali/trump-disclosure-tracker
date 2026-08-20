import json
import os
from pathlib import Path

from annual_excel_parser import ingest_annual_excel
from oge_monitor import scan_oge
from annual_parser import ingest_annual_holdings
from pdf_parser import ingest_oge_transactions
from sec_edgar import ingest_sec_submissions
from transaction_excel_parser import ingest_transaction_excels


def main():
    annual_excel_path = os.environ.get("ANNUAL_EXCEL_PATH")
    transaction_excel_dir = os.environ.get("TRANSACTION_EXCEL_DIR")
    result = {
        "sec_edgar": ingest_sec_submissions(),
        "oge": scan_oge(),
        "pdf_parser": ingest_oge_transactions(),
        "annual_parser": ingest_annual_holdings(),
    }
    if annual_excel_path:
        result["annual_excel_parser"] = ingest_annual_excel(Path(annual_excel_path))
    if transaction_excel_dir:
        paths = sorted(Path(transaction_excel_dir).glob("*.xlsx"))
        result["transaction_excel_parser"] = ingest_transaction_excels(paths)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
