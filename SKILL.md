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
> 用 WorkBuddy 内置的金融数据 skill 替代原项目付费 API，最后生成 PDF 报告。

---

## 零、首次加载须知（AI 必须执行）

**每次 skill 被加载，AI 必须做以下两件事：**

### 0.1 用最简单的话告诉用户怎么用

AI 第一句话应该像这样：

> "这个 skill 会在你选定的几只股票上，同时跑 19 个 AI 分析师——Warren Buffett 算估值、Peter Lynch 找十倍股、Nassim Taleb 测风险……最后汇总给出买/卖/持仓建议，并生成一份 PDF 报告。
> 
> 你只需要告诉我：**想看哪些股票**（比如 00700.HK, AAPL），剩下的日期、资金、选哪些分析师都用默认值就行。"

### 0.2 参数确认流程（如果用户没给参数）

如果用户没有在第一次请求中给出完整参数，AI **必须**列出下表，问用户要不要改：

| 参数 | 说明 | 默认值 |
|---|---|---|
| **股票代码** | 想看哪些？支持 A 股/港股/美股。例：`600519.SH, 00700.HK, AAPL` | *必填，无默认* |
| **看哪些分析师** | 19 个投资大师+功能型分析师，选几个？ | 全部 19 个（最全面） |
| **日期范围** | 分析哪段时间的数据？ | 最近 90 天 |
| **初始资金** | 模拟用多少钱起步？ | 100 万（1,000,000） |
| **已有持仓** | 之前买了哪些股票、多少股？ | 空仓（还没买过） |
| **保证金比例** | 能不能融资做空？0.5 = 可以借一半 | 0.5 |
| **生成 PDF 报告** | 最后要不要输出一份 PDF？ | 要（默认生成） |

**询问话术模板：**

> "上面的参数我帮你列好了，除了股票代码必须告诉我之外，其他都可以用默认值直接跑。你想改哪个，还是直接按默认跑？"

如果用户说"以后都走默认"——AI 记录这句话，之后加载 skill 时不再列出参数表，直接进入用户说看哪些股票→用默认跑。

---

## 一、这是干什么的

按用户给的 ticker 列表，并行跑 19 个投资分析 agent（13 个投资大师 + 6 个功能型），
得到每个 ticker 的 `bullish / bearish / neutral` 信号，再汇总通过 Risk Manager（基于波动率 + 相关性）
和 Portfolio Manager（基于允许仓位 + 共识比例）给出最终下单建议，最后生成一份 PDF 报告。

| 阶段 | 输入 | 输出 |
|---|---|---|
| 1. 数据拉取 | tickers / 日期范围 | 价格 + 财务 + 新闻 + 股东 |
| 2. Analyst agents（并行）| 数据 | 每个 ticker 的 signal + confidence + reasoning |
| 3. Risk Manager | 所有 ticker 价格 + portfolio | 仓位限制 |
| 4. Portfolio Manager | signals + risk 数据 | 最终 buy/sell/short/cover/hold 决策 |
| 5. PDF 报告 | 以上所有 | 一份格式化的 PDF 文件 |

---

## 二、运行过程展示（AI 必须执行）

AI 跑分析时，**必须逐步展示进度**，让用户知道现在在干什么。格式：

```
正在拉取数据……
  ✓ 600519.SH — 78 天行情 + 8 期财报 + news
  ✓ 00700.HK — 76 天行情 + 8 期财报 + news

正在运行分析师（共 12 位）……
  ✓ warren_buffett — bullish (conf 72%)
  ✓ peter_lynch — neutral (conf 50%)
  ✓ nassim_taleb — bearish (conf 65%)
  ...（逐个展示）

Risk Manager 计算中……
  600519.SH: 价格 1291.74, 仓位上限 185,956, 波动率 24.4%
  00700.HK: 价格 434.60, 仓位上限 134,796, 波动率 41.0%

汇总决策中……
```

最后输出判定表：

| ticker | 决策 | 数量 | 置信度 | 信号分布 |
|---|---|---|---|---|
| 600519.SH | BUY | 120 | 60% | 3 bullish / 1 bearish / 8 neutral |
| 00700.HK | HOLD | 0 | 50% | 1 bullish / 0 bearish / 11 neutral |
| AAPL | HOLD | 0 | 46% | 1 bullish / 2 bearish / 9 neutral |

---

## 三、PDF 报告生成（AI 必须执行）

分析完成后，AI **必须**生成一份 PDF 报告，保存到 `results/ai_hedge_fund_report_<timestamp>.pdf`。

### 报告内容要求

1. **封面**：标题 "AI Hedge Fund 分析报告" + 日期 + ticker 列表
2. **摘要页**：每个 ticker 的最终决策 + 多空比
3. **分析师信号总览表**：每个 ticker × 每个 agent 的 signal / confidence / reasoning 表格
4. **风险数据**：每个 ticker 的价格、波动率、仓位限制
5. **免责声明**

### 生成方式

