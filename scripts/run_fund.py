"""run_fund.py — AI 对冲基金主执行器（复现 virattt/ai-hedge-fund 工作流）

用法:
    python run_fund.py --ticker AAPL,MSFT,NVDA --analysts warren_buffett,ben_graham,peter_lynch,nassim_taleb,fundamentals,technicals,valuation --start 2026-04-01 --end 2026-07-24 --initial-cash 1000000 --show-reasoning

如果不传 --analysts，跑全部 19 个 agent。

输出:
    1. 控制台：每个 ticker 的所有 agent 信号 + risk 数据 + 最终下单
    2. JSON 文件：results/<run_id>.json 详细结果

依赖:
    - data_fetcher.py（同目录）
    - westock-data（已安装）
    - Python 3.10+（用 match-case / type hint）
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# 让脚本能 import data_fetcher（同目录）
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from data_fetcher import (
    get_prices,
    get_financial_metrics,
    search_line_items,
    get_company_news,
    get_insider_trades,
    get_market_cap,
    get_company_facts,
    ticker_to_westock,
)

# ---------------------------------------------------------------------------
# 19 个 analyst 配置（来自原项目 src/utils/analysts.py）
# ---------------------------------------------------------------------------

ANALYSTS = {
    # === 投资大师（13 个） ===
    "aswath_damodaran": {"display_name": "Aswath Damodaran", "type": "analyst"},
    "ben_graham": {"display_name": "Ben Graham", "type": "analyst"},
    "bill_ackman": {"display_name": "Bill Ackman", "type": "analyst"},
    "cathie_wood": {"display_name": "Cathie Wood", "type": "analyst"},
    "charlie_munger": {"display_name": "Charlie Munger", "type": "analyst"},
    "michael_burry": {"display_name": "Michael Burry", "type": "analyst"},
    "mohnish_pabrai": {"display_name": "Mohnish Pabrai", "type": "analyst"},
    "nassim_taleb": {"display_name": "Nassim Taleb", "type": "analyst"},
    "peter_lynch": {"display_name": "Peter Lynch", "type": "analyst"},
    "phil_fisher": {"display_name": "Phil Fisher", "type": "analyst"},
    "rakesh_jhunjhunwala": {"display_name": "Rakesh Jhunjhunwala", "type": "analyst"},
    "stanley_druckenmiller": {"display_name": "Stanley Druckenmiller", "type": "analyst"},
    "warren_buffett": {"display_name": "Warren Buffett", "type": "analyst"},
    # === 功能型（6 个） ===
    "technical_analyst": {"display_name": "Technical Analyst", "type": "analyst"},
    "fundamentals_analyst": {"display_name": "Fundamentals Analyst", "type": "analyst"},
    "growth_analyst": {"display_name": "Growth Analyst", "type": "analyst"},
    "news_sentiment_analyst": {"display_name": "News Sentiment Analyst", "type": "analyst"},
    "sentiment_analyst": {"display_name": "Sentiment Analyst", "type": "analyst"},
    "valuation_analyst": {"display_name": "Valuation Analyst", "type": "analyst"},
}

DEFAULT_ANALYSTS = list(ANALYSTS.keys())


# ---------------------------------------------------------------------------
# 19 个 Agent 的纯规则实现（不调 LLM）
# ---------------------------------------------------------------------------

def _safe_metrics(metrics: list[dict]) -> dict | None:
    return metrics[0] if metrics else None


def _signal(bullish_score: float, max_score: float, bullish_thr: float = 0.6, bearish_thr: float = 0.33):
    """根据得分比例返回 signal + confidence.

    默认 bearish_thr=0.33（原 0.4 太敏感，A 股数据不全时 3/9=0.33 刚好被卡成 bearish）。
    """
    if max_score <= 0:
        return "neutral", 0
    ratio = bullish_score / max_score
    if ratio >= bullish_thr:
        return "bullish", round(min(ratio * 100, 95))
    if ratio <= bearish_thr:
        return "bearish", round(min((1 - ratio) * 100, 95))
    return "neutral", round(50 - abs(ratio - 0.5) * 100)


# ============== 投资大师 ==============

def warren_buffett_agent(ticker: str, metrics: dict, line_items: list[dict], market_cap: float) -> dict:
    """Buffett 7 维评分：fundamentals + consistency + moat + mgmt + owner_earnings
    + intrinsic_value + book_growth + pricing_power（满分 27）."""
    score = 0
    max_score = 27
    details = {}

    if not metrics:
        return {"signal": "neutral", "confidence": 0, "reasoning": "no data"}

    # 1. fundamentals (max 10)
    fund = 0
    if metrics.get("return_on_equity") and metrics["return_on_equity"] > 0.15:
        fund += 2
    if metrics.get("debt_to_equity") and metrics["debt_to_equity"] < 0.5:
        fund += 2
    if metrics.get("operating_margin") and metrics["operating_margin"] > 0.15:
        fund += 2
    if metrics.get("current_ratio") and metrics["current_ratio"] > 1.5:
        fund += 1
    if metrics.get("gross_margin") and metrics["gross_margin"] > 0.5:
        fund += 1
    if metrics.get("return_on_assets") and metrics["return_on_assets"] > 0.1:
        fund += 2
    details["fundamentals"] = fund
    score += fund

    # 2. consistency (max 3)
    if len(line_items) >= 2:
        eps_seq = [_try_float(li.get("earnings_per_share")) for li in line_items]
        eps_seq = [e for e in eps_seq if e is not None]
        if len(eps_seq) >= 2:
            increasing = all(eps_seq[i] >= eps_seq[i + 1] * 0.9 for i in range(len(eps_seq) - 1))
            if increasing:
                score += 3
                details["consistency"] = 3
            else:
                details["consistency"] = 0

    # 3. moat (max 5)
    moat = 0
    if metrics.get("return_on_equity") and metrics["return_on_equity"] > 0.15:
        moat += 2
    if metrics.get("gross_margin") and metrics["gross_margin"] > 0.4:
        moat += 2
    if metrics.get("return_on_assets") and metrics["return_on_assets"] > 0.1:
        moat += 1
    details["moat"] = moat
    score += moat

    # 4. management_quality (max 2)
    score += 1  # placeholder: 都给 1 分
    details["management"] = 1

    # 5. owner_earnings (informational)
    if line_items and line_items[0].get("net_income") is not None:
        details["net_income"] = line_items[0]["net_income"]

    # 6. intrinsic_value: 3 阶段 DCF 简化版
    intrinsic_value = 0
    if line_items and line_items[0].get("free_cash_flow"):
        fcf0 = _try_float(line_items[0]["free_cash_flow"]) or 0
        growth = metrics.get("revenue_growth") or 0.05
        growth = min(max(growth, 0), 0.08)
        wacc = 0.10
        terminal_growth = 0.025
        # 5y growth + terminal
        pv = 0
        for yr in range(1, 6):
            pv += fcf0 * (1 + growth) ** yr / (1 + wacc) ** yr
        term = fcf0 * (1 + growth) ** 5 * (1 + terminal_growth) / (wacc - terminal_growth)
        pv_term = term / (1 + wacc) ** 5
        intrinsic_value = (pv + pv_term) * 0.85  # 85% 折扣
        details["intrinsic_value"] = round(intrinsic_value, 2)

    # 7. book_value_growth (max 5)
    bvg = metrics.get("book_value_growth")
    if bvg is not None:
        if bvg > 0.10:
            score += 3
        elif bvg > 0.05:
            score += 2
        elif bvg > 0:
            score += 1
        details["book_growth"] = bvg

    # 8. pricing_power (max 5)
    pp = 0
    gm = metrics.get("gross_margin")
    if gm is not None:
        if gm > 0.5:
            pp += 2
        elif gm > 0.3:
            pp += 1
    score += pp
    details["pricing_power"] = pp

    # margin_of_safety
    current_price = metrics.get("price_to_book_ratio", 0) * metrics.get("book_value_per_share", 0) if metrics.get("book_value_per_share") else 0
    if market_cap and metrics.get("total_shares") and intrinsic_value:
        current_price = market_cap / metrics["total_shares"]
        margin_of_safety = (intrinsic_value - current_price) / current_price if current_price else 0
        details["margin_of_safety"] = round(margin_of_safety, 4)
    else:
        margin_of_safety = 0

    # 决策
    if score >= 18 and margin_of_safety > 0:
        signal = "bullish"
        confidence = min(70 + score, 95)
    elif score <= 9 or margin_of_safety < -0.4:
        signal = "bearish"
        confidence = min(60 + (27 - score), 95)
    else:
        signal = "neutral"
        confidence = 50

    details["total_score"] = score
    details["max_score"] = max_score
    return {"signal": signal, "confidence": confidence, "reasoning": json.dumps(details, ensure_ascii=False)[:120]}


def ben_graham_agent(ticker: str, metrics: dict, line_items: list[dict], market_cap: float) -> dict:
    """Graham 3 维评分（满分 15）：earnings_stability + financial_strength + graham_valuation."""
    score = 0
    details = []

    if not line_items:
        return {"signal": "neutral", "confidence": 0, "reasoning": "no line items"}

    # 1. earnings_stability (max 4)
    eps_seq = [_try_float(li.get("earnings_per_share")) for li in line_items]
    eps_seq = [e for e in eps_seq if e is not None]
    if len(eps_seq) >= 2:
        positive = sum(1 for e in eps_seq if e > 0)
        if positive == len(eps_seq):
            score += 3
            details.append("EPS 全正")
        elif positive >= len(eps_seq) * 0.8:
            score += 2
        if eps_seq[0] > eps_seq[-1]:
            score += 1
            details.append("EPS 增长")

    # 2. financial_strength (max 5)
    li0 = line_items[0]
    ca = _try_float(li0.get("current_assets"))
    cl = _try_float(li0.get("current_liabilities"))
    ta = _try_float(li0.get("total_assets"))
    tl = _try_float(li0.get("total_liabilities"))
    if ca and cl and cl > 0:
        cr = ca / cl
        if cr >= 2:
            score += 2
        elif cr >= 1.5:
            score += 1
    if ta and tl and ta > 0:
        dr = tl / ta
        if dr < 0.5:
            score += 2
        elif dr < 0.8:
            score += 1
    score += 1  # 默认给 1 分（分红项 placeholder）

    # 3. graham_valuation (max 7)
    eps = _try_float(li0.get("earnings_per_share")) or 0
    bvps = _try_float(li0.get("book_value_per_share")) or 0
    if ca and tl:
        ncav = ca - tl
        if ncav > 0 and market_cap and market_cap > 0:
            if ncav > market_cap:
                score += 4
                details.append("NCAV > market_cap")
            elif ncav / market_cap >= 0.67:
                score += 2
    if eps > 0 and bvps > 0:
        graham_num = math.sqrt(22.5 * eps * bvps)
        if market_cap and line_items[0].get("outstanding_shares"):
            shares = _try_float(line_items[0]["outstanding_shares"])
            if shares and shares > 0:
                price = market_cap / shares
                if price > 0:
                    mos = (graham_num - price) / price
                    if mos > 0.5:
                        score += 3
                    elif mos > 0.2:
                        score += 1

    max_score = 15
    sig, conf = _signal(score, max_score, bullish_thr=0.7, bearish_thr=0.3)
    return {"signal": sig, "confidence": conf,
            "reasoning": f"score {score}/{max_score} {'; '.join(details[:3])}"[:120]}


def peter_lynch_agent(ticker: str, metrics: dict, line_items: list[dict], market_cap: float, news: list[dict]) -> dict:
    """Lynch 5 维加权（满分 10）：growth 30% + valuation 25% + fundamentals 20% + sentiment 15% + insider 10%."""
    if not line_items:
        return {"signal": "neutral", "confidence": 0, "reasoning": "no data"}

    scores = {}

    # 1. growth (max 10)
    rev_seq = [_try_float(li.get("revenue")) for li in line_items]
    rev_seq = [v for v in rev_seq if v is not None]
    eps_seq = [_try_float(li.get("earnings_per_share")) for li in line_items]
    eps_seq = [v for v in eps_seq if v is not None]
    raw = 0
    if len(rev_seq) >= 2 and rev_seq[-1] > 0:
        rg = (rev_seq[0] - rev_seq[-1]) / abs(rev_seq[-1])
        if rg > 0.25: raw += 3
        elif rg > 0.10: raw += 2
        elif rg > 0.02: raw += 1
    if len(eps_seq) >= 2 and abs(eps_seq[-1]) > 1e-9:
        eg = (eps_seq[0] - eps_seq[-1]) / abs(eps_seq[-1])
        if eg > 0.25: raw += 3
        elif eg > 0.10: raw += 2
        elif eg > 0.02: raw += 1
    scores["growth"] = min((raw / 6) * 10, 10)

    # 2. valuation (PEG)
    raw = 0
    eps0 = _try_float(line_items[0].get("earnings_per_share"))
    if eps0 and eps0 > 0 and market_cap and len(line_items) > 1:
        ni0 = _try_float(line_items[0].get("net_income")) or 0
        if ni0 > 0:
            pe = market_cap / ni0
            if pe < 15: raw += 2
            elif pe < 25: raw += 1
    if len(eps_seq) >= 2 and eps_seq[-1] > 0 and eps_seq[0] > 0:
        years = len(eps_seq) - 1
        cagr = (eps_seq[0] / eps_seq[-1]) ** (1 / years) - 1
        if pe := (market_cap / (_try_float(line_items[0].get("net_income")) or 1)) and cagr > 0:
            peg = pe / (cagr * 100)
            if peg < 1: raw += 3
            elif peg < 2: raw += 2
            elif peg < 3: raw += 1
    scores["valuation"] = min((raw / 5) * 10, 10)

    # 3. fundamentals
    raw = 0
    m = metrics or {}
    if m.get("debt_to_equity") is not None:
        if m["debt_to_equity"] < 0.5: raw += 2
        elif m["debt_to_equity"] < 1.0: raw += 1
    if m.get("operating_margin") is not None:
        if m["operating_margin"] > 0.20: raw += 2
        elif m["operating_margin"] > 0.10: raw += 1
    if m.get("free_cash_flow_per_share") and m.get("earnings_per_share"):
        if m["free_cash_flow_per_share"] > 0:
            raw += 2
    scores["fundamentals"] = min((raw / 6) * 10, 10)

    # 4. sentiment
    if news:
        neg = sum(1 for n in news if n.get("sentiment") == "bearish")
        ratio = neg / len(news)
        if ratio > 0.3: scores["sentiment"] = 3
        elif ratio > 0: scores["sentiment"] = 6
        else: scores["sentiment"] = 8
    else:
        scores["sentiment"] = 5

    # 5. insider (placeholder)
    scores["insider"] = 5

    total = (scores["growth"] * 0.30 + scores["valuation"] * 0.25 +
             scores["fundamentals"] * 0.20 + scores["sentiment"] * 0.15 +
             scores["insider"] * 0.10)
    if total >= 7.5:
        return {"signal": "bullish", "confidence": min(round(total * 10), 90), "reasoning": f"total {total:.1f}/10 PEG focus"[:120]}
    if total <= 4.5:
        return {"signal": "bearish", "confidence": min(round((10 - total) * 10), 90), "reasoning": f"total {total:.1f}/10"[:120]}
    return {"signal": "neutral", "confidence": 50, "reasoning": f"total {total:.1f}/10"}


def nassim_taleb_agent(ticker: str, metrics: dict, line_items: list[dict], market_cap: float, prices: list[dict]) -> dict:
    """Taleb 7 维（满分 50）。"""
    score = 0
    details = {}

    m = metrics or {}

    # 1. tail_risk (max 8)
    if prices and len(prices) >= 30:
        rets = [prices[i]["close"] / prices[i - 1]["close"] - 1 for i in range(1, len(prices)) if prices[i - 1]["close"]]
        if rets:
            sorted_rets = sorted(rets)
            tail5 = sorted_rets[:max(1, len(sorted_rets) // 20)]
            tail_ratio = abs(sum(tail5) / len(tail5)) if tail5 else 0
            if tail_ratio < 0.03:
                score += 3
            elif tail_ratio < 0.05:
                score += 1
            # max drawdown
            peak = max(prices, key=lambda p: p["close"])["close"]
            trough = min(prices, key=lambda p: p["close"])["close"]
            dd = (peak - trough) / peak if peak > 0 else 0
            if dd < 0.3:
                score += 2
            details["tail_ratio"] = tail_ratio

    # 2. antifragility (max 10)
    if m.get("current_ratio") and m["current_ratio"] > 1.5: score += 2
    if m.get("debt_to_equity") is not None and m["debt_to_equity"] < 0.3: score += 2
    if m.get("operating_margin") and m["operating_margin"] > 0.15: score += 2
    if m.get("free_cash_flow_per_share") and m["free_cash_flow_per_share"] > 0: score += 2

    # 3. convexity (max 10)
    if m.get("revenue_growth") and m["revenue_growth"] > 0.20: score += 3
    if m.get("gross_margin") and m["gross_margin"] > 0.5: score += 2

    # 4. fragility (max 8) — 反向
    if m.get("debt_to_equity") and m["debt_to_equity"] > 1: score -= 3
    if m.get("operating_margin") is not None and m["operating_margin"] < 0.05: score -= 1

    # 5. skin_in_game (max 4)
    insider = get_insider_trades(ticker, "2026-07-24") or {}
    if insider.get("insider_events"):
        score += 2

    # 6. volatility_regime (max 6)
    if prices and len(prices) >= 60:
        rets = [prices[i]["close"] / prices[i - 1]["close"] - 1 for i in range(1, len(prices))]
        vol = statistics.stdev(rets) * math.sqrt(252) if len(rets) > 1 else 0.25
        if vol < 0.25: score += 2
        elif vol < 0.4: score += 1

    # 7. black_swan_sentinel (max 4)
    score += 1

    if score >= 35:
        return {"signal": "bullish", "confidence": min(70 + score - 35, 95), "reasoning": f"antifragile {score}/50"[:120]}
    if score <= 20:
        return {"signal": "bearish", "confidence": min(70 + 20 - score, 95), "reasoning": f"fragile {score}/50"[:120]}
    return {"signal": "neutral", "confidence": 50, "reasoning": f"score {score}/50"}


def fundamentals_agent(ticker: str, metrics: dict) -> dict:
    """Fundamentals 4 维多数票。"""
    if not metrics:
        return {"signal": "neutral", "confidence": 0, "reasoning": "no data"}

    m = metrics
    signals = []

    # profitability
    profitable_hits = 0
    if m.get("return_on_equity") and m["return_on_equity"] > 0.15: profitable_hits += 1
    if m.get("net_margin") and m["net_margin"] > 0.20: profitable_hits += 1
    if m.get("operating_margin") and m["operating_margin"] > 0.15: profitable_hits += 1
    signals.append("bullish" if profitable_hits >= 2 else "bearish" if profitable_hits == 0 else "neutral")

    # growth
    growth_hits = 0
    if m.get("revenue_growth") and m["revenue_growth"] > 0.10: growth_hits += 1
    if m.get("earnings_growth") and m["earnings_growth"] > 0.10: growth_hits += 1
    if m.get("book_value_growth") and m["book_value_growth"] > 0.10: growth_hits += 1
    signals.append("bullish" if growth_hits >= 2 else "bearish" if growth_hits == 0 else "neutral")

    # health
    health_hits = 0
    if m.get("current_ratio") and m["current_ratio"] > 1.5: health_hits += 1
    if m.get("debt_to_equity") and m["debt_to_equity"] < 0.5: health_hits += 1
    if (m.get("free_cash_flow_per_share") and m.get("earnings_per_share") and
            m["free_cash_flow_per_share"] > m["earnings_per_share"] * 0.8):
        health_hits += 1
    signals.append("bullish" if health_hits >= 2 else "bearish" if health_hits == 0 else "neutral")

    # price ratios (反向)
    pe = m.get("price_to_earnings_ratio")
    pb = m.get("price_to_book_ratio")
    ps = m.get("price_to_sales_ratio")
    high_pe = pe is not None and pe > 25
    high_pb = pb is not None and pb > 3
    high_ps = ps is not None and ps > 5
    overcount = sum([high_pe, high_pb, high_ps])
    if overcount >= 2:
        signals.append("bearish")
    elif overcount == 0:
        signals.append("bullish")
    else:
        signals.append("neutral")

    bullish_count = signals.count("bullish")
    bearish_count = signals.count("bearish")
    if bullish_count > bearish_count:
        sig = "bullish"
        conf = round(bullish_count / 4 * 100)
    elif bearish_count > bullish_count:
        sig = "bearish"
        conf = round(bearish_count / 4 * 100)
    else:
        sig = "neutral"
        conf = 50
    return {"signal": sig, "confidence": conf, "reasoning": f"{bullish_count}B/{bearish_count}Be/{4 - bullish_count - bearish_count}N"}


def technicals_agent(ticker: str, prices: list[dict]) -> dict:
    """纯规则技术分析：5 子策略加权。"""
    if len(prices) < 60:
        return {"signal": "neutral", "confidence": 0, "reasoning": f"only {len(prices)} days"}

    closes = [p["close"] for p in prices]
    sma20 = sum(closes[-20:]) / 20
    sma50 = sum(closes[-50:]) / 50
    sma200 = sum(closes[-min(200, len(closes)):]) / min(200, len(closes))

    # 1. trend
    if closes[-1] > sma20 > sma50:
        trend = ("bullish", 0.7)
    elif closes[-1] < sma20 < sma50:
        trend = ("bearish", 0.7)
    else:
        trend = ("neutral", 0.5)

    # 2. momentum (20 日)
    mom_20d = (closes[-1] - closes[-21]) / closes[-21] if closes[-21] > 0 else 0
    momentum = ("bullish", min(abs(mom_20d) * 5, 1.0)) if mom_20d > 0.05 else ("bearish", min(abs(mom_20d) * 5, 1.0)) if mom_20d < -0.05 else ("neutral", 0.5)

    # 3. mean_reversion (20 日 z-score)
    recent = closes[-20:]
    mean = sum(recent) / 20
    std = statistics.stdev(recent) if len(recent) > 1 else 1
    z = (closes[-1] - mean) / std if std > 0 else 0
    if z < -1.5:
        mr = ("bullish", min(abs(z) / 3, 1.0))
    elif z > 1.5:
        mr = ("bearish", min(abs(z) / 3, 1.0))
    else:
        mr = ("neutral", 0.5)

    # 4. volatility
    rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    vol = statistics.stdev(rets) * math.sqrt(252) if len(rets) > 1 else 0.25
    vol_signal = "neutral"
    if vol < 0.20: vol_signal = "bullish"
    elif vol > 0.50: vol_signal = "bearish"

    # 5. stat_arb (placeholder)
    sa = ("neutral", 0.5)

    # 加权
    weights = {"trend": 0.30, "momentum": 0.30, "mr": 0.20, "vol": 0.10, "sa": 0.10}
    score = 0
    for sig_pair, w in [(trend, weights["trend"]), (momentum, weights["momentum"]),
                         (mr, weights["mr"]), (sa, weights["sa"])]:
        s, c = sig_pair
        score += ({"bullish": 1, "neutral": 0, "bearish": -1}[s] * w * c)
    # vol 是单独判断
    if vol_signal == "bearish": score -= 0.3

    if score > 0.15:
        sig = "bullish"
    elif score < -0.15:
        sig = "bearish"
    else:
        sig = "neutral"
    return {"signal": sig, "confidence": min(round(abs(score) * 100), 95),
            "reasoning": f"trend={trend[0]} mom={momentum[0]} mr={mr[0]} vol={vol:.1%}"}


def valuation_agent(ticker: str, metrics: dict, line_items: list[dict], market_cap: float) -> dict:
    """简化版 Valuation：基于 PE / PB / PS + 行业经验阈值的相对估值 + 简化 DCF。

    注意：完整 DCF / Owner Earnings / RIM 多模型估值最好让 LLM 跑。
    """
    if not metrics or not market_cap:
        return {"signal": "neutral", "confidence": 0, "reasoning": "no data"}

    m = metrics

    # 1. PE 估值（PE < 15 偏便宜，> 30 偏贵）
    pe_score = 0
    pe = m.get("price_to_earnings_ratio")
    if pe and 0 < pe < 15:
        pe_score = 1
    elif pe and pe > 30:
        pe_score = -1

    # 2. PB 估值
    pb_score = 0
    pb = m.get("price_to_book_ratio")
    if pb and 0 < pb < 1.5:
        pb_score = 1
    elif pb and pb > 5:
        pb_score = -1

    # 3. 简化 DCF：用 TTM 净利做 5 年增长 + terminal，per-share
    dcf_per_share = 0
    eps = _try_float(line_items[0].get("earnings_per_share")) if line_items else None
    growth = m.get("revenue_growth") or 0.05
    growth = min(max(growth, 0), 0.08)  # 保守 cap 8%
    if eps and eps > 0:
        wacc = 0.10
        term_g = 0.025
        pv = 0
        for yr in range(1, 6):
            pv += eps * (1 + growth) ** yr / (1 + wacc) ** yr
        term = eps * (1 + growth) ** 5 * (1 + term_g) / (wacc - term_g)
        pv_term = term / (1 + wacc) ** 5
        dcf_per_share = pv + pv_term

    # current price per share
    shares = (metrics.get("_raw") or {}).get("TotalShares") if False else None  # TotalShares 不直接存
    # 用 market_cap / dcf 总值比
    # 简化：per-share gap = (DCF + PE/PB 综合) vs current_price
    current_price = m.get("_current_price")  # 注：这个字段没注入
    # 退而求其次：用 PB × BVPS 估算 current_price
    bvps = _try_float(line_items[0].get("book_value_per_share")) if line_items else None
    if pb and bvps:
        current_price = pb * bvps

    if current_price and current_price > 0 and dcf_per_share > 0:
        dcf_gap = (dcf_per_share - current_price) / current_price
    else:
        dcf_gap = 0

    # 合并得分：pe_score + pb_score + dcf_gap
    score = pe_score + pb_score + (1 if dcf_gap > 0.15 else -1 if dcf_gap < -0.15 else 0)

    if score >= 2:
        sig = "bullish"
        conf = min(60 + score * 10, 90)
    elif score <= -2:
        sig = "bearish"
        conf = min(60 - score * 10, 90)
    else:
        sig = "neutral"
        conf = 50
    return {"signal": sig, "confidence": conf,
            "reasoning": f"PE={pe:.1f} PB={pb:.1f} DCF_gap={dcf_gap:.1%}"[:120]}


def news_sentiment_agent(ticker: str, news: list[dict]) -> dict:
    """简单情感计数。"""
    if not news:
        return {"signal": "neutral", "confidence": 0, "reasoning": "no news"}
    bullish = sum(1 for n in news if n.get("sentiment") == "bullish")
    bearish = sum(1 for n in news if n.get("sentiment") == "bearish")
    total = len(news)
    bp = bullish / total
    bnp = bearish / total
    if bp > 0.6:
        sig, conf = "bullish", round((bp - bnp) * 100)
    elif bnp > 0.6:
        sig, conf = "bearish", round((bnp - bp) * 100)
    else:
        sig, conf = "neutral", round((1 - abs(bp - bnp)) * 50)
    return {"signal": sig, "confidence": conf, "reasoning": f"{bullish}B/{bearish}Be/{total - bullish - bearish}N"}


def sentiment_agent(ticker: str, other_signals: dict) -> dict:
    """反向：其他 agent 共识过高时反向。"""
    sigs = [v.get("signal") for v in other_signals.values() if isinstance(v, dict) and v.get("signal")]
    if not sigs:
        return {"signal": "neutral", "confidence": 0, "reasoning": "no other signals"}
    bullish_ratio = sigs.count("bullish") / len(sigs)
    bearish_ratio = sigs.count("bearish") / len(sigs)
    if bullish_ratio > 0.7:
        return {"signal": "bearish", "confidence": 70, "reasoning": f"contrarian: {bullish_ratio:.0%} bullish"}
    if bearish_ratio > 0.7:
        return {"signal": "bullish", "confidence": 70, "reasoning": f"contrarian: {bearish_ratio:.0%} bearish"}
    return {"signal": "neutral", "confidence": 50, "reasoning": "mixed"}


def growth_agent(ticker: str, metrics: dict, line_items: list[dict]) -> dict:
    rev_seq = [_try_float(li.get("revenue")) for li in line_items]
    rev_seq = [v for v in rev_seq if v is not None]
    eps_seq = [_try_float(li.get("earnings_per_share")) for li in line_items]
    eps_seq = [v for v in eps_seq if v is not None]

    rev_cagr = _cagr(rev_seq)
    eps_cagr = _cagr(eps_seq)

    score = 0
    for c in [rev_cagr, eps_cagr]:
        if c and c > 0.25: score += 5
        elif c and c > 0.15: score += 3
        elif c and c > 0.08: score += 2

    pe = (metrics or {}).get("price_to_earnings_ratio")
    eps_g = (metrics or {}).get("earnings_growth")
    if pe and eps_g and eps_g > 0:
        peg = pe / (eps_g * 100)
        if peg < 1: score += 5
        elif peg < 2: score += 3

    if score >= 12:
        return {"signal": "bullish", "confidence": min(60 + score, 95), "reasoning": f"score {score} CAGR high"[:120]}
    if score <= 6:
        return {"signal": "bearish", "confidence": min(60 + (14 - score), 95), "reasoning": f"score {score}"}
    return {"signal": "neutral", "confidence": 50, "reasoning": f"score {score}"}


def generic_moat_agent(ticker: str, metrics: dict) -> dict:
    """通用 moat agent（用于 aswath / bill_ackman / charlie_munger / michael_burry /
    mohnish_pabrai / phil_fisher / cathie_wood / rakesh / stanley）。

    关键修复（2026-07-24）：数据严重不全时直接返回 neutral 占位，不给虚假的 bearish 信号。
    """
    if not metrics:
        return {"signal": "neutral", "confidence": 0, "reasoning": "no data"}

    m = metrics

    # === 数据完整性检查 ===
    # 如果 ROE / gross_margin / revenue_growth 三个关键维度有 2+ 缺失，
    # 说明数据质量不足以支撑打分，直接给 neutral（不给虚假 bearish）
    key_missing = 0
    detail_parts = []
    for name, field, threshold in [
        ("ROE", "return_on_equity", 0.10),
        ("margin", "gross_margin", 0.3),
        ("growth", "revenue_growth", 0.10),
    ]:
        v = m.get(field)
        if v is None:
            key_missing += 1
            detail_parts.append(f"{name}=N/A")
        else:
            detail_parts.append(f"{name}={v:.1%}")

    if key_missing >= 2:
        return {
            "signal": "neutral",
            "confidence": 25,
            "reasoning": f"insufficient data ({', '.join(detail_parts)})"
        }

    # === 正常评分（max 9） ===
    score = 0

    # ROE
    if m.get("return_on_equity") and m["return_on_equity"] > 0.20: score += 3
    elif m.get("return_on_equity") and m["return_on_equity"] > 0.15: score += 2
    elif m.get("return_on_equity") and m["return_on_equity"] > 0.10: score += 1

    # gross margin
    if m.get("gross_margin") and m["gross_margin"] > 0.5: score += 2
    elif m.get("gross_margin") and m["gross_margin"] > 0.3: score += 1

    # revenue growth
    if m.get("revenue_growth") and m["revenue_growth"] > 0.20: score += 2
    elif m.get("revenue_growth") and m["revenue_growth"] > 0.10: score += 1

    # debt
    if m.get("debt_to_equity") is not None and m["debt_to_equity"] < 0.5: score += 1

    # PE
    if m.get("price_to_earnings_ratio") and 0 < m["price_to_earnings_ratio"] < 25: score += 1

    max_s = 9
    # bearish_thr 从 0.4 降到 0.3，避免 3/9 (0.33) 被误判为 bearish
    sig, conf = _signal(score, max_s, bullish_thr=0.6, bearish_thr=0.3)
    return {
        "signal": sig,
        "confidence": conf,
        "reasoning": f"{ticker}: {score}/{max_s} ({', '.join(detail_parts)})"[:120],
    }


# ---------------------------------------------------------------------------
# Risk Manager（仓位限额）
# ---------------------------------------------------------------------------

def risk_manager(ticker: str, prices: list[dict], portfolio: dict, all_prices: dict[str, list[dict]]) -> dict:
    if not prices:
        return {"remaining_position_limit": 0, "current_price": 0,
                "reasoning": {"error": "no price data"}}

    current_price = prices[-1]["close"]
    closes = [p["close"] for p in prices]
    if len(closes) < 30:
        annualized_vol = 0.25
        vol_pct = 100
    else:
        rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
        daily_vol = statistics.stdev(rets) if len(rets) > 1 else 0.025
        annualized_vol = daily_vol * math.sqrt(252)
        vol_pct = 50

    # volatility-adjusted limit
    if annualized_vol < 0.15:
        limit_pct = 0.25
    elif annualized_vol < 0.30:
        limit_pct = 0.20 - (annualized_vol - 0.15) * 0.33
    elif annualized_vol < 0.50:
        limit_pct = 0.15 - (annualized_vol - 0.30) * 0.25
    else:
        limit_pct = 0.10

    # 简化的相关性 multiplier（取与其他 ticker 平均）
    corr_multiplier = 1.0
    if len(all_prices) >= 2:
        other_rets = {}
        for t, ps in all_prices.items():
            if t == ticker or not ps: continue
            cls = [p["close"] for p in ps]
            if len(cls) < 30: continue
            other_rets[t] = [cls[i] / cls[i - 1] - 1 for i in range(1, len(cls))]
        # 与 ticker rets 求平均相关系数
        ticker_rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
        common = min(len(ticker_rets), min((len(r) for r in other_rets.values()), default=0))
        if common > 5 and other_rets:
            corrs = []
            for r in other_rets.values():
                if len(r) >= common:
                    a = ticker_rets[-common:]
                    b = r[-common:]
                    if statistics.stdev(a) > 0 and statistics.stdev(b) > 0:
                        corrs.append(_corr(a, b))
            if corrs:
                avg_corr = sum(corrs) / len(corrs)
                if avg_corr >= 0.8: corr_multiplier = 0.70
                elif avg_corr >= 0.6: corr_multiplier = 0.85
                elif avg_corr >= 0.4: corr_multiplier = 1.0
                elif avg_corr >= 0.2: corr_multiplier = 1.05
                else: corr_multiplier = 1.10

    combined_pct = limit_pct * corr_multiplier
    cash = portfolio.get("cash", 0)
    total_value = cash + sum(p.get("long", 0) * current_price for p in portfolio.get("positions", {}).values())

    position_limit = total_value * combined_pct
    current_pos_value = abs(portfolio.get("positions", {}).get(ticker, {}).get("long", 0)) * current_price
    remaining = max(position_limit - current_pos_value, 0)
    max_pos_size = min(remaining, cash)

    return {
        "remaining_position_limit": max_pos_size,
        "current_price": current_price,
        "volatility_metrics": {
            "annualized_volatility": annualized_vol,
            "daily_volatility": annualized_vol / math.sqrt(252),
            "volatility_percentile": vol_pct,
            "data_points": len(prices),
        },
        "correlation_multiplier": corr_multiplier,
        "reasoning": {
            "base_position_limit_pct": limit_pct,
            "combined_position_limit_pct": combined_pct,
            "position_limit": position_limit,
            "remaining_limit": remaining,
            "available_cash": cash,
        },
    }


# ---------------------------------------------------------------------------
# Portfolio Manager（聚合 signals → 决策）
# ---------------------------------------------------------------------------

def portfolio_manager(analyst_signals: dict, risk_data: dict, portfolio: dict) -> dict:
    """聚合所有 agent signals，结合 risk 限额，做出最终下单决策。

    策略：
      - bullish 占比 >= 60% → buy（用 max_qty 的 70%）
      - bearish 占比 >= 60% → sell（卖出现有 long 的 70%）或 short（如果有空间）
      - 否则 → hold
    """
    decisions = {}
    cash = portfolio.get("cash", 0)
    positions = portfolio.get("positions", {})
    margin_requirement = portfolio.get("margin_requirement", 0.5)
    margin_used = portfolio.get("margin_used", 0)

    for ticker in analyst_signals.get("_tickers", []):
        price = risk_data.get(ticker, {}).get("current_price", 0)
        remaining_limit = risk_data.get(ticker, {}).get("remaining_position_limit", 0)
        max_shares = int(remaining_limit // price) if price > 0 else 0

        pos = positions.get(ticker, {"long": 0, "short": 0})
        long_shares = pos.get("long", 0)

        # 聚合 signals
        sigs = []
        for agent_key, agent_signals in analyst_signals.items():
            if agent_key.startswith("_"): continue
            if isinstance(agent_signals, dict) and ticker in agent_signals:
                s = agent_signals[ticker]
                if isinstance(s, dict) and s.get("signal"):
                    sigs.append(s["signal"])

        if not sigs:
            decisions[ticker] = {"action": "hold", "quantity": 0, "confidence": 0,
                                "reasoning": "no analyst signals"}
            continue

        bullish = sigs.count("bullish")
        bearish = sigs.count("bearish")
        total = len(sigs)
        bullish_ratio = bullish / total
        bearish_ratio = bearish / total

        if bullish_ratio >= 0.6 and max_shares > 0:
            qty = max(1, int(max_shares * 0.7))
            decisions[ticker] = {
                "action": "buy",
                "quantity": qty,
                "confidence": round(bullish_ratio * 100),
                "reasoning": f"{bullish}/{total} bullish; risk allows {max_shares}",
            }
        elif bearish_ratio >= 0.6:
            if long_shares > 0:
                qty = max(1, int(long_shares * 0.7))
                decisions[ticker] = {
                    "action": "sell",
                    "quantity": qty,
                    "confidence": round(bearish_ratio * 100),
                    "reasoning": f"{bearish}/{total} bearish; close {qty}/{long_shares}",
                }
            elif max_shares > 0:
                # 检查 short 的保证金
                equity = cash
                available_margin = max(0, equity / margin_requirement - margin_used) if margin_requirement > 0 else 0
                max_short = int(min(max_shares, available_margin // price)) if price > 0 else 0
                if max_short > 0:
                    decisions[ticker] = {
                        "action": "short",
                        "quantity": max_short,
                        "confidence": round(bearish_ratio * 100),
                        "reasoning": f"{bearish}/{total} bearish; short {max_short}",
                    }
                else:
                    decisions[ticker] = {"action": "hold", "quantity": 0, "confidence": 0,
                                          "reasoning": "bearish but no margin"}
            else:
                decisions[ticker] = {"action": "hold", "quantity": 0, "confidence": 0,
                                      "reasoning": "bearish but no capacity"}
        else:
            decisions[ticker] = {"action": "hold", "quantity": 0, "confidence": round(50 - abs(bullish_ratio - bearish_ratio) * 50),
                                  "reasoning": f"mixed {bullish}B/{bearish}Be/{total - bullish - bearish}N"}

    return decisions


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _try_float(x: Any) -> float | None:
    if x is None or x == "" or x == "-": return None
    try: return float(str(x).replace(",", ""))
    except: return None


def _cagr(seq: list[float]) -> float | None:
    seq = [s for s in seq if s is not None and s > 0]
    if len(seq) < 2: return None
    years = len(seq) - 1
    return (seq[0] / seq[-1]) ** (1 / years) - 1


def _corr(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den_a = math.sqrt(sum((x - ma) ** 2 for x in a))
    den_b = math.sqrt(sum((y - mb) ** 2 for y in b))
    return num / (den_a * den_b) if den_a > 0 and den_b > 0 else 0


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="AI Hedge Fund (WorkBuddy edition)")
    p.add_argument("--ticker", required=True, help="逗号分隔 ticker 列表，如 AAPL,MSFT,600519.SH")
    p.add_argument("--analysts", default="", help="逗号分隔 analyst key（默认全部）")
    p.add_argument("--start", default=None, help="开始日期 YYYY-MM-DD（默认 3 个月前）")
    p.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD（默认今天）")
    p.add_argument("--initial-cash", type=float, default=1_000_000, help="初始现金")
    p.add_argument("--margin-requirement", type=float, default=0.5, help="保证金比例")
    p.add_argument("--show-reasoning", action="store_true", help="显示每个 agent 的推理")
    p.add_argument("--output", default=None, help="输出 JSON 文件路径")
    return p.parse_args()


def main():
    args = parse_args()
    tickers = [t.strip() for t in args.ticker.split(",") if t.strip()]
    selected = [a.strip() for a in args.analysts.split(",") if a.strip()] if args.analysts else DEFAULT_ANALYSTS
    # 兼容拼写（technicals_analyst → technical_analyst）
    selected = [s.replace("technicals_analyst", "technical_analyst") for s in selected]
    selected = [s for s in selected if s in ANALYSTS]  # 过滤掉不存在的
    end_date = args.end or datetime.now().strftime("%Y-%m-%d")
    start_date = args.start or (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")

    print(f"\n=== AI Hedge Fund ===")
    print(f"tickers:       {tickers}")
    print(f"analysts:      {len(selected)} selected ({', '.join(selected[:5])}...)")
    print(f"date range:    {start_date} ~ {end_date}")
    print(f"initial cash:  {args.initial_cash:,.0f}")
    print()

    portfolio = {
        "cash": args.initial_cash,
        "margin_requirement": args.margin_requirement,
        "margin_used": 0.0,
        "positions": {t: {"long": 0, "short": 0, "long_cost_basis": 0.0,
                          "short_cost_basis": 0.0, "short_margin_used": 0.0} for t in tickers},
        "realized_gains": {t: {"long": 0.0, "short": 0.0} for t in tickers},
    }

    # Step 1: 拉数据（并行缓存到 data_fetcher）
    print("Step 1: 拉行情 / 财务 / 新闻")
    prices_map: dict[str, list[dict]] = {}
    metrics_map: dict[str, list[dict]] = {}
    line_items_map: dict[str, list[dict]] = {}
    news_map: dict[str, list[dict]] = {}
    market_cap_map: dict[str, float] = {}

    for ticker in tickers:
        wt = ticker_to_westock(ticker)
        print(f"  {ticker} → {wt}", end=" ... ")
        prices_map[ticker] = get_prices(ticker, start_date, end_date)
        metrics_map[ticker] = get_financial_metrics(ticker, end_date, period="ttm", limit=8)
        line_items_map[ticker] = search_line_items(ticker, [
            "revenue", "net_income", "earnings_per_share", "book_value_per_share",
            "total_assets", "total_liabilities", "current_assets", "current_liabilities",
            "outstanding_shares", "free_cash_flow", "operating_income",
            "depreciation_and_amortization", "capital_expenditure", "working_capital",
            "cash_and_equivalents", "total_debt", "interest_expense", "ebit", "ebitda",
        ], end_date, period="ttm", limit=4)
        news_map[ticker] = get_company_news(ticker, end_date, limit=10)
        market_cap_map[ticker] = get_market_cap(ticker, end_date) or 0
        print(f"OK ({len(prices_map[ticker])} prices, {len(metrics_map[ticker])} metrics)")

    # Step 2: 跑 analyst agents
    print(f"\nStep 2: 跑 {len(selected)} analyst agents")
    analyst_signals: dict[str, dict] = {"_tickers": tickers}

    AGENT_FUNCS = {
        "warren_buffett": lambda t: warren_buffett_agent(t, _safe_metrics(metrics_map[t]),
                                                         line_items_map[t], market_cap_map[t]),
        "ben_graham": lambda t: ben_graham_agent(t, _safe_metrics(metrics_map[t]),
                                                  line_items_map[t], market_cap_map[t]),
        "peter_lynch": lambda t: peter_lynch_agent(t, _safe_metrics(metrics_map[t]),
                                                    line_items_map[t], market_cap_map[t],
                                                    news_map[t]),
        "nassim_taleb": lambda t: nassim_taleb_agent(t, _safe_metrics(metrics_map[t]),
                                                      line_items_map[t], market_cap_map[t],
                                                      prices_map[t]),
        "fundamentals_analyst": lambda t: fundamentals_agent(t, _safe_metrics(metrics_map[t])),
        "growth_analyst": lambda t: growth_agent(t, _safe_metrics(metrics_map[t]),
                                                  line_items_map[t]),
        "valuation_analyst": lambda t: valuation_agent(t, _safe_metrics(metrics_map[t]),
                                                        line_items_map[t], market_cap_map[t]),
        "news_sentiment_analyst": lambda t: news_sentiment_agent(t, news_map[t]),
        "sentiment_analyst": lambda t: sentiment_agent(t, {}),  # 先跑空，后面回填
        "technical_analyst": lambda t: technicals_agent(t, prices_map[t]),
    }

    # 通用 moat agent
    for key in ["aswath_damodaran", "bill_ackman", "cathie_wood", "charlie_munger",
                "michael_burry", "mohnish_pabrai", "phil_fisher", "rakesh_jhunjhunwala",
                "stanley_druckenmiller"]:
        AGENT_FUNCS[key] = lambda t: generic_moat_agent(t, _safe_metrics(metrics_map[t]))

    # 第一遍：除 sentiment_agent 外
    first_round_results = {}
    for agent_key in selected:
        if agent_key not in AGENT_FUNCS:
            print(f"  ⚠️ unknown analyst: {agent_key}")
            continue
        if agent_key == "sentiment_analyst":
            continue
        results = {}
        for ticker in tickers:
            try:
                results[ticker] = AGENT_FUNCS[agent_key](ticker)
            except Exception as e:
                results[ticker] = {"signal": "neutral", "confidence": 0,
                                    "reasoning": f"error: {str(e)[:80]}"}
        first_round_results[agent_key] = results
        analyst_signals[agent_key] = results
        print(f"  ✓ {agent_key}")

    # 第二遍：sentiment_agent 用其他 agent 的结果做反向
    if "sentiment_analyst" in selected:
        sent_results = {}
        for ticker in tickers:
            other_sigs = {a: r[ticker] for a, r in first_round_results.items() if ticker in r}
            sent_results[ticker] = sentiment_agent(ticker, other_sigs)
        analyst_signals["sentiment_analyst"] = sent_results
        print(f"  ✓ sentiment_analyst (contrarian)")

    # Step 3: Risk Manager
    print(f"\nStep 3: Risk Manager")
    risk_data = {}
    for ticker in tickers:
        risk_data[ticker] = risk_manager(ticker, prices_map[ticker], portfolio, prices_map)
        rd = risk_data[ticker]
        if "volatility_metrics" in rd:
            print(f"  {ticker}: price={rd['current_price']:.2f}, "
                  f"limit={rd['remaining_position_limit']:,.0f}, "
                  f"vol={rd['volatility_metrics']['annualized_volatility']:.1%}")
        else:
            print(f"  {ticker}: price={rd['current_price']:.2f}, limit={rd['remaining_position_limit']:,.0f} (no vol data)")
    analyst_signals["risk_management_agent"] = {t: rd for t, rd in risk_data.items()}

    # Step 4: Portfolio Manager
    print(f"\nStep 4: Portfolio Manager")
    decisions = portfolio_manager(analyst_signals, risk_data, portfolio)
    print(f"\n{'='*60}")
    print(f"FINAL TRADING DECISIONS")
    print(f"{'='*60}")
    for ticker, d in decisions.items():
        print(f"  {ticker:8} {d['action'].upper():5} × {d['quantity']:4} "
              f"(conf {d['confidence']:3}%)  {d['reasoning'][:60]}")

    # 输出
    output = {
        "run_time": datetime.now().isoformat(),
        "args": vars(args),
        "tickers": tickers,
        "selected_analysts": selected,
        "analyst_signals": {k: v for k, v in analyst_signals.items() if not k.startswith("_")},
        "risk_data": risk_data,
        "decisions": decisions,
    }
    out_path = args.output or f"results/run_{int(time.time())}.json"
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str),
                                encoding="utf-8")
    print(f"\n结果已保存到: {out_path}")
    return output


if __name__ == "__main__":
    main()