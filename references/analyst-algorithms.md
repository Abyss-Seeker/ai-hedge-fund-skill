# 19 个 Agent 的量化算法

> 每个 agent 的"数据 → 子分析 → 加权聚合 → LLM 风格化输出"流水线。
> 部分 agent 是纯规则（如 technical_analyst），其余是 LLM 二次打分。
> 评分逻辑有 bug 不属于本 skill 修复范围 —— 沿用原项目语义。

---

## §1 投资大师（13 个）

### 1.2 Ben Graham — total max 15

```text
sub_total = earnings_stability + financial_strength + graham_valuation
signal    = bullish if sub_total >= 0.7 * 15 else bearish if sub_total <= 0.3 * 15 else neutral
```

| 子分析 | 满分 | 加分项 |
|---|---|---|
| `earnings_stability` | 4 | EPS 全正 +3，>80% 正 +2，末期 EPS > 初期 +1 |
| `financial_strength` | 5 | 流动比率 ≥2 +2，≥1.5 +1；负债率 <0.5 +2，<0.8 +1；多数期有分红 +1 |
| `graham_valuation` | 7 | NCAV > market_cap +4；NCAV/share ≥ 2/3 price +2；Graham Number MOS >50% +3，>20% +1 |

**LLM 再读**：用 Graham 风格写 reasoning，引用 Graham Number / NCAV / Current Ratio 等具体数字。

### 1.5 Charlie Munger — 借鉴模板

| 子分析 | 满分 | 加分项 |
|---|---|---|
| business_quality | 8 | ROE >20% +3，>15% +2；op margin >20% +3，>15% +2；gross margin >50% +2；D/E <0.3 +1 |
| moat | 5 | ROE 多年 >15%；gross margin 5 年稳定；asset turnover >1 |
| management | 4 | 股份回购 +2；无稀释 +1；稳定分红 +1 |
| valuation | 3 | PE <15 +2，<25 +1 |

满分 20；>14 bullish，<6 bearish。

### 1.6 Michael Burry — 借鉴模板

| 子分析 | 满分 | 加分项 |
|---|---|---|
| deep_value | 8 | EV/EBITDA <8 +3，<12 +2；PB <1 +3，<1.5 +2 |
| balance_sheet_stress | 6 | （反向）负债/权益 >2 警示 -3，>1 -1；利息覆盖 <2 -2 |
| contrarian_setup | 6 | 卖空比例 >20% +3；分析师评级分歧 +2；自由现金流持续 |
| sentiment_extreme | 5 | 看跌共识 <30% +2；极度负向新闻 +2 |

> Burry 也做空估值过高标的；信号里允许带"short"方向。

### 1.7 Mohnish Pabrai — 借鉴模板

| 子分析 | 满分 | 加分项 |
|---|---|---|
| heads_i_win | 8 | 下行空间 <30% +3；catalyst 临近 +2；管理层有 skin in game +2；FCF 为正 +1 |
| tails_i_dont_lose | 7 | 流动比率 >2 +2；D/E <0.5 +2；破产风险低 +2；行业护城河 +1 |
| business_simplicity | 5 | 单一清晰业务 +2；易于理解 +1 |

满分 20；>15 bullish，<8 bearish。

### 1.8 Nassim Taleb — **total max 50**（项目原代码）

```text
sub_total = tail_risk (8) + antifragility (10) + convexity (10) + fragility (8) + skin_in_game (4) + volatility_regime (6) + black_swan_sentinel (4)
signal    = bullish if sub_total >= 35 else bearish if sub_total <= 20 else neutral
```

| 子分析 | 满分 | 加分项 |
|---|---|---|
| `analyze_tail_risk` | 8 | 峰度高 (kurt >3) +2；正偏度（破产风险有限）+1；最大回撤 <20% +3；回撤频次 +2 |
| `analyze_antifragility` | 10 | cash/assets >25% +2；D/E <0.3 +2；op margin 多年稳定 +2；FCF 持续 +2；供应链分散 +2 |
| `analyze_convexity` | 10 | R&D/revenue >10% +3；正收益不对称 +2；现金期权（长期增长 runway）+2；FCF yield >5% +3 |
| `analyze_fragility` | 8 | **反向**：D/E >1 -3；interest coverage <3 -2；盈利波动 >50% -2；net margin <5% -1 |
| `analyze_skin_in_game` | 4 | insider 净买入 >0 +3，>0.5x 平均 +4 |
| `analyze_volatility_regime` | 6 | 年化波动 <25% +2；<40% +1；波动区间稳定 +3 |
| `analyze_black_swan_sentinel` | 4 | 新闻极负 +2；成交量异动 -2；价格错位 +2 |

**LLM 再读**：用 Taleb 风格（barbell / antifragility / via negativa / convexity）写 reasoning。

### 1.9 Peter Lynch — **total max 10**（项目原代码）

```text
total = growth * 0.30 + valuation * 0.25 + fundamentals * 0.20 + sentiment * 0.15 + insider_activity * 0.10
signal = bullish if total >= 7.5 else bearish if total <= 4.5 else neutral
```

