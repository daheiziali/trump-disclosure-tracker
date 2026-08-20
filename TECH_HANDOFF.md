# 特朗普交易披露追踪 - 技术交接说明

## 项目定位

本项目是一个本地可运行的披露数据追踪原型，面向中国投资用户展示特朗普公开披露范围内的个股、ETF、基金交易与推算持仓。

产品口径不是实时券商持仓，而是：

- 基于 2025 年度 OGE 278e 年报披露建立基准快照
- 纳入 2026 年迄今 OGE 278-T 交易披露作为增量流水
- 用官方金额区间中点做披露口径估算
- 默认过滤市政债、票据、现金、房地产、私人权益等普通投资用户低关注资产

## 目录结构

```text
frontend/
  index.html                # 产品前端单页
  trump-portrait.jpg        # 首页头像图

backend/
  review_server.py          # 本地 API 与复核后台服务
  analytics.py              # 资产清洗、ticker 映射、主题分类
  position_engine.py        # 推算持仓计算
  db.py                     # SQLite 表结构与连接
  run_pipeline.py           # 数据处理流水线入口
  *_parser.py               # PDF / Excel 解析
  data/disclosures.sqlite3  # 当前本地数据库

start_backend.sh            # 启动本地 API 服务
start_frontend.sh           # 启动静态前端服务
README_DEPLOY.md            # 部署/运行说明
FUTURE_ARCHITECTURE_NOTES.md      # 远期架构设想，当前 MVP 以 PRODUCT_REQUIREMENTS.md 为准
trump-disclosure-product-redesign.md
```

## 本地启动

推荐先启动后端：

```bash
cd /Users/jiajingwen/Documents/Codex/projects/trump-disclosure-tracker
./start_backend.sh
```

后端默认监听：

```text
http://127.0.0.1:8765
```

再启动前端：

```bash
./start_frontend.sh
```

也可以直接打开：

```text
frontend/index.html
```

前端默认 API 地址写在 `frontend/index.html`：

```js
const API_BASE = 'http://127.0.0.1:8765';
```

## 主要接口

```text
GET /api/dashboard
GET /api/inferred-positions?limit=50
GET /api/transactions?limit=300&state=parsed&public=1
GET /api/transactions?limit=5000&state=parsed&public=1&q=AAPL
GET /api/parse-report
GET /api/ticker-candidates
GET /api/ticker-overrides
```

## 当前前端结构

首页保留四个产品分项：

1. 前十大推算持仓
2. 投资主题占比
3. 最新披露交易
4. 资产详情

其中：

- `前十大推算持仓` 的“查看更多”进入完整推算持仓表
- `最新披露交易` 的“查看更多”进入完整交易记录表
- `资产详情` 默认选中推算规模最高资产，并展示交易披露链

## 交付建议

技术同事接手后建议优先做：

1. 将 SQLite 数据库迁移到正式数据库，例如 PostgreSQL
2. 将 `review_server.py` 拆成正式 Web API，例如 FastAPI
3. 将 `frontend/index.html` 拆成 React / Vue / Next.js 项目
4. 将 ticker 标准化、ETF 映射和复核后台做成可维护的数据表
5. 增加定时采集 OGE / SEC 源数据任务
6. 增加行情服务后，再在资产详情中叠加 K 线与交易披露时间点

## 注意事项

- OGE 披露有制度性延迟，不应表述为实时交易信号
- 金额为官方披露区间，不代表精确金额、股数、成本或盈亏
- 推算持仓是披露口径推算，不是实际券商账户持仓
- 当前数据仍依赖部分人工复核和 ticker override
