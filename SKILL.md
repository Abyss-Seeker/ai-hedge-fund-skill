---
name: ai-hedge-fund
summary: 复现 virattt/ai-hedge-fund 的多 agent AI 投资分析流程。用 WorkBuddy 自带的金融数据 skill（westock-data + neodata）替代原项目的 financial-datasets API。
read_when:
  - 用户想跑多 agent AI 投资分析（仿对冲基金流程）
  - 用户提到 ai-hedge-fund / 对冲基金 / 多 agent 投资
  - 用户想选 19 个投资大师 / 估值模型 + 自动汇总决策
---

# AI Hedge Fund (WorkBuddy Edition)

> 复现 [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) 的 19-agent 投资分析框架。
> 把原项目用付费的 `financial-datasets.ai` API 拉数据，改成用 WorkBuddy 内置的金融数据 skill。

---

## 一、这是干什么的

按用户给的 ticker 列表，并行跑 19 个投资分析 agent（13 个投资大师 + 6 个功能型），
得到每个 ticker 的 `bullish / bearish / neutral` 信号，再汇总通过 Risk Manager（基于波动率 + 相关性）
和 Portfolio Manager（基于允许仓位 + 共识比例）给出最终下单建议。

| 阶段 | 输入 | 输出 |
|---|---|---|
| 1. 数据拉取 | tickers / 日期范围 | 价格 + 财务 + 新闻 + 股东 |
| 2. Analyst agents（并行）| 数据 | 每个 ticker 的 signal + confidence |
| 3. Risk Manager | 所有 ticker 价格 + portfolio | 每个 ticker 的 position_limit |
| 4. Portfolio Manager | signals + risk 数据 | 最终 buy/sell/short/cover/hold 决策 |

---

## 二、与原项目差异

| 项 | 原项目 | 本 skill |
|---|---|---|
| 数据源 | `https://api.financialdatasets.ai/`（付费）| **westock-data + neodaTa-financial-search**（免费，WorkBuddy 内置）|
| LLM | OpenAI / Anthropic / Groq / DeepSeek / Ollama | **当前 WorkBuddy 路由的任意 LLM**（你 → 我） |
| 行情 / 财务字段 | 英文驼峰命名 | 跨 A 股 / 港股 / 美股自动适配 |
| News 字段 | `news` 端点 | `report`（研报）+ `notice`（公告）拼接 |
| Insider 字段 | 完整 transaction | `shareholder`（大股东）+ 增减持公告关键词过滤（**降级**）|
| 公司事实 | `company/facts` | `profile`（简况）|
| 缓存层 | sqlite | 本地 JSON 文件 |

---

## 三、怎么用

### 3.1 触发词

- "跑一下 ai-hedge-fund"
- "AI 对冲基金分析"
- "对冲基金流程跑 X / Y / Z"
- "用 virattt 那个多 agent 框架分析"
- "选几个投资大师跑一下"

### 3.2 推荐使用方式（让 WorkBuddy AI 来跑）

> 最完整的体验是让 AI（也就是本 skill 加载后的我）来跑：每个 agent 我能用 LLM 做风格化输出，
> 数据通过 westock-data 拉，结果汇总给用户做决策。

调用模板（直接对 WorkBuddy 说）：

```
用 ai-hedge-fund 分析 00700.HK,600519.SH,AAPL，
日期范围 2026-04-01 ~ 2026-07-24，
初始资金 100 万，
选这几位投资大师：warren_buffett, peter_lynch, nassim_taleb, cathie_wood, charlie_munger
+ 这几位功能型：fundamentals, technicals, valuation
输出 JSON 决策 + 推理。
```

我会按下面流程跑：
1. 用 `westock-data search` 查代码（如有需要）
2. 用 `westock-data quote / finance / kline / news / shareholder / profile` 拉数据
3. 按 `references/analyst-algorithms.md` 跑 19 个 agent 的量化打分
4. 用 LLM 做风格化 reasoning 输出
5. 跑 Risk Manager（波动率 / 相关性）+ Portfolio Manager（共识比例）
6. 输出 JSON 到 `results/run_<ts>.json`

### 3.3 命令行脚本模式（不需要 LLM）

> 纯规则版，无 LLM 风格化。所有 agent 走 hard-coded 量化算法。  
> 适合快速 smoke test / 验证数据。

```bash
cd ~/.workbuddy/skills/ai-hedge-fund/scripts
python run_fund.py \
  --ticker 00700.HK,600519.SH,AAPL \
  --analysts warren_buffett,ben_graham,peter_lynch,nassim_taleb,fundamentals_analyst,technical_analyst,valuation_analyst,news_sentiment_analyst \
  --start 2026-04-01 --end 2026-07-24 \
  --initial-cash 1000000 \
  --show-reasoning \
  --output ../results/my_run.json
```

参数：
- `--ticker` 必填，逗号分隔。支持 `AAPL` / `usAAPL` / `600519.SH` / `sh600519` / `00700.HK` / `hk00700`
- `--analysts` 选填，默认全部 19 个。支持的 key 见下文 §4
- `--start / --end` 选填，默认最近 3 个月
- `--initial-cash` 选填，默认 1,000,000
- `--margin-requirement` 选填，默认 0.5
- `--show-reasoning` 显示每个 agent 的 reasoning
- `--output` JSON 输出路径

---

## 四、19 个 Agent Key

