# AI Hedge Fund Skill

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)

> **WorkBuddy搜索 "技能-AI对冲基金智囊团" 即可一键添加使用**

> **Agent一键安装Prompt：** ```请根据 https://skillhub.cn/install/skillhub.md，安装 ai-hedge-team。```

**此项目为AI辅助生成，仅作学习探讨使用，不可作为投资参考。**

> **复现 [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) 的 19-agent 投资分析框架**，
> 用 WorkBuddy 内置的免费金融数据 skill 替代原项目的付费 `financial-datasets.ai` API。

19 个 AI 代理并行分析一只股票：Warren Buffett 算内在价值，Peter Lynch 看 PEG 十倍股，Nassim Taleb 测反脆弱性……最后 Risk Manager 控仓位，Portfolio Manager 拍板下单 —— 整个流程在 WorkBuddy 里一句话跑完。

```
"用 AI对冲基金智囊团 帮我看看 腾讯、茅台、苹果 现在该不该买"
```

---

## 架构

```
                用户输入（tickers / agents / 日期 / 资金）
                            │
            ┌───────────────┼───────────────┐
            ▼               ▼               ▼
       westock-data    neodata      westock-data
       (行情/财务)     (兜底搜索)    (新闻/股东)
            │               │               │
            └───────────────┼───────────────┘
                            ▼
            ┌───────────────────────────────┐
            │   13 投资大师 + 6 功能 Agent  │  ← 并行
            │   Warren · Lynch · Taleb ...  │
            └───────────────┬───────────────┘
                            ▼
                    ┌──────────────┐
                    │  Risk Manager │  ← 波动率+相关性 算仓位限制
                    └──────┬───────┘
                           ▼
                    ┌──────────────────┐
                    │ Portfolio Manager │  ← 共识比例 → 下单
                    └──────────────────┘
```

---

## 安装方式

### 方式 A：WorkBuddy 内一键安装（推荐）

直接在 WorkBuddy 对话里说：

```
帮我安装 AI对冲基金智囊团 skill
```

或者手动 clone 到 WorkBuddy 的 skills 目录：

```bash
git clone https://github.com/virattt/ai-hedge-fund-skill.git ~/.workbuddy/skills/ai-hedge-fund/
```

装完后下次对话说 "用 AI对冲基金智囊团 跑" 即可触发。

### 方式 B：独立 Python 脚本（不需要 WorkBuddy）

如果你只想用脚本模式（不需要 WorkBuddy AI）：

```bash
git clone https://github.com/virattt/ai-hedge-fund-skill.git
cd ai-hedge-fund-skill/scripts

# 需要先装 westock-data（WorkBuddy 内置 skill）
# 独立使用需自行配置：见下方「独立环境配置」

python run_fund.py \
  --ticker 00700.HK,600519.SH,AAPL \
  --analysts warren_buffett,peter_lynch,fundamentals_analyst,valuation_analyst \
  --initial-cash 1000000
```

> **注意**：独立脚本模式**不调用 LLM**，所有 agent 走 hard-coded 量化算法。  
> 要 LLM 风格化输出（Warren 用他的语气写 reasoning），必须走 WorkBuddy AI 模式。

---

## 使用示例

### CLI（脚本模式，不需要 LLM）

```bash
cd scripts
python run_fund.py \
  --ticker 00700.HK,600519.SH,AAPL \
  --analysts warren_buffett,ben_graham,peter_lynch,nassim_taleb,technical_analyst,fundamentals_analyst,valuation_analyst \
  --start 2026-04-01 --end 2026-07-24 \
  --initial-cash 1000000 \
  --show-reasoning
```

输出：

```
============================================================
FINAL TRADING DECISIONS
============================================================
  00700.HK HOLD  ×    0 (conf 50%)  mixed 1B/1Be/3N
  600519.SH BUY   ×  120 (conf 60%)  3/5 bullish; risk allows 120
  AAPL     SHORT ×  543 (conf 80%)  4/5 bearish; short 543
```

### AI 模式（WorkBuddy 内，最完整）

