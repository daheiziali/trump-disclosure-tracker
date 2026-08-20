# 远期架构设想 - 政要交易披露数据库

> 本文档仅作为远期产品与后端架构参考，不代表当前 MVP 的必须实现范围。
> 当前交付与开发优先级以 `PRODUCT_REQUIREMENTS.md` 为准。
>
> 当前 MVP 聚焦：特朗普本人、OGE 官网披露检索页、个股/ETF/基金交易披露与推算持仓。
> 本文中的 SEC、House、Senate、政策事件、合同数据、告警系统等内容属于后续扩展方向。

## 产品定位

建议定位为“政要财务披露与利益冲突情报数据库”，而不是“政要跟单炒股工具”。核心价值是：

- 聚合 OGE、SEC、House、Senate 等官方披露。
- 显示交易日、提交日、公开日和延迟天数。
- 保留原始文件、页码、哈希和解析版本，建立可审计证据链。
- 对政策、合同、监管事件与持仓暴露做交叉分析。

## 第一版用户工作流

1. 首页看到最新披露、迟报、大额交易、数据源健康。
2. 进入人物页查看持仓、交易、信托/配偶/实体关联。
3. 进入资产页查看哪些政要披露了同一证券、ETF、基金或公司。
4. 对人物、资产、金额区间、迟报、政策关键词创建告警。
5. 点击任意交易可回到官方原件、页码、原文片段和解析记录。

## 数据源

### 必接官方源

- OGE: 总统、副总统、内阁、PAS 官员的 278e、278-T、伦理协议。
- SEC EDGAR: Form 3/4/5、13D/13G、8-K、10-K，用于上市公司权益和内部人交易。
- House Clerk: 众议员年度财务披露和 Periodic Transaction Reports。
- Senate eFD: 参议员和高级 staff 的年度披露与 PTR。
- White House / agency ethics pages: 个别官员披露、伦理协议和 waiver 可能散落在机构页面。

### 冲突分析补充源

- Federal Register: 行政命令、规则制定、公开评论期。
- USAspending.gov: 联邦合同授予。
- SAM.gov: 政府采购机会。
- FEC: 政治捐款。
- Lobbying Disclosure Act database: 游说登记。
- Company filings: 10-K、8-K、proxy statement。

## 更新频率

- SEC EDGAR: 5-15 分钟轮询。
- House/Senate PTR: 1-6 小时轮询。
- OGE/White House/agency: 每日轮询，页面结构变更时触发人工检查。
- 年度报告: 每日检查即可。

注意：产品能做到“发现公开文件后快速更新”，不能消除披露制度本身的延迟。界面必须始终展示：

- transaction_date
- filed_date
- published_at
- filing_lag_days
- source_refresh_at

## 后端模块

### 1. Source Registry

维护每个数据源的配置：

- source_id
- source_type: oge, sec, house, senate, agency
- base_url
- fetch_strategy: api, sitemap, html_scrape, pdf_index, rss
- refresh_interval
- parser_id
- health_check_rule
- legal_notes

### 2. Fetcher

职责：

- 定时拉取官方页面、API、PDF、XML、HTML。
- 遵守 robots、速率限制和 User-Agent。
- 保存原始文件到对象存储。
- 计算 sha256。
- 如果同一 URL 文件 hash 变化，生成新版本。

### 3. Parser

按来源拆解析器：

- sec_edgar_parser: XML/HTML 结构化优先。
- oge_278e_parser: PDF 表格、OCR、附表和 Exhibit 解析。
- oge_278t_parser: 交易报告解析。
- house_ptr_parser / senate_ptr_parser: PTR 解析。

每条记录输出：

- raw_text
- source_page
- field_confidence
- parser_version
- needs_review

### 4. Entity Resolution

重点难点：

- 人物同名合并。
- 本人、配偶、信托、LLC、子公司、基金底层资产分开建模。
- 证券 ticker、CIK、CUSIP、ISIN、基金名称映射。
- 非上市资产和授权协议不要强行映射成股票。

建议规则：

- 证券优先用 CIK/CUSIP/ISIN。
- 人物使用内部 canonical_person_id。
- 信托和 LLC 使用 ownership_node，支持图谱关系。
- 金额只保存原始区间，不生成伪精确估值。

### 5. Review Queue

进入人工复核的条件：

- PDF/OCR 置信度低。
- 金额区间无法解析。
- 同一交易疑似重复。
- 人物或资产实体匹配冲突。
- 大额交易、迟报、敏感政策关联。

### 6. Alert Engine

可支持：

- 新披露。
- 大额买入/卖出。
- 迟报。
- 特定人物。
- 特定 ticker / issuer / sector。
- 交易与政策事件时间接近。
- 官方文件被修改或撤换。

### 7. Audit Layer

每条标准化记录必须能回溯：

- source_url
- source_document_id
- document_hash
- source_page
- original_excerpt
- parser_version
- normalized_record_version
- reviewer_id
- reviewed_at

## 核心数据表

```sql
persons(id, full_name, role, agency, term_start, term_end, status)
ownership_nodes(id, person_id, node_type, name, relationship, ownership_pct)
source_documents(id, source_id, url, file_type, sha256, fetched_at, published_at, version)
filings(id, person_id, filing_type, reporting_year, filed_date, source_document_id, amendment_of)
assets(id, canonical_name, asset_type, ticker, cik, cusip, isin, sector)
holdings(id, filing_id, owner_node_id, asset_id, value_range, income_type, income_range, source_page, confidence)
transactions(id, filing_id, owner_node_id, asset_id, transaction_type, transaction_date, amount_range, filed_date, published_at, lag_days, source_page, confidence)
review_tasks(id, record_type, record_id, reason, status, assigned_to, resolved_at)
source_health(id, source_id, checked_at, status, latency_ms, last_success_at, error_summary)
alerts(id, user_id, rule_json, channel, active)
```

## 数据真实性保证

可以承诺：

- 每条数据都来自官方文件或官方 API。
- 原始文件可回溯、可下载、可哈希校验。
- 解析过程可复现。
- 人工复核记录可审计。

不能承诺：

- 申报人一定没有漏报或误报。
- 交易实时。
- 披露金额为精确值。
- 披露交易一定由本人亲自下单。

## 合规提醒

上线付费产品前需要美国律师确认：

- Ethics in Government Act 对 public financial disclosure report 的商业用途限制。
- 是否落入投资顾问、投资建议或交易信号监管范围。
- 披露数据、原文片段、PDF 缓存和再分发的边界。
- 免责声明和用户协议。

推荐第一版面向媒体、研究机构、合规/风控、公共政策研究者，避免 C 端“跟单”叙事。