```text
# 投资大师（13 个）
aswath_damodaran, ben_graham, bill_ackman, cathie_wood, charlie_munger,
michael_burry, mohnish_pabrai, nassim_taleb, peter_lynch, phil_fisher,
rakesh_jhunjhunwala, stanley_druckenmiller, warren_buffett

# 功能型（6 个）
technical_analyst, fundamentals_analyst, growth_analyst,
news_sentiment_analyst, sentiment_analyst, valuation_analyst
```

> 注意：`technical_analyst`（没 s），`technicals_analyst` 会被自动归一化。

默认全部；至少建议保留：`fundamentals_analyst` + `technical_analyst` + `valuation_analyst`
+ 至少 2 位投资大师（warren_buffett + peter_lynch 是稳妥组合）。

---

## 五、用户决策点（必复现的部分）

跑之前必须问用户：

| 决策 | 默认 | 备注 |
|---|---|---|
| 1. ticker 列表 | — | 必填 |
| 2. 选哪些 agent | 全选 | 用户可 subset |
| 3. 日期范围 | 最近 90 天 | |
| 4. 初始资金 | 1,000,000 | 任意币种都行 |
| 5. 初始持仓 | 全空 | 若用户已有持仓，提供 long/short 数 |
| 6. 保证金比例 | 0.5 | < 1.0 → 可融资 |
| 7. 显示 reasoning | off | on → 体积更大，token 多 |

---

## 六、数据源映射速查（详见 references/data-mapping.md）

| 用途 | 原项目 | 本 skill |
|---|---|---|
| 日 K 线 | `GET /prices/` | `westock-data kline {code} --period day --start X --end Y` |
| 财务指标 | `GET /financial-metrics/` | `westock-data finance {code} --num N` + 自适配 A 股 / 港股 / 美股 |
| 财报行项目 | `POST /financials/search/line-items` | 同上（合并到 `finance`）|
| 公司新闻 | `GET /news/` | `report` + `notice`（westock-data news 命令在当前渠道不可用）|
| 内部人交易 | `GET /insider-trades/` | `shareholder` + 增减持公告（降级）|
| 市值 | `GET /company/facts/` | `quote` 的 `total_market_cap`（单位亿）|

---

## 七、已知限制

1. **数据缺失时给空信号**：单 ticker 字段全缺，agent 输出 `neutral / conf 0`，不会编造。
2. **公司新闻不完整**：westock-data news 命令在当前渠道不可用，用研报 + 公告拼接。
3. **Insider 数据降级**：原项目有 transaction_price / shares 精细字段，本 skill 只能拿到大股东 + 增减持事件标题。
4. **A股 finance zhsy 缺失**：A 股 zhsy 不存在，财务比率从 zcfz 自己算。
5. **valuation_analyst 简化**：脚本版只跑 PE/PB + 简化 DCF，不跑完整 4 模型加权。如要完整估值，让 AI 跑。
6. **未实盘交易**：仅输出建议，不会下单。
7. **LLM 风格化只在 AI 模式**：脚本模式输出 JSON 推理比较机械。

---

## 八、目录结构

```
ai-hedge-fund/
├── SKILL.md              ← 你正在读
├── references/
│   ├── data-mapping.md        字段映射总表
│   ├── agent-roles.md         19 个 agent 的角色卡 + system prompt
│   ├── analyst-algorithms.md  19 个 agent 的量化算法
│   └── risk-portfolio.md      Risk Manager + Portfolio Manager 路由逻辑
├── scripts/
│   ├── data_fetcher.py        6 个 API 替代函数（westock-data → 原 financial-datasets 接口）
│   └── run_fund.py            主执行器（CLI 入口）
└── data_cache/                本地 JSON 缓存（按 key 自动过期）
```

---

## 九、典型示例对话

**例 1：让 AI 跑（推荐）**
> 用户："用 ai-hedge-fund 帮我看看 腾讯、茅台、苹果 现在该不该买"  
> 我：先确认 tickers / 日期 / 资金 → 拉数据 → 跑 19 agent（用 LLM 风格化）→ 输出决策 JSON  
> 我："00700.HK 4/19 看多（warren / lynch / taleb / technical 都看多），建议 buy × 50 @ 434；
> 600519.SH 共识偏中性 hold；
> AAPL 估值偏贵（PE 38.9）6/19 看空，建议 sell 现持仓 70% 或 short"

**例 2：命令行快速跑**
```bash
python run_fund.py --ticker 00700.HK,600519.SH,AAPL \
  --analysts warren_buffett,peter_lynch,fundamentals_analyst,technical_analyst \
  --initial-cash 5000000
```

**例 3：回测模式**
```bash
python run_fund.py --ticker AAPL \
  --start 2024-01-01 --end 2024-12-31 \
  --analysts warren_buffett,ben_graham,valuation_analyst
```
（注意：本 skill 没自带回测器；想回测建议自己写个简单 wrapper 循环调用 run_fund.py）

---

## 十、依赖

- Python 3.10+
- `westock-data`（已安装于 WorkBuddy 内置 skills）
- `node`（运行 westock-data 用）
- 不需要任何额外 Python 包（data_fetcher 纯 stdlib）

---

## 十一、声明

本 skill 输出的所有交易建议**仅用于研究和教育目的**，不构成投资建议。
真实交易前请咨询持牌投资顾问，使用者自负盈亏。