在 WorkBuddy 对话中：

```
用 AI对冲基金智囊团 分析 00700.HK,600519.SH,AAPL，
日期 2026-04-01 ~ 2026-07-24，初始资金 100 万，
选 warren_buffett, peter_lynch, nassim_taleb, cathie_wood
+ fundamentals, technicals, valuation
给我输出每个 agent 的 reasoning 和最终决策 JSON
```

AI 会用 LLM 给每个 agent 写风格化推理，输出完整 JSON。

---

## CLI 参数一览

| 参数 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `--ticker` | ✅ | — | 逗号分隔，支持 `AAPL` / `600519.SH` / `00700.HK` |
| `--analysts` | ❌ | 全部 19 个 | 逗号分隔 agent key |
| `--start` | ❌ | 90 天前 | `YYYY-MM-DD` |
| `--end` | ❌ | 今天 | `YYYY-MM-DD` |
| `--initial-cash` | ❌ | 1,000,000 | 初始现金 |
| `--margin-requirement` | ❌ | 0.5 | 保证金比例 |
| `--show-reasoning` | ❌ | off | 打印每个 agent 的评分细节 |
| `--output` | ❌ | `results/run_<ts>.json` | JSON 输出路径 |

---

## 19 个 Agent 一览

### 13 投资大师

| Key | 代理人 | 风格 | Script 精度 |
|---|---|---|---|
| `warren_buffett` | Warren Buffett | 护城河 + 安全边际 + DCF | ★★★★☆ |
| `ben_graham` | Ben Graham | NCAV + Graham Number + 净流动资产 | ★★★★☆ |
| `peter_lynch` | Peter Lynch | GARP + PEG + 十倍股 | ★★★★☆ |
| `nassim_taleb` | Nassim Taleb | 反脆弱 + 尾部风险 + 凸性 | ★★★☆☆ |
| `cathie_wood` | Cathie Wood | 颠覆性创新 + 指数增长 | ★★☆☆☆ |
| `charlie_munger` | Charlie Munger | 优质企业 + 合理价格 + 逆向思考 | ★★☆☆☆ |
| `bill_ackman` | Bill Ackman | 激进投资者 + 催化剂 | ★★☆☆☆ |
| `michael_burry` | Michael Burry | 逆向 + 深度价值 + 做空 | ★★☆☆☆ |
| `mohnish_pabrai` | Mohnish Pabrai | Dhandho + 低风险翻倍 | ★★☆☆☆ |
| `phil_fisher` | Phil Fisher | Scuttlebutt + 管理层 + 创新产品 | ★★☆☆☆ |
| `stanley_druckenmiller` | Stanley Druckenmiller | 宏观 + 非对称机会 | ★★☆☆☆ |
| `aswath_damodaran` | Aswath Damodaran | 故事 + 数字 + 严谨估值 | ★★☆☆☆ |
| `rakesh_jhunjhunwala` | Rakesh Jhunjhunwala | 新兴市场 + 大牛 | ★★☆☆☆ |

### 6 功能型 Agent

| Key | 功能 | Script 精度 |
|---|---|---|
| `fundamentals_analyst` | 基本面 4 维打分（盈利/增长/健康/估值比） | ★★★★☆ |
| `technical_analyst` | 5 子策略加权（趋势/均值回归/动量/波动率/统计套利） | ★★★★★ |
| `valuation_analyst` | PE/PB + 简化 DCF（脚本版）; 完整 4 模型加权（AI 版） | ★★★☆☆ |
| `growth_analyst` | 3 年 CAGR + PEG | ★★★☆☆ |
| `news_sentiment_analyst` | 研报+公告情感计数 | ★★☆☆☆ |
| `sentiment_analyst` | 反向共识指标 | ★★★☆☆ |

> **精度星级**：★★★★★ 纯规则不依赖 LLM，稳定可靠；★★★☆☆ 部分依赖简化；★★☆☆☆ 脚本版可跑但需 AI 模式才能成形。

---

## 数据来源

