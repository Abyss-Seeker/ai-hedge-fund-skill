# 数据源映射：financial-datasets → WorkBuddy 金融 skill

> 原始 ai-hedge-fund 项目用 `https://api.financialdatasets.ai/` 拉所有数据，
> 在 WorkBuddy 里我们用 **westock-data（主）+ neodata-financial-search（兜底）+ westock-tool（批量筛选时）** 替代。
> 缺失的 `insider_trades` 走 shareholder 字段做降级处理。

---

## 一、端点对照总表

| 原始端点 | financial-datasets 用途 | WorkBuddy 替代方案 | 覆盖率 | 备注 |
|---|---|---|---|---|
| `GET /prices/` | 日 K 线（open/close/high/low/volume） | `westock-data kline {code} --period day --start X --end Y` | ✅ 100% | 同时支持 A 股 / 港股 / 美股 |
| `GET /financial-metrics/` | TTM / 年度估值与盈利指标 | `westock-data finance {code} --num 8` | ✅ 95% | 字段名略不同，详见下表 |
| `POST /financials/search/line-items` | 指定行项目查询（EPS / Revenue / Net Income / 资产负债表等） | `westock-data finance {code}`（同一接口）| ✅ 90% | westock-data 把 metrics + line-items 合并到了 `finance` 命令 |
| `GET /insider-trades/` | 内部人交易明细 | `westock-data shareholder {code}`（仅 A股/港股）| ⚠️ 降级 | 拿到董监高增减持事件当代理；如缺失则 agent 跳过 |
| `GET /news/` | 公司新闻 + 情绪 | `westock-data news article {code} --limit 20` | ✅ 100% | 自带新闻情绪 |
| `GET /company/facts/` | 公司基础事实（行业 / 上市日 / 员工 / market cap）| `westock-data profile {code}` + `westock-data quote {code}` | ✅ 100% | market cap 从 quote 拿更实时 |

---

## 二、代码格式转换

financial-datasets 用美股代码（`AAPL`、`MSFT`），westock-data 用 `{market}{code}` 格式：

| 市场 | financial-datasets | westock-data code | 例子 |
|---|---|---|---|
| 沪 A | `600519.SS` | `sh600519` | sh600519（贵州茅台）|
| 深 A | `000001.SZ` | `sz000001` | sz000001（平安银行）|
| 京 A（北交所）| `830799.BJ` | `bj830799` | bj830799 |
| 港股 | `0700.HK` | `hk00700` | hk00700（腾讯）|
| 美股 | `AAPL` | `usAAPL` | usAAPL（苹果）|

> 转换函数见 `scripts/data_fetcher.py::ticker_to_westock()`。

---

## 三、财务字段对照

下表列出原项目 19 个 agent 用到的全部财务字段 → 来自 `FinancialMetrics` + `LineItem` 模型。

### A. 估值 / 盈利（FinancialMetrics 大部分字段都能拿）

| 原字段 | westock-data `finance` 字段 | agent 使用方 |
|---|---|---|
| `market_cap` | `MarketCap` / 实时从 `quote` 拿 | warren_buffett, ben_graham, valuation, peter_lynch, bill_ackman, fundamentals |
| `enterprise_value` | `EV` | bill_ackman, valuation |
| `price_to_earnings_ratio` | `PE_TTM` / `PE_LFY` | fundamentals, warren_buffett, valuation |
| `price_to_book_ratio` | `PB_MRQ` | fundamentals, ben_graham |
| `price_to_sales_ratio` | `PS_TTM` | fundamentals, charlie_munger |
| `enterprise_value_to_ebitda_ratio` | 需要 neodata 兜底 `EV/EBITDA` | valuation |
| `gross_margin` | `GrossMargin_TTM` | warren_buffett（定价权）|
| `operating_margin` | `OperatingMargin_TTM` | fundamentals, warren_buffett, mohnish_pabrai |
| `net_margin` | `NetProfitMargin_TTM` | fundamentals, phil_fisher, peter_lynch |
| `return_on_equity` | `ROE_TTM` | 几乎所有 agent |
| `return_on_assets` | `ROA_TTM` | warren_buffett |
| `current_ratio` | `CurrentRatio` 或 `CurrentRatio_TTM` | ben_graham, fundamentals, warren_buffett |
| `quick_ratio` | `QuickRatio` | warren_buffett |
| `debt_to_equity` | `DebtToEquityRatio` / `LiabilityToAssetRatio` | fundamentals, warren_buffett, ben_graham, michael_burry |
| `revenue_growth` | `OperatingRevenue_TTMYoY` | fundamentals, cathie_wood, phil_fisher, growth_agent |
| `earnings_growth` | `NetProfit_TTMYoY` | fundamentals, growth_agent |
| `book_value_growth` | `NAVPerShare_TTMYoY` | warren_buffett, fundamentals |
| `earnings_per_share` | `EPS_TTM` | 几乎所有 agent |
| `book_value_per_share` | `NAVPerShare` | ben_graham |
| `free_cash_flow_per_share` | `FCFPS` 或 `OCFPS` | fundamentals, warren_buffett |
| `payout_ratio` | `DividendPayoutRatio` | warren_buffett, charlie_munger |

