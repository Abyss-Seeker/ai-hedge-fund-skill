# Risk Manager + Portfolio Manager 路由逻辑

> 这两个 agent 是流程的"必经节点"——用户不能关闭。
> 数据流：13 投资大师 + 6 功能 agent → risk_manager → portfolio_manager → final_orders。

---

## §1 Risk Manager

### 1.1 输入
- 所有 ticker 的行情序列（`get_prices`，用于算波动率 / 相关性）
- 当前组合（`portfolio`）：`cash / positions / margin_used / realized_gains`
- `start_date` / `end_date`

### 1.2 单 ticker 波动率计算（`calculate_volatility_metrics`）

```python
recent_returns = close.pct_change().tail(60)
daily_vol      = recent_returns.std()
annual_vol     = daily_vol * sqrt(252)
vol_percentile = (rolling_vol_30 <= daily_vol).mean() * 100   # 过去 30 日 rolling vol 中分位
```

> 数据点不足时回退 5% daily / 12.6% 年化波动。

### 1.3 仓位限额（`calculate_volatility_adjusted_limit`）

| 年化波动 | multiplier | 上限占组合比 |
|---|---|---|
| <15% | 1.25× | 25% |
| 15% – 30% | 1.0× → 0.75× 线性 | 20% → 15% |
| 30% – 50% | 0.75× → 0.5× 线性 | 15% → 10% |
| >50% | 0.5× | 10% |

base = 20%。最终 limit_pct = base × multiplier，clamp [5%, 25%]。

### 1.4 相关性调整（`calculate_correlation_multiplier`）

取该 ticker 与所有当前 active 仓位的平均相关系数（来自 60 日收益率的相关系数矩阵）：

| avg_correlation | multiplier |
|---|---|
| ≥ 0.80 | 0.70 |
| 0.60 – 0.80 | 0.85 |
| 0.40 – 0.60 | 1.00 |
| 0.20 – 0.40 | 1.05 |
| < 0.20 | 1.10 |

> 如果 active position 为空，则与所有 ticker 相关性取平均。

### 1.5 组合限额

```python
position_limit = total_portfolio_value * vol_limit_pct * corr_multiplier
remaining_position_limit = position_limit - current_position_value
max_position_size = min(remaining_position_limit, available_cash)
```

### 1.6 输出（每个 ticker）

```json
{
  "remaining_position_limit": float,   // 剩余可建仓金额（美元 / 本位币）
  "current_price": float,
  "volatility_metrics": {
    "daily_volatility": float,
    "annualized_volatility": float,
    "volatility_percentile": float,
    "data_points": int
  },
  "correlation_metrics": {
    "avg_correlation_with_active": float | null,
    "max_correlation_with_active": float | null,
    "top_correlated_tickers": [{"ticker": str, "correlation": float}, ...]
  },
  "reasoning": {
    "portfolio_value": float,
    "current_position_value": float,
    "base_position_limit_pct": float,
    "correlation_multiplier": float,
    "combined_position_limit_pct": float,
    "position_limit": float,
    "remaining_limit": float,
    "available_cash": float,
    "risk_adjustment": str
  }
}
```

---

## §2 Portfolio Manager

### 2.1 输入
- `analyst_signals`：所有 agent 输出的 `{ticker: {signal, confidence}}`
- `risk_data`（来自 risk_manager）：`remaining_position_limit` + `current_price`
- `portfolio`：现金 + 持仓 + 保证金
- `margin_requirement`：默认 0.5

### 2.2 allowed_actions 计算（`compute_allowed_actions`，纯规则）

```python
def allowed_for(t):
    actions = {"buy": 0, "sell": 0, "short": 0, "cover": 0, "hold": 0}
    # sell: 已有 long 仓位即可
    if long_shares > 0:
        actions["sell"] = long_shares
    # buy: cash > 0 且 price > 0 且 max_qty (from risk) 允许
    if cash > 0 and price > 0:
        max_buy_cash = cash // price
        max_buy = min(max_qty, max_buy_cash)
        if max_buy > 0:
            actions["buy"] = max_buy
    # cover: 已有 short 仓位即可
    if short_shares > 0:
        actions["cover"] = short_shares
    # short: 有 max_qty 且保证金允许
    if price > 0 and max_qty > 0:
        available_margin = max(0, equity / margin_requirement - margin_used)
        max_short = min(max_qty, available_margin // price)
        if max_short > 0:
            actions["short"] = max_short
    # hold 永远合法
    actions["hold"] = 0
    # prune 0 capacity 项（保留 hold）
    return actions
```