| 数据 | 来源 | 缓存 TTL |
|---|---|---|
| 日 K 线 | `westock-data kline` | 1 天 |
| 财务指标（ROE / PE / D/E 等） | `westock-data finance` + 跨市场自适配 | 7 天 |
| 实时行情 + 市值 | `westock-data quote` | 1 天 |
| 公司新闻 | `westock-data report` + `notice list` 拼接（news 命令渠道不可用） | 1 天 |
| 股东 / 内部人 | `westock-data shareholder` + 增减持公告关键词过滤 | 7 天 |
| 公司简况 | `westock-data profile` | 30 天 |
| 兜底搜索 | `neodata-financial-search`（自然语言问） | 不缓存 |

> **跨市场自动适配**：港股（zhsy/zcfz/xjll）、A 股（lrb/zcfz/xjll）、美股（income/balance/cashflow）字段名不同，`data_fetcher.py` 自动识别 + 补全缺失的财务比率。

---

## Precision: Script vs AI Mode

逸世问的「能不能 agent 调用更精确的版本」—— 答案在下面这张表里：

| 维度 | Script 模式 | AI 模式（WorkBuddy 内） |
|---|---|---|
| **数据源** | westock-data + neodata | 同左（完全一样） |
| **量化算法** | hard-coded 规则（见 `analyst-algorithms.md`） | 同左 + LLM 补充判断 |
| **Reasoning 质量** | 机械（"score 6/15 EPS 全正"） | 风格化（"This stock trades at a 35% discount to NCAV..."） |
| **Valuation Agent** | PE/PB + 简化 5y DCF | 完整 4 模型加权（DCF + Owner Earnings + EV/EBITDA + RIM） |
| **投资大师** | 通用 moat 算法（8/13 走同一套） | 每个 agent 用独立 LLM system prompt，行为更像原作 |
| **Insider 数据** | 大股东 + 关键词过滤 | 大股东 + 增减持公告全文分析 |
| **News 数据** | 研报 + 公告情感计数 | 研报全文 LLM 理解 + 公告事件分类 |
| **最终下单** | 共识比例 ≥ 60% buy/short | LLM 综合所有 agent 推理，做情境判断 |
| **速度** | 3-5 秒 per ticker | 取决于 LLM 模型（通常 10-30 秒 per ticker） |

### 如何让脚本版更精确

如果你想在脚本版（无 LLM）下跑得更准：

1. **选对 agent**：至少选 `fundamentals_analyst` + `technical_analyst` + `valuation_analyst` + 2 位大师（warren_buffett, peter_lynch）
2. **数据够多**：日期范围至少 90 天（finance 需要多期对比，kline 需要 30 根 bar）
3. **不跑 A 股 valuation**：A 股 finance 字段不如港股 / 美股全，valuation 的 DCF 依赖 EPS → 缺 EPS 时走简化 DCF
4. **自定义阈值**：编辑 `scripts/analysts.py` 里的 `_signal()` 函数，调 bullish_thr / bearish_thr 到自己想要的范围

### 如何让 AI 模式更精确

1. **给足够的 ticker 上下文**：“如果 A 涨了 B 也涨”这种联动判断要在对话里说出来，让我在 agent prompt 里注入
2. **指定 agent 权重**：比如 "valuation 的信号的权重应该翻倍" — 我修改 portfolio_manager 聚合逻辑
3. **跑多次对比**：改日期范围，看不同时间窗口的信号稳定性

---

## 文件结构

```
ai-hedge-fund-skill/
├── README.md                       ← 你正在读
├── SKILL.md                        ← WorkBuddy skill 入口（触发词 / 路由）
├── .gitignore
├── LICENSE
├── requirements.txt
├── references/
│   ├── data-mapping.md             ← financial-datasets → westock-data 字段映射
│   ├── agent-roles.md              ← 19 agent 角色卡 + system prompt
│   ├── analyst-algorithms.md       ← 19 agent 量化算法（含原项目源码细节）
│   └── risk-portfolio.md           ← Risk + Portfolio 路由逻辑
├── scripts/
│   ├── data_fetcher.py             ← 6 个 API 替代函数 + 跨市场适配
│   ├── run_fund.py                 ← 主执行器（CLI）
│   └── results/                    ← CLI 生成的 JSON 结果
└── data_cache/                     ← 本地 JSON 缓存（自动过期）
```