| 子分析 | 满分 | 加分项 |
|---|---|---|
| `analyze_lynch_growth` | 10（scale from /6）| rev growth >25% +3，>10% +2，>2% +1；EPS growth 同分档 |
| `analyze_lynch_fundamentals` | 10 | D/E <0.5 +2，<1.0 +1；op margin >20% +2，>10% +1；FCF >0 +2 |
| `analyze_lynch_valuation` | 10（scale from /5）| PE <15 +2，<25 +1；PEG <1 +3，<2 +2，<3 +1 |
| `analyze_sentiment` | 10 | 负面新闻 <30% → 8；少量负面 → 6；>30% 负面 → 3 |
| `analyze_insider_activity` | 10 | 净买入 >70% → 8；30-70% → 6；<30% → 4 |

**LLM 再读**：用 Lynch 风格（PEG / ten-bagger / "if my kids love..."）写 reasoning。

### 1.10 Phil Fisher — 借鉴模板

| 子分析 | 满分 | 加分项 |
|---|---|---|
| scuttlebutt | 8 | R&D/revenue >10% +3；管理层长期持股 +2；产品迭代 +2 |
| margin_stability | 6 | gross margin 5 年稳定 +3；gross margin >50% +3 |
| sell_through | 6 | 应收周转 <30 天 +2；库存周转 >6 次 +2 |
| management | 5 | 长期 vision +3；不增发稀释 +2 |

满分 25；>18 bullish，<10 bearish。

### 1.11 Rakesh Jhunjhunwala — 借鉴模板

| 子分析 | 满分 | 加分项 |
|---|---|---|
| em_tailwind | 8 | 印度/新兴市场敞口 +3；国内消费主题 +3；汇率敏感低 +2 |
| skin_in_game | 6 | 大股东持股 >50% +3；管理层增持 +3 |
| secular_growth | 6 | 行业 5 年 CAGR >15% +3；TAM 扩张 +3 |

**注意**：A 股 / 港股适用，美股可降级。

### 1.12 Stanley Druckenmiller — 借鉴模板

| 子分析 | 满分 | 加分项 |
|---|---|---|
| macro_tailwind | 10 | 利率下行受益 +3；汇率受益 +2；商品周期上行 +3；财政刺激 +2 |
| earnings_leverage | 8 | 经营杠杆高 +3；固定成本占比 +2 |
| liquidity | 4 | 资金流入 +2；卖空比例低 +2 |

**数据源**：可能需要外部宏观数据（neodata macro indicator 兜底）。

### 1.13 Warren Buffett — **total max 27**（项目原代码）

```text
sub_total = fundamentals (10) + consistency (3) + moat (5) + management (2) + pricing_power (5) + book_value_growth (5) + owner_earnings + intrinsic_value
margin_of_safety = (intrinsic_value - current_price) / current_price
signal = bullish if fundamentals >= 0.7*10 AND margin_of_safety > 0
       = bearish if fundamentals <= 0.3*10 OR margin_of_safety < -0.3
       = neutral otherwise
```

| 子分析 | 满分 | 加分项 |
|---|---|---|
| `analyze_fundamentals` | 10 | ROE >15% +2；D/E <0.5 +2；op margin >15% +2；current ratio >1.5 +1 |
| `analyze_consistency` | 3 | 净利润逐期增长 +2；总增长 >50% +1 |
| `analyze_moat` | 5 | ROE >15% in 80%+ 时期 +2；op margin 5 年稳定 +1；asset turnover >1 +1；绩效稳定 +1 |
| `analyze_management_quality` | 2 | 股份回购 +1；分红记录 +1 |
| `analyze_owner_earnings` | 不评分 | = NI + D&A - maintenance capex - ΔWC |
| `analyze_intrinsic_value` | 不评分 | 3 阶段 DCF；discount rate 10%；保守 85% |
| `analyze_book_value_growth` | 5 | BVPS CAGR >10% +3，>5% +1 |
| `analyze_pricing_power` | 5 | gross margin 趋势 +3；gross margin >50% +2，>30% +1 |

**LLM 再读**：用 Buffett 风格（circle of competence / moat / margin of safety）写 reasoning。

### 1.1 Aswath Damodaran — 借鉴模板（不重做估值，价值在 storytelling）

| 子分析 | 满分 | 加分项 |
|---|---|---|
| story_quality | 6 | 增长故事清晰 +3；可量化 +2；可证伪 +1 |
| numbers_consistency | 5 | 历史预测误差 <10% +3，<20% +2 |
| model_choice | 4 | 用 DCF + comparables + DDM 三法交叉 +2 |
| intrinsic_value_gap | 5 | intrinsic/price >1.3 +3，>1.1 +2 |

满分 20；>14 bullish，<7 bearish。

### 1.3 Bill Ackman — 借鉴模板

| 子分析 | 满分 | 加分项 |
|---|---|---|
| business_quality | 8 | simple + predictable + FCF-generative + 品牌 + 定价权 |
| catalyst | 6 | activist angle + 管理层激励改善 + 资产剥离 |
| valuation | 6 | EV/EBITDA <10 + 资产低估 +3 |
| position_size | 5 | 大仓位可行性（流动性）|

