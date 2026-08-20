import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from analytics import (
    _name_key,
    asset_category,
    classify_concept,
    clear_ticker_override_cache,
    clean_asset_name,
    display_asset_name,
    infer_ticker,
    is_public_investable_asset,
    parse_amount_range,
    public_trade_quality,
)
from db import connect, init_db
from position_engine import inferred_positions, parse_report


_CACHE = {}
_CACHE_TTL_SECONDS = 300


def _cached(key, factory):
    now = time.time()
    cached = _CACHE.get(key)
    if cached and now - cached["time"] < _CACHE_TTL_SECONDS:
        return cached["value"]
    value = factory()
    _CACHE[key] = {"time": now, "value": value}
    return value


def _clear_cache():
    _CACHE.clear()


def _ticker_candidates(conn, limit=100):
    override_keys = {
        row["normalized_name"]
        for row in conn.execute("SELECT normalized_name FROM ticker_overrides")
    }
    rows = []
    for table_name, source_label in (
        ("parsed_transactions", "交易记录"),
        ("parsed_holdings", "持仓记录"),
    ):
        rows.extend(dict(row) | {"source_label": source_label} for row in conn.execute(
            f"""
            SELECT asset_name, ticker, review_state, raw_text
            FROM {table_name}
            WHERE asset_name IS NOT NULL
              AND (ticker IS NULL OR trim(ticker) = '' OR ticker = '—' OR ticker = '-')
            """
        ))
    grouped = {}
    for row in rows:
        raw_name = clean_asset_name(row.get("asset_name"))
        key = _name_key(raw_name)
        if not key:
            continue
        if key in override_keys:
            continue
        category = asset_category(raw_name, row.get("ticker"))
        if category in {"债券/票据", "非公开/现金类"}:
            continue
        item = grouped.setdefault(key, {
            "asset_name": raw_name,
            "normalized_name": key,
            "suggested_ticker": infer_ticker(raw_name) or "",
            "asset_type": category,
            "sources": set(),
            "states": set(),
            "count": 0,
            "sample_raw": row.get("raw_text") or "",
        })
        item["count"] += 1
        item["sources"].add(row["source_label"])
        item["states"].add(row.get("review_state") or "")
        if not item["suggested_ticker"]:
            item["suggested_ticker"] = infer_ticker(raw_name) or ""
    result = []
    for item in grouped.values():
        item["sources"] = " / ".join(sorted(item["sources"]))
        item["states"] = " / ".join(sorted(state for state in item["states"] if state))
        result.append(item)
    result.sort(key=lambda item: (-item["count"], item["asset_name"]))
    return result[:limit]


def _ticker_override_rows(conn):
    return [dict(row) for row in conn.execute(
        """
        SELECT id, asset_name, normalized_name, ticker, display_name, asset_type, note, created_at, updated_at
        FROM ticker_overrides
        ORDER BY updated_at DESC, id DESC
        LIMIT 200
        """
    )]


def _apply_ticker_override(conn, asset_name, ticker, display_name=None):
    key = _name_key(asset_name)
    if not key:
        return
    clean_display = clean_asset_name(display_name or asset_name)
    for table_name in ("parsed_transactions", "parsed_holdings"):
        conn.execute(
            f"""
            UPDATE {table_name}
            SET ticker = ?,
                asset_name = CASE
                    WHEN ? <> '' THEN ?
                    ELSE asset_name
                END
            WHERE asset_name IS NOT NULL
              AND (
                upper(asset_name) = upper(?)
                OR upper(asset_name) LIKE upper(?)
              )
            """,
            (
                ticker,
                clean_display,
                clean_display,
                asset_name,
                f"%{asset_name}%",
            ),
        )


HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Disclosure Review Queue</title>
  <style>
    body { margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f6f7f4; color: #17211b; }
    header { padding: 18px 22px; background: #fff; border-bottom: 1px solid #d9ddd5; display: flex; justify-content: space-between; gap: 16px; align-items: center; }
    h1 { margin: 0; font-size: 20px; }
    main { padding: 18px 22px; display: grid; gap: 14px; }
    .stats { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 12px; }
    .card { background: #fff; border: 1px solid #d9ddd5; border-radius: 8px; box-shadow: 0 10px 24px rgba(23,33,27,.08); }
    .guide { padding: 16px 18px; display: grid; gap: 10px; }
    .guide h2 { margin: 0; font-size: 16px; }
    .guide-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
    .guide-item { border: 1px solid #e1e5de; border-radius: 8px; padding: 12px; background: #fbfcfa; }
    .guide-item strong { display: block; margin-bottom: 5px; font-size: 13px; }
    .guide-item span { color: #657068; font-size: 12px; line-height: 1.45; }
    .metric { padding: 14px; }
    .metric span { color: #657068; font-size: 12px; }
    .metric strong { display: block; margin-top: 8px; font-size: 24px; }
    .queue-tools { padding: 12px 14px; display: flex; justify-content: space-between; align-items: center; gap: 12px; border-bottom: 1px solid #d9ddd5; background: #fbfcfa; }
    .queue-tools p { margin: 0; color: #657068; font-size: 12px; }
    .filters { display: flex; gap: 8px; flex-wrap: wrap; }
    .filters button { background: #fff; color: #17211b; }
    .filters button.active { background: #17211b; color: #fff; border-color: #17211b; }
    table { width: max-content; border-collapse: collapse; background: #fff; min-width: 1760px; }
    th, td { padding: 10px 12px; border-bottom: 1px solid #d9ddd5; text-align: left; vertical-align: top; white-space: nowrap; }
    th { font-size: 11px; color: #657068; text-transform: uppercase; background: #fbfcfa; position: sticky; top: 0; z-index: 2; }
    .table-wrap { overflow: auto; max-height: calc(100vh - 248px); border-radius: 0 0 8px 8px; }
    .table-wrap::-webkit-scrollbar { height: 14px; width: 14px; }
    .table-wrap::-webkit-scrollbar-thumb { background: #b8c2bb; border: 3px solid #eef1ec; border-radius: 999px; }
    .table-wrap::-webkit-scrollbar-track { background: #eef1ec; }
    .col-id { min-width: 72px; }
    .col-person { min-width: 150px; }
    .col-account { min-width: 100px; }
    .col-asset { min-width: 270px; }
    .col-ticker { min-width: 120px; }
    .col-type { min-width: 150px; }
    .col-date { min-width: 128px; }
    .col-amount { min-width: 170px; }
    .col-confidence { min-width: 82px; }
    .col-state { min-width: 132px; }
    .col-raw { min-width: 620px; max-width: 820px; }
    .col-actions { min-width: 150px; position: sticky; right: 0; background: #fff; box-shadow: -8px 0 18px rgba(23,33,27,.06); }
    th.col-actions { background: #fbfcfa; }
    .raw { white-space: normal; color: #334039; line-height: 1.35; }
    input, select { width: 100%; min-width: 0; padding: 7px 8px; border: 1px solid #c9d0c6; border-radius: 6px; background: #fff; }
    select { min-width: 132px; }
    button { border: 1px solid #b9c0b6; background: #17211b; color: white; border-radius: 6px; padding: 8px 10px; cursor: pointer; }
    .secondary { background: #fff; color: #17211b; }
    .danger { background: #fff; color: #a1362b; border-color: #e8bbb5; }
    .row-actions { display: flex; gap: 6px; align-items: center; }
    .detail-row td { background: #fbfcfa; white-space: normal; }
    .review-detail { display: grid; grid-template-columns: minmax(260px, 1fr) minmax(320px, 1.2fr) auto; gap: 14px; align-items: start; }
    .review-detail h3 { margin: 0 0 8px; font-size: 14px; }
    .detail-fields { display: grid; grid-template-columns: repeat(2, minmax(140px, 1fr)); gap: 8px; }
    .detail-fields label { display: grid; gap: 4px; color: #657068; font-size: 12px; }
    .detail-fields span { font-weight: 700; color: #17211b; }
    .detail-raw { color: #334039; font-size: 13px; line-height: 1.45; max-height: 160px; overflow: auto; border: 1px solid #e1e5de; border-radius: 8px; padding: 10px; background: #fff; }
    .detail-actions { display: flex; flex-direction: column; gap: 8px; min-width: 108px; }
    .hidden { display: none !important; }
    .ticker-manager { padding: 16px; display: grid; gap: 16px; }
    .ticker-form { display: grid; grid-template-columns: minmax(260px, 1.2fr) 120px minmax(220px, 1fr) 120px minmax(180px, .8fr) auto; gap: 10px; align-items: end; }
    .ticker-form label { display: grid; gap: 5px; color: #657068; font-size: 12px; }
    .ticker-form label span { font-weight: 700; color: #17211b; }
    .ticker-list { display: grid; gap: 10px; }
    .ticker-list h2 { margin: 0; font-size: 15px; }
    .ticker-table { overflow: auto; border: 1px solid #d9ddd5; border-radius: 8px; max-height: 360px; }
    .ticker-table table { min-width: 1050px; width: 100%; }
    .ticker-table th, .ticker-table td { white-space: nowrap; }
    .tabs { display: flex; gap: 8px; }
    .tabs button.active { background: #1d6f5a; border-color: #1d6f5a; }
    .tag { display: inline-block; border-radius: 999px; padding: 3px 8px; border: 1px solid #d9ddd5; background: #fbfcfa; }
    @media (max-width: 800px) { .stats { grid-template-columns: 1fr; } header { align-items: flex-start; flex-direction: column; } }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>交易披露复核后台</h1>
      <div>OGE 278-T PDF 解析结果，保留原文证据，支持人工确认/修正。</div>
    </div>
    <div class="tabs">
      <button id="txTab" class="active" onclick="setMode('transactions')">交易复核</button>
      <button id="holdingsTab" onclick="setMode('holdings')">持仓复核</button>
      <button id="tickerTab" onclick="setMode('tickers')">代码补充</button>
      <button class="secondary" onclick="loadData()">刷新</button>
    </div>
  </header>
  <main>
    <section class="card guide">
      <h2>复核后台用于决定“这条解析结果是否能进入产品数据”</h2>
      <div class="guide-grid">
        <div class="guide-item"><strong>确认纳入</strong><span>适用于个股、ETF、基金等投资用户关注的公开证券。修正名称、代码、交易动作、日期、金额后点击“确认”。代币、NFT、数字资产一律排除。</span></div>
        <div class="guide-item"><strong>排除</strong><span>适用于市政债、企业债、票据、现金账户、房产/公司权益、解析碎片或明显不相关记录。排除后不会进入前台产品展示。</span></div>
        <div class="guide-item"><strong>回查/修改</strong><span>确认和排除都不是删除数据；记录会进入对应列表，后续仍可重新修改并再次确认或排除。</span></div>
      </div>
    </section>
    <section class="stats" id="stats"></section>
    <section class="card" id="reviewQueue">
      <div class="queue-tools">
        <p id="queueNote">默认展示待复核记录；确认后可在“已确认”列表回查和修改。</p>
        <div class="filters">
          <button id="needsFilter" class="active" onclick="setReviewFilter('needs_review')">待复核</button>
          <button id="approvedFilter" onclick="setReviewFilter('approved')">已确认</button>
          <button id="excludedFilter" onclick="setReviewFilter('excluded')">已排除</button>
          <button id="allFilter" onclick="setReviewFilter('')">全部</button>
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th class="col-id">ID</th><th class="col-person">人物</th><th class="col-account">账户/章节</th><th class="col-asset">资产</th><th class="col-ticker">Ticker</th><th class="col-type">类型</th><th class="col-date">日期/价值</th><th class="col-amount">金额/收入</th><th class="col-confidence">置信度</th><th class="col-state">状态</th><th class="col-raw">原文</th><th class="col-actions">操作</th>
            </tr>
          </thead>
          <tbody id="rows"></tbody>
        </table>
      </div>
    </section>
    <section class="card ticker-manager hidden" id="tickerManager">
      <div>
        <h2>个股/ETF 代码补充</h2>
        <p style="margin:4px 0 0;color:#657068;font-size:12px;">用于补充机器未识别的 ticker。保存后，前台交易记录、推算持仓和资产详情会优先使用人工补充结果。</p>
      </div>
      <form class="ticker-form" onsubmit="saveTickerOverride(event)">
        <label><span>资产原始名称</span><input id="tickerAssetName" required placeholder="例如 CLEAR SECURE INC CLASS A"></label>
        <label><span>Ticker</span><input id="tickerSymbol" required placeholder="YOU"></label>
        <label><span>标准展示名</span><input id="tickerDisplayName" placeholder="Clear Secure Inc Class A"></label>
        <label><span>类型</span><select id="tickerAssetType"><option>个股</option><option>ETF</option><option>基金</option></select></label>
        <label><span>备注</span><input id="tickerNote" placeholder="来源/说明"></label>
        <button type="submit">保存代码</button>
      </form>
      <div class="ticker-list">
        <h2>缺失代码候选</h2>
        <div class="ticker-table"><table>
          <thead><tr><th>资产名称</th><th>建议代码</th><th>类型</th><th>出现次数</th><th>来源</th><th>状态</th><th>操作</th></tr></thead>
          <tbody id="tickerCandidates"></tbody>
        </table></div>
      </div>
      <div class="ticker-list">
        <h2>已补充代码</h2>
        <div class="ticker-table"><table>
          <thead><tr><th>资产名称</th><th>Ticker</th><th>标准展示名</th><th>类型</th><th>备注</th><th>更新时间</th></tr></thead>
          <tbody id="tickerOverrides"></tbody>
        </table></div>
      </div>
    </section>
  </main>
  <script>
    let mode = 'transactions';
    let reviewFilter = 'needs_review';
    function setMode(next) {
      mode = next;
      document.getElementById('txTab').classList.toggle('active', mode === 'transactions');
      document.getElementById('holdingsTab').classList.toggle('active', mode === 'holdings');
      document.getElementById('tickerTab').classList.toggle('active', mode === 'tickers');
      document.getElementById('reviewQueue').classList.toggle('hidden', mode === 'tickers');
      document.getElementById('tickerManager').classList.toggle('hidden', mode !== 'tickers');
      loadData();
    }
    function setReviewFilter(next) {
      reviewFilter = next;
      document.getElementById('needsFilter').classList.toggle('active', reviewFilter === 'needs_review');
      document.getElementById('approvedFilter').classList.toggle('active', reviewFilter === 'approved');
      document.getElementById('excludedFilter').classList.toggle('active', reviewFilter === 'excluded');
      document.getElementById('allFilter').classList.toggle('active', reviewFilter === '');
      loadData();
    }
    async function loadData() {
      if (mode === 'tickers') {
        await loadTickerManager();
        return;
      }
      const stateParam = reviewFilter ? `&state=${encodeURIComponent(reviewFilter)}` : '';
      const [stats, rows] = await Promise.all([
        fetch('/api/stats').then(r => r.json()),
        fetch(`/api/${mode}?limit=200${stateParam}`).then(r => r.json())
      ]);
      document.getElementById('stats').innerHTML = [
        ['源文件', stats.source_documents],
        ['Filings', stats.filings],
        ['交易记录', stats.transactions],
        ['持仓记录', stats.holdings],
        ['待复核', mode === 'transactions' ? stats.needs_review : stats.holdings_needs_review],
        ['已确认', mode === 'transactions' ? stats.approved : stats.holdings_approved],
        ['已排除', mode === 'transactions' ? stats.excluded : stats.holdings_excluded]
      ].map(([k,v]) => `<div class="card metric"><span>${k}</span><strong>${v}</strong></div>`).join('');
      const filterText = reviewFilter === 'approved' ? '已确认' : reviewFilter === 'excluded' ? '已排除' : reviewFilter === 'needs_review' ? '待复核' : '全部';
      document.getElementById('queueNote').textContent = `当前显示：${filterText} · ${rows.length} 条。确认=纳入可用数据；排除=不进入前台产品，但可回查。`;
      document.getElementById('rows').innerHTML = rows.map(row => mode === 'transactions' ? transactionRow(row) : holdingRow(row)).join('');
    }
    function actionButtons(row) {
      if (reviewFilter === 'excluded') {
        return `<button class="secondary" onclick="toggleReviewDetail(${row.id})">修改</button>`;
      }
      return `<button onclick="approve(${row.id})">确认</button><button class="danger" onclick="excludeRow(${row.id})">排除</button>`;
    }
    function transactionRow(row) {
      return `
        <tr data-id="${row.id}">
          <td class="col-id">${row.id}</td>
          <td class="col-person">${escapeHtml(row.person_name || '')}</td>
          <td class="col-account">${escapeHtml(row.source_page ? 'page ' + row.source_page : '')}</td>
          <td class="col-asset"><input data-field="asset_name" value="${escapeAttr(row.asset_name || '')}"></td>
          <td class="col-ticker"><input data-field="ticker" value="${escapeAttr(row.ticker || '')}"></td>
          <td class="col-type">
            <select data-field="transaction_type">
              ${['Purchase','Sale','Exchange',''].map(v => `<option ${row.transaction_type === v ? 'selected' : ''}>${v}</option>`).join('')}
            </select>
          </td>
          <td class="col-date"><input data-field="transaction_date" value="${escapeAttr(row.transaction_date || '')}"></td>
          <td class="col-amount"><input data-field="amount_range" value="${escapeAttr(row.amount_range || '')}"></td>
          <td class="col-confidence">${Number(row.confidence || 0).toFixed(2)}</td>
          <td class="col-state"><span class="tag">${escapeHtml(row.review_state || '')}</span></td>
          <td class="col-raw raw">${escapeHtml(row.raw_text || '')}</td>
          <td class="col-actions"><div class="row-actions">${actionButtons(row)}</div></td>
        </tr>
        ${reviewDetailRow(row)}
      `;
    }
    function holdingRow(row) {
      return `
        <tr data-id="${row.id}">
          <td class="col-id">${row.id}</td>
          <td class="col-person">${escapeHtml(row.person_name || '')}</td>
          <td class="col-account">${escapeHtml(row.account_name || row.section || '')}</td>
          <td class="col-asset"><input data-field="asset_name" value="${escapeAttr(row.asset_name || '')}"></td>
          <td class="col-ticker"><input data-field="ticker" value="${escapeAttr(row.ticker || '')}"></td>
          <td class="col-type"><input data-field="income_type" value="${escapeAttr(row.income_type || '')}"></td>
          <td class="col-date"><input data-field="value_range" value="${escapeAttr(row.value_range || '')}"></td>
          <td class="col-amount"><input data-field="income_range" value="${escapeAttr(row.income_range || '')}"></td>
          <td class="col-confidence">${Number(row.confidence || 0).toFixed(2)}</td>
          <td class="col-state"><span class="tag">${escapeHtml(row.review_state || '')}</span></td>
          <td class="col-raw raw">${escapeHtml(row.raw_text || '')}</td>
          <td class="col-actions"><div class="row-actions">${actionButtons(row)}</div></td>
        </tr>
        ${reviewDetailRow(row)}
      `;
    }
    function reviewDetailRow(row) {
      if (reviewFilter !== 'excluded') return '';
      const typeLabel = mode === 'transactions' ? '动作' : '收入类型';
      const dateLabel = mode === 'transactions' ? '交易日' : '价值区间';
      const amountLabel = mode === 'transactions' ? '金额区间' : '收入区间';
      const typeValue = mode === 'transactions' ? row.transaction_type : row.income_type;
      const dateValue = mode === 'transactions' ? row.transaction_date : row.value_range;
      const amountValue = mode === 'transactions' ? row.amount_range : row.income_range;
      return `
        <tr class="detail-row" id="detail-${row.id}" hidden>
          <td colspan="12">
            <div class="review-detail">
              <div>
                <h3>排除记录详情</h3>
                <div class="detail-fields">
                  <label><span>资产</span>${escapeHtml(row.asset_name || '')}</label>
                  <label><span>Ticker</span>${escapeHtml(row.ticker || '—')}</label>
                  <label><span>${typeLabel}</span>${escapeHtml(typeValue || '—')}</label>
                  <label><span>${dateLabel}</span>${escapeHtml(dateValue || '—')}</label>
                  <label><span>${amountLabel}</span>${escapeHtml(amountValue || '—')}</label>
                  <label><span>置信度</span>${Number(row.confidence || 0).toFixed(2)}</label>
                </div>
              </div>
              <div>
                <h3>原文证据</h3>
                <div class="detail-raw">${escapeHtml(row.raw_text || '')}</div>
              </div>
              <div class="detail-actions">
                <button onclick="approve(${row.id})">确认纳入</button>
                <button class="danger" onclick="excludeRow(${row.id})">继续排除</button>
              </div>
            </div>
          </td>
        </tr>
      `;
    }
    function toggleReviewDetail(id) {
      const detail = document.getElementById(`detail-${id}`);
      if (detail) detail.hidden = !detail.hidden;
    }
    async function loadTickerManager() {
      const [candidates, overrides] = await Promise.all([
        fetch('/api/ticker-candidates?limit=120').then(r => r.json()),
        fetch('/api/ticker-overrides').then(r => r.json())
      ]);
      document.getElementById('stats').innerHTML = [
        ['缺失候选', candidates.length],
        ['已补充', overrides.length]
      ].map(([k,v]) => `<div class="card metric"><span>${k}</span><strong>${v}</strong></div>`).join('');
      document.getElementById('tickerCandidates').innerHTML = candidates.length ? candidates.map(row => `
        <tr>
          <td>${escapeHtml(row.asset_name || '')}</td>
          <td>${escapeHtml(row.suggested_ticker || '—')}</td>
          <td>${escapeHtml(row.asset_type || '')}</td>
          <td>${row.count || 0}</td>
          <td>${escapeHtml(row.sources || '')}</td>
          <td>${escapeHtml(row.states || '')}</td>
          <td><button class="secondary" onclick='fillTickerForm(${JSON.stringify({
            asset_name: row.asset_name || '',
            ticker: row.suggested_ticker || '',
            display_name: row.asset_name || '',
            asset_type: row.asset_type || '个股'
          }).replace(/'/g, '&#39;')})'>补充</button></td>
        </tr>
      `).join('') : '<tr><td colspan="7">暂无缺失代码候选。</td></tr>';
      document.getElementById('tickerOverrides').innerHTML = overrides.length ? overrides.map(row => `
        <tr>
          <td>${escapeHtml(row.asset_name || '')}</td>
          <td>${escapeHtml(row.ticker || '')}</td>
          <td>${escapeHtml(row.display_name || '')}</td>
          <td>${escapeHtml(row.asset_type || '')}</td>
          <td>${escapeHtml(row.note || '')}</td>
          <td>${escapeHtml(row.updated_at || '')}</td>
        </tr>
      `).join('') : '<tr><td colspan="6">暂无人工补充代码。</td></tr>';
    }
    function fillTickerForm(row) {
      document.getElementById('tickerAssetName').value = row.asset_name || '';
      document.getElementById('tickerSymbol').value = row.ticker || '';
      document.getElementById('tickerDisplayName').value = row.display_name || '';
      document.getElementById('tickerAssetType').value = row.asset_type || '个股';
      document.getElementById('tickerNote').focus();
    }
    async function saveTickerOverride(event) {
      event.preventDefault();
      const body = {
        asset_name: document.getElementById('tickerAssetName').value,
        ticker: document.getElementById('tickerSymbol').value,
        display_name: document.getElementById('tickerDisplayName').value,
        asset_type: document.getElementById('tickerAssetType').value,
        note: document.getElementById('tickerNote').value
      };
      await fetch('/api/ticker-overrides', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
      document.getElementById('tickerSymbol').value = '';
      document.getElementById('tickerNote').value = '';
      await loadTickerManager();
    }
    function valuesFor(id, nextState) {
      const tr = document.querySelector(`tr[data-id="${id}"]`);
      const body = { review_state: nextState };
      tr.querySelectorAll('[data-field]').forEach(el => body[el.dataset.field] = el.value);
      return body;
    }
    async function approve(id) {
      await fetch(`/api/${mode}/${id}`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(valuesFor(id, 'approved')) });
      await loadData();
    }
    async function excludeRow(id) {
      await fetch(`/api/${mode}/${id}`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(valuesFor(id, 'excluded')) });
      await loadData();
    }
    function escapeHtml(s) { return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
    function escapeAttr(s) { return escapeHtml(s).replace(/`/g, '&#96;'); }
    loadData();
  </script>
</body>
</html>"""


def _json(handler, payload, status=200):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("content-type", "application/json; charset=utf-8")
    handler.send_header("access-control-allow-origin", "*")
    handler.send_header("access-control-allow-methods", "GET, POST, OPTIONS")
    handler.send_header("access-control-allow-headers", "content-type")
    handler.send_header("content-length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _range_score(value_range):
    if not value_range:
        return 0
    text = str(value_range).replace(",", "")
    numbers = [int(n) for n in re.findall(r"\$?(\d+)", text)]
    if not numbers:
        return 0
    if "over" in text.lower():
        return numbers[0] * 1.25
    if len(numbers) >= 2:
        return (numbers[0] + numbers[1]) / 2
    return numbers[0]


def _date_score(value):
    text = str(value or "").strip()
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if match:
        month, day, year = (int(part) for part in match.groups())
        return year * 10000 + month * 100 + day
    match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if match:
        year, month, day = (int(part) for part in match.groups())
        return year * 10000 + month * 100 + day
    return 0


def _is_cash_like(row):
    name = str(row.get("asset_name") or "").lower()
    ticker = str(row.get("ticker") or "").lower()
    cash_terms = (
        "cash",
        "checking",
        "savings",
        "money market",
        "bank account",
        "brokerage account money market",
    )
    return ticker == "cash" or any(term in name for term in cash_terms)


def _latest_filing_id(conn, person_name="Trump, Donald J"):
    row = conn.execute(
        """
        SELECT id
        FROM filings
        WHERE filing_type = '278e' AND person_name = ?
        ORDER BY filed_at DESC, id DESC
        LIMIT 1
        """,
        (person_name,),
    ).fetchone()
    return row[0] if row else None


def _recent_trade_index(conn):
    rows = [dict(row) for row in conn.execute(
        """
        SELECT person_name, asset_name, ticker, transaction_type, transaction_date,
               amount_range, filed_date, review_state
        FROM parsed_transactions
        WHERE review_state IN ('parsed', 'approved')
        """
    )]
    index = {}
    for row in rows:
        ok, reasons = public_trade_quality(row)
        if not ok:
            continue
        row["asset_name"] = clean_asset_name(row["asset_name"])
        row["ticker"] = infer_ticker(row["asset_name"], row.get("ticker"))
        row["asset_name"] = display_asset_name(row["asset_name"], row.get("ticker"))
        row["asset_category"] = asset_category(row["asset_name"], row.get("ticker"))
        row["amount_midpoint"] = parse_amount_range(row["amount_range"])["mid"]
        key = str(row.get("ticker") or "").upper()
        if not key:
            key = clean_asset_name(row.get("asset_name")).upper()
        if not key:
            continue
        current = index.get(key)
        if not current or _date_score(row.get("transaction_date")) > _date_score(current.get("transaction_date")):
            index[key] = row
    return index


def _attach_recent_trade(rows, trade_index):
    for row in rows:
        key = str(row.get("ticker") or "").upper()
        trade = trade_index.get(key)
        if not trade and not key:
            trade = trade_index.get(clean_asset_name(row.get("asset_name")).upper())
        row["last_trade_type"] = trade.get("transaction_type") if trade else None
        row["last_trade_date"] = trade.get("transaction_date") if trade else None
        row["last_trade_amount_range"] = trade.get("amount_range") if trade else None
        row["last_trade_filed_date"] = trade.get("filed_date") if trade else None
    return rows


def _sort_holding_rows(rows):
    rows.sort(
        key=lambda row: (
            -(row.get("score") or 0),
            int(row.get("source_page") or 0),
            int(row.get("id") or 0),
            clean_asset_name(row.get("asset_name")),
        )
    )
    return rows


def _matches_public_query(row, query_text, fields):
    if not query_text:
        return True
    ticker = str(row.get("ticker") or "").upper()
    if ticker and ticker == query_text:
        return True
    ticker_like = bool(re.fullmatch(r"[A-Z0-9.\-]{1,6}", query_text))
    haystack = " ".join(str(row.get(field) or "") for field in fields).upper()
    if ticker_like:
        return re.search(rf"(?<![A-Z0-9]){re.escape(query_text)}(?![A-Z0-9])", haystack) is not None
    return query_text in haystack


def _dashboard_payload():
    with connect() as conn:
        stats = {
            "source_documents": conn.execute("SELECT count(*) FROM source_documents").fetchone()[0],
            "filings": conn.execute("SELECT count(*) FROM filings").fetchone()[0],
            "transactions": conn.execute("SELECT count(*) FROM parsed_transactions").fetchone()[0],
            "needs_review": conn.execute("SELECT count(*) FROM parsed_transactions WHERE review_state = 'needs_review'").fetchone()[0],
            "holdings": conn.execute("SELECT count(*) FROM parsed_holdings").fetchone()[0],
            "holdings_needs_review": conn.execute("SELECT count(*) FROM parsed_holdings WHERE review_state = 'needs_review'").fetchone()[0],
        }
        latest_filing_id = _latest_filing_id(conn)
        holding_rows = []
        trade_index = _recent_trade_index(conn)
        if latest_filing_id:
            holding_rows = [dict(row) for row in conn.execute(
                """
                SELECT id, person_name, asset_name, ticker, value_range, income_type,
                       income_range, source_page, confidence, review_state
                FROM parsed_holdings
                WHERE filing_id = ?
                  AND value_range IS NOT NULL
                  AND asset_name IS NOT NULL
                """,
                (latest_filing_id,),
            )]
        for row in holding_rows:
            row["asset_name"] = clean_asset_name(row["asset_name"])
            row["ticker"] = infer_ticker(row["asset_name"], row.get("ticker"))
            row["asset_name"] = display_asset_name(row["asset_name"], row.get("ticker"))
            row["asset_category"] = asset_category(row["asset_name"], row.get("ticker"))
            row["score"] = _range_score(row["value_range"])
        holding_rows = [
            row for row in holding_rows
            if row["score"] > 0
            and row.get("review_state") == "parsed"
            and not _is_cash_like(row)
            and is_public_investable_asset(row["asset_name"], row.get("ticker"))
        ]
        _sort_holding_rows(holding_rows)
        _attach_recent_trade(holding_rows, trade_index)
        top_holdings = holding_rows[:10]
        total_top_score = sum(row["score"] for row in top_holdings) or 1
        for idx, row in enumerate(top_holdings, start=1):
            row["rank"] = idx
            row["top10_share"] = round(row["score"] / total_top_score * 100, 2)
        transaction_candidates = [dict(row) for row in conn.execute(
            """
            SELECT id, person_name, asset_name, ticker, transaction_type, transaction_date,
                   amount_range, filed_date, confidence, review_state
            FROM parsed_transactions
            WHERE review_state IN ('parsed', 'approved')
            ORDER BY filed_date DESC, transaction_date DESC, id DESC
            LIMIT 1000
            """
        )]
        recent_transactions = []
        concept_totals = {}
        for row in transaction_candidates:
            ok, reasons = public_trade_quality(row)
            if not ok:
                continue
            row["asset_name"] = clean_asset_name(row["asset_name"])
            row["ticker"] = infer_ticker(row["asset_name"], row.get("ticker"))
            row["asset_name"] = display_asset_name(row["asset_name"], row.get("ticker"))
            row["asset_category"] = asset_category(row["asset_name"], row.get("ticker"))
            row["concept"] = classify_concept(row["asset_name"])
            amount = parse_amount_range(row["amount_range"])
            row["amount_midpoint"] = amount["mid"]
            concept_totals[row["concept"]] = concept_totals.get(row["concept"], 0) + amount["mid"]
            if len(recent_transactions) < 25:
                recent_transactions.append(row)
        public_transaction_count = 0
        for row in conn.execute(
            """
            SELECT asset_name, ticker, transaction_type, transaction_date, amount_range, review_state
            FROM parsed_transactions
            WHERE review_state IN ('parsed', 'approved')
            """
        ):
            ok, _ = public_trade_quality(dict(row))
            if ok:
                public_transaction_count += 1
        source_health = [dict(row) for row in conn.execute(
            """
            SELECT source, status, detail
            FROM source_health
            WHERE id IN (SELECT max(id) FROM source_health GROUP BY source)
            ORDER BY source
            """
        )]
        stats["public_transactions"] = public_transaction_count
        stats["public_holdings"] = len(holding_rows)
        stats["asset_scope"] = "个股、ETF、基金"
    return {
        "stats": stats,
        "top_holdings": top_holdings,
        "recent_transactions": recent_transactions,
        "source_health": source_health,
        "concept_summary": [
            {"concept": concept, "midpoint_volume": volume}
            for concept, volume in sorted(concept_totals.items(), key=lambda item: item[1], reverse=True)
        ][:8],
        "notes": {
            "holding_rank_method": "Sorted by estimated midpoint of the official disclosed value range. Over ranges use 1.25x the lower bound for display ranking only.",
            "precision": "Official OGE disclosures report ranges, not exact positions.",
        },
    }


class ReviewHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        _json(self, {"ok": True})

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            data = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if parsed.path == "/api/stats":
            with connect() as conn:
                payload = {
                    "source_documents": conn.execute("SELECT count(*) FROM source_documents").fetchone()[0],
                    "filings": conn.execute("SELECT count(*) FROM filings").fetchone()[0],
                    "transactions": conn.execute("SELECT count(*) FROM parsed_transactions").fetchone()[0],
                    "needs_review": conn.execute("SELECT count(*) FROM parsed_transactions WHERE review_state = 'needs_review'").fetchone()[0],
                    "approved": conn.execute("SELECT count(*) FROM parsed_transactions WHERE review_state = 'approved'").fetchone()[0],
                    "excluded": conn.execute("SELECT count(*) FROM parsed_transactions WHERE review_state = 'excluded'").fetchone()[0],
                    "holdings": conn.execute("SELECT count(*) FROM parsed_holdings").fetchone()[0],
                    "holdings_needs_review": conn.execute("SELECT count(*) FROM parsed_holdings WHERE review_state = 'needs_review'").fetchone()[0],
                    "holdings_approved": conn.execute("SELECT count(*) FROM parsed_holdings WHERE review_state = 'approved'").fetchone()[0],
                    "holdings_excluded": conn.execute("SELECT count(*) FROM parsed_holdings WHERE review_state = 'excluded'").fetchone()[0],
                }
            _json(self, payload)
            return
        if parsed.path == "/api/ticker-candidates":
            qs = parse_qs(parsed.query)
            limit = min(int(qs.get("limit", ["100"])[0]), 500)
            with connect() as conn:
                _json(self, _ticker_candidates(conn, limit=limit))
            return
        if parsed.path == "/api/ticker-overrides":
            with connect() as conn:
                _json(self, _ticker_override_rows(conn))
            return
        if parsed.path == "/api/dashboard":
            _json(self, _cached(("dashboard",), _dashboard_payload))
            return
        if parsed.path == "/api/transactions":
            qs = parse_qs(parsed.query)
            limit = min(int(qs.get("limit", ["100"])[0]), 5000)
            state = qs.get("state", [None])[0]
            query = qs.get("q", [None])[0]
            public_only = qs.get("public", ["0"])[0] == "1"
            annual_only = qs.get("annual", ["0"])[0] == "1"
            sql = "SELECT * FROM parsed_transactions"
            params = []
            clauses = []
            if state:
                clauses.append("review_state = ?")
                params.append(state)
            if annual_only:
                clauses.append("filing_id IN (SELECT id FROM filings WHERE filing_type = '278e')")
            if query:
                clauses.append("(asset_name LIKE ? OR ticker LIKE ? OR person_name LIKE ?)")
                like = f"%{query}%"
                params.extend([like, like, like])
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            sql += " ORDER BY review_state = 'needs_review' DESC, id DESC LIMIT ?"
            if public_only and query:
                params.append(limit * 20)
            else:
                params.append(30000 if annual_only and public_only else limit * 5 if public_only else limit)
            with connect() as conn:
                rows = [dict(row) for row in conn.execute(sql, params)]
            if public_only:
                clean_rows = []
                query_text = (query or "").strip().upper()
                for row in rows:
                    ok, reasons = public_trade_quality(row)
                    if not ok:
                        continue
                    row["asset_name"] = clean_asset_name(row["asset_name"])
                    row["ticker"] = infer_ticker(row["asset_name"], row.get("ticker"))
                    row["asset_name"] = display_asset_name(row["asset_name"], row.get("ticker"))
                    row["asset_category"] = asset_category(row["asset_name"], row.get("ticker"))
                    row["concept"] = classify_concept(row["asset_name"])
                    row["amount_midpoint"] = parse_amount_range(row["amount_range"])["mid"]
                    if query_text:
                        if not _matches_public_query(row, query_text, ("asset_name", "ticker", "person_name", "concept")):
                            continue
                    clean_rows.append(row)
                    if len(clean_rows) >= limit:
                        break
                rows = clean_rows
            _json(self, rows)
            return
        if parsed.path == "/api/holdings":
            qs = parse_qs(parsed.query)
            limit = min(int(qs.get("limit", ["100"])[0]), 500)
            state = qs.get("state", [None])[0]
            query = qs.get("q", [None])[0]
            latest_only = qs.get("latest", ["0"])[0] == "1"
            public_only = qs.get("public", ["0"])[0] == "1" or latest_only
            sql = "SELECT * FROM parsed_holdings"
            params = []
            clauses = []
            if state:
                clauses.append("review_state = ?")
                params.append(state)
            if query and not public_only:
                clauses.append("(asset_name LIKE ? OR ticker LIKE ? OR person_name LIKE ?)")
                like = f"%{query}%"
                params.extend([like, like, like])
            with connect() as conn:
                trade_index = _recent_trade_index(conn)
                if latest_only:
                    latest_id = _latest_filing_id(conn)
                    if latest_id:
                        clauses.append("filing_id = ?")
                        params.append(latest_id)
                if clauses:
                    sql += " WHERE " + " AND ".join(clauses)
                sql += " ORDER BY review_state = 'needs_review' DESC, id DESC LIMIT ?"
                params.append(10000 if public_only else limit)
                rows = [dict(row) for row in conn.execute(sql, params)]
            if public_only:
                clean_rows = []
                query_text = (query or "").strip().upper()
                for row in rows:
                    row["asset_name"] = clean_asset_name(row.get("asset_name"))
                    row["ticker"] = infer_ticker(row["asset_name"], row.get("ticker"))
                    row["asset_name"] = display_asset_name(row["asset_name"], row.get("ticker"))
                    row["asset_category"] = asset_category(row["asset_name"], row.get("ticker"))
                    row["score"] = _range_score(row.get("value_range"))
                    if row.get("review_state") not in {"parsed", "approved"}:
                        continue
                    if row["score"] <= 0:
                        continue
                    if not is_public_investable_asset(row["asset_name"], row.get("ticker")):
                        continue
                    if query_text:
                        if not _matches_public_query(row, query_text, ("asset_name", "person_name", "asset_category")):
                            continue
                    clean_rows.append(row)
                _sort_holding_rows(clean_rows)
                rows = _attach_recent_trade(clean_rows, trade_index)[:limit]
            _json(self, rows)
            return
        if parsed.path == "/api/top-holdings":
            qs = parse_qs(parsed.query)
            limit = min(int(qs.get("limit", ["10"])[0]), 50)
            payload = _cached(("dashboard",), _dashboard_payload)["top_holdings"][:limit]
            _json(self, payload)
            return
        if parsed.path == "/api/inferred-positions":
            qs = parse_qs(parsed.query)
            limit = min(int(qs.get("limit", ["200"])[0]), 5000)
            _json(self, _cached(("inferred_positions", limit), lambda: inferred_positions(limit=limit)))
            return
        if parsed.path == "/api/parse-report":
            qs = parse_qs(parsed.query)
            local_dir = qs.get("local_dir", ["/Users/jiajingwen/Desktop/trump 披露"])[0]
            _json(self, parse_report(local_dir))
            return
        _json(self, {"error": "not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path.rstrip("/") == "/api/ticker-overrides":
            length = int(self.headers.get("content-length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            asset_name = clean_asset_name(payload.get("asset_name"))
            ticker = str(payload.get("ticker") or "").strip().upper()
            display_name = clean_asset_name(payload.get("display_name") or asset_name)
            asset_type = str(payload.get("asset_type") or "个股").strip() or "个股"
            note = str(payload.get("note") or "").strip()
            normalized_name = _name_key(asset_name)
            if not asset_name or not ticker or not normalized_name:
                _json(self, {"error": "asset_name and ticker are required"}, 400)
                return
            with connect() as conn:
                conn.execute(
                    """
                    INSERT INTO ticker_overrides
                        (asset_name, normalized_name, ticker, display_name, asset_type, note, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(normalized_name) DO UPDATE SET
                        asset_name = excluded.asset_name,
                        ticker = excluded.ticker,
                        display_name = excluded.display_name,
                        asset_type = excluded.asset_type,
                        note = excluded.note,
                        updated_at = datetime('now')
                    """,
                    (asset_name, normalized_name, ticker, display_name, asset_type, note),
                )
                _apply_ticker_override(conn, asset_name, ticker, display_name)
            _clear_cache()
            clear_ticker_override_cache()
            _json(self, {"ok": True, "asset_name": asset_name, "ticker": ticker})
            return
        match = parsed.path.rstrip("/").split("/")
        if len(match) == 4 and match[:3] == ["", "api", "transactions"]:
            tx_id = int(match[3])
            length = int(self.headers.get("content-length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            fields = ["asset_name", "ticker", "transaction_type", "transaction_date", "amount_range", "review_state"]
            values = [payload.get(field) for field in fields]
            with connect() as conn:
                conn.execute(
                    """
                    UPDATE parsed_transactions
                    SET asset_name = ?, ticker = ?, transaction_type = ?, transaction_date = ?,
                        amount_range = ?, review_state = ?
                    WHERE id = ?
                    """,
                    values + [tx_id],
                )
            _clear_cache()
            _json(self, {"ok": True, "id": tx_id})
            return
        if len(match) == 4 and match[:3] == ["", "api", "holdings"]:
            holding_id = int(match[3])
            length = int(self.headers.get("content-length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            fields = ["asset_name", "ticker", "income_type", "value_range", "income_range", "review_state"]
            values = [payload.get(field) for field in fields]
            with connect() as conn:
                conn.execute(
                    """
                    UPDATE parsed_holdings
                    SET asset_name = ?, ticker = ?, income_type = ?, value_range = ?,
                        income_range = ?, review_state = ?
                    WHERE id = ?
                    """,
                    values + [holding_id],
                )
            _clear_cache()
            _json(self, {"ok": True, "id": holding_id})
            return
        _json(self, {"error": "not found"}, 404)

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))


def run(host="127.0.0.1", port=8765):
    init_db()
    server = ThreadingHTTPServer((host, port), ReviewHandler)
    print(f"Review server listening on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