---

## 对于原项目的改动

| 项 | 原项目 (virattt/ai-hedge-fund) | 本 skill |
|---|---|---|
| 数据源 | `api.financialdatasets.ai`（需 API Key） | **westock-data** + **neodata**（WorkBuddy 内置，免费） |
| LLM | OpenAI / Anthropic / Groq / DeepSeek / Ollama | **WorkBuddy 路由**的任意 LLM |
| 语言 | Python + Poetry + LangGraph | **标准 Python 3.10+**（无外部依赖） |
| A 股 | 不支持 | **支持 A 股 / 港股 / 美股** 跨市场自动适配 |
| 安装 | `poetry install` + 配 `.env` | **零配置**（WorkBuddy 内），或 `python run_fund.py` |
| 输出 | 控制台 JSON | 控制台 + 结构化 JSON 文件 |
| LangGraph | 用 LangGraph StateGraph 做节点流 | **direct 函数调用**（更简单，更少依赖） |

---

## 独立环境配置（不需要 WorkBuddy）

如果你只是想在本地 Python 环境跑脚本版（不需要 WorkBuddy AI）：

```bash
# 1. 克隆
git clone https://github.com/virattt/ai-hedge-fund-skill.git
cd ai-hedge-fund-skill

# 2. 无需 pip install（纯 stdlib）—— 直接跑
python scripts/run_fund.py --ticker AAPL,MSFT --analysts warren_buffett,fundamentals_analyst,technical_analyst

# 3. 但 run_fund.py 依赖 data_fetcher.py 调用 westock-data（WorkBuddy 内置 skill）
#    → 不用 WorkBuddy 的话，需要把 westock-data 独立装到 PATH（问 WorkBuddy 官方）
#    → 或者改 data_fetcher.py 换成你自己的数据源（分叉适配）
```

> **推荐**：用 WorkBuddy AI 模式，一句对话跑完所有；脚本模式作为 smoke test / 快速验证用。

---

## 已知限制

1. **westock-data news 命令在当前渠道不可用** → 用研报 + 公告拼接。news_sentiment 分析偏保守。
2. **Insider 精细字段缺失**（transaction_price / shares）→ 用大股东持股 + 增减持公告关键词过滤。
3. **A 股 zhsy 不存在** → 财务比率从 zcfz 自己算，部分字段（EPS growth / book_value_growth）覆盖不全。
4. **脚本版 valuation 只跑简化 DCF**（不跑完整 4 模型加权）。AI 模式下可完整跑。
5. **不执行真实交易**。纯研究 / 教育工具。
6. **A 股 finance 默认只输出最近 1-2 期**（westock-data 的 A 股数据返回策略），跨期对比能力弱于港股/美股。

---

## 贡献

Fork → 改代码 → 开 PR。请保持 PR 小而专注。

- 想加新的 agent？在 `scripts/analysts.py` 的 `AGENT_REGISTRY` 里注册新函数 + 在 `references/agent-roles.md` 加角色卡
- 想换数据源？改 `data_fetcher.py` 的 6 个 `get_*` 函数（接口签名别动），已有的函数名跟原项目 `src/tools/api.py` 一致
- 发现 A 股 / 美股字段覆盖不全？改 `data_fetcher.py` 里的 `get_financial_metrics` 字段映射表

---

## 许可

MIT License — 见 [LICENSE](LICENSE)。

原项目 [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) 也是 MIT。

---

## 声明

本 skill 输出的所有交易建议**仅用于研究和教育目的**，不构成投资建议。
过去表现不代表未来结果。真实交易前请咨询持牌投资顾问。

---

*Made with ❤️ for the WorkBuddy ecosystem. 19 agents, zero API keys needed.*