优先使用 Python `fpdf2` 库或 WorkBuddy 自带的 `pdfkit-py` skill。如果不可用，先生成一份格式良好的 HTML，再告知用户可以手动导出为 PDF。

AI 生成 PDF 后应告诉用户路径："报告已保存到 results/ai_hedge_fund_report_20260724_2330.pdf"

### PDF 模板参考

```python
# scripts/generate_report.py 可独立调用
python generate_report.py --input results/run_xxx.json --output results/report_xxx.pdf
```

---

## 四、与原项目差异

| 项 | 原项目 | 本 skill |
|---|---|---|
| 数据源 | `https://api.financialdatasets.ai/`（付费）| **westock-data + neodata**（免费，WorkBuddy 内置）|
| LLM | OpenAI / Anthropic / Groq / DeepSeek / Ollama | **WorkBuddy 路由的任意 LLM** |
| 行情 / 财务字段 | 英文驼峰命名 | 跨 A 股 / 港股 / 美股自动适配 |
| News 字段 | `news` 端点 | `report`（研报）+ `notice`（公告）拼接 |
| Insider 字段 | 完整 transaction | `shareholder`（大股东）+ 增减持公告关键词过滤（**降级**）|
| 缓存层 | sqlite | 本地 JSON 文件 |
| 输出 | 控制台 JSON | 控制台 + JSON + **PDF 报告** |

---

## 五、怎么用

### 5.1 触发词

- "跑一下 ai-hedge-fund"
- "AI 对冲基金分析"
- "对冲基金流程跑 X / Y / Z"
- "用 virattt 那个多 agent 框架分析"

### 5.2 AI 模式（推荐）

直接对 WorkBuddy 说：

```
用 ai-hedge-fund 分析 00700.HK,600519.SH,AAPL，生成 PDF 报告
```

### 5.3 命令行脚本模式（无 LLM，无 PDF）

```bash
cd ~/.workbuddy/skills/ai-hedge-fund/scripts
python run_fund.py \
  --ticker 00700.HK,600519.SH,AAPL \
  --analysts warren_buffett,ben_graham,peter_lynch,nassim_taleb,fundamentals_analyst,technical_analyst,valuation_analyst \
  --start 2026-04-01 --end 2026-07-24 \
  --initial-cash 1000000
```

---

## 六、19 个 Agent Key

```
# 投资大师（13 个）
aswath_damodaran, ben_graham, bill_ackman, cathie_wood, charlie_munger,
michael_burry, mohnish_pabrai, nassim_taleb, peter_lynch, phil_fisher,
rakesh_jhunjhunwala, stanley_druckenmiller, warren_buffett

# 功能型（6 个）
technical_analyst, fundamentals_analyst, growth_analyst,
news_sentiment_analyst, sentiment_analyst, valuation_analyst
```

默认全部。稳妥组合：`fundamentals_analyst` + `technical_analyst` + `valuation_analyst` + warren_buffett + peter_lynch。

---

## 七、用户决策点

| 参数 | 默认 | 说明 |
|---|---|---|
| ticker 列表 | *必填* | 支持 `AAPL` / `600519.SH` / `00700.HK` |
| 选哪些 agent | 全部 19 个 | 可 subset |
| 日期范围 | 最近 90 天 | YYYY-MM-DD ~ YYYY-MM-DD |
| 初始资金 | 1,000,000 | 任意币种 |
| 初始持仓 | 空仓 | 有持仓报 long/short 数量 |
| 保证金比例 | 0.5 | |
| 生成 PDF 报告 | 是 | 默认生成 |

---

## 八、数据源映射

详见 `references/data-mapping.md`。

---

## 九、已知限制

1. 数据缺失时给空信号，不编造
2. 公司新闻用研报 + 公告拼接（westock-data news 渠道不可用）
3. Insider 降级为大股东 + 增减持公告
4. A 股 zhsy 不存在，比率从 zcfz 算
5. 脚本版 valuation 只跑简化 DCF；AI 模式可跑完整 4 模型
6. 不执行真实交易
7. 数据严重不全时 agent 给 neutral（不捏造 bearish 信号）—— 2026-07-24 修复

---

## 十、目录结构

```
ai-hedge-fund/
├── SKILL.md                    ← 你正在读
├── README.md                   ← GitHub 首页文档
├── references/
│   ├── data-mapping.md
│   ├── agent-roles.md
│   ├── analyst-algorithms.md
│   └── risk-portfolio.md
├── scripts/
│   ├── data_fetcher.py
│   ├── run_fund.py
│   └── generate_report.py      ← PDF 报告生成器
└── results/                    ← 所有输出（JSON + PDF）
```

---

## 十一、依赖

- Python 3.10+
- `westock-data`（WorkBuddy 内置）
- `node`（运行 westock-data）
- `fpdf2`（PDF 报告生成，可选：`pip install fpdf2`）

---

## 十二、声明

本 skill 输出的所有交易建议仅用于研究和教育目的，不构成投资建议。