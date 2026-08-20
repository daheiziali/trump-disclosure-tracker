# Cabinet Disclosure MVP

本地 MVP 覆盖三条主链：

1. SEC EDGAR 自动采集：`sec_edgar.py`
2. OGE 278-T / 278e 监控与 PDF 下载：`oge_monitor.py`
3. OGE 278-T PDF 解析与人工复核后台：`pdf_parser.py` + `review_server.py`
4. OGE 278e 年度 PDF 解析：`annual_parser.py`
5. OGE 278e 年度 Excel 表格解析：`annual_excel_parser.py`
6. OGE 278-T Excel 表格解析：`transaction_excel_parser.py`

## 运行环境

使用 Codex 内置 Python：

```bash
/Users/jiajingwen/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
```

依赖：

- Python 标准库
- pypdf
- pdfplumber 已可用，但当前解析器先用 pypdf

## 初始化和采集

```bash
cd /Users/jiajingwen/Documents/Codex/2026-07-09/t/work/disclosure_mvp
/Users/jiajingwen/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 sec_edgar.py
/Users/jiajingwen/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 oge_monitor.py
/Users/jiajingwen/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 pdf_parser.py
/Users/jiajingwen/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 annual_parser.py
```

如果已有年度 278e 的 Excel 表格版，优先使用 Excel 作为结构化主数据源：

```bash
cd /Users/jiajingwen/Documents/Codex/2026-07-09/t/work/disclosure_mvp
/Users/jiajingwen/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 annual_excel_parser.py /Users/jiajingwen/Downloads/Donald-J-Trump-2026-278ANNUAL.xlsx --dry-run
/Users/jiajingwen/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 annual_excel_parser.py /Users/jiajingwen/Downloads/Donald-J-Trump-2026-278ANNUAL.xlsx
```

如果已有 278-T 的 Excel 表格版，可批量替换对应 PDF OCR 抽取结果：

```bash
cd /Users/jiajingwen/Documents/Codex/2026-07-09/t/work/disclosure_mvp
/Users/jiajingwen/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 transaction_excel_parser.py --dry-run
/Users/jiajingwen/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 transaction_excel_parser.py
```

或一次性运行：

```bash
/Users/jiajingwen/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 run_pipeline.py
```

如需在一键流程中使用 Excel 年报覆盖 PDF 抽取结果：

```bash
ANNUAL_EXCEL_PATH=/Users/jiajingwen/Downloads/Donald-J-Trump-2026-278ANNUAL.xlsx /Users/jiajingwen/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 run_pipeline.py
```

如需在一键流程中批量使用 278-T Excel 覆盖 PDF OCR 抽取结果：

```bash
TRANSACTION_EXCEL_DIR="/Users/jiajingwen/Desktop/trump 披露/excel" /Users/jiajingwen/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 run_pipeline.py
```

## 启动复核后台

```bash
cd /Users/jiajingwen/Documents/Codex/2026-07-09/t/work/disclosure_mvp
/Users/jiajingwen/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 review_server.py
```

然后打开：

```text
http://127.0.0.1:8765
```

页面提供两个视图：

- 交易复核：来自 OGE 278-T。
- 持仓复核：来自 OGE 278e 年度披露 Part 6。

## 数据文件

- SQLite: `data/disclosures.sqlite3`
- SEC 原始 JSON: `data/raw/sec/`
- OGE 原始 PDF/metadata: `data/raw/oge/`

## 当前限制

- OGE 278-T 扫描件 OCR 质量不稳定，解析器会把低置信度记录放入复核队列。
- 如果有 278-T Excel 转换结果，优先用 `transaction_excel_parser.py` 替换对应 PDF OCR 行；解析结果在 `raw_text` 中保留 Excel 文件名、sheet、行号。
- Annual 278e PDF 解析可作为兜底；如果有 Excel 表格版，优先用 `annual_excel_parser.py` 解析 Part 6 和 Part 7，并保留来源 sheet/行号在 `raw_text` 中。
- 投资用户主视图应过滤为个股、ETF、基金；市政债、票据、现金、房地产和私营企业资产保留在后台数据中，不进入主列表。
- SEC 当前默认监控 TMTG/DJT 的 CIK，可在 `config.py` 的 `SEC_COMPANIES` 扩展。
- OGE 目标人物可在 `config.py` 的 `OGE_TARGETS` 扩展。
