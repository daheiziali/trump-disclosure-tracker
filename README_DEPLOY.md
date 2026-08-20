# 特朗普交易披露追踪 - 本地部署交付包

本交付包包含当前 MVP 的前端页面、Python 后端、SQLite 数据库和复核后台。

## 目录结构

```text
frontend/
  index.html
  trump-portrait.jpg

backend/
  review_server.py
  analytics.py
  position_engine.py
  db.py
  data/
    disclosures.sqlite3
    hsbc_us_stock_codes.csv
    hsbc_us_stock_codes.json

requirements.txt
start_backend.sh
start_frontend.sh
```

## 运行方式

建议使用 Python 3.11+。

```bash
cd trump-disclosure-tracker-20260728
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

启动后端：

```bash
./start_backend.sh
```

后端地址：

```text
http://127.0.0.1:8765
```

另开一个终端启动前端：

```bash
./start_frontend.sh
```

前端地址：

```text
http://127.0.0.1:8080
```

也可以直接用浏览器打开：

```text
frontend/index.html
```

## 重要页面

- 产品前台：`http://127.0.0.1:8080`
- 复核后台：`http://127.0.0.1:8765`

## 当前数据口径

- 数据来自本地 SQLite：`backend/data/disclosures.sqlite3`
- 前台仅展示投资用户关注的个股、ETF、基金。
- 市政债、企业债、票据、现金、房产/私营企业权益等可在后台保留，但不进入产品主展示。
- 金额为 OGE 披露区间的中点估算，不代表真实账户金额、持股数或实时市值。
- 人工补充的 ticker 保存在 `ticker_overrides` 表中，会优先覆盖自动识别结果。

## 复核后台工作流

- `待复核`：机器解析后需要人工判断的记录。
- `已确认`：人工确认纳入产品数据池的记录。
- `已排除`：人工确认不进入产品前台的记录。
- `代码补充`：补充缺失个股/ETF/fund ticker，不需要修改源码。

## 后续接入服务器建议

生产化时建议：

- 用 Nginx 托管 `frontend/` 静态页面。
- 用 systemd/supervisor/pm2 托管 `backend/review_server.py`。
- 将 `frontend/index.html` 中的 `API_BASE` 从 `http://127.0.0.1:8765` 改为服务器后端地址。
- 将 SQLite 迁移到 PostgreSQL 或 MySQL 后，再做多用户权限和审计日志。

## GitLab 推送

如果需要推送到 GitLab：

```bash
cd trump-disclosure-tracker-20260728
git init
git add .
git commit -m "Initial Trump disclosure tracker delivery"
git branch -M main
git remote add origin <你的 GitLab 仓库地址>
git push -u origin main
```

如果需要我直接创建/推送 GitLab 仓库，请提供 GitLab 仓库地址和有权限的访问方式。不要把 token 写进代码，可通过环境变量提供。