### 2.3 纯 hold 短路

如果某 ticker 的 allowed_actions 只有 `"hold"` 一个键，**直接**预填 `PortfolioDecision(action="hold", quantity=0, confidence=100, reasoning="No valid trade available")`，**不送 LLM**，省 token。

### 2.4 送 LLM 的内容（仅对非纯 hold 的 ticker）

```text
system:
  You are a portfolio manager.
  Inputs per ticker: analyst signals and allowed actions with max qty (already validated).
  Pick one allowed action per ticker and a quantity ≤ the max.
  Keep reasoning very concise (max 100 chars). No cash or margin math. Return JSON only.

human:
  Signals: {signals_by_ticker}
  Allowed: {allowed_actions}
  
  Format:
  {
    "decisions": {
      "TICKER": {"action": "...", "quantity": int, "confidence": int, "reasoning": "..."}
    }
  }
```

> LLM 不做金额 / 保证金数学，全部由 `compute_allowed_actions` 算好；LLM 只挑 action + 填 quantity。

### 2.5 最终输出

```json
{
  "decisions": {
    "AAPL": {"action": "buy", "quantity": 50, "confidence": 78, "reasoning": "5/7 analysts bullish, low vol"},
    "MSFT": {"action": "hold", "quantity": 0, "confidence": 0, "reasoning": "default"},
    "TSLA": {"action": "short", "quantity": 10, "confidence": 65, "reasoning": "valuation extreme"}
  }
}
```

`action` ∈ {`buy`, `sell`, `short`, `cover`, `hold`}。

### 2.6 失败兜底

LLM 调不通时所有未预填的 ticker 默认 `{action: "hold", quantity: 0, confidence: 0, reasoning: "default"}`。

---

## §3 Graph 流程总图（复现原 main.py）

```
                ┌──────────────────────────────────┐
                │     用户选定 selected_analysts    │
                │  （默认全部；可手动 subset）      │
                └────────────────┬─────────────────┘
                                 ▼
                        ┌───────────────┐
                        │   start_node  │
                        └───────┬───────┘
            ┌────┬────┬────┬────┼────┬────┬────┬────┬────┐
            ▼    ▼    ▼    ▼    ▼    ▼    ▼    ▼    ▼    ▼
        [agent_1] [agent_2] ... [agent_N]  (并行跑)
            └────┴────┴────┴────┼────┴────┴────┴────┴────┘
                                 ▼
                      ┌────────────────────┐
                      │  risk_manager       │  ← 算仓位限额
                      └────────┬───────────┘
                               ▼
                      ┌────────────────────┐
                      │  portfolio_manager  │  ← 决策下单
                      └────────┬───────────┘
                               ▼
                          END (输出)
```

> 每个 agent 是独立 LangGraph node；数据通过 `state["data"]["analyst_signals"]` 累积；
> `merge_dicts` reducer 把每个 agent 的 `{ticker: {...}}` 合并到同一个 dict 里。

---

## §4 用户决策点（必须在 SKILL.md / 主执行器复现）

1. **选择哪些 ticker**（必填，逗号分隔）。例：`AAPL,MSFT,NVDA,0700.HK,600519.SH`
2. **选择哪些 analyst agent**（可选，默认全选）。多选界面：
   - 13 投资大师（13 选 N）
   - 6 功能 agent（建议至少保留 technical + fundamentals）
3. **日期范围**（可选，默认最近 3 个月）
4. **初始资金 + 初始持仓**（可选，默认 100 万现金 + 空仓）
5. **保证金比例**（可选，默认 0.5）
6. **是否显示 reasoning**（默认 off，省 token）
7. **风险限额偏好**（低 / 中 / 高，影响 vol 调整系数；默认中）