### B. 财报行项目（LineItem）

| 原字段 | 替代 | 备注 |
|---|---|---|
| `revenue` | `finance` 命令里 `OperatingRevenue` | |
| `net_income` | `NetProfit` | |
| `earnings_per_share` | `EPSBasic` | |
| `book_value_per_share` | `NAVPerShare` | |
| `total_assets` | `TotalAssets` | |
| `total_liabilities` | `TotalLiabilities` | |
| `current_assets` | `CurrentAssets` | |
| `current_liabilities` | `CurrentLiabilities` | |
| `dividends_and_other_cash_distributions` | `DividendDistribution` / 从 `dividend` 命令查 | |
| `outstanding_shares` | `TotalShares` / `CirculationShares` | |
| `depreciation_and_amortization` | `DepreciationAmortization` | |
| `capital_expenditure` | `CapitalExpenditure` | |
| `working_capital` | `WorkingCapital` | |
| `free_cash_flow` | `FreeCashFlow` | |
| `operating_income` | `OperatingProfit` | |
| `gross_profit` | `GrossProfit` | |

> 注：westock-data 不同公司的字段覆盖度不同；个别字段缺失时 agent 应跳过该项不报错，
> 而不是用 0 填充。详见 `scripts/data_fetcher.py::safe_get()`。

### C. 新闻 / 内部人 / 公司事实

| 原端点 | 替代 | 字段映射 |
|---|---|---|
| `get_company_news(ticker, end_date, start_date, limit)` | `westock-data news article {code} --limit N` | title / date / source / url / sentiment 直接对应 |
| `get_insider_trades(ticker, end_date, start_date, limit)` | `westock-data shareholder {code}` + `westock-data notice list {code}` | 拿到董监高 / 大股东增减持事件；agent 需做语义匹配 |
| `get_market_cap(ticker, end_date)` | `westock-data quote {code}` 实时市值 | 若 `end_date` 不是今天则回退到 `finance --num 4` 最近期 market_cap |
| `get_company_facts(ticker)` | `westock-data profile {code}` | industry / sector / listing_date / employees / website |

---

## 四、缓存策略

- 路径：`~/.workbuddy/skills/ai-hedge-fund/data_cache/{ticker}_{key}.json`
- 键：原 `cache_key` 命名规则保持一致（`{ticker}_{period}_{end_date}_{limit}` 等）
- TTL：行情 1 天，财务 7 天，公司新闻 1 天，股东/内部人 7 天
- 命中时直接读 JSON 不调 API；首次 miss 才走 westock-data

> 缓存不区分 LRU 容量，文件命名空间全靠 key；过期靠 TTL 时间戳。

---

## 五、错误兜底

```
westock-data finance 报错 / 字段缺失
  → neodata-financial-search 兜底（自然语言问）
  → 仍失败：agent 跳过该项，给出 "数据不可用" 占位信号
```

- 单个 ticker 拉数据失败不应阻塞整个流程
- 关键指标（PE/ROE/revenue/market_cap）任一缺失时该 ticker 标 "skip"，其他 ticker 继续
- 输出 JSON 里所有 "confidence" 必须基于实际拿到的数据，不得凭空给 70/80