满分 25；>18 bullish，<10 bearish。

### 1.4 Cathie Wood — 借鉴模板

| 子分析 | 满分 | 加分项 |
|---|---|---|
| disruptive_innovation | 10 | AI / 基因 / 储能 / 区块链 / 机器人 + 各 +2 |
| exponential_growth | 8 | 收入 5 年 CAGR >25% +5，>15% +3 |
| TAM_runway | 6 | TAM 5-10 年扩张 +3；渗透率 <50% +3 |
| R&D_intensity | 4 | R&D/revenue >15% +3，>10% +2 |
| short_term_loss_tolerance | 2 | 接受亏损换增长 +1 |

满分 30；>22 bullish，<12 bearish。

---

## §2 功能型 agent（6 个）

### 2.1 Technical Analyst — **纯计算，不调 LLM**

| 子策略 | 权重 | 触发 |
|---|---|---|
| trend_following (EMA 8/21/55 + ADX 14) | 0.25 | 8>21>55 bullish；ADX/100 = confidence |
| mean_reversion (50 日 z-score + Bollinger + RSI 14/28) | 0.20 | z<-2 且价在下轨附近 bullish |
| momentum (1/3/6 月 + 成交量确认) | 0.25 | 动量得分 >5% 且量>均线 bullish |
| volatility (21 日 HV vs 63 日均线) | 0.15 | vol_regime<0.8 且 z<-1 bullish |
| statistical_arbitrage (Hurst + skew + kurt) | 0.15 | Hurst<0.4 且正偏 bullish |

```text
final_score = Σ (signal_value * weight * confidence) / Σ(weight * confidence)
signal = bullish if final_score > 0.2 else bearish if < -0.2 else neutral
confidence = round(abs(final_score) * 100, 0)
```

> 不调 LLM。**这一项不能关闭**（technical_analyst 默认 always-on）。

### 2.2 Fundamentals Analyst — **总 4 维**

| 子分析 | bullish 阈值 | bearish 阈值 |
|---|---|---|
| profitability (3 项) | ≥2 项超阈值 → bullish | 0 项 → bearish |
| growth (3 项) | ≥2 项 >10% → bullish | 0 项 → bearish |
| financial_health (3 项) | ≥2 项超阈值 → bullish | 0 → bearish |
| price_ratios (3 项) | 0 项高估值 → bullish | ≥2 项高估 → bearish |

最终信号 = 多数票；confidence = max(bullish_count, bearish_count) / 4 * 100。

> 不调 LLM。

### 2.3 Growth Analyst — **借鉴模板**

| 子分析 | 满分 | 加分项 |
|---|---|---|
| revenue_cagr_3y | 10 | >25% +5，>15% +3，>8% +2 |
| earnings_cagr_3y | 10 | 同上 |
| fcf_cagr_3y | 10 | 同上 |
| peg_ratio | 10 | PEG<1 +5，<2 +3 |

满分 40；>28 bullish，<14 bearish。

### 2.4 News Sentiment Analyst — **简单计数**

```text
bullish_pct = count(bullish) / total
bearish_pct = count(bearish) / total
signal = bullish if bullish_pct > 0.6
       = bearish if bearish_pct > 0.6
       = neutral otherwise
confidence = |bullish_pct - bearish_pct| * 100
```

> 不调 LLM。直接用新闻标题情感计数（westock-data news 自带 sentiment 字段）。

### 2.5 Sentiment Analyst — **反向交易**

```text
bullish_ratio = count(bullish across other analysts) / total_other_agents
signal = bearish if bullish_ratio > 0.7 (contrarian over-crowded)
       = bullish if bullish_ratio < 0.3 (contrarian under-crowded)
       = neutral otherwise
```

> 输入其他 analyst 的信号，做反向。

### 2.6 Valuation Analyst — **DCF + Owner Earnings + EV/EBITDA + RIM**

| 方法 | 权重 | 模型 |
|---|---|---|
| dcf_enhanced | 0.35 | 多阶段（3 年高增长 + 4 年过渡 + terminal）；WACC 由 CAPM 算（rf=4.5%，MRP=6%，beta_proxy=1.0）；quality_factor = max(0.7, 1 - FCF_vol*0.5) |
| owner_earnings | 0.35 | 5 年 + terminal，required_return=15%，margin_of_safety=25% |
| ev_ebitda | 0.20 | 取历史中位倍数；implied = med_mult * EBITDA_now - net_debt |
| residual_income | 0.10 | EBO 模型；book_value + PV(RI) + terminal，20% safety |

```text
weighted_gap = Σ weight * (method_value - market_cap) / market_cap
signal = bullish if weighted_gap > 0.15
       = bearish if weighted_gap < -0.15
       = neutral otherwise
confidence = min(|weighted_gap| / 0.30 * 100, 100)
```

> 输出包含 4 个子方法的 gap + DCF 三情景（bear / base / bull）详情。

---

## §3 路由型（不可关闭）

### 3.1 Risk Manager — 见 `risk-portfolio.md §1`
### 3.2 Portfolio Manager — 见 `risk-portfolio.md §2`